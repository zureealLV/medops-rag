"""Profile the hardened V2 upload, parse/index, search, rerank and answer path."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient
from fastembed.rerank.cross_encoder.text_cross_encoder import TextCrossEncoder

from app.config import Settings
from app.db import initialize, transaction
from app.main import create_app
from app.repositories.api_credentials import create_credential
from app.services.ingestion_jobs import process_next

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ROOT / "evals" / "v2_retrieval_documents.jsonl"
CASES = ROOT / "evals" / "v2_retrieval_cases.jsonl"
RERANKER = "BAAI/bge-reranker-base"


def _summary(samples: list[float]) -> dict[str, object]:
    ordered = sorted(samples)
    p95_index = min(len(ordered) - 1, round((len(ordered) - 1) * 0.95))
    return {
        "count": len(samples),
        "mean_ms": round(statistics.fmean(samples), 3),
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(ordered[p95_index], 3),
        "min_ms": round(ordered[0], 3),
        "max_ms": round(ordered[-1], 3),
        "samples_ms": [round(value, 3) for value in samples],
    }


def run(answer_cases: int = 30, rerank_cases: int = 20) -> dict[str, object]:
    documents = [json.loads(line) for line in DOCUMENTS.read_text(encoding="utf-8").splitlines()]
    all_cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines()]
    answerable = [case for case in all_cases if not case["expected_abstain"]]
    if answer_cases < 1 or rerank_cases < 1:
        raise ValueError("case counts must be positive")

    with tempfile.TemporaryDirectory(prefix="medops-v2-profile-") as directory:
        database = Path(directory) / "profile.db"
        settings = Settings(database_path=database, auth_mode="api_key", ocr_enabled=False)
        initialize(database)
        _, token = create_credential(
            database,
            tenant_id="hospital-a",
            name="benchmark-admin",
            role="admin",
        )
        headers = {"Authorization": f"Bearer {token}"}
        upload_samples: list[float] = []
        worker_samples: list[float] = []
        search_samples: list[float] = []
        answer_samples: list[float] = []
        providers: Counter[str] = Counter()
        abstained = 0

        with TestClient(create_app(settings)) as client:
            created = client.post(
                "/knowledge-bases",
                headers=headers,
                json={"name": "Performance corpus"},
            )
            assert created.status_code == 201, created.text
            kb_id = created.json()["id"]

            for index, document in enumerate(documents):
                started = time.perf_counter()
                response = client.post(
                    f"/knowledge-bases/{kb_id}/ingestion-jobs",
                    headers={**headers, "Idempotency-Key": f"profile-upload-{index:04d}"},
                    files={
                        "file": (
                            document["source"],
                            document["text"].encode("utf-8"),
                            "text/markdown",
                        )
                    },
                )
                upload_samples.append((time.perf_counter() - started) * 1000)
                assert response.status_code == 202, response.text

            for index in range(len(documents)):
                started = time.perf_counter()
                processed = process_next(database, settings, f"profile-worker-{index}")
                worker_samples.append((time.perf_counter() - started) * 1000)
                assert processed is not None

            for case in answerable:
                started = time.perf_counter()
                response = client.post(
                    "/search",
                    headers=headers,
                    json={
                        "query": case["question"],
                        "knowledge_base_id": kb_id,
                        "top_k": 5,
                        "strategy": "auto",
                    },
                )
                search_samples.append((time.perf_counter() - started) * 1000)
                assert response.status_code == 200, response.text

            for case in answerable[: min(answer_cases, len(answerable))]:
                started = time.perf_counter()
                response = client.post(
                    "/answer",
                    headers=headers,
                    json={
                        "question": case["question"],
                        "knowledge_base_id": kb_id,
                        "top_k": 5,
                    },
                )
                answer_samples.append((time.perf_counter() - started) * 1000)
                assert response.status_code == 200, response.text
                body = response.json()
                providers[body["provider"]] += 1
                abstained += int(body["abstained"])

        with transaction(database) as connection:
            rows = connection.execute(
                """SELECT stage,duration_ms FROM pipeline_metrics
                   WHERE tenant_id='hospital-a' AND pipeline='ingestion' ORDER BY id"""
            ).fetchall()
        parse_samples = [float(row["duration_ms"]) for row in rows if row["stage"] == "parse_ocr"]
        index_samples = [float(row["duration_ms"]) for row in rows if row["stage"] == "persist_index"]

        load_started = time.perf_counter()
        reranker = TextCrossEncoder(
            model_name=RERANKER,
            cache_dir=str(ROOT / "data" / "models" / "fastembed"),
        )
        reranker_load_ms = (time.perf_counter() - load_started) * 1000
        texts = [str(document["text"]) for document in documents[:10]]
        rerank_samples: list[float] = []
        for case in answerable[: min(rerank_cases, len(answerable))]:
            started = time.perf_counter()
            scores = list(reranker.rerank(str(case["question"]), texts))
            rerank_samples.append((time.perf_counter() - started) * 1000)
            assert len(scores) == len(texts)

    return {
        "benchmark": "medops-v2-hardened-local-performance-v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "auth_mode": "api_key",
            "database": "SQLite",
            "text_embedding_enabled": False,
            "ocr_enabled": False,
            "model_files_cached": True,
        },
        "dataset": {
            "documents": len(documents),
            "search_cases": len(answerable),
            "answer_cases": len(answer_samples),
            "rerank_cases": len(rerank_samples),
            "documents_sha256": hashlib.sha256(DOCUMENTS.read_bytes()).hexdigest(),
            "cases_sha256": hashlib.sha256(CASES.read_bytes()).hexdigest(),
        },
        "stages": {
            "upload_accept_api": _summary(upload_samples),
            "worker_total_parse_index": _summary(worker_samples),
            "parse_ocr": _summary(parse_samples),
            "persist_index": _summary(index_samples),
            "search_api_auto_bm25": _summary(search_samples),
            "rerank_bge_top10": _summary(rerank_samples),
            "answer_api_offline": _summary(answer_samples),
        },
        "reranker": {"model": RERANKER, "load_ms": round(reranker_load_ms, 3)},
        "answers": {"providers": dict(sorted(providers.items())), "abstained": abstained},
        "limitations": [
            "One Windows 10 host, one process and a temporary SQLite database; "
            "not a concurrency capacity test.",
            "Upload-accept includes HTTP multipart parsing, scrypt API-key verification "
            "and queue persistence.",
            "OCR and remote generation are disabled; dedicated OCR benchmarks are reported separately.",
            "BGE receives ten fixed candidate documents; retrieval quality is evaluated "
            "by the frozen Beta.1 report.",
            "Cached model load excludes network download time.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answer-cases", type=int, default=30)
    parser.add_argument("--rerank-cases", type=int, default=20)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "v2-performance-profile.json")
    args = parser.parse_args()
    report = run(args.answer_cases, args.rerank_cases)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
