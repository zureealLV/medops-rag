"""Search request and ranked evidence models."""

from typing import Literal

from pydantic import BaseModel, Field

RetrievalStrategy = Literal["keyword", "vector", "weighted", "bm25", "rrf"]


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    knowledge_base_id: int | None = Field(default=None, ge=1)
    top_k: int = Field(default=5, ge=1, le=10)
    strategy: RetrievalStrategy = "weighted"


class Evidence(BaseModel):
    score: float
    keyword_score: float
    vector_score: float
    bm25_score: float = 0.0
    source: str
    document_id: int
    chunk_id: int
    chunk_index: int
    text: str


class SearchResponse(BaseModel):
    query: str
    strategy: RetrievalStrategy
    results: list[Evidence]
    retrieval_ms: float
