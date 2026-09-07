"""Tenant-scoped operational metrics snapshot."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from fastapi import APIRouter

from app.api.deps import SettingsDep, TenantContext
from app.db import transaction

router = APIRouter(prefix="/system", tags=["observability"])


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


@router.get("/metrics")
def metrics_snapshot(context: TenantContext, settings: SettingsDep) -> dict[str, object]:
    with transaction(settings.database_path) as connection:
        queue_rows = {}
        for table in ("ingestion_jobs", "summary_jobs"):
            counts = connection.execute(
                f"""SELECT state, COUNT(*) AS count FROM {table}
                    WHERE tenant_id=? GROUP BY state""",  # noqa: S608 - fixed table allowlist
                (context.tenant_id,),
            ).fetchall()
            oldest = connection.execute(
                f"""SELECT MAX(0, (julianday('now') - julianday(MIN(created_at))) * 86400)
                    AS age_seconds FROM {table}
                    WHERE tenant_id=? AND state='queued'""",  # noqa: S608 - fixed table allowlist
                (context.tenant_id,),
            ).fetchone()
            queue_rows[table.removesuffix("_jobs")] = {
                "states": {row["state"]: row["count"] for row in counts},
                "oldest_queued_age_seconds": round(float(oldest["age_seconds"] or 0), 3),
            }

        requests = connection.execute(
            """SELECT status_code,latency_ms,abstained,retrieval_ms,model_ms,token_usage,
                      provider,retrieval_profile
               FROM request_metrics
               WHERE tenant_id=? AND created_at >= datetime('now','-24 hours')""",
            (context.tenant_id,),
        ).fetchall()
        stages = connection.execute(
            """SELECT pipeline,stage,outcome,duration_ms,provider,details_json
               FROM pipeline_metrics
               WHERE tenant_id=? AND created_at >= datetime('now','-24 hours')
               ORDER BY id DESC LIMIT 1000""",
            (context.tenant_id,),
        ).fetchall()

    request_latencies = [float(row["latency_ms"]) for row in requests]
    retrieval_latencies = [float(row["retrieval_ms"]) for row in requests if row["retrieval_ms"]]
    model_latencies = [float(row["model_ms"]) for row in requests if row["model_ms"]]
    providers: dict[str, int] = defaultdict(int)
    for row in requests:
        if row["provider"]:
            providers[str(row["provider"])] += 1

    grouped: dict[str, list] = defaultdict(list)
    errors: dict[str, int] = defaultdict(int)
    pipeline_providers: dict[str, int] = defaultdict(int)
    for row in stages:
        key = f"{row['pipeline']}.{row['stage']}"
        grouped[key].append(float(row["duration_ms"]))
        if row["outcome"] == "error":
            errors[key] += 1
        if row["provider"]:
            pipeline_providers[str(row["provider"])] += 1

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "window_hours": 24,
        "tenant_id": context.tenant_id,
        "queues": queue_rows,
        "requests": {
            "count": len(requests),
            "error_count": sum(1 for row in requests if int(row["status_code"]) >= 400),
            "abstained_count": sum(int(row["abstained"]) for row in requests),
            "latency_ms": {
                "avg": round(sum(request_latencies) / len(request_latencies), 3)
                if request_latencies
                else 0.0,
                "p95": _percentile(request_latencies, 0.95),
            },
            "retrieval_ms_p95": _percentile(retrieval_latencies, 0.95),
            "model_ms_p95": _percentile(model_latencies, 0.95),
            "token_usage": sum(int(row["token_usage"]) for row in requests),
            "providers": dict(sorted(providers.items())),
            "fallback_count": sum(
                1 for row in requests if "fallback" in str(row["provider"] or "")
            ),
        },
        "pipeline_stages": {
            key: {
                "count": len(values),
                "error_count": errors[key],
                "avg_ms": round(sum(values) / len(values), 3),
                "p95_ms": _percentile(values, 0.95),
            }
            for key, values in sorted(grouped.items())
        },
        "pipeline_providers": dict(sorted(pipeline_providers.items())),
    }
