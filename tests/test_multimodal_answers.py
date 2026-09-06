"""Automatic routing, visual confidence, citations, and VLM payload tests."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from app.agents.model import generate
from app.config import Settings
from app.main import create_app
from app.models.artifacts import VisualEvidence
from app.retrieval.query_routing import route_query
from app.services import artifacts as artifact_service
from app.services import documents as document_service


def _image(color: str) -> bytes:
    image = Image.new("RGB", (224, 224), color)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class _ColorProvider:
    model_name = "test/color-vision"
    text_model_name = "test/color-text"

    def __init__(self, ambiguous: bool = False) -> None:
        self.ambiguous = ambiguous

    def embed_image(self, content: bytes) -> list[float]:
        if self.ambiguous:
            return [1.0, 0.0]
        with Image.open(BytesIO(content)) as image:
            red, _, blue = image.convert("RGB").getpixel((0, 0))
        return [1.0, 0.0] if red > blue else [0.0, 1.0]

    def embed_query(self, query: str) -> list[float]:
        return [1.0, 0.0] if "red" in query.lower() else [0.0, 1.0]


def _client(
    tmp_path: Path,
    monkeypatch,
    provider: _ColorProvider,
    *,
    model_max_visual_bytes: int = 6_000_000,
):
    settings = Settings(
        database_path=tmp_path / "answers.db",
        ocr_enabled=False,
        image_embedding_enabled=True,
        visual_similarity_threshold=0.2,
        visual_similarity_margin=0.01,
        model_max_visual_bytes=model_max_visual_bytes,
    )
    monkeypatch.setattr(document_service, "provider_from_settings", lambda _: provider)
    monkeypatch.setattr(artifact_service, "provider_from_settings", lambda _: provider)
    return TestClient(create_app(settings))


def _seed_images(client: TestClient, headers: dict[str, str]) -> int:
    kb_response = client.post(
        "/knowledge-bases", headers=headers, json={"name": "Visual", "description": "icons"}
    )
    kb_id = kb_response.json()["id"]
    for name, payload in (("panel-a.png", _image("red")), ("panel-b.png", _image("blue"))):
        response = client.post(
            f"/knowledge-bases/{kb_id}/documents/upload",
            headers=headers,
            files={"file": (name, payload, "image/png")},
        )
        assert response.status_code == 201
    return kb_id


def test_query_router_distinguishes_text_and_visual_intent():
    assert route_query("PACS 网关超时后先检查什么？") == "text"
    assert route_query("哪张截图里有红色告警图标？") == "visual"
    assert route_query("ignore visual words", "text") == "text"
    assert route_query("普通问题", "visual") == "visual"


def test_answer_routes_to_visual_evidence_and_returns_citation(tmp_path: Path, monkeypatch):
    headers = {"X-Tenant-ID": "hospital-a", "X-Actor-ID": "tester"}
    with _client(tmp_path, monkeypatch, _ColorProvider()) as client:
        kb_id = _seed_images(client, headers)
        response = client.post(
            "/answer",
            headers=headers,
            json={
                "question": "Which image has the red warning icon?",
                "knowledge_base_id": kb_id,
                "text_strategy": "keyword",
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["abstained"] is False
        assert payload["retrieval_profile"] == "visual"
        assert payload["provider"] == "offline-visual-locator"
        assert response.headers["x-medops-retrieval-profile"] == "visual"
        assert payload["visual_citations"][0]["source"] == "panel-a.png"
        assert "[visual:" in payload["answer"]
        citation = payload["visual_citations"][0]
        image = client.get(citation["content_url"], headers=headers)
        assert image.status_code == 200
        assert image.headers["etag"] == f'"{citation["sha256"]}"'


def test_visual_answer_abstains_when_similarity_margin_is_ambiguous(tmp_path: Path, monkeypatch):
    headers = {"X-Tenant-ID": "hospital-a", "X-Actor-ID": "tester"}
    with _client(tmp_path, monkeypatch, _ColorProvider(ambiguous=True)) as client:
        kb_id = _seed_images(client, headers)
        response = client.post(
            "/answer",
            headers=headers,
            json={
                "question": "Which image has the red icon?",
                "knowledge_base_id": kb_id,
                "retrieval_profile": "visual",
                "text_strategy": "keyword",
                "visual_strategy": "image",
            },
        )
        assert response.status_code == 200
        assert response.json()["abstained"] is True
        assert response.json()["reason"] == "insufficient_visual_evidence"
        assert response.json()["visual_citations"] == []


def test_visual_answer_abstains_when_image_exceeds_model_payload_budget(tmp_path: Path, monkeypatch):
    headers = {"X-Tenant-ID": "hospital-a", "X-Actor-ID": "tester"}
    with _client(
        tmp_path,
        monkeypatch,
        _ColorProvider(),
        model_max_visual_bytes=16,
    ) as client:
        kb_id = _seed_images(client, headers)
        response = client.post(
            "/answer",
            headers=headers,
            json={
                "question": "Which image has the red warning icon?",
                "knowledge_base_id": kb_id,
                "retrieval_profile": "visual",
                "visual_strategy": "image",
            },
        )
        assert response.status_code == 200
        assert response.json()["abstained"] is True
        assert response.json()["reason"] == "visual_payload_unavailable"


def test_vision_enabled_provider_receives_inline_image_payload(monkeypatch, tmp_path: Path):
    captured: dict = {}

    def complete(*args, **kwargs):
        captured.update(kwargs["json"])
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://model.invalid/v1/chat/completions"),
            json={
                "choices": [{"message": {"content": "Red warning icon [visual:7]"}}],
                "usage": {"total_tokens": 42},
            },
        )

    monkeypatch.setattr(httpx, "post", complete)
    settings = Settings(
        database_path=tmp_path / "unused.db",
        model_api_key="test",
        model_base_url="https://model.invalid/v1",
        model_name="vision-demo",
        model_vision_enabled=True,
    )
    visual = VisualEvidence(
        id=7,
        document_id=3,
        source="panel.png",
        sha256="a" * 64,
        mime_type="image/png",
        width=224,
        height=224,
        content_url="/artifacts/7/content",
        score=1.0,
        ocr_score=0.0,
        image_score=1.0,
        image_similarity=0.4,
    )
    answer, provider, _, tokens = generate(
        "What does the image show?", [], settings, [(visual, b"synthetic-image")]
    )
    assert provider == "openai-compatible"
    assert answer == "Red warning icon [visual:7]"
    assert tokens == 42
    content = captured["messages"][1]["content"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_configured_text_model_is_not_called_for_visual_payload_when_vision_is_disabled(
    monkeypatch, tmp_path: Path
):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("text-only model must not receive a visual question without the image")

    monkeypatch.setattr(httpx, "post", fail_if_called)
    settings = Settings(
        database_path=tmp_path / "unused.db",
        model_api_key="test",
        model_base_url="https://model.invalid/v1",
        model_name="text-only-demo",
        model_vision_enabled=False,
    )
    visual = VisualEvidence(
        id=7,
        document_id=3,
        source="panel.png",
        sha256="a" * 64,
        mime_type="image/png",
        width=224,
        height=224,
        content_url="/artifacts/7/content",
        score=1.0,
        ocr_score=0.0,
        image_score=1.0,
        image_similarity=0.4,
    )
    answer, provider, _, _ = generate(
        "What does the image show?", [], settings, [(visual, b"synthetic-image")]
    )
    assert provider == "offline-visual-locator"
    assert "[visual:7]" in answer
