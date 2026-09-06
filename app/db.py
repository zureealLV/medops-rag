"""SQLite connection and schema lifecycle."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);
CREATE TABLE IF NOT EXISTS knowledge_bases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, name)
);
CREATE INDEX IF NOT EXISTS idx_kb_tenant ON knowledge_bases(tenant_id);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    knowledge_base_id INTEGER NOT NULL,
    tenant_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'text/plain',
    sha256 TEXT NOT NULL DEFAULT '',
    parser TEXT NOT NULL DEFAULT 'manual',
    ingest_status TEXT NOT NULL DEFAULT 'succeeded',
    warning_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_documents_kb ON documents(knowledge_base_id);
CREATE INDEX IF NOT EXISTS idx_documents_tenant ON documents(tenant_id);
CREATE TABLE IF NOT EXISTS document_elements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    element_index INTEGER NOT NULL,
    modality TEXT NOT NULL,
    text TEXT NOT NULL,
    page_number INTEGER,
    heading TEXT,
    artifact_sha256 TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    UNIQUE(document_id, element_index)
);
CREATE INDEX IF NOT EXISTS idx_document_elements_document ON document_elements(document_id);
CREATE TABLE IF NOT EXISTS artifact_blobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    content BLOB NOT NULL,
    embedding_json TEXT,
    embedding_model TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, sha256)
);
CREATE INDEX IF NOT EXISTS idx_artifact_blobs_tenant ON artifact_blobs(tenant_id);
CREATE TABLE IF NOT EXISTS document_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    blob_id INTEGER NOT NULL,
    artifact_index INTEGER NOT NULL,
    page_number INTEGER,
    bbox_json TEXT,
    ocr_text TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(blob_id) REFERENCES artifact_blobs(id) ON DELETE RESTRICT,
    UNIQUE(document_id, artifact_index)
);
CREATE INDEX IF NOT EXISTS idx_document_artifacts_document ON document_artifacts(document_id);
CREATE INDEX IF NOT EXISTS idx_document_artifacts_blob ON document_artifacts(blob_id);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    knowledge_base_id INTEGER NOT NULL,
    tenant_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    embedding_json TEXT NOT NULL,
    embedding_model TEXT NOT NULL DEFAULT 'medops/hashing-256-v1',
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    UNIQUE(document_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_chunks_tenant_kb ON chunks(tenant_id, knowledge_base_id);
CREATE TABLE IF NOT EXISTS parent_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    knowledge_base_id INTEGER NOT NULL,
    tenant_id TEXT NOT NULL,
    parent_index INTEGER NOT NULL,
    element_start INTEGER,
    element_end INTEGER,
    page_start INTEGER,
    page_end INTEGER,
    heading TEXT,
    text TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    UNIQUE(document_id, parent_index)
);
CREATE INDEX IF NOT EXISTS idx_parent_chunks_tenant_kb
    ON parent_chunks(tenant_id, knowledge_base_id);
CREATE TABLE IF NOT EXISTS child_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER NOT NULL,
    document_id INTEGER NOT NULL,
    knowledge_base_id INTEGER NOT NULL,
    tenant_id TEXT NOT NULL,
    child_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    embedding_json TEXT NOT NULL,
    embedding_model TEXT NOT NULL DEFAULT 'medops/hashing-256-v1',
    FOREIGN KEY(parent_id) REFERENCES parent_chunks(id) ON DELETE CASCADE,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    UNIQUE(parent_id, child_index)
);
CREATE INDEX IF NOT EXISTS idx_child_chunks_tenant_kb
    ON child_chunks(tenant_id, knowledge_base_id);
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    knowledge_base_id INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL,
    filename TEXT NOT NULL,
    declared_mime TEXT,
    content BLOB,
    content_sha256 TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('queued','running','succeeded','failed','partial','cancelled')),
    progress INTEGER NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    lease_owner TEXT,
    lease_expires_at REAL,
    document_id INTEGER,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE SET NULL,
    UNIQUE(tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_claim
    ON ingestion_jobs(state, lease_expires_at, created_at);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_tenant
    ON ingestion_jobs(tenant_id, created_at);
CREATE TABLE IF NOT EXISTS summary_jobs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    knowledge_base_id INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    question TEXT NOT NULL,
    document_ids_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('queued','running','succeeded','failed','partial','cancelled')),
    progress INTEGER NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    lease_owner TEXT,
    lease_expires_at REAL,
    summary TEXT,
    provider TEXT,
    token_usage INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    UNIQUE(tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_summary_jobs_claim
    ON summary_jobs(state, lease_expires_at, created_at);
CREATE INDEX IF NOT EXISTS idx_summary_jobs_tenant
    ON summary_jobs(tenant_id, created_at);
CREATE TABLE IF NOT EXISTS summary_map_results (
    job_id TEXT NOT NULL,
    document_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('succeeded','failed')),
    source TEXT NOT NULL,
    summary TEXT,
    provider TEXT,
    token_usage INTEGER NOT NULL DEFAULT 0,
    citation_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(job_id, document_id),
    FOREIGN KEY(job_id) REFERENCES summary_jobs(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    action TEXT NOT NULL,
    resource TEXT NOT NULL,
    result TEXT NOT NULL,
    details TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_logs(tenant_id, created_at);
CREATE TABLE IF NOT EXISTS request_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    path TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    latency_ms REAL NOT NULL,
    error_type TEXT,
    abstained INTEGER NOT NULL DEFAULT 0,
    retrieval_ms REAL NOT NULL DEFAULT 0,
    model_ms REAL NOT NULL DEFAULT 0,
    token_usage INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def transaction(path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize(path: Path) -> None:
    with transaction(path) as connection:
        connection.executescript(SCHEMA)
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(request_metrics)")}
        if "retrieval_ms" not in columns:
            connection.execute("ALTER TABLE request_metrics ADD COLUMN retrieval_ms REAL NOT NULL DEFAULT 0")
        if "model_ms" not in columns:
            connection.execute("ALTER TABLE request_metrics ADD COLUMN model_ms REAL NOT NULL DEFAULT 0")
        if "token_usage" not in columns:
            connection.execute(
                "ALTER TABLE request_metrics ADD COLUMN token_usage INTEGER NOT NULL DEFAULT 0"
            )
        document_columns = {row["name"] for row in connection.execute("PRAGMA table_info(documents)")}
        migrations = {
            "mime_type": "ALTER TABLE documents ADD COLUMN mime_type TEXT NOT NULL DEFAULT 'text/plain'",
            "sha256": "ALTER TABLE documents ADD COLUMN sha256 TEXT NOT NULL DEFAULT ''",
            "parser": "ALTER TABLE documents ADD COLUMN parser TEXT NOT NULL DEFAULT 'manual'",
            "ingest_status": (
                "ALTER TABLE documents ADD COLUMN ingest_status TEXT NOT NULL DEFAULT 'succeeded'"
            ),
            "warning_json": "ALTER TABLE documents ADD COLUMN warning_json TEXT NOT NULL DEFAULT '[]'",
        }
        for name, sql in migrations.items():
            if name not in document_columns:
                connection.execute(sql)
        element_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(document_elements)")
        }
        if "artifact_sha256" not in element_columns:
            connection.execute("ALTER TABLE document_elements ADD COLUMN artifact_sha256 TEXT")
        for table in ("chunks", "child_chunks"):
            columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            if "embedding_model" not in columns:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN embedding_model TEXT NOT NULL "
                    "DEFAULT 'medops/hashing-256-v1'"
                )
        connection.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_ingest_dedup
               ON documents(tenant_id, knowledge_base_id, sha256) WHERE sha256 <> ''"""
        )
        # Existing alpha databases have only fixed chunks. Preserve their searchability
        # under the new strategy without rewriting or deleting the legacy rows. New and
        # edited documents receive richer structure-aware parents in the service layer.
        connection.execute(
            """INSERT INTO parent_chunks
               (document_id, knowledge_base_id, tenant_id, parent_index, text)
               SELECT c.document_id, c.knowledge_base_id, c.tenant_id, c.chunk_index, c.text
               FROM chunks c
               WHERE NOT EXISTS (
                   SELECT 1 FROM parent_chunks p WHERE p.document_id = c.document_id
               )"""
        )
        connection.execute(
            """INSERT INTO child_chunks
               (parent_id, document_id, knowledge_base_id, tenant_id, child_index, text,
                embedding_json, embedding_model)
               SELECT p.id, c.document_id, c.knowledge_base_id, c.tenant_id, 0, c.text,
                      c.embedding_json, c.embedding_model
               FROM chunks c
               JOIN parent_chunks p
                 ON p.document_id = c.document_id AND p.parent_index = c.chunk_index
               WHERE NOT EXISTS (
                   SELECT 1 FROM child_chunks cc WHERE cc.parent_id = p.id
               )"""
        )
