"""User API success and failure tests."""

from fastapi.testclient import TestClient


def test_create_and_get_user(client: TestClient, tenant_headers: dict[str, str]):
    created = client.post(
        "/users", headers=tenant_headers, json={"name": "Alice", "email": "alice@example.test"}
    )
    assert created.status_code == 201
    fetched = client.get(f"/users/{created.json()['id']}", headers=tenant_headers)
    assert fetched.status_code == 200
    assert fetched.json()["tenant_id"] == "hospital-a"


def test_user_validation_and_not_found(client: TestClient, tenant_headers: dict[str, str]):
    assert client.post("/users", headers=tenant_headers, json={"name": "Alice"}).status_code == 422
    response = client.get("/users/999", headers=tenant_headers)
    assert response.status_code == 404
    assert response.json()["code"] == "user_not_found"


def test_tenant_header_required(client: TestClient):
    response = client.get("/users/1")
    assert response.status_code == 422
