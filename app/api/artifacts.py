"""Tenant-scoped image artifact and visual-search endpoints."""

from typing import Annotated

from fastapi import APIRouter, Path, Response

from app.api.deps import RequestIdDep, SettingsDep, TenantContext
from app.exceptions import AppError
from app.models.artifacts import DocumentArtifact, VisualSearchRequest, VisualSearchResponse
from app.security.audit import write_audit
from app.services import artifacts as service

router = APIRouter(tags=["visual evidence"])
PositiveId = Annotated[int, Path(ge=1)]


@router.get("/documents/{document_id}/artifacts")
def list_document_artifacts(
    document_id: PositiveId, context: TenantContext, settings: SettingsDep
) -> list[DocumentArtifact]:
    result = service.list_for_document(settings.database_path, context.tenant_id, document_id)
    if result is None:
        raise AppError(404, "document_not_found", "Document not found")
    return result


@router.get("/artifacts/{artifact_id}/content")
def get_artifact_content(
    artifact_id: PositiveId, context: TenantContext, settings: SettingsDep
) -> Response:
    result = service.content(settings.database_path, context.tenant_id, artifact_id)
    if result is None:
        raise AppError(404, "artifact_not_found", "Artifact not found")
    payload, mime_type, sha256 = result
    return Response(
        content=payload,
        media_type=mime_type,
        headers={"ETag": f'"{sha256}"', "Cache-Control": "private, max-age=3600"},
    )


@router.post("/visual-search")
def visual_search(
    data: VisualSearchRequest,
    context: TenantContext,
    settings: SettingsDep,
    request_id: RequestIdDep,
) -> VisualSearchResponse:
    result = service.search(settings.database_path, settings, context.tenant_id, data)
    if result is None:
        raise AppError(404, "knowledge_base_not_found", "Knowledge base not found")
    write_audit(
        settings.database_path,
        request_id=request_id,
        actor=context.actor,
        tenant_id=context.tenant_id,
        action="visual_search",
        resource=str(data.knowledge_base_id or "all"),
        result="ok",
        details={"strategy": data.strategy, "result_count": len(result.results)},
    )
    return result
