"""Audit-event construction with PII-safe details."""

from __future__ import annotations

import json
from pathlib import Path

from app.db import transaction
from app.security.pii import redact


def write_audit(
    database_path: Path,
    *,
    request_id: str,
    actor: str,
    tenant_id: str,
    action: str,
    resource: str,
    result: str,
    details: dict[str, object] | None = None,
) -> None:
    safe_details = redact(json.dumps(details or {}, ensure_ascii=False))
    with transaction(database_path) as connection:
        connection.execute(
            """INSERT INTO audit_logs
               (request_id, actor, tenant_id, action, resource, result, details)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (request_id, actor, tenant_id, action, resource, result, safe_details),
        )
