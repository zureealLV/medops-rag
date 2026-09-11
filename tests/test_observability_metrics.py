"""Operational snapshot coverage for requests, queues, workers, model stages and fallback."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.security.audit import write_audit
from app.services.ingestion_jobs import process_next as process_ingestion
from app.services.summary_jobs import process_next as process_summary


def test_metrics_snapshot_aggregates_tenant_scoped_pipeline_facts(
    client: TestClient,
    tenant_headers: dict[str, str],
    kb: dict,
):
    upload = client.post(
        f"/knowledge-bases/{kb['id']}/ingestion-jobs",
        headers={**tenant_headers, "Idempotency-Key": "metrics-upload-01"},
        files={"file": ("metrics.md", b"Gateway timeout. Check DNS and TLS first.", "text/markdown")},
    )
    assert upload.status_code == 202
    settings: Settings = client.app.state.settings
    assert process_ingestion(settings.database_path, settings, "metrics-ingestion") == upload.json()["id"]
    ingested = client.get(f"/ingestion-jobs/{upload.json()['id']}", headers=tenant_headers).json()
    assert ingested["state"] == "succeeded"

    search = client.post(
        "/search",
        headers=tenant_headers,
        json={"query": "gateway timeout", "knowledge_base_id": kb["id"]},
    )
    assert search.status_code == 200
    assert float(search.headers["x-medops-retrieval-ms"]) >= 0
    answer = client.post(
        "/answer",
        headers=tenant_headers,
        json={"question": "What should I check for gateway timeout?", "knowledge_base_id": kb["id"]},
    )
    assert answer.status_code == 200
    assert answer.headers["x-medops-provider"]

    summary = client.post(
        f"/knowledge-bases/{kb['id']}/summary-jobs",
        headers={**tenant_headers, "Idempotency-Key": "metrics-summary-01"},
        json={"question": "Summarize recovery", "document_ids": [ingested["document_id"]]},
    )
    assert summary.status_code == 202
    assert process_summary(settings.database_path, settings, "metrics-summary") == summary.json()["id"]
    write_audit(
        settings.database_path,
        request_id="metrics-overload-01",
        actor="tester",
        tenant_id="hospital-a",
        action="answer",
        resource="rag",
        result="rejected",
        details={
            "reason": "model_provider_overloaded",
            "overload_reason": "queue_timeout",
        },
    )
    write_audit(
        settings.database_path,
        request_id="metrics-circuit-01",
        actor="tester",
        tenant_id="hospital-a",
        action="answer",
        resource="rag",
        result="rejected",
        details={"reason": "model_provider_circuit_open", "circuit_state": "open"},
    )
    write_audit(
        settings.database_path,
        request_id="metrics-deadline-01",
        actor="tester",
        tenant_id="hospital-a",
        action="answer",
        resource="rag",
        result="rejected",
        details={"reason": "model_provider_deadline_exceeded", "deadline_phase": "backoff"},
    )

    response = client.get("/system/metrics", headers=tenant_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_id"] == "hospital-a"
    assert payload["window_hours"] == 24
    assert payload["queues"]["ingestion"]["states"]["succeeded"] == 1
    assert payload["queues"]["summary"]["states"]["succeeded"] == 1
    assert payload["requests"]["count"] >= 5
    assert payload["requests"]["retrieval_ms_p95"] >= 0
    assert payload["requests"]["providers"]
    assert payload["pipeline_stages"]["ingestion.parse_ocr"]["count"] == 1
    assert payload["pipeline_stages"]["ingestion.persist_index"]["count"] == 1
    assert payload["pipeline_stages"]["summary.map_model"]["count"] == 1
    assert payload["pipeline_stages"]["summary.reduce_model"]["count"] == 1
    assert payload["pipeline_providers"]["offline-extractive"] == 1
    assert payload["pipeline_providers"]["offline-map-reduce"] == 1
    assert payload["rag_routing"]["event_count"] >= 2
    assert payload["rag_routing"]["strategies"]["bm25"] >= 2
    search_reason = search.json()["routing"]["reason_code"]
    answer_reason = answer.json()["retrieval_routing"]["reason_code"]
    assert payload["rag_routing"]["reasons"][search_reason] >= 1
    assert payload["rag_routing"]["reasons"][answer_reason] >= 1
    assert payload["rag_routing"]["orchestrations"]["langgraph"] >= 1
    assert payload["rag_routing"]["overload_rejections"] == 1
    assert payload["rag_routing"]["overload_reasons"] == {"queue_timeout": 1}
    assert payload["rag_routing"]["circuit_rejections"] == 1
    assert payload["rag_routing"]["circuit_states"] == {"open": 1}
    assert payload["rag_routing"]["deadline_rejections"] == 1
    assert payload["rag_routing"]["deadline_phases"] == {"backoff": 1}
    assert payload["rag_routing"]["malformed_audit_details"] == 0
    assert payload["provider_runtime"]["scope"] == "process_local"
    assert payload["provider_runtime"]["capacity"]["max_concurrency"] == 4
    assert payload["provider_runtime"]["capacity"]["max_concurrency_per_tenant"] == 2
    assert payload["provider_runtime"]["capacity"]["max_queue_waiters_per_tenant"] == 4
    assert payload["provider_runtime"]["circuit"]["state"] == "closed"
    assert payload["provider_runtime"]["policy"] == {
        "request_deadline_seconds": 12.0,
        "max_retries_per_request": 1,
        "retry_after_max_seconds": 5.0,
    }
    assert payload["provider_runtime"]["retry_budget"]["retries_consumed"] == 0
    assert payload["provider_runtime"]["retry_budget"]["global"]["capacity"] == 32
    assert payload["provider_runtime"]["retry_budget"]["per_tenant"]["capacity"] == 8


def test_metrics_do_not_cross_tenant_boundary(
    client: TestClient,
    tenant_headers: dict[str, str],
):
    client.get("/knowledge-bases", headers=tenant_headers)
    other = client.get("/system/metrics", headers={"X-Tenant-ID": "hospital-b"})
    assert other.status_code == 200
    assert other.json()["requests"]["count"] == 0
    assert other.json()["rag_routing"]["event_count"] == 0
