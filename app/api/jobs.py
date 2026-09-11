"""Asynchronous ingestion job endpoints."""

from typing import Annotated

from fastapi import APIRouter, File, Header, Path, Response, UploadFile

from app.api.deps import SettingsDep, TenantContext
from app.exceptions import AppError
from app.models.jobs import IngestionJob
from app.services import ingestion_jobs as service

router = APIRouter(tags=["ingestion-jobs"])
PositiveId = Annotated[int, Path(ge=1)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]


@router.post("/knowledge-bases/{kb_id}/ingestion-jobs", status_code=202)
def enqueue_ingestion(
    kb_id: PositiveId,
    key: IdempotencyKey,
    file: Annotated[UploadFile, File()],
    response: Response,
    context: TenantContext,
    settings: SettingsDep,
) -> IngestionJob:
    raw = file.file.read(settings.max_upload_bytes + 1)
    if len(raw) > settings.max_upload_bytes:
        raise AppError(413, "document_too_large", f"Uploads are limited to {settings.max_upload_bytes} bytes")
    job, duplicate = service.enqueue(
        settings.database_path,
        context.tenant_id,
        kb_id,
        key,
        file.filename or "upload.txt",
        file.content_type,
        raw,
    )
    if duplicate:
        response.status_code = 200
    response.headers["Location"] = f"/ingestion-jobs/{job.id}"
    return job


@router.get("/ingestion-jobs/{job_id}")
def get_job(job_id: str, context: TenantContext, settings: SettingsDep) -> IngestionJob:
    job = service.get(settings.database_path, context.tenant_id, job_id)
    if job is None:
        raise AppError(404, "ingestion_job_not_found", "Ingestion job not found")
    return job


@router.post("/ingestion-jobs/{job_id}/cancel")
def cancel_job(job_id: str, context: TenantContext, settings: SettingsDep) -> IngestionJob:
    if not service.cancel(settings.database_path, context.tenant_id, job_id):
        raise AppError(409, "ingestion_job_not_cancellable", "Job does not exist or is already terminal")
    job = service.get(settings.database_path, context.tenant_id, job_id)
    assert job is not None
    return job
