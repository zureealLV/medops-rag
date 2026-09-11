"""Offline concurrency benchmark for the MedOps FastAPI/SQLite request paths.

The benchmark intentionally never contacts a model provider.  The answer path uses
the real retrieval, LangGraph and persistence code, but replaces the synchronous
OpenAI-compatible HTTP call with a deterministic, configurable-delay substitute.

This is a closed-loop, in-process ASGI benchmark.  It is useful for finding local
contention and tail-latency trends; it is not a production capacity claim.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sqlite3
import statistics
import threading
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import httpx

# Make accidental provider use impossible even when the parent shell contains a
# real key.  The benchmark application receives an explicit non-secret sentinel
# and the only model URL accepted by the substitute is the reserved .invalid host.
for _secret_name in ("MODEL_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
    os.environ.pop(_secret_name, None)

from app.config import Settings  # noqa: E402
from app.db import initialize  # noqa: E402
from app.main import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TENANT_HEADERS = {
    "X-Tenant-ID": "concurrency-benchmark",
    "X-Actor-ID": "offline-load-generator",
}


def _percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * fraction))
    return ordered[index]


def _latency_summary(samples: list[float]) -> dict[str, float | int]:
    if not samples:
        raise ValueError("at least one latency sample is required")
    return {
        "count": len(samples),
        "mean_ms": round(statistics.fmean(samples), 3),
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(_percentile(samples, 0.95), 3),
        "p99_ms": round(_percentile(samples, 0.99), 3),
        "min_ms": round(min(samples), 3),
        "max_ms": round(max(samples), 3),
    }


def _offline_model_body() -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": (
                        "LIS 接口连续超时时，应检查接口网关、消息队列积压、连接池占用和最近配置变更。"
                    )
                }
            }
        ],
        "usage": {
            "prompt_tokens": 180,
            "completion_tokens": 32,
            "total_tokens": 212,
            "prompt_cache_hit_tokens": 0,
        },
    }


class OfflineModelSubstitute:
    """Thread-safe ``httpx.MockTransport`` handler used by the model adapter."""

    def __init__(self, delay_ms: float) -> None:
        self.delay_seconds = delay_ms / 1000
        self._calls = 0
        self._lock = threading.Lock()

    @property
    def calls(self) -> int:
        with self._lock:
            return self._calls

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if not str(request.url).startswith("https://offline-model.invalid/"):
            raise RuntimeError(f"network safety guard rejected model URL: {request.url}")
        time.sleep(self.delay_seconds)
        with self._lock:
            self._calls += 1
        return httpx.Response(200, request=request, json=_offline_model_body())


def _seed(database: Path, document_count: int) -> int:
    """Seed a large metadata list plus one strongly matching RAG chunk."""
    with sqlite3.connect(database) as connection:
        cursor = connection.execute(
            """INSERT INTO knowledge_bases(tenant_id,name,description)
               VALUES (?,?,?)""",
            (TENANT_HEADERS["X-Tenant-ID"], "Concurrency corpus", "offline benchmark"),
        )
        kb_id = int(cursor.lastrowid)
        documents = [
            (
                kb_id,
                TENANT_HEADERS["X-Tenant-ID"],
                f"Medical operations document {index:05d}",
                (
                    "LIS 接口连续超时时，先检查接口网关健康状态、消息队列积压、连接池占用和最近配置变更。"
                    if index == 0
                    else f"医疗知识库归档记录 {index:05d}，用于分页并发基准。"
                ),
                f"benchmark-{index:05d}.md",
            )
            for index in range(document_count)
        ]
        connection.executemany(
            """INSERT INTO documents
               (knowledge_base_id,tenant_id,title,content,source)
               VALUES (?,?,?,?,?)""",
            documents,
        )
        rows = connection.execute(
            "SELECT id,content FROM documents WHERE knowledge_base_id=? ORDER BY id",
            (kb_id,),
        ).fetchall()
        connection.executemany(
            """INSERT INTO chunks
               (document_id,knowledge_base_id,tenant_id,chunk_index,text,embedding_json)
               VALUES (?,?,?,?,?,?)""",
            [(row[0], kb_id, TENANT_HEADERS["X-Tenant-ID"], 0, row[1], "[]") for row in rows],
        )
    return kb_id


RequestFactory = Callable[[httpx.AsyncClient], Awaitable[httpx.Response]]


async def _load_once(
    client: httpx.AsyncClient,
    request_factory: RequestFactory,
    *,
    concurrency: int,
    request_count: int,
) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(concurrency)

    async def request_one(index: int) -> tuple[float, float | None, int, str | None]:
        async with semaphore:
            started = time.perf_counter()
            try:
                response = await request_factory(client)
                latency_ms = (time.perf_counter() - started) * 1000
                server_timing = response.headers.get("Server-Timing", "")
                server_ms = None
                if server_timing.startswith("app;dur="):
                    server_ms = float(server_timing.removeprefix("app;dur="))
                provider = response.headers.get("X-MedOps-Provider")
                return latency_ms, server_ms, response.status_code, provider
            except Exception as exc:  # keep load results inspectable instead of aborting early
                latency_ms = (time.perf_counter() - started) * 1000
                return latency_ms, None, 0, type(exc).__name__

    started = time.perf_counter()
    results = await asyncio.gather(*(request_one(index) for index in range(request_count)))
    wall_seconds = time.perf_counter() - started
    latencies = [item[0] for item in results]
    server_latencies = [item[1] for item in results if item[1] is not None]
    statuses = Counter(str(item[2]) for item in results)
    providers = Counter(item[3] for item in results if item[3])
    success_count = sum(1 for item in results if 200 <= item[2] < 300)
    return {
        "request_count": request_count,
        "concurrency": concurrency,
        "wall_seconds": round(wall_seconds, 3),
        "throughput_requests_per_second": round(request_count / wall_seconds, 3),
        "success_count": success_count,
        "error_count": request_count - success_count,
        "status_codes": dict(sorted(statuses.items())),
        "providers_or_exceptions": dict(sorted(providers.items())),
        "client_latency": _latency_summary(latencies),
        "server_latency": _latency_summary(server_latencies) if server_latencies else None,
    }


def _combine_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "repetitions": len(runs),
        "median_throughput_requests_per_second": round(
            statistics.median(run["throughput_requests_per_second"] for run in runs), 3
        ),
        "median_client_p95_ms": round(statistics.median(run["client_latency"]["p95_ms"] for run in runs), 3),
        "total_success_count": sum(run["success_count"] for run in runs),
        "total_error_count": sum(run["error_count"] for run in runs),
        "runs": runs,
    }


async def benchmark(
    *,
    concurrency_levels: list[int],
    requests_per_level: int,
    repetitions: int,
    document_count: int,
    model_delay_ms: float,
) -> dict[str, Any]:
    if not concurrency_levels or any(level < 1 or level > 256 for level in concurrency_levels):
        raise ValueError("concurrency levels must be between 1 and 256")
    if requests_per_level < max(concurrency_levels):
        raise ValueError("requests per level must be at least the largest concurrency level")
    if repetitions < 1 or repetitions > 10:
        raise ValueError("repetitions must be between 1 and 10")
    if document_count < 100 or document_count > 100_000:
        raise ValueError("document count must be between 100 and 100000")
    if model_delay_ms < 1 or model_delay_ms > 10_000:
        raise ValueError("model delay must be between 1 and 10000 ms")

    # SQLite/FTS file handles can be released a few milliseconds after AnyIO's
    # worker threads finish on Windows.  Ignoring a transient cleanup failure
    # keeps the benchmark result available without touching any project data.
    with TemporaryDirectory(prefix="medops-concurrency-", ignore_cleanup_errors=True) as directory:
        database = Path(directory) / "benchmark.db"
        initialize(database)
        kb_id = _seed(database, document_count)
        settings = Settings(
            database_path=database,
            app_env="benchmark",
            log_level="WARNING",
            auth_mode="trusted_headers",
            ocr_enabled=False,
            text_embedding_enabled=False,
            image_embedding_enabled=False,
            model_api_key="offline-benchmark-only",
            model_base_url="https://offline-model.invalid/v1",
            model_name="deterministic-delay-substitute",
            model_max_retries=0,
            # Keep this above the largest load level so this historical throughput
            # benchmark remains comparable. Dedicated tests cover overload behavior.
            model_max_concurrency=max(concurrency_levels),
            model_max_concurrency_per_tenant=max(concurrency_levels),
            model_max_queue_waiters=max(concurrency_levels),
            model_max_queue_waiters_per_tenant=max(concurrency_levels),
        )
        substitute = OfflineModelSubstitute(model_delay_ms)
        application = create_app(
            settings,
            model_transport=httpx.MockTransport(substitute),
        )
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://offline-benchmark.local",
                timeout=30,
                headers=TENANT_HEADERS,
            ) as client:
                scenarios: dict[str, RequestFactory] = {
                    "health_db_read": lambda current: current.get("/health"),
                    "document_page_read": lambda current: current.get(
                        f"/knowledge-bases/{kb_id}/documents/page?limit=50&offset=0"
                    ),
                    "answer_controlled_model": lambda current: current.post(
                        "/answer",
                        json={
                            "question": "LIS 接口连续超时时应检查哪些项目？",
                            "knowledge_base_id": kb_id,
                            "top_k": 5,
                            "retrieval_profile": "auto",
                            "text_strategy": "auto",
                            "orchestration": "langgraph",
                        },
                    ),
                }
                # Warm each route without recording it in the load samples.
                for factory in scenarios.values():
                    warmup = await factory(client)
                    if warmup.status_code != 200:
                        raise RuntimeError(f"warmup failed: {warmup.status_code} {warmup.text}")

                measured: dict[str, dict[str, Any]] = {}
                for scenario_name, factory in scenarios.items():
                    measured[scenario_name] = {}
                    for concurrency in concurrency_levels:
                        runs = [
                            await _load_once(
                                client,
                                factory,
                                concurrency=concurrency,
                                request_count=requests_per_level,
                            )
                            for _ in range(repetitions)
                        ]
                        measured[scenario_name][str(concurrency)] = _combine_runs(runs)
        expected_model_calls = 1 + requests_per_level * repetitions * len(concurrency_levels)
        if substitute.calls != expected_model_calls:
            raise RuntimeError(
                "controlled model path did not execute once per answer request: "
                f"expected {expected_model_calls}, observed {substitute.calls}"
            )
        with sqlite3.connect(database) as connection:
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
            busy_timeout_ms = int(connection.execute("PRAGMA busy_timeout").fetchone()[0])
            metric_rows = int(connection.execute("SELECT COUNT(*) FROM request_metrics").fetchone()[0])
        await asyncio.sleep(0.1)

    return {
        "schema_version": 1,
        "benchmark": "medops-v3-offline-concurrency",
        "generated_at": datetime.now().astimezone().isoformat(),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "processor_count": os.cpu_count(),
            "transport": "httpx.ASGITransport (in-process, no socket)",
            "application_processes": 1,
            "fastapi_endpoints": (
                "async /answer with SQLite, retrieval and checkpoint stages worker-offloaded; "
                "mixed sync/async supporting endpoints"
            ),
            "database": "temporary SQLite",
            "sqlite_journal_mode": journal_mode,
            "sqlite_connection_timeout_seconds": 10,
            "sqlite_observed_busy_timeout_ms": busy_timeout_ms,
            "request_metrics_write_enabled": True,
            "document_count": document_count,
            "chunks": document_count,
            "model_provider": "deterministic offline substitute",
            "model_delay_ms": model_delay_ms,
            "model_substitute_calls": substitute.calls,
            "real_api_key_loaded": False,
            "network_model_calls": 0,
            "requests_per_level_per_repetition": requests_per_level,
            "repetitions": repetitions,
            "concurrency_levels": concurrency_levels,
            "persisted_request_metric_rows": metric_rows,
        },
        "scenarios": measured,
        "limitations": [
            "Closed-loop load: each virtual user sends another request only after its prior "
            "request finishes.",
            "In-process ASGI transport excludes TCP, TLS, reverse-proxy and cross-process "
            "serialization cost.",
            "One application process is measured; this report does not claim multi-worker scaling.",
            "The controlled model has deterministic latency and no provider-side queueing, "
            "rate limits or network jitter.",
            "SQLite telemetry writes occur after every request, so even the read scenarios "
            "include one best-effort write.",
            "Results describe this host and seeded dataset only; production sizing needs "
            "deployment-specific load tests.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concurrency", default="1,4,16,32")
    parser.add_argument("--requests-per-level", type=int, default=64)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--documents", type=int, default=15_000)
    parser.add_argument("--model-delay-ms", type=float, default=75)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "concurrency-benchmark-v3.json",
    )
    args = parser.parse_args()
    levels = [int(value) for value in args.concurrency.split(",") if value.strip()]
    report = asyncio.run(
        benchmark(
            concurrency_levels=levels,
            requests_per_level=args.requests_per_level,
            repetitions=args.repetitions,
            document_count=args.documents,
            model_delay_ms=args.model_delay_ms,
        )
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
