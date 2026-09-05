"""Measure a local end-to-end latency baseline over the evaluation questions."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from scripts.seed_sample_data import seed

ROOT = Path(__file__).resolve().parents[1]


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def main() -> None:
    cases = [
        json.loads(line)
        for line in (ROOT / "evals" / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    with tempfile.TemporaryDirectory(prefix="medops-perf-") as directory:
        settings = Settings(database_path=Path(directory) / "perf.db")
        kb_id, _ = seed(settings)
        durations: list[float] = []
        errors = 0
        with TestClient(create_app(settings)) as client:
            for case in cases:
                started = time.perf_counter()
                response = client.post(
                    "/answer",
                    headers={"X-Tenant-ID": "hospital-a", "X-Actor-ID": "baseline"},
                    json={"question": case["question"], "knowledge_base_id": kb_id},
                )
                durations.append((time.perf_counter() - started) * 1000)
                errors += int(response.status_code != 200)
    report = {
        "requests": len(durations),
        "p50_ms": round(percentile(durations, 0.50), 3),
        "p95_ms": round(percentile(durations, 0.95), 3),
        "max_ms": round(max(durations), 3),
        "error_rate": round(errors / len(durations), 4),
        "provider": "offline-extractive",
    }
    output = ROOT / "reports" / "generated" / "performance.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
