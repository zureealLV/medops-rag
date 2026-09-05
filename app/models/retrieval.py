"""Search request and ranked evidence models."""

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    knowledge_base_id: int | None = Field(default=None, ge=1)
    top_k: int = Field(default=5, ge=1, le=10)


class Evidence(BaseModel):
    score: float
    keyword_score: float
    vector_score: float
    source: str
    document_id: int
    chunk_id: int
    chunk_index: int
    text: str


class SearchResponse(BaseModel):
    query: str
    results: list[Evidence]
    retrieval_ms: float
