"""Durable SQLite operations for resumable Map-Reduce summary jobs."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path

from app.db import transaction
from app.exceptions import AppError
from app.models.summaries import SummaryCitation, SummaryJob, SummaryMapResult


def _request_hash(kb_id: int, question: str, document_ids: list[int]) -> str:
    payload = json.dumps(
        {"knowledge_base_id": kb_id, "question": question, "document_ids": document_ids},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _map_model(row) -> SummaryMapResult:
    citation = json.loads(row["citation_json"])
    return SummaryMapResult(
        document_id=row["document_id"],
        status=row["status"],
        source=row["source"],
        summary=row["summary"],
        provider=row["provider"],
        token_usage=row["token_usage"],
        citation=SummaryCitation(**citation),
        error_code=row["error_code"],
        error_message=row["error_message"],
    )


def _model(row, map_rows) -> SummaryJob:
    data = dict(row)
    data.pop("request_sha256")
    data["document_ids"] = json.loads(data.pop("document_ids_json"))
    data["map_results"] = [_map_model(item) for item in map_rows]
    return SummaryJob(**data)


def enqueue(
    path: Path,
    tenant_id: str,
    kb_id: int,
    key: str,
    question: str,
    document_ids: list[int],
) -> tuple[SummaryJob, bool]:
    digest = _request_hash(kb_id, question, document_ids)
    with transaction(path) as connection:
        existing = connection.execute(
            "SELECT * FROM summary_jobs WHERE tenant_id=? AND idempotency_key=?",
            (tenant_id, key),
        ).fetchone()
        if existing:
            if existing["request_sha256"] != digest:
                raise AppError(
                    409,
                    "idempotency_conflict",
                    "Idempotency key was already used for another summary request",
                )
            maps = connection.execute(
                "SELECT * FROM summary_map_results WHERE job_id=? ORDER BY document_id",
                (existing["id"],),
            ).fetchall()
            return _model(existing, maps), True
        job_id = str(uuid.uuid4())
        connection.execute(
            """INSERT INTO summary_jobs
               (id,tenant_id,knowledge_base_id,idempotency_key,request_sha256,question,
                document_ids_json,state)
               VALUES (?,?,?,?,?,?,?,'queued')""",
            (job_id, tenant_id, kb_id, key, digest, question, json.dumps(document_ids)),
        )
        row = connection.execute("SELECT * FROM summary_jobs WHERE id=?", (job_id,)).fetchone()
    return _model(row, []), False


def get(path: Path, tenant_id: str, job_id: str) -> SummaryJob | None:
    with transaction(path) as connection:
        row = connection.execute(
            "SELECT * FROM summary_jobs WHERE id=? AND tenant_id=?", (job_id, tenant_id)
        ).fetchone()
        if not row:
            return None
        maps = connection.execute(
            "SELECT * FROM summary_map_results WHERE job_id=? ORDER BY document_id", (job_id,)
        ).fetchall()
    return _model(row, maps)


def claim(path: Path, worker_id: str, lease_seconds: float = 1800.0, now: float | None = None):
    current = time.time() if now is None else now
    with transaction(path) as connection:
        connection.execute(
            """UPDATE summary_jobs
               SET state=CASE WHEN EXISTS (
                     SELECT 1 FROM summary_map_results r
                     WHERE r.job_id=summary_jobs.id AND r.status='succeeded'
                   ) THEN 'partial' ELSE 'failed' END,
                   progress=100,error_code='retry_exhausted',
                   error_message='Worker lease expired after the maximum attempt count',
                   lease_owner=NULL,lease_expires_at=NULL,completed_at=CURRENT_TIMESTAMP,
                   updated_at=CURRENT_TIMESTAMP
               WHERE state='running' AND lease_expires_at < ? AND attempt >= max_attempts""",
            (current,),
        )
        row = connection.execute(
            """SELECT * FROM summary_jobs
               WHERE (state='queued' OR (state='running' AND lease_expires_at < ?))
                 AND attempt < max_attempts
               ORDER BY created_at,id LIMIT 1""",
            (current,),
        ).fetchone()
        if not row:
            return None
        cursor = connection.execute(
            """UPDATE summary_jobs
               SET state='running',progress=MAX(progress,5),attempt=attempt+1,
                   lease_owner=?,lease_expires_at=?,
                   started_at=COALESCE(started_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP
               WHERE id=? AND (state='queued' OR (state='running' AND lease_expires_at < ?))""",
            (worker_id, current + lease_seconds, row["id"], current),
        )
        if cursor.rowcount != 1:
            return None
        claimed = dict(
            connection.execute("SELECT * FROM summary_jobs WHERE id=?", (row["id"],)).fetchone()
        )
        claimed["document_ids"] = json.loads(claimed.pop("document_ids_json"))
        return claimed


def completed_document_ids(path: Path, job_id: str) -> set[int]:
    with transaction(path) as connection:
        rows = connection.execute(
            "SELECT document_id FROM summary_map_results WHERE job_id=?", (job_id,)
        ).fetchall()
    return {int(row["document_id"]) for row in rows}


def _owned_running(connection, job_id: str, worker_id: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM summary_jobs WHERE id=? AND state='running' AND lease_owner=?",
            (job_id, worker_id),
        ).fetchone()
        is not None
    )


def save_map(
    path: Path,
    job_id: str,
    worker_id: str,
    document_id: int,
    source: str,
    *,
    summary: str | None,
    provider: str | None,
    token_usage: int,
    error_code: str | None = None,
    error_message: str | None = None,
) -> bool:
    status = "failed" if error_code else "succeeded"
    citation = json.dumps({"document_id": document_id, "source": source}, ensure_ascii=False)
    with transaction(path) as connection:
        if not _owned_running(connection, job_id, worker_id):
            return False
        connection.execute(
            """INSERT INTO summary_map_results
               (job_id,document_id,status,source,summary,provider,token_usage,citation_json,
                error_code,error_message)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(job_id,document_id) DO UPDATE SET
                 status=excluded.status,source=excluded.source,summary=excluded.summary,
                 provider=excluded.provider,token_usage=excluded.token_usage,
                 citation_json=excluded.citation_json,error_code=excluded.error_code,
                 error_message=excluded.error_message,updated_at=CURRENT_TIMESTAMP""",
            (
                job_id,
                document_id,
                status,
                source,
                summary,
                provider,
                token_usage,
                citation,
                error_code,
                error_message,
            ),
        )
        return True


def heartbeat(
    path: Path, job_id: str, worker_id: str, progress: int, lease_seconds: float = 1800.0
) -> bool:
    with transaction(path) as connection:
        cursor = connection.execute(
            """UPDATE summary_jobs SET progress=?,lease_expires_at=?,updated_at=CURRENT_TIMESTAMP
               WHERE id=? AND state='running' AND lease_owner=?""",
            (max(5, min(progress, 95)), time.time() + lease_seconds, job_id, worker_id),
        )
        return cursor.rowcount == 1


def successful_maps(path: Path, job_id: str) -> list[dict[str, object]]:
    with transaction(path) as connection:
        rows = connection.execute(
            """SELECT document_id,source,summary,provider,token_usage
               FROM summary_map_results WHERE job_id=? AND status='succeeded'
               ORDER BY document_id""",
            (job_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def result_counts(path: Path, job_id: str) -> tuple[int, int, int]:
    with transaction(path) as connection:
        row = connection.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN status='succeeded' THEN 1 ELSE 0 END) AS succeeded,
                      SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed
               FROM summary_map_results WHERE job_id=?""",
            (job_id,),
        ).fetchone()
    return int(row["total"]), int(row["succeeded"] or 0), int(row["failed"] or 0)


