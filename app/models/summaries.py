"""Persisted Map-Reduce summary job models."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.jobs import JobState


class SummaryJobCreate(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    document_ids: list[int] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_document_ids(self):
        if any(value < 1 for value in self.document_ids):
            raise ValueError("document_ids must contain positive integers")
        if len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("document_ids must not contain duplicates")
        return self


class SummaryCitation(BaseModel):
    document_id: int
    source: str


class SummaryMapResult(BaseModel):
    document_id: int
    status: Literal["succeeded", "failed"]
    source: str
    summary: str | None = None
    provider: str | None = None
    token_usage: int = 0
    citation: SummaryCitation
    error_code: str | None = None
    error_message: str | None = None


class SummaryJob(BaseModel):
    id: str
    tenant_id: str
    knowledge_base_id: int
    idempotency_key: str
    question: str
    document_ids: list[int]
    state: JobState
    progress: int
    attempt: int
    max_attempts: int
    lease_owner: str | None = None
    lease_expires_at: float | None = None
    summary: str | None = None
    provider: str | None = None
    token_usage: int = 0
    error_code: str | None = None
    error_message: str | None = None
    map_results: list[SummaryMapResult] = Field(default_factory=list)
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    updated_at: str
