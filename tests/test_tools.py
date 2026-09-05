"""Allowlisted and rejected tool-call tests."""

from fastapi.testclient import TestClient


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
