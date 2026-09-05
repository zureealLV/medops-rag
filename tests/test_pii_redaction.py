"""Sensitive-data redaction and log-leakage tests."""

from fastapi.testclient import TestClient

from app.security.pii import redact


def test_common_identifiers_are_redacted():
    value = redact("手机 13800138000 邮箱 alice@example.com 身份证 11010519491231002X")
    assert "13800138000" not in value
    assert "alice@example.com" not in value
    assert "11010519491231002X" not in value


def test_audit_details_do_not_store_raw_pii(
    client: TestClient, tenant_headers: dict[str, str], document: dict
):
    client.post("/search", headers=tenant_headers, json={"query": "联系 13800138000 查询 LIS"})
    details = client.get("/audit-logs", headers=tenant_headers).json()[0]["details"]
    assert "13800138000" not in details
    assert "[REDACTED_PHONE]" in details
