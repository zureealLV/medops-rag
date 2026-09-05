"""Health endpoint tests."""

from fastapi.testclient import TestClient


def test_health_is_public_and_reports_database(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.0.0", "database": "ok"}
    assert response.headers["X-Request-ID"]


def test_openapi_lists_rag_endpoints(client: TestClient):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/search", "/answer", "/tools/call"}.issubset(paths)
