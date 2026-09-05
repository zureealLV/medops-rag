"""Audit-event response models."""

from pydantic import BaseModel


class AuditEvent(BaseModel):
    id: int
    request_id: str
    actor: str
    tenant_id: str
    action: str
    resource: str
    result: str
    details: str
    created_at: str
