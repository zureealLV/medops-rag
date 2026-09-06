# MedOps Multimodal RAG V2 — Engineering Design

Status: `alpha.1` implementation in progress on `feat/multimodal-rag-v2`.

## 1. Product boundary

The project remains an educational assistant for **synthetic hospital IT operations material**. It does not
process patient records, diagnose, prescribe, or execute system-changing tools.

V2 must support two distinct meanings that are often incorrectly collapsed into “multimodal RAG”:

1. **Multiformat ingestion** — TXT, Markdown, PDF, DOCX, PPTX, PNG, JPEG, and WebP enter one normalized
   element model. Implemented in alpha.1.
2. **Image-grounded retrieval and answering** — charts, screenshots, diagrams, and scanned pages remain
   first-class evidence with visual embeddings/description and region citations. OCR-only ingestion is not
   sufficient for this claim. Planned for alpha.2–beta.1.

Alpha.1 therefore makes the honest claim **multiformat + OCR multimodal ingestion**, not yet full visual
question answering.

## 2. Quality attributes

| Attribute | Engineering rule | Verification |
| --- | --- | --- |
| Grounding | An answer may cite only persisted evidence returned by tenant-scoped retrieval | citation and cross-tenant tests |
| Traceability | Every element retains modality, source, page/slide, heading, and parser metadata | `GET /documents/{id}/elements` |
| Idempotency | Identical bytes in the same tenant/KB resolve to one document | partial unique index + upload test |
| Failure visibility | Parse/OCR warnings are stored; no-text input is not silently accepted | stable error codes and warning list |
| Local reproducibility | Core OCR and retrieval work without an external API key | ONNX Runtime and deterministic tests |
| Benchmarkability | Every retrieval choice is an explicit strategy and has a versioned report | `evals/benchmark_*.py` |
| Security | Untrusted files are bounded by byte/pixel limits and tenant filtering occurs before ranking | negative/API/security tests |

## 3. Target architecture

```text
Upload API
  -> bounded streaming upload
  -> signature/MIME validation
  -> ingestion_jobs (idempotency key, state, attempt, progress)
  -> parser registry
       text/markdown
       PDF native text + conditional rendered-page OCR
       DOCX paragraphs + tables + embedded-image OCR
       PPTX text + tables + picture OCR
       raster image OCR
  -> normalized document_elements
  -> source artifacts (object storage / local development store)
  -> parent-child chunk builder
  -> text dense + sparse index
  -> image embedding / VLM description index

Query API
  -> tenant and knowledge-base scope
  -> query classifier (text-only / visual / low-confidence / summary)
  -> BM25 + dense text retrieval
  -> optional image retrieval
  -> RRF/DBSF fusion
  -> bounded CrossEncoder/VLM reranking
  -> parent context reconstruction
  -> prompt-injection quarantine
  -> grounded generation or abstention
  -> text/page/region citations + pipeline trace
```

## 4. Implemented alpha.1 components

### 4.1 Parser boundary

`app/ingestion/parsers.py` returns `ParsedDocument` containing immutable `NormalizedElement` values.
Each element has:

- `modality`: `text`, `table`, or `image_ocr`;
- `text`: searchable normalized content;
- `page_number`: PDF page or PPTX slide when known;
- `heading`: nearest DOCX heading when known;
- `metadata`: parser-specific data such as shape index, image dimensions, and OCR confidence.

The rest of the application does not import PDF, DOCX, or PPTX object models. Replacing a parser therefore
does not change retrieval or API contracts.

### 4.2 Conditional OCR

- Raster images always use RapidOCR when OCR is enabled.
- DOCX/PPTX embedded pictures are OCR'd and stored as `image_ocr` elements.
- PDF uses native text extraction first. A page is rendered at 2x scale and OCR'd only when native text has
  fewer than 24 characters.
- Image inputs are decoded and checked against `MAX_IMAGE_PIXELS` before OCR.
- `OCR_MIN_CONFIDENCE` filters low-confidence lines.

This policy is data-driven: on the current CPU, native PDF steady-state median parsing was about **1.2 ms**,
while OCR-backed image/scanned-page ingestion was about **1.35–1.65 s**. Always applying OCR would therefore
add roughly three orders of magnitude of avoidable latency to native text pages on this fixture.

