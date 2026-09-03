# MedOps RAG

An auditable knowledge assistant for synthetic hospital IT operations documents.

This repository is developed in incremental, testable stages. It starts as a minimal FastAPI service and evolves into a cited, evaluated, tenant-isolated RAG application with restricted tool calling.

## Safety Boundary

- Use only public or synthetic data.
- Do not provide diagnosis or treatment advice.
- Do not store real patient information, credentials, cookies, or API tokens.
- Treat retrieved documents and model output as untrusted data.

## Current Stage

**Day 1 — minimal FastAPI API complete**

- `GET /health`
- `POST /users` with Pydantic request and response models
- `GET /users/{user_id}` with integer path validation

## Documents

- Chinese overview: [`README_CN.md`](README_CN.md)
- Project specification: [`docs/PROJECT_SPEC.md`](docs/PROJECT_SPEC.md)
- Clear 30-day task checklist: [`docs/plans/2026-09-03-medops-rag-30-day-plan.md`](docs/plans/2026-09-03-medops-rag-30-day-plan.md)

## Version Gates

| Gate | Version | Evidence |
|---|---|---|
| Day 7 | MedKB API v0.1 | FastAPI, SQLite, CRUD, layers, errors, logs, pytest |
| Day 14 | MedOps RAG v0.2 | ingestion, retrieval, citations, evaluation, restricted tools |
| Day 21 | Secure MedOps RAG v0.3 | tenant isolation, injection tests, redaction, audit trail |
| Day 30 | MedOps RAG v1.0 | reproducible deployment, observability, documentation, demo |
