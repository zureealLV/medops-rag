# MedOps RAG

An auditable knowledge assistant for synthetic hospital IT operations documents.

This repository is intentionally developed in daily increments. Each day must leave runnable code, a negative test or failure example, a short explanation, and a focused Git commit. The project starts as a minimal FastAPI service and evolves into a cited, evaluated, tenant-isolated RAG application with restricted tool calling.

## Safety Boundary

- Use only public or synthetic data.
- Do not provide diagnosis or treatment advice.
- Do not store real patient information, credentials, cookies, or API tokens.
- Treat retrieved documents and model output as untrusted data.

## Current Stage

**Day 0 — planning scaffold**

The application code is deliberately not generated yet. Day 1 begins from an empty Python application so the implementation can be completed and explained independently.

## Documents

- Chinese overview: [`README_CN.md`](README_CN.md)
- Project specification: [`docs/PROJECT_SPEC.md`](docs/PROJECT_SPEC.md)
- 30-day plan: [`docs/plans/2026-09-03-medops-rag-30-day-plan.md`](docs/plans/2026-09-03-medops-rag-30-day-plan.md)
- Daily evidence index: [`docs/progress/DAILY_LOG.md`](docs/progress/DAILY_LOG.md)
- Daily report template: [`docs/progress/DAY_REPORT_TEMPLATE.md`](docs/progress/DAY_REPORT_TEMPLATE.md)

## Version Gates

| Gate | Version | Evidence |
|---|---|---|
| Day 7 | MedKB API v0.1 | FastAPI, SQLite, CRUD, layers, errors, logs, pytest |
| Day 14 | MedOps RAG v0.2 | ingestion, retrieval, citations, evaluation, restricted tools |
| Day 21 | Secure MedOps RAG v0.3 | tenant isolation, injection tests, redaction, audit trail |
| Day 30 | MedOps RAG v1.0 | reproducible deployment, observability, documentation, demo |
