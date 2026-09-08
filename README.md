# MedOps Multimodal RAG V2.3

[中文说明](README_CN.md) · [Web console](docs/v2/WEB_CONSOLE.md) · [Chinese corpus benchmark](docs/v2/BENCHMARK_REPORT_V2_3_CHINESE.md) · [Engineering design](docs/v2/ENGINEERING_DESIGN.md) · [Authentication](docs/v2/AUTHORIZATION.md) · [Parser safety](docs/v2/PARSER_SECURITY.md) · [Observability](docs/v2/OBSERVABILITY.md) · [Deployment](docs/v2/DEPLOYMENT.md) · [Migration/rollback](docs/v2/MIGRATION_AND_ROLLBACK.md) · [Performance](docs/v2/BENCHMARK_REPORT_PERFORMANCE.md) · [Roadmap](docs/v2/ROADMAP.md) · [Threat model](THREAT_MODEL.md)

An auditable, tenant-scoped multimodal RAG assistant for **public medical knowledge and medical-device evidence**. V2.3 makes Chinese the primary local corpus with 15,000 pinned Huatuo-26M records, keeps the official NLM MedlinePlus bulk importer, and adds SQLite trigram FTS prefiltering for responsive Chinese lexical retrieval. The bright clinical console, source-friendly answer cards, multimodal evidence, structured ingestion, RBAC, parser budgets, metrics, migration/rollback and verified single-host Compose profile remain intact.

> Educational portfolio software, not a medical device. It does not diagnose, prescribe, process real patient records, or execute system-changing tools.

> **Claim boundary:** alpha.2 routes visual questions, retrieves text-free images, and returns stored image evidence. It does not yet claim chart/diagram reasoning or production Chinese cross-modal quality.

## Current capabilities

- a responsive, dependency-free Web console for knowledge spaces, synchronous demo uploads, cited Q&A,
  health and tenant-scoped operational metrics;
- FastAPI application factory, typed routes, dependency injection, stable errors and OpenAPI;
- SQLite transactions, foreign keys, indexes and restart persistence;
- knowledge-base and document CRUD with SHA-256 idempotent uploads;
- durable asynchronous ingestion jobs with tenant-scoped idempotency keys, leases, bounded retries, cancellation and crash recovery;
- an isolated polling worker for parsing, OCR, chunking and embedding outside the API process;
- resumable multi-document Map-Reduce summary jobs with persisted per-document results, final citations,
  partial-failure visibility and a hard 30-second per-model-call timeout;
- TXT/Markdown/PDF/DOCX/PPTX/PNG/JPEG/WebP/CSV/JSON/JSONL parsing with native text, table, structured-row and OCR elements;
- pre-decompression Office archive budgets, unsafe path/macro rejection, PDF page/render caps and a
  deterministic malformed-input regression corpus;
