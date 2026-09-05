"""Knowledge-base CRUD tests."""

from fastapi.testclient import TestClient


def test_knowledge_base_crud(client: TestClient, tenant_headers: dict[str, str]):
    created = client.post("/knowledge-bases", headers=tenant_headers, json={"name": "PACS"})
    assert created.status_code == 201
    kb_id = created.json()["id"]
    assert client.get("/knowledge-bases", headers=tenant_headers).json()[0]["name"] == "PACS"
    updated = client.patch(
        f"/knowledge-bases/{kb_id}", headers=tenant_headers, json={"description": "Imaging ops"}
    )
    assert updated.json()["description"] == "Imaging ops"
    assert client.delete(f"/knowledge-bases/{kb_id}", headers=tenant_headers).status_code == 204
    assert client.get(f"/knowledge-bases/{kb_id}", headers=tenant_headers).status_code == 404


def test_duplicate_name_is_conflict(client: TestClient, tenant_headers: dict[str, str], kb: dict):
    response = client.post("/knowledge-bases", headers=tenant_headers, json={"name": kb["name"]})
    assert response.status_code == 409
    assert response.json()["code"] == "knowledge_base_exists"
