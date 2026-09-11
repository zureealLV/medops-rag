"""Parity and trace coverage for the three RAG orchestration modes."""

from fastapi.testclient import TestClient

from app.services.answers import _strip_inline_citation_markers


def test_structured_citation_markers_are_removed_from_natural_answer():
    raw = "结论 [source:1]，补充 [evidence:2]，中文括号【source:3】。"

    assert _strip_inline_citation_markers(raw) == "结论，补充，中文括号。"


def test_default_answer_uses_langgraph_agent_trace(
    client: TestClient, tenant_headers: dict[str, str], document: dict
):
    response = client.post(
        "/answer",
        headers=tenant_headers,
        json={"question": "LIS 接口超时先检查什么？"},
    )

    assert response.status_code == 200
    body = response.json()
    assert response.headers["X-MedOps-Orchestration"] == "langgraph"
    assert body["orchestration"] == "langgraph"
    assert [step["node"] for step in body["agent_steps"]] == [
        "route_question",
        "select_read_only_tool",
        "execute_grounded_text_answer",
        "verify_citation_scope",
        "verify_grounding",
    ]
    assert body["agent_steps"][1]["detail"] == (
        "tools=grounded_text_answer,verify_citation_scope; max_calls=2"
    )
    assert body["agent_steps"][3]["detail"] == "tenant_scoped=true"
    assert body["citations"][0]["document_id"] == document["id"]


def test_orchestration_modes_keep_answer_policy_and_citations_equivalent(
    client: TestClient, tenant_headers: dict[str, str]
):
    results = {}
    for mode in ("classic", "langchain", "langgraph"):
        response = client.post(
            "/answer",
            headers=tenant_headers,
            json={
                "question": "LIS 接口超时先检查什么？",
                "orchestration": mode,
            },
        )
        assert response.status_code == 200
        body = response.json()
        results[mode] = (
            body["answer"],
            body["abstained"],
            [citation["source"] for citation in body["citations"]],
        )
        assert body["orchestration"] == mode
        assert body["agent_steps"]

    assert results["classic"] == results["langchain"] == results["langgraph"]


def test_langgraph_agent_keeps_medical_advice_refusal(
    client: TestClient, tenant_headers: dict[str, str]
):
    response = client.post(
        "/answer",
        headers=tenant_headers,
        json={
            "question": "我头痛应该吃什么药和剂量？",
            "orchestration": "langgraph",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["abstained"] is True
    assert body["reason"] == "medical_advice_denied"
    assert [step["node"] for step in body["agent_steps"]] == [
        "route_question",
        "apply_safety_policy",
        "verify_grounding",
    ]
    assert body["agent_steps"][-1]["status"] == "abstained"


def test_langgraph_agent_does_not_call_search_tool_for_out_of_domain_question(
    client: TestClient, tenant_headers: dict[str, str]
):
    response = client.post(
        "/answer",
        headers=tenant_headers,
        json={"question": "明天合肥会下雨吗？", "orchestration": "langgraph"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reason"] == "insufficient_evidence"
    assert not any(step["node"].startswith("execute_grounded_") for step in body["agent_steps"])
    assert "verify_citation_scope" not in {
        step["node"] for step in body["agent_steps"]
    }