- page/slide/heading provenance and fixed-layout bounding boxes through `GET /documents/{id}/elements`;
- conditional scanned-PDF OCR and embedded-image OCR through RapidOCR/ONNX Runtime;
- tenant-local SHA-256 image BLOB deduplication with page/slide/shape placement metadata;
- `GET /documents/{id}/artifacts`, tenant-scoped original bytes, and hash ETags;
- optional paired CLIP image/text embeddings and `ocr`/`image`/`fusion` visual search;
- automatic `text`/`visual` answer routing, calibrated visual abstention, and retrievable image citations;
- deterministic hashing, keyword, BM25, weighted, and RRF retrieval strategies;
- explicit rewrite, multi-query and deterministic template-HyDE transformations with policy-gated auto HyDE;
- opt-in structure-aware `parent_child` retrieval that matches small children and reconstructs parent context;
- cited extractive answers and evidence-threshold abstention, with natural answer text and numbered source/image cards below it instead of inline implementation locators;
- reproducible import of the official NLM MedlinePlus bulk health-topic XML, with per-topic provenance and a local source manifest;
- bounded, revision-pinned import of 12,000 Chinese medical knowledge-graph QA records and 3,000 Chinese medical encyclopedia QA records from Huatuo-26M;
- tenant- and knowledge-base-scoped SQLite FTS5 trigram candidate retrieval before in-process BM25 reranking;
- optional OpenAI-compatible generation with timeout, bounded retry and offline fallback;
- tenant filtering in SQL before retrieval/model context;
- optional scrypt-hashed API keys, immediate revocation, server-bound tenancy and viewer/editor/admin roles;
- indirect prompt-injection quarantine, PII-safe audit data and medical-advice denial;
- three read-only tools: `search_documents`, `get_document_metadata`, `get_system_status`;
- request IDs, `Server-Timing`, tenant-scoped request/queue/pipeline metrics, 97 API/security/parser/migration/job/UI tests and repeatable ingestion/retrieval benchmarks;
- backup-first V1-to-V2 migration, explicit schema versioning and a tested full-database rollback path;
- a verified Docker Compose image with API, ingestion worker, summary worker, health checks and persistent
  data/model volumes;
- two idempotent starter knowledge bases for clinical fundamentals and medical-device safety, derived from public FDA, CDC, WHO and MedlinePlus material and kept strictly educational.

## Quick start (Windows / PowerShell)

Requires Python 3.11+.

```powershell
git clone https://github.com/zureealLV/medops-rag.git
cd medops-rag
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe .\scripts\seed_sample_data.py --profile medical
.\.venv\Scripts\python.exe -m scripts.import_huatuo
.\.venv\Scripts\python.exe -m scripts.import_medlineplus
.\.venv\Scripts\fastapi.exe dev
```

The Huatuo command imports the default Chinese-first 15,000-record research corpus; the
MedlinePlus command imports the full English public-health corpus. See
[`docs/v2/PUBLIC_MEDICAL_CORPORA.md`](docs/v2/PUBLIC_MEDICAL_CORPORA.md) for
source selection, attribution boundaries, optional Spanish import and test questions.

Open `http://127.0.0.1:8000/` for the Web console, or `http://127.0.0.1:8000/docs` for Swagger. The console defaults to these local demo trust-boundary headers:

```text
X-Tenant-ID: hospital-a
X-Actor-ID: local-demo
```

`X-Tenant-ID` is the convenient local demo mode. For a directly authenticated service, create an admin key
and switch modes:

```powershell
.\.venv\Scripts\python.exe .\scripts\manage_api_keys.py create `
  --tenant hospital-a --name local-admin --role admin
$env:AUTH_MODE = "api_key"
$headers = @{ Authorization = "Bearer <the-key-printed-once>" }
```

In `api_key` mode the server derives tenant, actor and role from the hashed credential record and ignores
spoofed `X-Tenant-ID`/`X-Actor-ID` values. See [`docs/v2/AUTHORIZATION.md`](docs/v2/AUTHORIZATION.md).

## Minimal demonstration

```powershell
$headers = @{ "X-Tenant-ID" = "hospital-a"; "X-Actor-ID" = "local-demo" }

Invoke-RestMethod http://127.0.0.1:8000/search -Method Post -Headers $headers `
  -ContentType "application/json" -Body '{"query":"哪些因素可能影响脉搏血氧仪读数？","knowledge_base_id":2}'

Invoke-RestMethod http://127.0.0.1:8000/answer -Method Post -Headers $headers `
  -ContentType "application/json" -Body '{"question":"输液泵上游阻塞告警应先核对什么？","knowledge_base_id":2}'
```

Queue a document with an idempotency key, then run one worker iteration:

```powershell
$headers["Idempotency-Key"] = "demo-upload-0001"
"PACS gateway recovery: verify DNS, TLS and DICOM reachability." | Set-Content .\demo-runbook.md
Invoke-RestMethod http://127.0.0.1:8000/knowledge-bases/1/ingestion-jobs `
  -Method Post -Headers $headers -Form @{ file = Get-Item .\demo-runbook.md }
