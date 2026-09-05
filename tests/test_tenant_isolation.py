"""Cross-tenant access denial tests."""

from fastapi.testclient import TestClient


def test_other_tenant_cannot_read_or_retrieve_document(
    client: TestClient, tenant_headers: dict[str, str], document: dict
):
    other = {"X-Tenant-ID": "hospital-b", "X-Actor-ID": "intruder"}
    assert client.get(f"/documents/{document['id']}", headers=other).status_code == 404
    search = client.post("/search", headers=other, json={"query": "LIS 接口超时"})
    assert search.status_code == 200
    assert search.json()["results"] == []


def test_cross_tenant_kb_id_is_hidden(client: TestClient, tenant_headers: dict[str, str], kb: dict):
    other = {"X-Tenant-ID": "hospital-b"}
    response = client.post("/search", headers=other, json={"query": "LIS", "knowledge_base_id": kb["id"]})
    assert response.status_code == 404
    logs = client.get("/audit-logs", headers=other).json()
    assert logs[0]["result"] == "denied"
