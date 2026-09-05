"""Grounded question-answering HTTP endpoint."""

from fastapi import APIRouter, Response

from app.api.deps import RequestIdDep, SettingsDep, TenantContext
from app.exceptions import AppError
from app.models.answers import AnswerRequest, AnswerResponse
from app.security.audit import write_audit
from app.services.answers import answer

router = APIRouter(prefix="/answer", tags=["answers"])


@router.post("")
def grounded_answer(
    data: AnswerRequest,
    response: Response,
    context: TenantContext,
    settings: SettingsDep,
    request_id: RequestIdDep,
) -> AnswerResponse:
    result = answer(settings.database_path, settings, context.tenant_id, data)
    if result is None:
        raise AppError(404, "knowledge_base_not_found", "Knowledge base not found")
    response.headers["X-MedOps-Abstained"] = str(result.abstained).lower()
    response.headers["X-MedOps-Retrieval-Ms"] = str(result.retrieval_ms)
    response.headers["X-MedOps-Model-Ms"] = str(result.model_ms)
    response.headers["X-MedOps-Token-Usage"] = str(result.token_usage)
    write_audit(
        settings.database_path,
        request_id=request_id,
        actor=context.actor,
        tenant_id=context.tenant_id,
        action="answer",
        resource="rag",
        result="abstained" if result.abstained else "ok",
        details={
            "question": data.question,
            "reason": result.reason,
            "documents": [citation.document_id for citation in result.citations],
            "chunks": [citation.chunk_id for citation in result.citations],
            "provider": result.provider,
        },
    )
    return result
