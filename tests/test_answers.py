"""Citation, grounding, and refusal tests."""

from fastapi.testclient import TestClient


def test_grounded_answer_has_citations(client: TestClient, tenant_headers: dict[str, str], document: dict):
    response = client.post("/answer", headers=tenant_headers, json={"question": "LIS 接口超时先检查什么？"})
    assert response.status_code == 200
    body = response.json()
    assert body["abstained"] is False
    assert body["citations"][0]["document_id"] == document["id"]
    assert body["provider"] == "offline-extractive"


def test_unanswerable_question_abstains(client: TestClient, tenant_headers: dict[str, str], document: dict):
    response = client.post("/answer", headers=tenant_headers, json={"question": "月球基地氧气产量是多少？"})
    assert response.status_code == 200
    assert response.json()["abstained"] is True
    assert response.headers["X-MedOps-Abstained"] == "true"


def test_medical_advice_is_denied(client: TestClient, tenant_headers: dict[str, str], document: dict):
    response = client.post("/answer", headers=tenant_headers, json={"question": "头痛应该吃什么药和剂量？"})
    assert response.status_code == 200
    assert response.json()["reason"] == "medical_advice_denied"
