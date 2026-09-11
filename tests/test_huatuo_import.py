"""Tests for the bounded Huatuo Chinese corpus importer."""

import json
from pathlib import Path

from app.config import Settings
from app.models.answers import AnswerRequest
from app.services import answers
from scripts.import_huatuo import CORPORA, import_records, parse_record, read_records


def test_parse_huatuo_record_flattens_nested_questions():
    raw = json.dumps(
        {
            "questions": [["流行性感冒的常见症状是什么？"]],
            "answers": ["流行性感冒的常见症状包括发热、咳嗽和乏力。"],
        },
        ensure_ascii=False,
    ).encode()

    record = parse_record(CORPORA[1], 7, raw)

    assert record is not None
    assert record.question == "流行性感冒的常见症状是什么？"
    assert "发热、咳嗽和乏力" in record.content
    assert record.source.endswith("?row=7")
    assert CORPORA[1].revision in record.content


def test_read_records_skips_malformed_empty_rows(tmp_path: Path):
    path = tmp_path / "subset.jsonl"
    path.write_text(
        '{"questions": [], "answers": []}\n'
        '{"questions": ["高血压有哪些危险因素？"], "answers": ["高盐饮食；肥胖"]}\n',
        encoding="utf-8",
    )

    records = read_records(CORPORA[0], path, 2)

    assert len(records) == 1
    assert records[0].row_index == 1


def test_imported_chinese_record_is_searchable_and_idempotent(tmp_path: Path):
    settings = Settings(
        database_path=tmp_path / "medops.db",
        retrieval_threshold=0.05,
        retrieval_keyword_threshold=0.20,
    )
    record = parse_record(
        CORPORA[0],
        0,
        json.dumps(
            {
                "questions": ["流行性感冒的常见症状是什么？"],
                "answers": ["流行性感冒的常见症状包括发热、咳嗽和乏力。"],
            },
            ensure_ascii=False,
        ).encode(),
    )
    assert record is not None

    kb_id, created, updated, skipped = import_records(
        settings, [record], tenant_id="hospital-a", refresh_existing=False
    )
    second = import_records(settings, [record], tenant_id="hospital-a", refresh_existing=False)
    result = answers.answer(
        settings.database_path,
        settings,
        "hospital-a",
        AnswerRequest(knowledge_base_id=kb_id, question="流行性感冒的常见症状是什么？"),
    )

    assert (created, updated, skipped) == (1, 0, 0)
    assert second[1:] == (0, 0, 1)
    assert result is not None
    assert result.abstained is False
    assert "发热、咳嗽和乏力" in result.answer
    assert result.citations[0].source.endswith("?row=0")
