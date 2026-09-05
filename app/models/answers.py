"""Question, grounded answer, citation, and abstention models."""

from pydantic import BaseModel, Field

from app.models.retrieval import Evidence


class AnswerRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    knowledge_base_id: int | None = Field(default=None, ge=1)
    top_k: int = Field(default=5, ge=1, le=10)


class Citation(BaseModel):
    source: str
    document_id: int
    chunk_id: int


class AnswerResponse(BaseModel):
    answer: str
    citations: list[Citation]
    retrieved_chunks: list[Evidence]
    abstained: bool
    reason: str | None = None
    provider: str
    retrieval_ms: float
    model_ms: float
    token_usage: int
