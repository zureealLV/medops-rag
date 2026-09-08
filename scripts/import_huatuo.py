"""Import a bounded, reproducible Chinese medical corpus from Huatuo-26M.

The importer streams only the requested number of JSONL records from immutable
Hugging Face revisions.  This keeps the default local demo useful without
silently downloading or indexing the complete multi-gigabyte collection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.request
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import Settings
from app.db import initialize
from app.models.documents import DocumentCreate, DocumentUpdate
from app.models.knowledge_bases import KnowledgeBaseCreate
from app.services import documents, knowledge_bases

ROOT = Path(__file__).resolve().parents[1]
KB_NAME = "华佗中文医学知识库（研究用途）"
MAX_LINE_BYTES = 1_000_000
MAX_SUBSET_BYTES = 64_000_000


@dataclass(frozen=True, slots=True)
class CorpusSpec:
    key: str
    label: str
    repository: str
    revision: str
    filename: str
    default_limit: int

    @property
    def dataset_url(self) -> str:
        return f"https://huggingface.co/datasets/{self.repository}"

    @property
    def download_url(self) -> str:
        return f"{self.dataset_url}/resolve/{self.revision}/{self.filename}?download=true"


CORPORA = (
    CorpusSpec(
        key="knowledge_graph",
        label="Huatuo-26M 医疗知识图谱问答",
        repository="FreedomIntelligence/huatuo_knowledge_graph_qa",
        revision="b01fb013d5595abe18c97408dd2fc939e4f7ea3f",
        filename="train_datasets.jsonl",
        default_limit=12_000,
    ),
    CorpusSpec(
        key="encyclopedia",
        label="Huatuo-26M 在线医疗百科问答",
        repository="FreedomIntelligence/huatuo_encyclopedia_qa",
        revision="2989899dd5bed83cf9bd17cf9fff9889705436e2",
        filename="train_datasets.jsonl",
        default_limit=3_000,
    ),
)


@dataclass(frozen=True, slots=True)
class QARecord:
    corpus: CorpusSpec
    row_index: int
    question: str
    answer: str

    @property
    def source(self) -> str:
        return f"{self.corpus.dataset_url}?row={self.row_index}"

    @property
    def title(self) -> str:
        return self.question.rstrip("？?")[:200]

    @property
    def content(self) -> str:
        return "\n\n".join(
            (
                f"# {self.question}",
                "## 数据集答案",
                self.answer,
                "## 数据来源",
                f"数据集：{self.corpus.label}",
                f"Hugging Face 仓库：{self.corpus.repository}",
                f"固定版本：{self.corpus.revision}",
                f"原始文件：{self.corpus.filename}，第 {self.row_index + 1} 条记录",
                "许可证标记：Apache-2.0",
                "证据说明：该语料由公开医学知识库和在线医学百科整理，未经本项目临床复核。",
                "安全说明：仅供医学知识检索测试，不能替代医生诊断、处方或治疗建议。",
            )
        )[:200_000]


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        normalized = " ".join(value.split())
        return [normalized] if normalized else []
    if isinstance(value, list):
        flattened: list[str] = []
        for item in value:
            flattened.extend(_flatten_strings(item))
        return flattened
    return []


def parse_record(spec: CorpusSpec, row_index: int, raw: bytes) -> QARecord | None:
    """Validate the two observed Huatuo schemas without executing dataset code."""
    if len(raw) > MAX_LINE_BYTES:
        raise ValueError(f"{spec.key} row {row_index} exceeds the per-record safety limit")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{spec.key} row {row_index} is not valid UTF-8 JSON") from exc
    questions = _flatten_strings(payload.get("questions")) if isinstance(payload, dict) else []
    answers = _flatten_strings(payload.get("answers")) if isinstance(payload, dict) else []
    if not questions or not answers:
        return None
    question = "；".join(dict.fromkeys(questions))
    answer = "；".join(dict.fromkeys(answers))
    if len(question) < 2 or len(answer) < 1:
        return None
    return QARecord(spec, row_index, question[:2_000], answer[:50_000])


def download_subset(spec: CorpusSpec, destination: Path, limit: int, retries: int = 3) -> Path:
    """Stream a deterministic prefix and close the remote response at ``limit`` rows."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        cached_rows = 0
        cached_bytes = 0
        with destination.open("rb") as cached:
            for line in cached:
                cached_rows += 1
                cached_bytes += len(line)
                if len(line) > MAX_LINE_BYTES or cached_bytes > MAX_SUBSET_BYTES:
                    break
        if cached_rows == limit and cached_bytes <= MAX_SUBSET_BYTES:
            return destination
        destination.unlink()
    temporary = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                spec.download_url, headers={"User-Agent": "medops-rag/2.3 corpus importer"}
            )
            with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as out:
                written = 0
                rows = 0
                while rows < limit:
                    line = response.readline(MAX_LINE_BYTES + 1)
                    if not line:
                        break
                    if len(line) > MAX_LINE_BYTES:
                        raise ValueError("Huatuo record exceeds the per-record safety limit")
                    written += len(line)
                    if written > MAX_SUBSET_BYTES:
                        raise ValueError("Huatuo subset exceeds the local download safety limit")
                    out.write(line.rstrip(b"\r\n") + b"\n")
                    rows += 1
            if rows != limit:
                raise RuntimeError(f"Huatuo download returned {rows} records; expected {limit}")
            temporary.replace(destination)
            return destination
        except (OSError, RuntimeError, ValueError) as exc:
            temporary.unlink(missing_ok=True)
            if attempt == retries:
                raise RuntimeError(f"Failed to download {spec.key} after {retries} attempts") from exc
            time.sleep(2 ** (attempt - 1))
    raise AssertionError("unreachable")


