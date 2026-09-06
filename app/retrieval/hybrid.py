"""Hybrid ranking with explicit component scores."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any

from rank_bm25 import BM25Okapi

from app.models.retrieval import Evidence
from app.retrieval.embeddings import embed, tokenize
from app.retrieval.keyword import keyword_score
from app.retrieval.vector import vector_score


def _normalize(values: Sequence[float]) -> list[float]:
    maximum = max(values, default=0.0)
    if maximum <= 0:
        return [0.0 for _ in values]
    return [max(0.0, value) / maximum for value in values]


def _ranks(values: Sequence[float]) -> list[int]:
    ordered = sorted(range(len(values)), key=lambda index: (-values[index], index))
    ranks = [0] * len(values)
    for rank_value, index in enumerate(ordered, start=1):
        ranks[index] = rank_value
    return ranks


def rank(
    query: str,
    rows: Iterable[Any],
    *,
    top_k: int,
    strategy: str = "weighted",
) -> list[Evidence]:
    materialized = list(rows)
    if not materialized:
        return []
    query_vector = embed(query)
    query_tokens = tokenize(query)
    corpus_tokens = [tokenize(row["text"]) for row in materialized]
    bm25_raw = [float(value) for value in BM25Okapi(corpus_tokens).get_scores(query_tokens)]
    bm25_scores = _normalize(bm25_raw)
    keyword_scores = [keyword_score(query, row["text"]) for row in materialized]
    vector_scores = [
        vector_score(query_vector, json.loads(row["embedding_json"])) for row in materialized
    ]
    bm25_ranks = _ranks(bm25_scores)
    vector_ranks = _ranks(vector_scores)
    rrf_raw = [
        1.0 / (60 + sparse_rank) + 1.0 / (60 + dense_rank)
        for sparse_rank, dense_rank in zip(bm25_ranks, vector_ranks, strict=True)
    ]
    rrf_scores = _normalize(rrf_raw)

    results: list[Evidence] = []
    for index, row in enumerate(materialized):
        keyword = keyword_scores[index]
        vector = vector_scores[index]
        bm25 = bm25_scores[index]
        score_by_strategy = {
            "keyword": keyword,
            "vector": vector,
            "weighted": 0.55 * vector + 0.45 * keyword,
            "bm25": bm25,
            "rrf": rrf_scores[index],
        }
        if strategy not in score_by_strategy:
            raise ValueError(f"Unknown retrieval strategy: {strategy}")
        results.append(
            Evidence(
                score=round(score_by_strategy[strategy], 6),
                keyword_score=round(keyword, 6),
                vector_score=round(vector, 6),
                bm25_score=round(bm25, 6),
                source=row["source"],
                document_id=row["document_id"],
                chunk_id=row["id"],
                chunk_index=row["chunk_index"],
                text=row["text"],
            )
        )
    return sorted(results, key=lambda item: (-item.score, item.chunk_id))[:top_k]
