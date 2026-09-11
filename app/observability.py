"""Request IDs, latency measurements, and durable request metrics."""

from __future__ import annotations

import json
import time
import uuid
from functools import partial
from pathlib import Path
from typing import Any

from anyio import to_thread
from fastapi import FastAPI, Request

from app.db import transaction


def record_pipeline_metric(
    path: Path,
    *,
    tenant_id: str,
    job_id: str,
    pipeline: str,
    stage: str,
    outcome: str,
    duration_ms: float,
    provider: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Persist bounded operational facts; telemetry must never fail business work."""
    try:
        safe_details = json.dumps(details or {}, ensure_ascii=False, sort_keys=True)[:2_000]
        with transaction(path) as connection:
            connection.execute(
                """INSERT INTO pipeline_metrics
                   (tenant_id,job_id,pipeline,stage,outcome,duration_ms,provider,details_json)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    tenant_id,
                    job_id,
                    pipeline,
                    stage,
                    outcome,
                    round(max(0.0, duration_ms), 3),
                    provider,
                    safe_details,
                ),
            )
    except Exception:
        pass


def _record_request_metric(
    path: Path,
    *,
    request_id: str,
    tenant_id: str | None,
    request_path: str,
    status_code: int,
    latency_ms: float,
    error_type: str | None,
    abstained: bool,
    retrieval_ms: float,
    model_ms: float,
    token_usage: int,
    provider: str | None,
    retrieval_profile: str | None,
) -> None:
    """Persist one request measurement from a worker thread."""
    try:
        with transaction(path) as connection:
            connection.execute(
                """INSERT INTO request_metrics
                   (request_id, tenant_id, path, status_code, latency_ms, error_type,
                    abstained, retrieval_ms, model_ms, token_usage, provider,
                    retrieval_profile)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    request_id,
                    tenant_id,
                    request_path,
                    status_code,
                    latency_ms,
                    error_type,
                    int(abstained),
                    retrieval_ms,
                    model_ms,
                    token_usage,
                    provider,
                    retrieval_profile,
                ),
            )
    except Exception:
        # Telemetry must never turn a valid application response into a failure.
        pass


def install_observability(app: FastAPI) -> None:
    database_path = app.state.settings.database_path

    @app.middleware("http")
    async def trace_request(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))[:100]
        request.state.request_id = request_id
        started = time.perf_counter()
        error_type: str | None = None
        try:
            response = await call_next(request)
        except Exception as exc:
            error_type = type(exc).__name__
            raise
        finally:
            latency_ms = (time.perf_counter() - started) * 1000
            status_code = locals().get("response").status_code if "response" in locals() else 500
            if request.url.path != "/live":
                headers = response.headers if "response" in locals() else {}
                await to_thread.run_sync(
                    partial(
                        _record_request_metric,
                        database_path,
                        request_id=request_id,
                        tenant_id=getattr(request.state, "tenant_id", None),
                        request_path=request.url.path,
                        status_code=status_code,
                        latency_ms=latency_ms,
                        error_type=error_type,
                        abstained=headers.get("X-MedOps-Abstained") == "true",
                        retrieval_ms=float(headers.get("X-MedOps-Retrieval-Ms", 0)),
                        model_ms=float(headers.get("X-MedOps-Model-Ms", 0)),
                        token_usage=int(headers.get("X-MedOps-Token-Usage", 0)),
                        provider=headers.get("X-MedOps-Provider"),
                        retrieval_profile=headers.get("X-MedOps-Retrieval-Profile"),
                    )
                )
        response.headers["X-Request-ID"] = request_id
        response.headers["Server-Timing"] = f"app;dur={latency_ms:.2f}"
        return response
