# MedOps RAG V1

[中文说明](README_CN.md) · [Learning guide](docs/LEARNING_GUIDE.md) · [Threat model](THREAT_MODEL.md)

An auditable, tenant-scoped RAG assistant for **synthetic hospital IT operations documents**. It demonstrates a complete FastAPI → SQLite → ingestion → hybrid retrieval → cited answer pipeline without requiring an API key.

> Educational portfolio software, not a medical device. It does not diagnose, prescribe, process real patient records, or execute system-changing tools.

## V1 capabilities

- FastAPI application factory, typed routes, dependency injection, stable errors and OpenAPI;
- SQLite transactions, foreign keys, indexes and restart persistence;
- knowledge-base and document CRUD with automatic chunking and indexing;
- deterministic hashing embeddings plus keyword/vector hybrid ranking;
- cited extractive answers and evidence-threshold abstention;
- optional OpenAI-compatible generation with timeout, bounded retry and offline fallback;
- tenant filtering in SQL before retrieval/model context;
- indirect prompt-injection quarantine, PII-safe audit data and medical-advice denial;
- three read-only tools: `search_documents`, `get_document_metadata`, `get_system_status`;
- request IDs, `Server-Timing`, request metrics, 26 API/security tests and a 30-case offline evaluation;
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

## Quality gates

```powershell
.\scripts\run_tests.ps1
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe .\evals\run_eval.py
```

Validated V1 baseline: **26 tests passed**; 30 evaluation cases achieved Retrieval Hit@5 `1.00`, citation correctness `1.00`, and correct abstention `1.00` on the bundled synthetic corpus. This is a small deterministic benchmark, not a production-quality claim.

## Docker Compose

```powershell
docker compose up --build
```

The API binds only to `127.0.0.1:8000`; SQLite data lives in the named volume `medops_data`.

## Optional model provider

Offline extractive answers are the default. To use an OpenAI-compatible `/chat/completions` endpoint, copy `.env.example` to `.env` and configure `MODEL_API_KEY`, `MODEL_BASE_URL`, and `MODEL_NAME`. Never commit `.env`.

## Architecture

![MedOps RAG architecture](docs/architecture.svg)

Read [`docs/LEARNING_GUIDE.md`](docs/LEARNING_GUIDE.md) in the listed order to understand the FastAPI and RAG implementation without treating every file as equally important.

## Explicit limits

- Hashing embeddings are lightweight and deterministic, not comparable to production embedding models.
- Prompt-injection detection is heuristic defense-in-depth, not a complete solution.
- The tenant header is a demo boundary; production deployments require authenticated identity and authorization.
- SQLite and in-process retrieval target a local demonstration, not hospital-scale traffic.
- The corpus is synthetic and the evaluation set is intentionally small.
