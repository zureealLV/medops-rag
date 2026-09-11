"""Resumable Map-Reduce summary job tests."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents import summaries as summary_agent
from app.agents.summaries import SummaryCallError
from app.config import Settings
from app.main import create_app
from app.repositories import summary_jobs as repository
from app.services import summary_jobs as service


def _client(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "summaries.db")
    return settings, TestClient(create_app(settings))


def _documents(client: TestClient, headers: dict[str, str]) -> tuple[int, list[int]]:
    kb = client.post("/knowledge-bases", headers=headers, json={"name": "Summaries"}).json()
    ids = []
    for title, content in (
        ("PACS", "PACS outage procedure. Verify DNS first. Then test TLS connectivity."),
        ("LIS", "LIS recovery procedure. Inspect the message queue. Replay only failed messages."),
    ):
        response = client.post(
            f"/knowledge-bases/{kb['id']}/documents",
            headers=headers,
            json={"title": title, "content": content, "source": f"{title.lower()}.md"},
        )
        ids.append(response.json()["id"])
    return kb["id"], ids


def test_summary_job_map_reduce_citations_and_idempotency(tmp_path: Path):
    settings, client = _client(tmp_path)
    headers = {
        "X-Tenant-ID": "hospital-a",
        "X-Actor-ID": "tester",
        "Idempotency-Key": "summary-key-001",
    }
    with client:
        kb_id, document_ids = _documents(client, headers)
        request = {"question": "Summarize recovery checks", "document_ids": document_ids}
        queued = client.post(
            f"/knowledge-bases/{kb_id}/summary-jobs", headers=headers, json=request
        )
        assert queued.status_code == 202
        process_id = service.process_next(settings.database_path, settings, "summary-worker")
        assert process_id is not None
        assert process_id == queued.json()["id"]
        result = client.get(f"/summary-jobs/{process_id}", headers=headers).json()
        assert result["state"] == "succeeded"
        assert result["progress"] == 100
        assert len(result["map_results"]) == 2
        assert all(item["status"] == "succeeded" for item in result["map_results"])
        assert all(item["citation"]["document_id"] in document_ids for item in result["map_results"])
        assert all(f"[document:{value}]" in result["summary"] for value in document_ids)

        duplicate = client.post(
            f"/knowledge-bases/{kb_id}/summary-jobs", headers=headers, json=request
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["id"] == process_id
        conflict = client.post(
            f"/knowledge-bases/{kb_id}/summary-jobs",
            headers=headers,
            json={"question": "Different objective", "document_ids": document_ids},
        )
        assert conflict.status_code == 409


def test_partial_map_failure_remains_visible(tmp_path: Path, monkeypatch):
    settings, client = _client(tmp_path)
    headers = {
        "X-Tenant-ID": "hospital-a",
        "X-Actor-ID": "tester",
        "Idempotency-Key": "summary-key-partial",
    }
    with client:
        kb_id, document_ids = _documents(client, headers)
        original = service.map_document

        def one_failure(question, document, resolved_settings):
            if document.id == document_ids[1]:
                raise SummaryCallError("summary_model_failed", "simulated timeout")
            return original(question, document, resolved_settings)

        monkeypatch.setattr(service, "map_document", one_failure)
        queued = client.post(
            f"/knowledge-bases/{kb_id}/summary-jobs",
            headers=headers,
            json={"question": "Summarize recovery checks", "document_ids": document_ids},
        ).json()
        service.process_next(settings.database_path, settings, "partial-worker")
        result = client.get(f"/summary-jobs/{queued['id']}", headers=headers).json()
        assert result["state"] == "partial"
        assert result["error_code"] == "map_partial_failure"
        assert [item["status"] for item in result["map_results"]] == ["succeeded", "failed"]
        assert f"[document:{document_ids[0]}]" in result["summary"]
        assert f"[document:{document_ids[1]}]" not in result["summary"]


def test_expired_lease_resumes_without_repeating_completed_maps(tmp_path: Path, monkeypatch):
    settings, client = _client(tmp_path)
    headers = {
        "X-Tenant-ID": "hospital-a",
        "X-Actor-ID": "tester",
        "Idempotency-Key": "summary-key-resume",
    }
    with client:
        kb_id, document_ids = _documents(client, headers)
        queued = client.post(
            f"/knowledge-bases/{kb_id}/summary-jobs",
            headers=headers,
            json={"question": "Summarize recovery checks", "document_ids": document_ids},
        ).json()
        first = repository.claim(settings.database_path, "dead-worker", lease_seconds=1, now=100)
        assert first["id"] == queued["id"]
        document = client.get(f"/documents/{document_ids[0]}", headers=headers).json()
        assert repository.save_map(
            settings.database_path,
            queued["id"],
            "dead-worker",
            document_ids[0],
            document["source"],
            summary="already completed",
            provider="test",
            token_usage=2,
        )
        called: list[int] = []
        original = service.map_document

        def count_maps(question, item, resolved_settings):
            called.append(item.id)
            return original(question, item, resolved_settings)

        monkeypatch.setattr(service, "map_document", count_maps)
        service.process_next(settings.database_path, settings, "recovery-worker", now=102)
        result = client.get(f"/summary-jobs/{queued['id']}", headers=headers).json()
        assert result["state"] == "succeeded"
        assert result["attempt"] == 2
        assert called == [document_ids[1]]
        assert len(result["map_results"]) == 2


def test_tenant_scope_validation_and_cancel(tmp_path: Path):
    settings, client = _client(tmp_path)
    a = {
        "X-Tenant-ID": "hospital-a",
        "X-Actor-ID": "a",
        "Idempotency-Key": "summary-key-cancel",
    }
    b = {"X-Tenant-ID": "hospital-b", "X-Actor-ID": "b"}
    with client:
        kb_id, document_ids = _documents(client, a)
        other_kb = client.post("/knowledge-bases", headers=a, json={"name": "Other"}).json()
        other_document = client.post(
            f"/knowledge-bases/{other_kb['id']}/documents",
            headers=a,
            json={"title": "Other", "content": "Other knowledge base content.", "source": "other.md"},
        ).json()
        cross_scope_headers = {**a, "Idempotency-Key": "summary-key-cross-scope"}
        cross_scope = client.post(
            f"/knowledge-bases/{kb_id}/summary-jobs",
            headers=cross_scope_headers,
            json={"question": "Summarize", "document_ids": [other_document["id"]]},
        )
        assert cross_scope.status_code == 404
        assert cross_scope.json()["code"] == "document_not_found"
        queued = client.post(
            f"/knowledge-bases/{kb_id}/summary-jobs",
            headers=a,
            json={"question": "Summarize", "document_ids": document_ids},
        ).json()
        assert client.get(f"/summary-jobs/{queued['id']}", headers=b).status_code == 404
        cancelled = client.post(f"/summary-jobs/{queued['id']}/cancel", headers=a)
        assert cancelled.status_code == 200
        assert cancelled.json()["state"] == "cancelled"
        assert service.process_next(settings.database_path, settings, "worker") is None


def test_online_summary_timeout_is_hard_capped_at_30_seconds(tmp_path: Path, monkeypatch):
    settings = Settings(
        database_path=tmp_path / "unused.db",
        model_api_key="secret",
        model_base_url="https://model.invalid/v1",
        model_name="test-model",
        model_max_retries=0,
        summary_model_timeout_seconds=999,
    )
    seen: list[float] = []

    def timeout(*args, **kwargs):
        seen.append(kwargs["timeout"])
        raise summary_agent.httpx.TimeoutException("timed out")

    monkeypatch.setattr(summary_agent.httpx, "post", timeout)
    with pytest.raises(SummaryCallError) as caught:
        summary_agent._call_model("system", "user", settings)
    assert caught.value.code == "summary_model_failed"
    assert seen == [30.0]


def test_abrupt_worker_exit_is_recovered_by_separate_worker_process(tmp_path: Path):
    settings, client = _client(tmp_path)
    headers = {
        "X-Tenant-ID": "hospital-a",
        "X-Actor-ID": "tester",
        "Idempotency-Key": "summary-key-killed-worker",
    }
    root = Path(__file__).parents[1]
    with client:
        kb_id, document_ids = _documents(client, headers)
        queued = client.post(
            f"/knowledge-bases/{kb_id}/summary-jobs",
            headers=headers,
            json={"question": "Recover after crash", "document_ids": document_ids},
        ).json()
        env = os.environ.copy()
        env["SUMMARY_TEST_DB"] = str(settings.database_path)
        killed = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import os; from pathlib import Path; "
                    "from app.repositories.summary_jobs import claim; "
                    "claim(Path(os.environ['SUMMARY_TEST_DB']), 'killed-worker', 0.1); "
                    "os._exit(23)"
                ),
            ],
            cwd=root,
            env=env,
            timeout=30,
            check=False,
        )
        assert killed.returncode == 23
        time.sleep(0.2)
        env["DATABASE_URL"] = f"sqlite:///{settings.database_path}"
        recovered = subprocess.run(
            [sys.executable, "scripts/summary_worker.py", "--once"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert recovered.returncode == 0, recovered.stderr
        result = client.get(f"/summary-jobs/{queued['id']}", headers=headers).json()
        assert result["state"] == "succeeded"
        assert result["attempt"] == 2


def test_two_worker_processes_do_not_duplicate_map_work(tmp_path: Path):
    settings, client = _client(tmp_path)
    headers = {
        "X-Tenant-ID": "hospital-a",
        "X-Actor-ID": "tester",
        "Idempotency-Key": "summary-key-contention",
    }
    root = Path(__file__).parents[1]
    with client:
        kb_id, document_ids = _documents(client, headers)
        queued = client.post(
            f"/knowledge-bases/{kb_id}/summary-jobs",
            headers=headers,
            json={"question": "Concurrent workers", "document_ids": document_ids},
        ).json()
        env = os.environ.copy()
        env["DATABASE_URL"] = f"sqlite:///{settings.database_path}"
        command = [sys.executable, "scripts/summary_worker.py", "--once"]
        workers = [
            subprocess.Popen(command, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for _ in range(2)
        ]
        outputs = [worker.communicate(timeout=30) for worker in workers]
        assert [worker.returncode for worker in workers] == [0, 0], outputs
        result = client.get(f"/summary-jobs/{queued['id']}", headers=headers).json()
        assert result["state"] == "succeeded"
        assert result["attempt"] == 1
        assert len(result["map_results"]) == 2
