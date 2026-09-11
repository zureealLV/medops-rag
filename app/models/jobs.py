"""Persisted ingestion job API models."""

from typing import Literal

from pydantic import BaseModel

JobState = Literal["queued", "running", "succeeded", "failed", "partial", "cancelled"]


class IngestionJob(BaseModel):
    id: str
    tenant_id: str
    knowledge_base_id: int
    idempotency_key: str
    filename: str
    content_sha256: str
    state: JobState
    progress: int
    attempt: int
    max_attempts: int
    lease_owner: str | None = None
    lease_expires_at: float | None = None
    document_id: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    updated_at: str
