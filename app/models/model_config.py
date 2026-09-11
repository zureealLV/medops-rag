"""Public models for the admin-only runtime Provider configuration."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ProviderName = Literal["deepseek", "openai", "qwen", "zhipu", "ollama", "custom"]


def _validated_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("base_url must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("base_url must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url must not contain a query string or fragment")
    if parsed.path.rstrip("/").endswith("/chat/completions"):
        raise ValueError("base_url must not include /chat/completions")
    return normalized


class ModelConfigView(BaseModel):
    provider: ProviderName
    model_name: str
    base_url: str
    api_key_configured: bool
    api_key_source: Literal["none", "environment", "runtime"]
    vision_enabled: bool
    activation_source: Literal["environment", "runtime"]
    session_only: bool = True


class ModelConfigInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    provider: ProviderName = "deepseek"
    model_name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=8, max_length=2048)
    api_key: str | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False
    vision_enabled: bool = False

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return _validated_base_url(value)

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized

    @model_validator(mode="after")
    def reject_conflicting_key_actions(self) -> ModelConfigInput:
        if self.clear_api_key and self.api_key is not None:
            raise ValueError("api_key and clear_api_key cannot be used together")
        return self


class ModelConfigTestResult(BaseModel):
    status: Literal["ok"] = "ok"
    provider: ProviderName
    model_name: str
    endpoint: str
    latency_ms: float
    response_preview: str
