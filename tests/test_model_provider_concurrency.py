"""Provider client reuse, bounded admission, and HTTP backpressure tests."""

from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents.model import ModelProvider, ModelProviderOverloadedError, generate
from app.config import Settings
from app.main import create_app
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


class _CountingTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.calls = 0
        self.close_calls = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return _success(request)

    def close(self) -> None:
        self.close_calls += 1


def test_provider_reuses_one_client_and_lifespan_closes_it(tmp_path: Path) -> None:
    transport = _CountingTransport()
    settings = Settings(database_path=tmp_path / "app.db", model_api_key="test")
    application = create_app(settings, model_transport=transport)
    runtime = application.state.model_provider

    with TestClient(application):
        first = generate("LIS 超时检查什么？", _evidence(), settings, provider=runtime)
        second = generate("LIS 超时检查什么？", _evidence(), settings, provider=runtime)
        assert first[1] == second[1] == "openai-compatible"
        assert runtime.is_closed is False

    assert transport.calls == 2
    assert transport.close_calls == 1
    assert runtime.is_closed is True


def test_queue_timeout_is_distinct_and_capacity_is_released(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()

    def blocked(request: httpx.Request) -> httpx.Response:
        entered.set()
        assert release.wait(5)
        return _success(request)

    settings = Settings(
        database_path=tmp_path / "unused.db",
        model_api_key="test",
        model_max_concurrency=1,
        model_max_queue_waiters=1,
        model_queue_timeout_seconds=0.02,
        model_max_retries=0,
    )
    with ModelProvider(settings, transport=httpx.MockTransport(blocked)) as runtime:
        with ThreadPoolExecutor(max_workers=1) as executor:
            first = executor.submit(generate, "LIS 超时检查什么？", _evidence(), settings, None, runtime)
            assert entered.wait(2)
            with pytest.raises(ModelProviderOverloadedError) as caught:
                generate("LIS 超时检查什么？", _evidence(), settings, provider=runtime)
            assert caught.value.reason == "queue_timeout"
            assert caught.value.waited_ms >= 10
            release.set()
            assert first.result(timeout=2)[1] == "openai-compatible"
        assert runtime.capacity_snapshot()["active"] == 0
        assert runtime.capacity_snapshot()["waiting"] == 0


def test_retry_backoff_keeps_the_provider_slot(tmp_path: Path) -> None:
    first_attempt_finished = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def retry_once(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        with calls_lock:
            calls += 1
            current = calls
        if current == 1:
            first_attempt_finished.set()
            return httpx.Response(503, request=request)
        return _success(request)

    settings = Settings(
        database_path=tmp_path / "unused.db",
        model_api_key="test",
        model_max_concurrency=1,
        model_max_queue_waiters=0,
        model_max_retries=1,
    )
    with ModelProvider(settings, transport=httpx.MockTransport(retry_once)) as runtime:
        with ThreadPoolExecutor(max_workers=1) as executor:
            first = executor.submit(generate, "LIS 超时检查什么？", _evidence(), settings, None, runtime)
            assert first_attempt_finished.wait(2)
            with pytest.raises(ModelProviderOverloadedError) as caught:
                generate("LIS 超时检查什么？", _evidence(), settings, provider=runtime)
            assert caught.value.reason == "queue_full"
            assert first.result(timeout=2)[1] == "openai-compatible"
    assert calls == 2


@pytest.mark.parametrize(
    ("max_queue_waiters", "expected_reason"),
    [(0, "queue_full"), (1, "queue_timeout")],
)
def test_answer_overload_returns_explicit_503_and_retry_headers(
    tmp_path: Path,
    max_queue_waiters: int,
    expected_reason: str,
) -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked(request: httpx.Request) -> httpx.Response:
            entered.set()
            await asyncio.wait_for(release.wait(), 2)
            return _success(request)

        settings = Settings(
            database_path=tmp_path / "api.db",
            model_api_key="test",
            model_max_concurrency=1,
            model_max_concurrency_per_tenant=1,
            model_max_queue_waiters=max_queue_waiters,
            model_queue_timeout_seconds=0.01,
            model_overload_retry_after_seconds=2,
            model_max_retries=0,
        )
        app = create_app(settings, model_async_transport=httpx.MockTransport(blocked))
        headers = {"X-Tenant-ID": "hospital-a", "X-Actor-ID": "tester"}
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                kb = (
                    await client.post(
                        "/knowledge-bases",
                        headers=headers,
                        json={"name": "Operations", "description": "Synthetic runbooks"},
                    )
                ).json()
                document = await client.post(
                    f"/knowledge-bases/{kb['id']}/documents",
                    headers=headers,
                    json={
                        "title": "LIS Timeout",
                        "source": "lis.md",
                        "content": "LIS 接口连续超时时，先检查接口网关健康状态和消息队列积压。",
                    },
                )
                assert document.status_code == 201
                payload = {
                    "question": "LIS 接口连续超时时先检查什么？",
                    "knowledge_base_id": kb["id"],
                }
                first = asyncio.create_task(client.post("/answer", headers=headers, json=payload))
                await asyncio.wait_for(entered.wait(), 2)
                overloaded = await client.post("/answer", headers=headers, json=payload)
                assert overloaded.status_code == 503
                assert overloaded.headers["retry-after"] == "2"
                assert overloaded.headers["x-medops-provider-overloaded"] == "true"
                assert overloaded.headers["x-medops-overload-reason"] == expected_reason
                assert overloaded.json()["code"] == "model_provider_overloaded"
                assert overloaded.json()["details"]["reason"] == expected_reason
                audit = (await client.get("/audit-logs", headers=headers)).json()
                rejected = next(event for event in audit if event["result"] == "rejected")
                assert json.loads(rejected["details"])["overload_reason"] == expected_reason
                release.set()
                completed = await first
                assert completed.status_code == 200
                assert completed.headers["x-medops-provider"] == "openai-compatible"

    asyncio.run(scenario())
