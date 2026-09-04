"""Document CRUD and upload HTTP endpoints."""
from fastapi import APIRouter, HTTPException

from app.models.documents import (
    Document,
    DocumentCreate,
    DocumentUpdate,
)

from app.services import documents as document_service


router = APIRouter(
    tags=["documents"],
)


@router.post(
    "/knowledge-bases/{kb_id}/documents",
    response_model=Document,
)
async def create_document(
    kb_id: int,
    document: DocumentCreate,
):

    new_document = document_service.create_document(
        kb_id,
        document,
    )

    if new_document is None:
        raise HTTPException(
            status_code=404,
            detail="Knowledge base not found",
        )

    return new_document


@router.get(
    "/documents/{document_id}",
    response_model=Document,
)
async def get_document(document_id: int):

    document = document_service.get_document(
        document_id
    )

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found",
        )

    return document


@router.patch(
    "/documents/{document_id}",
    response_model=Document,
)
async def update_document(
    document_id: int,
    document: DocumentUpdate,
):

    updated_document = (
        document_service.update_document(
            document_id,
            document,
        )
    )

    if updated_document is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found",
        )

    return updated_document


@router.delete(
    "/documents/{document_id}"
)
async def delete_document(document_id: int):

    deleted = document_service.delete_document(
        document_id
    )

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Document not found",
        )

    return {
        "deleted": True,
        "document_id": document_id,
    }