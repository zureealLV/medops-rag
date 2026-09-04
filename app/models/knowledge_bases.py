"""Knowledge-base create, update, and response models."""
from pydantic import BaseModel, model_validator


class KnowledgeBaseCreate(BaseModel):
    name: str
    description: str | None = None


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = None
    description: str | None = None

    @model_validator(mode="after")
    def validate_update(self):
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")

        return self


class KnowledgeBase(BaseModel):
    id: int
    name: str
    description: str | None = None