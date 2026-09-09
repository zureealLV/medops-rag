"""Import a hash-pinned catalog of official Chinese medical PDFs.

Source binaries remain outside Git.  Downloads are restricted to exact HTTPS
publisher hosts, capped by byte count, checked as PDFs and verified against the
catalog SHA-256 before parsing or persistence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import unicodedata
import urllib.request
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from app.config import Settings
from app.db import initialize
from app.ingestion.parsers import NormalizedElement, ParsedDocument, parse_bytes
from app.models.documents import DocumentUpdate
from app.models.knowledge_bases import KnowledgeBaseCreate
from app.services import documents, knowledge_bases

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "data" / "catalogs" / "chinese_official_sources.json"
DEFAULT_OUTPUT = ROOT / "data" / "external" / "chinese_official"
KB_NAME = "中国官方医疗与医疗器械资料（政府公开）"
ALLOWED_HOSTS = frozenset(
    {"www.nhc.gov.cn", "www.gov.cn", "xzfg.moj.gov.cn", "udid.nmpa.gov.cn"}
)
MAX_SOURCE_BYTES = 25_000_000
MAX_TOTAL_BYTES = 100_000_000
MAX_SOURCES = 50


@dataclass(frozen=True, slots=True)
class OfficialSource:
    key: str
    title: str
    publisher: str
    published_at: str
    category: str
    trust_tier: str
    filename: str
    url: str
    sha256: str


def _validate_source(source: OfficialSource) -> None:
    parsed = urlparse(source.url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"{source.key}: source URL host is not allow-listed")
    if Path(source.filename).name != source.filename or not source.filename.lower().endswith(".pdf"):
        raise ValueError(f"{source.key}: filename must be a plain PDF filename")
    if len(source.sha256) != 64 or any(character not in "0123456789abcdef" for character in source.sha256):
        raise ValueError(f"{source.key}: invalid SHA-256")
    if source.trust_tier != "official_government":
        raise ValueError(f"{source.key}: catalog entry does not meet the official trust tier")


def load_catalog(path: Path) -> tuple[OfficialSource, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("catalog_version") != 1 or payload.get("language") != "zh-CN":
        raise ValueError("unsupported official-source catalog")
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources or len(raw_sources) > MAX_SOURCES:
        raise ValueError("catalog must contain between 1 and 50 sources")
    sources = tuple(OfficialSource(**item) for item in raw_sources)
    for field in ("key", "title", "filename", "url"):
        if len({getattr(source, field) for source in sources}) != len(sources):
            raise ValueError(f"catalog source {field} values must be unique")
    for source in sources:
        _validate_source(source)
    return sources


def download_source(
    source: OfficialSource, destination: Path, *, max_bytes: int = MAX_SOURCE_BYTES, retries: int = 3
) -> Path:
    """Download one immutable expected payload, reusing only a matching cache."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == source.sha256:
        return destination
    destination.unlink(missing_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                source.url, headers={"User-Agent": "Mozilla/5.0 medops-rag/2.4 official-importer"}
            )
            digest = hashlib.sha256()
            written = 0
            prefix = b""
            with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as out:
                final = urlparse(response.geturl())
                if final.scheme != "https" or final.hostname not in ALLOWED_HOSTS:
                    raise ValueError(f"{source.key}: redirect left the publisher allow-list")
                while chunk := response.read(128 * 1024):
                    written += len(chunk)
                    if written > max_bytes:
                        raise ValueError(f"{source.key}: source exceeds {max_bytes} bytes")
                    if len(prefix) < 5:
                        prefix += chunk[: 5 - len(prefix)]
                    digest.update(chunk)
                    out.write(chunk)
            if prefix != b"%PDF-":
                raise ValueError(f"{source.key}: response is not a PDF")
            actual = digest.hexdigest()
            if actual != source.sha256:
                raise ValueError(f"{source.key}: SHA-256 mismatch ({actual})")
            temporary.replace(destination)
            return destination
        except (OSError, ValueError) as exc:
            temporary.unlink(missing_ok=True)
            if attempt == retries:
                raise RuntimeError(f"failed to download verified source {source.key}") from exc
            time.sleep(2 ** (attempt - 1))
    raise AssertionError("unreachable")


