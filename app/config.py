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
    auth_mode: str = "trusted_headers"
    retrieval_threshold: float = 0.20
    retrieval_keyword_threshold: float = 0.28
    retrieval_dense_threshold: float = 0.40
    chunk_size: int = 600
    chunk_overlap: int = 80
    parent_chunk_size: int = 1600
    child_chunk_size: int = 350
    child_chunk_overlap: int = 50
    text_embedding_enabled: bool = False
    text_embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    hyde_auto_enabled: bool = False
    max_upload_bytes: int = 10_000_000
    max_image_pixels: int = 25_000_000
    max_archive_entries: int = 2_048
    max_archive_uncompressed_bytes: int = 50_000_000
    max_archive_entry_bytes: int = 20_000_000
    max_archive_compression_ratio: float = 200.0
    max_pdf_pages: int = 200
    ocr_enabled: bool = True
    ocr_min_confidence: float = 0.50
    image_embedding_enabled: bool = False
    image_embedding_model: str = "Qdrant/clip-ViT-B-32-vision"
    image_text_embedding_model: str = "Qdrant/clip-ViT-B-32-text"
    model_cache_dir: Path = Path("data/models/fastembed")
    visual_similarity_threshold: float = 0.28
    visual_similarity_margin: float = 0.002
    model_api_key: str = ""
    model_base_url: str = "https://api.deepseek.com"
    model_name: str = "deepseek-v4-flash"
    model_vision_enabled: bool = False
    model_max_visual_images: int = 3
    model_max_visual_bytes: int = 6_000_000
    model_timeout_seconds: float = 8.0
    model_request_deadline_seconds: float = 12.0
    model_max_retries: int = 1
    model_retry_base_delay_seconds: float = 0.1
    model_retry_max_delay_seconds: float = 2.0
    model_retry_jitter_ratio: float = 0.2
    model_retry_after_max_seconds: float = 5.0
    model_retry_budget_global_capacity: int = 32
    model_retry_budget_global_refill_per_second: float = 4.0
    model_retry_budget_per_tenant_capacity: int = 8
    model_retry_budget_per_tenant_refill_per_second: float = 1.0
    model_max_concurrency: int = 4
    model_max_concurrency_per_tenant: int = 2
    model_max_queue_waiters: int = 8
    model_max_queue_waiters_per_tenant: int = 4
    model_queue_timeout_seconds: float = 0.25
    model_overload_retry_after_seconds: int = 1
    model_circuit_failure_threshold: int = 5
    model_circuit_recovery_seconds: float = 30.0
    model_shutdown_timeout_seconds: float = 5.0
    summary_model_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_path=_database_path(os.getenv("DATABASE_URL", "sqlite:///./data/runtime/medops.db")),
            app_env=os.getenv("APP_ENV", "development"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            auth_mode=os.getenv("AUTH_MODE", "trusted_headers"),
            retrieval_threshold=float(os.getenv("RETRIEVAL_THRESHOLD", "0.20")),
            retrieval_keyword_threshold=float(os.getenv("RETRIEVAL_KEYWORD_THRESHOLD", "0.28")),
            retrieval_dense_threshold=float(os.getenv("RETRIEVAL_DENSE_THRESHOLD", "0.40")),
            chunk_size=int(os.getenv("CHUNK_SIZE", "600")),
            chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "80")),
            parent_chunk_size=int(os.getenv("PARENT_CHUNK_SIZE", "1600")),
            child_chunk_size=int(os.getenv("CHILD_CHUNK_SIZE", "350")),
            child_chunk_overlap=int(os.getenv("CHILD_CHUNK_OVERLAP", "50")),
            text_embedding_enabled=os.getenv("TEXT_EMBEDDING_ENABLED", "false").lower()
            in {"1", "true", "yes", "on"},
            text_embedding_model=os.getenv(
                "TEXT_EMBEDDING_MODEL",
                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            ),
            hyde_auto_enabled=os.getenv("HYDE_AUTO_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", "10000000")),
            max_image_pixels=int(os.getenv("MAX_IMAGE_PIXELS", "25000000")),
            max_archive_entries=int(os.getenv("MAX_ARCHIVE_ENTRIES", "2048")),
            max_archive_uncompressed_bytes=int(os.getenv("MAX_ARCHIVE_UNCOMPRESSED_BYTES", "50000000")),
            max_archive_entry_bytes=int(os.getenv("MAX_ARCHIVE_ENTRY_BYTES", "20000000")),
            max_archive_compression_ratio=float(os.getenv("MAX_ARCHIVE_COMPRESSION_RATIO", "200")),
            max_pdf_pages=int(os.getenv("MAX_PDF_PAGES", "200")),
            ocr_enabled=os.getenv("OCR_ENABLED", "true").lower() in {"1", "true", "yes", "on"},
            ocr_min_confidence=float(os.getenv("OCR_MIN_CONFIDENCE", "0.50")),
            image_embedding_enabled=os.getenv("IMAGE_EMBEDDING_ENABLED", "false").lower()
            in {"1", "true", "yes", "on"},
            image_embedding_model=os.getenv("IMAGE_EMBEDDING_MODEL", "Qdrant/clip-ViT-B-32-vision"),
            image_text_embedding_model=os.getenv("IMAGE_TEXT_EMBEDDING_MODEL", "Qdrant/clip-ViT-B-32-text"),
            model_cache_dir=Path(os.getenv("MODEL_CACHE_DIR", "data/models/fastembed")),
            visual_similarity_threshold=float(os.getenv("VISUAL_SIMILARITY_THRESHOLD", "0.28")),
            visual_similarity_margin=float(os.getenv("VISUAL_SIMILARITY_MARGIN", "0.002")),
            model_api_key=os.getenv("MODEL_API_KEY") or os.getenv("DEEPSEEK_API_KEY", ""),
            model_base_url=os.getenv("MODEL_BASE_URL", "https://api.deepseek.com"),
            model_name=os.getenv("MODEL_NAME", "deepseek-v4-flash"),
            model_vision_enabled=os.getenv("MODEL_VISION_ENABLED", "false").lower()
            in {"1", "true", "yes", "on"},
            model_max_visual_images=int(os.getenv("MODEL_MAX_VISUAL_IMAGES", "3")),
            model_max_visual_bytes=int(os.getenv("MODEL_MAX_VISUAL_BYTES", "6000000")),
            model_timeout_seconds=float(os.getenv("MODEL_TIMEOUT_SECONDS", "8")),
            model_request_deadline_seconds=float(
                os.getenv("MODEL_REQUEST_DEADLINE_SECONDS", "12")
            ),
            model_max_retries=int(os.getenv("MODEL_MAX_RETRIES", "1")),
            model_retry_base_delay_seconds=float(
                os.getenv("MODEL_RETRY_BASE_DELAY_SECONDS", "0.1")
            ),
            model_retry_max_delay_seconds=float(
                os.getenv("MODEL_RETRY_MAX_DELAY_SECONDS", "2")
            ),
            model_retry_jitter_ratio=float(os.getenv("MODEL_RETRY_JITTER_RATIO", "0.2")),
            model_retry_after_max_seconds=float(
                os.getenv("MODEL_RETRY_AFTER_MAX_SECONDS", "5")
            ),
            model_retry_budget_global_capacity=int(
                os.getenv("MODEL_RETRY_BUDGET_GLOBAL_CAPACITY", "32")
            ),
            model_retry_budget_global_refill_per_second=float(
                os.getenv("MODEL_RETRY_BUDGET_GLOBAL_REFILL_PER_SECOND", "4")
            ),
            model_retry_budget_per_tenant_capacity=int(
                os.getenv("MODEL_RETRY_BUDGET_PER_TENANT_CAPACITY", "8")
            ),
            model_retry_budget_per_tenant_refill_per_second=float(
                os.getenv("MODEL_RETRY_BUDGET_PER_TENANT_REFILL_PER_SECOND", "1")
            ),
            model_max_concurrency=int(os.getenv("MODEL_MAX_CONCURRENCY", "4")),
            model_max_concurrency_per_tenant=int(
                os.getenv("MODEL_MAX_CONCURRENCY_PER_TENANT", "2")
            ),
            model_max_queue_waiters=int(os.getenv("MODEL_MAX_QUEUE_WAITERS", "8")),
            model_max_queue_waiters_per_tenant=int(
                os.getenv("MODEL_MAX_QUEUE_WAITERS_PER_TENANT", "4")
            ),
            model_queue_timeout_seconds=float(os.getenv("MODEL_QUEUE_TIMEOUT_SECONDS", "0.25")),
            model_overload_retry_after_seconds=int(os.getenv("MODEL_OVERLOAD_RETRY_AFTER_SECONDS", "1")),
            model_circuit_failure_threshold=int(
                os.getenv("MODEL_CIRCUIT_FAILURE_THRESHOLD", "5")
            ),
            model_circuit_recovery_seconds=float(
                os.getenv("MODEL_CIRCUIT_RECOVERY_SECONDS", "30")
            ),
            model_shutdown_timeout_seconds=float(
                os.getenv("MODEL_SHUTDOWN_TIMEOUT_SECONDS", "5")
            ),
            summary_model_timeout_seconds=float(os.getenv("SUMMARY_MODEL_TIMEOUT_SECONDS", "30")),
        )
