"""Exercise API plus both durable workers in a running local Compose stack."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid

BASE_URL = "http://127.0.0.1:8000"
TENANT_HEADERS = {"X-Tenant-ID": "compose-smoke", "X-Actor-ID": "compose-smoke"}


def _request(
    method: str,
    path: str,
    *,
    body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        BASE_URL + path,
        data=payload,
        method=method,
        headers={
            **TENANT_HEADERS,
            **(headers or {}),
            **({"Content-Type": "application/json"} if payload is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _wait_job(path: str, timeout: float = 30.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, job = _request("GET", path)
        if status == 200 and job["state"] in {"succeeded", "partial", "failed", "cancelled"}:
            return job
        time.sleep(0.25)
    raise TimeoutError(f"job did not finish: {path}")


def main() -> None:
    status, health = _request("GET", "/health")
    assert status == 200 and health["status"] == "ok", health
    with urllib.request.urlopen(f"{BASE_URL}/ui/", timeout=5) as response:
        console = response.read().decode("utf-8")
        assert response.status == 200 and "MedOps Control Plane" in console
    nonce = uuid.uuid4().hex[:12]
    status, kb = _request("POST", "/knowledge-bases", body={"name": f"Compose smoke {nonce}"})
    assert status == 201, kb

    # Multipart is constructed with stdlib so this smoke runner adds no dependency.
    boundary = f"----medops-{nonce}"
    content = b"PACS gateway timeout. Verify DNS and TLS before restart."
    multipart = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"smoke.md\"\r\n"
        "Content-Type: text/markdown\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    upload_request = urllib.request.Request(
        f"{BASE_URL}/knowledge-bases/{kb['id']}/ingestion-jobs",
        data=multipart,
        method="POST",
        headers={
            **TENANT_HEADERS,
            "Idempotency-Key": f"compose-upload-{nonce}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    with urllib.request.urlopen(upload_request, timeout=5) as response:
        assert response.status == 202
        ingestion = json.loads(response.read())
    ingestion = _wait_job(f"/ingestion-jobs/{ingestion['id']}")
    assert ingestion["state"] == "succeeded", ingestion

    status, summary = _request(
        "POST",
        f"/knowledge-bases/{kb['id']}/summary-jobs",
        body={"question": "Summarize recovery", "document_ids": [ingestion["document_id"]]},
        headers={"Idempotency-Key": f"compose-summary-{nonce}"},
    )
    assert status == 202, summary
    summary = _wait_job(f"/summary-jobs/{summary['id']}")
    assert summary["state"] == "succeeded", summary
    assert f"[document:{ingestion['document_id']}]" in str(summary["summary"])
    print("Compose Web console + API + ingestion worker + summary worker smoke: PASS")


if __name__ == "__main__":
    main()
