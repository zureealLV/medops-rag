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
