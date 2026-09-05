"""User request and response models."""

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)


class User(BaseModel):
    id: int
    tenant_id: str
    name: str
    email: str
