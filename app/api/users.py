"""User HTTP endpoints."""

from typing import Annotated

from fastapi import APIRouter, Path

from app.api.deps import SettingsDep, TenantContext
from app.exceptions import AppError
from app.models.users import User, UserCreate
from app.services import users as service

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", status_code=201)
def create_user(data: UserCreate, context: TenantContext, settings: SettingsDep) -> User:
    return service.create_user(settings.database_path, context.tenant_id, data)


@router.get("/{user_id}")
def get_user(user_id: Annotated[int, Path(ge=1)], context: TenantContext, settings: SettingsDep) -> User:
    user = service.get_user(settings.database_path, context.tenant_id, user_id)
    if user is None:
        raise AppError(404, "user_not_found", "User not found")
    return user
