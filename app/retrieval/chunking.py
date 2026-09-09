"""Split normalized text into overlapping, traceable chunks."""

from __future__ import annotations

import re

_BOUNDARIES = ("\n", "。", "！", "？", "；", ". ", "! ", "? ", "; ")


def _last_boundary(text: str, start: int, end: int) -> tuple[int, int] | None:
    """Return the right-most semantic boundary and its width in ``[start, end)``."""
    candidates = []
    for marker in _BOUNDARIES:
        position = text.rfind(marker, start, end)
        if position >= 0:
            candidates.append((position, len(marker)))
    return max(candidates, default=None, key=lambda item: item[0])


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
            boundary = _last_boundary(normalized, start + size // 2, target_end)
            if boundary is not None and boundary[0] > start:
                end = boundary[0] + boundary[1]
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        desired_start = max(end - overlap, start + 1)
        # Snap overlap to a nearby sentence/paragraph boundary so the next
        # chunk does not begin in the middle of a Chinese sentence.
        overlap_boundary = _last_boundary(
            normalized,
            max(start, desired_start - overlap),
            desired_start + 1,
        )
        if overlap_boundary is not None and overlap_boundary[0] + overlap_boundary[1] > start:
            start = overlap_boundary[0] + overlap_boundary[1]
        else:
            start = desired_start
    return chunks
