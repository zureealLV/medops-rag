"""Compare the local SQLite lease queue with a real Redis/Celery worker."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * fraction))]


def _metrics(publish_ms: list[float], elapsed: float, tasks: int) -> dict[str, float]:
    return {
        "tasks": tasks,
        "publish_p50_ms": round(statistics.median(publish_ms), 3),
        "publish_p95_ms": round(_percentile(publish_ms, 0.95), 3),
        "end_to_end_seconds": round(elapsed, 3),
        "end_to_end_tasks_per_second": round(tasks / elapsed, 3),
    }


def _median_metrics(runs: list[dict[str, float]]) -> dict[str, float]:
    keys = ("publish_p50_ms", "publish_p95_ms", "end_to_end_seconds", "end_to_end_tasks_per_second")
    return {key: round(statistics.median(run[key] for run in runs), 3) for key in keys}


def benchmark_sqlite(tasks: int) -> dict[str, float]:
    with tempfile.TemporaryDirectory(prefix="medops-queue-") as directory:
        path = Path(directory) / "jobs.db"
        connection = sqlite3.connect(path)
        connection.executescript(
            """PRAGMA journal_mode=WAL;
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                payload INTEGER NOT NULL,
                lease_owner TEXT,
                lease_expires_at REAL
            );
            CREATE INDEX idx_jobs_claim ON jobs(state,id);"""
        )
        connection.close()
        started = time.perf_counter()
        publish_ms: list[float] = []
        for value in range(tasks):
            before = time.perf_counter()
            with sqlite3.connect(path) as connection:
                connection.execute("INSERT INTO jobs(state,payload) VALUES ('queued',?)", (value,))
            publish_ms.append((time.perf_counter() - before) * 1000)
        for _ in range(tasks):
            with sqlite3.connect(path, timeout=10) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT id FROM jobs WHERE state='queued' ORDER BY id LIMIT 1"
                ).fetchone()
                if row is None:
                    raise RuntimeError("SQLite queue drained before all tasks were claimed")
                connection.execute(
                    """UPDATE jobs SET state='running',lease_owner='benchmark',lease_expires_at=?
                       WHERE id=? AND state='queued'""",
                    (time.time() + 60, row[0]),
                )
                connection.execute(
                    "UPDATE jobs SET state='succeeded',lease_owner=NULL,lease_expires_at=NULL WHERE id=?",
                    (row[0],),
                )
        elapsed = time.perf_counter() - started
    return _metrics(publish_ms, elapsed, tasks)


def _wait_for_worker(app, deadline_seconds: float = 30.0) -> None:
    deadline = time.time() + deadline_seconds
    while time.time() < deadline:
        if app.control.ping(timeout=1):
            return
        time.sleep(0.25)
    raise RuntimeError("Celery benchmark worker did not become ready")


def benchmark_celery(tasks: int, redis_url: str) -> dict[str, float]:
    os.environ["BENCHMARK_REDIS_URL"] = redis_url
    from celery_benchmark_app import app

    app.control.purge()
    environment = os.environ.copy()
    environment["BENCHMARK_REDIS_URL"] = redis_url
    command = [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "evals.celery_benchmark_app:app",
        "worker",
        "--pool=solo",
        "--concurrency=1",
        "--loglevel=WARNING",
        "--without-gossip",
        "--without-mingle",
    ]
    worker = subprocess.Popen(
        command,
        cwd=Path(__file__).parents[1],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_worker(app)
        warmup = app.send_task("medops.benchmark.noop", args=[-1])
        assert warmup.get(timeout=10) == -1
        started = time.perf_counter()
        publish_ms: list[float] = []
        results = []
        for value in range(tasks):
            before = time.perf_counter()
            results.append(app.send_task("medops.benchmark.noop", args=[value]))
            publish_ms.append((time.perf_counter() - before) * 1000)
        for value, result in enumerate(results):
            if result.get(timeout=60) != value:
                raise RuntimeError("Celery result did not match its task payload")
        elapsed = time.perf_counter() - started
        return _metrics(publish_ms, elapsed, tasks)
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=10)
        except subprocess.TimeoutExpired:
            worker.kill()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=int, default=500)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--redis-url", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 10 <= args.tasks <= 10_000:
        raise SystemExit("--tasks must be between 10 and 10000")
    if not 1 <= args.repetitions <= 10:
        raise SystemExit("--repetitions must be between 1 and 10")
    sqlite_runs = [benchmark_sqlite(args.tasks) for _ in range(args.repetitions)]
    celery_runs = [
        benchmark_celery(args.tasks, args.redis_url) for _ in range(args.repetitions)
    ]
    import celery
    import redis

    redis_client = redis.Redis.from_url(args.redis_url)
    report = {
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "celery_pool": "solo",
            "celery_version": celery.__version__,
            "redis_server_version": redis_client.info("server")["redis_version"],
            "redis_py_version": redis.__version__,
            "worker_concurrency": 1,
            "payload": "integer no-op",
            "repetitions": args.repetitions,
        },
        "sqlite": {"median": _median_metrics(sqlite_runs), "runs": sqlite_runs},
        "redis_celery": {"median": _median_metrics(celery_runs), "runs": celery_runs},
    }
    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
