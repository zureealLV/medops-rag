"""API proof that blocking RAG work is offloaded and model I/O stays async."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import httpx

from app.agents.checkpoints import CheckpointSession
from app.config import Settings
from app.main import create_app
from app.services import answers as answer_service


def _success(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        request=request,
        json={"choices": [{"message": {"content": "先检查网关。 [source:1]"}}]},
    )


async def _seed(client: httpx.AsyncClient, headers: dict[str, str]) -> int:
    kb_response = await client.post(
        "/knowledge-bases", headers=headers, json={"name": "Operations"}
    )
    assert kb_response.status_code == 201
    kb_id = kb_response.json()["id"]
    document = await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        headers=headers,
        json={
            "title": "LIS Runbook",
            "source": "lis.md",
            "content": "LIS 接口连续超时时，先检查接口网关健康状态和消息队列积压。",
        },
    )
    assert document.status_code == 201
    return kb_id


def test_answer_keeps_event_loop_live_and_offloads_retrieval_and_checkpoints(
    tmp_path: Path, monkeypatch
) -> None:
    async def scenario() -> None:
        loop_thread = threading.get_ident()
        retrieval_threads: list[int] = []
        checkpoint_threads: list[int] = []
        provider_threads: list[int] = []
        original_search = answer_service.text_search
        original_record = CheckpointSession.record

        def slow_search(*args, **kwargs):
            retrieval_threads.append(threading.get_ident())
            time.sleep(0.05)
            return original_search(*args, **kwargs)

        def tracked_record(self, *args, **kwargs):
            checkpoint_threads.append(threading.get_ident())
            return original_record(self, *args, **kwargs)

        async def online(request: httpx.Request) -> httpx.Response:
            provider_threads.append(threading.get_ident())
            await asyncio.sleep(0.01)
            return _success(request)

        monkeypatch.setattr(answer_service, "text_search", slow_search)
        monkeypatch.setattr(CheckpointSession, "record", tracked_record)
        settings = Settings(database_path=tmp_path / "api.db", model_api_key="test")
        app = create_app(
            settings,
            model_async_transport=httpx.MockTransport(online),
        )
        headers = {"X-Tenant-ID": "hospital-a", "X-Actor-ID": "tester"}
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                kb_id = await _seed(client, headers)
                completed = asyncio.Event()
                ticks = 0

                async def heartbeat() -> None:
                    nonlocal ticks
                    while not completed.is_set():
                        ticks += 1
                        await asyncio.sleep(0.002)

                beat = asyncio.create_task(heartbeat())
                response = await client.post(
                    "/answer",
                    headers=headers,
                    json={"question": "LIS 接口超时先检查什么？", "knowledge_base_id": kb_id},
                )
                completed.set()
                await beat

        assert response.status_code == 200
        assert ticks >= 5
        assert retrieval_threads and all(value != loop_thread for value in retrieval_threads)
        assert checkpoint_threads and all(value != loop_thread for value in checkpoint_threads)
        assert provider_threads == [loop_thread]

    asyncio.run(scenario())


def test_answer_circuit_open_is_explicit_503_and_never_offline_200(tmp_path: Path) -> None:
    async def scenario() -> None:
        attempts = 0

        async def fail(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(503, request=request)

        settings = Settings(
            database_path=tmp_path / "api.db",
            model_api_key="test",
            model_max_retries=0,
            model_circuit_failure_threshold=1,
            model_circuit_recovery_seconds=30,
        )
        app = create_app(settings, model_async_transport=httpx.MockTransport(fail))
        headers = {"X-Tenant-ID": "hospital-a", "X-Actor-ID": "tester"}
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                kb_id = await _seed(client, headers)
                payload = {
                    "question": "LIS 接口超时先检查什么？",
                    "knowledge_base_id": kb_id,
                }
                first = await client.post("/answer", headers=headers, json=payload)
                second = await client.post("/answer", headers=headers, json=payload)

        assert first.status_code == 503
        assert first.json()["code"] == "model_provider_circuit_open"
        assert first.headers["x-medops-circuit-state"] == "open"
        assert second.status_code == 503
        assert second.json()["code"] == "model_provider_circuit_open"
        assert attempts == 1

    asyncio.run(scenario())
