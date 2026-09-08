"""Load synthetic medical knowledge or legacy operations examples into a local database."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.db import initialize
from app.models.documents import DocumentCreate
from app.models.knowledge_bases import KnowledgeBaseCreate
from app.services import documents, knowledge_bases

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class Corpus:
    key: str
    name: str
    description: str
    directory: Path


CORPORA = {
    "clinical": Corpus(
        key="clinical",
        name="医疗基础知识（权威摘要）",
        description="生命体征、标准预防与手卫生的教学摘要，附权威来源",
        directory=ROOT / "sample_data" / "medical_knowledge" / "clinical_basics",
    ),
    "devices": Corpus(
        key="devices",
        name="医疗器械安全与维护（权威摘要）",
        description="血氧仪、输液泵、器械再处理与设备生命周期教学摘要",
        directory=ROOT / "sample_data" / "medical_knowledge" / "medical_devices",
    ),
    "operations": Corpus(
        key="operations",
        name="Synthetic Operations",
        description="Legacy synthetic HIS/EMR/LIS/PACS runbooks",
        directory=ROOT / "sample_data" / "documents",
    ),
}


def _seed_corpus(settings: Settings, tenant_id: str, corpus: Corpus) -> tuple[int, int]:
    existing = knowledge_bases.list_all(settings.database_path, tenant_id)
    kb = next((item for item in existing if item.name == corpus.name), None)
    if kb is None:
        kb = knowledge_bases.create(
            settings.database_path,
            tenant_id,
            KnowledgeBaseCreate(name=corpus.name, description=corpus.description),
        )
    known_sources = {
        item.source for item in documents.list_for_kb(settings.database_path, tenant_id, kb.id) or []
    }
    created = 0
    for path in sorted(corpus.directory.glob("*.md")):
        if path.name in known_sources:
            continue
        result = documents.create(
            settings.database_path,
            settings,
            tenant_id,
            kb.id,
            DocumentCreate(
                title=path.stem.replace("_", " "),
                source=path.name,
                content=path.read_text(encoding="utf-8"),
            ),
        )
        created += int(result is not None)
    return kb.id, created


def seed(settings: Settings, *, tenant_id: str = "hospital-a") -> tuple[int, int]:
    """Backward-compatible operations corpus seed used by the V1 evaluation suite."""
    initialize(settings.database_path)
    return _seed_corpus(settings, tenant_id, CORPORA["operations"])


def seed_medical(settings: Settings, *, tenant_id: str = "hospital-a") -> list[tuple[str, int, int]]:
    """Create the two user-facing medical knowledge bases and return their counts."""
    initialize(settings.database_path)
    results = []
    for key in ("clinical", "devices"):
        kb_id, created = _seed_corpus(settings, tenant_id, CORPORA[key])
        results.append((key, kb_id, created))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="hospital-a")
    parser.add_argument(
        "--profile",
        choices=("medical", "operations", "all"),
        default="medical",
        help="medical is the user-facing default; operations keeps the legacy evaluation corpus",
    )
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.profile in {"medical", "all"}:
        for key, kb_id, created in seed_medical(settings, tenant_id=args.tenant):
            print(f"profile={key} knowledge_base_id={kb_id} documents_created={created}")
    if args.profile in {"operations", "all"}:
        kb_id, created = seed(settings, tenant_id=args.tenant)
        print(f"profile=operations knowledge_base_id={kb_id} documents_created={created}")


if __name__ == "__main__":
    main()
