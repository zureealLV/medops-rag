"""Document lifecycle and ingestion orchestration."""

from app.models.documents import (
    Document,
    DocumentCreate,
    DocumentUpdate,
)

from app.repositories import documents as document_repository
from app.repositories import knowledge_bases as kb_repository


def create_document(
    kb_id: int,
    document: DocumentCreate,
) -> Document | None:

    knowledge_base = kb_repository.get_knowledge_base(kb_id)

    if knowledge_base is None:
        return None

    return document_repository.create_document(
        kb_id,
        document,
    )


def get_document(
    document_id: int,
) -> Document | None:

    return document_repository.get_document(
        document_id
    )


def update_document(
    document_id: int,
    document: DocumentUpdate,
) -> Document | None:

    return document_repository.update_document(
        document_id,
        document,
    )


def delete_document(
    document_id: int,
) -> bool:

    return document_repository.delete_document(
        document_id
    )