"""Image artifact metadata, visual citations, and search contracts."""

from typing import Literal

from pydantic import BaseModel, Field

VisualStrategy = Literal["ocr", "image", "fusion"]


class DocumentArtifact(BaseModel):
    id: int
    document_id: int
    source: str
    sha256: str
    mime_type: str
    width: int
    height: int
    page_number: int | None = None
    bbox: dict[str, str | int | float] | None = None
    ocr_text: str = ""
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    embedding_model: str | None = None
    content_url: str


class VisualSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    knowledge_base_id: int | None = Field(default=None, ge=1)
    top_k: int = Field(default=5, ge=1, le=10)
    strategy: VisualStrategy = "fusion"


class VisualEvidence(DocumentArtifact):
    score: float
    ocr_score: float
    image_score: float | None = None
    image_similarity: float | None = None


class VisualSearchResponse(BaseModel):
    query: str
    strategy: VisualStrategy
    results: list[VisualEvidence]
    retrieval_ms: float
    image_embedding_available: bool
