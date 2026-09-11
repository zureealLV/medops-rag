"""Run a paid, counterbalanced DeepSeek benchmark on the official Chinese corpus.

The script never writes the API key.  It accepts either MODEL_API_KEY or
DEEPSEEK_API_KEY from the process environment or a user-supplied dotenv file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import time
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from app.agents.orchestration import orchestrate_answer
from app.config import Settings
from app.models.answers import AnswerRequest, AnswerResponse
from app.services.answers import answer
from app.services.knowledge_bases import list_all
from scripts.import_chinese_official import KB_NAME

ROOT = Path(__file__).resolve().parents[1]
MODES = ("classic", "langchain", "langgraph")
PRICE_SOURCE = "https://api-docs.deepseek.com/quick_start/pricing/"
# USD per one million tokens. A range is retained because DeepSeek publishes
# separate off-peak and peak prices.
DEEPSEEK_V4_FLASH_PRICES = {
    "off_peak": {"cache_hit_input": 0.007, "cache_miss_input": 0.22, "output": 0.66},
    "peak": {"cache_hit_input": 0.014, "cache_miss_input": 0.44, "output": 1.32},
}


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def _api_key(env_file: Path | None) -> str:
    values = dict(os.environ)
    if env_file is not None:
        if not env_file.is_file():
            raise SystemExit(f"Dotenv file not found: {env_file}")
        values.update(_read_dotenv(env_file))
    key = values.get("MODEL_API_KEY") or values.get("DEEPSEEK_API_KEY") or ""
    if not key:
        raise SystemExit("MODEL_API_KEY or DEEPSEEK_API_KEY is required for the live benchmark")
    return key


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def _normalize_answer(text: str) -> str:
    return re.sub(r"[\s*#_，。、；：,.!！?？()（）\[\]【】]+", "", text).replace("克", "g").lower()


def _answer_matches(expected: str, actual: str) -> bool:
    expected_normalized = _normalize_answer(expected)
    actual_normalized = _normalize_answer(actual)
    if expected_normalized in actual_normalized:
        return True
    terms = [
        _normalize_answer(term)
        for term in re.split(r"[、，,；;和]", expected)
        if _normalize_answer(term)
    ]
    return len(terms) > 1 and all(term in actual_normalized for term in terms)


def _passed(case: dict[str, Any], result: AnswerResponse) -> bool:
    if case["expected_abstain"]:
        return result.abstained and result.reason == case["expected_reason"]
    return (
        not result.abstained
        and _answer_matches(case["expected_answer_contains"], result.answer)
        and any(case["expected_source_contains"] in item.source for item in result.citations)
    )


def _cost(tokens: dict[str, int], price: dict[str, float]) -> float:
    prompt = tokens["prompt"]
    cached = min(prompt, tokens["cached_prompt"])
    cache_miss = prompt - cached
    return round(
        (
            cached * price["cache_hit_input"]
            + cache_miss * price["cache_miss_input"]
            + tokens["completion"] * price["output"]
        )
        / 1_000_000,
        8,
    )


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [float(row["latency_ms"]) for row in rows]
    retrieval = [float(row["retrieval_ms"]) for row in rows]
    model = [float(row["model_ms"]) for row in rows]
    answerable = [row for row in rows if not row["expected_abstain"]]
    abstainable = [row for row in rows if row["expected_abstain"]]
    tokens = {
        "total": sum(int(row["token_usage"]) for row in rows),
        "prompt": sum(int(row["prompt_tokens"]) for row in rows),
        "completion": sum(int(row["completion_tokens"]) for row in rows),
        "cached_prompt": sum(int(row["cached_prompt_tokens"]) for row in rows),
    }
    return {
        "runs": len(rows),
        "quality": {
            "case_accuracy": round(sum(bool(row["passed"]) for row in rows) / len(rows), 4),
            "retrieval_hit_at_5": round(
                sum(bool(row["retrieval_hit"]) for row in answerable) / len(answerable), 4
            ),
            "citation_correctness": round(
                sum(bool(row["citation_hit"]) for row in answerable) / len(answerable), 4
            ),
            "answer_content_match_accuracy": round(
                sum(bool(row["answer_match"]) for row in answerable) / len(answerable), 4
            ),
            "correct_abstention": round(
                sum(bool(row["passed"]) for row in abstainable) / len(abstainable), 4
            ),
            "live_provider_success": round(
                sum(row["provider"] == "openai-compatible" for row in answerable)
                / len(answerable),
                4,
            ),
        },
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 3),
            "median": round(statistics.median(latencies), 3),
            "p95": round(_percentile(latencies, 0.95), 3),
            "retrieval_mean": round(statistics.fmean(retrieval), 3),
            "model_mean": round(statistics.fmean(model), 3),
        },
        "tokens": tokens,
        "estimated_cost_usd": {
            period: _cost(tokens, price)
            for period, price in DEEPSEEK_V4_FLASH_PRICES.items()
        },
        "providers": dict(Counter(str(row["provider"]) for row in rows)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--database", type=Path, default=ROOT / "data/runtime/medops.db")
    parser.add_argument("--tenant", default="hospital-a")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports/deepseek-live-benchmark-v3.json",
    )
    args = parser.parse_args()
    if args.repetitions < 1:
        raise SystemExit("--repetitions must be >= 1")

    settings = replace(
        Settings.from_env(),
        database_path=args.database.resolve(),
        model_api_key=_api_key(args.env_file),
        model_base_url="https://api.deepseek.com",
        model_name="deepseek-v4-flash",
    )
    kb = next(
        (item for item in list_all(settings.database_path, args.tenant) if item.name == KB_NAME),
        None,
    )
    if kb is None:
        raise SystemExit("Official Chinese corpus is missing; run the official importer first")
    cases = [
        json.loads(line)
        for line in (ROOT / "evals/chinese_official_cases.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]

    rows_by_mode: dict[str, list[dict[str, Any]]] = {mode: [] for mode in MODES}
    samples: list[dict[str, Any]] = []
    for repetition in range(args.repetitions):
        for case_index, case in enumerate(cases):
            # Rotate execution position so HTTP connection/cache effects do not
            # consistently favour one orchestration framework.
            offset = (case_index + repetition) % len(MODES)
            ordered_modes = MODES[offset:] + MODES[:offset]
            for mode in ordered_modes:
                request = AnswerRequest(
                    question=case["question"],
                    knowledge_base_id=kb.id,
                    top_k=5,
                    orchestration=mode,
                )
                started = time.perf_counter()
                result = orchestrate_answer(
                    mode,
                    request,
                    lambda request=request: answer(
                        settings.database_path,
                        settings,
                        args.tenant,
                        request,
                    ),
                )
                latency_ms = (time.perf_counter() - started) * 1000
                if result is None:
                    raise RuntimeError(f"Knowledge base disappeared while running {case['id']}")
                expected_source = case.get("expected_source_contains", "")
                expected_answer = case.get("expected_answer_contains", "")
                row = {
                    "case_id": case["id"],
                    "repetition": repetition + 1,
                    "expected_abstain": case["expected_abstain"],
                    "passed": _passed(case, result),
                    "retrieval_hit": bool(
                        expected_source
                        and any(expected_source in item.source for item in result.retrieved_chunks[:5])
                    ),
                    "citation_hit": bool(
                        expected_source
                        and any(expected_source in item.source for item in result.citations)
                    ),
                    "answer_match": bool(
                        expected_answer and _answer_matches(expected_answer, result.answer)
                    ),
                    "abstained": result.abstained,
                    "reason": result.reason,
                    "provider": result.provider,
                    "latency_ms": round(latency_ms, 3),
                    "retrieval_ms": result.retrieval_ms,
                    "model_ms": result.model_ms,
                    "token_usage": result.token_usage,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    "cached_prompt_tokens": result.cached_prompt_tokens,
                }
                rows_by_mode[mode].append(row)
                if repetition == 0:
                    samples.append(
                        {
                            "mode": mode,
                            "case_id": case["id"],
                            "answer": result.answer,
                            "citations": [item.source for item in result.citations],
                            **row,
                        }
                    )

    report = {
        "benchmark": "medops-deepseek-live-v3",
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "provider": {
            "base_url": settings.model_base_url,
            "model": settings.model_name,
            "live_api": True,
            "api_key_recorded": False,
        },
        "controlled_variables": {
            "dataset": "evals/chinese_official_cases.jsonl",
            "knowledge_base": KB_NAME,
            "cases": len(cases),
            "repetitions": args.repetitions,
            "counterbalanced_mode_order": True,
            "retriever_prompt_model_and_thresholds_identical": True,
        },
        "versions": {
            "medops-rag": version("medops-rag"),
            "langchain": version("langchain"),
            "langgraph": version("langgraph"),
        },
        "pricing_snapshot": {
            "currency": "USD",
            "unit": "per_1m_tokens",
            "source": PRICE_SOURCE,
            "rates": DEEPSEEK_V4_FLASH_PRICES,
            "note": (
                "Cost is a peak/off-peak range based on reported cache-hit, "
                "prompt and completion tokens."
            ),
        },
        "results": {mode: _summarize(rows) for mode, rows in rows_by_mode.items()},
        "samples": samples,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {key: value for key, value in report.items() if key != "samples"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    failures = [row for rows in rows_by_mode.values() for row in rows if not row["passed"]]
    if failures:
        print(f"Live benchmark completed with {len(failures)} failed samples; inspect {args.output}")


if __name__ == "__main__":
    main()
