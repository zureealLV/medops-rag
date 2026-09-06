"""SQLite document and chunk persistence operations."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.db import transaction
from app.ingestion.parsers import ParsedDocument, element_metadata_json
from app.models.documents import Document, DocumentCreate, DocumentUpdate
from app.repositories import artifacts as artifact_repository
from app.retrieval.embeddings import embed


def _model(row: sqlite3.Row) -> Document:
    data = dict(row)
    data["kb_id"] = data.pop("knowledge_base_id")
    data["warnings"] = json.loads(data.pop("warning_json", "[]"))
    return Document(**data)


DOCUMENT_SELECT = """SELECT d.id, d.knowledge_base_id, d.tenant_id, d.title, d.content, d.source,
                            d.mime_type, d.sha256, d.parser, d.ingest_status, d.warning_json,
                            COUNT(DISTINCT c.id) AS chunk_count,
                            COUNT(DISTINCT e.id) AS element_count,
                            COUNT(DISTINCT da.id) AS artifact_count
                     FROM documents d
                     LEFT JOIN chunks c ON c.document_id = d.id
                     LEFT JOIN document_elements e ON e.document_id = d.id
                     LEFT JOIN document_artifacts da ON da.document_id = d.id"""


def _insert_chunks(
    connection: sqlite3.Connection,
    document_id: int,
    kb_id: int,
    tenant_id: str,
    chunks: list[str],
) -> None:
    connection.executemany(
        """INSERT INTO chunks
           (document_id, knowledge_base_id, tenant_id, chunk_index, text, embedding_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (document_id, kb_id, tenant_id, index, text, json.dumps(embed(text)))
            for index, text in enumerate(chunks)
        ],
    )


