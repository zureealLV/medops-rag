"""Admin model Provider configuration boundary and secret-handling tests."""

import json
import sqlite3
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import initialize
from app.main import create_app
from app.repositories.api_credentials import create_credential


def test_runtime_model_config_is_masked_and_applied_without_persisting_secret(
    client: TestClient,
    tenant_headers: dict[str, str],
) -> None:
    initial = client.get("/system/model-config", headers=tenant_headers)
    assert initial.status_code == 200
    assert initial.json() == {
        "provider": "deepseek",
        "model_name": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "api_key_configured": False,
        "api_key_source": "none",
        "vision_enabled": False,
        "activation_source": "environment",
        "session_only": True,
    }

    secret = "test-secret-runtime"
    applied = client.put(
        "/system/model-config",
        headers=tenant_headers,
        json={
            "provider": "openai",
            "model_name": "gpt-4o-mini",
            "base_url": "https://api.openai.com/v1",
            "api_key": secret,
            "vision_enabled": True,
        },
    )
    assert applied.status_code == 200
    payload = applied.json()
    assert payload["api_key_configured"] is True
    assert payload["api_key_source"] == "runtime"
    assert payload["activation_source"] == "runtime"
    assert secret not in applied.text
    assert client.app.state.settings.model_api_key == secret
    assert client.app.state.settings_ref["value"] is client.app.state.settings

    with sqlite3.connect(client.app.state.settings.database_path) as connection:
        details = connection.execute(
            "SELECT details FROM audit_logs WHERE action = 'model_config_apply'"
        ).fetchone()[0]
    assert secret not in details
    assert json.loads(details)["api_key_changed"] is True


def test_model_config_requires_admin_in_api_key_mode(tmp_path: Path) -> None:
    database = tmp_path / "model-config-auth.db"
    initialize(database)
    _, viewer_token = create_credential(
        database,
        tenant_id="hospital-a",
        name="viewer",
        role="viewer",
    )
    _, admin_token = create_credential(
        database,
        tenant_id="hospital-a",
        name="admin",
        role="admin",
    )
    settings = Settings(database_path=database, auth_mode="api_key")
    with TestClient(create_app(settings)) as client:
        viewer = client.get(
            "/system/model-config",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert viewer.status_code == 403
        admin = client.get(
            "/system/model-config",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert admin.status_code == 200


def test_model_config_connection_test_uses_ephemeral_key_and_sanitized_response(
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}

    def provider(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("Authorization")
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "OK from fixture"}}]},
        )

    settings = Settings(database_path=tmp_path / "model-config-test.db", app_env="test")
    transport = httpx.MockTransport(provider)
    with TestClient(create_app(settings, model_async_transport=transport)) as client:
        response = client.post(
            "/system/model-config/test",
            headers={"X-Tenant-ID": "hospital-a", "X-Actor-ID": "admin"},
            json={
                "provider": "custom",
                "model_name": "fixture-model",
                "base_url": "https://provider.example/v1",
                "api_key": "test-secret-ephemeral",
            },
        )
    assert response.status_code == 200
    assert response.json()["response_preview"] == "OK from fixture"
    assert seen["authorization"] == "Bearer test-secret-ephemeral"
    assert seen["payload"] == {
        "model": "fixture-model",
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "temperature": 0,
        "max_tokens": 8,
        "stream": False,
    }
    assert "test-secret-ephemeral" not in response.text


def test_model_config_rejects_unsafe_or_malformed_endpoints(
    client: TestClient,
    tenant_headers: dict[str, str],
) -> None:
    malformed = client.put(
        "/system/model-config",
        headers=tenant_headers,
        json={
            "provider": "custom",
            "model_name": "bad",
            "base_url": "file:///etc/passwd",
        },
    )
    assert malformed.status_code == 422

    unsafe = client.post(
        "/system/model-config/test",
        headers=tenant_headers,
        json={
            "provider": "custom",
            "model_name": "bad",
            "base_url": "http://169.254.169.254/latest/meta-data",
        },
    )
    assert unsafe.status_code == 422
    assert unsafe.json()["code"] == "unsafe_model_endpoint"
