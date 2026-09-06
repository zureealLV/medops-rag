"""Pluggable paired text/image embeddings for visual evidence retrieval."""

from __future__ import annotations

import threading
from functools import lru_cache
from io import BytesIO
from typing import Protocol

import numpy as np
from PIL import Image

from app.config import Settings


class ImageEmbeddingProvider(Protocol):
    model_name: str
    text_model_name: str

    def embed_image(self, content: bytes) -> list[float]: ...

    def embed_query(self, query: str) -> list[float]: ...


_image_lock = threading.Lock()
_text_lock = threading.Lock()


def _normalized(values) -> list[float]:
    vector = np.asarray(values, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if norm:
        vector = vector / norm
    return vector.tolist()


@lru_cache(maxsize=4)
def _image_model(model_name: str, cache_dir: str):
    from fastembed import ImageEmbedding

    return ImageEmbedding(model_name=model_name, cache_dir=cache_dir)


@lru_cache(maxsize=4)
def _text_model(model_name: str, cache_dir: str):
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=model_name, cache_dir=cache_dir)


class FastEmbedClipProvider:
    """Local ONNX CLIP provider; paired model names must share one vector space."""

    def __init__(self, model_name: str, text_model_name: str, cache_dir: str) -> None:
        self.model_name = model_name
        self.text_model_name = text_model_name
        self.cache_dir = cache_dir

    def embed_image(self, content: bytes) -> list[float]:
        with Image.open(BytesIO(content)) as source:
            image = source.convert("RGB").copy()
        with _image_lock:
            vector = next(_image_model(self.model_name, self.cache_dir).embed(image))
        return _normalized(vector)

    def embed_query(self, query: str) -> list[float]:
        with _text_lock:
            vector = next(_text_model(self.text_model_name, self.cache_dir).query_embed(query))
        return _normalized(vector)


def provider_from_settings(settings: Settings) -> ImageEmbeddingProvider | None:
    if not settings.image_embedding_enabled:
        return None
    return FastEmbedClipProvider(
        model_name=settings.image_embedding_model,
        text_model_name=settings.image_text_embedding_model,
        cache_dir=str(settings.model_cache_dir),
    )
