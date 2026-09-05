"""Split normalized text into overlapping, traceable chunks."""

from __future__ import annotations

import re


def normalize_text(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def split_text(text: str, *, size: int = 600, overlap: int = 80) -> list[str]:
    if size < 100:
        raise ValueError("chunk size must be at least 100")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be non-negative and smaller than size")

    normalized = normalize_text(text)
    if not normalized:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        target_end = min(start + size, len(normalized))
        end = target_end
        if target_end < len(normalized):
            boundary = max(
                normalized.rfind("\n", start + size // 2, target_end),
                normalized.rfind("。", start + size // 2, target_end),
                normalized.rfind(". ", start + size // 2, target_end),
            )
            if boundary > start:
                end = boundary + 1
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)
    return chunks