def finish(
    path: Path,
    job_id: str,
    worker_id: str,
    state: str,
    summary: str | None,
    provider: str | None,
    token_usage: int,
    error_code: str | None = None,
    error_message: str | None = None,
) -> bool:
    with transaction(path) as connection:
        cursor = connection.execute(
            """UPDATE summary_jobs
               SET state=?,progress=100,summary=?,provider=?,token_usage=?,error_code=?,
                   error_message=?,lease_owner=NULL,lease_expires_at=NULL,
                   completed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
               WHERE id=? AND state='running' AND lease_owner=?""",
            (
                state,
                summary,
                provider,
                token_usage,
                error_code,
                error_message,
                job_id,
                worker_id,
            ),
        )
        return cursor.rowcount == 1


def retry(path: Path, job_id: str, worker_id: str, code: str, message: str) -> bool:
    with transaction(path) as connection:
        row = connection.execute(
            """SELECT attempt,max_attempts FROM summary_jobs
               WHERE id=? AND state='running' AND lease_owner=?""",
            (job_id, worker_id),
        ).fetchone()
        if not row:
            return False
        if row["attempt"] < row["max_attempts"]:
            state = "queued"
        else:
            successful = connection.execute(
                """SELECT 1 FROM summary_map_results
                   WHERE job_id=? AND status='succeeded' LIMIT 1""",
                (job_id,),
            ).fetchone()
            state = "partial" if successful else "failed"
        cursor = connection.execute(
            """UPDATE summary_jobs
                SET state=?,error_code=?,error_message=?,lease_owner=NULL,lease_expires_at=NULL,
                    completed_at=CASE WHEN ?='queued' THEN NULL ELSE CURRENT_TIMESTAMP END,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND state='running' AND lease_owner=?""",
            (state, code, message, state, job_id, worker_id),
        )
        return cursor.rowcount == 1


def cancel(path: Path, tenant_id: str, job_id: str) -> bool:
    with transaction(path) as connection:
        cursor = connection.execute(
            """UPDATE summary_jobs SET state='cancelled',progress=100,lease_owner=NULL,
                   lease_expires_at=NULL,completed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
               WHERE id=? AND tenant_id=? AND state IN ('queued','running')""",
            (job_id, tenant_id),
        )
        return cursor.rowcount == 1
