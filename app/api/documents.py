"""Document CRUD and ingestion endpoints."""

from pathlib import Path as FilePath
from typing import Annotated

from fastapi import APIRouter, File, Path, Response, UploadFile

from app.api.deps import SettingsDep, TenantContext
from app.exceptions import AppError
from app.models.documents import Document, DocumentCreate, DocumentUpdate
from app.retrieval.extract import extract_bytes
from app.services import documents as service

router = APIRouter(tags=["documents"])
PositiveId = Annotated[int, Path(ge=1)]
UploadedFile = Annotated[UploadFile, File(description="UTF-8 .txt or .md document")]


@router.post("/knowledge-bases/{kb_id}/documents", status_code=201)
def create_document(
    data: DocumentCreate, kb_id: PositiveId, context: TenantContext, settings: SettingsDep
) -> Document:
    result = service.create(settings.database_path, settings, context.tenant_id, kb_id, data)
    if result is None:
        raise AppError(404, "knowledge_base_not_found", "Knowledge base not found")
    return result


@router.get("/knowledge-bases/{kb_id}/documents")
def list_documents(kb_id: PositiveId, context: TenantContext, settings: SettingsDep) -> list[Document]:
    result = service.list_for_kb(settings.database_path, context.tenant_id, kb_id)
    if result is None:
        raise AppError(404, "knowledge_base_not_found", "Knowledge base not found")
    return result


@router.post("/knowledge-bases/{kb_id}/documents/upload", status_code=201)
def upload_document(
    kb_id: PositiveId,
    file: UploadedFile,
    context: TenantContext,
    settings: SettingsDep,
) -> Document:
    filename = file.filename or "upload.txt"
    raw = file.file.read(200_001)
    if len(raw) > 200_000:
        raise AppError(413, "document_too_large", "V1 uploads are limited to 200000 bytes")
    content = extract_bytes(filename, raw)
    result = service.create(
        settings.database_path,
        settings,
        context.tenant_id,
        kb_id,
        DocumentCreate(title=FilePath(filename).stem, content=content, source=filename),
    )
    if result is None:
        raise AppError(404, "knowledge_base_not_found", "Knowledge base not found")
    return result


@router.get("/documents/{document_id}")
def get_document(document_id: PositiveId, context: TenantContext, settings: SettingsDep) -> Document:
    result = service.get(settings.database_path, context.tenant_id, document_id)
    if result is None:
        raise AppError(404, "document_not_found", "Document not found")
    return result


@router.patch("/documents/{document_id}")
def update_document(
    data: DocumentUpdate, document_id: PositiveId, context: TenantContext, settings: SettingsDep
) -> Document:
    result = service.update(settings.database_path, settings, context.tenant_id, document_id, data)
    if result is None:
        raise AppError(404, "document_not_found", "Document not found")
    return result


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: PositiveId, context: TenantContext, settings: SettingsDep) -> Response:
    if not service.delete(settings.database_path, context.tenant_id, document_id):
        raise AppError(404, "document_not_found", "Document not found")
    return Response(status_code=204)
