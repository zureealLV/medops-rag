"""Structure-aware parent/child chunking and retrieval tests."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import initialize, transaction
from app.ingestion.parsers import NormalizedElement
from app.models.documents import DocumentCreate
from app.models.knowledge_bases import KnowledgeBaseCreate
from app.models.retrieval import SearchRequest
from app.retrieval.structure_chunking import build_parent_child_chunks
from app.services import documents, knowledge_bases
from app.services.retrieval import search


def test_structure_chunker_preserves_heading_and_page_provenance():
    elements = (
        NormalizedElement(modality="text", text="PACS gateway overview.", page_number=1, heading="Gateway"),
        NormalizedElement(
            modality="text",
            text="Check DICOM port 104 and TLS.",
            page_number=2,
            heading="Gateway",
        ),
        NormalizedElement(
            modality="text",
            text="Archive capacity procedure.",
            page_number=3,
            heading="Storage",
        ),
    )
    plans = build_parent_child_chunks(elements, parent_size=200, child_size=100, child_overlap=10)
    assert len(plans) == 2
    assert plans[0].heading == "Gateway"
    assert plans[0].page_start == 1
    assert plans[0].page_end == 2
    assert plans[0].element_start == 0
    assert plans[0].element_end == 1
    assert plans[1].heading == "Storage"
    assert plans[1].page_start == 3
    assert all(plan.children for plan in plans)


def test_parent_child_strategy_retrieves_child_but_returns_parent_context(
    client: TestClient, tenant_headers: dict[str, str], kb: dict
):
    prefix = "Gateway baseline notes. " * 35
    needle = "If code ZEBRA-417 appears, rotate the synthetic gateway certificate. "
    suffix = "Then validate the DICOM echo and record the change ticket. " * 8
    created = client.post(
        f"/knowledge-bases/{kb['id']}/documents",
        headers=tenant_headers,
        json={"title": "Long runbook", "source": "long.md", "content": prefix + needle + suffix},
    )
    assert created.status_code == 201

    response = client.post(
        "/search",
        headers=tenant_headers,
        json={
            "query": "What should happen for ZEBRA-417?",
            "knowledge_base_id": kb["id"],
            "strategy": "parent_child",
            "top_k": 3,
        },
    )
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["parent_id"] is not None
    assert "ZEBRA-417" in result["matched_text"]
    assert result["text"] == result["parent_text"]
    assert len(result["parent_text"]) > len(result["matched_text"])
    assert "DICOM echo" in result["parent_text"]


def test_parent_child_rows_are_rebuilt_after_manual_content_update(
    client: TestClient, tenant_headers: dict[str, str], kb: dict, document: dict
):
    updated = client.patch(
        f"/documents/{document['id']}",
        headers=tenant_headers,
        json={"content": "New runbook says use replacement marker NEBULA-900 and restart no services."},
    )
    assert updated.status_code == 200
    response = client.post(
        "/search",
        headers=tenant_headers,
        json={"query": "NEBULA-900", "strategy": "parent_child"},
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["document_id"] == document["id"]
    assert "NEBULA-900" in response.json()["results"][0]["matched_text"]


def test_initialize_backfills_legacy_fixed_chunks_without_rewriting_them(tmp_path):
    path = tmp_path / "legacy-chunks.db"
    settings = Settings(database_path=path)
    initialize(path)
    kb = knowledge_bases.create(path, "hospital-a", KnowledgeBaseCreate(name="Legacy"))
    document = documents.create(
        path,
        settings,
        "hospital-a",
        kb.id,
        DocumentCreate(title="Legacy", source="legacy.md", content="Legacy marker ORBIT-77."),
    )
    assert document is not None
    with transaction(path) as connection:
        legacy_count = connection.execute(
            "SELECT COUNT(*) FROM chunks WHERE document_id = ?", (document.id,)
        ).fetchone()[0]
        connection.execute("DELETE FROM parent_chunks WHERE document_id = ?", (document.id,))

    initialize(path)
    result = search(
        path,
        "hospital-a",
        SearchRequest(query="ORBIT-77", strategy="parent_child"),
    )
    assert result is not None and result.results
    assert result.results[0].document_id == document.id
    with transaction(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM chunks WHERE document_id = ?", (document.id,)
        ).fetchone()[0] == legacy_count
