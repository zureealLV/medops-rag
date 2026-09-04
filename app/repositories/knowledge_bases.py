"""Knowledge-base persistence operations."""
from app.models.knowledge_bases import (
    KnowledgeBase,
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
)


knowledge_bases: dict[int, KnowledgeBase] = {}

next_kb_id = 1


def create_knowledge_base(
    knowledge_base: KnowledgeBaseCreate,
) -> KnowledgeBase:

    global next_kb_id

    new_knowledge_base = KnowledgeBase(
        id=next_kb_id,
        name=knowledge_base.name,
        description=knowledge_base.description,
    )

    knowledge_bases[next_kb_id] = new_knowledge_base

    next_kb_id += 1

    return new_knowledge_base


def list_knowledge_bases() -> list[KnowledgeBase]:
    return list(knowledge_bases.values())


def get_knowledge_base(
    kb_id: int,
) -> KnowledgeBase | None:

    return knowledge_bases.get(kb_id)


def update_knowledge_base(
    kb_id: int,
    knowledge_base: KnowledgeBaseUpdate,
) -> KnowledgeBase | None:

    stored_knowledge_base = knowledge_bases.get(kb_id)

    if stored_knowledge_base is None:
        return None

    update_data = knowledge_base.model_dump(
        exclude_unset=True
    )

    stored_data = stored_knowledge_base.model_dump()

    stored_data.update(update_data)

    updated_knowledge_base = KnowledgeBase(
        **stored_data
    )

    knowledge_bases[kb_id] = updated_knowledge_base

    return updated_knowledge_base


def delete_knowledge_base(
    kb_id: int,
) -> bool:

    if kb_id not in knowledge_bases:
        return False

    del knowledge_bases[kb_id]

    return True