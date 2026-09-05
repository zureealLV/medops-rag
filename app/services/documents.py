"""Document lifecycle and ingestion orchestration."""

from pathlib import Path

from app.config import Settings
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
