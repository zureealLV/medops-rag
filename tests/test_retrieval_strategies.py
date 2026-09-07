"""Retrieval strategy schema and benchmark smoke tests."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.retrieval.query_transform import hypothetical_document, rewrite_query


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


def test_explicit_query_transforms_are_visible_and_bounded(
    client: TestClient, tenant_headers: dict[str, str], kb: dict, document: dict
):
    multi = client.post(
        "/search",
        headers=tenant_headers,
        json={
            "query": "How should operators remediate LIS gateway timeout?",
            "knowledge_base_id": kb["id"],
            "strategy": "bm25",
            "query_transform": "multi_query",
        },
    )
    assert multi.status_code == 200
    assert multi.json()["query_transform"] == "multi_query"
    assert len(multi.json()["transformed_queries"]) == 2
    hyde = client.post(
        "/search",
        headers=tenant_headers,
        json={
            "query": "LIS gateway timeout should be remediated how?",
            "knowledge_base_id": kb["id"],
            "strategy": "bm25",
            "query_transform": "hyde",
        },
    )
    assert hyde.status_code == 200
    assert hyde.json()["query_transform"] == "hyde"
    assert hyde.json()["transformed_queries"][0].startswith("Hospital IT operations runbook")
    assert len(hyde.json()["transformed_queries"][0]) <= 1800


def test_hyde_auto_policy_is_disabled_by_default_and_opt_in(tmp_path: Path):
    headers = {"X-Tenant-ID": "hospital-a", "X-Actor-ID": "tester"}
    for enabled, expected in ((False, "none"), (True, "hyde")):
        settings = Settings(database_path=tmp_path / f"hyde-{enabled}.db", hyde_auto_enabled=enabled)
        with TestClient(create_app(settings)) as client:
            kb_id = client.post("/knowledge-bases", headers=headers, json={"name": "HyDE"}).json()["id"]
            client.post(
                f"/knowledge-bases/{kb_id}/documents",
                headers=headers,
                json={
                    "title": "LIS",
                    "content": "Inspect the LIS gateway logs before a controlled restart.",
                    "source": "lis.md",
                },
            )
            response = client.post(
                "/search",
                headers=headers,
                json={
                    "query": "Why and how should operators investigate a recurring LIS gateway timeout?",
                    "knowledge_base_id": kb_id,
                    "strategy": "bm25",
                },
            )
            assert response.status_code == 200
            assert response.json()["query_transform"] == expected


def test_query_rewrite_removes_boilerplate_without_losing_incident_terms():
    rewritten = rewrite_query("遇到 PACS DICOM TLS 握手失败，第一项受控操作是什么？")
    assert "PACS DICOM TLS 握手失败" in rewritten
    assert "第一项受控操作是什么" not in rewritten
    hypothetical = hypothetical_document("如何处理 RIS worklist mismatch?")
    assert "RIS worklist mismatch" in hypothetical
    assert len(hypothetical) <= 1800