### 4.3 Persistence

Existing `documents` rows are migrated in place with:

- canonical MIME type;
- SHA-256 content identity;
- parser name and ingestion status;
- persisted warning JSON.

`document_elements` stores normalized provenance. A partial unique index over
`(tenant_id, knowledge_base_id, sha256)` applies only when SHA-256 is non-empty, preserving old manual rows
while making byte uploads idempotent.

### 4.4 Retrieval strategy surface

`POST /search` now accepts:

- `keyword`: legacy token overlap;
- `vector`: deterministic hashing-vector baseline;
- `weighted`: legacy normalized weighted baseline;
- `bm25`: Okapi BM25;
- `rrf`: rank fusion of BM25 and the hashing-vector baseline.

All results expose keyword, vector, and normalized BM25 component scores. The default remains `weighted`
for backward compatibility until a harder versioned corpus justifies a migration.

## 5. Technology decisions

### 5.1 PDF: pypdf + pypdfium2, not PyMuPDF as the default

| Candidate | Strength | Cost/risk | Decision |
| --- | --- | --- | --- |
| pypdf + pypdfium2 | permissive licenses, native text plus reliable CPU page rendering | two libraries and a normalization boundary | selected |
| PyMuPDF | very convenient text/image/table APIs and fast rendering | AGPL/commercial licensing requires a deliberate distribution decision | keep as an optional experiment |
| Unstructured | broad type coverage and rich elements | much larger dependency and service surface; parser behavior must still be benchmarked | compare later on adversarial PDFs |

The current generated native-PDF fixture has a ~1.2 ms median after import warm-up. The meaningful next
comparison is extraction correctness on multi-column, table, mixed-font, and scanned PDFs, not only speed.

### 5.2 OCR: RapidOCR ONNX, not a system Tesseract dependency

RapidOCR was selected because it runs through the Python environment and ONNX Runtime on Windows without a
separate executable. Tesseract was not installed on the development host, so choosing it would make the
quick-start path non-reproducible. The current warm CPU cost is ~1.46 s for a 1000x220 fixture, which is too
expensive for the request thread at scale; beta moves OCR to an ingestion worker.

### 5.3 Retrieval: do not copy “BM25 + Dense + RRF + BGE” blindly

On the current 25-question/6-document synthetic corpus:

- BM25: Hit@1 `1.00`, MRR@5 `1.00`, mean query scoring ~`0.4 ms`;
- multilingual MiniLM dense: Hit@1 `0.88`, MRR@5 `0.928`, mean ~`124 ms`;
- BM25 + MiniLM RRF: Hit@1 `0.96`, MRR@5 `0.9733`, mean ~`124 ms`;
- BGE reranking of the fused Top-10: Hit@1 `1.00`, MRR@5 `1.00`, mean ~`1.20 s`.

This corpus is lexical and tiny, so BM25 already saturates it. The result **does not prove dense retrieval is
bad**; it proves the current dataset cannot justify paying 124–1200 ms for the extra stages. A harder V2 set
with paraphrases, ambiguous terms, distractors, tables, OCR noise, and visual questions is required before
enabling dense retrieval/reranking by default.

### 5.4 Storage: keep SQLite for the alpha, benchmark before adding Chroma/Qdrant

The alpha corpus is small enough for exact in-process scoring and SQLite provenance. Adding a vector DB now
would change operational complexity without improving this benchmark. The beta decision gate is:

1. build a versioned corpus with at least 1,000 chunks and tenant filters;
2. compare SQLite exact scan, Chroma, and Qdrant local/server mode;
3. measure index time, p50/p95 query latency, recall against exact Top-K, disk size, and filtered-query
   behavior;
4. select Qdrant if named dense/sparse/image vectors and server-side fusion materially simplify the product;
5. otherwise keep the smaller local stack.

Qdrant is the leading beta candidate because its query API supports multiple named vectors, prefetch, RRF,
and DBSF. It is not selected merely because it is fashionable.

## 6. Planned data model

