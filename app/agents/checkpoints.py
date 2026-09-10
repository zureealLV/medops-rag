"""Tenant- and actor-scoped SQLite checkpoints for read-only agent runs.

Only control-plane metadata is persisted.  Questions, retrieved chunks, model
prompts, and answers are deliberately excluded so a later turn cannot reuse
evidence that was authorized under a different identity or stale policy.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from app.db import transaction

THREAD_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,63}$")
CheckpointStatus = Literal["running", "completed", "failed", "abstained"]


@dataclass(frozen=True, slots=True)
class AgentCheckpoint:
    tenant_id: str
    actor: str
    thread_id: str
    run_id: str
    sequence: int
    phase: str
    route: str | None
    tool_plan: tuple[str, ...]
    tool_calls: int
    status: CheckpointStatus
    resumed_from_run_id: str | None


def new_or_validated_thread_id(value: str | None) -> str:
    if value is None:
        return uuid4().hex
    if not THREAD_ID_PATTERN.fullmatch(value):
        raise ValueError(
            "X-MedOps-Thread-Id must contain 8-64 ASCII letters, digits, '.', '_' or '-'"
        )
    return value


def _from_row(row: object) -> AgentCheckpoint:
    data = dict(row)  # type: ignore[arg-type]
    return AgentCheckpoint(
        tenant_id=data["tenant_id"],
        actor=data["actor"],
        thread_id=data["thread_id"],
        run_id=data["run_id"],
        sequence=int(data["sequence"]),
        phase=data["phase"],
        route=data["route"],
        tool_plan=tuple(json.loads(data["tool_plan_json"])),
        tool_calls=int(data["tool_calls"]),
        status=data["status"],
        resumed_from_run_id=data["resumed_from_run_id"],
    )


def latest_for_identity(
    path: Path, tenant_id: str, actor: str, thread_id: str
) -> AgentCheckpoint | None:
    """Load only from the current security boundary; never fall back by thread id."""
    with transaction(path) as connection:
        row = connection.execute(
            """SELECT tenant_id, actor, thread_id, run_id, sequence, phase, route,
                      tool_plan_json, tool_calls, status, resumed_from_run_id
               FROM agent_checkpoints
               WHERE tenant_id=? AND actor=? AND thread_id=?
               ORDER BY id DESC LIMIT 1""",
            (tenant_id, actor, thread_id),
        ).fetchone()
    return None if row is None else _from_row(row)


class CheckpointSession:
    """Append-only checkpoint writer for one authenticated answer request."""

    def __init__(
        self,
        path: Path,
        *,
        tenant_id: str,
        actor: str,
        thread_id: str,
        run_id: str,
    ) -> None:
        self.path = path
        self.tenant_id = tenant_id
        self.actor = actor
        self.thread_id = thread_id
        self.run_id = run_id
        self.sequence = 0
        previous = latest_for_identity(path, tenant_id, actor, thread_id)
        self.resumed_from_run_id = (
            previous.run_id if previous is not None and previous.status in {"running", "failed"} else None
        )

    def record(
        self,
        *,
        phase: str,
        route: str | None,
        tool_plan: tuple[str, ...],
        tool_calls: int,
        status: CheckpointStatus = "running",
    ) -> AgentCheckpoint:
        self.sequence += 1
        with transaction(self.path) as connection:
            connection.execute(
                """INSERT INTO agent_checkpoints
                   (tenant_id, actor, thread_id, run_id, sequence, phase, route,
                    tool_plan_json, tool_calls, status, resumed_from_run_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.tenant_id,
                    self.actor,
                    self.thread_id,
                    self.run_id,
                    self.sequence,
                    phase,
                    route,
                    json.dumps(tool_plan, separators=(",", ":")),
                    tool_calls,
                    status,
                    self.resumed_from_run_id,
                ),
            )
        return AgentCheckpoint(
            tenant_id=self.tenant_id,
            actor=self.actor,
            thread_id=self.thread_id,
            run_id=self.run_id,
            sequence=self.sequence,
            phase=phase,
            route=route,
            tool_plan=tool_plan,
            tool_calls=tool_calls,
            status=status,
            resumed_from_run_id=self.resumed_from_run_id,
        )
