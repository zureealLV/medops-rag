"""Document CRUD and ingestion endpoints."""

from typing import Annotated

from fastapi import APIRouter, File, Path, Response, UploadFile

from app.api.deps import SettingsDep, TenantContext
from app.exceptions import AppError
from app.ingestion import parse_bytes
from app.models.documents import Document, DocumentCreate, DocumentElement, DocumentUpdate
from app.services import documents as service

router = APIRouter(tags=["documents"])
PositiveId = Annotated[int, Path(ge=1)]
UploadedFile = Annotated[
    UploadFile,
    File(description="TXT, Markdown, PDF, DOCX, PPTX, PNG, JPEG, or WebP document"),
]


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
    response: Response,
    context: TenantContext,
    settings: SettingsDep,
) -> Document:
    filename = file.filename or "upload.txt"
    raw = file.file.read(settings.max_upload_bytes + 1)
    if len(raw) > settings.max_upload_bytes:
        raise AppError(
            413, "document_too_large", f"Uploads are limited to {settings.max_upload_bytes} bytes"
        )
    parsed = parse_bytes(
        filename,
        raw,
        file.content_type,
        ocr_enabled=settings.ocr_enabled,
        ocr_min_confidence=settings.ocr_min_confidence,
        max_image_pixels=settings.max_image_pixels,
    )
    result, deduplicated = service.create_from_parsed(
        settings.database_path, settings, context.tenant_id, kb_id, parsed
    )
    if result is None:
        raise AppError(404, "knowledge_base_not_found", "Knowledge base not found")
    if deduplicated:
        response.status_code = 200
    return result


@router.get("/documents/{document_id}/elements")
def list_document_elements(
    document_id: PositiveId, context: TenantContext, settings: SettingsDep
) -> list[DocumentElement]:
    result = service.list_elements(settings.database_path, context.tenant_id, document_id)
    if result is None:
        raise AppError(404, "document_not_found", "Document not found")
    return [DocumentElement(**item) for item in result]


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
