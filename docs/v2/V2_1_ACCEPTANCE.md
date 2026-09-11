# V2.1 Web Console Acceptance

Date: 2026-09-07
Branch: `feat/multimodal-rag-v2`

## Scope delivered

- same-origin FastAPI static Web console at `/ui/` with `/` redirect;
- responsive overview, evidence Q&A, knowledge document and operations views;
- trusted-header and Bearer-key connection profiles, with Bearer keys kept in session storage;
- knowledge-base creation, synchronous demonstration uploads, cited/abstained answer rendering and authorized visual-evidence loading;
- health, request, latency, fallback, abstention and durable-queue visibility;
- Docker image inclusion, operator documentation and route regression coverage.

## Verification evidence

### Static and Python checks

```text
node --check web/app.js
python -m ruff check app tests scripts
All checks passed!
```

### Automated suite

```text
scripts/run_tests.ps1
collected 86 items
86 passed, 2 warnings in 28.01s
```

The two warnings are upstream FastAPI/Starlette deprecation notices from `TestClient`; they do not represent test failures.

### Live browser behavior

Verified in the Codex in-app browser against `http://127.0.0.1:8000/ui/`:

- health indicator changed to `服务正常` and reported `2.1.0`;
- tenant `hospital-a` loaded one knowledge base and six synthetic documents;
- the default LIS timeout question returned `EVIDENCE GROUNDED` with five ranked source cards;
- layout rendered at the browser's compact width without horizontal overflow.

### Fresh container image and worker smoke

```text
docker compose up --build -d
Container medops-rag-api-1 Healthy
Container medops-rag-ingestion-worker-1 Started
Container medops-rag-summary-worker-1 Started

python scripts/compose_smoke.py
Compose Web console + API + ingestion worker + summary worker smoke: PASS
```

The Compose stack used fresh temporary data/model volumes. It was removed after the smoke run with `docker compose down --volumes --remove-orphans`.

## Claim boundary

V2.1 is a portfolio/operator console, not a separate production frontend platform. It deliberately avoids a Node build chain and delegates all authentication, tenant filtering, file safety and answer policy to the API. The upload control uses the synchronous endpoint for a fast local demonstration; the durable worker queue remains the production-shaped ingestion path.
