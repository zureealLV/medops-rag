# MedOps Medical Knowledge Agent RAG V3.4

[中文说明](README_CN.md) · [RAG-Pro comparison and MCP migration](docs/v3/RAG_PRO_COMPARISON_AND_MIGRATION.md) · [Enterprise roadmap](docs/v4/ENTERPRISE_ROADMAP.md) · [Adaptive challenge v3](docs/v3/ADAPTIVE_CHALLENGE_V3_EVALUATION.md) · [Summary Provider policy](docs/v4/SUMMARY_PROVIDER_POLICY.md) · [Concurrency audit](docs/v3/CONCURRENCY_OPTIONS.md) · [Agent tools/checkpoints](docs/v4/AGENT_TOOLS_AND_CHECKPOINTS.md) · [Agent benchmark](docs/v3/BENCHMARK_AGENT_ORCHESTRATION.md) · [Official Chinese corpus](docs/v2/OFFICIAL_CHINESE_CORPUS.md) · [Authentication](docs/v2/AUTHORIZATION.md) · [Deployment](docs/v2/DEPLOYMENT.md) · [Threat model](THREAT_MODEL.md)

An auditable, tenant-scoped Agent RAG assistant for **public medical knowledge and medical-device evidence**.
V3.4 adds one end-to-end Provider deadline across queueing, HTTP attempts and backoff, bounded `Retry-After`,
exponential jitter, process-local global/per-tenant retry budgets, and an honestly harder adaptive challenge v3.
It retains V3.3's tenant-fair AsyncClient path, circuit breaker, explicit overload behavior, and the admin-only
retrieval laboratory, tenant/actor-scoped Agent control checkpoints, Vue 3 enterprise console,
explainable adaptive retrieval, DeepSeek V4 Flash, token/cost telemetry,
and measured chunk-profile gates. It retains V2.4's six hash-pinned Chinese government
PDFs, 15,000-record Huatuo research corpus, NLM MedlinePlus import, multimodal evidence, SQLite trigram FTS and
the bright clinical console.

> Educational portfolio software, not a medical device. It does not diagnose, prescribe, process real patient records, or execute system-changing tools.

> **Claim boundary:** alpha.2 routes visual questions, retrieves text-free images, and returns stored image evidence. It does not yet claim chart/diagram reasoning or production Chinese cross-modal quality.

## Current capabilities

- Experimental V3 bounded-Agent layer: the same `/answer` endpoint compares Classic Python, LangChain LCEL,
  and LangGraph; the managed path selects at most two code-owned read-only tools (grounded answer plus citation
  scope verification), applies safety/grounding gates, records a Web-visible trace, and persists bounded control
  checkpoints without storing questions, prompts, evidence, or answers.
- DeepSeek V4 Flash OpenAI-compatible API defaults, with the API key read only from the local environment;
  production `/answer` uses a lifespan-scoped shared `httpx.AsyncClient`, tenant round-robin scheduling,
  bounded global/per-tenant active and waiting budgets, classified retries, a closed/open/half-open breaker,
  a queue/HTTP/backoff deadline with explicit `504`, bounded `Retry-After` plus jitter, process-local retry token
  buckets, explicit overload `503`, bounded shutdown, token accounting, and controlled offline fallback.
- a Vue 3.5 + TypeScript 5.9 + Vite 7 + Vue Router 4 + Pinia 3 + Element Plus 2 enterprise console for knowledge spaces, bounded-parallel uploads, cited Q&A,
  health and tenant-scoped operational metrics; the document catalog uses metadata-only server pagination and
  title/source filtering instead of sending every document body to the browser;
- an MCP Python SDK 2.2 Streamable HTTP endpoint at `/mcp/`, exposing tenant-scoped knowledge-base listing,
  evidence search and policy-controlled grounded answers with server-side API-key identity resolution and audit logging;
- viewer/editor callers submit business questions only; the server owns `top_k`, retrieval/evidence strategy,
  and orchestration defaults, while administrators retain benchmark and incident-diagnosis overrides in a
  dedicated retrieval/answer laboratory; text search and visual search enforce the same server boundary;
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
- deterministic adaptive routing between BM25, RRF, and parent-child, with an auditable reason, confidence,
  extracted query features, and candidate scores;
- cited extractive answers and evidence-threshold abstention, with natural answer text and numbered source/image cards below it instead of inline implementation locators;
- reproducible import of the official NLM MedlinePlus bulk health-topic XML, with per-topic provenance and a local source manifest;
- bounded, revision-pinned import of 12,000 Chinese medical knowledge-graph QA records and 3,000 Chinese medical encyclopedia QA records from Huatuo-26M;
- hash-pinned import of six official Chinese medical/medical-device PDFs with publisher-host, redirect, size, signature and content-hash gates;
- Chinese punctuation-aware chunking with boundary-aligned overlap, plus quantity/list-aware deterministic extraction;
- tenant- and knowledge-base-scoped SQLite FTS5 trigram candidate retrieval before in-process BM25 reranking;
- optional OpenAI-compatible generation with timeout, bounded retry and offline fallback;
- tenant filtering in SQL before retrieval/model context;
- optional scrypt-hashed API keys, immediate revocation, server-bound tenancy and viewer/editor/admin roles;
- indirect prompt-injection quarantine, PII-safe audit data and medical-advice denial;
- three read-only tools: `search_documents`, `get_document_metadata`, `get_system_status`;
- request IDs, `Server-Timing`, dependency-free `/live`, database-aware `/ready`, tenant-scoped routing metrics,
  process-local Provider capacity/breaker/deadline/retry-budget telemetry, 210 tests,
  and repeatable ingestion/retrieval/concurrency benchmarks;
