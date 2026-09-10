"""Health endpoint tests."""

from fastapi.testclient import TestClient


def test_health_is_public_and_reports_database(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "3.2.0", "database": "ok"}
    assert response.headers["X-Request-ID"]


def test_liveness_is_dependency_free_and_not_persisted(client: TestClient):
    from app.db import transaction

    response = client.get("/live")
    ready = client.get("/ready")
    assert response.status_code == ready.status_code == 200
    assert response.json() == {"status": "ok", "version": "3.2.0"}

    database = client.app.state.settings.database_path
    with transaction(database) as connection:
        live_rows = connection.execute(
            "SELECT COUNT(*) FROM request_metrics WHERE path = '/live'"
        ).fetchone()[0]
    assert live_rows == 0


def test_openapi_lists_rag_endpoints(client: TestClient):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/search", "/answer", "/tools/call"}.issubset(paths)


def test_web_console_is_served_and_root_redirects(client: TestClient):
    root = client.get("/", follow_redirects=False)
    assert root.status_code == 307
    assert root.headers["location"] == "/ui/"

    page = client.get("/ui/")
    assert page.status_code == 200
    if '<div id="app"></div>' in page.text:
        assert "MedOps 企业知识控制台" in page.text
        assert "/ui/assets/" in page.text
    else:
        assert "MedOps 医疗知识助手" in page.text
        script = client.get("/ui/app.js")
        assert script.status_code == 200
        assert "[来源${index + 1}]" in script.text
        assert "SCORE ${" not in script.text
        styles = client.get("/ui/styles.css")
        assert styles.status_code == 200
        assert "--surface-solid: #ffffff" in styles.text
