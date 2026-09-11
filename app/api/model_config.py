"""Admin-only model Provider inspection, testing, and session activation."""

from __future__ import annotations

import ipaddress
import time
from dataclasses import replace
from functools import partial
from urllib.parse import urlsplit

import httpx
from anyio import to_thread
from fastapi import APIRouter, Request

from app.api.deps import RequestIdDep, SettingsDep, TenantContext
from app.config import Settings
from app.exceptions import AppError
from app.models.model_config import ModelConfigInput, ModelConfigTestResult, ModelConfigView
from app.security.audit import write_audit

router = APIRouter(prefix="/system/model-config", tags=["system"])


def _provider_from_url(base_url: str) -> str:
    host = (urlsplit(base_url).hostname or "").lower()
    if "deepseek" in host:
        return "deepseek"
    if "openai" in host:
        return "openai"
    if "dashscope" in host or "aliyuncs" in host:
        return "qwen"
    if "bigmodel" in host:
        return "zhipu"
    if host in {"localhost", "127.0.0.1", "::1"}:
        return "ollama"
    return "custom"


def _view(request: Request, settings: Settings) -> ModelConfigView:
    source = getattr(request.app.state, "model_config_source", "environment")
    provider = getattr(
        request.app.state,
        "model_config_provider",
        _provider_from_url(settings.model_base_url),
    )
    key_source = getattr(request.app.state, "model_api_key_source", None)
    if key_source is None:
        key_source = "environment" if settings.model_api_key else "none"
    return ModelConfigView(
        provider=provider,
        model_name=settings.model_name,
        base_url=settings.model_base_url,
        api_key_configured=bool(settings.model_api_key),
        api_key_source=key_source,
        vision_enabled=settings.model_vision_enabled,
        activation_source=source,
    )


def _test_endpoint_allowed(settings: Settings, base_url: str) -> None:
    parsed = urlsplit(base_url)
    host = parsed.hostname or ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if parsed.scheme == "http":
        local = host.lower() == "localhost" or bool(address and address.is_loopback)
        if settings.app_env not in {"development", "test"} or not local:
            raise AppError(
                422,
                "unsafe_model_endpoint",
                "Plain HTTP Provider tests are allowed only for loopback in development/test",
            )
    if address and (address.is_private or address.is_link_local or address.is_reserved):
        if not (address.is_loopback and settings.app_env in {"development", "test"}):
            raise AppError(422, "unsafe_model_endpoint", "Private Provider IP is not allowed")


def _effective_key(settings: Settings, data: ModelConfigInput) -> str:
    if data.clear_api_key:
        return ""
    return data.api_key if data.api_key is not None else settings.model_api_key


@router.get("")
def get_model_config(
    request: Request,
    context: TenantContext,
    settings: SettingsDep,
) -> ModelConfigView:
    del context
    return _view(request, settings)


@router.put("")
async def apply_model_config(
    data: ModelConfigInput,
    request: Request,
    context: TenantContext,
    settings: SettingsDep,
    request_id: RequestIdDep,
) -> ModelConfigView:
    updated = replace(
        settings,
        model_api_key=_effective_key(settings, data),
        model_base_url=data.base_url,
        model_name=data.model_name,
        model_vision_enabled=data.vision_enabled,
    )
    request.app.state.settings = updated
    request.app.state.settings_ref["value"] = updated
    request.app.state.model_config_source = "runtime"
    request.app.state.model_config_provider = data.provider
    if data.clear_api_key:
        request.app.state.model_api_key_source = "none"
    elif data.api_key is not None:
        request.app.state.model_api_key_source = "runtime"
    await to_thread.run_sync(
        partial(
            write_audit,
            settings.database_path,
            request_id=request_id,
            actor=context.actor,
            tenant_id=context.tenant_id,
            action="model_config_apply",
            resource=data.provider,
            result="ok",
            details={
                "model_name": data.model_name,
                "base_url": data.base_url,
                "vision_enabled": data.vision_enabled,
                "api_key_changed": data.api_key is not None or data.clear_api_key,
                "session_only": True,
            },
        )
    )
    return _view(request, updated)


@router.post("/test")
async def test_model_config(
    data: ModelConfigInput,
    request: Request,
    context: TenantContext,
    settings: SettingsDep,
    request_id: RequestIdDep,
) -> ModelConfigTestResult:
    _test_endpoint_allowed(settings, data.base_url)
    endpoint = f"{data.base_url}/chat/completions"
    headers = {"Content-Type": "application/json"}
    key = _effective_key(settings, data)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload = {
        "model": data.model_name,
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "temperature": 0,
        "max_tokens": 8,
        "stream": False,
    }
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=min(settings.model_timeout_seconds, 10.0),
            transport=getattr(request.app.state, "model_test_transport", None),
        ) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
        preview = str(body.get("choices", [{}])[0].get("message", {}).get("content", "OK"))
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        await to_thread.run_sync(
            partial(
                write_audit,
                settings.database_path,
                request_id=request_id,
                actor=context.actor,
                tenant_id=context.tenant_id,
                action="model_config_test",
                resource=data.provider,
                result="failed",
                details={"model_name": data.model_name, "http_status": status},
            )
        )
        message = f"Provider returned HTTP {status}" if status else "Provider connection failed"
        raise AppError(502, "model_provider_test_failed", message) from exc
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    await to_thread.run_sync(
        partial(
            write_audit,
            settings.database_path,
            request_id=request_id,
            actor=context.actor,
            tenant_id=context.tenant_id,
            action="model_config_test",
            resource=data.provider,
            result="ok",
            details={"model_name": data.model_name, "latency_ms": latency_ms},
        )
    )
    return ModelConfigTestResult(
        provider=data.provider,
        model_name=data.model_name,
        endpoint=endpoint,
        latency_ms=latency_ms,
        response_preview=preview[:120],
    )
