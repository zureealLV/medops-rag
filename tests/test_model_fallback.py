"""Model adapter timeout and fallback tests."""

from pathlib import Path

import httpx

from app.agents.model import ModelProvider, generate, generate_detailed
from app.config import Settings
from app.models.retrieval import Evidence


def test_settings_accept_existing_deepseek_api_key_alias(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "alias-secret")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'alias.db'}")

    settings = Settings.from_env()

    assert settings.model_api_key == "alias-secret"


def test_settings_load_provider_backpressure_limits(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'limits.db'}")
    monkeypatch.setenv("MODEL_MAX_CONCURRENCY", "7")
    monkeypatch.setenv("MODEL_MAX_CONCURRENCY_PER_TENANT", "3")
    monkeypatch.setenv("MODEL_MAX_QUEUE_WAITERS", "11")
    monkeypatch.setenv("MODEL_MAX_QUEUE_WAITERS_PER_TENANT", "5")
    monkeypatch.setenv("MODEL_QUEUE_TIMEOUT_SECONDS", "0.4")
    monkeypatch.setenv("MODEL_OVERLOAD_RETRY_AFTER_SECONDS", "3")
    monkeypatch.setenv("MODEL_CIRCUIT_FAILURE_THRESHOLD", "9")
    monkeypatch.setenv("MODEL_CIRCUIT_RECOVERY_SECONDS", "12")
    monkeypatch.setenv("MODEL_SHUTDOWN_TIMEOUT_SECONDS", "4")

    settings = Settings.from_env()

    assert settings.model_max_concurrency == 7
    assert settings.model_max_concurrency_per_tenant == 3
    assert settings.model_max_queue_waiters == 11
    assert settings.model_max_queue_waiters_per_tenant == 5
    assert settings.model_queue_timeout_seconds == 0.4
    assert settings.model_overload_retry_after_seconds == 3
    assert settings.model_circuit_failure_threshold == 9
    assert settings.model_circuit_recovery_seconds == 12
    assert settings.model_shutdown_timeout_seconds == 4


def test_provider_failure_uses_bounded_offline_fallback(tmp_path: Path):
    attempts = 0

    def fail(request: httpx.Request):
        nonlocal attempts
        attempts += 1
        raise httpx.TimeoutException("synthetic timeout", request=request)

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
    with ModelProvider(settings, transport=httpx.MockTransport(fail)) as runtime:
        answer, provider, _, token_usage = generate(
            "LIS 超时检查什么？", evidence, settings, provider=runtime
        )
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


def test_deepseek_v4_flash_openai_compatible_payload(tmp_path: Path):
    captured = {}

    def succeed(request: httpx.Request):
        captured.update(
            url=str(request.url),
            headers=dict(request.headers),
            json=__import__("json").loads(request.content),
        )
        return httpx.Response(
            200,
            request=request,
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

    with ModelProvider(settings, transport=httpx.MockTransport(succeed)) as runtime:
        answer, provider, _, token_usage = generate("资料说了什么？", evidence, settings, provider=runtime)

    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["json"]["model"] == "deepseek-v4-flash"
    assert captured["headers"]["authorization"] == "Bearer secret"
    assert answer == "证据回答 [source:1]"
    assert provider == "openai-compatible"
    assert token_usage == 42

    with ModelProvider(settings, transport=httpx.MockTransport(succeed)) as runtime:
        detailed = generate_detailed("资料说了什么？", evidence, settings, provider=runtime)
    assert detailed.usage.prompt_tokens == 30
    assert detailed.usage.completion_tokens == 12
    assert detailed.usage.cached_prompt_tokens == 8
