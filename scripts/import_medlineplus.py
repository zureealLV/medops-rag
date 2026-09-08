"""Download and import the official MedlinePlus health-topic corpus.

Raw archives and manifests stay outside Git so imports are reproducible
without redistributing a frequently updated third-party corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

from app.config import Settings
from app.db import initialize
from app.models.documents import DocumentCreate, DocumentUpdate
from app.models.knowledge_bases import KnowledgeBaseCreate
from app.services import documents, knowledge_bases

ROOT = Path(__file__).resolve().parents[1]
INDEX_URL = "https://medlineplus.gov/xml.html"
KB_NAME = "MedlinePlus 健康主题（NLM 官方）"
ARCHIVE_PATTERN = re.compile(
    r"(?:https://medlineplus\.gov)?/xml/mplus_topics_compressed_\d{4}-\d{2}-\d{2}\.zip"
)
MAX_ARCHIVE_BYTES = 20_000_000
MAX_XML_BYTES = 80_000_000


@dataclass(frozen=True, slots=True)
class Topic:
    medlineplus_id: str
    title: str
    url: str
    language: str
    content: str


class _HTMLTextExtractor(HTMLParser):
    BLOCK_TAGS = {"br", "div", "h1", "h2", "h3", "h4", "li", "p", "section", "ul"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        lines = [" ".join(line.split()) for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line)


def _clean_html(value: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(value)
    parser.close()
    return parser.text()


def _values(node: ET.Element, tag: str) -> list[str]:
    return [" ".join("".join(item.itertext()).split()) for item in node.findall(tag) if item.text]


def parse_topics(xml_bytes: bytes, languages: set[str]) -> tuple[list[Topic], str]:
    """Convert bounded official XML into one traceable document per topic."""
    if len(xml_bytes) > MAX_XML_BYTES:
        raise ValueError(f"MedlinePlus XML exceeds the {MAX_XML_BYTES}-byte safety limit")
    root = ET.fromstring(xml_bytes)
    if root.tag != "health-topics":
        raise ValueError("Expected a MedlinePlus health-topics XML document")

    generated_at = root.attrib.get("date-generated", "unknown")
    topics: list[Topic] = []
    for node in root.findall("health-topic"):
        language = node.attrib.get("language", "").strip()
        if language not in languages:
            continue
        title = node.attrib.get("title", "").strip()
        url = node.attrib.get("url", "").strip()
        topic_id = node.attrib.get("id", "").strip()
        summary_node = node.find("full-summary")
        summary = _clean_html(summary_node.text or "") if summary_node is not None else ""
        if not title or not url or not topic_id or not summary:
            continue

        aliases = _values(node, "also-called")
        mesh = _values(node, "mesh-heading")
        groups = _values(node, "group")
        related = _values(node, "related-topic")
        institutes = _values(node, "primary-institute")
        sections = [f"# {title}", f"Language: {language}", f"MedlinePlus topic ID: {topic_id}"]
        if aliases:
            sections.append("Also called: " + "; ".join(dict.fromkeys(aliases)))
        if mesh:
            sections.append("MeSH headings: " + "; ".join(dict.fromkeys(mesh)))
        if groups:
            sections.append("Topic groups: " + "; ".join(dict.fromkeys(groups)))
        if institutes:
            sections.append("Primary NIH institute: " + "; ".join(dict.fromkeys(institutes)))
        sections.extend(["## Summary", summary])
        if related:
            sections.append("Related topics: " + "; ".join(dict.fromkeys(related)))
        sections.extend(
            [
                "## Provenance",
                "Source: MedlinePlus.gov, U.S. National Library of Medicine.",
                f"Topic URL: {url}",
                f"Bulk feed generated: {generated_at}",
                "Safety: educational health information; not a diagnosis or treatment instruction.",
            ]
        )
        topics.append(
            Topic(
                medlineplus_id=topic_id,
                title=title[:200],
                url=url[:300],
                language=language,
                content="\n\n".join(sections)[:200_000],
            )
        )
    return topics, generated_at


def discover_latest_archive(index_url: str = INDEX_URL) -> str:
    request = urllib.request.Request(index_url, headers={"User-Agent": "medops-rag/2.2 corpus importer"})
    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read(2_000_000).decode("utf-8", errors="replace")
    matches = ARCHIVE_PATTERN.findall(html)
    if not matches:
        raise RuntimeError("The MedlinePlus XML page did not expose a compressed topic archive")
    return urllib.parse.urljoin(index_url, matches[0])


def download_archive(url: str, destination: Path, retries: int = 3) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return destination
    temporary = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "medops-rag/2.2 corpus importer"})
            with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES:
                        raise ValueError("MedlinePlus archive exceeded the download safety limit")
                    output.write(chunk)
            temporary.replace(destination)
            return destination
        except (OSError, ValueError) as exc:
            temporary.unlink(missing_ok=True)
            if attempt == retries:
                raise RuntimeError(f"Failed to download MedlinePlus after {retries} attempts") from exc
            time.sleep(2 ** (attempt - 1))
    raise AssertionError("unreachable")


def read_archive(path: Path) -> bytes:
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("MedlinePlus archive exceeds the safety limit")
    with zipfile.ZipFile(path) as archive:
        files = [item for item in archive.infolist() if not item.is_dir()]
        if len(files) != 1 or not files[0].filename.lower().endswith(".xml"):
            raise ValueError("MedlinePlus archive must contain exactly one XML file")
        item = files[0]
        if item.file_size > MAX_XML_BYTES or Path(item.filename).name != item.filename:
            raise ValueError("MedlinePlus archive contains an unsafe XML entry")
        return archive.read(item)


def import_topics(
    settings: Settings,
    topics: list[Topic],
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
                description="NLM 官方 MedlinePlus 健康主题全量 XML；英文/西班牙文，可复现更新",
            ),
        )
    existing = {
        item.source: item
        for item in documents.list_for_kb(settings.database_path, tenant_id, kb.id) or []
    }
    created = updated = skipped = 0
    for topic in topics:
        stored = existing.get(topic.url)
        if stored is None:
            result = documents.create(
                settings.database_path,
                settings,
                tenant_id,
                kb.id,
                DocumentCreate(title=topic.title, source=topic.url, content=topic.content),
            )
            created += int(result is not None)
        elif refresh_existing and (stored.title != topic.title or stored.content != topic.content):
            documents.update(
                settings.database_path,
                settings,
                tenant_id,
                stored.id,
                DocumentUpdate(title=topic.title, content=topic.content),
            )
            updated += 1
        else:
            skipped += 1
    return kb.id, created, updated, skipped


def write_manifest(
    output_dir: Path,
    *,
    archive: Path,
    download_url: str,
    generated_at: str,
    topics: list[Topic],
    kb_id: int,
) -> Path:
    manifest = {
        "name": "MedlinePlus Health Topics XML",
        "publisher": "U.S. National Library of Medicine",
        "index_url": INDEX_URL,
        "download_url": download_url,
        "access_method": "official bulk ZIP/XML",
        "accessed_at": datetime.now(UTC).isoformat(),
        "feed_generated_at": generated_at,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "record_count": len(topics),
        "languages": sorted({topic.language for topic in topics}),
        "knowledge_base_id": kb_id,
        "usage_note": "Attribute the data to MedlinePlus.gov; do not imply NLM endorsement.",
        "safety_note": "Educational information only; not a substitute for professional diagnosis or care.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "sources.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="hospital-a")
    parser.add_argument("--language", action="append", choices=("English", "Spanish"))
    parser.add_argument("--limit", type=int, default=0, help="0 imports every matching topic")
    parser.add_argument("--archive", type=Path, help="Use a previously downloaded official ZIP")
    parser.add_argument("--download-url", help="Override automatic latest-archive discovery")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "external" / "medlineplus")
    parser.add_argument("--database", type=Path, help="Override DATABASE_URL for this import")
    parser.add_argument("--refresh-existing", action="store_true")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be zero or greater")

    output_dir = args.output_dir.resolve()
    if args.archive:
        archive = args.archive.resolve()
        download_url = args.download_url or "local-official-archive"
    else:
        download_url = args.download_url or discover_latest_archive()
        filename = Path(urllib.parse.urlparse(download_url).path).name
        archive = download_archive(download_url, output_dir / "raw" / filename)
    topics, generated_at = parse_topics(read_archive(archive), set(args.language or ["English"]))
    if args.limit:
        topics = topics[: args.limit]
    settings = Settings.from_env()
    if args.database:
        settings = replace(settings, database_path=args.database.resolve())
    kb_id, created, updated, skipped = import_topics(
        settings, topics, tenant_id=args.tenant, refresh_existing=args.refresh_existing
    )
    manifest = write_manifest(
        output_dir,
        archive=archive,
        download_url=download_url,
        generated_at=generated_at,
        topics=topics,
        kb_id=kb_id,
    )
    print(
        f"knowledge_base_id={kb_id} records={len(topics)} created={created} "
        f"updated={updated} skipped={skipped} manifest={manifest}"
    )


if __name__ == "__main__":
    main()
