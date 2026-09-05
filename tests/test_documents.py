"""Document CRUD, relationship, and ingestion tests."""

from fastapi.testclient import TestClient


def test_document_crud_and_chunking(
    client: TestClient, tenant_headers: dict[str, str], kb: dict, document: dict
):
    assert document["chunk_count"] >= 1
    listed = client.get(f"/knowledge-bases/{kb['id']}/documents", headers=tenant_headers)
    assert [item["id"] for item in listed.json()] == [document["id"]]
    updated = client.patch(
        f"/documents/{document['id']}",
        headers=tenant_headers,
        json={"content": "PACS 健康检查失败时检查 DICOM 端口、磁盘容量和服务日志。"},
    )
    assert updated.status_code == 200
    assert updated.json()["chunk_count"] == 1
    assert client.delete(f"/documents/{document['id']}", headers=tenant_headers).status_code == 204
    assert client.get(f"/documents/{document['id']}", headers=tenant_headers).status_code == 404


def test_missing_kb_rejects_document(client: TestClient, tenant_headers: dict[str, str]):
    response = client.post(
        "/knowledge-bases/999/documents",
        headers=tenant_headers,
        json={"title": "x", "content": "some valid content", "source": "x.md"},
    )
    assert response.status_code == 404


def test_markdown_upload_and_extension_validation(
    client: TestClient, tenant_headers: dict[str, str], kb: dict
):
    uploaded = client.post(
        f"/knowledge-bases/{kb['id']}/documents/upload",
        headers=tenant_headers,
        files={"file": ("pacs.md", "PACS DICOM 端口健康检查。".encode(), "text/markdown")},
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["source"] == "pacs.md"
    rejected = client.post(
        f"/knowledge-bases/{kb['id']}/documents/upload",
        headers=tenant_headers,
        files={"file": ("payload.exe", b"not a document", "application/octet-stream")},
    )
    assert rejected.status_code == 400


def test_deleting_kb_cascades_documents(
    client: TestClient, tenant_headers: dict[str, str], kb: dict, document: dict
):
    assert client.delete(f"/knowledge-bases/{kb['id']}", headers=tenant_headers).status_code == 204
    assert client.get(f"/documents/{document['id']}", headers=tenant_headers).status_code == 404
