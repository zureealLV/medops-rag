"""Persistent multi-turn conversation behavior and isolation."""

from fastapi.testclient import TestClient


def test_conversation_persists_and_resolves_colloquial_followup(
    client: TestClient, tenant_headers: dict[str, str], kb: dict, document: dict
):
    created = client.post(
        "/conversations",
        headers=tenant_headers,
        json={"knowledge_base_id": kb["id"]},
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    first = client.post(
        f"/conversations/{conversation_id}/messages",
        headers=tenant_headers,
        json={"content": "LIS 接口老是超时，先瞧啥啊？"},
    )
    assert first.status_code == 200
    assert first.json()["answer"]["abstained"] is False

    followup = client.post(
        f"/conversations/{conversation_id}/messages",
        headers=tenant_headers,
        json={"content": "那还要看啥？"},
    )
    assert followup.status_code == 200
    body = followup.json()
    assert "LIS 接口经常超时" in body["contextualized_question"]
    assert "那还要看什么" in body["contextualized_question"]
    assert body["answer"]["orchestration"] == "langgraph"
    assert body["answer"]["citations"][0]["document_id"] == document["id"]

    loaded = client.get(f"/conversations/{conversation_id}", headers=tenant_headers)
    assert loaded.status_code == 200
    assert [item["role"] for item in loaded.json()["messages"]] == ["user", "assistant", "user", "assistant"]
    assert loaded.json()["message_count"] == 4


def test_conversation_is_actor_scoped(client: TestClient, tenant_headers: dict[str, str], kb: dict):
    created = client.post(
        "/conversations", headers=tenant_headers, json={"knowledge_base_id": kb["id"]}
    ).json()
    other_actor = {**tenant_headers, "X-Actor-ID": "someone-else"}

    assert client.get(f"/conversations/{created['id']}", headers=other_actor).status_code == 404
    assert client.get("/conversations", headers=other_actor).json() == []


def test_delete_conversation_removes_history(client: TestClient, tenant_headers: dict[str, str], kb: dict):
    created = client.post(
        "/conversations", headers=tenant_headers, json={"knowledge_base_id": kb["id"]}
    ).json()
    response = client.delete(f"/conversations/{created['id']}", headers=tenant_headers)
    assert response.status_code == 204
    assert client.get(f"/conversations/{created['id']}", headers=tenant_headers).status_code == 404


def test_colloquial_prescription_request_is_denied(
    client: TestClient, tenant_headers: dict[str, str], kb: dict
):
    created = client.post(
        "/conversations", headers=tenant_headers, json={"knowledge_base_id": kb["id"]}
    ).json()
    response = client.post(
        f"/conversations/{created['id']}/messages",
        headers=tenant_headers,
        json={"content": "我血压高，你直接给我开点药呗"},
    )

    assert response.status_code == 200
    assert response.json()["answer"]["reason"] == "medical_advice_denied"
