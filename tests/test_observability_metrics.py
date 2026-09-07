"""Operational snapshot coverage for requests, queues, workers, model stages and fallback."""

from fastapi.testclient import TestClient

from app.config import Settings
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


def test_metrics_do_not_cross_tenant_boundary(
    client: TestClient,
    tenant_headers: dict[str, str],
):
    client.get("/knowledge-bases", headers=tenant_headers)
    other = client.get("/system/metrics", headers={"X-Tenant-ID": "hospital-b"})
    assert other.status_code == 200
    assert other.json()["requests"]["count"] == 0
