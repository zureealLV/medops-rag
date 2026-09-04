"""Knowledge-base business rules."""
from app.repositories import documents as document_repository
from app.models.knowledge_bases import (
    KnowledgeBase,
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
)

from app.repositories import knowledge_bases as kb_repository


def create_knowledge_base(
    knowledge_base: KnowledgeBaseCreate,
) -> KnowledgeBase:

    return kb_repository.create_knowledge_base(
        knowledge_base
    )


def list_knowledge_bases() -> list[KnowledgeBase]:

    return kb_repository.list_knowledge_bases()


def get_knowledge_base(
    kb_id: int,
) -> KnowledgeBase | None:

    return kb_repository.get_knowledge_base(kb_id)


def update_knowledge_base(
    kb_id: int,
    knowledge_base: KnowledgeBaseUpdate,
) -> KnowledgeBase | None:

    return kb_repository.update_knowledge_base(
        kb_id,
        knowledge_base,
    )


def delete_knowledge_base(
    kb_id: int,
) -> bool:

    knowledge_base = kb_repository.get_knowledge_base(
        kb_id
    )

    if knowledge_base is None:
        return False

    document_repository.delete_documents_by_kb_id(
        kb_id
    )

    return kb_repository.delete_knowledge_base(
        kb_id
    )