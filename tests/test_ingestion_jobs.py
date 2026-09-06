"""Durable ingestion queue, idempotency and lease recovery tests."""

import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.repositories import ingestion_jobs as repository
from app.services import ingestion_jobs as job_service
from app.services.ingestion_jobs import process_next


def _client(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "jobs.db")
    return settings, TestClient(create_app(settings))


def test_ingestion_job_processes_once_and_reuses_idempotency_key(tmp_path: Path):
    settings, client = _client(tmp_path)
    headers = {"X-Tenant-ID": "hospital-a", "X-Actor-ID": "tester", "Idempotency-Key": "upload-key-001"}
    with client:
        kb = client.post("/knowledge-bases", headers=headers, json={"name": "Async"}).json()
        queued = client.post(
            f"/knowledge-bases/{kb['id']}/ingestion-jobs",
            headers=headers,
            files={"file": ("runbook.md", b"PACS gateway async runbook", "text/markdown")},
        )
        assert queued.status_code == 202
        job_id = queued.json()["id"]
        assert queued.json()["state"] == "queued"
        assert process_next(settings.database_path, settings, "worker-1") == job_id
        done = client.get(f"/ingestion-jobs/{job_id}", headers=headers).json()
        assert done["state"] == "succeeded"
        assert done["document_id"] is not None
        assert done["progress"] == 100
        duplicate = client.post(
            f"/knowledge-bases/{kb['id']}/ingestion-jobs",
            headers=headers,
            files={"file": ("runbook.md", b"PACS gateway async runbook", "text/markdown")},
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["id"] == job_id
        conflict = client.post(
            f"/knowledge-bases/{kb['id']}/ingestion-jobs",
            headers=headers,
            files={"file": ("runbook.md", b"different payload", "text/markdown")},
        )
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "idempotency_conflict"


def test_expired_worker_lease_is_reclaimed_without_duplicate_claim(tmp_path: Path):
    settings, client = _client(tmp_path)
    headers = {"X-Tenant-ID": "hospital-a", "X-Actor-ID": "tester", "Idempotency-Key": "upload-key-002"}
    with client:
        kb = client.post("/knowledge-bases", headers=headers, json={"name": "Recovery"}).json()
        job = client.post(
            f"/knowledge-bases/{kb['id']}/ingestion-jobs",
            headers=headers,
            files={"file": ("recovery.txt", b"recovery content", "text/plain")},
        ).json()
        first = repository.claim(settings.database_path, "dead-worker", lease_seconds=1, now=100)
        assert first["id"] == job["id"]
        assert first["attempt"] == 1
        assert repository.claim(settings.database_path, "early-worker", now=100.5) is None
        second = repository.claim(settings.database_path, "recovery-worker", now=102)
        assert second["id"] == job["id"]
        assert second["attempt"] == 2
        assert second["lease_owner"] == "recovery-worker"
        assert repository.succeed(settings.database_path, job["id"], "dead-worker", 999) is False
        assert (
            repository.fail(
                settings.database_path,
                job["id"],
                "dead-worker",
                "stale_worker",
                "must not overwrite the new lease owner",
                retryable=False,
            )
            is False
        )
        third = repository.claim(settings.database_path, "last-worker", lease_seconds=1, now=200)
        assert third["id"] == job["id"]
        assert third["attempt"] == 3
        assert repository.claim(settings.database_path, "too-late", now=202) is None
        exhausted = repository.get(settings.database_path, "hospital-a", job["id"])
        assert exhausted is not None
        assert exhausted.state == "failed"
        assert exhausted.error_code == "retry_exhausted"


def test_cancel_and_tenant_isolation(tmp_path: Path):
    settings, client = _client(tmp_path)
    a = {"X-Tenant-ID": "hospital-a", "X-Actor-ID": "a", "Idempotency-Key": "upload-key-003"}
    b = {"X-Tenant-ID": "hospital-b", "X-Actor-ID": "b"}
    with client:
        kb = client.post("/knowledge-bases", headers=a, json={"name": "Cancel"}).json()
        job = client.post(
            f"/knowledge-bases/{kb['id']}/ingestion-jobs",
            headers=a,
            files={"file": ("cancel.txt", b"cancel me", "text/plain")},
        ).json()
        assert client.get(f"/ingestion-jobs/{job['id']}", headers=b).status_code == 404
        cancelled = client.post(f"/ingestion-jobs/{job['id']}/cancel", headers=a)
        assert cancelled.status_code == 200
        assert cancelled.json()["state"] == "cancelled"
        assert process_next(settings.database_path, settings, "worker") is None


def test_poison_document_fails_terminally_without_creating_document(tmp_path: Path):
    settings, client = _client(tmp_path)
    headers = {
        "X-Tenant-ID": "hospital-a",
        "X-Actor-ID": "tester",
        "Idempotency-Key": "upload-key-poison",
    }
    with client:
        kb = client.post("/knowledge-bases", headers=headers, json={"name": "Poison"}).json()
        job = client.post(
            f"/knowledge-bases/{kb['id']}/ingestion-jobs",
            headers=headers,
            files={"file": ("malware.exe", b"MZ-not-a-supported-document", "application/octet-stream")},
        ).json()
        assert process_next(settings.database_path, settings, "worker-poison") == job["id"]
        failed = client.get(f"/ingestion-jobs/{job['id']}", headers=headers).json()
        assert failed["state"] == "failed"
        assert failed["attempt"] == 1
        assert failed["error_code"] == "unsupported_document"
        assert failed["document_id"] is None


def test_transient_worker_error_requeues_then_succeeds(tmp_path: Path, monkeypatch):
    settings, client = _client(tmp_path)
    headers = {
        "X-Tenant-ID": "hospital-a",
        "X-Actor-ID": "tester",
        "Idempotency-Key": "upload-key-retry",
    }
    with client:
        kb = client.post("/knowledge-bases", headers=headers, json={"name": "Retry"}).json()
        job = client.post(
            f"/knowledge-bases/{kb['id']}/ingestion-jobs",
            headers=headers,
            files={"file": ("retry.txt", b"retryable content", "text/plain")},
        ).json()
        original_parse = job_service.parse_bytes

        def fail_once(*args, **kwargs):
            raise RuntimeError("temporary parser outage")

        monkeypatch.setattr(job_service, "parse_bytes", fail_once)
        assert process_next(settings.database_path, settings, "worker-retry-1") == job["id"]
        queued = client.get(f"/ingestion-jobs/{job['id']}", headers=headers).json()
        assert queued["state"] == "queued"
        assert queued["attempt"] == 1
        assert queued["error_code"] == "worker_error"

        monkeypatch.setattr(job_service, "parse_bytes", original_parse)
        assert process_next(settings.database_path, settings, "worker-retry-2") == job["id"]
        succeeded = client.get(f"/ingestion-jobs/{job['id']}", headers=headers).json()
        assert succeeded["state"] == "succeeded"
        assert succeeded["attempt"] == 2
        assert succeeded["document_id"] is not None


def test_worker_cli_processes_persisted_job_in_separate_process(tmp_path: Path):
    settings, client = _client(tmp_path)
    headers = {
        "X-Tenant-ID": "hospital-a",
        "X-Actor-ID": "tester",
        "Idempotency-Key": "upload-key-subprocess",
    }
    with client:
        kb = client.post("/knowledge-bases", headers=headers, json={"name": "Subprocess"}).json()
        job = client.post(
            f"/knowledge-bases/{kb['id']}/ingestion-jobs",
            headers=headers,
            files={"file": ("worker.md", b"isolated worker content", "text/markdown")},
        ).json()

        env = os.environ.copy()
        env["DATABASE_URL"] = f"sqlite:///{settings.database_path}"
        result = subprocess.run(
            [sys.executable, "scripts/ingestion_worker.py", "--once"],
            cwd=Path(__file__).parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        succeeded = client.get(f"/ingestion-jobs/{job['id']}", headers=headers).json()
        assert succeeded["state"] == "succeeded"
        assert succeeded["document_id"] is not None
