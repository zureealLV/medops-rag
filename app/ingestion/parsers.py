"""Parser registry for text, office, PDF, and raster-image inputs.

The boundary deliberately emits one normalized element model. Retrieval and
persistence never need to understand a DOCX relationship or a PPTX shape.
"""

from __future__ import annotations

import csv
import hashlib
import json
import threading
import zipfile
from dataclasses import dataclass, field
from functools import lru_cache
from io import BytesIO, StringIO
from pathlib import Path
from typing import Literal

from app.exceptions import AppError

Modality = Literal["text", "table", "image_ocr"]
SUPPORTED_SUFFIXES = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".jsonl",
    ".pdf",
    ".docx",
    ".pptx",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}
MIME_BY_SUFFIX = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


@dataclass(frozen=True, slots=True)
class NormalizedElement:
    modality: Modality
    text: str
    page_number: int | None = None
    heading: str | None = None
    artifact_sha256: str | None = None
    bbox: dict[str, str | int | float] | None = None
    metadata: dict[str, str | int | float | bool | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParsedArtifact:
    sha256: str
    mime_type: str
    content: bytes
    width: int
    height: int
    page_number: int | None = None
    bbox: dict[str, str | int | float] | None = None
    ocr_text: str = ""
    metadata: dict[str, str | int | float | bool | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    filename: str
    mime_type: str
    parser: str
    sha256: str
    elements: tuple[NormalizedElement, ...]
    artifacts: tuple[ParsedArtifact, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def content(self) -> str:
        return "\n\n".join(element.text.strip() for element in self.elements if element.text.strip())


_ocr_lock = threading.Lock()


@lru_cache(maxsize=1)
def _ocr_engine():
    from rapidocr import RapidOCR

    return RapidOCR()


def _validate_image(content: bytes, max_image_pixels: int) -> tuple[int, int]:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(BytesIO(content)) as image:
            width, height = image.size
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise AppError(400, "invalid_image", "Uploaded image cannot be decoded") from exc
    if width * height > max_image_pixels:
        raise AppError(413, "image_too_large", f"Image exceeds {max_image_pixels} pixels")
    return width, height


def _ocr_image(
    content: bytes,
    *,
    mime_type: str,
    page_number: int | None,
    min_confidence: float,
    max_image_pixels: int,
    bbox: dict[str, str | int | float] | None = None,
    metadata: dict[str, str | int | float | bool | None] | None = None,
) -> tuple[NormalizedElement | None, ParsedArtifact]:
    width, height = _validate_image(content, max_image_pixels)
    with _ocr_lock:
        result = _ocr_engine()(content)
    accepted = [
        (text.strip(), float(score))
        for text, score in zip(result.txts or (), result.scores or (), strict=False)
        if text.strip() and float(score) >= min_confidence
    ]
    lines = [text for text, _ in accepted]
    scores = [score for _, score in accepted]
    details = {"width": width, "height": height, "ocr_engine": "RapidOCR"}
    if scores:
        details["ocr_mean_confidence"] = round(sum(scores) / len(scores), 4)
    if metadata:
        details.update(metadata)
    digest = hashlib.sha256(content).hexdigest()
    ocr_text = "\n".join(lines)
    artifact = ParsedArtifact(
        sha256=digest,
        mime_type=mime_type,
        content=content,
        width=width,
        height=height,
        page_number=page_number,
        bbox=bbox,
        ocr_text=ocr_text,
        metadata=dict(details),
    )
    if not ocr_text:
        return None, artifact
    return (
        NormalizedElement(
            modality="image_ocr",
            text=ocr_text,
            page_number=page_number,
            artifact_sha256=digest,
            bbox=bbox,
            metadata=details,
        ),
        artifact,
    )


def _image_without_ocr(
    content: bytes,
    *,
    mime_type: str,
    page_number: int | None,
    max_image_pixels: int,
    bbox: dict[str, str | int | float] | None = None,
    metadata: dict[str, str | int | float | bool | None] | None = None,
) -> ParsedArtifact:
    width, height = _validate_image(content, max_image_pixels)
    return ParsedArtifact(
        sha256=hashlib.sha256(content).hexdigest(),
        mime_type=mime_type,
        content=content,
        width=width,
        height=height,
        page_number=page_number,
        bbox=bbox,
        metadata=dict(metadata or {}),
    )


def _decode_text(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError(400, "invalid_encoding", "Text documents must use UTF-8") from exc


def _preflight_office_archive(
    content: bytes,
    *,
    kind: str,
    max_entries: int,
    max_uncompressed_bytes: int,
    max_entry_bytes: int,
    max_compression_ratio: float,
) -> None:
    """Inspect ZIP metadata before any Office XML or media is decompressed."""
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
    except (zipfile.BadZipFile, OSError) as exc:
        raise AppError(400, f"invalid_{kind}", f"{kind.upper()} package cannot be parsed") from exc
    if len(entries) > max_entries:
        raise AppError(413, "archive_limit_exceeded", "Office package contains too many entries")

    total_uncompressed = 0
    for entry in entries:
        normalized = entry.filename.replace("\\", "/")
        path_parts = normalized.split("/")
        if (
            not normalized
            or normalized.startswith("/")
            or "\x00" in normalized
            or any(part == ".." for part in path_parts)
        ):
            raise AppError(400, "unsafe_archive", "Office package contains an unsafe entry path")
        if entry.flag_bits & 0x1:
            raise AppError(400, "unsafe_archive", "Encrypted Office entries are not accepted")
        if normalized.lower().endswith("vbaproject.bin"):
            raise AppError(400, "unsafe_archive", "Macro-enabled Office packages are not accepted")
        if entry.file_size > max_entry_bytes:
            raise AppError(413, "archive_limit_exceeded", "Office package entry is too large")
        total_uncompressed += entry.file_size
        if total_uncompressed > max_uncompressed_bytes:
            raise AppError(413, "archive_limit_exceeded", "Office package expands beyond the limit")
        compressed_size = max(entry.compress_size, 1)
        ratio = entry.file_size / compressed_size
        if entry.file_size >= 1_000_000 and ratio > max_compression_ratio:
            raise AppError(413, "archive_limit_exceeded", "Office package compression ratio is unsafe")


def _parse_text(
    content: bytes, suffix: str
) -> tuple[list[NormalizedElement], list[str], list[ParsedArtifact]]:
    text = _decode_text(content)
    elements = [
        NormalizedElement(modality="text", text=part.strip(), metadata={"format": suffix[1:]})
        for part in text.replace("\r\n", "\n").replace("\r", "\n").split("\n\n")
        if part.strip()
    ]
    return elements, [], []


def _stringify_structured_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _records_to_elements(
    records: list[object], *, source_format: str
) -> tuple[list[NormalizedElement], list[str], list[ParsedArtifact]]:
    elements: list[NormalizedElement] = []
    for row_number, record in enumerate(records, start=1):
        if isinstance(record, dict):
            text = " | ".join(f"{key}: {_stringify_structured_value(value)}" for key, value in record.items())
            modality: Modality = "table"
        else:
            text = _stringify_structured_value(record)
            modality = "text"
        if text.strip():
            elements.append(
                NormalizedElement(
                    modality=modality,
                    text=text,
                    metadata={"format": source_format, "row_number": row_number},
                )
            )
    return elements, [], []


def _parse_csv(
    content: bytes,
) -> tuple[list[NormalizedElement], list[str], list[ParsedArtifact]]:
    text = _decode_text(content)
    try:
        sample = text[:8192]
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        reader = csv.DictReader(StringIO(text), dialect=dialect)
        if not reader.fieldnames:
            raise ValueError("missing header")
        records = [dict(row) for row in reader]
    except (csv.Error, ValueError) as exc:
        raise AppError(400, "invalid_csv", "CSV must contain a readable header row") from exc
    if not records:
        raise AppError(422, "no_extractable_content", "CSV contains no data rows")
    return _records_to_elements(records, source_format="csv")


def _parse_json(
    content: bytes, *, json_lines: bool
) -> tuple[list[NormalizedElement], list[str], list[ParsedArtifact]]:
    text = _decode_text(content)
    try:
        if json_lines:
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            payload = json.loads(text)
            records = payload if isinstance(payload, list) else [payload]
    except json.JSONDecodeError as exc:
        code = "invalid_jsonl" if json_lines else "invalid_json"
        label = "JSONL" if json_lines else "JSON"
        raise AppError(400, code, f"{label} cannot be decoded") from exc
    if not records:
        raise AppError(422, "no_extractable_content", "Structured document contains no records")
    return _records_to_elements(records, source_format="jsonl" if json_lines else "json")


def _parse_docx(
    content: bytes,
    *,
    ocr: bool,
    min_confidence: float,
    max_image_pixels: int,
    max_archive_entries: int,
    max_archive_uncompressed_bytes: int,
    max_archive_entry_bytes: int,
    max_archive_compression_ratio: float,
) -> tuple[list[NormalizedElement], list[str], list[ParsedArtifact]]:
    from docx import Document as WordDocument

    _preflight_office_archive(
        content,
        kind="docx",
        max_entries=max_archive_entries,
        max_uncompressed_bytes=max_archive_uncompressed_bytes,
        max_entry_bytes=max_archive_entry_bytes,
        max_compression_ratio=max_archive_compression_ratio,
    )
    try:
        document = WordDocument(BytesIO(content))
    except Exception as exc:
        raise AppError(400, "invalid_docx", "DOCX package cannot be parsed") from exc
    elements: list[NormalizedElement] = []
    artifacts: list[ParsedArtifact] = []
    warnings: list[str] = []
    heading: str | None = None
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style_name = paragraph.style.name if paragraph.style else ""
        if style_name.lower().startswith("heading"):
            heading = text
        elements.append(
            NormalizedElement(modality="text", text=text, heading=heading, metadata={"style": style_name})
        )
    for table_index, table in enumerate(document.tables, start=1):
        rows = [[cell.text.strip().replace("\n", " ") for cell in row.cells] for row in table.rows]
        text = "\n".join(" | ".join(cells) for cells in rows if any(cells))
        if text:
            elements.append(
                NormalizedElement(
                    modality="table", text=text, heading=heading, metadata={"table_index": table_index}
                )
            )
    seen_hashes: set[str] = set()
    for relationship in document.part.rels.values():
        part = getattr(relationship, "target_part", None)
        blob = getattr(part, "blob", None)
        content_type = getattr(part, "content_type", "")
        if not blob or not str(content_type).startswith("image/"):
            continue
        digest = hashlib.sha256(blob).hexdigest()
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        try:
            if not ocr:
                artifacts.append(
                    _image_without_ocr(
                        blob,
                        mime_type=str(content_type),
                        page_number=None,
                        max_image_pixels=max_image_pixels,
                        metadata={"container": "docx"},
                    )
                )
                continue
            element, artifact = _ocr_image(
                blob,
                mime_type=str(content_type),
                page_number=None,
                min_confidence=min_confidence,
                max_image_pixels=max_image_pixels,
                metadata={"container": "docx"},
            )
            artifacts.append(artifact)
            if element:
                elements.append(element)
        except AppError as exc:
            warnings.append(f"docx image skipped: {exc.code}")
    return elements, warnings, artifacts


def _parse_pptx(
    content: bytes,
    *,
    ocr: bool,
    min_confidence: float,
    max_image_pixels: int,
    max_archive_entries: int,
    max_archive_uncompressed_bytes: int,
    max_archive_entry_bytes: int,
    max_archive_compression_ratio: float,
) -> tuple[list[NormalizedElement], list[str], list[ParsedArtifact]]:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    _preflight_office_archive(
        content,
        kind="pptx",
        max_entries=max_archive_entries,
        max_uncompressed_bytes=max_archive_uncompressed_bytes,
        max_entry_bytes=max_archive_entry_bytes,
        max_compression_ratio=max_archive_compression_ratio,
    )
    try:
        presentation = Presentation(BytesIO(content))
    except Exception as exc:
        raise AppError(400, "invalid_pptx", "PPTX package cannot be parsed") from exc
    elements: list[NormalizedElement] = []
    artifacts: list[ParsedArtifact] = []
    warnings: list[str] = []
    for slide_number, slide in enumerate(presentation.slides, start=1):
        for shape_index, shape in enumerate(slide.shapes, start=1):
            shape_bbox = {
                "unit": "emu",
                "x": int(shape.left),
                "y": int(shape.top),
                "width": int(shape.width),
                "height": int(shape.height),
            }
            if getattr(shape, "has_text_frame", False):
                text = shape.text.strip()
                if text:
                    elements.append(
                        NormalizedElement(
                            modality="text",
                            text=text,
                            page_number=slide_number,
                            bbox=shape_bbox,
                            metadata={"shape_index": shape_index},
                        )
                    )
            if getattr(shape, "has_table", False):
                rows = [
                    [cell.text.strip().replace("\n", " ") for cell in row.cells] for row in shape.table.rows
                ]
                text = "\n".join(" | ".join(cells) for cells in rows if any(cells))
                if text:
                    elements.append(
                        NormalizedElement(
                            modality="table",
                            text=text,
                            page_number=slide_number,
                            bbox=shape_bbox,
                            metadata={"shape_index": shape_index},
                        )
                    )
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                try:
                    if not ocr:
                        artifacts.append(
                            _image_without_ocr(
                                shape.image.blob,
                                mime_type=shape.image.content_type,
                                page_number=slide_number,
                                max_image_pixels=max_image_pixels,
                                bbox=shape_bbox,
                                metadata={"container": "pptx", "shape_index": shape_index},
                            )
                        )
                        continue
                    element, artifact = _ocr_image(
                        shape.image.blob,
                        mime_type=shape.image.content_type,
                        page_number=slide_number,
                        min_confidence=min_confidence,
                        max_image_pixels=max_image_pixels,
                        bbox=shape_bbox,
                        metadata={"container": "pptx", "shape_index": shape_index},
                    )
                    artifacts.append(artifact)
                    if element:
                        elements.append(element)
                except AppError as exc:
                    warnings.append(f"pptx image on slide {slide_number} skipped: {exc.code}")
    return elements, warnings, artifacts


def _render_pdf_page(content: bytes, page_index: int) -> bytes:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(content)
    try:
        bitmap = document[page_index].render(scale=2.0)
        image = bitmap.to_pil()
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
    finally:
        document.close()


def _parse_pdf(
    content: bytes,
    *,
    ocr: bool,
    min_confidence: float,
    max_image_pixels: int,
    max_pdf_pages: int,
) -> tuple[list[NormalizedElement], list[str], list[ParsedArtifact]]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(content))
    except Exception as exc:
        raise AppError(400, "invalid_pdf", "PDF cannot be parsed") from exc
    if len(reader.pages) > max_pdf_pages:
        raise AppError(413, "pdf_page_limit_exceeded", f"PDF exceeds {max_pdf_pages} pages")
    elements: list[NormalizedElement] = []
    artifacts: list[ParsedArtifact] = []
    warnings: list[str] = []
    for page_number, page in enumerate(reader.pages, start=1):
        page_bbox = {
            "unit": "pdf-point",
            "x": float(page.mediabox.left),
            "y": float(page.mediabox.bottom),
            "width": float(page.mediabox.width),
            "height": float(page.mediabox.height),
        }
        try:
            text = (page.extract_text() or "").strip()
        except Exception as exc:
            text = ""
            warnings.append(f"pdf page {page_number} text extraction failed: {type(exc).__name__}")
        if text:
            elements.append(
                NormalizedElement(
                    modality="text",
                    text=text,
                    page_number=page_number,
                    bbox=page_bbox,
                    metadata={"format": "pdf"},
                )
            )
        if ocr and len(text) < 24:
            try:
                estimated_pixels = int(float(page.mediabox.width) * float(page.mediabox.height) * 4)
                if estimated_pixels > max_image_pixels:
                    raise AppError(
                        413,
                        "pdf_render_too_large",
                        f"Rendered PDF page exceeds {max_image_pixels} pixels",
                    )
                rendered = _render_pdf_page(content, page_number - 1)
                element, artifact = _ocr_image(
                    rendered,
                    mime_type="image/png",
                    page_number=page_number,
                    min_confidence=min_confidence,
                    max_image_pixels=max_image_pixels,
                    bbox=page_bbox,
                    metadata={"container": "pdf", "rendered_page": True},
                )
                artifacts.append(artifact)
                if element:
                    elements.append(element)
                elif not text:
                    warnings.append(f"pdf page {page_number} produced no OCR text")
            except AppError:
                raise
            except Exception as exc:
                warnings.append(f"pdf page {page_number} OCR failed: {type(exc).__name__}")
    return elements, warnings, artifacts


def _parse_image(
    content: bytes,
    *,
    mime_type: str,
    ocr: bool,
    min_confidence: float,
    max_image_pixels: int,
) -> tuple[list[NormalizedElement], list[str], list[ParsedArtifact]]:
    width, height = _validate_image(content, max_image_pixels)
    image_bbox = {"unit": "pixel", "x": 0, "y": 0, "width": width, "height": height}
    if not ocr:
        artifact = _image_without_ocr(
            content,
            mime_type=mime_type,
            page_number=1,
            max_image_pixels=max_image_pixels,
            bbox=image_bbox,
            metadata={"container": "image"},
        )
        return [], [], [artifact]
    element, artifact = _ocr_image(
        content,
        mime_type=mime_type,
        page_number=1,
        min_confidence=min_confidence,
        max_image_pixels=max_image_pixels,
        bbox=image_bbox,
        metadata={"container": "image"},
    )
    return (
        [element] if element else [],
        [] if element else ["image produced no OCR text"],
        [artifact],
    )


def parse_bytes(
    filename: str,
    content: bytes,
    declared_mime: str | None = None,
    *,
    ocr_enabled: bool = True,
    ocr_min_confidence: float = 0.50,
    max_image_pixels: int = 25_000_000,
    max_archive_entries: int = 2_048,
    max_archive_uncompressed_bytes: int = 50_000_000,
    max_archive_entry_bytes: int = 20_000_000,
    max_archive_compression_ratio: float = 200.0,
    max_pdf_pages: int = 200,
) -> ParsedDocument:
    safe_name = Path(filename).name or "upload"
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise AppError(400, "unsupported_document", f"Supported document types: {supported}")
    if not content:
        raise AppError(400, "empty_document", "Uploaded document is empty")

    parser_name = suffix.removeprefix(".")
    if suffix in {".txt", ".md"}:
        elements, warnings, artifacts = _parse_text(content, suffix)
    elif suffix == ".csv":
        elements, warnings, artifacts = _parse_csv(content)
    elif suffix in {".json", ".jsonl"}:
        elements, warnings, artifacts = _parse_json(content, json_lines=suffix == ".jsonl")
    elif suffix == ".docx":
        elements, warnings, artifacts = _parse_docx(
            content,
            ocr=ocr_enabled,
            min_confidence=ocr_min_confidence,
            max_image_pixels=max_image_pixels,
            max_archive_entries=max_archive_entries,
            max_archive_uncompressed_bytes=max_archive_uncompressed_bytes,
            max_archive_entry_bytes=max_archive_entry_bytes,
            max_archive_compression_ratio=max_archive_compression_ratio,
        )
    elif suffix == ".pptx":
        elements, warnings, artifacts = _parse_pptx(
            content,
            ocr=ocr_enabled,
            min_confidence=ocr_min_confidence,
            max_image_pixels=max_image_pixels,
            max_archive_entries=max_archive_entries,
            max_archive_uncompressed_bytes=max_archive_uncompressed_bytes,
            max_archive_entry_bytes=max_archive_entry_bytes,
            max_archive_compression_ratio=max_archive_compression_ratio,
        )
    elif suffix == ".pdf":
        elements, warnings, artifacts = _parse_pdf(
            content,
            ocr=ocr_enabled,
            min_confidence=ocr_min_confidence,
            max_image_pixels=max_image_pixels,
            max_pdf_pages=max_pdf_pages,
        )
    else:
        elements, warnings, artifacts = _parse_image(
            content,
            mime_type=MIME_BY_SUFFIX[suffix],
            ocr=ocr_enabled,
            min_confidence=ocr_min_confidence,
            max_image_pixels=max_image_pixels,
        )
    if not any(element.text.strip() for element in elements) and not artifacts:
        raise AppError(422, "no_extractable_content", "No searchable content could be extracted")

    canonical_mime = MIME_BY_SUFFIX[suffix]
    if declared_mime and declared_mime not in {canonical_mime, "application/octet-stream"}:
        warnings.append(f"declared MIME {declared_mime} did not match extension; used {canonical_mime}")
    return ParsedDocument(
        filename=safe_name,
        mime_type=canonical_mime,
        parser=parser_name,
        sha256=hashlib.sha256(content).hexdigest(),
        elements=tuple(elements),
        artifacts=tuple(artifacts),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def element_metadata_json(element: NormalizedElement) -> str:
    return json.dumps(element.metadata, ensure_ascii=False, sort_keys=True)
