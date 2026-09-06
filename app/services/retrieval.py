"""Tenant-scoped search orchestration."""

from __future__ import annotations

import time
from pathlib import Path

from app.config import Settings
from app.models.retrieval import SearchRequest, SearchResponse
from app.repositories.documents import retrieval_rows
from app.repositories.knowledge_bases import get as get_kb
from app.retrieval.hybrid import rank
from app.retrieval.text_embeddings import provider_from_settings


def search(
    path: Path,
    tenant_id: str,
    request: SearchRequest,
    settings: Settings | None = None,
) -> SearchResponse | None:
    if request.knowledge_base_id is not None and get_kb(path, tenant_id, request.knowledge_base_id) is None:
        return None
    started = time.perf_counter()
    # Tenant filtering happens in SQL, before any chunk can enter ranking or a model prompt.
    use_parent_child = request.strategy == "parent_child"
    rows = retrieval_rows(
        path,
        tenant_id,
        request.knowledge_base_id,
        parent_child=use_parent_child,
    )
    scoring_strategy = "bm25" if use_parent_child else request.strategy
    query_vector = None
    if scoring_strategy in {"vector", "weighted", "rrf"}:
        provider = provider_from_settings(settings)
        rows = [row for row in rows if row["embedding_model"] == provider.model_name]
        query_vector = provider.embed_query(request.query)
    results = rank(
        request.query,
        rows,
        top_k=(len(rows) if use_parent_child else request.top_k),
        # The current benchmark shows BM25 outperforming the hashing-vector baseline.
        # Parent/child retrieval therefore reconstructs context without smuggling in
        # an unvalidated dense model; beta will benchmark a real dense child index.
        strategy=scoring_strategy,
        query_vector=query_vector,
    )
    if use_parent_child:
        deduplicated = []
        seen_parent_ids: set[int] = set()
        for item in results:
            if item.parent_id is None or item.parent_id in seen_parent_ids:
                continue
            seen_parent_ids.add(item.parent_id)
            deduplicated.append(item)
            if len(deduplicated) == request.top_k:
                break
        results = deduplicated
    return SearchResponse(
        query=request.query,
        strategy=request.strategy,
        results=results,
        retrieval_ms=round((time.perf_counter() - started) * 1000, 3),
    )
