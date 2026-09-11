"""Hybrid-search HTTP endpoint."""

from fastapi import APIRouter, Response

from app.api.deps import RequestIdDep, SettingsDep, TenantContext
from app.exceptions import AppError
from app.models.retrieval import SearchRequest, SearchResponse
from app.security.audit import write_audit
from app.services.retrieval import search

router = APIRouter(prefix="/search", tags=["retrieval"])


def _effective_request(data: SearchRequest, context: TenantContext) -> SearchRequest:
    if context.role == "admin":
        return data
    return data.model_copy(update={"top_k": 5, "strategy": "auto", "query_transform": "auto"})


@router.post("")
def hybrid_search(
    data: SearchRequest,
    response: Response,
    context: TenantContext,
    settings: SettingsDep,
    request_id: RequestIdDep,
) -> SearchResponse:
    effective = _effective_request(data, context)
    result = search(settings.database_path, context.tenant_id, effective, settings)
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
    response.headers["X-MedOps-Retrieval-Ms"] = str(result.retrieval_ms)
    response.headers["X-MedOps-Retrieval-Profile"] = "text"
    response.headers["X-MedOps-Retrieval-Strategy"] = result.strategy
    write_audit(
        settings.database_path,
        request_id=request_id,
        actor=context.actor,
        tenant_id=context.tenant_id,
        action="search",
        resource="chunks",
        result="ok",
        details={
            "query": effective.query,
            "result_count": len(result.results),
            "strategy": result.strategy,
            "routing_reason": result.routing.reason_code if result.routing else None,
        },
    )
    return result