.\.venv\Scripts\python.exe .\scripts\ingestion_worker.py --once
```

The first accepted upload returns `202`; replaying the same key and payload returns the same job with `200`.
Reusing the key for different bytes or a different knowledge base returns `409`.

Queue a summary over explicit tenant-scoped document IDs, then run its worker:

```powershell
$headers["Idempotency-Key"] = "demo-summary-0001"
$body = @{ question = "Summarize recovery checks"; document_ids = @(1, 2) } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/knowledge-bases/1/summary-jobs `
  -Method Post -Headers $headers -ContentType "application/json" -Body $body
.\.venv\Scripts\python.exe .\scripts\summary_worker.py --once
```

See [`docs/demo.md`](docs/demo.md) for normal, abstention, cross-tenant, injection and denied-tool cases.

## Quality gates and benchmarks

Run the release core (Ruff, 92 tests, 30-case answer/citation/abstention evaluation, ingestion and retrieval
benchmarks) with one command. `-Full` additionally runs the cached MiniLM confidence calibration and BGE
performance profile:

```powershell
.\scripts\reproduce_release.ps1
.\scripts\reproduce_release.ps1 -Full
```

Individual runners remain available for focused investigation:

```powershell
.\scripts\run_tests.ps1
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe .\evals\run_eval.py
.\.venv\Scripts\python.exe .\evals\benchmark_ingestion.py
.\.venv\Scripts\python.exe .\evals\benchmark_retrieval.py
.\.venv\Scripts\python.exe .\evals\benchmark_semantic_retrieval.py
.\.venv\Scripts\python.exe .\evals\benchmark_visual_retrieval.py
.\.venv\Scripts\python.exe .\evals\benchmark_parent_child.py
.\.venv\Scripts\python.exe .\evals\benchmark_query_transforms.py
.\.venv\Scripts\python.exe .\evals\evaluate_confidence_thresholds.py
.\.venv\Scripts\python.exe .\evals\benchmark_qdrant_server.py
.\.venv\Scripts\python.exe .\evals\benchmark_v2_performance.py
```

See the [Alpha.2 benchmark report](docs/v2/BENCHMARK_REPORT_ALPHA2.md). CLIP-B/32 reached 0.95 English Hit@1 on 20 text-free icons versus 0.05 for OCR-only, but only 0.10 Chinese Hit@1. Image embeddings therefore remain opt-in until a multilingual profile passes the Chinese gate.

The [parent-child benchmark](docs/v2/BENCHMARK_REPORT_BETA1.md) kept the linked action in returned context for
50/50 questions versus 0/50 with fixed chunks, while mean local retrieval rose from 13.628 to 19.702 ms.

Absolute evidence floors prevent per-query normalized BM25/RRF scores from turning the best irrelevant row
into false confidence. On the frozen 120-positive/20-negative set, both BM25 and RRF admitted 120/120
answerable cases and rejected 20/20 negatives. These synthetic-corpus thresholds must be recalibrated for a
new domain. The Docker Qdrant Server 1.19.0 gate reached 77.959 query/s at concurrency 8 over 10k vectors,
Recall@10 `1.0`, with zero tenant-filter violations; SQLite exact remains the simpler shipped default.

## Docker Compose

```powershell
docker compose up --build
```

The API binds only to `127.0.0.1:8000`; SQLite data lives in the named volume `medops_data`.
The selected exact local vector index is stored in that database; optional model files live in
`medops_models`. The three-service stack was built and passed `scripts/compose_smoke.py` on Docker Engine
29.1.3 / Compose 2.40.3. See [`docs/v2/DEPLOYMENT.md`](docs/v2/DEPLOYMENT.md).

## Optional model provider

