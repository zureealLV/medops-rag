"""Reusable FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends, Request

from app.config import Settings
from app.security.tenant import RequestContext, tenant_context

TenantContext = Annotated[RequestContext, Depends(tenant_context)]


def settings_from_request(request: Request) -> Settings:
    return request.app.state.settings


SettingsDep = Annotated[Settings, Depends(settings_from_request)]


def request_id(request: Request) -> str:
    return request.state.request_id


RequestIdDep = Annotated[str, Depends(request_id)]
