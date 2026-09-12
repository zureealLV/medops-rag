"""MCP transport, tool discovery, tenant scope, and policy regression tests."""

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "Mcp-Protocol-Version": "2025-11-25",
}


def _call(client: TestClient, tenant_id: str, name: str, arguments: dict | None = None) -> dict:
    response = client.post(
        "/mcp/",
        headers={**MCP_HEADERS, "X-Tenant-ID": tenant_id, "X-Actor-ID": "mcp-test"},
        json={
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        },
    )
    assert response.status_code == 200
    return response.json()["result"]


def test_mcp_initialize_and_tool_schemas(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "mcp.db")
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        initialize = client.post(
            "/mcp/",
            headers={
                **MCP_HEADERS,
                "X-Tenant-ID": "hospital-a",
                "X-Actor-ID": "mcp-test",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "1"},
                },
            },
        )
        assert initialize.status_code == 200
        assert initialize.json()["result"]["serverInfo"] == {
            "description": "Tenant-scoped medical and medical-device evidence retrieval.",
            "name": "MedOps RAG",
            "version": "3.4.0",
        }

        tools = client.post(
            "/mcp/",
            headers={
                **MCP_HEADERS,
                "X-Tenant-ID": "hospital-a",
                "X-Actor-ID": "mcp-test",
            },
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert tools.status_code == 200
        listed = {tool["name"]: tool for tool in tools.json()["result"]["tools"]}
        assert set(listed) == {"list_knowledge_bases", "rag_search", "rag_answer"}
        assert "ctx" not in listed["rag_search"]["inputSchema"]["properties"]
        assert listed["rag_search"]["inputSchema"]["properties"]["top_k"]["maximum"] == 10


def test_mcp_allows_loopback_browser_origin_and_rejects_external_origin(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "mcp-origin.db")
    payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        local = client.post(
            "/mcp/",
            headers={**MCP_HEADERS, "Origin": "http://127.0.0.1:5175"},
            json=payload,
        )
        assert local.status_code == 200

        external = client.post(
            "/mcp/",
            headers={**MCP_HEADERS, "Origin": "https://attacker.example"},
            json=payload,
        )
        assert external.status_code == 403


def test_mcp_list_knowledge_bases_is_tenant_scoped(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "mcp-tenants.db")
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        for tenant, name in (("hospital-a", "甲院知识"), ("hospital-b", "乙院知识")):
            response = client.post(
                "/knowledge-bases",
                headers={"X-Tenant-ID": tenant, "X-Actor-ID": "seed"},
                json={"name": name, "description": None},
            )
            assert response.status_code == 201

        result = _call(client, "hospital-a", "list_knowledge_bases")
        assert result["isError"] is False
        assert [item["name"] for item in result["structuredContent"]["knowledge_bases"]] == [
            "甲院知识"
        ]


def test_mcp_answer_preserves_medical_advice_refusal(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "mcp-policy.db", policy_profile="medical")
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        result = _call(
            client,
            "hospital-a",
            "rag_answer",
            {"question": "头痛应该吃什么药和剂量？"},
        )
        assert result["isError"] is False
        assert result["structuredContent"]["abstained"] is True
        assert result["structuredContent"]["reason"] == "medical_advice_denied"
        with sqlite3.connect(settings.database_path) as connection:
            audit = connection.execute(
                """SELECT actor, tenant_id, action, result, details
                   FROM audit_logs ORDER BY id DESC LIMIT 1"""
            ).fetchone()
        assert audit is not None
        assert audit[:4] == ("mcp-test", "hospital-a", "mcp_answer", "abstained")
        assert json.loads(audit[4])["reason"] == "medical_advice_denied"


def test_mcp_api_key_mode_resolves_identity_server_side(tmp_path: Path):
    from app.db import initialize
    from app.repositories.api_credentials import create_credential

    database = tmp_path / "mcp-auth.db"
    initialize(database)
    _, token = create_credential(
        database,
        tenant_id="hospital-a",
        name="viewer-mcp",
        role="viewer",
    )
    settings = Settings(database_path=database, auth_mode="api_key")
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        response = client.post(
            "/mcp/",
            headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"},
            json={
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "list_knowledge_bases", "arguments": {}},
            },
        )
        assert response.status_code == 200
        assert response.json()["result"]["isError"] is False