def parse_official_pdf(source: OfficialSource, content: bytes, settings: Settings) -> ParsedDocument:
    parsed = parse_bytes(
        source.filename,
        content,
        declared_mime="application/pdf",
        ocr_enabled=False,
        max_image_pixels=settings.max_image_pixels,
        max_archive_entries=settings.max_archive_entries,
        max_archive_uncompressed_bytes=settings.max_archive_uncompressed_bytes,
        max_archive_entry_bytes=settings.max_archive_entry_bytes,
        max_archive_compression_ratio=settings.max_archive_compression_ratio,
        max_pdf_pages=min(settings.max_pdf_pages, 300),
    )
    normalized_elements = tuple(
        replace(
            element,
            text=re.sub(r"\s+", " ", unicodedata.normalize("NFKC", element.text)).strip(),
        )
        for element in parsed.elements
        if element.text.strip()
    )
    provenance = NormalizedElement(
        modality="text",
        heading="官方来源与使用边界",
        text="\n".join(
            (
                f"# {source.title}",
                f"发布机构：{source.publisher}",
                f"发布日期：{source.published_at}",
                f"资料类别：{source.category}",
                f"官方原文：{source.url}",
                f"固定文件 SHA-256：{source.sha256}",
                "来源等级：中国政府部门公开资料。",
                "安全说明：仅供知识检索与教育测试；不能替代临床诊断、治疗或合规意见。",
            )
        ),
        metadata={"format": "provenance", "trust_tier": source.trust_tier},
    )
    result = replace(parsed, elements=(provenance, *normalized_elements))
    if not result.content.strip():
        raise ValueError(f"{source.key}: PDF produced no searchable text")
    if len(result.content) > 200_000:
        raise ValueError(f"{source.key}: extracted text exceeds the document content limit")
    return result


def import_sources(
    settings: Settings,
    sources: tuple[OfficialSource, ...],
    files: dict[str, Path],
    *,
    tenant_id: str,
) -> tuple[int, int, int]:
    initialize(settings.database_path)
    existing_kbs = knowledge_bases.list_all(settings.database_path, tenant_id)
    kb = next((item for item in existing_kbs if item.name == KB_NAME), None)
    if kb is None:
        kb = knowledge_bases.create(
            settings.database_path,
            tenant_id,
            KnowledgeBaseCreate(
                name=KB_NAME,
                description="国家卫健委、国务院与国家药监局公开中文指南、法规和标准；文件哈希固定",
            ),
        )
    existing_documents = documents.list_for_kb(settings.database_path, tenant_id, kb.id) or []
    by_hash = {document.sha256: document for document in existing_documents}
    by_title = {document.title: document for document in existing_documents}
    by_source = {document.source: document for document in existing_documents}
    created = skipped = 0
    for source in sources:
        stored = by_hash.get(source.sha256)
        if stored is not None:
            if stored.title != source.title or stored.source != source.url:
                documents.update(
                    settings.database_path,
                    settings,
                    tenant_id,
                    stored.id,
                    DocumentUpdate(title=source.title, source=source.url),
                )
            skipped += 1
            continue
        conflict = by_source.get(source.url) or by_title.get(source.title)
        if conflict is not None:
            raise RuntimeError(
                f"{source.key}: existing official document has a different SHA-256; "
                "review and supersede it explicitly"
            )
        content = files[source.key].read_bytes()
        if hashlib.sha256(content).hexdigest() != source.sha256:
            raise RuntimeError(f"{source.key}: local source SHA-256 does not match the catalog")
        parsed = parse_official_pdf(source, content, settings)
        document, duplicate = documents.create_from_parsed(
            settings.database_path, settings, tenant_id, kb.id, parsed
        )
        if document is None:
            raise RuntimeError(f"knowledge base {kb.id} disappeared during import")
        documents.update(
            settings.database_path,
            settings,
            tenant_id,
            document.id,
            DocumentUpdate(title=source.title, source=source.url),
        )
        created += int(not duplicate)
        skipped += int(duplicate)
    return kb.id, created, skipped


def write_manifest(
    output_dir: Path, sources: tuple[OfficialSource, ...], files: dict[str, Path], kb_id: int
) -> Path:
    payload = {
        "name": "Official Chinese medical and medical-device source snapshot",
        "accessed_at": datetime.now(UTC).isoformat(),
        "knowledge_base_id": kb_id,
        "language": "zh-CN",
        "source_count": len(sources),
        "sources": [
            {
                **asdict(source),
                "local_path": str(files[source.key]),
                "local_bytes": files[source.key].stat().st_size,
            }
            for source in sources
        ],
        "distribution_note": "Downloaded source binaries are ignored by Git and remain local.",
        "safety_note": "Knowledge retrieval and education only; not clinical decision support.",
    }
    path = output_dir / "sources.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="hospital-a")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--database", type=Path, help="Override DATABASE_URL for this import")
    args = parser.parse_args()

    sources = load_catalog(args.catalog.resolve())
    output_dir = args.output_dir.resolve()
    files: dict[str, Path] = {}
    total = 0
    for source in sources:
        destination = output_dir / "raw" / source.filename
        files[source.key] = download_source(source, destination)
        total += destination.stat().st_size
        if total > MAX_TOTAL_BYTES:
            raise RuntimeError(f"official snapshot exceeds {MAX_TOTAL_BYTES} total bytes")

    settings = Settings.from_env()
    if args.database:
        settings = replace(settings, database_path=args.database.resolve())
    kb_id, created, skipped = import_sources(settings, sources, files, tenant_id=args.tenant)
    manifest = write_manifest(output_dir, sources, files, kb_id)
    print(
        f"knowledge_base_id={kb_id} sources={len(sources)} created={created} "
        f"skipped={skipped} manifest={manifest}"
    )


if __name__ == "__main__":
    main()