```text
documents
  id, tenant_id, knowledge_base_id, sha256, mime_type, parser,
  ingest_status, warning_json, created_at, updated_at

document_elements
  id, document_id, element_index, modality, text,
  page_number, heading, bbox_json, artifact_id, metadata_json

artifacts
  id, tenant_id, sha256, media_type, storage_uri, width, height, bytes

parent_chunks
  id, document_id, element_start, element_end, text, token_count

child_chunks
  id, parent_id, modality, text, embedding_model, embedding_json

ingestion_jobs
  id, tenant_id, idempotency_key, state, progress, attempt,
  error_code, created_at, started_at, completed_at
```

The alpha schema contains `documents`, `document_elements`, and legacy `chunks`. Parent/child chunks,
artifacts, and jobs must be migrations, not destructive table rewrites.

## 7. API evolution

### Implemented

- `POST /knowledge-bases/{kb_id}/documents/upload`
  - bounded by `MAX_UPLOAD_BYTES`;
  - returns `201` for a new byte identity and `200` for a deduplicated upload;
  - supports eight suffixes and returns stable parse/OCR errors.
- `GET /documents/{document_id}/elements`
  - tenant-scoped normalized provenance.
- `POST /search`
  - explicit retrieval `strategy` and component scores.

### Planned

- `POST /knowledge-bases/{kb_id}/ingestion-jobs` -> `202 + job_id`;
- `GET /ingestion-jobs/{job_id}` -> state/progress/warnings;
- `POST /search/compare` -> shadow multiple strategies without affecting answers;
- `POST /answer` -> `retrieval_profile`, visual evidence, pipeline trace ID;
- `POST /summary-jobs` -> map/reduce background summary with partial results.

## 8. Failure model

| Failure | Required behavior |
| --- | --- |
| unsupported or malformed file | stable 4xx code; no document row |
| image exceeds pixel budget | reject before OCR |
| OCR returns no text | 422 for image-only input; warning when native text remains |
| duplicate bytes | reuse same document inside one tenant/KB |
| parser partially succeeds | persist usable elements and warnings |
| embedding/reranker unavailable | fall back to BM25 and record degraded trace |
| one document in batch fails | job becomes `partial`; successful documents remain queryable |
| model generation fails | keep retrieved evidence and use existing offline fallback |

## 9. Security controls

- File extension selects the parser but canonical MIME and parser validation detect malformed containers.
- Upload bytes and decoded image pixels have separate limits.
- Parser output is untrusted data and cannot select tools or change policies.
- Tenant filtering remains in SQL before any chunk enters a model or ranking stage.
- OCR/model caches live under `data/models/` and are excluded from Git.
- Production worker design must use no secrets, restricted network, CPU/memory/time limits, and disposable
  work directories for hostile document parsing.

## 10. Release gates

### alpha.1 — multiformat and measured baselines (implemented this milestone)

- real TXT/MD/PDF/DOCX/PPTX/image parsing;
- OCR for images, office pictures, and scanned PDFs;
- normalized elements, provenance, SHA-256 idempotency;
- retrieval strategy comparison;
- parser and semantic benchmark reports;
- full legacy and new test suite green.

### alpha.2 — first-class multimodal evidence

- artifact store and bounding boxes;
- image embeddings or VLM descriptions behind a provider interface;
- text-to-image retrieval fixture set;
- visual citations that point to page/slide/region;
- image retrieval ablation against OCR-only baseline.

### beta.1 — retrieval quality

- parent-child chunking;
- versioned V2 benchmark with at least 100 questions and adversarial distractors;
- selected dense embedding and optional BGE reranker;
- conditional HyDE only if the held-out set shows a justified gain;
- calibrated abstention and failure taxonomy.

### beta.2 — asynchronous workloads

- persisted ingestion and summary state machines;
- worker isolation, retry, timeout, idempotency, partial completion;
- Map-Reduce multi-document summaries with citations;
- crash/restart recovery tests.

### v2.0 — release

- authenticated identity boundary rather than a demo tenant header;
- load, security, parser-fuzz, and migration tests;
- Docker startup including selected index/worker services;
- reproducible benchmark command and published limitations.
