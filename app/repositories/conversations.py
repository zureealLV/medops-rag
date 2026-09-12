"""SQLite persistence for durable conversation history."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.db import transaction
from app.models.answers import AnswerResponse
from app.models.conversations import ConversationDetail, ConversationMessage, ConversationSummary


def _message(row: object) -> ConversationMessage:
    data = dict(row)  # type: ignore[arg-type]
    raw = data.pop("answer_json")
    data["answer"] = AnswerResponse.model_validate_json(raw) if raw else None
    return ConversationMessage(**data)


def create(
    path: Path, tenant_id: str, actor: str, knowledge_base_id: int, title: str
) -> ConversationSummary | None:
    conversation_id = uuid4().hex
    with transaction(path) as connection:
        kb = connection.execute(
            "SELECT 1 FROM knowledge_bases WHERE id=? AND tenant_id=?",
            (knowledge_base_id, tenant_id),
        ).fetchone()
        if kb is None:
            return None
        connection.execute(
            "INSERT INTO conversations(id,tenant_id,actor,knowledge_base_id,title) VALUES(?,?,?,?,?)",
            (conversation_id, tenant_id, actor, knowledge_base_id, title.strip()),
        )
    return get_summary(path, tenant_id, actor, conversation_id)


def get_summary(path: Path, tenant_id: str, actor: str, conversation_id: str) -> ConversationSummary | None:
    with transaction(path) as connection:
        row = connection.execute(
            """SELECT c.id,c.knowledge_base_id,c.title,c.created_at,c.updated_at,
                      COUNT(m.id) AS message_count
               FROM conversations c LEFT JOIN conversation_messages m ON m.conversation_id=c.id
               WHERE c.id=? AND c.tenant_id=? AND c.actor=? GROUP BY c.id""",
            (conversation_id, tenant_id, actor),
        ).fetchone()
    return ConversationSummary(**dict(row)) if row else None


def list_for_identity(path: Path, tenant_id: str, actor: str, limit: int = 100) -> list[ConversationSummary]:
    with transaction(path) as connection:
        rows = connection.execute(
            """SELECT c.id,c.knowledge_base_id,c.title,c.created_at,c.updated_at,
                      COUNT(m.id) AS message_count
               FROM conversations c LEFT JOIN conversation_messages m ON m.conversation_id=c.id
               WHERE c.tenant_id=? AND c.actor=? GROUP BY c.id
               ORDER BY c.updated_at DESC,c.rowid DESC LIMIT ?""",
            (tenant_id, actor, limit),
        ).fetchall()
    return [ConversationSummary(**dict(row)) for row in rows]


def get(path: Path, tenant_id: str, actor: str, conversation_id: str) -> ConversationDetail | None:
    summary = get_summary(path, tenant_id, actor, conversation_id)
    if summary is None:
        return None
    with transaction(path) as connection:
        rows = connection.execute(
            """SELECT id,role,content,contextualized_question,answer_json,created_at
               FROM conversation_messages WHERE conversation_id=? ORDER BY id""",
            (conversation_id,),
        ).fetchall()
    return ConversationDetail(**summary.model_dump(), messages=[_message(row) for row in rows])


def append(
    path: Path,
    tenant_id: str,
    actor: str,
    conversation_id: str,
    role: str,
    content: str,
    *,
    contextualized_question: str | None = None,
    answer: AnswerResponse | None = None,
) -> ConversationMessage | None:
    with transaction(path) as connection:
        owned = connection.execute(
            "SELECT title FROM conversations WHERE id=? AND tenant_id=? AND actor=?",
            (conversation_id, tenant_id, actor),
        ).fetchone()
        if owned is None:
            return None
        cursor = connection.execute(
            """INSERT INTO conversation_messages
               (conversation_id,tenant_id,actor,role,content,contextualized_question,answer_json)
               VALUES(?,?,?,?,?,?,?)""",
            (
                conversation_id,
                tenant_id,
                actor,
                role,
                content,
                contextualized_question,
                answer.model_dump_json() if answer else None,
            ),
        )
        if role == "user" and owned["title"] == "新对话":
            connection.execute(
                "UPDATE conversations SET title=? WHERE id=?",
                (content.strip().replace("\n", " ")[:36], conversation_id),
            )
        connection.execute(
            "UPDATE conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (conversation_id,),
        )
        row = connection.execute(
            """SELECT id,role,content,contextualized_question,answer_json,created_at
               FROM conversation_messages WHERE id=?""",
            (cursor.lastrowid,),
        ).fetchone()
    return _message(row)


def delete(path: Path, tenant_id: str, actor: str, conversation_id: str) -> bool:
    with transaction(path) as connection:
        cursor = connection.execute(
            "DELETE FROM conversations WHERE id=? AND tenant_id=? AND actor=?",
            (conversation_id, tenant_id, actor),
        )
    return cursor.rowcount == 1
