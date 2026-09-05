"""Model adapter timeout and fallback tests."""

from pathlib import Path

import httpx

from app.agents.model import generate
from app.config import Settings
from app.models.retrieval import Evidence


def test_provider_failure_uses_bounded_offline_fallback(monkeypatch, tmp_path: Path):
    attempts = 0

    def fail(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise httpx.TimeoutException("synthetic timeout")

    monkeypatch.setattr(httpx, "post", fail)
    settings = Settings(
        database_path=tmp_path / "unused.db",
        model_api_key="test",
        model_base_url="https://model.invalid/v1",
        model_name="demo",
        model_max_retries=1,
    )
    evidence = [
        Evidence(
            score=0.9,
            keyword_score=0.9,
            vector_score=0.9,
            source="synthetic.md",
            document_id=1,
            chunk_id=1,
            chunk_index=0,
            text="LIS 接口超时先检查网关。",
        )
    ]
    answer, provider, _, token_usage = generate("LIS 超时检查什么？", evidence, settings)
    assert attempts == 2
    assert provider == "offline-fallback"
    assert "网关" in answer
    assert token_usage > 0
