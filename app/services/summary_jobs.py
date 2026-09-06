"""Resumable Map-Reduce summary orchestration."""

from __future__ import annotations

from pathlib import Path

from app.agents.summaries import SummaryCallError, map_document, reduce_maps
from app.config import Settings
from app.exceptions import AppError
from app.models.summaries import SummaryJob, SummaryJobCreate
from app.repositories import documents as document_repository
from app.repositories import summary_jobs as repository
from app.repositories.knowledge_bases import get as get_kb


def enqueue(
    path: Path, tenant_id: str, kb_id: int, key: str, request: SummaryJobCreate
) -> tuple[SummaryJob, bool]:
    if get_kb(path, tenant_id, kb_id) is None:
        raise AppError(404, "knowledge_base_not_found", "Knowledge base not found")
    available = {item.id for item in document_repository.list_for_kb(path, tenant_id, kb_id)}
    if missing := [item for item in request.document_ids if item not in available]:
        raise AppError(
            404,
            "document_not_found",
            f"Documents are unavailable in this knowledge base: {missing}",
        )
    return repository.enqueue(
        path,
        tenant_id,
        kb_id,
        key,
        request.question,
        request.document_ids,
    )


def get(path: Path, tenant_id: str, job_id: str) -> SummaryJob | None:
    return repository.get(path, tenant_id, job_id)


def cancel(path: Path, tenant_id: str, job_id: str) -> bool:
    return repository.cancel(path, tenant_id, job_id)


def _with_citations(summary: str, maps: list[dict[str, object]]) -> str:
    missing = [
        f"[document:{item['document_id']}]"
        for item in maps
        if f"[document:{item['document_id']}]" not in summary
    ]
    return summary if not missing else f"{summary}\n\nSources: {' '.join(missing)}"


def process_next(
    path: Path,
    settings: Settings,
    worker_id: str,
    lease_seconds: float = 1800.0,
    now: float | None = None,
) -> str | None:
    claimed = repository.claim(path, worker_id, lease_seconds, now)
    if claimed is None:
        return None
    job_id = str(claimed["id"])
    try:
        document_ids = [int(value) for value in claimed["document_ids"]]
        completed = repository.completed_document_ids(path, job_id)
        pending = [value for value in document_ids if value not in completed]
        for index, document_id in enumerate(pending, start=1):
            document = document_repository.get(path, claimed["tenant_id"], document_id)
            if document is None or document.kb_id != claimed["knowledge_base_id"]:
                saved = repository.save_map(
                    path,
                    job_id,
                    worker_id,
                    document_id,
                    "unavailable",
                    summary=None,
                    provider=None,
                    token_usage=0,
                    error_code="document_unavailable",
                    error_message="Document was deleted or moved after the job was queued",
                )
            else:
                try:
                    summary, provider, tokens = map_document(claimed["question"], document, settings)
                    saved = repository.save_map(
                        path,
                        job_id,
                        worker_id,
                        document.id,
                        document.source,
                        summary=summary,
                        provider=provider,
                        token_usage=tokens,
                    )
                except SummaryCallError as exc:
                    saved = repository.save_map(
                        path,
                        job_id,
                        worker_id,
                        document.id,
                        document.source,
                        summary=None,
                        provider=None,
                        token_usage=0,
                        error_code=exc.code,
                        error_message=exc.message,
                    )
            if not saved:
                return job_id
            done = len(completed) + index
            progress = 10 + round(70 * done / len(document_ids))
            if not repository.heartbeat(path, job_id, worker_id, progress, lease_seconds):
                return job_id

        maps = repository.successful_maps(path, job_id)
        _, succeeded, failed = repository.result_counts(path, job_id)
        map_tokens = sum(int(item["token_usage"]) for item in maps)
        if succeeded == 0:
            repository.finish(
                path,
                job_id,
                worker_id,
                "failed",
                None,
                None,
                map_tokens,
                "all_maps_failed",
                "No document summary completed successfully",
            )
            return job_id
        try:
            final, provider, reduce_tokens = reduce_maps(claimed["question"], maps, settings)
            final = _with_citations(final, maps)
        except SummaryCallError as exc:
            repository.finish(
                path,
                job_id,
                worker_id,
                "partial",
                None,
                None,
                map_tokens,
                exc.code,
                exc.message,
            )
            return job_id
        repository.finish(
            path,
            job_id,
            worker_id,
            "partial" if failed else "succeeded",
            final,
            provider,
            map_tokens + reduce_tokens,
            "map_partial_failure" if failed else None,
            f"{failed} document map(s) failed" if failed else None,
        )
    except Exception as exc:
        repository.retry(path, job_id, worker_id, "worker_error", str(exc)[:500])
    return job_id
