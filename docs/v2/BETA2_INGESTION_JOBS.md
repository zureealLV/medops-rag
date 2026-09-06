# Beta.2 Durable Ingestion Jobs

## Scope

This increment moves document parsing, OCR, chunking and optional embedding out of the API request path. It
uses SQLite as a durable local queue so that job state survives API and worker restarts. It does not claim to
be a distributed queue replacement.

## API and worker

```text
POST /knowledge-bases/{kb_id}/ingestion-jobs  Idempotency-Key: 8..128 characters
GET  /ingestion-jobs/{job_id}
POST /ingestion-jobs/{job_id}/cancel

python scripts/ingestion_worker.py
python scripts/ingestion_worker.py --once
python scripts/ingestion_worker.py --lease-seconds 600
```

The upload endpoint enforces `MAX_UPLOAD_BYTES` before persisting the payload. Job lookup and cancellation
always include the trusted tenant boundary. Successful jobs remove their stored upload bytes after creating
the content-addressed document.

## State and lease protocol

```text
queued --claim--> running --success--> succeeded
   ^                  |  \
   |                  |   +--terminal parse error--> failed
   +--transient-------+   +--cancel----------------> cancelled
                          +--expired lease----------> running (next attempt)
                          +--expired final lease----> failed/retry_exhausted
```

- a claim increments `attempt`, records `lease_owner`, and sets an epoch `lease_expires_at` (the CLI defaults
  to 300 seconds and allows an explicit override);
- only the current lease owner may mark the job succeeded or failed, fencing stale workers;
- expired leases are reclaimable while `attempt < max_attempts`;
- the third expired lease becomes terminal `retry_exhausted`;
- stable `AppError` parser/input failures are terminal; unexpected worker exceptions requeue within the bound;
- document SHA-256 uniqueness closes the check-then-insert race if the same bytes are delivered twice.

The delivery contract is therefore **at least once at the worker boundary and effectively once at the
document boundary** for the same tenant, knowledge base and bytes.

## Verified cases

`tests/test_ingestion_jobs.py` covers:

1. successful processing and same-key replay;
2. key reuse conflict for a different payload;
3. unexpired-lease exclusion, expired-lease takeover and stale-owner fencing;
4. retry exhaustion after three claims;
5. cancellation and tenant isolation;
6. unsupported poison documents failing without a document row;
7. a transient worker exception requeueing once and then succeeding.
8. the worker CLI consuming a persisted job in a separate Python process.

## Explicit limits

- SQLite is selected only for the single-host portfolio profile. Redis/Celery and a real Qdrant server still
  require a concurrent benchmark before any distributed deployment claim.
- The parser call is blocking. Cancellation can prevent queued work or fence a running worker's final state,
  but cannot pre-empt third-party parser code mid-call.
- There is no lease heartbeat yet. Long work can be redelivered after lease expiry; document hash uniqueness
  prevents duplicate document rows, while a later valid lease owner remains responsible for the terminal job
  state.
- `partial` is reserved in the schema for the upcoming batch Map-Reduce summary flow and is not exposed as a
  completed capability in this increment.
