"""Tenant-scoped search orchestration."""

from __future__ import annotations

import time
from pathlib import Path

from app.models.retrieval import SearchRequest, SearchResponse
from app.repositories.documents import retrieval_rows
from app.repositories.knowledge_bases import get as get_kb
from app.retrieval.hybrid import rank


def search(path: Path, tenant_id: str, request: SearchRequest) -> SearchResponse | None:
    if request.knowledge_base_id is not None and get_kb(path, tenant_id, request.knowledge_base_id) is None:
        return None
    started = time.perf_counter()
    # Tenant filtering happens in SQL, before any chunk can enter ranking or a model prompt.
    rows = retrieval_rows(path, tenant_id, request.knowledge_base_id)
    results = rank(request.query, rows, top_k=request.top_k, strategy=request.strategy)
    return SearchResponse(
        query=request.query,
        strategy=request.strategy,
        results=results,
        retrieval_ms=round((time.perf_counter() - started) * 1000, 3),
    )
