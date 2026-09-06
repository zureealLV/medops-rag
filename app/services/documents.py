"""Document lifecycle and ingestion orchestration."""

import sqlite3
from pathlib import Path

from app.config import Settings
from app.ingestion.parsers import ParsedDocument
from app.models.documents import Document, DocumentCreate, DocumentUpdate
from app.repositories import documents as repository
from app.repositories import knowledge_bases
from app.retrieval.chunking import split_text


def create(
    path: Path, settings: Settings, tenant_id: str, kb_id: int, data: DocumentCreate
) -> Document | None:
    if knowledge_bases.get(path, tenant_id, kb_id) is None:
        return None
    chunks = split_text(data.content, size=settings.chunk_size, overlap=settings.chunk_overlap)
    return repository.create(path, tenant_id, kb_id, data, chunks)


def create_from_parsed(
    path: Path, settings: Settings, tenant_id: str, kb_id: int, parsed: ParsedDocument
) -> tuple[Document | None, bool]:
    if knowledge_bases.get(path, tenant_id, kb_id) is None:
        return None, False
    existing = repository.find_by_hash(path, tenant_id, kb_id, parsed.sha256)
    if existing is not None:
        return existing, True
    content = parsed.content
    chunks = split_text(content, size=settings.chunk_size, overlap=settings.chunk_overlap)
    try:
        document = repository.create(
            path,
            tenant_id,
            kb_id,
            DocumentCreate(title=Path(parsed.filename).stem, content=content, source=parsed.filename),
            chunks,
            parsed,
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
    if data.content is not None:
        chunks = split_text(data.content, size=settings.chunk_size, overlap=settings.chunk_overlap)
    return repository.update(path, tenant_id, document_id, data, chunks)


def delete(path: Path, tenant_id: str, document_id: int) -> bool:
    return repository.delete(path, tenant_id, document_id)


def list_elements(path: Path, tenant_id: str, document_id: int):
    return repository.list_elements(path, tenant_id, document_id)
