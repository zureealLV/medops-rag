"""Run a real local API process through image ingestion and CLIP visual search."""

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
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def icon(color: str, shape: str) -> bytes:
    image = Image.new("RGB", (384, 384), "white")
    draw = ImageDraw.Draw(image)
    if shape == "triangle":
        draw.polygon([(192, 45), (45, 330), (339, 330)], fill=color)
    else:
        draw.ellipse((45, 45, 339, 339), fill=color)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def wait_for_health(client: httpx.Client) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            if client.get("/health").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError("server did not become healthy")


def main() -> None:
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="medops-visual-smoke-") as directory:
        environment = os.environ.copy()
        environment.update(
            {
                "DATABASE_URL": f"sqlite:///{(Path(directory) / 'smoke.db').as_posix()}",
                "PYTHONUTF8": "1",
                "OCR_ENABLED": "false",
                "IMAGE_EMBEDDING_ENABLED": "true",
                "MODEL_CACHE_DIR": str(ROOT / "data/models/fastembed"),
                "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
            }
        )
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
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=60) as client:
                wait_for_health(client)
                headers = {"X-Tenant-ID": "hospital-a", "X-Actor-ID": "visual-smoke"}
                created = client.post(
                    "/knowledge-bases",
                    headers=headers,
                    json={"name": "Visual Smoke", "description": "generated icons"},
                )
                created.raise_for_status()
                kb_id = created.json()["id"]
                for filename, payload in (
                    ("red-triangle.png", icon("#e53935", "triangle")),
                    ("blue-circle.png", icon("#2775d8", "circle")),
                ):
                    upload = client.post(
                        f"/knowledge-bases/{kb_id}/documents/upload",
                        headers=headers,
                        files={"file": (filename, payload, "image/png")},
                    )
                    upload.raise_for_status()
                    assert upload.json()["artifact_count"] == 1
                search = client.post(
                    "/visual-search",
                    headers=headers,
                    json={
                        "query": "a red triangle icon",
                        "knowledge_base_id": kb_id,
                        "strategy": "image",
                    },
                )
                search.raise_for_status()
                result = search.json()
                top = result["results"][0]
                assert top["source"] == "red-triangle.png"
                content = client.get(top["content_url"], headers=headers)
                content.raise_for_status()
                assert content.headers["content-type"] == "image/png"
                answer = client.post(
                    "/answer",
                    headers=headers,
                    json={
                        "question": "Which image has the red triangle icon?",
                        "knowledge_base_id": kb_id,
                        "text_strategy": "keyword",
                    },
                )
                answer.raise_for_status()
                grounded = answer.json()
                assert grounded["abstained"] is False
                assert grounded["retrieval_profile"] == "visual"
                assert grounded["visual_citations"][0]["source"] == "red-triangle.png"
                print(
                    json.dumps(
                        {
                            "health": "ok",
                            "image_embedding_available": result["image_embedding_available"],
                            "strategy": result["strategy"],
                            "top_source": top["source"],
                            "top_score": top["score"],
                            "visual_citation": top["content_url"],
                            "content_sha256": top["sha256"],
                            "answer_profile": grounded["retrieval_profile"],
                            "answer_provider": grounded["provider"],
                            "answer_visual_source": grounded["visual_citations"][0]["source"],
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


if __name__ == "__main__":
    main()
