"""Knowledge-base business rules."""

import sqlite3
from pathlib import Path

from app.exceptions import AppError
from app.models.knowledge_bases import KnowledgeBase, KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.repositories import knowledge_bases as repository


def create(path: Path, tenant_id: str, data: KnowledgeBaseCreate) -> KnowledgeBase:
    try:
        return repository.create(path, tenant_id, data)
    except sqlite3.IntegrityError as exc:
        raise AppError(
            409, "knowledge_base_exists", "A knowledge base with this name already exists"
        ) from exc


def list_all(path: Path, tenant_id: str) -> list[KnowledgeBase]:
    return repository.list_all(path, tenant_id)


def get(path: Path, tenant_id: str, kb_id: int) -> KnowledgeBase | None:
    return repository.get(path, tenant_id, kb_id)


def update(path: Path, tenant_id: str, kb_id: int, data: KnowledgeBaseUpdate) -> KnowledgeBase | None:
    try:
        return repository.update(path, tenant_id, kb_id, data)
    except sqlite3.IntegrityError as exc:
        raise AppError(
            409, "knowledge_base_exists", "A knowledge base with this name already exists"
        ) from exc


def delete(path: Path, tenant_id: str, kb_id: int) -> bool:
    return repository.delete(path, tenant_id, kb_id)
