"""Hybrid ranking with explicit component scores."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from app.models.retrieval import Evidence
from app.retrieval.embeddings import embed
from app.retrieval.keyword import keyword_score
from app.retrieval.vector import vector_score


def rank(query: str, rows: Iterable[Any], *, top_k: int) -> list[Evidence]:
    query_vector = embed(query)
    results: list[Evidence] = []
    for row in rows:
        keyword = keyword_score(query, row["text"])
        vector = vector_score(query_vector, json.loads(row["embedding_json"]))
        combined = 0.55 * vector + 0.45 * keyword
        results.append(
            Evidence(
                score=round(combined, 6),
                keyword_score=round(keyword, 6),
                vector_score=round(vector, 6),
                source=row["source"],
                document_id=row["document_id"],
                chunk_id=row["id"],
                chunk_index=row["chunk_index"],
                text=row["text"],
            )
        )
    return sorted(results, key=lambda item: item.score, reverse=True)[:top_k]
