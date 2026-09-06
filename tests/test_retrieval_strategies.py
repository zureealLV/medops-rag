"""Retrieval strategy schema and benchmark smoke tests."""

from fastapi.testclient import TestClient


def test_search_exposes_all_retrieval_components(
    client: TestClient, tenant_headers: dict[str, str], kb: dict, document: dict
):
    for strategy in ("keyword", "vector", "weighted", "bm25", "rrf"):
        response = client.post(
            "/search",
            headers=tenant_headers,
            json={
                "query": "LIS gateway timeout",
                "knowledge_base_id": kb["id"],
                "strategy": strategy,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["strategy"] == strategy
        assert payload["results"]
        assert set(payload["results"][0]) >= {
            "score",
            "keyword_score",
            "vector_score",
            "bm25_score",
        }


def test_unknown_retrieval_strategy_is_validation_error(
    client: TestClient, tenant_headers: dict[str, str], kb: dict
):
    response = client.post(
        "/search",
        headers=tenant_headers,
        json={"query": "PACS health", "knowledge_base_id": kb["id"], "strategy": "magic"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
