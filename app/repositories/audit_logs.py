"""Audit-event persistence operations."""

from pathlib import Path

from app.db import transaction
from app.models.audit import AuditEvent


def list_recent(path: Path, tenant_id: str, *, limit: int = 50) -> list[AuditEvent]:
    with transaction(path) as connection:
        rows = connection.execute(
            """SELECT id, request_id, actor, tenant_id, action, resource, result, details, created_at
               FROM audit_logs WHERE tenant_id = ? ORDER BY id DESC LIMIT ?""",
            (tenant_id, limit),
        ).fetchall()
    return [AuditEvent(**dict(row)) for row in rows]
