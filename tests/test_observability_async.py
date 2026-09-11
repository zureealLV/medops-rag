"""Event-loop liveness proof for durable request telemetry."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx

from app import observability
from app.config import Settings
from app.main import create_app


def test_slow_request_metric_write_is_offloaded_from_event_loop(
    tmp_path: Path, monkeypatch
) -> None:
    async def scenario() -> None:
        writes: list[str] = []

        def slow_write(*args, **kwargs) -> None:
            time.sleep(0.05)
            writes.append(str(kwargs["request_path"]))

        monkeypatch.setattr(observability, "_record_request_metric", slow_write)
        app = create_app(Settings(database_path=tmp_path / "metrics.db"))
        ticks = 0
        finished = asyncio.Event()

        async def heartbeat() -> None:
            nonlocal ticks
            while not finished.is_set():
                ticks += 1
                await asyncio.sleep(0.002)

        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                beat = asyncio.create_task(heartbeat())
                response = await client.get("/ready")
                finished.set()
                await beat

        assert response.status_code == 200
        assert writes == ["/ready"]
        assert ticks >= 5

    asyncio.run(scenario())
