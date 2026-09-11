"""Structure-aware parent contexts with smaller retrieval children."""

from __future__ import annotations

from dataclasses import dataclass

from app.ingestion.parsers import NormalizedElement
from app.retrieval.chunking import normalize_text, split_text


@dataclass(frozen=True, slots=True)
class ParentChunkPlan:
    text: str
    children: tuple[str, ...]
    element_start: int | None
    element_end: int | None
    page_start: int | None
    page_end: int | None
    heading: str | None


def build_parent_child_chunks(
    elements: tuple[NormalizedElement, ...],
    *,
    parent_size: int = 1600,
    child_size: int = 350,
    child_overlap: int = 50,
) -> list[ParentChunkPlan]:
    """Pack adjacent elements by heading/size, then split each parent for retrieval."""
    if parent_size < child_size:
        raise ValueError("parent chunk size must be at least child chunk size")

    materialized = []
    for index, element in enumerate(elements):
        text = normalize_text(element.text)
        if text:
            materialized.append((index, element, text))
    plans: list[ParentChunkPlan] = []
    current: list[tuple[int, NormalizedElement, str]] = []

    def flush() -> None:
        if not current:
            return
        text = "\n\n".join(item[2] for item in current)
        pages = [item[1].page_number for item in current if item[1].page_number is not None]
        heading = next((item[1].heading for item in current if item[1].heading), None)
        children = tuple(split_text(text, size=child_size, overlap=child_overlap))
        plans.append(
            ParentChunkPlan(
                text=text,
                children=children,
                element_start=current[0][0],
                element_end=current[-1][0],
                page_start=min(pages) if pages else None,
                page_end=max(pages) if pages else None,
                heading=heading,
            )
        )
        current.clear()

    for index, element, text in materialized:
        current_length = sum(len(item[2]) + 2 for item in current)
        current_heading = next((item[1].heading for item in current if item[1].heading), None)
        heading_boundary = bool(current and element.heading and element.heading != current_heading)
        if current and (heading_boundary or current_length + len(text) > parent_size):
            flush()
        if len(text) <= parent_size:
            current.append((index, element, text))
            continue
        for part in split_text(text, size=parent_size, overlap=0):
            current.append((index, element, part))
            flush()
    flush()
    return plans
