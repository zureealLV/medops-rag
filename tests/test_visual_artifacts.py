"""First-class image evidence, tenant isolation, deduplication, and fusion tests."""

from __future__ import annotations

import sqlite3
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from app.services import artifacts as artifact_service
from app.services import documents as document_service


def _solid_image(color: str) -> bytes:
    image = Image.new("RGB", (224, 224), color)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _create_kb(client: TestClient, headers: dict[str, str], name: str = "Visual KB") -> int:
    response = client.post(
        "/knowledge-bases", headers=headers, json={"name": name, "description": "images"}
    )
    assert response.status_code == 201
    return int(response.json()["id"])


def _upload(client: TestClient, headers: dict[str, str], kb_id: int, name: str, content: bytes):
    return client.post(
        f"/knowledge-bases/{kb_id}/documents/upload",
        headers=headers,
        files={"file": (name, content, "image/png")},
    )


class _FakeClipProvider:
    model_name = "test/clip-vision"
    text_model_name = "test/clip-text"

    def embed_image(self, content: bytes) -> list[float]:
        with Image.open(BytesIO(content)) as image:
            red, _, blue = image.convert("RGB").getpixel((0, 0))
        return [1.0, 0.0] if red > blue else [0.0, 1.0]

    def embed_query(self, query: str) -> list[float]:
        return [1.0, 0.0] if "red" in query.lower() else [0.0, 1.0]


def test_artifact_metadata_content_tenant_scope_and_blob_dedup(
    client: TestClient, tenant_headers: dict[str, str], kb: dict
):
    image = _solid_image("red")
    first = _upload(client, tenant_headers, kb["id"], "red-panel.png", image)
    assert first.status_code == 201, first.text
    document = first.json()
    assert document["artifact_count"] == 1

    listed = client.get(
        f"/documents/{document['id']}/artifacts", headers=tenant_headers
    )
    assert listed.status_code == 200
    artifact = listed.json()[0]
    assert artifact["mime_type"] == "image/png"
    assert artifact["width"] == 224 and artifact["height"] == 224
    content = client.get(artifact["content_url"], headers=tenant_headers)
    assert content.status_code == 200
    assert content.content == image
    assert content.headers["etag"] == f'"{artifact["sha256"]}"'

    denied = client.get(
        artifact["content_url"],
        headers={"X-Tenant-ID": "hospital-b", "X-Actor-ID": "intruder"},
    )
    assert denied.status_code == 404

    second_kb = _create_kb(client, tenant_headers, "Second Visual KB")
    second = _upload(client, tenant_headers, second_kb, "same-red-panel.png", image)
    assert second.status_code == 201

    other_headers = {"X-Tenant-ID": "hospital-b", "X-Actor-ID": "tester-b"}
    other_kb = _create_kb(client, other_headers, "Other Tenant Visual KB")
    other = _upload(client, other_headers, other_kb, "same-red-panel.png", image)
    assert other.status_code == 201
    database = client.app.state.settings.database_path
    connection = sqlite3.connect(database)
    blob_count = connection.execute("SELECT COUNT(*) FROM artifact_blobs").fetchone()[0]
    reference_count = connection.execute("SELECT COUNT(*) FROM document_artifacts").fetchone()[0]
    connection.close()
    assert blob_count == 2
    assert reference_count == 3


def test_visual_search_uses_paired_image_embeddings_and_fusion(
    tmp_path: Path, monkeypatch
):
    settings = Settings(
        database_path=tmp_path / "visual.db",
        ocr_enabled=False,
        image_embedding_enabled=True,
    )
    provider = _FakeClipProvider()
    monkeypatch.setattr(document_service, "provider_from_settings", lambda _: provider)
    monkeypatch.setattr(artifact_service, "provider_from_settings", lambda _: provider)
    headers = {"X-Tenant-ID": "hospital-a", "X-Actor-ID": "tester"}
    with TestClient(create_app(settings)) as client:
        kb_id = _create_kb(client, headers)
        red = _upload(client, headers, kb_id, "red-panel.png", _solid_image("red"))
        blue = _upload(client, headers, kb_id, "blue-panel.png", _solid_image("blue"))
        assert red.status_code == blue.status_code == 201
        assert red.json()["element_count"] == 0
        assert red.json()["artifact_count"] == 1
        other_headers = {"X-Tenant-ID": "hospital-b", "X-Actor-ID": "tester-b"}
        other_kb = _create_kb(client, other_headers, "Secret Visual KB")
        secret = _upload(
            client, other_headers, other_kb, "other-secret.png", _solid_image("red")
        )
        assert secret.status_code == 201

        image_search = client.post(
            "/visual-search",
            headers=headers,
            json={"query": "red warning panel", "knowledge_base_id": kb_id, "strategy": "image"},
        )
        assert image_search.status_code == 200, image_search.text
        payload = image_search.json()
        assert payload["image_embedding_available"] is True
        assert payload["results"][0]["source"] == "red-panel.png"
        assert payload["results"][0]["image_score"] == 1.0
        assert "other-secret.png" not in {item["source"] for item in payload["results"]}

        fusion_search = client.post(
            "/visual-search",
            headers=headers,
            json={"query": "blue status panel", "knowledge_base_id": kb_id, "strategy": "fusion"},
        )
        assert fusion_search.status_code == 200
        assert fusion_search.json()["results"][0]["source"] == "blue-panel.png"


def test_image_strategy_fails_explicitly_without_embeddings(
    tmp_path: Path,
):
    settings = Settings(database_path=tmp_path / "disabled.db", ocr_enabled=False)
    headers = {"X-Tenant-ID": "hospital-a", "X-Actor-ID": "tester"}
    with TestClient(create_app(settings)) as client:
        kb_id = _create_kb(client, headers)
        uploaded = _upload(client, headers, kb_id, "red-panel.png", _solid_image("red"))
        assert uploaded.status_code == 201
        response = client.post(
            "/visual-search",
            headers=headers,
            json={"query": "red panel", "knowledge_base_id": kb_id, "strategy": "image"},
        )
        assert response.status_code == 409
        assert response.json()["code"] == "image_embeddings_unavailable"


def test_manual_content_replacement_removes_artifact_and_orphan_blob(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "cleanup.db", ocr_enabled=False)
    headers = {"X-Tenant-ID": "hospital-a", "X-Actor-ID": "tester"}
    with TestClient(create_app(settings)) as client:
        kb_id = _create_kb(client, headers)
        uploaded = _upload(client, headers, kb_id, "red-panel.png", _solid_image("red"))
        document_id = uploaded.json()["id"]
        replaced = client.patch(
            f"/documents/{document_id}",
            headers=headers,
            json={"content": "Replacement text invalidates original visual provenance."},
        )
        assert replaced.status_code == 200
        assert replaced.json()["artifact_count"] == 0
        assert client.get(
            f"/documents/{document_id}/artifacts", headers=headers
        ).json() == []

    connection = sqlite3.connect(settings.database_path)
    assert connection.execute("SELECT COUNT(*) FROM artifact_blobs").fetchone()[0] == 0
    connection.close()
