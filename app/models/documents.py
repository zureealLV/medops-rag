"""Document and chunk request, response, and metadata models."""
from pydantic import BaseModel, model_validator


class DocumentCreate(BaseModel):
    title: str
    content: str


class DocumentUpdate(BaseModel):
    title: str | None = None
    content: str | None = None

    @model_validator(mode="after")
    def validate_update(self):
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be null")

        if "content" in self.model_fields_set and self.content is None:
            raise ValueError("content cannot be null")

        return self


class Document(BaseModel):
    id: int
    kb_id: int
    title: str
    content: str