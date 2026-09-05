"""Request IDs, latency measurements, and durable request metrics."""

from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request

from app.db import transaction


def install_observability(app: FastAPI) -> None:
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
            try:
                with transaction(request.app.state.settings.database_path) as connection:
                    abstained = (
                        response.headers.get("X-MedOps-Abstained") == "true"
                        if "response" in locals()
                        else False
                    )
                    retrieval_ms = (
                        float(response.headers.get("X-MedOps-Retrieval-Ms", 0))
                        if "response" in locals()
                        else 0
                    )
                    model_ms = (
                        float(response.headers.get("X-MedOps-Model-Ms", 0)) if "response" in locals() else 0
                    )
                    token_usage = (
                        int(response.headers.get("X-MedOps-Token-Usage", 0)) if "response" in locals() else 0
                    )
                    connection.execute(
                        """INSERT INTO request_metrics
                           (request_id, path, status_code, latency_ms, error_type, abstained,
                            retrieval_ms, model_ms, token_usage)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            request_id,
                            request.url.path,
                            status_code,
                            latency_ms,
                            error_type,
                            int(abstained),
                            retrieval_ms,
                            model_ms,
                            token_usage,
                        ),
                    )
            except Exception:
                # Metrics must never turn a valid application response into a failure.
                pass
        response.headers["X-Request-ID"] = request_id
        response.headers["Server-Timing"] = f"app;dur={latency_ms:.2f}"
        return response