Offline extractive answers are the default. To use an OpenAI-compatible `/chat/completions` endpoint, copy `.env.example` to `.env` and configure `MODEL_API_KEY`, `MODEL_BASE_URL`, and `MODEL_NAME`. Never commit `.env`.

To enable the local alpha visual profile, set `IMAGE_EMBEDDING_ENABLED=true`. The paired ONNX model files are
downloaded to `MODEL_CACHE_DIR` on first use and are excluded from Git. External vision inference additionally
requires `MODEL_VISION_ENABLED=true`; image count and aggregate raw bytes are capped by
`MODEL_MAX_VISUAL_IMAGES` and `MODEL_MAX_VISUAL_BYTES`. The default `0.28` similarity and `0.002` margin are
provisional Qdrant CLIP-B/32 values and must be recalibrated for another provider.

Set `TEXT_EMBEDDING_ENABLED=true` to persist/query normalized FastEmbed vectors. The current opt-in profile is
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`; rows carry their model identity, so vectors
from incompatible models are never scored together. A real local smoke retrieved the Chinese/English
credential fixture first at cosine `0.497208` in `63.082 ms` after indexing three documents in `2094.785 ms`.

On the frozen 120-question set, BM25 scored 0.9583 Hit@1, MiniLM 0.9417, RRF 0.9917, and RRF+BGE 1.0000.
The BGE stage remains offline because its 0.83-point gain raised mean latency from 130.244 to 1082.388 ms.

Query transformation also remains disabled by default. On the same frozen set, no-transform and rewrite both
reached 0.9917 Hit@1, multi-query fell to 0.9833, and deterministic template-HyDE fell to 0.7833. Explicit
experiments remain available through `query_transform`; automatic HyDE additionally requires
`HYDE_AUTO_ENABLED=true`.

On a real Redis 7.0.15 broker in WSL2, Celery 5.6.3 processed no-op transport tasks at a median 480.528
tasks/s versus 347.085 tasks/s for the SQLite lease loop. SQLite remains selected for the single-host profile:
the measured transport delta is tiny beside OCR/model latency, while Celery still needs the same domain tables
for progress, partial maps and citations. See the [queue benchmark](docs/v2/BENCHMARK_REPORT_JOB_QUEUES.md).

The hardened single-host [performance profile](docs/v2/BENCHMARK_REPORT_PERFORMANCE.md) measured authenticated
BM25 search at `56.127 ms` mean / `76.903 ms` p95 and offline answer at `73.866 ms` mean / `81.472 ms` p95.
Cached BGE Top-10 reranking alone averaged `369.715 ms` and remains outside the default online path. Raw
per-request samples are committed in `reports/v2-performance-profile.json`.

## Architecture

![MedOps RAG architecture](docs/architecture.svg)

Read [`docs/v2/ENGINEERING_DESIGN.md`](docs/v2/ENGINEERING_DESIGN.md), then [`docs/LEARNING_GUIDE.md`](docs/LEARNING_GUIDE.md), without treating every file as equally important.

## Explicit limits

- CLIP retrieves non-text images but does not reason over chart values or diagram relationships.
- PDF, PPTX and raster sources expose fixed-layout regions; DOCX flow layout does not claim stable page or
  image coordinates without a rendering engine.
- The tested CLIP profiles failed the current Chinese retrieval gate and remain opt-in.
- Hashing embeddings are lightweight and deterministic, not comparable to production embedding models.
- The local HyDE profile is a deterministic hypothetical-document template, not an LLM-generated passage;
  it materially hurt the frozen benchmark and is not enabled automatically.
- Prompt-injection detection is heuristic defense-in-depth, not a complete solution.
- `trusted_headers` remains a demo boundary; the API-key mode is authenticated but still needs gateway TLS,
  rate limiting and secret management for an Internet-facing deployment.
- SQLite and in-process retrieval target a local demonstration, not hospital-scale traffic.
- The corpus is synthetic and the evaluation set is intentionally small.
