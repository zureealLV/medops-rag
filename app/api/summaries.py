"""Asynchronous multi-document Map-Reduce summary endpoints."""

from typing import Annotated

from fastapi import APIRouter, Header, Path, Response

from app.api.deps import SettingsDep, TenantContext
from app.exceptions import AppError
from app.models.summaries import SummaryJob, SummaryJobCreate
from app.services import summary_jobs as service

router = APIRouter(tags=["summary-jobs"])
PositiveId = Annotated[int, Path(ge=1)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]


@router.post("/knowledge-bases/{kb_id}/summary-jobs", status_code=202)
def enqueue_summary(
    kb_id: PositiveId,
    data: SummaryJobCreate,
    key: IdempotencyKey,
    response: Response,
    context: TenantContext,
    settings: SettingsDep,
) -> SummaryJob:
    job, duplicate = service.enqueue(
        settings.database_path, context.tenant_id, kb_id, key, data
    )
    if duplicate:
        response.status_code = 200
    response.headers["Location"] = f"/summary-jobs/{job.id}"
    return job


@router.get("/summary-jobs/{job_id}")
def get_summary(job_id: str, context: TenantContext, settings: SettingsDep) -> SummaryJob:
    job = service.get(settings.database_path, context.tenant_id, job_id)
    if job is None:
        raise AppError(404, "summary_job_not_found", "Summary job not found")
    return job


@router.post("/summary-jobs/{job_id}/cancel")
def cancel_summary(job_id: str, context: TenantContext, settings: SettingsDep) -> SummaryJob:
    if not service.cancel(settings.database_path, context.tenant_id, job_id):
        raise AppError(409, "summary_job_not_cancellable", "Job does not exist or is already terminal")
    job = service.get(settings.database_path, context.tenant_id, job_id)
    assert job is not None
    return job