def create(
    path: Path,
    tenant_id: str,
    kb_id: int,
    data: DocumentCreate,
    chunks: list[str],
    parsed: ParsedDocument | None = None,
    artifact_embeddings: dict[str, list[float]] | None = None,
    artifact_embedding_model: str | None = None,
) -> Document:
    with transaction(path) as connection:
        cursor = connection.execute(
            """INSERT INTO documents
               (knowledge_base_id, tenant_id, title, content, source, mime_type, sha256, parser,
                ingest_status, warning_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'succeeded', ?)""",
            (
                kb_id,
                tenant_id,
                data.title,
                data.content,
                data.source,
                parsed.mime_type if parsed else "text/plain",
                parsed.sha256 if parsed else "",
                parsed.parser if parsed else "manual",
                json.dumps(parsed.warnings if parsed else (), ensure_ascii=False),
            ),
        )
        document_id = int(cursor.lastrowid)
        if parsed:
            connection.executemany(
                """INSERT INTO document_elements
                   (document_id, element_index, modality, text, page_number, heading,
                    artifact_sha256, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        document_id,
                        index,
                        element.modality,
                        element.text,
                        element.page_number,
                        element.heading,
                        element.artifact_sha256,
                        element_metadata_json(element),
                    )
                    for index, element in enumerate(parsed.elements)
                ],
            )
            artifact_repository.persist(
                connection,
                tenant_id=tenant_id,
                document_id=document_id,
                artifacts=parsed.artifacts,
                embeddings=artifact_embeddings or {},
                embedding_model=artifact_embedding_model,
            )
        _insert_chunks(connection, document_id, kb_id, tenant_id, chunks)
        row = connection.execute(
            DOCUMENT_SELECT + " WHERE d.id = ? GROUP BY d.id",
            (document_id,),
        ).fetchone()
    return _model(row)


def get(path: Path, tenant_id: str, document_id: int) -> Document | None:
    with transaction(path) as connection:
        row = connection.execute(
            DOCUMENT_SELECT + " WHERE d.id = ? AND d.tenant_id = ? GROUP BY d.id",
            (document_id, tenant_id),
        ).fetchone()
    return _model(row) if row else None


def list_for_kb(path: Path, tenant_id: str, kb_id: int) -> list[Document]:
    with transaction(path) as connection:
        rows = connection.execute(
            DOCUMENT_SELECT
            + " WHERE d.knowledge_base_id = ? AND d.tenant_id = ? GROUP BY d.id ORDER BY d.id",
            (kb_id, tenant_id),
        ).fetchall()
    return [_model(row) for row in rows]


def find_by_hash(path: Path, tenant_id: str, kb_id: int, sha256: str) -> Document | None:
    with transaction(path) as connection:
        row = connection.execute(
            DOCUMENT_SELECT
            + " WHERE d.tenant_id = ? AND d.knowledge_base_id = ? AND d.sha256 = ? GROUP BY d.id",
            (tenant_id, kb_id, sha256),
        ).fetchone()
    return _model(row) if row else None


def list_elements(path: Path, tenant_id: str, document_id: int) -> list[dict[str, object]] | None:
    if get(path, tenant_id, document_id) is None:
        return None
    with transaction(path) as connection:
        rows = connection.execute(
            """SELECT element_index, modality, text, page_number, heading, artifact_sha256,
                      metadata_json
               FROM document_elements WHERE document_id = ? ORDER BY element_index""",
            (document_id,),
        ).fetchall()
    return [
        {
            "index": row["element_index"],
            "modality": row["modality"],
            "text": row["text"],
            "page_number": row["page_number"],
            "heading": row["heading"],
            "artifact_sha256": row["artifact_sha256"],
            "metadata": json.loads(row["metadata_json"]),
        }
        for row in rows
    ]


def update(
    path: Path,
    tenant_id: str,
    document_id: int,
    data: DocumentUpdate,
    chunks: list[str] | None,
) -> Document | None:
    stored = get(path, tenant_id, document_id)
    if stored is None:
        return None
    values = stored.model_dump(
        exclude={
            "chunk_count",
            "element_count",
            "artifact_count",
            "id",
            "kb_id",
            "tenant_id",
            "mime_type",
            "sha256",
            "parser",
            "ingest_status",
            "warnings",
        }
    )
    values.update(data.model_dump(exclude_unset=True))
    with transaction(path) as connection:
        if chunks is None:
            connection.execute(
                """UPDATE documents SET title = ?, source = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND tenant_id = ?""",
                (values["title"], values["source"], document_id, tenant_id),
            )
        else:
            # A manual content edit invalidates byte identity and parser provenance.
            connection.execute(
                """UPDATE documents
                   SET title = ?, content = ?, source = ?, mime_type = 'text/plain', sha256 = '',
                       parser = 'manual', ingest_status = 'succeeded', warning_json = '[]',
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND tenant_id = ?""",
                (values["title"], values["content"], values["source"], document_id, tenant_id),
            )
            connection.execute("DELETE FROM document_elements WHERE document_id = ?", (document_id,))
            connection.execute("DELETE FROM document_artifacts WHERE document_id = ?", (document_id,))
            artifact_repository.delete_orphan_blobs(connection, tenant_id)
        if chunks is not None:
            connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            _insert_chunks(connection, document_id, stored.kb_id, tenant_id, chunks)
    return get(path, tenant_id, document_id)


def delete(path: Path, tenant_id: str, document_id: int) -> bool:
    with transaction(path) as connection:
        cursor = connection.execute(
            "DELETE FROM documents WHERE id = ? AND tenant_id = ?", (document_id, tenant_id)
        )
        deleted = cursor.rowcount == 1
        if deleted:
            artifact_repository.delete_orphan_blobs(connection, tenant_id)
        return deleted


def retrieval_rows(path: Path, tenant_id: str, kb_id: int | None = None) -> list[sqlite3.Row]:
    sql = """SELECT c.id, c.document_id, c.chunk_index, c.text, c.embedding_json, d.source
             FROM chunks c JOIN documents d ON d.id = c.document_id
             WHERE c.tenant_id = ?"""
    params: list[object] = [tenant_id]
    if kb_id is not None:
        sql += " AND c.knowledge_base_id = ?"
        params.append(kb_id)
    with transaction(path) as connection:
        return list(connection.execute(sql, params).fetchall())
