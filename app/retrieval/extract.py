"""Backward-compatible extraction helpers.

New code should use :mod:`app.ingestion.parsers` directly so it can retain
element-level provenance instead of flattening the parsed document to text.
"""

from pathlib import Path

from app.ingestion.parsers import SUPPORTED_SUFFIXES as SUPPORTED_SUFFIXES
from app.ingestion.parsers import parse_bytes


def extract_file(path: Path) -> str:
    return extract_bytes(path.name, path.read_bytes())


def extract_bytes(filename: str, content: bytes) -> str:
    return parse_bytes(filename, content).content
