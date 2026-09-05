"""Hybrid-search HTTP endpoint."""

from fastapi import APIRouter

from app.api.deps import RequestIdDep, SettingsDep, TenantContext
from app.exceptions import AppError
from app.models.retrieval import SearchRequest, SearchResponse
from app.security.audit import write_audit
from app.services.retrieval import search

router = APIRouter(prefix="/search", tags=["retrieval"])


@router.post("")
def hybrid_search(
    data: SearchRequest,
    context: TenantContext,
    settings: SettingsDep,
    request_id: RequestIdDep,
) -> SearchResponse:
    result = search(settings.database_path, context.tenant_id, data)
    if result is None:
        write_audit(
            settings.database_path,
            request_id=request_id,
            actor=context.actor,
            tenant_id=context.tenant_id,
            action="search",
            resource=str(data.knowledge_base_id),
            result="denied",
            details={"reason": "knowledge_base_not_found"},
        )
        raise AppError(404, "knowledge_base_not_found", "Knowledge base not found")
    write_audit(
        settings.database_path,
        request_id=request_id,
        actor=context.actor,
        tenant_id=context.tenant_id,
        action="search",
        resource="chunks",
        result="ok",
        details={"query": data.query, "result_count": len(result.results)},
    )
    return result
