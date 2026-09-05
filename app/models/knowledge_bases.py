"""Knowledge-base create, update, and response models."""

from pydantic import BaseModel, Field, model_validator


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_update(self):
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")

        return self


class KnowledgeBase(BaseModel):
    id: int
    tenant_id: str
    name: str
    description: str | None = None
