"""Regression tests for the offline concurrency benchmark contract."""

from __future__ import annotations

import asyncio

from evals.benchmark_concurrency_v3 import _latency_summary, benchmark


def test_latency_summary_reports_tail_percentiles() -> None:
    summary = _latency_summary([1.0, 2.0, 3.0, 4.0, 20.0])

    assert summary["count"] == 5
    assert summary["median_ms"] == 3.0
    assert summary["p95_ms"] == 20.0
    assert summary["p99_ms"] == 20.0


def test_benchmark_uses_only_controlled_offline_model() -> None:
    report = asyncio.run(
        benchmark(
            concurrency_levels=[1, 2],
            requests_per_level=2,
            repetitions=1,
            document_count=100,
            model_delay_ms=1,
        )
    )

    environment = report["environment"]
    assert environment["real_api_key_loaded"] is False
    assert environment["network_model_calls"] == 0
    assert environment["model_substitute_calls"] == 5  # four measured calls plus warmup
    for scenario in report["scenarios"].values():
        for result in scenario.values():
            assert result["total_success_count"] == 2
            assert result["total_error_count"] == 0
