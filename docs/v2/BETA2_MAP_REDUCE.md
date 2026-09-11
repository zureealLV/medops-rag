# Beta.2 Resumable Map-Reduce Summaries

## Contract

The summary API accepts an explicit objective and 1–50 document IDs. Every document is validated inside the
request tenant and knowledge base before the job is queued.

```text
POST /knowledge-bases/{kb_id}/summary-jobs  Idempotency-Key: 8..128 characters
GET  /summary-jobs/{job_id}
POST /summary-jobs/{job_id}/cancel

python scripts/summary_worker.py
python scripts/summary_worker.py --once
```

The response includes each map's status, summary, provider, token usage, error and immutable document/source
citation. The final text is forced to include a `[document:ID]` marker for every successful map even if an
online reducer omits it.

## Resume and partial semantics

Each map is written to `summary_map_results` before the worker advances progress and renews its lease. On
lease recovery, the next worker skips every persisted map—successful or failed—and runs only missing
documents. The reduce step can also be retried without repeating maps.

Terminal states mean:

- `succeeded`: every map and the reduce step completed;
- `partial`: at least one map succeeded, but another map or the reducer failed;
- `failed`: no map produced usable output, or the retry budget expired before any persisted result;
- `cancelled`: a client cancelled queued work or fenced a running worker between map calls.

The worker uses a 30-minute lease and heartbeats after each map. A configured online model call is hard-capped
at 30 seconds even if `SUMMARY_MODEL_TIMEOUT_SECONDS` is set higher. Offline mode uses deterministic
extractive maps and a citation-preserving reduce, so fresh clones require no API key.

## Verified recovery properties

`tests/test_summary_jobs.py` verifies:

1. two-document Map-Reduce output and map/final citations;
2. idempotent replay and conflicting request rejection;
3. visible partial output after one map timeout;
4. resumption without repeating an already persisted map;
5. tenant isolation and cancellation;
6. the hard 30-second HTTP timeout cap;
7. abrupt process exit (`os._exit`) followed by successful lease recovery in a new worker process;
8. two concurrent worker processes completing one job with one claim and one result per document.

## Capability boundary

This is a locally durable, at-least-once job workflow, not a claim of distributed exactly-once execution.
The next selection gate compares the measured SQLite implementation against Redis/Celery. Document-level
summaries are bounded input transformations, not semantic proof that every source fact was preserved.
