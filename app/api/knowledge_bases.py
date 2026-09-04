"""Knowledge-base HTTP endpoints."""
from fastapi import APIRouter, HTTPException

from app.models.knowledge_bases import (
    KnowledgeBase,
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
)

from app.services import knowledge_bases as kb_service


router = APIRouter(
    prefix="/knowledge-bases",
    tags=["knowledge-bases"],
)


@router.post("", response_model=KnowledgeBase)
async def create_knowledge_base(
    knowledge_base: KnowledgeBaseCreate,
):
    return kb_service.create_knowledge_base(
        knowledge_base
    )


@router.get("", response_model=list[KnowledgeBase])
async def list_knowledge_bases():
    return kb_service.list_knowledge_bases()


@router.get("/{kb_id}", response_model=KnowledgeBase)
async def get_knowledge_base(kb_id: int):

    knowledge_base = kb_service.get_knowledge_base(kb_id)

    if knowledge_base is None:
        raise HTTPException(
            status_code=404,
            detail="Knowledge base not found",
        )

    return knowledge_base


@router.patch("/{kb_id}", response_model=KnowledgeBase)
async def update_knowledge_base(
    kb_id: int,
    knowledge_base: KnowledgeBaseUpdate,
):

    updated_knowledge_base = (
        kb_service.update_knowledge_base(
            kb_id,
            knowledge_base,
        )
    )

    if updated_knowledge_base is None:
        raise HTTPException(
            status_code=404,
            detail="Knowledge base not found",
        )

    return updated_knowledge_base


@router.delete("/{kb_id}")
async def delete_knowledge_base(kb_id: int):

    deleted = kb_service.delete_knowledge_base(kb_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Knowledge base not found",
        )

    return {
        "deleted": True,
        "kb_id": kb_id,
    }