def read_records(spec: CorpusSpec, path: Path, limit: int) -> list[QARecord]:
    records: list[QARecord] = []
    with path.open("rb") as source:
        for row_index, line in enumerate(source):
            if len(records) >= limit:
                break
            record = parse_record(spec, row_index, line)
            if record is not None:
                records.append(record)
    return records


def import_records(
    settings: Settings,
    records: list[QARecord],
    *,
    tenant_id: str,
    refresh_existing: bool,
) -> tuple[int, int, int, int]:
    initialize(settings.database_path)
    existing_kbs = knowledge_bases.list_all(settings.database_path, tenant_id)
    kb = next((item for item in existing_kbs if item.name == KB_NAME), None)
    if kb is None:
        kb = knowledge_bases.create(
            settings.database_path,
            tenant_id,
            KnowledgeBaseCreate(
                name=KB_NAME,
                description="Huatuo-26M 中文知识图谱与医学百科问答；Apache-2.0，研究测试用途",
            ),
        )
    existing = {
        item.source: item
        for item in documents.list_for_kb(settings.database_path, tenant_id, kb.id) or []
    }
    created = updated = skipped = 0
    for record in records:
        stored = existing.get(record.source)
        if stored is None:
            result = documents.create(
                settings.database_path,
                settings,
                tenant_id,
                kb.id,
                DocumentCreate(title=record.title, source=record.source, content=record.content),
            )
            created += int(result is not None)
        elif refresh_existing and (stored.title != record.title or stored.content != record.content):
            documents.update(
                settings.database_path,
                settings,
                tenant_id,
                stored.id,
                DocumentUpdate(title=record.title, content=record.content),
            )
            updated += 1
        else:
            skipped += 1
    return kb.id, created, updated, skipped


def write_manifest(output_dir: Path, files: list[tuple[CorpusSpec, Path, int]], kb_id: int) -> Path:
    manifest = {
        "name": "Huatuo-26M bounded Chinese RAG corpus",
        "publisher": "FreedomIntelligence",
        "accessed_at": datetime.now(UTC).isoformat(),
        "knowledge_base_id": kb_id,
        "language": "zh-CN",
        "license_declared_by_dataset": "Apache-2.0",
        "records": sum(count for _, _, count in files),
        "sources": [
            {
                "key": spec.key,
                "repository": spec.repository,
                "revision": spec.revision,
                "filename": spec.filename,
                "download_url": spec.download_url,
                "local_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "record_count": count,
            }
            for spec, path, count in files
        ],
        "provenance_note": (
            "Aggregated from public medical knowledge graphs and online encyclopedias; "
            "the MedOps project has not clinically reviewed individual records."
        ),
        "safety_note": "Research and retrieval testing only; not clinical decision support.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "sources.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="hospital-a")
    parser.add_argument("--knowledge-graph-limit", type=int, default=12_000)
    parser.add_argument("--encyclopedia-limit", type=int, default=3_000)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "external" / "huatuo")
    parser.add_argument("--database", type=Path, help="Override DATABASE_URL for this import")
    parser.add_argument("--refresh-existing", action="store_true")
    args = parser.parse_args()
    limits = {
        "knowledge_graph": args.knowledge_graph_limit,
        "encyclopedia": args.encyclopedia_limit,
    }
    if any(value < 0 for value in limits.values()) or not any(limits.values()):
        parser.error("limits must be non-negative and at least one corpus limit must be positive")

    output_dir = args.output_dir.resolve()
    all_records: list[QARecord] = []
    files: list[tuple[CorpusSpec, Path, int]] = []
    for spec in CORPORA:
        limit = limits[spec.key]
        if limit == 0:
            continue
        path = output_dir / "raw" / f"{spec.key}-{spec.revision[:12]}-{limit}.jsonl"
        path = download_subset(spec, path, limit)
        records = read_records(spec, path, limit)
        all_records.extend(records)
        files.append((spec, path, len(records)))

    settings = Settings.from_env()
    if args.database:
        settings = replace(settings, database_path=args.database.resolve())
    kb_id, created, updated, skipped = import_records(
        settings, all_records, tenant_id=args.tenant, refresh_existing=args.refresh_existing
    )
    manifest = write_manifest(output_dir, files, kb_id)
    print(
        f"knowledge_base_id={kb_id} records={len(all_records)} created={created} "
        f"updated={updated} skipped={skipped} manifest={manifest}"
    )


if __name__ == "__main__":
    main()
