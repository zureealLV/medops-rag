"""Async Provider admission, tenant fairness, and circuit-breaker tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from app.agents.model import (
    ModelProvider,
    ModelProviderCircuitOpenError,
    ModelProviderOverloadedError,
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
        json={
            "choices": [{"message": {"content": "先检查网关。 [source:1]"}}],
            "usage": {"total_tokens": 12},
        },
    )


def test_async_generation_uses_lifespan_managed_async_client(tmp_path: Path) -> None:
    calls = 0

    async def succeed(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return _success(request)

    async def scenario() -> None:
        settings = Settings(database_path=tmp_path / "unused.db", model_api_key="test")
        runtime = ModelProvider(settings, async_transport=httpx.MockTransport(succeed))
        await runtime.start()
        result = await generate_detailed_async(
            "LIS 超时检查什么？",
            _evidence(),
            settings,
            tenant_id="hospital-a",
            provider=runtime,
        )
        assert result.provider == "openai-compatible"
        assert runtime.is_async_started is True
        await runtime.aclose()
        assert runtime.is_closed is True

    asyncio.run(scenario())
    assert calls == 1


def test_circuit_opens_after_consecutive_failures_and_half_open_probe_closes_it(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        attempts = 0
        half_open_entered = asyncio.Event()
        release_probe = asyncio.Event()

        async def fail_then_recover(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts <= 2:
                return httpx.Response(503, request=request)
            half_open_entered.set()
            await release_probe.wait()
            return _success(request)

        settings = Settings(
            database_path=tmp_path / "unused.db",
            model_api_key="test",
            model_max_retries=0,
            model_circuit_failure_threshold=2,
            model_circuit_recovery_seconds=0.02,
        )
        runtime = ModelProvider(settings, async_transport=httpx.MockTransport(fail_then_recover))
        await runtime.start()

        first = await generate_detailed_async(
            "LIS 超时检查什么？",
            _evidence(),
            settings,
            tenant_id="hospital-a",
            provider=runtime,
        )
        assert first.provider == "offline-fallback"
        with pytest.raises(ModelProviderCircuitOpenError) as opened:
            await generate_detailed_async(
                "LIS 超时检查什么？",
                _evidence(),
                settings,
                tenant_id="hospital-a",
                provider=runtime,
            )
        assert opened.value.state == "open"
        assert runtime.circuit_snapshot()["state"] == "open"
        assert attempts == 2

        with pytest.raises(ModelProviderCircuitOpenError):
            await generate_detailed_async(
                "LIS 超时检查什么？",
                _evidence(),
                settings,
                tenant_id="hospital-b",
                provider=runtime,
            )
        assert attempts == 2

        await asyncio.sleep(0.03)
        probe = asyncio.create_task(
            generate_detailed_async(
                "LIS 超时检查什么？",
                _evidence(),
                settings,
                tenant_id="hospital-a",
                provider=runtime,
            )
        )
        await half_open_entered.wait()
        assert runtime.circuit_snapshot()["state"] == "half_open"
        with pytest.raises(ModelProviderCircuitOpenError) as rejected:
            await generate_detailed_async(
                "LIS 超时检查什么？",
                _evidence(),
                settings,
                tenant_id="hospital-b",
                provider=runtime,
            )
        assert rejected.value.state == "half_open"
        release_probe.set()
        assert (await probe).provider == "openai-compatible"
        assert runtime.circuit_snapshot()["state"] == "closed"
        await runtime.aclose()

    asyncio.run(scenario())


def test_cancelled_half_open_probe_reopens_circuit_without_leaking_probe(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        calls = 0
        probe_entered = asyncio.Event()

        async def fail_then_block(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(503, request=request)
            probe_entered.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        settings = Settings(
            database_path=tmp_path / "unused.db",
            model_api_key="test",
            model_max_retries=0,
            model_circuit_failure_threshold=1,
            model_circuit_recovery_seconds=0.01,
        )
        runtime = ModelProvider(settings, async_transport=httpx.MockTransport(fail_then_block))
        await runtime.start()
        with pytest.raises(ModelProviderCircuitOpenError):
            await generate_detailed_async(
                "LIS 超时检查什么？",
                _evidence(),
                settings,
                tenant_id="hospital-a",
                provider=runtime,
            )
        await asyncio.sleep(0.02)
        probe = asyncio.create_task(
            generate_detailed_async(
                "LIS 超时检查什么？",
                _evidence(),
                settings,
                tenant_id="hospital-a",
                provider=runtime,
            )
        )
        await probe_entered.wait()
        probe.cancel()
        with pytest.raises(asyncio.CancelledError):
            await probe
        assert runtime.circuit_snapshot()["state"] == "open"
        assert runtime.circuit_snapshot()["half_open_probe_active"] is False
        with pytest.raises(ModelProviderCircuitOpenError):
            await generate_detailed_async(
                "LIS 超时检查什么？",
                _evidence(),
                settings,
                tenant_id="hospital-b",
                provider=runtime,
            )
        assert calls == 2
        await runtime.aclose()

    asyncio.run(scenario())


def test_retry_backoff_releases_attempt_slot_but_retains_bounded_admission(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        calls = 0
        first_failed = asyncio.Event()

        async def retry_once(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                first_failed.set()
                return httpx.Response(503, request=request)
            return _success(request)

        settings = Settings(
            database_path=tmp_path / "unused.db",
            model_api_key="test",
            model_max_concurrency=1,
            model_max_concurrency_per_tenant=1,
            model_max_queue_waiters=1,
            model_queue_timeout_seconds=0.2,
            model_max_retries=1,
        )
        runtime = ModelProvider(settings, async_transport=httpx.MockTransport(retry_once))
        await runtime.start()
        first = asyncio.create_task(
            generate_detailed_async(
                "LIS 超时检查什么？",
                _evidence(),
                settings,
                tenant_id="hospital-a",
                provider=runtime,
            )
        )
        await first_failed.wait()
        second = await asyncio.wait_for(
            generate_detailed_async(
                "LIS 超时检查什么？",
                _evidence(),
                settings,
                tenant_id="hospital-b",
                provider=runtime,
            ),
            timeout=0.08,
        )
        assert second.provider == "openai-compatible"
        assert (await first).provider == "openai-compatible"
        assert calls == 3
        await runtime.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(("status", "expected_calls"), [(401, 1), (403, 1), (400, 1), (429, 2), (503, 2)])
def test_async_retry_policy_only_retries_transient_failures(
    tmp_path: Path, status: int, expected_calls: int
) -> None:
    async def scenario() -> None:
        calls = 0

        async def respond(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(status, request=request)
            return _success(request)

        settings = Settings(
            database_path=tmp_path / "unused.db",
            model_api_key="test",
            model_max_retries=1,
            model_circuit_failure_threshold=10,
        )
        runtime = ModelProvider(settings, async_transport=httpx.MockTransport(respond))
        await runtime.start()
        result = await generate_detailed_async(
            "LIS 超时检查什么？",
            _evidence(),
            settings,
            tenant_id="hospital-a",
            provider=runtime,
        )
        assert calls == expected_calls
        assert result.provider == (
            "openai-compatible" if expected_calls == 2 else "offline-fallback"
        )
        await runtime.aclose()

    asyncio.run(scenario())


def test_async_admission_enforces_tenant_fairness_under_global_limit(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = Settings(
            database_path=tmp_path / "unused.db",
            model_max_concurrency=2,
            model_max_concurrency_per_tenant=1,
            model_max_queue_waiters=2,
            model_queue_timeout_seconds=1,
        )
        runtime = ModelProvider(settings)
        await runtime.start()
        first_a_entered = asyncio.Event()
        release_a = asyncio.Event()
        second_a_entered = asyncio.Event()
        b_entered = asyncio.Event()

        async def hold_a() -> None:
            async with runtime.async_request_slot("hospital-a"):
                first_a_entered.set()
                await release_a.wait()

        async def wait_a() -> None:
            async with runtime.async_request_slot("hospital-a"):
                second_a_entered.set()

        async def run_b() -> None:
            async with runtime.async_request_slot("hospital-b"):
                b_entered.set()

        first = asyncio.create_task(hold_a())
        await first_a_entered.wait()
        second = asyncio.create_task(wait_a())
        await asyncio.sleep(0)
        other_tenant = asyncio.create_task(run_b())
        await asyncio.wait_for(b_entered.wait(), 0.2)
        assert second_a_entered.is_set() is False
        snapshot = runtime.capacity_snapshot()
        assert snapshot["active"] == 1
        assert snapshot["waiting"] == 1
        assert snapshot["active_tenants"] == 1
        release_a.set()
        await asyncio.gather(first, second, other_tenant)
        await runtime.aclose()

    asyncio.run(scenario())


def test_round_robin_prevents_hot_tenant_starvation_with_one_attempt_slot(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        settings = Settings(
            database_path=tmp_path / "unused.db",
            model_max_concurrency=1,
            model_max_concurrency_per_tenant=1,
            model_max_queue_waiters=4,
            model_max_queue_waiters_per_tenant=3,
            model_queue_timeout_seconds=1,
        )
        runtime = ModelProvider(settings)
        await runtime.start()
        first_entered = asyncio.Event()
        release_first = asyncio.Event()
        order: list[str] = []

        async def hold_first() -> None:
            async with runtime.async_request_slot("hospital-a"):
                order.append("a1")
                first_entered.set()
                await release_first.wait()

        async def take(label: str, tenant_id: str) -> None:
            async with runtime.async_request_slot(tenant_id):
                order.append(label)
                await asyncio.sleep(0)

        first = asyncio.create_task(hold_first())
        await first_entered.wait()
        a2 = asyncio.create_task(take("a2", "hospital-a"))
        a3 = asyncio.create_task(take("a3", "hospital-a"))
        await asyncio.sleep(0)
        tenant_b = asyncio.create_task(take("b1", "hospital-b"))
        await asyncio.sleep(0)
        release_first.set()
        await asyncio.gather(first, a2, a3, tenant_b)
        assert order == ["a1", "b1", "a2", "a3"]
        await runtime.aclose()

    asyncio.run(scenario())


def test_hot_tenant_cannot_consume_every_global_waiter(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = Settings(
            database_path=tmp_path / "unused.db",
            model_max_concurrency=1,
            model_max_concurrency_per_tenant=1,
            model_max_queue_waiters=3,
            model_max_queue_waiters_per_tenant=1,
            model_queue_timeout_seconds=1,
        )
        runtime = ModelProvider(settings)
        await runtime.start()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def hold() -> None:
            async with runtime.async_request_slot("hospital-a"):
                entered.set()
                await release.wait()

        async def wait_a() -> None:
            async with runtime.async_request_slot("hospital-a"):
                return None

        first = asyncio.create_task(hold())
        await entered.wait()
        queued_a = asyncio.create_task(wait_a())
        await asyncio.sleep(0)
        with pytest.raises(ModelProviderOverloadedError) as caught:
            async with runtime.async_request_slot("hospital-a"):
                raise AssertionError("unreachable")
        assert caught.value.reason == "queue_full"

        # The rejected hot-tenant request did not consume the capacity reserved
        # for other tenants.
        tenant_b_entered = asyncio.Event()

        async def run_b() -> None:
            async with runtime.async_request_slot("hospital-b"):
                tenant_b_entered.set()

        tenant_b = asyncio.create_task(run_b())
        release.set()
        await asyncio.wait_for(tenant_b_entered.wait(), 0.2)
        await asyncio.gather(first, queued_a, tenant_b)
        await runtime.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("queue_waiters", "expected_reason"),
    [(0, "queue_full"), (1, "queue_timeout")],
)
def test_async_admission_reports_bounded_queue_reasons(
    tmp_path: Path, queue_waiters: int, expected_reason: str
) -> None:
    async def scenario() -> None:
        settings = Settings(
            database_path=tmp_path / "unused.db",
            model_max_concurrency=1,
            model_max_concurrency_per_tenant=1,
            model_max_queue_waiters=queue_waiters,
            model_queue_timeout_seconds=0.01,
        )
        runtime = ModelProvider(settings)
        await runtime.start()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def hold() -> None:
            async with runtime.async_request_slot("hospital-a"):
                entered.set()
                await release.wait()

        first = asyncio.create_task(hold())
        await entered.wait()
        with pytest.raises(ModelProviderOverloadedError) as caught:
            async with runtime.async_request_slot("hospital-a"):
                raise AssertionError("unreachable")
        assert caught.value.reason == expected_reason
        release.set()
        await first
        assert runtime.capacity_snapshot()["active"] == 0
        assert runtime.capacity_snapshot()["waiting"] == 0
        await runtime.aclose()

    asyncio.run(scenario())


def test_cancelled_waiter_does_not_leak_async_capacity(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = Settings(
            database_path=tmp_path / "unused.db",
            model_max_concurrency=1,
            model_max_concurrency_per_tenant=1,
            model_max_queue_waiters=1,
            model_queue_timeout_seconds=1,
        )
        runtime = ModelProvider(settings)
        await runtime.start()
        release = asyncio.Event()
        entered = asyncio.Event()

        async def hold() -> None:
            async with runtime.async_request_slot("hospital-a"):
                entered.set()
                await release.wait()

        first = asyncio.create_task(hold())
        await entered.wait()
        waiter = asyncio.create_task(runtime.async_request_slot("hospital-b").__aenter__())
        while runtime.capacity_snapshot()["waiting"] != 1:
            await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert runtime.capacity_snapshot()["waiting"] == 0
        assert runtime.capacity_snapshot()["outstanding"] == 1
        release.set()
        await first
        assert runtime.capacity_snapshot()["outstanding"] == 0
        await runtime.aclose()

    asyncio.run(scenario())


def test_aclose_is_bounded_and_rejects_queued_requests(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = Settings(
            database_path=tmp_path / "unused.db",
            model_max_concurrency=1,
            model_max_concurrency_per_tenant=1,
            model_max_queue_waiters=1,
            model_queue_timeout_seconds=10,
            model_shutdown_timeout_seconds=0.02,
        )
        runtime = ModelProvider(settings)
        await runtime.start()
        release = asyncio.Event()
        entered = asyncio.Event()

        async def hold() -> None:
            async with runtime.async_request_slot("hospital-a"):
                entered.set()
                await release.wait()

        first = asyncio.create_task(hold())
        await entered.wait()
        queued = asyncio.create_task(runtime.async_request_slot("hospital-b").__aenter__())
        while runtime.capacity_snapshot()["waiting"] != 1:
            await asyncio.sleep(0)
        started = asyncio.get_running_loop().time()
        await runtime.aclose()
        elapsed = asyncio.get_running_loop().time() - started
        assert elapsed < 0.2
        with pytest.raises(RuntimeError, match="closed"):
            await queued
        release.set()
        await first

    asyncio.run(scenario())
