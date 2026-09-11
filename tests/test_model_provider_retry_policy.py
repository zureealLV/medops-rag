"""End-to-end deadline and bounded retry-policy tests."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest

from app.agents.model import (
    ModelProvider,
    ModelProviderDeadlineExceededError,
    _parse_retry_after_seconds,
    generate_detailed,
    generate_detailed_async,
)
from app.config import Settings
from app.models.retrieval import Evidence


def _evidence() -> list[Evidence]:
    return [
        Evidence(
            score=1.0,
            keyword_score=1.0,
            vector_score=0.0,
            source="runbook.md",
            document_id=1,
            chunk_id=1,
            chunk_index=0,
            text="LIS 接口超时先检查网关健康状态和消息队列积压。",
        )
    ]


def _success(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        request=request,
        json={"choices": [{"message": {"content": "先检查网关。 [source:1]"}}]},
    )


def test_end_to_end_deadline_expires_while_waiting_for_attempt_slot(tmp_path: Path) -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked(request: httpx.Request) -> httpx.Response:
            entered.set()
            await release.wait()
            return _success(request)

        settings = Settings(
            database_path=tmp_path / "unused.db",
            model_api_key="test",
            model_request_deadline_seconds=0.02,
            model_queue_timeout_seconds=1,
            model_max_concurrency=1,
            model_max_concurrency_per_tenant=1,
            model_max_queue_waiters=1,
            model_max_queue_waiters_per_tenant=1,
            model_max_retries=0,
        )
        runtime = ModelProvider(settings, async_transport=httpx.MockTransport(blocked))
        await runtime.start()
        first = asyncio.create_task(
            generate_detailed_async(
                "LIS 超时检查什么？",
                _evidence(),
                replace(settings, model_request_deadline_seconds=1),
                tenant_id="hospital-a",
                provider=runtime,
            )
        )
        await entered.wait()
        with pytest.raises(ModelProviderDeadlineExceededError) as caught:
            await generate_detailed_async(
                "LIS 超时检查什么？",
                _evidence(),
                settings,
                tenant_id="hospital-b",
                provider=runtime,
            )
        assert caught.value.phase == "queue"
        assert caught.value.deadline_seconds == 0.02
        release.set()
        assert (await first).provider == "openai-compatible"
        snapshot = await runtime.async_capacity_snapshot()
        assert snapshot["waiting"] == 0
        assert snapshot["outstanding"] == 0
        await runtime.aclose()

    asyncio.run(scenario())


def test_end_to_end_deadline_cancels_http_and_releases_permits(tmp_path: Path) -> None:
    async def scenario() -> None:
        entered = asyncio.Event()

        async def blocked(request: httpx.Request) -> httpx.Response:
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        settings = Settings(
            database_path=tmp_path / "unused.db",
            model_api_key="test",
            model_request_deadline_seconds=0.03,
            model_max_retries=0,
            model_circuit_failure_threshold=10,
        )
        runtime = ModelProvider(settings, async_transport=httpx.MockTransport(blocked))
        await runtime.start()
        with pytest.raises(ModelProviderDeadlineExceededError) as caught:
            await generate_detailed_async(
                "LIS 超时检查什么？",
                _evidence(),
                settings,
                tenant_id="hospital-a",
                provider=runtime,
            )
        assert entered.is_set()
        assert caught.value.phase == "http"
        assert caught.value.elapsed_ms >= 20
        assert runtime.circuit_snapshot()["consecutive_failures"] == 1
        assert (await runtime.async_capacity_snapshot())["outstanding"] == 0
        await runtime.aclose()

    asyncio.run(scenario())


def test_end_to_end_deadline_interrupts_retry_backoff(tmp_path: Path) -> None:
    async def scenario() -> None:
        calls = 0

        async def unavailable(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(503, request=request)

        settings = Settings(
            database_path=tmp_path / "unused.db",
            model_api_key="test",
            model_request_deadline_seconds=0.03,
            model_max_retries=2,
            model_retry_base_delay_seconds=0.2,
            model_retry_max_delay_seconds=0.2,
            model_retry_jitter_ratio=0,
            model_circuit_failure_threshold=10,
        )
        runtime = ModelProvider(settings, async_transport=httpx.MockTransport(unavailable))
        await runtime.start()
        with pytest.raises(ModelProviderDeadlineExceededError) as caught:
            await generate_detailed_async(
                "LIS 超时检查什么？",
                _evidence(),
                settings,
                tenant_id="hospital-a",
                provider=runtime,
            )
        assert caught.value.phase == "backoff"
        assert calls == 1
        assert runtime.retry_budget_snapshot()["retries_consumed"] == 1
        assert (await runtime.async_capacity_snapshot())["outstanding"] == 0
        await runtime.aclose()

    asyncio.run(scenario())


def test_retry_after_delta_is_parsed_and_capped(tmp_path: Path) -> None:
    async def scenario() -> None:
        calls = 0

        async def throttle_once(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(429, request=request, headers={"Retry-After": "60"})
            return _success(request)

        settings = Settings(
            database_path=tmp_path / "unused.db",
            model_api_key="test",
            model_request_deadline_seconds=1,
            model_max_retries=1,
            model_retry_base_delay_seconds=0,
            model_retry_max_delay_seconds=0,
            model_retry_jitter_ratio=0,
            model_retry_after_max_seconds=0.02,
        )
        runtime = ModelProvider(settings, async_transport=httpx.MockTransport(throttle_once))
        await runtime.start()
        started = asyncio.get_running_loop().time()
        result = await generate_detailed_async(
            "LIS 超时检查什么？",
            _evidence(),
            settings,
            tenant_id="hospital-a",
            provider=runtime,
        )
        elapsed = asyncio.get_running_loop().time() - started
        assert result.provider == "openai-compatible"
        assert calls == 2
        assert 0.015 <= elapsed < 0.2
        await runtime.aclose()

    asyncio.run(scenario())


def test_retry_after_http_date_and_invalid_value_parsing() -> None:
    now = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
    future = format_datetime(now + timedelta(seconds=7), usegmt=True)

    assert _parse_retry_after_seconds("12", now=now) == 12
    assert _parse_retry_after_seconds(future, now=now) == 7
    assert _parse_retry_after_seconds("not-a-delay", now=now) is None


def test_exponential_backoff_uses_bounded_jitter(monkeypatch, tmp_path: Path) -> None:
    bounds: list[tuple[float, float]] = []

    def upper_bound(low: float, high: float) -> float:
        bounds.append((low, high))
        return high

    monkeypatch.setattr("app.agents.model.random.uniform", upper_bound)
    settings = Settings(
        database_path=tmp_path / "unused.db",
        model_retry_base_delay_seconds=0.1,
        model_retry_max_delay_seconds=0.3,
        model_retry_jitter_ratio=0.2,
    )
    runtime = ModelProvider(settings)
    request = httpx.Request("POST", "https://model.invalid")
    exc = httpx.TimeoutException("timeout", request=request)
    try:
        assert runtime.retry_delay_seconds(0, exc) == pytest.approx(0.12)
        assert runtime.retry_delay_seconds(1, exc) == pytest.approx(0.24)
        assert runtime.retry_delay_seconds(2, exc) == pytest.approx(0.3)
        assert len(bounds) == 3
        for actual, expected in zip(
            bounds, [(0.08, 0.12), (0.16, 0.24), (0.24, 0.36)], strict=True
        ):
            assert actual == pytest.approx(expected)
    finally:
        runtime.close()


def test_global_retry_budget_bounds_retry_storm_across_tenants(tmp_path: Path) -> None:
    async def scenario() -> None:
        calls = 0

        async def unavailable(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(503, request=request)

        settings = Settings(
            database_path=tmp_path / "unused.db",
            model_api_key="test",
            model_max_retries=2,
            model_retry_base_delay_seconds=0,
            model_retry_max_delay_seconds=0,
            model_retry_jitter_ratio=0,
            model_retry_budget_global_capacity=1,
            model_retry_budget_global_refill_per_second=0,
            model_retry_budget_per_tenant_capacity=10,
            model_retry_budget_per_tenant_refill_per_second=0,
            model_circuit_failure_threshold=10,
        )
        runtime = ModelProvider(settings, async_transport=httpx.MockTransport(unavailable))
        await runtime.start()
        for tenant_id in ("hospital-a", "hospital-b"):
            result = await generate_detailed_async(
                "LIS 超时检查什么？",
                _evidence(),
                settings,
                tenant_id=tenant_id,
                provider=runtime,
            )
            assert result.provider == "offline-fallback"
        snapshot = runtime.retry_budget_snapshot()
        assert calls == 3
        assert snapshot["retries_consumed"] == 1
        assert snapshot["global"] == {
            "remaining": 0.0,
            "capacity": 1,
            "refill_per_second": 0,
            "rejected": 2,
        }
        assert "hospital-a" not in str(snapshot)
        assert "hospital-b" not in str(snapshot)
        await runtime.aclose()

    asyncio.run(scenario())


def test_per_tenant_retry_budget_isolated_and_snapshot_is_aggregated(tmp_path: Path) -> None:
    async def scenario() -> None:
        calls = 0

        async def unavailable(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(503, request=request)

        settings = Settings(
            database_path=tmp_path / "unused.db",
            model_api_key="test",
            model_max_retries=2,
            model_retry_base_delay_seconds=0,
            model_retry_max_delay_seconds=0,
            model_retry_jitter_ratio=0,
            model_retry_budget_global_capacity=10,
            model_retry_budget_global_refill_per_second=0,
            model_retry_budget_per_tenant_capacity=1,
            model_retry_budget_per_tenant_refill_per_second=0,
            model_circuit_failure_threshold=10,
        )
        runtime = ModelProvider(settings, async_transport=httpx.MockTransport(unavailable))
        await runtime.start()
        for tenant_id in ("hospital-a", "hospital-b"):
            await generate_detailed_async(
                "LIS 超时检查什么？",
                _evidence(),
                settings,
                tenant_id=tenant_id,
                provider=runtime,
            )
        snapshot = runtime.retry_budget_snapshot()
        assert calls == 4
        assert snapshot["global"]["remaining"] == 8
        assert snapshot["per_tenant"] == {
            "tracked": 2,
            "remaining_total": 0.0,
            "remaining_min": 0.0,
            "remaining_max": 0.0,
            "capacity": 1,
            "refill_per_second": 0,
            "rejected": 2,
        }
        assert "hospital" not in str(snapshot)
        await runtime.aclose()

    asyncio.run(scenario())


def test_sync_deadline_covers_queue_wait_and_releases_permit(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "unused.db",
        model_api_key="test",
        model_request_deadline_seconds=0.03,
        model_queue_timeout_seconds=1,
        model_max_concurrency=1,
        model_max_queue_waiters=1,
    )
    runtime = ModelProvider(settings, transport=httpx.MockTransport(_success))
    entered = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with runtime.request_slot():
            entered.set()
            release.wait(1)

    worker = threading.Thread(target=hold)
    worker.start()
    assert entered.wait(1)
    try:
        with pytest.raises(ModelProviderDeadlineExceededError) as caught:
            generate_detailed("LIS 超时检查什么？", _evidence(), settings, provider=runtime)
        assert caught.value.phase == "queue"
    finally:
        release.set()
        worker.join(1)
        runtime.close()
    assert runtime.capacity_snapshot()["outstanding"] == 0


def test_sync_retry_obeys_backoff_deadline(tmp_path: Path) -> None:
    calls = 0

    def unavailable(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, request=request)

    settings = Settings(
        database_path=tmp_path / "unused.db",
        model_api_key="test",
        model_request_deadline_seconds=0.03,
        model_max_retries=1,
        model_retry_base_delay_seconds=0.2,
        model_retry_max_delay_seconds=0.2,
        model_retry_jitter_ratio=0,
        model_circuit_failure_threshold=10,
    )
    with ModelProvider(settings, transport=httpx.MockTransport(unavailable)) as runtime:
        with pytest.raises(ModelProviderDeadlineExceededError) as caught:
            generate_detailed("LIS 超时检查什么？", _evidence(), settings, provider=runtime)
        assert caught.value.phase == "backoff"
        assert calls == 1
        assert runtime.capacity_snapshot()["outstanding"] == 0
