"""SQLite user persistence operations."""

from pathlib import Path

from app.db import transaction
from app.models.users import User, UserCreate


def create_user(path: Path, tenant_id: str, data: UserCreate) -> User:
    with transaction(path) as connection:
        cursor = connection.execute(
            "INSERT INTO users (tenant_id, name, email) VALUES (?, ?, ?)",
            (tenant_id, data.name, data.email),
        )
        return User(id=cursor.lastrowid, tenant_id=tenant_id, **data.model_dump())


def get_user(path: Path, tenant_id: str, user_id: int) -> User | None:
    with transaction(path) as connection:
        row = connection.execute(
            "SELECT id, tenant_id, name, email FROM users WHERE id = ? AND tenant_id = ?",
            (user_id, tenant_id),
        ).fetchone()
    return User(**dict(row)) if row else None
