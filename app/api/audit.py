"""Tenant-scoped audit-log endpoint for demonstrations."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import SettingsDep, TenantContext
from app.models.audit import AuditEvent
from app.repositories.audit_logs import list_recent

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("")
def audit_logs(
    context: TenantContext,
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AuditEvent]:
    return list_recent(settings.database_path, context.tenant_id, limit=limit)
