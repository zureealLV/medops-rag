"""Hashed API credential persistence and verification."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.db import transaction

Role = Literal["viewer", "editor", "admin"]
VALID_ROLES: frozenset[str] = frozenset({"viewer", "editor", "admin"})


@dataclass(frozen=True, slots=True)
class CredentialIdentity:
    credential_id: str
    tenant_id: str
    actor: str
    role: Role


def _derive(secret: str, salt: bytes) -> bytes:
    return hashlib.scrypt(secret.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)


def create_credential(
    path: Path,
    *,
    tenant_id: str,
    name: str,
    role: Role,
) -> tuple[CredentialIdentity, str]:
    if role not in VALID_ROLES:
        raise ValueError(f"unsupported credential role: {role}")
    credential_id = str(uuid.uuid4())
    prefix = secrets.token_hex(6)
    secret = secrets.token_urlsafe(32)
    salt = secrets.token_bytes(16)
    secret_hash = _derive(secret, salt)
    actor = name.strip()[:80]
    if not actor:
        raise ValueError("credential name must not be blank")
    with transaction(path) as connection:
        connection.execute(
            """
            INSERT INTO api_credentials
                (id, tenant_id, name, key_prefix, secret_hash, salt, role)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (credential_id, tenant_id, actor, prefix, secret_hash, salt, role),
        )
    identity = CredentialIdentity(credential_id, tenant_id, actor, role)
    return identity, f"mops_{prefix}.{secret}"


def authenticate(path: Path, token: str) -> CredentialIdentity | None:
    try:
        prefix_part, secret = token.split(".", maxsplit=1)
    except ValueError:
        return None
    if not prefix_part.startswith("mops_") or not secret:
        return None
    prefix = prefix_part.removeprefix("mops_")
    if len(prefix) != 12 or any(char not in "0123456789abcdef" for char in prefix):
        return None

    with transaction(path) as connection:
        row = connection.execute(
            """
            SELECT id, tenant_id, name, role, secret_hash, salt
            FROM api_credentials
            WHERE key_prefix = ? AND revoked_at IS NULL
            """,
            (prefix,),
        ).fetchone()
        if row is None:
            return None
        candidate = _derive(secret, bytes(row["salt"]))
        if not hmac.compare_digest(candidate, bytes(row["secret_hash"])):
            return None
        connection.execute(
            "UPDATE api_credentials SET last_used_at = CURRENT_TIMESTAMP WHERE id = ?",
            (row["id"],),
        )
    return CredentialIdentity(row["id"], row["tenant_id"], row["name"], row["role"])


def revoke_credential(path: Path, *, tenant_id: str, credential_id: str) -> bool:
    with transaction(path) as connection:
        cursor = connection.execute(
            """
            UPDATE api_credentials
            SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP)
            WHERE id = ? AND tenant_id = ? AND revoked_at IS NULL
            """,
            (credential_id, tenant_id),
        )
    return cursor.rowcount == 1
