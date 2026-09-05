"""User business rules."""

from pathlib import Path

from app.models.users import User, UserCreate
from app.repositories import users as repository


def create_user(path: Path, tenant_id: str, data: UserCreate) -> User:
    return repository.create_user(path, tenant_id, data)


def get_user(path: Path, tenant_id: str, user_id: int) -> User | None:
    return repository.get_user(path, tenant_id, user_id)
