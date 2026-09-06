"""Compare legacy fixed chunks with structure-aware child retrieval + parent reconstruction."""

from __future__ import annotations

import json
import statistics
import tempfile
from datetime import datetime
from pathlib import Path

from app.config import Settings
from app.db import initialize
from app.models.documents import DocumentCreate
from app.models.knowledge_bases import KnowledgeBaseCreate
from app.models.retrieval import SearchRequest
from app.services import documents, knowledge_bases
from app.services.retrieval import search

TENANT = "benchmark-tenant"
CASES = 50


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def run() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="medops-parent-child-") as directory:
        path = Path(directory) / "benchmark.db"
        settings = Settings(database_path=path)
        initialize(path)
        kb = knowledge_bases.create(
            path, TENANT, KnowledgeBaseCreate(name="Parent-child benchmark")
        )
        expected: dict[str, tuple[int, str]] = {}
        filler = "General maintenance telemetry remains stable and no restart is authorized. " * 13
        for index in range(CASES):
            marker = f"CASE-{index:03d}-ZX"
            action = f"ACTION-{index:03d}: rotate only the synthetic gateway certificate."
            content = (
                f"Alert marker {marker} was recorded. "
                + filler
                + "After checking the full section, the linked instruction is: "
                + action
            )
            document = documents.create(
                path,
                settings,
                TENANT,
                kb.id,
                DocumentCreate(title=marker, source=f"runbook-{index:03d}.md", content=content),
            )
            assert document is not None
            expected[marker] = (document.id, action)

        output: dict[str, object] = {}
        for strategy in ("bm25", "parent_child"):
            latencies: list[float] = []
            document_hits = 0
            action_context_hits = 0
            context_lengths: list[int] = []
            for marker, (document_id, action) in expected.items():
                result = search(
                    path,
                    TENANT,
                    SearchRequest(
                        query=f"What instruction belongs to {marker}?",
                        knowledge_base_id=kb.id,
                        top_k=1,
                        strategy=strategy,
                    ),
                )
                assert result is not None and result.results
                top = result.results[0]
                latencies.append(result.retrieval_ms)
                document_hits += int(top.document_id == document_id)
                action_context_hits += int(action in top.text)
                context_lengths.append(len(top.text))
            output[strategy] = {
                "hit_at_1": round(document_hits / CASES, 4),
                "linked_action_in_returned_context": round(action_context_hits / CASES, 4),
                "mean_context_chars": round(statistics.fmean(context_lengths), 1),
                "query_mean_ms": round(statistics.fmean(latencies), 3),
                "query_p95_ms": round(percentile(latencies, 0.95), 3),
            }

        return {
            "benchmark": "parent-child-context-v1",
            "generated_at": datetime.now().astimezone().isoformat(),
            "documents": CASES,
            "questions": CASES,
            "fixture": "unique alert near section start; linked action beyond legacy 600-char chunk",
            "profiles": output,
            "decision": (
                "Parent-child is opt-in: it improves context completeness on this fixture, while BM25 "
                "remains the measured child scorer until a real dense model wins a held-out benchmark."
            ),
            "limitations": [
                "Synthetic lexical markers make document retrieval easy for both strategies.",
                "This measures context reconstruction, not answer generation quality.",
                "SQLite exact scoring and 50 documents do not establish a production scale choice.",
            ],
        }


if __name__ == "__main__":
    report = run()
    destination = Path("reports/parent-child-benchmark-v2-beta1.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
