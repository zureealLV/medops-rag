"""Extraction boundary for V1 text and Markdown documents."""

from pathlib import Path

from app.exceptions import AppError

SUPPORTED_SUFFIXES = {".txt", ".md"}


def extract_file(path: Path) -> str:
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise AppError(400, "unsupported_document", "Only .txt and .md are supported in V1")
    return path.read_text(encoding="utf-8")


def extract_bytes(filename: str, content: bytes) -> str:
    if Path(filename).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise AppError(400, "unsupported_document", "Only .txt and .md are supported in V1")
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError(400, "invalid_encoding", "Uploaded documents must use UTF-8") from exc
