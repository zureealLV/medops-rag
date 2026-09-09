"""Tests for the hash-pinned official Chinese source importer."""

import hashlib
import json
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from app.config import Settings
from app.models.answers import AnswerRequest
from app.services import answers
from scripts.import_chinese_official import (
    OfficialSource,
    import_sources,
    load_catalog,
)


def _pdf(path: Path) -> bytes:
    target = canvas.Canvas(str(path))
    target.drawString(72, 720, "UDI-DI identifies a medical device model.")
    target.save()
    return path.read_bytes()


def _source(content: bytes) -> OfficialSource:
    return OfficialSource(
        key="nmpa-test",
        title="医疗器械唯一标识测试资料",
        publisher="国家药品监督管理局",
        published_at="2022-08-17",
        category="医疗器械标准",
        trust_tier="official_government",
        filename="udi-test.pdf",
        url="https://udid.nmpa.gov.cn/example/udi-test.pdf",
        sha256=hashlib.sha256(content).hexdigest(),
    )


def test_catalog_rejects_unapproved_hosts(tmp_path: Path):
    content = b"%PDF-test"
    source = _source(content)
    payload = {
        "catalog_version": 1,
        "language": "zh-CN",
        "sources": [{**{field: getattr(source, field) for field in source.__dataclass_fields__},
                     "url": "https://example.com/not-approved.pdf"}],
    }
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="allow-listed"):
        load_catalog(catalog)


def test_official_pdf_import_is_searchable_idempotent_and_cited(tmp_path: Path):
    pdf_path = tmp_path / "udi-test.pdf"
    content = _pdf(pdf_path)
    source = _source(content)
    settings = Settings(
        database_path=tmp_path / "medops.db",
        retrieval_threshold=0.01,
        retrieval_keyword_threshold=0.01,
    )

    first = import_sources(
        settings, (source,), {source.key: pdf_path}, tenant_id="hospital-a"
    )
    second = import_sources(
        settings, (source,), {source.key: pdf_path}, tenant_id="hospital-a"
    )
    result = answers.answer(
        settings.database_path,
        settings,
        "hospital-a",
        AnswerRequest(knowledge_base_id=first[0], question="医疗器械 UDI-DI 标识什么？"),
    )

    assert first[1:] == (1, 0)
    assert second[1:] == (0, 1)
    assert result is not None
    assert result.abstained is False
    assert result.citations[0].source == source.url
    assert "医疗器械" in result.answer


def test_import_rechecks_local_file_hash(tmp_path: Path):
    content = _pdf(tmp_path / "udi-test.pdf")
    source = _source(content)
    path = tmp_path / "udi-test.pdf"
    path.write_bytes(content + b"changed")

    with pytest.raises(RuntimeError, match="local source SHA-256"):
        import_sources(
            Settings(database_path=tmp_path / "medops.db"),
            (source,),
            {source.key: path},
            tenant_id="hospital-a",
        )
