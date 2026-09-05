"""Allowlisted tool execution with validated arguments."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.exceptions import AppError
from app.models.retrieval import SearchRequest
from app.models.tools import DocumentMetadataArgs, SearchDocumentsArgs, SystemStatusArgs
from app.repositories.documents import get as get_document
from app.services.retrieval import search

ALLOWED_TOOLS = {
    "search_documents": SearchDocumentsArgs,
    "get_document_metadata": DocumentMetadataArgs,
    "get_system_status": SystemStatusArgs,
}


def execute(path: Path, tenant_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    schema = ALLOWED_TOOLS.get(name)
    if schema is None:
        raise AppError(403, "tool_not_allowed", f"Tool '{name}' is not allowlisted")
    try:
        parsed = schema.model_validate(arguments)
    except ValidationError as exc:
        raise AppError(
            422, "invalid_tool_arguments", "Tool arguments failed validation", {"errors": exc.errors()}
        ) from exc

    if name == "search_documents":
        result = search(path, tenant_id, SearchRequest(**parsed.model_dump()))
        if result is None:
            raise AppError(404, "knowledge_base_not_found", "Knowledge base not found")
        return result.model_dump()
    if name == "get_document_metadata":
        document = get_document(path, tenant_id, parsed.document_id)
        if document is None:
            raise AppError(404, "document_not_found", "Document not found")
        return document.model_dump(exclude={"content"})
    return {"status": "ok", "database": "reachable", "mode": "read-only-tools"}
