"""Visual artifact listing, delivery, and paired text-to-image retrieval."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from rank_bm25 import BM25Okapi

from app.config import Settings
from app.exceptions import AppError
from app.models.artifacts import (
    DocumentArtifact,
    VisualEvidence,
    VisualSearchRequest,
    VisualSearchResponse,
)
from app.repositories import artifacts as repository
from app.repositories.knowledge_bases import get as get_kb
from app.retrieval.embeddings import tokenize
from app.retrieval.image_embeddings import provider_from_settings


def _normalize(values: list[float]) -> list[float]:
    finite = [value if math.isfinite(value) else 0.0 for value in values]
    minimum = min(finite, default=0.0)
    maximum = max(finite, default=0.0)
    if maximum <= minimum:
        return [0.0 for _ in finite]
    return [(value - minimum) / (maximum - minimum) for value in finite]


def _base(row) -> dict[str, object]:
    return {
        "id": row["id"],
        "document_id": row["document_id"],
        "source": row["source"],
        "sha256": row["sha256"],
        "mime_type": row["mime_type"],
        "width": row["width"],
        "height": row["height"],
        "page_number": row["page_number"],
        "bbox": json.loads(row["bbox_json"]) if row["bbox_json"] else None,
        "ocr_text": row["ocr_text"],
        "metadata": json.loads(row["metadata_json"]),
        "embedding_model": row["embedding_model"],
        "content_url": f"/artifacts/{row['id']}/content",
    }


def list_for_document(path: Path, tenant_id: str, document_id: int) -> list[DocumentArtifact] | None:
    rows = repository.list_for_document(path, tenant_id, document_id)
    if rows is None:
        return None
    return [DocumentArtifact(**_base(row)) for row in rows]


def content(path: Path, tenant_id: str, artifact_id: int) -> tuple[bytes, str, str] | None:
    row = repository.get_content(path, tenant_id, artifact_id)
    if row is None:
        return None
    return bytes(row["content"]), str(row["mime_type"]), str(row["sha256"])


def search(
    path: Path, settings: Settings, tenant_id: str, request: VisualSearchRequest
) -> VisualSearchResponse | None:
    if request.knowledge_base_id is not None and get_kb(
        path, tenant_id, request.knowledge_base_id
    ) is None:
        return None
    started = time.perf_counter()
    rows = repository.retrieval_rows(path, tenant_id, request.knowledge_base_id)
    if not rows:
        return VisualSearchResponse(
            query=request.query,
            strategy=request.strategy,
            results=[],
            retrieval_ms=round((time.perf_counter() - started) * 1000, 3),
            image_embedding_available=False,
        )

    corpus = [tokenize(str(row["ocr_text"])) or ["__no_ocr__"] for row in rows]
    ocr_raw = [float(value) for value in BM25Okapi(corpus).get_scores(tokenize(request.query))]
    ocr_scores = _normalize(ocr_raw)

    provider = provider_from_settings(settings)
    image_scores: list[float | None] = [None] * len(rows)
    profile = (
        f"{provider.model_name}|{provider.text_model_name}" if provider is not None else None
    )
    if provider is not None and any(
        row["embedding_json"] and row["embedding_model"] == profile for row in rows
    ):
        query_vector = provider.embed_query(request.query)
        for index, row in enumerate(rows):
            if row["embedding_json"] and row["embedding_model"] == profile:
                stored = json.loads(row["embedding_json"])
                image_scores[index] = sum(
                    left * right for left, right in zip(query_vector, stored, strict=True)
                )
    image_available = any(score is not None for score in image_scores)
    if request.strategy == "image" and not image_available:
        raise AppError(
            409,
            "image_embeddings_unavailable",
            "Enable IMAGE_EMBEDDING_ENABLED and reingest images before image search",
        )
    normalized_image = _normalize([score if score is not None else 0.0 for score in image_scores])

    results: list[VisualEvidence] = []
    for index, row in enumerate(rows):
        ocr_score = ocr_scores[index]
        image_score = normalized_image[index] if image_scores[index] is not None else None
        if request.strategy == "ocr":
            score = ocr_score
        elif request.strategy == "image":
            score = image_score or 0.0
        else:
            score = 0.45 * ocr_score + 0.55 * (image_score or 0.0)
        results.append(
            VisualEvidence(
                **_base(row),
                score=round(score, 6),
                ocr_score=round(ocr_score, 6),
                image_score=round(image_score, 6) if image_score is not None else None,
                image_similarity=(
                    round(image_scores[index], 6) if image_scores[index] is not None else None
                ),
            )
        )
    ranked = sorted(results, key=lambda item: (-item.score, item.id))[: request.top_k]
    return VisualSearchResponse(
        query=request.query,
        strategy=request.strategy,
        results=ranked,
        retrieval_ms=round((time.perf_counter() - started) * 1000, 3),
        image_embedding_available=image_available,
    )
