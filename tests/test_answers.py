"""Citation, grounding, and refusal tests."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
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
