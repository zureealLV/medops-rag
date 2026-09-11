"""Allowlisted and rejected tool-call tests."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import initialize
from app.main import create_app
from app.repositories.api_credentials import create_credential


def test_allowlisted_read_only_tools(client: TestClient, tenant_headers: dict[str, str], document: dict):
    status = client.post(
        "/tools/call", headers=tenant_headers, json={"name": "get_system_status", "arguments": {}}
    )
    assert status.status_code == 200
    metadata = client.post(
        "/tools/call",
        headers=tenant_headers,
        json={"name": "get_document_metadata", "arguments": {"document_id": document["id"]}},
    )
    assert metadata.status_code == 200
    assert "content" not in metadata.json()["result"]


def test_unregistered_and_invalid_tool_calls_are_rejected(client: TestClient, tenant_headers: dict[str, str]):
    denied = client.post(
        "/tools/call", headers=tenant_headers, json={"name": "run_shell", "arguments": {"command": "whoami"}}
    )
    assert denied.status_code == 403
    invalid = client.post(
        "/tools/call",
        headers=tenant_headers,
        json={"name": "get_document_metadata", "arguments": {"document_id": "bad"}},
    )
    assert invalid.status_code == 422


def test_direct_tool_selection_is_admin_only(tmp_path: Path):
    database = tmp_path / "tool-roles.db"
    initialize(database)
    _, viewer_token = create_credential(
        database, tenant_id="hospital-a", name="viewer", role="viewer"
    )
    _, editor_token = create_credential(
        database, tenant_id="hospital-a", name="editor", role="editor"
    )
    _, admin_token = create_credential(
        database, tenant_id="hospital-a", name="admin", role="admin"
    )
    settings = Settings(database_path=database, auth_mode="api_key")

    with TestClient(create_app(settings)) as client:
        for token in (viewer_token, editor_token):
            denied = client.post(
                "/tools/call",
                headers={"Authorization": f"Bearer {token}"},
                json={"name": "get_system_status", "arguments": {}},
            )
            assert denied.status_code == 403
            assert denied.json()["code"] == "permission_denied"
        allowed = client.post(
            "/tools/call",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "get_system_status", "arguments": {}},
        )
        assert allowed.status_code == 200
