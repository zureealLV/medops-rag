"""Health-check HTTP endpoint."""

from fastapi import APIRouter

from app.api.deps import SettingsDep
from app.db import transaction

router = APIRouter(tags=["health"])


@router.get("/live")
def liveness() -> dict[str, str]:
    """Process-only probe: no database access and no durable telemetry write."""
    return {"status": "ok", "version": "3.1.0"}


@router.get("/ready")
def readiness(settings: SettingsDep) -> dict[str, str]:
    """Dependency probe used before routing traffic to this instance."""
    with transaction(settings.database_path) as connection:
        connection.execute("SELECT 1").fetchone()
    return {"status": "ok", "version": "3.1.0", "database": "ok"}


@router.get("/health")
def health_check(settings: SettingsDep) -> dict[str, str]:
    """Backward-compatible readiness alias for existing clients."""
    return readiness(settings)
