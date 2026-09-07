"""Ingestion queue use cases and one-job worker execution."""

from __future__ import annotations

import time
from pathlib import Path

from app.config import Settings
from app.exceptions import AppError
from app.ingestion import parse_bytes
from app.models.jobs import IngestionJob
from app.observability import record_pipeline_metric
from app.repositories import ingestion_jobs as repository
from app.repositories.knowledge_bases import get as get_kb
from app.services.documents import create_from_parsed


def enqueue(
    path: Path, tenant_id: str, kb_id: int, key: str, filename: str, mime: str | None, content: bytes
) -> tuple[IngestionJob, bool]:
    if get_kb(path, tenant_id, kb_id) is None:
        raise AppError(404, "knowledge_base_not_found", "Knowledge base not found")
    return repository.enqueue(path, tenant_id, kb_id, key, filename, mime, content)


def get(path: Path, tenant_id: str, job_id: str) -> IngestionJob | None:
    return repository.get(path, tenant_id, job_id)


def cancel(path: Path, tenant_id: str, job_id: str) -> bool:
    return repository.cancel(path, tenant_id, job_id)


def process_next(
    path: Path, settings: Settings, worker_id: str, lease_seconds: float = 30.0, now: float | None = None
) -> str | None:
    claimed = repository.claim(path, worker_id, lease_seconds, now)
    if claimed is None:
        return None
    job_id = str(claimed["id"])
    stage = "parse_ocr"
    started = time.perf_counter()
    try:
        content = claimed["content"]
        if content is None:
            raise AppError(409, "job_payload_missing", "Queued job payload is unavailable")
        parsed = parse_bytes(
            claimed["filename"],
            bytes(content),
            claimed["declared_mime"],
            ocr_enabled=settings.ocr_enabled,
            ocr_min_confidence=settings.ocr_min_confidence,
            max_image_pixels=settings.max_image_pixels,
            max_archive_entries=settings.max_archive_entries,
            max_archive_uncompressed_bytes=settings.max_archive_uncompressed_bytes,
            max_archive_entry_bytes=settings.max_archive_entry_bytes,
            max_archive_compression_ratio=settings.max_archive_compression_ratio,
            max_pdf_pages=settings.max_pdf_pages,
        )
        record_pipeline_metric(
            path,
            tenant_id=claimed["tenant_id"],
            job_id=job_id,
            pipeline="ingestion",
            stage=stage,
            outcome="ok",
            duration_ms=(time.perf_counter() - started) * 1000,
            provider=parsed.parser,
            details={"artifact_count": len(parsed.artifacts), "warning_count": len(parsed.warnings)},
        )
        stage = "persist_index"
        started = time.perf_counter()
        document, _ = create_from_parsed(
            path, settings, claimed["tenant_id"], claimed["knowledge_base_id"], parsed
        )
        if document is None:
            raise AppError(404, "knowledge_base_not_found", "Knowledge base not found")
        record_pipeline_metric(
            path,
            tenant_id=claimed["tenant_id"],
            job_id=job_id,
            pipeline="ingestion",
            stage=stage,
            outcome="ok",
            duration_ms=(time.perf_counter() - started) * 1000,
            details={"document_id": document.id},
        )
        repository.succeed(path, claimed["id"], worker_id, document.id)
    except AppError as exc:
        record_pipeline_metric(
            path,
            tenant_id=claimed["tenant_id"],
            job_id=job_id,
            pipeline="ingestion",
            stage=stage,
            outcome="error",
            duration_ms=(time.perf_counter() - started) * 1000,
            details={"error_code": exc.code},
        )
        repository.fail(path, claimed["id"], worker_id, exc.code, exc.message, retryable=False)
    except Exception as exc:
        record_pipeline_metric(
            path,
            tenant_id=claimed["tenant_id"],
            job_id=job_id,
            pipeline="ingestion",
            stage=stage,
            outcome="error",
            duration_ms=(time.perf_counter() - started) * 1000,
            details={"error_code": "worker_error"},
        )
        repository.fail(path, claimed["id"], worker_id, "worker_error", str(exc)[:500], retryable=True)
    return job_id
