"""Document and chunk persistence operations."""
from app.models.documents import (
    Document,
    DocumentCreate,
    DocumentUpdate,
)


documents: dict[int, Document] = {}

next_document_id = 1


def create_document(
    kb_id: int,
    document: DocumentCreate,
) -> Document:

    global next_document_id

    new_document = Document(
        id=next_document_id,
        kb_id=kb_id,
        title=document.title,
        content=document.content,
    )

    documents[next_document_id] = new_document

    next_document_id += 1

    return new_document


def get_document(
    document_id: int,
) -> Document | None:

    return documents.get(document_id)


def update_document(
    document_id: int,
    document: DocumentUpdate,
) -> Document | None:

    stored_document = documents.get(document_id)

    if stored_document is None:
        return None

    update_data = document.model_dump(
        exclude_unset=True
    )

    stored_data = stored_document.model_dump()

    stored_data.update(update_data)

    updated_document = Document(
        **stored_data
    )

    documents[document_id] = updated_document

    return updated_document


def delete_document(
    document_id: int,
) -> bool:

    if document_id not in documents:
        return False

    del documents[document_id]

    return True


def delete_documents_by_kb_id(
    kb_id: int,
) -> int:

    document_ids = [
        document_id
        for document_id, document in documents.items()
        if document.kb_id == kb_id
    ]

    for document_id in document_ids:
        del documents[document_id]

    return len(document_ids)