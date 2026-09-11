# Summary Provider Capacity Policy

Status: V3.4 design decision. The online implementation remains authoritative;
the background-summary migration described here is not yet production code.

## Problem statement

Online `/answer` calls use the process-local asynchronous `ModelProvider` with
bounded outstanding requests, tenant round-robin scheduling, retry budgets, and
a circuit breaker. Background Map-Reduce summaries still use a separate
synchronous `httpx.post` adapter from another process. Consequently, the two
workloads do not share a real deployment-wide concurrency, retry, or breaker
budget.

This boundary must remain explicit: two Python semaphores in two processes do
not form one global limit. Running more API or summary-worker replicas multiplies
the effective upstream concurrency unless an external coordinator or gateway
enforces it.

## V3.4 decision: fixed online/batch partition first

For the currently supported topology of one API process and one summary worker,
use a declared Provider concurrency budget and reserve fixed, non-borrowing
partitions. For example, with a declared budget of four:

| Traffic class | Reserved concurrency | Goal |
|---|---:|---|
| Online answer | 3 | Protect interactive latency |
| Batch summary | 1 | Guarantee finite batch progress |

The concrete numbers are deployment inputs, not universal defaults. Startup
must reject a configuration whose online and batch reservations exceed the
declared budget. Capacity borrowing and preemption are deliberately deferred;
they add failure modes before a deployment-wide coordinator exists.

If the upstream supports separate projects or credentials, use distinct online
and batch credentials so the partition is also enforceable upstream. Never
commit either credential.

## Required migration shape

1. Convert the summary adapter to asynchronous Provider calls and pass both
   `tenant_id` and `traffic_class=batch`.
2. Give the summary worker a lifecycle-owned client (`start`/`aclose`) rather
   than one connection per call.
3. Classify retries identically to online calls: timeout, network failure, 429,
   and selected 5xx only. Do not retry 400/401/403 as transient faults.
4. Treat one map or reduce call as one scheduling quantum. A worker must not
   retain the fair-scheduling turn for an entire large job.
5. Add a unique lease token on every claim. Heartbeat independently while a
   model request or retry backoff is running; every save, finish, release, and
   retry operation must validate the lease token.
6. Make running cancellation observable (`cancelling` to `cancelled`) and cancel
   the async HTTP task. The guarantee is to stop future work, not to prove that
   an already-sent upstream request was never billed.
7. Persist a Provider-call ledger before and after each call. Reuse a stored
   successful response after a worker crash. Mark a sent request with no known
   result as `outcome_unknown` instead of silently retrying and claiming exact
   billing.

## Fairness and durability contract

- Same-tenant work remains FIFO.
- Eligible tenants rotate at map/reduce step granularity, so one large job does
  not indefinitely block another tenant's short job.
- Claim count and retry attempt count are separate. A 50-document job must not
  exhaust `max_attempts` merely because it yielded after each map step.
- A stale worker cannot save results after another worker owns a newer lease
  token.
- Token usage distinguishes known result tokens, all attempted tokens, and
  billing-unknown calls.

## Idempotency and billing boundary

Use stable call keys such as:

```text
summary:<job-id>:map:<document-id>
summary:<job-id>:reduce:<map-set-hash>
```

Persist `started` before sending the request and persist the response, Provider
request ID, and usage before writing the derived map result. Without an upstream
idempotency guarantee, a crash or timeout after send is fundamentally
ambiguous. Strict mode therefore requires manual reconciliation for
`outcome_unknown`; an at-least-once mode may retry only when it exposes
`billing_uncertain=true`.

Exactly-once upstream billing cannot be guaranteed by SQLite job idempotency.
A Provider gateway that caches successful responses by call key is the preferred
long-term boundary.

## Verification gates

### Single host / SQLite gate

- MockTransport proves summary uses the async Provider policy and typed errors.
- 400/401/403 receive one attempt; timeout/network/429/5xx obey the same bounded
  retry rules as online traffic.
- A 50-document tenant and a one-document tenant interleave by step.
- Lease loss rejects stale save/finish calls; heartbeat covers map, backoff, and
  reduce.
- Running cancellation stops the current async call and schedules no next step.
- A persisted response is reused after a simulated crash; `outcome_unknown`
  is not silently replayed in strict mode.

### Deployment-wide gate

Multiple Uvicorn workers, multiple summary replicas, or multiple hosts require
one of:

1. a Redis-backed atomic lease/token-bucket protocol with TTL, heartbeat, and a
   fencing generation; or
2. a single Provider gateway enforcing concurrency, RPS/TPM, tenant/workload
   fairness, idempotency response caching, circuit state, and billing telemetry.

Only a real socket test through every process may claim a deployment-wide cap.
ASGITransport and process-local snapshots cannot prove it.

## Rollout order

1. Freeze typed outcomes and telemetry fields.
2. Introduce the async batch adapter under a fixed partition.
3. Add fencing, heartbeat, and cancellation acknowledgement.
4. Add the Provider-call ledger and strict unknown-outcome policy.
5. Change scheduling to one-step quanta with tenant round-robin.
6. Validate the supported one-API/one-worker topology with a mock HTTP gateway.
7. Add Redis or a Provider gateway before enabling replicas or dynamic borrowing.
