"""Tenant-scoped image blob deduplication and document artifact references."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.db import transaction
from app.ingestion import ParsedArtifact


def persist(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    document_id: int,
    artifacts: tuple[ParsedArtifact, ...],
    embeddings: dict[str, list[float]],
    embedding_model: str | None,
) -> None:
    for index, artifact in enumerate(artifacts):
        embedding = embeddings.get(artifact.sha256)
        connection.execute(
            """INSERT INTO artifact_blobs
               (tenant_id, sha256, mime_type, width, height, content, embedding_json, embedding_model)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(tenant_id, sha256) DO NOTHING""",
            (
                tenant_id,
                artifact.sha256,
                artifact.mime_type,
                artifact.width,
                artifact.height,
                artifact.content,
                json.dumps(embedding) if embedding is not None else None,
                embedding_model if embedding is not None else None,
            ),
        )
        row = connection.execute(
            """SELECT id, embedding_json, embedding_model FROM artifact_blobs
               WHERE tenant_id = ? AND sha256 = ?""",
            (tenant_id, artifact.sha256),
        ).fetchone()
        if row is None:
            raise RuntimeError("artifact blob disappeared during persistence")
        blob_id = int(row["id"])
        if embedding is not None and (
            row["embedding_json"] is None or row["embedding_model"] != embedding_model
        ):
            connection.execute(
                """UPDATE artifact_blobs SET embedding_json = ?, embedding_model = ?
                   WHERE id = ? AND tenant_id = ?""",
                (json.dumps(embedding), embedding_model, blob_id, tenant_id),
            )
        connection.execute(
            """INSERT INTO document_artifacts
               (document_id, blob_id, artifact_index, page_number, bbox_json, ocr_text, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                document_id,
                blob_id,
                index,
                artifact.page_number,
                json.dumps(artifact.bbox, ensure_ascii=False) if artifact.bbox else None,
                artifact.ocr_text,
                json.dumps(artifact.metadata, ensure_ascii=False, sort_keys=True),
            ),
        )


ARTIFACT_SELECT = """SELECT da.id, da.document_id, d.source, b.sha256, b.mime_type,
                              b.width, b.height, da.page_number, da.bbox_json, da.ocr_text,
                              da.metadata_json, b.embedding_json, b.embedding_model
                       FROM document_artifacts da
                       JOIN artifact_blobs b ON b.id = da.blob_id
                       JOIN documents d ON d.id = da.document_id"""


def list_for_document(path: Path, tenant_id: str, document_id: int) -> list[sqlite3.Row] | None:
    with transaction(path) as connection:
        exists = connection.execute(
            "SELECT 1 FROM documents WHERE id = ? AND tenant_id = ?", (document_id, tenant_id)
        ).fetchone()
        if exists is None:
            return None
        return list(
            connection.execute(
                ARTIFACT_SELECT
                + " WHERE d.id = ? AND d.tenant_id = ? ORDER BY da.artifact_index",
                (document_id, tenant_id),
            ).fetchall()
        )


def retrieval_rows(
    path: Path, tenant_id: str, knowledge_base_id: int | None = None
) -> list[sqlite3.Row]:
    sql = ARTIFACT_SELECT + " WHERE d.tenant_id = ?"
    params: list[object] = [tenant_id]
    if knowledge_base_id is not None:
        sql += " AND d.knowledge_base_id = ?"
        params.append(knowledge_base_id)
    with transaction(path) as connection:
        return list(connection.execute(sql, params).fetchall())


def get_content(path: Path, tenant_id: str, artifact_id: int) -> sqlite3.Row | None:
    with transaction(path) as connection:
        return connection.execute(
            """SELECT b.content, b.mime_type, b.sha256
               FROM document_artifacts da
               JOIN artifact_blobs b ON b.id = da.blob_id
               JOIN documents d ON d.id = da.document_id
               WHERE da.id = ? AND d.tenant_id = ?""",
            (artifact_id, tenant_id),
        ).fetchone()


def delete_orphan_blobs(connection: sqlite3.Connection, tenant_id: str) -> None:
    connection.execute(
        """DELETE FROM artifact_blobs
           WHERE tenant_id = ?
             AND NOT EXISTS (
                 SELECT 1 FROM document_artifacts da WHERE da.blob_id = artifact_blobs.id
             )""",
        (tenant_id,),
    )
