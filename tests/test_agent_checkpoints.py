"""Bounded agent tool planning and scoped SQLite checkpoint coverage."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.checkpoints import CheckpointSession, latest_for_identity
from app.db import initialize


def test_answer_returns_thread_contract_and_persists_only_control_metadata(
    client: TestClient, tenant_headers: dict[str, str], document: dict
):
    response = client.post(
        "/answer",
        headers={**tenant_headers, "X-MedOps-Thread-Id": "thread-demo-001"},
        json={"question": "LIS 接口超时先检查什么？"},
    )

    assert response.status_code == 200
    assert response.headers["X-MedOps-Thread-Id"] == "thread-demo-001"
    assert response.headers["X-MedOps-Run-Id"]
    checkpoint = latest_for_identity(
        client.app.state.settings.database_path,
        "hospital-a",
        "tester",
        "thread-demo-001",
    )
    assert checkpoint is not None
    assert checkpoint.status == "completed"
    assert checkpoint.phase == "finished"
    assert checkpoint.tool_plan == (
        "grounded_text_answer",
        "verify_citation_scope",
    )
    assert checkpoint.tool_calls == 2

    with sqlite3.connect(client.app.state.settings.database_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(agent_checkpoints)")
        }
        assert "question" not in columns
        assert "answer" not in columns
        assert "evidence" not in columns
        assert connection.execute(
            "SELECT MAX(tool_calls) FROM agent_checkpoints"
        ).fetchone()[0] <= 2


def test_checkpoint_resume_marker_is_identity_scoped(tmp_path: Path):
    database = tmp_path / "checkpoints.db"
    initialize(database)
    failed = CheckpointSession(
        database,
        tenant_id="hospital-a",
        actor="alice",
        thread_id="thread-scope-001",
        run_id="run-failed",
    )
    failed.record(
        phase="execute_read_only_tools",
        route="text",
        tool_plan=("grounded_text_answer", "verify_citation_scope"),
        tool_calls=1,
        status="failed",
    )

    resumed = CheckpointSession(
        database,
        tenant_id="hospital-a",
        actor="alice",
        thread_id="thread-scope-001",
        run_id="run-retry",
    )
    assert resumed.resumed_from_run_id == "run-failed"
    assert latest_for_identity(database, "hospital-b", "alice", "thread-scope-001") is None
    assert latest_for_identity(database, "hospital-a", "mallory", "thread-scope-001") is None

    other_identity = CheckpointSession(
        database,
        tenant_id="hospital-b",
        actor="alice",
        thread_id="thread-scope-001",
        run_id="run-other",
    )
    assert other_identity.resumed_from_run_id is None


def test_invalid_thread_id_is_rejected_before_agent_execution(
    client: TestClient, tenant_headers: dict[str, str]
):
    response = client.post(
        "/answer",
        headers={**tenant_headers, "X-MedOps-Thread-Id": "../../tenant-b"},
        json={"question": "LIS 接口超时先检查什么？"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_thread_id"


def test_citation_scope_verifier_fails_closed_without_leaking_results(
    client: TestClient,
    tenant_headers: dict[str, str],
    document: dict,
    monkeypatch,
):
    monkeypatch.setattr("app.api.answers._citations_belong_to_tenant", lambda *_: False)

    response = client.post(
        "/answer",
        headers=tenant_headers,
        json={"question": "LIS 接口超时先检查什么？"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["abstained"] is True
    assert body["reason"] == "citation_scope_violation"
    assert body["citations"] == []
    assert body["visual_citations"] == []
    assert body["retrieved_chunks"] == []
    assert body["retrieved_artifacts"] == []
