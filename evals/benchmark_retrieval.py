"""Compare retrieval strategies on the versioned synthetic evaluation set."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.models.retrieval import SearchRequest
from app.services.retrieval import search
from scripts.seed_sample_data import seed

ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ("keyword", "vector", "weighted", "bm25", "rrf")


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def evaluate_strategy(
    database_path: Path, kb_id: int, cases: list[dict[str, object]], strategy: str
) -> dict[str, float | int | str]:
    reciprocal_ranks: list[float] = []
    latencies: list[float] = []
    hit_1 = hit_3 = hit_5 = 0
    for case in cases:
        started = time.perf_counter()
        response = search(
            database_path,
            "hospital-a",
            SearchRequest(
                query=str(case["question"]),
                knowledge_base_id=kb_id,
                top_k=5,
                strategy=strategy,
            ),
        )
        latencies.append((time.perf_counter() - started) * 1000)
        assert response is not None
        sources = [item.source for item in response.results]
        expected = str(case["expected_source"])
        rank = next((index for index, source in enumerate(sources, start=1) if source == expected), None)
        hit_1 += int(rank == 1)
        hit_3 += int(rank is not None and rank <= 3)
        hit_5 += int(rank is not None and rank <= 5)
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
    count = len(cases)
    return {
        "strategy": strategy,
        "cases": count,
        "hit_at_1": round(hit_1 / count, 4),
        "hit_at_3": round(hit_3 / count, 4),
        "hit_at_5": round(hit_5 / count, 4),
        "mrr_at_5": round(statistics.fmean(reciprocal_ranks), 4),
        "latency_mean_ms": round(statistics.fmean(latencies), 3),
        "latency_p95_ms": round(percentile(latencies, 0.95), 3),
    }


def run() -> dict[str, object]:
    cases = [
        json.loads(line)
        for line in (ROOT / "evals" / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line and not json.loads(line)["expected_abstain"]
    ]
    with tempfile.TemporaryDirectory(prefix="medops-retrieval-benchmark-") as directory:
        settings = Settings(database_path=Path(directory) / "benchmark.db")
        kb_id, _ = seed(settings)
        results = [
            evaluate_strategy(settings.database_path, kb_id, cases, strategy)
            for strategy in STRATEGIES
        ]
    return {
        "benchmark": "synthetic-operations-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "corpus_documents": 6,
        "answerable_cases": len(cases),
        "embedding": "deterministic-hashing-256d",
        "notes": [
            "Hit@5 is weak on a six-document corpus; Hit@1 and MRR@5 are the primary diagnostics.",
            "These results compare orchestration only and do not represent a production embedding model.",
        ],
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run()
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
