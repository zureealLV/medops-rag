"""Tests for the reproducible official MedlinePlus corpus importer."""

from pathlib import Path

from app.config import Settings
from app.models.answers import AnswerRequest
from app.services import answers
from scripts.import_medlineplus import import_topics, parse_topics

XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<health-topics total="2" date-generated="09/05/2026 02:30:39">
  <health-topic title="A1C" url="https://medlineplus.gov/a1c.html" id="6308" language="English">
    <also-called>Hemoglobin A1C test</also-called>
    <full-summary>
      &lt;h2&gt;What does an A1C test measure?&lt;/h2&gt;
      &lt;p&gt;A1C measures average blood glucose over the past three months.&lt;/p&gt;
    </full-summary>
    <mesh-heading>Glycated Hemoglobin</mesh-heading>
    <group>Diagnostic Tests</group>
    <primary-institute>National Institute of Diabetes and Digestive and Kidney Diseases</primary-institute>
  </health-topic>
  <health-topic title="Prueba A1C" url="https://medlineplus.gov/spanish/a1c.html"
                id="6309" language="Spanish">
    <full-summary>&lt;p&gt;La prueba mide el nivel promedio de glucosa.&lt;/p&gt;</full-summary>
  </health-topic>
</health-topics>
"""


def test_parse_topics_filters_language_and_preserves_provenance():
    topics, generated_at = parse_topics(XML, {"English"})

    assert generated_at == "09/05/2026 02:30:39"
    assert len(topics) == 1
    assert topics[0].title == "A1C"
    assert "average blood glucose" in topics[0].content
    assert "Glycated Hemoglobin" in topics[0].content
    assert topics[0].url == "https://medlineplus.gov/a1c.html"


def test_imported_topic_is_searchable_and_idempotent(tmp_path: Path):
    settings = Settings(
        database_path=tmp_path / "medops.db",
        retrieval_threshold=0.05,
        retrieval_keyword_threshold=0.20,
    )
    topics, _ = parse_topics(XML, {"English"})

    kb_id, created, updated, skipped = import_topics(
        settings, topics, tenant_id="hospital-a", refresh_existing=False
    )
    second = import_topics(settings, topics, tenant_id="hospital-a", refresh_existing=False)
    result = answers.answer(
        settings.database_path,
        settings,
        "hospital-a",
        AnswerRequest(knowledge_base_id=kb_id, question="What does A1C measure?"),
    )

    assert (created, updated, skipped) == (1, 0, 0)
    assert second[1:] == (0, 0, 1)
    assert result is not None
    assert result.abstained is False
    assert result.citations[0].source == "https://medlineplus.gov/a1c.html"
    assert "blood glucose" in result.answer
    assert "What does an A1C test measure?" not in result.answer
