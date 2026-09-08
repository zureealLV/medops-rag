"""Tenant-scoped search orchestration."""

from __future__ import annotations

import time
from pathlib import Path

from app.config import Settings
from app.models.retrieval import SearchRequest, SearchResponse
from app.repositories.documents import lexical_candidate_rows, retrieval_rows
from app.repositories.knowledge_bases import get as get_kb
from app.retrieval.hybrid import rank
from app.retrieval.query_transform import transform_queries
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
    resolved_strategy = request.strategy
    use_parent_child = resolved_strategy == "parent_child"
    use_lexical_index = not use_parent_child and (
        resolved_strategy in {"keyword", "bm25"}
        or (resolved_strategy == "auto" and not (settings and settings.text_embedding_enabled))
    )
    rows = (
        lexical_candidate_rows(
            path,
            tenant_id,
            request.knowledge_base_id,
            request.query,
            limit=max(800, request.top_k * 100),
        )
        if use_lexical_index
        else None
    )
    if rows is None or not rows:
        rows = retrieval_rows(
            path,
            tenant_id,
            request.knowledge_base_id,
            parent_child=use_parent_child,
        )
    if resolved_strategy == "auto":
        if settings and settings.text_embedding_enabled:
            resolved_strategy = "rrf"
        else:
            # rank_bm25 can produce non-positive IDF for one/two-row corpora;
            # preserve a meaningful score there instead of normalizing to zero.
            resolved_strategy = "weighted" if len(rows) < 3 else "bm25"
    scoring_strategy = "bm25" if use_parent_child else resolved_strategy
    resolved_transform, queries = transform_queries(request.query, request.query_transform, settings)
    if scoring_strategy in {"vector", "weighted", "rrf"}:
        provider = provider_from_settings(settings)
        rows = [row for row in rows if row["embedding_model"] == provider.model_name]
    else:
        provider = None
    ranking_limit = len(rows) if use_parent_child or len(queries) > 1 else request.top_k
    rankings = [
        rank(
            query,
            rows,
            top_k=ranking_limit,
            strategy=scoring_strategy,
            query_vector=provider.embed_query(query) if provider else None,
        )
        for query in queries
    ]
    if len(rankings) == 1:
        results = rankings[0]
    else:
        by_chunk = {item.chunk_id: item for items in rankings for item in items}
        fused = {chunk_id: 0.0 for chunk_id in by_chunk}
        for items in rankings:
            for result_rank, item in enumerate(items, start=1):
                fused[item.chunk_id] += 1.0 / (60 + result_rank)
        maximum = max(fused.values(), default=1.0)
        results = sorted(
            (
                item.model_copy(update={"score": round(fused[chunk_id] / maximum, 6)})
                for chunk_id, item in by_chunk.items()
            ),
            key=lambda item: (-item.score, item.chunk_id),
        )[:ranking_limit]
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
        strategy=resolved_strategy,
        results=results,
        retrieval_ms=round((time.perf_counter() - started) * 1000, 3),
        query_transform=resolved_transform,
        transformed_queries=queries,
    )
