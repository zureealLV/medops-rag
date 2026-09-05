"""Knowledge-base HTTP endpoints."""

from typing import Annotated

from fastapi import APIRouter, Path, Response

from app.api.deps import SettingsDep, TenantContext
from app.exceptions import AppError
from app.models.knowledge_bases import KnowledgeBase, KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.services import knowledge_bases as service

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])
KbId = Annotated[int, Path(ge=1)]


@router.post("", status_code=201)
def create_knowledge_base(
    data: KnowledgeBaseCreate, context: TenantContext, settings: SettingsDep
) -> KnowledgeBase:
    return service.create(settings.database_path, context.tenant_id, data)


@router.get("")
def list_knowledge_bases(context: TenantContext, settings: SettingsDep) -> list[KnowledgeBase]:
    return service.list_all(settings.database_path, context.tenant_id)


@router.get("/{kb_id}")
def get_knowledge_base(kb_id: KbId, context: TenantContext, settings: SettingsDep) -> KnowledgeBase:
    result = service.get(settings.database_path, context.tenant_id, kb_id)
    if result is None:
        raise AppError(404, "knowledge_base_not_found", "Knowledge base not found")
    return result


@router.patch("/{kb_id}")
def update_knowledge_base(
    data: KnowledgeBaseUpdate, kb_id: KbId, context: TenantContext, settings: SettingsDep
) -> KnowledgeBase:
    result = service.update(settings.database_path, context.tenant_id, kb_id, data)
    if result is None:
        raise AppError(404, "knowledge_base_not_found", "Knowledge base not found")
    return result


@router.delete("/{kb_id}", status_code=204)
def delete_knowledge_base(kb_id: KbId, context: TenantContext, settings: SettingsDep) -> Response:
    if not service.delete(settings.database_path, context.tenant_id, kb_id):
        raise AppError(404, "knowledge_base_not_found", "Knowledge base not found")
    return Response(status_code=204)
