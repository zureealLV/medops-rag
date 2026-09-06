"""Document lifecycle and ingestion orchestration."""

import sqlite3
from pathlib import Path

from app.config import Settings
from app.ingestion.parsers import NormalizedElement, ParsedDocument
from app.models.documents import Document, DocumentCreate, DocumentUpdate
from app.repositories import documents as repository
from app.repositories import knowledge_bases
from app.retrieval.chunking import split_text
from app.retrieval.image_embeddings import provider_from_settings
from app.retrieval.structure_chunking import build_parent_child_chunks


def create(
    path: Path, settings: Settings, tenant_id: str, kb_id: int, data: DocumentCreate
) -> Document | None:
    if knowledge_bases.get(path, tenant_id, kb_id) is None:
        return None
    chunks = split_text(data.content, size=settings.chunk_size, overlap=settings.chunk_overlap)
    elements = (NormalizedElement(modality="text", text=data.content),)
    parents = build_parent_child_chunks(
        elements,
        parent_size=settings.parent_chunk_size,
        child_size=settings.child_chunk_size,
        child_overlap=settings.child_chunk_overlap,
    )
    return repository.create(path, tenant_id, kb_id, data, chunks, parents)


def create_from_parsed(
    path: Path, settings: Settings, tenant_id: str, kb_id: int, parsed: ParsedDocument
) -> tuple[Document | None, bool]:
    if knowledge_bases.get(path, tenant_id, kb_id) is None:
        return None, False
    existing = repository.find_by_hash(path, tenant_id, kb_id, parsed.sha256)
    if existing is not None:
        return existing, True
    content = parsed.content or f"[visual artifact: {parsed.filename}]"
    chunks = split_text(content, size=settings.chunk_size, overlap=settings.chunk_overlap)
    parents = build_parent_child_chunks(
        parsed.elements,
        parent_size=settings.parent_chunk_size,
        child_size=settings.child_chunk_size,
        child_overlap=settings.child_chunk_overlap,
    )
    provider = provider_from_settings(settings)
    artifact_embeddings: dict[str, list[float]] = {}
    if provider is not None:
        for artifact in parsed.artifacts:
            if artifact.sha256 not in artifact_embeddings:
                artifact_embeddings[artifact.sha256] = provider.embed_image(artifact.content)
    try:
        document = repository.create(
            path,
            tenant_id,
            kb_id,
            DocumentCreate(title=Path(parsed.filename).stem, content=content, source=parsed.filename),
            chunks,
            parents,
            parsed,
            artifact_embeddings,
            (
                f"{provider.model_name}|{provider.text_model_name}"
                if provider is not None
                else None
            ),
        )
    except sqlite3.IntegrityError:
        # Close the check-then-insert race through the partial unique index.
        document = repository.find_by_hash(path, tenant_id, kb_id, parsed.sha256)
        if document is None:
            raise
        return document, True
    return document, False


def get(path: Path, tenant_id: str, document_id: int) -> Document | None:
    return repository.get(path, tenant_id, document_id)


def list_for_kb(path: Path, tenant_id: str, kb_id: int) -> list[Document] | None:
    if knowledge_bases.get(path, tenant_id, kb_id) is None:
        return None
    return repository.list_for_kb(path, tenant_id, kb_id)


def update(
    path: Path, settings: Settings, tenant_id: str, document_id: int, data: DocumentUpdate
) -> Document | None:
    chunks = None
    parents = None
    if data.content is not None:
        chunks = split_text(data.content, size=settings.chunk_size, overlap=settings.chunk_overlap)
        parents = build_parent_child_chunks(
            (NormalizedElement(modality="text", text=data.content),),
            parent_size=settings.parent_chunk_size,
            child_size=settings.child_chunk_size,
            child_overlap=settings.child_chunk_overlap,
        )
    return repository.update(path, tenant_id, document_id, data, chunks, parents)


def delete(path: Path, tenant_id: str, document_id: int) -> bool:
    return repository.delete(path, tenant_id, document_id)


def list_elements(path: Path, tenant_id: str, document_id: int):
    return repository.list_elements(path, tenant_id, document_id)
