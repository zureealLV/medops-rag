"""Shared fixtures using a fresh SQLite database per test."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "medops-test.db")
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def tenant_headers() -> dict[str, str]:
    return {"X-Tenant-ID": "hospital-a", "X-Actor-ID": "tester"}


@pytest.fixture
def kb(client: TestClient, tenant_headers: dict[str, str]) -> dict:
    response = client.post(
        "/knowledge-bases",
        headers=tenant_headers,
        json={"name": "Operations", "description": "Synthetic runbooks"},
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def document(client: TestClient, tenant_headers: dict[str, str], kb: dict) -> dict:
    response = client.post(
        f"/knowledge-bases/{kb['id']}/documents",
        headers=tenant_headers,
        json={
            "title": "LIS Timeout Runbook",
            "source": "lis-timeout.md",
            "content": (
                "LIS 接口连续超时时，先检查接口网关健康状态、消息队列积压、"
                "连接池占用和最近配置变更。不要处理患者诊断数据。"
            ),
        },
    )
    assert response.status_code == 201
    return response.json()