- backup-first V1-to-V2 migration, explicit schema versioning and a tested full-database rollback path;
- a Docker Compose definition with API, ingestion worker, summary worker, health checks and persistent
  data/model volumes; the prior V3 image gate was verified, while the V3.4 async/frontend image still needs
  revalidation on a host with the Docker Linux engine available;
- two idempotent starter knowledge bases for clinical fundamentals and medical-device safety, derived from public FDA, CDC, WHO and MedlinePlus material and kept strictly educational.

## Quick start (Windows / PowerShell)

Requires Python 3.11+. Building the Vue console also requires Node.js 20.19+, 22.12+, or 24
(validated here with Node 24.15.0 and npm 11.14.1).

```powershell
git clone https://github.com/zureealLV/medops-rag.git
cd medops-rag
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\scripts\build_frontend.ps1
.\.venv\Scripts\python.exe .\scripts\seed_sample_data.py --profile medical
.\.venv\Scripts\python.exe -m scripts.import_chinese_official
.\.venv\Scripts\python.exe -m scripts.import_huatuo
.\.venv\Scripts\python.exe -m scripts.import_medlineplus
.\.venv\Scripts\fastapi.exe dev
```

To reuse an existing external DeepSeek dotenv file without copying its secret into this repository:

```powershell
.\scripts\run_dev.ps1 -EnvFile <external-.env-path>
```

The official-source command imports six hash-pinned government PDFs without bundling their binaries in Git.
The Huatuo command imports the default Chinese-first 15,000-record research corpus; the
MedlinePlus command imports the full English public-health corpus. See the
[official Chinese corpus guide](docs/v2/OFFICIAL_CHINESE_CORPUS.md) and
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

Run the release core (Ruff, 210 tests, Vue typecheck/production build, 30-case answer/citation/abstention evaluation, ingestion and retrieval
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
.\.venv\Scripts\python.exe .\evals\benchmark_agent_orchestration.py --repetitions 20
.\.venv\Scripts\python.exe .\evals\benchmark_chunk_profiles.py
.\.venv\Scripts\python.exe .\evals\benchmark_official_chunk_profiles.py
.\.venv\Scripts\python.exe .\evals\benchmark_adaptive_routing.py
.\.venv\Scripts\python.exe .\evals\benchmark_adaptive_heldout_zh.py --repetitions 3
.\.venv\Scripts\python.exe .\evals\benchmark_adaptive_challenge_v2.py --repetitions 1
.\.venv\Scripts\python.exe .\evals\benchmark_adaptive_challenge_v3.py --repetitions 5
.\.venv\Scripts\python.exe .\evals\benchmark_concurrency_v3.py
```

The independent Chinese held-out set contains 20 synthetic operations documents, 32 answerable questions and
8 negatives. Adaptive routing reached `1.0000` Hit@1, tying fixed BM25 and parent-child rather than beating them;
fixed RRF reached `0.9062`. Adaptive chose BM25/RRF/parent-child for `16/10/6` answerable cases and avoided dense
query latency on 22 of 32 cases. This is source-ranking evidence only—not generated-answer accuracy, production
traffic, or clinical validation. The threshold-tuning set was not reused and the benchmark forces local-only
model loading with zero provider/API calls.

Adaptive challenge v2 adds 28 documents and 48 cases with zero normalized question/source-name overlap against
the tuning set and held-out v1. On 24 single-source cases, BM25, parent-child, and adaptive each reached `1.0000`
Hit@1; RRF reached `0.9583`. All four strategies reached full two-source coverage@3 on eight cases, which is
reported as insufficient discriminative difficulty rather than a universal win. Eight unanswerable cases are
route-only, while eight real SQLite tenant probes produced zero leaks and hid every foreign KB ID (`8/8`).

The frozen challenge v3 deliberately adds typo/noise, low lexical overlap, and three-source conflict/combination
cases. Adaptive reached Hit@1 `0.8000` and Hit@5 `1.0000` on 20 single-source cases, but only `0.6000` Hit@1 on
the low-overlap subset. On eight three-source cases it reached Recall@5 `0.8333` and full coverage@5 `0.6250`;
fixed BM25 was better at `0.8750` and `0.7500`. All exact, near-duplicate, source-name, and content-hash overlaps
against the three previous datasets were zero. This exposes a real retrieval gap rather than tuning the router
after seeing the scores; provider/application calls remained zero.

The [V3 Agent benchmark](docs/v3/BENCHMARK_AGENT_ORCHESTRATION.md) isolates framework overhead on 600 calls
per mode and records a paid live `deepseek-v4-flash` run on 8 official-corpus cases, 3 repetitions and 24 runs
per mode. All live quality metrics were 1.0000; mean end-to-end latency was 2332.197 ms (Classic), 2269.603 ms
(LangChain LCEL), and 2294.754 ms (LangGraph). The live result proves compatibility and telemetry, not a broad
latency ranking; the repeated offline benchmark isolates LangGraph overhead at 1.986 ms.

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
