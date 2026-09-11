"""Pluggable text embeddings with a deterministic no-download default."""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol

import numpy as np

from app.config import Settings
from app.retrieval.embeddings import embed


class TextEmbeddingProvider(Protocol):
    model_name: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class HashingTextProvider:
    model_name = "medops/hashing-256-v1"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return embed(text)


class FastEmbedTextProvider:
    def __init__(self, model_name: str, cache_dir: str) -> None:
        from fastembed import TextEmbedding

        self.model_name = model_name
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)

    @staticmethod
    def _values(vectors) -> list[list[float]]:
        output: list[list[float]] = []
        for vector in vectors:
            values = np.asarray(vector, dtype=np.float32)
            norm = float(np.linalg.norm(values))
            output.append((values / norm if norm else values).tolist())
        return output

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._values(self._model.embed(texts))

    def embed_query(self, text: str) -> list[float]:
        return self._values(self._model.query_embed(text))[0]


@lru_cache(maxsize=4)
def _fastembed_provider(model_name: str, cache_dir: str) -> FastEmbedTextProvider:
    return FastEmbedTextProvider(model_name, cache_dir)


def provider_from_settings(settings: Settings | None) -> TextEmbeddingProvider:
    if settings is None or not settings.text_embedding_enabled:
        return HashingTextProvider()
    return _fastembed_provider(settings.text_embedding_model, str(settings.model_cache_dir))
