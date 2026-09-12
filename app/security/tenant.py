"""Tenant context used before any document is read or retrieved."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, Request

from app.config import Settings
from app.exceptions import AppError
from app.repositories.api_credentials import authenticate

TENANT_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$")


@dataclass(frozen=True, slots=True)
class RequestContext:
    tenant_id: str
    actor: str
    role: str
    credential_id: str | None
    auth_mode: str


VIEWER_POST_PATHS = frozenset({"/answer", "/search", "/visual-search", "/conversations"})


def _unauthorized(message: str = "A valid Bearer API key is required") -> AppError:
    return AppError(
        401,
        "authentication_required",
        message,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _authorize(context: RequestContext, method: str, path: str) -> None:
    if context.auth_mode != "api_key" or context.role == "admin":
        return
    if (
        path == "/users"
        or path.startswith("/users/")
        or path.startswith("/audit-logs")
        or path.startswith("/system/metrics")
        or path.startswith("/system/model-config")
        or path == "/tools/call"
    ):
        raise AppError(403, "permission_denied", "This endpoint requires the admin role")
    if context.role == "editor":
        return
    if context.role == "viewer" and (
        method == "GET"
        or path in VIEWER_POST_PATHS
        or (path.startswith("/conversations/") and path.endswith("/messages"))
        or (method == "DELETE" and path.startswith("/conversations/"))
    ):
        return
    raise AppError(403, "permission_denied", "This endpoint requires the editor role")


def resolve_request_context(
    settings: Settings,
    *,
    tenant_id: str | None,
    actor: str = "demo-user",
    authorization: str | None = None,
    method: str = "GET",
    path: str = "/",
) -> RequestContext:
    """Resolve one authenticated tenant identity outside FastAPI dependency injection.

    HTTP endpoints and mounted protocol adapters (such as MCP) must share the
    same credential lookup and role policy. Keeping this logic here prevents an
    adapter from accidentally turning client-supplied tenant metadata into a
    production identity.
    """
    if settings.auth_mode == "api_key":
        if authorization is None or not authorization.startswith("Bearer "):
            raise _unauthorized()
        token = authorization.removeprefix("Bearer ").strip()
        identity = authenticate(settings.database_path, token)
        if identity is None:
            raise _unauthorized("The Bearer API key is invalid or revoked")
        context = RequestContext(
            tenant_id=identity.tenant_id,
            actor=identity.actor,
            role=identity.role,
            credential_id=identity.credential_id,
            auth_mode="api_key",
        )
    elif settings.auth_mode == "trusted_headers":
        if tenant_id is None or not TENANT_PATTERN.fullmatch(tenant_id):
            raise AppError(400, "invalid_tenant", "X-Tenant-ID has an invalid format")
        context = RequestContext(
            tenant_id=tenant_id,
            actor=actor[:80],
            role="admin",
            credential_id=None,
            auth_mode="trusted_headers",
        )
    else:
        raise AppError(500, "invalid_auth_configuration", "AUTH_MODE is not supported")
    _authorize(context, method, path)
    return context


def tenant_context(
    request: Request,
    tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    actor: Annotated[str, Header(alias="X-Actor-ID")] = "demo-user",
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> RequestContext:
    settings = request.app.state.settings
    context = resolve_request_context(
        settings,
        tenant_id=tenant_id,
        actor=actor,
        authorization=authorization,
        method=request.method,
        path=request.url.path,
    )
    request.state.tenant_id = context.tenant_id
    return context
