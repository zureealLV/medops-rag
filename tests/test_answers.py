"""Citation, grounding, and refusal tests."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models.answers import AnswerRequest
from app.services.answers import answer
from scripts.seed_sample_data import seed


def test_grounded_answer_has_citations(client: TestClient, tenant_headers: dict[str, str], document: dict):
    response = client.post("/answer", headers=tenant_headers, json={"question": "LIS 接口超时先检查什么？"})
    assert response.status_code == 200
    body = response.json()
    assert body["abstained"] is False
    assert body["citations"][0]["document_id"] == document["id"]
    assert body["provider"] == "offline-extractive"
    assert "[来源" not in body["answer"]
    assert "[1:1]" not in body["answer"]
    assert body["citations"][0]["source"] == document["source"]


def test_unanswerable_question_abstains(client: TestClient, tenant_headers: dict[str, str], document: dict):
    response = client.post("/answer", headers=tenant_headers, json={"question": "月球基地氧气产量是多少？"})
    assert response.status_code == 200
    assert response.json()["abstained"] is True
    assert response.headers["X-MedOps-Abstained"] == "true"


def test_enterprise_profile_answers_grounded_non_medical_question(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "enterprise.db", policy_profile="enterprise")
    with TestClient(create_app(settings)) as client:
        headers = {"X-Tenant-ID": "company-a", "X-Actor-ID": "tester"}
        kb_response = client.post(
            "/knowledge-bases",
            headers=headers,
            json={"name": "人事制度", "description": "企业内部制度"},
        )
        knowledge_base_id = kb_response.json()["id"]
        document_response = client.post(
            f"/knowledge-bases/{knowledge_base_id}/documents",
            headers=headers,
            json={
                "title": "员工休假制度",
                "source": "leave-policy.md",
                "content": "员工未休年假最多可以结转五天至下一自然年度。",
            },
        )
        assert document_response.status_code == 201

        response = client.post(
            "/answer",
            headers=headers,
            json={"question": "员工年假最多可以结转几天？", "knowledge_base_id": knowledge_base_id},
        )

    assert response.status_code == 200
    assert response.json()["abstained"] is False
    assert response.json()["citations"][0]["source"] == "leave-policy.md"


def test_medical_advice_is_denied(client: TestClient, tenant_headers: dict[str, str], document: dict):
    response = client.post("/answer", headers=tenant_headers, json={"question": "头痛应该吃什么药和剂量？"})
    assert response.status_code == 200
    assert response.json()["reason"] == "medical_advice_denied"


def test_full_demo_corpus_abstains_on_out_of_scope_questions(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "abstention.db")
    knowledge_base_id, _ = seed(settings)

    for question in (
        "月球基地的氧气产量是多少？",
        "医院食堂今天供应什么菜？",
        "量子计算机有多少个量子比特？",
        "明天合肥会不会下雨？",
    ):
        result = answer(
            settings.database_path,
            settings,
            "hospital-a",
            AnswerRequest(question=question, knowledge_base_id=knowledge_base_id),
        )
        assert result is not None
        assert result.abstained is True, question
        assert result.reason == "insufficient_evidence"
