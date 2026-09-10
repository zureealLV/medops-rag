"""Chunking, ranking, and hybrid-retrieval tests."""

import pytest
from fastapi.testclient import TestClient

from app.retrieval.chunking import split_text


def test_chunk_overlap_and_validation():
    text = "段落一。" * 100
    chunks = split_text(text, size=120, overlap=20)
    assert len(chunks) > 1
    with pytest.raises(ValueError):
        split_text(text, size=50)


def test_chinese_chunks_prefer_sentence_boundaries_and_semicolons():
    text = "第一项说明很重要；" * 12 + "第二段包含完整结论。" * 12
    chunks = split_text(text, size=100, overlap=20)

    assert len(chunks) > 1
    assert all(chunk.endswith(("；", "。")) for chunk in chunks[:-1])
    assert all(not chunk.startswith(("项", "明", "重", "要", "段", "包")) for chunk in chunks[1:])


def test_search_returns_component_scores(client: TestClient, tenant_headers: dict[str, str], document: dict):
    response = client.post("/search", headers=tenant_headers, json={"query": "LIS 接口超时检查", "top_k": 5})
    assert response.status_code == 200
    first = response.json()["results"][0]
    assert response.json()["strategy"] == "bm25"
    assert response.json()["routing"]["reason_code"]
    assert first["document_id"] == document["id"]
    assert first["score"] > 0
    assert {"keyword_score", "vector_score", "chunk_id", "source"}.issubset(first)


def test_search_missing_kb_is_404(client: TestClient, tenant_headers: dict[str, str]):
    response = client.post(
        "/search", headers=tenant_headers, json={"query": "LIS timeout", "knowledge_base_id": 999}
    )
    assert response.status_code == 404
