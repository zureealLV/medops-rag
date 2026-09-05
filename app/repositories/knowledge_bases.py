"""SQLite knowledge-base persistence operations."""

import sqlite3
from pathlib import Path

from app.db import transaction
from app.models.knowledge_bases import KnowledgeBase, KnowledgeBaseCreate, KnowledgeBaseUpdate


def _model(row: sqlite3.Row) -> KnowledgeBase:
    return KnowledgeBase(**dict(row))


def create(path: Path, tenant_id: str, data: KnowledgeBaseCreate) -> KnowledgeBase:
    with transaction(path) as connection:
        cursor = connection.execute(
            "INSERT INTO knowledge_bases (tenant_id, name, description) VALUES (?, ?, ?)",
            (tenant_id, data.name, data.description),
        )
        row = connection.execute(
            "SELECT id, tenant_id, name, description FROM knowledge_bases WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return _model(row)


def list_all(path: Path, tenant_id: str) -> list[KnowledgeBase]:
    with transaction(path) as connection:
        rows = connection.execute(
            "SELECT id, tenant_id, name, description FROM knowledge_bases WHERE tenant_id = ? ORDER BY id",
            (tenant_id,),
        ).fetchall()
    return [_model(row) for row in rows]


def get(path: Path, tenant_id: str, kb_id: int) -> KnowledgeBase | None:
    with transaction(path) as connection:
        row = connection.execute(
            "SELECT id, tenant_id, name, description FROM knowledge_bases WHERE id = ? AND tenant_id = ?",
            (kb_id, tenant_id),
        ).fetchone()
    return _model(row) if row else None


def update(path: Path, tenant_id: str, kb_id: int, data: KnowledgeBaseUpdate) -> KnowledgeBase | None:
    stored = get(path, tenant_id, kb_id)
    if stored is None:
        return None
    values = stored.model_dump()
    values.update(data.model_dump(exclude_unset=True))
    with transaction(path) as connection:
        connection.execute(
            "UPDATE knowledge_bases SET name = ?, description = ? WHERE id = ? AND tenant_id = ?",
            (values["name"], values["description"], kb_id, tenant_id),
        )
    return KnowledgeBase(**values)


def delete(path: Path, tenant_id: str, kb_id: int) -> bool:
    with transaction(path) as connection:
        cursor = connection.execute(
            "DELETE FROM knowledge_bases WHERE id = ? AND tenant_id = ?", (kb_id, tenant_id)
        )
        return cursor.rowcount == 1
