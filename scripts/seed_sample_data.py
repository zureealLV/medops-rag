"""Load the repository's synthetic runbooks into a local database."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.config import Settings
from app.db import initialize
from app.models.documents import DocumentCreate
from app.models.knowledge_bases import KnowledgeBaseCreate
from app.services import documents, knowledge_bases

ROOT = Path(__file__).resolve().parents[1]


def seed(settings: Settings, *, tenant_id: str = "hospital-a") -> tuple[int, int]:
    initialize(settings.database_path)
    existing = knowledge_bases.list_all(settings.database_path, tenant_id)
    kb = next((item for item in existing if item.name == "Synthetic Operations"), None)
    if kb is None:
        kb = knowledge_bases.create(
            settings.database_path,
            tenant_id,
            KnowledgeBaseCreate(
                name="Synthetic Operations", description="Synthetic HIS/EMR/LIS/PACS runbooks"
            ),
        )
    known_sources = {
        item.source for item in documents.list_for_kb(settings.database_path, tenant_id, kb.id) or []
    }
    created = 0
    for path in sorted((ROOT / "sample_data" / "documents").glob("*.md")):
        if path.name in known_sources:
            continue
        result = documents.create(
            settings.database_path,
            settings,
            tenant_id,
            kb.id,
            DocumentCreate(
                title=path.stem.replace("_", " "), source=path.name, content=path.read_text(encoding="utf-8")
            ),
        )
        created += int(result is not None)
    return kb.id, created


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="hospital-a")
    args = parser.parse_args()
    kb_id, created = seed(Settings.from_env(), tenant_id=args.tenant)
    print(f"knowledge_base_id={kb_id} documents_created={created}")


if __name__ == "__main__":
    main()
