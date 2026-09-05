"""Tenant context used before any document is read or retrieved."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated

from fastapi import Header

from app.exceptions import AppError

TENANT_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$")


@dataclass(frozen=True, slots=True)
class RequestContext:
    tenant_id: str
    actor: str


def tenant_context(
    tenant_id: Annotated[str, Header(alias="X-Tenant-ID")],
    actor: Annotated[str, Header(alias="X-Actor-ID")] = "demo-user",
) -> RequestContext:
    if not TENANT_PATTERN.fullmatch(tenant_id):
        raise AppError(400, "invalid_tenant", "X-Tenant-ID has an invalid format")
    return RequestContext(tenant_id=tenant_id, actor=actor[:80])
