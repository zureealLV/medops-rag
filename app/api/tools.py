"""Read-only allowlisted tool-calling endpoint."""

from fastapi import APIRouter

from app.api.deps import RequestIdDep, SettingsDep, TenantContext
from app.models.tools import ToolCallRequest, ToolCallResponse
from app.security.audit import write_audit
from app.services.tools import execute

router = APIRouter(prefix="/tools", tags=["tools"])


@router.post("/call")
def call_tool(
    data: ToolCallRequest,
    context: TenantContext,
    settings: SettingsDep,
    request_id: RequestIdDep,
) -> ToolCallResponse:
    try:
        result = execute(settings.database_path, context.tenant_id, data.name, data.arguments)
    except Exception:
        write_audit(
            settings.database_path,
            request_id=request_id,
            actor=context.actor,
            tenant_id=context.tenant_id,
            action="tool_call",
            resource=data.name,
            result="denied",
            details={"arguments": data.arguments},
        )
        raise
    write_audit(
        settings.database_path,
        request_id=request_id,
        actor=context.actor,
        tenant_id=context.tenant_id,
        action="tool_call",
        resource=data.name,
        result="ok",
        details={"arguments": data.arguments},
    )
    return ToolCallResponse(name=data.name, result=result)
