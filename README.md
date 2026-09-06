# MedOps Multimodal RAG V2 Alpha.1

[中文说明](README_CN.md) · [V2 engineering design](docs/v2/ENGINEERING_DESIGN.md) · [Alpha.1 benchmark](docs/v2/BENCHMARK_REPORT_ALPHA1.md) · [Roadmap](docs/v2/ROADMAP.md) · [Threat model](THREAT_MODEL.md)

An auditable, tenant-scoped multimodal RAG assistant for **synthetic hospital IT operations documents**. Alpha.1 adds real PDF/DOCX/PPTX/image ingestion, OCR evidence, provenance, idempotent uploads, and measured retrieval baselines to the V1 FastAPI → SQLite → cited-answer pipeline.

> Educational portfolio software, not a medical device. It does not diagnose, prescribe, process real patient records, or execute system-changing tools.

> **Claim boundary:** alpha.1 implements multiformat and OCR-based multimodal ingestion. First-class visual embeddings, chart/diagram reasoning, and region citations are scheduled for alpha.2; OCR alone is not presented as complete visual RAG.

## Alpha.1 capabilities

- FastAPI application factory, typed routes, dependency injection, stable errors and OpenAPI;
- SQLite transactions, foreign keys, indexes and restart persistence;
- knowledge-base and document CRUD with SHA-256 idempotent uploads;
- TXT/Markdown/PDF/DOCX/PPTX/PNG/JPEG/WebP parsing with native text, table, and OCR elements;
- page/slide/heading provenance through `GET /documents/{id}/elements`;
- conditional scanned-PDF OCR and embedded-image OCR through RapidOCR/ONNX Runtime;
- deterministic hashing, keyword, BM25, weighted, and RRF retrieval strategies;
- cited extractive answers and evidence-threshold abstention;
- optional OpenAI-compatible generation with timeout, bounded retry and offline fallback;
- tenant filtering in SQL before retrieval/model context;
- indirect prompt-injection quarantine, PII-safe audit data and medical-advice denial;
- three read-only tools: `search_documents`, `get_document_metadata`, `get_system_status`;
- request IDs, `Server-Timing`, request metrics, 34 API/security/parser/migration tests and repeatable ingestion/retrieval benchmarks;
- reproducible local and Docker Compose startup.

## Quick start (Windows / PowerShell)

Requires Python 3.11+.

```powershell
git clone https://github.com/zureealLV/medops-rag.git
cd medops-rag
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe .\scripts\seed_sample_data.py
.\.venv\Scripts\fastapi.exe dev
```

Open `http://127.0.0.1:8000/docs`. Business endpoints require the demo trust-boundary header:

```text
X-Tenant-ID: hospital-a
X-Actor-ID: local-demo
```

`X-Tenant-ID` represents identity already authenticated by an upstream gateway. It is deliberately **not** production authentication.

## Minimal demonstration

```powershell
$headers = @{ "X-Tenant-ID" = "hospital-a"; "X-Actor-ID" = "local-demo" }

Invoke-RestMethod http://127.0.0.1:8000/search -Method Post -Headers $headers `
  -ContentType "application/json" -Body '{"query":"LIS 接口连续超时先检查什么？"}'

Invoke-RestMethod http://127.0.0.1:8000/answer -Method Post -Headers $headers `
  -ContentType "application/json" -Body '{"question":"PACS 健康检查失败如何排查？"}'
```

See [`docs/demo.md`](docs/demo.md) for normal, abstention, cross-tenant, injection and denied-tool cases.

## Quality gates and benchmarks

```powershell
.\scripts\run_tests.ps1
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe .\evals\run_eval.py
.\.venv\Scripts\python.exe .\evals\benchmark_ingestion.py
.\.venv\Scripts\python.exe .\evals\benchmark_retrieval.py
.\.venv\Scripts\python.exe .\evals\benchmark_semantic_retrieval.py
```

See the [Alpha.1 benchmark report](docs/v2/BENCHMARK_REPORT_ALPHA1.md). The current six-document corpus favors BM25; local dense retrieval and BGE reranking are experiments rather than defaults until a harder held-out V2 dataset justifies their latency and memory cost.

## Docker Compose

```powershell
docker compose up --build
```

The API binds only to `127.0.0.1:8000`; SQLite data lives in the named volume `medops_data`.

## Optional model provider

Offline extractive answers are the default. To use an OpenAI-compatible `/chat/completions` endpoint, copy `.env.example` to `.env` and configure `MODEL_API_KEY`, `MODEL_BASE_URL`, and `MODEL_NAME`. Never commit `.env`.

## Architecture

![MedOps RAG architecture](docs/architecture.svg)

Read [`docs/v2/ENGINEERING_DESIGN.md`](docs/v2/ENGINEERING_DESIGN.md), then [`docs/LEARNING_GUIDE.md`](docs/LEARNING_GUIDE.md), without treating every file as equally important.

## Explicit limits

- OCR extracts text from images but does not yet understand non-textual charts or diagrams.
- Hashing embeddings are lightweight and deterministic, not comparable to production embedding models.
- Prompt-injection detection is heuristic defense-in-depth, not a complete solution.
- The tenant header is a demo boundary; production deployments require authenticated identity and authorization.
- SQLite and in-process retrieval target a local demonstration, not hospital-scale traffic.
- The corpus is synthetic and the evaluation set is intentionally small.
