"""Medical-domain seed coverage and idempotency."""

from pathlib import Path

from app.config import Settings
from app.models.answers import AnswerRequest
from app.services.answers import answer
from scripts.seed_sample_data import seed_medical


def test_medical_seed_creates_domain_knowledge_bases_and_is_idempotent(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "medical.db")

    first = seed_medical(settings)
    second = seed_medical(settings)

    assert [(key, created) for key, _, created in first] == [("clinical", 3), ("devices", 4)]
    assert [(key, created) for key, _, created in second] == [("clinical", 0), ("devices", 0)]


def test_medical_device_question_uses_domain_corpus(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "medical.db")
    results = seed_medical(settings)
    device_kb_id = next(kb_id for key, kb_id, _ in results if key == "devices")

    result = answer(
        settings.database_path,
        settings,
        "hospital-a",
        AnswerRequest(question="哪些因素可能影响脉搏血氧仪读数？", knowledge_base_id=device_kb_id),
    )

    assert result is not None
    assert result.abstained is False
    assert result.citations[0].source == "pulse_oximeter_basics.md"
    assert "[来源1]" in result.answer
    assert "[" + str(result.citations[0].document_id) + ":" not in result.answer
