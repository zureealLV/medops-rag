"""Exact V1 schema upgrade, data preservation and full-file rollback evidence."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.db import initialize
from app.migrations import database_sha256, restore_database, upgrade_database

V1_SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL,
    name TEXT NOT NULL, email TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE knowledge_bases (
    id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL, name TEXT NOT NULL,
    description TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(tenant_id, name)
);
CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT, knowledge_base_id INTEGER NOT NULL, tenant_id TEXT NOT NULL,
    title TEXT NOT NULL, content TEXT NOT NULL, source TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
);
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL,
    knowledge_base_id INTEGER NOT NULL, tenant_id TEXT NOT NULL, chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL, embedding_json TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    UNIQUE(document_id, chunk_index)
);
CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL, actor TEXT NOT NULL,
    tenant_id TEXT NOT NULL, action TEXT NOT NULL, resource TEXT NOT NULL, result TEXT NOT NULL,
    details TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE request_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL, path TEXT NOT NULL,
    status_code INTEGER NOT NULL, latency_ms REAL NOT NULL, error_type TEXT,
    abstained INTEGER NOT NULL DEFAULT 0, retrieval_ms REAL NOT NULL DEFAULT 0,
    model_ms REAL NOT NULL DEFAULT 0, token_usage INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO users(tenant_id,name,email) VALUES ('hospital-a','Legacy User','legacy@example.test');
INSERT INTO knowledge_bases(tenant_id,name,description) VALUES ('hospital-a','Legacy KB','V1');
INSERT INTO documents(knowledge_base_id,tenant_id,title,content,source)
VALUES (1,'hospital-a','Legacy Runbook','PACS legacy recovery','legacy.md');
INSERT INTO chunks(document_id,knowledge_base_id,tenant_id,chunk_index,text,embedding_json)
VALUES (1,1,'hospital-a',0,'PACS legacy recovery','[1.0,0.0]');
INSERT INTO audit_logs(request_id,actor,tenant_id,action,resource,result,details)
VALUES ('legacy-request','legacy-user','hospital-a','search','chunks','ok','{}');
INSERT INTO request_metrics(request_id,path,status_code,latency_ms)
VALUES ('legacy-request','/search',200,12.5);
"""


def _create_v1(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(V1_SCHEMA)


def test_exact_v1_upgrade_preserves_rows_backfills_indexes_and_rolls_back(tmp_path: Path):
    database = tmp_path / "medops-v1.db"
    backup = tmp_path / "medops-v1.pre-v2.bak"
    _create_v1(database)

    used_backup, upgraded_digest = upgrade_database(database, backup)
    assert used_backup == backup
    assert upgraded_digest == database_sha256(database)
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert connection.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()[0] == "5"
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='conversations'"
        ).fetchone()[0] == 1
        document = connection.execute("SELECT * FROM documents WHERE id=1").fetchone()
        assert document["content"] == "PACS legacy recovery"
        assert document["mime_type"] == "text/plain"
        assert document["parser"] == "manual"
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 1
        assert connection.execute("SELECT tenant_id FROM request_metrics").fetchone()[0] is None
        assert connection.execute("SELECT COUNT(*) FROM parent_chunks").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM agent_checkpoints").fetchone()[0] == 0
        fts_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunks_fts'"
        ).fetchone()
        if fts_exists:
            assert connection.execute(
                "SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'PACS'"
            ).fetchone()[0] == 1
        child = connection.execute("SELECT * FROM child_chunks").fetchone()
        assert child["text"] == "PACS legacy recovery"
        assert child["embedding_model"] == "medops/hashing-256-v1"
        connection.execute(
            "INSERT INTO knowledge_bases(tenant_id,name) VALUES ('hospital-a','V2 only')"
        )
        connection.commit()

    restored_digest = restore_database(database, backup)
    assert restored_digest == database_sha256(database)
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "schema_metadata" not in tables
        assert "parent_chunks" not in tables
        assert connection.execute("SELECT COUNT(*) FROM knowledge_bases").fetchone()[0] == 1
        assert connection.execute("SELECT content FROM documents WHERE id=1").fetchone()[0] == (
            "PACS legacy recovery"
        )


def test_upgrade_new_database_needs_no_backup(tmp_path: Path):
    database = tmp_path / "new.db"
    backup, digest = upgrade_database(database)
    assert backup is None
    assert digest == database_sha256(database)
    initialize(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
