"""API-key authentication, role authorization, and tenant isolation tests."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import initialize, transaction
from app.main import create_app
from app.repositories.api_credentials import create_credential, revoke_credential


def _credential(path: Path, tenant: str, name: str, role: str) -> tuple[str, str]:
    identity, token = create_credential(
        path,
        tenant_id=tenant,
        name=name,
        role=role,  # type: ignore[arg-type]
    )
    return identity.credential_id, token


def _headers(token: str, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **extra}


def test_api_key_required_and_identity_is_server_resolved(tmp_path: Path):
    database = tmp_path / "auth.db"
    initialize(database)
    credential_id, token = _credential(database, "hospital-a", "automation", "viewer")
    settings = Settings(database_path=database, auth_mode="api_key")

    with TestClient(create_app(settings)) as client:
        missing = client.get("/auth/whoami")
        assert missing.status_code == 401
        assert missing.headers["www-authenticate"] == "Bearer"

        malformed = client.get("/auth/whoami", headers=_headers("not-a-medops-key"))
        assert malformed.status_code == 401

        response = client.get(
            "/auth/whoami",
            headers=_headers(token, **{"X-Tenant-ID": "hospital-forged", "X-Actor-ID": "mallory"}),
        )
        assert response.status_code == 200
        assert response.json() == {
            "tenant_id": "hospital-a",
            "actor": "automation",
            "role": "viewer",
            "credential_id": credential_id,
            "auth_mode": "api_key",
        }


def test_roles_tenant_isolation_revocation_and_hash_only_storage(tmp_path: Path):
    database = tmp_path / "roles.db"
    initialize(database)
    admin_id, admin_token = _credential(database, "hospital-a", "admin-a", "admin")
    _, other_admin_token = _credential(database, "hospital-b", "admin-b", "admin")
    _, editor_token = _credential(database, "hospital-a", "editor-a", "editor")
    viewer_id, viewer_token = _credential(database, "hospital-a", "viewer-a", "viewer")
    settings = Settings(database_path=database, auth_mode="api_key")

    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/knowledge-bases",
            headers=_headers(admin_token),
            json={"name": "Operations", "description": "Synthetic runbooks"},
        )
        assert created.status_code == 201
        kb_id = created.json()["id"]

        # The authenticated credential wins over spoofed tenancy headers.
        isolated = client.get(
            "/knowledge-bases",
            headers=_headers(other_admin_token, **{"X-Tenant-ID": "hospital-a"}),
        )
        assert isolated.status_code == 200
        assert isolated.json() == []
        assert (
            client.get(f"/knowledge-bases/{kb_id}", headers=_headers(other_admin_token)).status_code
            == 404
        )

        assert client.get("/knowledge-bases", headers=_headers(viewer_token)).status_code == 200
        search = client.post(
            "/search",
            headers=_headers(viewer_token),
            json={"query": "gateway timeout", "knowledge_base_id": kb_id},
        )
        assert search.status_code == 200
        denied = client.post(
            "/knowledge-bases",
            headers=_headers(viewer_token),
            json={"name": "Denied"},
        )
        assert denied.status_code == 403
        assert denied.json()["code"] == "permission_denied"

        edited = client.post(
            "/knowledge-bases",
            headers=_headers(editor_token),
            json={"name": "Editor KB"},
        )
        assert edited.status_code == 201
        assert client.get("/audit-logs", headers=_headers(editor_token)).status_code == 403
        assert (
            client.post(
                "/users",
                headers=_headers(editor_token),
                json={"name": "Nope", "email": "nope@example.test"},
            ).status_code
            == 403
        )

        admin_user = client.post(
            "/users",
            headers=_headers(admin_token),
            json={"name": "Alice", "email": "alice@example.test"},
        )
        assert admin_user.status_code == 201
        assert client.get("/audit-logs", headers=_headers(admin_token)).status_code == 200

        assert revoke_credential(database, tenant_id="hospital-a", credential_id=viewer_id)
        assert client.get("/auth/whoami", headers=_headers(viewer_token)).status_code == 401

    with transaction(database) as connection:
        row = connection.execute(
            "SELECT key_prefix, secret_hash, salt, revoked_at FROM api_credentials WHERE id = ?",
            (viewer_id,),
        ).fetchone()
        stored_text = " ".join(str(value) for value in row)
    assert viewer_token not in stored_text
    assert isinstance(row["secret_hash"], bytes) and len(row["secret_hash"]) == 32
    assert isinstance(row["salt"], bytes) and len(row["salt"]) == 16
    assert row["revoked_at"] is not None
    assert admin_id != viewer_id
