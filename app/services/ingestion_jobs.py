"""Ingestion queue use cases and one-job worker execution."""

from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.exceptions import AppError
from app.ingestion import parse_bytes
from app.models.jobs import IngestionJob
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
        )
        document, _ = create_from_parsed(
            path, settings, claimed["tenant_id"], claimed["knowledge_base_id"], parsed
        )
        if document is None:
            raise AppError(404, "knowledge_base_not_found", "Knowledge base not found")
        repository.succeed(path, claimed["id"], worker_id, document.id)
    except AppError as exc:
        repository.fail(path, claimed["id"], worker_id, exc.code, exc.message, retryable=False)
    except Exception as exc:
        repository.fail(path, claimed["id"], worker_id, "worker_error", str(exc)[:500], retryable=True)
    return str(claimed["id"])
