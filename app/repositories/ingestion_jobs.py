"""Atomic SQLite queue operations for ingestion jobs."""

from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path

from app.db import transaction
from app.exceptions import AppError
from app.models.jobs import IngestionJob


def _model(row) -> IngestionJob:
    return IngestionJob(**dict(row))


def enqueue(
    path: Path, tenant_id: str, kb_id: int, key: str, filename: str, mime: str | None, content: bytes
) -> tuple[IngestionJob, bool]:
    digest = hashlib.sha256(content).hexdigest()
    with transaction(path) as connection:
        existing = connection.execute(
            "SELECT * FROM ingestion_jobs WHERE tenant_id=? AND idempotency_key=?", (tenant_id, key)
        ).fetchone()
        if existing:
            if existing["content_sha256"] != digest or existing["knowledge_base_id"] != kb_id:
                raise AppError(
                    409, "idempotency_conflict", "Idempotency key was already used for another payload"
                )
            return _model(existing), True
        job_id = str(uuid.uuid4())
        connection.execute(
            """INSERT INTO ingestion_jobs
            (id,tenant_id,knowledge_base_id,idempotency_key,filename,declared_mime,content,content_sha256,state)
            VALUES (?,?,?,?,?,?,?,?, 'queued')""",
            (job_id, tenant_id, kb_id, key, filename, mime, content, digest),
        )
        row = connection.execute("SELECT * FROM ingestion_jobs WHERE id=?", (job_id,)).fetchone()
    return _model(row), False


def get(path: Path, tenant_id: str, job_id: str) -> IngestionJob | None:
    with transaction(path) as connection:
        row = connection.execute(
            "SELECT * FROM ingestion_jobs WHERE id=? AND tenant_id=?", (job_id, tenant_id)
        ).fetchone()
    return _model(row) if row else None


def claim(path: Path, worker_id: str, lease_seconds: float = 30.0, now: float | None = None):
    current = time.time() if now is None else now
    with transaction(path) as connection:
        connection.execute(
            """UPDATE ingestion_jobs
               SET state='failed',progress=100,error_code='retry_exhausted',
                   error_message='Worker lease expired after the maximum attempt count',
                   lease_owner=NULL,lease_expires_at=NULL,completed_at=CURRENT_TIMESTAMP,
                   updated_at=CURRENT_TIMESTAMP
               WHERE state='running' AND lease_expires_at < ? AND attempt >= max_attempts""",
            (current,),
        )
        row = connection.execute(
            """SELECT * FROM ingestion_jobs
            WHERE (state='queued' OR (state='running' AND lease_expires_at < ?)) AND attempt < max_attempts
            ORDER BY created_at,id LIMIT 1""",
            (current,),
        ).fetchone()
        if not row:
            return None
        updated = connection.execute(
            """UPDATE ingestion_jobs SET state='running',progress=10,attempt=attempt+1,
            lease_owner=?,lease_expires_at=?,started_at=COALESCE(started_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND (state='queued' OR (state='running' AND lease_expires_at < ?))""",
            (worker_id, current + lease_seconds, row["id"], current),
        )
        if updated.rowcount != 1:
            return None
        return dict(connection.execute("SELECT * FROM ingestion_jobs WHERE id=?", (row["id"],)).fetchone())


def succeed(path: Path, job_id: str, worker_id: str, document_id: int) -> bool:
    with transaction(path) as connection:
        cursor = connection.execute(
            """UPDATE ingestion_jobs SET state='succeeded',progress=100,document_id=?,content=NULL,
            lease_owner=NULL,lease_expires_at=NULL,completed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND state='running' AND lease_owner=?""",
            (document_id, job_id, worker_id),
        )
        return cursor.rowcount == 1


def fail(path: Path, job_id: str, worker_id: str, code: str, message: str, retryable: bool) -> bool:
    with transaction(path) as connection:
        row = connection.execute(
            """SELECT attempt,max_attempts FROM ingestion_jobs
               WHERE id=? AND state='running' AND lease_owner=?""",
            (job_id, worker_id),
        ).fetchone()
        if not row:
            return False
        state = "queued" if retryable and row["attempt"] < row["max_attempts"] else "failed"
        cursor = connection.execute(
            """UPDATE ingestion_jobs
               SET state=?,progress=?,error_code=?,error_message=?,lease_owner=NULL,
                   lease_expires_at=NULL,
                   completed_at=CASE WHEN ?='failed' THEN CURRENT_TIMESTAMP ELSE NULL END,
                   updated_at=CURRENT_TIMESTAMP
               WHERE id=? AND lease_owner=?""",
            (state, 0 if state == "queued" else 100, code, message, state, job_id, worker_id),
        )
        return cursor.rowcount == 1


def cancel(path: Path, tenant_id: str, job_id: str) -> bool:
    with transaction(path) as connection:
        cursor = connection.execute(
            """UPDATE ingestion_jobs SET state='cancelled',progress=100,lease_owner=NULL,
            lease_expires_at=NULL,completed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND tenant_id=? AND state IN ('queued','running')""",
            (job_id, tenant_id),
        )
        return cursor.rowcount == 1
