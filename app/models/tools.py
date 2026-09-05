"""Allowlisted tool input and output models."""

from typing import Any

from pydantic import BaseModel, Field


class ToolCallRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallResponse(BaseModel):
    name: str
    result: dict[str, Any]


class SearchDocumentsArgs(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    knowledge_base_id: int | None = Field(default=None, ge=1)
    top_k: int = Field(default=5, ge=1, le=10)


class DocumentMetadataArgs(BaseModel):
    document_id: int = Field(ge=1)


class SystemStatusArgs(BaseModel):
    pass
