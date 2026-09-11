"""Evaluate the installed Chinese corpus, citations, abstention and latency."""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import replace
from pathlib import Path

from app.config import Settings
from app.models.answers import AnswerRequest
from app.services.answers import answer
from app.services.knowledge_bases import list_all
from scripts.import_huatuo import KB_NAME

ROOT = Path(__file__).resolve().parents[1]


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[int((len(ordered) - 1) * fraction)] if ordered else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--tenant", default="hospital-a")
    parser.add_argument("--max-p95-ms", type=float, default=1_000)
    args = parser.parse_args()

    settings = Settings.from_env()
    if args.database:
        settings = replace(settings, database_path=args.database.resolve())
    kb = next(
        (item for item in list_all(settings.database_path, args.tenant) if item.name == KB_NAME),
        None,
    )
    if kb is None:
        raise SystemExit("Chinese corpus is missing; run python -m scripts.import_huatuo first")
    cases = [
        json.loads(line)
        for line in (ROOT / "evals/chinese_medical_cases.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line
    ]

    failures: list[dict[str, object]] = []
    latencies: list[float] = []
    positive_hits = abstention_hits = 0
    positives = sum(not item["expected_abstain"] for item in cases)
    negatives = len(cases) - positives
    for case in cases:
        result = answer(
            settings.database_path,
            settings,
            args.tenant,
            AnswerRequest(knowledge_base_id=kb.id, question=case["question"], top_k=5),
        )
        assert result is not None
        latencies.append(result.retrieval_ms)
        if case["expected_abstain"]:
            passed = result.abstained and result.reason == case["expected_reason"]
            abstention_hits += int(passed)
        else:
            sources = [item.source for item in result.citations]
            passed = (
                not result.abstained
                and case["expected_answer_contains"] in result.answer
                and any(case["expected_source_contains"] in source for source in sources)
            )
            positive_hits += int(passed)
        if not passed:
            failures.append(
                {
                    "id": case["id"],
                    "question": case["question"],
                    "answer": result.answer,
                    "reason": result.reason,
                    "sources": [item.source for item in result.citations],
                }
            )

    report = {
        "knowledge_base_id": kb.id,
        "cases": len(cases),
        "positive_cases": positives,
        "positive_answer_and_citation_accuracy": round(positive_hits / positives, 4),
        "negative_cases": negatives,
        "correct_abstention": round(abstention_hits / negatives, 4),
        "retrieval_median_ms": round(statistics.median(latencies), 3),
        "retrieval_p95_ms": round(_percentile(latencies, 0.95), 3),
        "max_p95_ms": args.max_p95_ms,
        "failures": failures,
    }
    output = ROOT / "reports/generated/chinese_corpus_evaluation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures or report["retrieval_p95_ms"] > args.max_p95_ms:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
