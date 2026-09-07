"""Backup-first SQLite upgrade and rollback primitives."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.db import initialize


def _integrity_check(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    if result is None or result[0] != "ok":
        raise RuntimeError(f"SQLite integrity check failed for {path}")


def database_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def default_backup_path(path: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return path.with_name(f"{path.name}.pre-v2.{timestamp}.bak")


def backup_database(source: Path, destination: Path) -> str:
    if not source.exists():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    with sqlite3.connect(source) as source_connection, sqlite3.connect(
        destination
    ) as destination_connection:
        source_connection.backup(destination_connection)
    _integrity_check(destination)
    return database_sha256(destination)


def restore_database(destination: Path, backup: Path) -> str:
    if not backup.exists():
        raise FileNotFoundError(backup)
    _integrity_check(backup)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # The online backup API replaces destination pages while respecting WAL
    # and Windows file locks. Operators must still stop application writers.
    with sqlite3.connect(backup) as source_connection, sqlite3.connect(
        destination
    ) as destination_connection:
        source_connection.backup(destination_connection)
        destination_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    _integrity_check(destination)
    return database_sha256(destination)


def upgrade_database(path: Path, backup: Path | None = None) -> tuple[Path | None, str]:
    created_backup: Path | None = None
    if path.exists():
        created_backup = backup or default_backup_path(path)
        backup_database(path, created_backup)
    try:
        initialize(path)
        _integrity_check(path)
    except Exception:
        if created_backup is not None:
            restore_database(path, created_backup)
        raise
    return created_backup, database_sha256(path)
