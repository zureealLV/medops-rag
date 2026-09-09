"""Model adapter timeout and fallback tests."""

from pathlib import Path

import httpx

from app.agents.model import generate, generate_detailed
from app.config import Settings
from app.models.retrieval import Evidence


def test_settings_accept_existing_deepseek_api_key_alias(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "alias-secret")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'alias.db'}")

    settings = Settings.from_env()

    assert settings.model_api_key == "alias-secret"


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


def test_offline_extractor_keeps_quantities_and_class_lists(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "unused.db")
    evidence = [
        Evidence(
            score=1.0,
            keyword_score=1.0,
            vector_score=0.0,
            source="official.pdf",
            document_id=1,
            chunk_id=1,
            chunk_index=0,
            text=(
                "第六条 国家对医疗器械按照风险程度实行分类管理。"
                "第一类是风险程度低的医疗器械。"
                "第二类是具有中度风险的医疗器械。"
                "第三类是具有较高风险的医疗器械。"
            ),
        )
    ]

    answer, _, _, _ = generate("医疗器械按照风险程度分为哪三类？", evidence, settings)

    assert all(label in answer for label in ("第一类", "第二类", "第三类"))

    evidence[0].text = "每日烹调油宜控制在25g以内。食盐用量每日不宜超过5g。"
    answer, _, _, _ = generate("烹调油和食盐分别控制在多少？", evidence, settings)

    assert "25g" in answer
    assert "5g" in answer


def test_deepseek_v4_flash_openai_compatible_payload(monkeypatch, tmp_path: Path):
    captured = {}

    def succeed(url, *, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "choices": [{"message": {"content": "证据回答 [source:1]"}}],
                "usage": {
                    "prompt_tokens": 30,
                    "completion_tokens": 12,
                    "total_tokens": 42,
                    "prompt_cache_hit_tokens": 8,
                },
            },
        )

    monkeypatch.setattr(httpx, "post", succeed)
    settings = Settings(database_path=tmp_path / "unused.db", model_api_key="secret")
    evidence = [
        Evidence(
            score=0.9,
            keyword_score=0.9,
            vector_score=0.9,
            source="official.md",
            document_id=1,
            chunk_id=1,
            chunk_index=0,
            text="这是可核验的医学教育证据。",
        )
    ]

    answer, provider, _, token_usage = generate("资料说了什么？", evidence, settings)

    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["json"]["model"] == "deepseek-v4-flash"
    assert captured["headers"] == {"Authorization": "Bearer secret"}
    assert answer == "证据回答 [source:1]"
    assert provider == "openai-compatible"
    assert token_usage == 42

    detailed = generate_detailed("资料说了什么？", evidence, settings)
    assert detailed.usage.prompt_tokens == 30
    assert detailed.usage.completion_tokens == 12
    assert detailed.usage.cached_prompt_tokens == 8
