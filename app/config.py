"""Environment-backed application settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _database_path(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("MedOps V1 supports only sqlite:/// database URLs")
    path = Path(database_url.removeprefix(prefix))
    return path if path.is_absolute() else Path.cwd() / path


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    app_env: str = "development"
    log_level: str = "INFO"
    retrieval_threshold: float = 0.20
    chunk_size: int = 600
    chunk_overlap: int = 80
    max_upload_bytes: int = 10_000_000
    max_image_pixels: int = 25_000_000
    ocr_enabled: bool = True
    ocr_min_confidence: float = 0.50
    model_api_key: str = ""
    model_base_url: str = ""
    model_name: str = ""
    model_timeout_seconds: float = 8.0
    model_max_retries: int = 1

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_path=_database_path(os.getenv("DATABASE_URL", "sqlite:///./data/runtime/medops.db")),
            app_env=os.getenv("APP_ENV", "development"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            retrieval_threshold=float(os.getenv("RETRIEVAL_THRESHOLD", "0.20")),
            chunk_size=int(os.getenv("CHUNK_SIZE", "600")),
            chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "80")),
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", "10000000")),
            max_image_pixels=int(os.getenv("MAX_IMAGE_PIXELS", "25000000")),
            ocr_enabled=os.getenv("OCR_ENABLED", "true").lower() in {"1", "true", "yes", "on"},
            ocr_min_confidence=float(os.getenv("OCR_MIN_CONFIDENCE", "0.50")),
            model_api_key=os.getenv("MODEL_API_KEY", ""),
            model_base_url=os.getenv("MODEL_BASE_URL", ""),
            model_name=os.getenv("MODEL_NAME", ""),
            model_timeout_seconds=float(os.getenv("MODEL_TIMEOUT_SECONDS", "8")),
            model_max_retries=int(os.getenv("MODEL_MAX_RETRIES", "1")),
        )
