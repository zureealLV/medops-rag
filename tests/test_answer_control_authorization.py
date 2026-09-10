"""Technical RAG controls are administrator-only, not end-user preferences."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import initialize
from app.main import create_app
from app.repositories.api_credentials import create_credential


def _token(database: Path, role: str) -> str:
    _, token = create_credential(
        database,
        tenant_id="hospital-a",
        name=f"{role}-a",
        role=role,  # type: ignore[arg-type]
    )
    return token


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_non_admin_answer_controls_are_replaced_by_managed_defaults(tmp_path: Path):
    database = tmp_path / "answer-controls.db"
    initialize(database)
    admin_token = _token(database, "admin")
    viewer_token = _token(database, "viewer")
    settings = Settings(database_path=database, auth_mode="api_key")

    with TestClient(create_app(settings)) as client:
        kb = client.post(
            "/knowledge-bases",
            headers=_headers(admin_token),
            json={"name": "Operations"},
        ).json()
        client.post(
            f"/knowledge-bases/{kb['id']}/documents",
            headers=_headers(admin_token),
            json={
                "title": "LIS Runbook",
                "source": "lis.md",
                "content": "LIS 接口超时时，先检查接口网关健康状态和消息队列积压。",
            },
        )

        response = client.post(
            "/answer",
            headers=_headers(viewer_token),
            json={
                "question": "LIS 接口超时先检查什么？",
                "top_k": 1,
                "retrieval_profile": "visual",
                "text_strategy": "keyword",
                "visual_strategy": "fusion",
                "orchestration": "classic",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["orchestration"] == "langgraph"
    assert body["retrieval_profile"] == "text"
    assert body["agent_steps"][0]["detail"].startswith("profile=text; strategy=auto;")
    assert body["retrieval_strategy"] == "bm25"
    assert body["retrieval_routing"]["reason_code"]

    # Raw search is managed by the same server-side boundary.
    search = client.post(
        "/search",
        headers=_headers(viewer_token),
        json={"query": "LIS 接口超时先检查什么？", "strategy": "keyword", "top_k": 1},
    )
    assert search.status_code == 200
    assert search.json()["strategy"] == "bm25"
    assert search.json()["routing"] is not None


def test_admin_can_use_explicit_answer_controls(tmp_path: Path):
    database = tmp_path / "admin-answer-controls.db"
    initialize(database)
    admin_token = _token(database, "admin")
    settings = Settings(database_path=database, auth_mode="api_key")

    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/answer",
            headers=_headers(admin_token),
            json={
                "question": "LIS 接口超时先检查什么？",
                "text_strategy": "keyword",
                "orchestration": "classic",
            },
        )

    assert response.status_code == 200
    assert response.json()["orchestration"] == "classic"
