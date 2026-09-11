"""Start a real local server and exercise OCR upload, provenance, and search."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def image_fixture() -> bytes:
    image = Image.new("RGB", (1000, 220), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 52)
    draw.text((30, 70), "PACS PORT 104 HEALTH CHECK", font=font, fill="black")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def wait_for_health(client: httpx.Client, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = client.get("/health")
            if response.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(0.1)
    raise RuntimeError(f"server did not become healthy: {last_error}")


def main() -> None:
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="medops-v2-smoke-") as directory:
        database = Path(directory) / "smoke.db"
        environment = os.environ.copy()
        environment["DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
        environment["PYTHONUTF8"] = "1"
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=creation_flags,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=20) as client:
                wait_for_health(client)
                openapi = client.get("/openapi.json")
                openapi.raise_for_status()
                assert "/documents/{document_id}/elements" in openapi.json()["paths"]
                headers = {"X-Tenant-ID": "hospital-a", "X-Actor-ID": "smoke"}
                kb_response = client.post(
                    "/knowledge-bases",
                    headers=headers,
                    json={"name": "Smoke KB", "description": "Generated acceptance fixture"},
                )
                kb_response.raise_for_status()
                kb_id = kb_response.json()["id"]
                upload = client.post(
                    f"/knowledge-bases/{kb_id}/documents/upload",
                    headers=headers,
                    files={"file": ("pacs-check.png", image_fixture(), "image/png")},
                )
                upload.raise_for_status()
                document = upload.json()
                elements = client.get(
                    f"/documents/{document['id']}/elements", headers=headers
                )
                elements.raise_for_status()
                search = client.post(
                    "/search",
                    headers=headers,
                    json={
                        "query": "PACS PORT 104",
                        "knowledge_base_id": kb_id,
                        "strategy": "bm25",
                    },
                )
                search.raise_for_status()
                result = search.json()
                assert document["parser"] == "png"
                assert any(item["modality"] == "image_ocr" for item in elements.json())
                assert result["results"] and "PACS PORT 104" in result["results"][0]["text"]
                print(
                    json.dumps(
                        {
                            "health": "ok",
                            "openapi_elements_path": "ok",
                            "document_id": document["id"],
                            "sha256": document["sha256"],
                            "element_modalities": [item["modality"] for item in elements.json()],
                            "search_strategy": result["strategy"],
                            "top_source": result["results"][0]["source"],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
        finally:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)
        if process.returncode not in {0, -15, 1}:
            raise RuntimeError(f"uvicorn terminated unexpectedly with {process.returncode}")


if __name__ == "__main__":
    main()
