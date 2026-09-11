"""Authenticated identity introspection."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import TenantContext

router = APIRouter(prefix="/auth", tags=["auth"])


class IdentityResponse(BaseModel):
    tenant_id: str
    actor: str
    role: str
    credential_id: str | None
    auth_mode: str


@router.get("/whoami")
def whoami(context: TenantContext) -> IdentityResponse:
    return IdentityResponse(
        tenant_id=context.tenant_id,
        actor=context.actor,
        role=context.role,
        credential_id=context.credential_id,
        auth_mode=context.auth_mode,
    )
