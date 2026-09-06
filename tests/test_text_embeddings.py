"""Pluggable dense text embedding persistence and query tests."""

from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.retrieval.text_embeddings import FastEmbedTextProvider
from app.services import documents as document_service
from app.services import retrieval as retrieval_service


class _SemanticProvider:
    model_name = "test/semantic-2d"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    @staticmethod
    def _embed(text: str) -> list[float]:
        normalized = text.lower()
        return [1.0, 0.0] if any(word in normalized for word in ("certificate", "credential")) else [0.0, 1.0]


def test_fastembed_vectors_are_normalized_before_cosine_scoring():
    vector = FastEmbedTextProvider._values([np.asarray([3.0, 4.0], dtype=np.float32)])[0]
    assert vector == [0.6000000238418579, 0.800000011920929]


def test_configured_embedding_provider_is_persisted_and_used_for_vector_query(
    tmp_path: Path, monkeypatch
):
    provider = _SemanticProvider()
    monkeypatch.setattr(document_service, "text_provider_from_settings", lambda _: provider)
    monkeypatch.setattr(retrieval_service, "provider_from_settings", lambda _: provider)
    settings = Settings(
        database_path=tmp_path / "dense.db",
        text_embedding_enabled=True,
        text_embedding_model=provider.model_name,
    )
    headers = {"X-Tenant-ID": "hospital-a", "X-Actor-ID": "tester"}
    with TestClient(create_app(settings)) as client:
        kb_id = client.post(
            "/knowledge-bases", headers=headers, json={"name": "Dense"}
        ).json()["id"]
        for title, content in (
            ("Certificate", "Rotate the gateway certificate before it expires."),
            ("Storage", "Expand archive storage after capacity alert."),
        ):
            response = client.post(
                f"/knowledge-bases/{kb_id}/documents",
                headers=headers,
                json={"title": title, "source": f"{title}.md", "content": content},
            )
            assert response.status_code == 201

        response = client.post(
            "/search",
            headers=headers,
            json={"query": "renew gateway credential", "top_k": 2},
        )
        assert response.status_code == 200
        results = response.json()["results"]
        assert response.json()["strategy"] == "rrf"
        assert results[0]["source"] == "Certificate.md"
        assert results[0]["embedding_model"] == provider.model_name
        assert all(item["embedding_model"] == provider.model_name for item in results)
