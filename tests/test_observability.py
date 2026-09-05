"""Request tracing and performance-metric tests."""

from fastapi.testclient import TestClient

from app.db import transaction


def test_request_id_and_metric_are_recorded(client: TestClient):
    response = client.get("/health", headers={"X-Request-ID": "fixed-request-id"})
    assert response.headers["X-Request-ID"] == "fixed-request-id"
    assert "app;dur=" in response.headers["Server-Timing"]
    path = client.app.state.settings.database_path
    with transaction(path) as connection:
        row = connection.execute(
            "SELECT request_id, path, status_code, latency_ms FROM request_metrics WHERE request_id = ?",
            ("fixed-request-id",),
        ).fetchone()
    assert row["path"] == "/health"
    assert row["status_code"] == 200
    assert row["latency_ms"] >= 0
