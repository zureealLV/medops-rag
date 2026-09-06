"""Question, grounded answer, text citation, and visual citation models."""

from typing import Literal

from pydantic import BaseModel, Field

from app.models.artifacts import VisualEvidence, VisualStrategy
from app.models.retrieval import Evidence, RetrievalStrategy


class AnswerRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    knowledge_base_id: int | None = Field(default=None, ge=1)
    top_k: int = Field(default=5, ge=1, le=10)
    retrieval_profile: Literal["auto", "text", "visual"] = "auto"
    text_strategy: RetrievalStrategy = "weighted"
    visual_strategy: VisualStrategy = "fusion"


class Citation(BaseModel):
    source: str
    document_id: int
    chunk_id: int
    parent_id: int | None = None


class VisualCitation(BaseModel):
    artifact_id: int
    source: str
    document_id: int
    page_number: int | None = None
    bbox: dict[str, str | int | float] | None = None
    content_url: str
    sha256: str


class AnswerResponse(BaseModel):
    answer: str
    citations: list[Citation]
    visual_citations: list[VisualCitation] = Field(default_factory=list)
    retrieved_chunks: list[Evidence]
    retrieved_artifacts: list[VisualEvidence] = Field(default_factory=list)
    retrieval_profile: Literal["text", "visual"] = "text"
    abstained: bool
    reason: str | None = None
    provider: str
    retrieval_ms: float
    model_ms: float
    token_usage: int
