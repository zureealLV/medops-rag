"""Deterministic malformed-input and archive-budget tests for parser boundaries."""

from __future__ import annotations

import random
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.config import Settings
from app.exceptions import AppError
from app.ingestion import parse_bytes
from app.main import create_app


def _archive(entries: list[tuple[str, bytes]]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return output.getvalue()


@pytest.mark.parametrize("suffix", [".docx", ".pptx", ".pdf", ".png"])
def test_seeded_malformed_inputs_fail_only_with_stable_app_errors(suffix: str):
    generator = random.Random(20260907)
    for size in (1, 2, 7, 31, 127, 511):
        content = generator.randbytes(size)
        with pytest.raises(AppError) as raised:
            parse_bytes(f"fuzz{suffix}", content, ocr_enabled=False)
        assert 400 <= raised.value.status_code < 500
        assert raised.value.code


@pytest.mark.parametrize(
    ("content", "kwargs", "expected_code"),
    [
        (
            _archive([(f"word/item-{index}.xml", b"x") for index in range(5)]),
            {"max_archive_entries": 4},
            "archive_limit_exceeded",
        ),
        (
            _archive([("word/document.xml", b"x" * 101)]),
            {"max_archive_uncompressed_bytes": 100},
            "archive_limit_exceeded",
        ),
        (
            _archive([("word/media/payload.bin", b"0" * 1_500_000)]),
            {"max_archive_compression_ratio": 20.0},
            "archive_limit_exceeded",
        ),
        (
            _archive([("../outside.xml", b"x")]),
            {},
            "unsafe_archive",
        ),
        (
            _archive([("word/vbaProject.bin", b"macro")]),
            {},
            "unsafe_archive",
        ),
    ],
)
def test_office_preflight_rejects_archive_abuse_before_docx_parser(
    content: bytes, kwargs: dict[str, int | float], expected_code: str
):
    with pytest.raises(AppError) as raised:
        parse_bytes("unsafe.docx", content, ocr_enabled=False, **kwargs)
    assert raised.value.code == expected_code


def test_pdf_page_and_render_budgets_are_checked_before_ocr():
    pages = PdfWriter()
    for _ in range(3):
        pages.add_blank_page(width=612, height=792)
    output = BytesIO()
    pages.write(output)
    with pytest.raises(AppError) as too_many:
        parse_bytes("many.pdf", output.getvalue(), ocr_enabled=False, max_pdf_pages=2)
    assert too_many.value.code == "pdf_page_limit_exceeded"

    huge = PdfWriter()
    huge.add_blank_page(width=10_000, height=10_000)
    output = BytesIO()
    huge.write(output)
    with pytest.raises(AppError) as too_large:
        parse_bytes("huge.pdf", output.getvalue(), ocr_enabled=True, max_image_pixels=1_000_000)
    assert too_large.value.code == "pdf_render_too_large"


def test_http_upload_uses_configured_archive_budget(tmp_path: Path):
    settings = Settings(
        database_path=tmp_path / "archive-api.db",
        max_archive_entries=1,
        ocr_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        headers = {"X-Tenant-ID": "hospital-a"}
        kb = client.post("/knowledge-bases", headers=headers, json={"name": "Ops"}).json()
        response = client.post(
            f"/knowledge-bases/{kb['id']}/documents/upload",
            headers=headers,
            files={
                "file": (
                    "over-budget.docx",
                    _archive([("[Content_Types].xml", b"x"), ("word/document.xml", b"x")]),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
    assert response.status_code == 413
    assert response.json()["code"] == "archive_limit_exceeded"
