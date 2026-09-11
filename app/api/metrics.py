"""Tenant-scoped operational metrics snapshot."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from functools import partial

from anyio import to_thread
from fastapi import APIRouter

from app.api.deps import ModelProviderDep, SettingsDep, TenantContext
from app.db import transaction

router = APIRouter(prefix="/system", tags=["observability"])


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


def _tenant_metrics_snapshot(context: TenantContext, settings: SettingsDep) -> dict[str, object]:
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
        rag_events = connection.execute(
            """SELECT action,result,details
               FROM audit_logs
               WHERE tenant_id=? AND action IN ('answer','search')
                 AND created_at >= datetime('now','-24 hours')
               ORDER BY id DESC LIMIT 5000""",
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

    route_strategies: dict[str, int] = defaultdict(int)
    route_reasons: dict[str, int] = defaultdict(int)
    orchestrations: dict[str, int] = defaultdict(int)
    overload_reasons: dict[str, int] = defaultdict(int)
    circuit_states: dict[str, int] = defaultdict(int)
    deadline_phases: dict[str, int] = defaultdict(int)
    malformed_audit_details = 0
    for row in rag_events:
        try:
            details = json.loads(str(row["details"]))
        except (json.JSONDecodeError, TypeError):
            malformed_audit_details += 1
            continue
        strategy = details.get("retrieval_strategy") or details.get("strategy")
        reason = details.get("routing_reason")
        orchestration = details.get("orchestration")
        if strategy:
            route_strategies[str(strategy)] += 1
        if reason:
            route_reasons[str(reason)] += 1
        if orchestration:
            orchestrations[str(orchestration)] += 1
        if details.get("reason") == "model_provider_overloaded":
            overload_reasons[str(details.get("overload_reason") or "unknown")] += 1
        if details.get("reason") == "model_provider_circuit_open":
            circuit_states[str(details.get("circuit_state") or "unknown")] += 1
        if details.get("reason") == "model_provider_deadline_exceeded":
            deadline_phases[str(details.get("deadline_phase") or "unknown")] += 1

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
        "rag_routing": {
            "event_count": len(rag_events),
            "strategies": dict(sorted(route_strategies.items())),
            "reasons": dict(sorted(route_reasons.items())),
            "orchestrations": dict(sorted(orchestrations.items())),
            "overload_rejections": sum(overload_reasons.values()),
            "overload_reasons": dict(sorted(overload_reasons.items())),
            "circuit_rejections": sum(circuit_states.values()),
            "circuit_states": dict(sorted(circuit_states.items())),
            "deadline_rejections": sum(deadline_phases.values()),
            "deadline_phases": dict(sorted(deadline_phases.items())),
            "malformed_audit_details": malformed_audit_details,
        },
    }


@router.get("/metrics")
async def metrics_snapshot(
    context: TenantContext,
    settings: SettingsDep,
    model_provider: ModelProviderDep,
) -> dict[str, object]:
    """Read SQLite off-loop and append this process's Provider runtime state."""
    snapshot = await to_thread.run_sync(partial(_tenant_metrics_snapshot, context, settings))
    snapshot["provider_runtime"] = {
        "scope": "process_local",
        "capacity": await model_provider.async_capacity_snapshot(),
        "circuit": model_provider.circuit_snapshot(),
        "policy": {
            "request_deadline_seconds": settings.model_request_deadline_seconds,
            "max_retries_per_request": settings.model_max_retries,
            "retry_after_max_seconds": settings.model_retry_after_max_seconds,
        },
        "retry_budget": model_provider.retry_budget_snapshot(),
    }
    return snapshot
