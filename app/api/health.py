"""Health-check HTTP endpoint."""

from fastapi import APIRouter

from app.api.deps import SettingsDep
from app.db import transaction

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check(settings: SettingsDep) -> dict[str, str]:
    with transaction(settings.database_path) as connection:
        connection.execute("SELECT 1").fetchone()
    return {"status": "ok", "version": "1.0.0", "database": "ok"}
