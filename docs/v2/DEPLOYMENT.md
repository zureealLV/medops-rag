# V2 Single-host Docker Compose Deployment

Status: built and exercised on 2026-09-07 with Docker Engine `29.1.3` and Docker Compose `2.40.3` inside
Ubuntu 24.04 WSL2.

## Topology

The Compose project runs three non-root services from one immutable image:

1. `api` — Uvicorn/FastAPI bound only to `127.0.0.1:8000`;
2. `ingestion-worker` — durable parser/OCR/index queue consumer;
3. `summary-worker` — durable Map-Reduce queue consumer.

`medops_data` persists the SQLite database and its exact local vector index; this is the selected single-host
index from the committed vector-store benchmark. `medops_models` persists optional downloaded model files.
Qdrant is not silently started because it was not selected for this local-size profile.

All services use the unprivileged `medops` user (UID 10001), a read-only root filesystem, `no-new-privileges`,
all Linux capabilities dropped, a 256-process limit and a bounded temporary filesystem. The workers start only
after the API/database health check succeeds.

## Start and verify

```powershell
docker compose config
docker compose build --pull
docker compose up -d
docker compose ps
.\.venv\Scripts\python.exe .\scripts\compose_smoke.py
```

The smoke creates a unique synthetic tenant and knowledge base, submits a multipart Markdown ingestion job,
waits for the ingestion worker, submits a summary job, waits for the summary worker and verifies the final
document citation. It requires the default `trusted_headers` mode and is not a production probe.

The verification run reported all three services healthy, no traceback/error/exception log lines, and:

```text
user=medops readonly=true caps=["ALL"]
Compose API + ingestion worker + summary worker smoke: PASS
```

## Enable API-key mode

Create the first credential in the persistent data volume from a trusted shell, then restart with the hardened
mode. The plaintext key appears once.

```powershell
docker compose run --rm api python scripts/manage_api_keys.py create `
  --tenant hospital-a --name compose-admin --role admin
$env:AUTH_MODE = "api_key"
docker compose up -d
```

Put a TLS reverse proxy and rate limiter in front before exposing the service beyond localhost.

## Stop and recover

```powershell
docker compose down                 # preserve data/model volumes
docker compose down --volumes       # destructive: remove this project's persisted data and models
```

SQLite WAL, fenced job leases and idempotency keys allow the three processes to restart without inventing
completed work. Backup/rollback procedures are documented separately; Compose volumes are not a substitute
for tested backups.

## Scope

This topology is deliberately single-host. It is not a Kubernetes or horizontal-scaling claim. Multi-host
workers require a shared database/object store and an external vector service with the same tenant-filter
tests. The image build downloads Python dependencies; an air-gapped deployment must pin and mirror wheels and
base-image digests under its own supply-chain policy.
