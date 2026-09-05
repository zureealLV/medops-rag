"""Document and chunk request, response, and metadata models."""

from pydantic import BaseModel, Field, model_validator


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=200_000)
    source: str = Field(default="manual", min_length=1, max_length=300)


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1, max_length=200_000)
    source: str | None = Field(default=None, min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_update(self):
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be null")

        if "content" in self.model_fields_set and self.content is None:
            raise ValueError("content cannot be null")

        if "source" in self.model_fields_set and self.source is None:
            raise ValueError("source cannot be null")

        return self


class Document(BaseModel):
    id: int
    kb_id: int
    tenant_id: str
    title: str
    content: str
    source: str
    chunk_count: int = 0
