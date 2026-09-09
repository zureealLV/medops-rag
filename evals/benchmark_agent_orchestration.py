"""Benchmark classic Python, LangChain LCEL, and LangGraph on one frozen RAG corpus."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

from app.agents.orchestration import orchestrate_answer
from app.config import Settings
from app.models.answers import AnswerRequest
from app.services.answers import answer
from scripts.seed_sample_data import seed

ROOT = Path(__file__).resolve().parents[1]
MODES = ("classic", "langchain", "langgraph")


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


def _evaluate_mode(
    mode: str,
    cases: list[dict[str, Any]],
    repetitions: int,
    settings: Settings,
    kb_id: int,
) -> tuple[dict[str, Any], list[tuple[Any, ...]]]:
    timings: list[float] = []
    retrieval_hits = 0
    citation_hits = 0
    abstention_hits = 0
    answerable = sum(not case["expected_abstain"] for case in cases)
    abstainable = len(cases) - answerable
    signatures: list[tuple[Any, ...]] = []

    for repetition in range(repetitions):
        for case in cases:
            request = AnswerRequest(
                question=case["question"],
                knowledge_base_id=kb_id,
                orchestration=mode,
            )
            started = time.perf_counter()
            result = orchestrate_answer(
                mode,
                request,
                lambda request=request: answer(
                    settings.database_path,
                    settings,
                    "hospital-a",
                    request,
                ),
            )
            timings.append((time.perf_counter() - started) * 1000)
            assert result is not None
            sources = [item.source for item in result.retrieved_chunks[:5]]
            citations = [item.source for item in result.citations]
            if repetition == 0:
                if case["expected_abstain"]:
                    abstention_hits += int(result.abstained)
                else:
                    retrieval_hits += int(case["expected_source"] in sources)
                    citation_hits += int(case["expected_source"] in citations and not result.abstained)
                signatures.append(
                    (
                        result.answer,
                        result.abstained,
                        result.reason,
                        tuple(citations),
                    )
                )

    return (
        {
            "runs": len(timings),
            "quality": {
                "retrieval_hit_at_5": round(retrieval_hits / answerable, 4),
                "citation_correctness": round(citation_hits / answerable, 4),
                "correct_abstention": round(abstention_hits / abstainable, 4),
            },
            "latency_ms": {
                "mean": round(statistics.fmean(timings), 3),
                "median": round(statistics.median(timings), 3),
                "p95": round(_percentile(timings, 0.95), 3),
                "min": round(min(timings), 3),
                "max": round(max(timings), 3),
            },
        },
        signatures,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "agent-orchestration-benchmark-v3.json",
    )
    args = parser.parse_args()
    if args.repetitions < 1:
        raise SystemExit("--repetitions must be >= 1")

    cases = [
        json.loads(line)
        for line in (ROOT / "evals" / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    with tempfile.TemporaryDirectory(prefix="medops-agent-benchmark-") as directory:
        settings = Settings(database_path=Path(directory) / "benchmark.db")
        kb_id, _ = seed(settings)
        results: dict[str, Any] = {}
        signatures: dict[str, list[tuple[Any, ...]]] = {}
        for mode in MODES:
            results[mode], signatures[mode] = _evaluate_mode(
                mode,
                cases,
                args.repetitions,
                settings,
                kb_id,
            )

    baseline = signatures["classic"]
    for mode in MODES:
        results[mode]["exact_output_parity_with_classic"] = round(
            sum(left == right for left, right in zip(baseline, signatures[mode], strict=True))
            / len(baseline),
            4,
        )
        base_mean = results["classic"]["latency_ms"]["mean"]
        results[mode]["mean_overhead_vs_classic_ms"] = round(
            results[mode]["latency_ms"]["mean"] - base_mean,
            3,
        )

    report = {
        "benchmark": "medops-agent-orchestration-v3",
        "provider": "offline-extractive",
        "controlled_variables": {
            "dataset": "evals/dataset.jsonl",
            "cases": len(cases),
            "repetitions": args.repetitions,
            "retriever_prompt_and_model_are_identical": True,
        },
        "versions": {
            "medops-rag": version("medops-rag"),
            "langchain": version("langchain"),
            "langgraph": version("langgraph"),
        },
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
