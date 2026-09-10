# MedOps Enterprise RAG Roadmap

This roadmap keeps the public API auditable while moving the demonstration
console and retrieval pipeline toward a deployable enterprise architecture.
Each phase has an evidence gate; a dependency being present is not treated as
proof that the feature works.

## Product boundary

- End users submit a business question and optional knowledge-space scope.
- Retrieval profile, chunk/evidence strategy, `top_k`, and orchestration engine
  are platform-managed defaults for viewer/editor identities.
- Administrators may override those controls for benchmark, rollout, and
  incident diagnosis. Server-side authorization remains the source of truth;
  hiding controls in the browser is not an authorization mechanism.
- Answers must either contain tenant-scoped citations or abstain. The system is
  educational and operational; it does not diagnose or prescribe.

## Phase 0 - current enterprise baseline

### Vue 3 console

- Vue 3 + TypeScript + Vite application shell.
- Vue Router pages for overview, evidence Q&A, documents, and operations.
- Pinia stores for local authentication profile and application state.
- Element Plus components, accessible loading/empty/error states, and
  server-paginated document browsing.
- Production bundle served by FastAPI under `/ui/`; Vite development server
  proxies API requests to FastAPI.

**Gate:** typecheck + production build + FastAPI static smoke + visible browser
review at desktop and narrow viewport sizes.

### Adaptive retrieval routing

- Deterministic, explainable query classification selects an eligible retrieval
  strategy from query and corpus signals.
- The decision includes a reason and confidence suitable for audit/trace output.
- Fixed strategies stay available to administrators and offline benchmarks, not
  ordinary users.

**Gate:** unit tests for every routing class and an offline comparison against
fixed BM25, RRF, and parent-child baselines on the checked-in evaluation set.

### Concurrency baseline

- Measure read, write, and mixed traffic separately at multiple concurrency
  levels.
- Report throughput, p50/p95/p99 latency, error rate, and SQLite lock failures.
- Separate immediately safe tuning from changes that require Redis, PostgreSQL,
  or a different vector service.

**Gate:** repeatable local benchmark JSON with environment and workload details;
no production-scale claim based only on a single-process laptop run.

## Phase 1 - retrieval quality and scale

- Expand the Chinese evaluation set with answerable, unanswerable, ambiguous,
  long-context, table/figure, and tenant-isolation cases.
- Evaluate a Chinese/multilingual embedding model against lexical and fusion
  baselines before changing defaults.
- Add reranking only when it improves grounded retrieval metrics enough to
  justify its latency and memory cost.
- Move high-volume dense retrieval to Qdrant with tenant and knowledge-base
  filters; keep a tested rollback path to the SQLite baseline.

**Gate:** retrieval quality, abstention quality, latency, memory, and index-size
reports from the same frozen corpus and queries.

## Phase 2 - agent workflow and durable execution

- Replace the single bounded evidence call with a policy-controlled registry of
  read-only tools such as text search, visual search, metadata lookup, and
  system status.
- Add LangGraph checkpointing for resumable long-running workflows.
- Keep user conversation memory separate from evidence and authorization state;
  never let memory bypass tenant or citation checks.
- Add per-tool timeout, retry budget, circuit breaker, trace, and maximum-step
  limits.

**Gate:** deterministic graph tests, interruption/resume tests, tool-policy
tests, tenant-boundary tests, and failure-injection runs.

## Phase 3 - production deployment

- PostgreSQL for transactional multi-user state and durable audit data.
- Redis-backed queue/cache/rate limiting where measurements justify it.
- Qdrant replication/backups for vector search where the corpus outgrows the
  embedded baseline.
- Horizontally replicated stateless FastAPI workers behind a reverse proxy;
  ingestion and summary workers remain separate.
- SSO/RBAC, secret manager integration, structured logs, OpenTelemetry, SLOs,
  backup/restore drills, and controlled schema/index migrations.

**Gate:** load test against an explicit SLO, multi-instance tenant/security
tests, restore drill, rolling-upgrade/rollback evidence, and deployment smoke.

## Decision record policy

Every engine or model change must record:

1. frozen dataset and query IDs;
2. exact versions and configuration;
3. quality metrics and abstention errors;
4. latency distribution and resource use;
5. migration and rollback procedure;
6. the reason the candidate is accepted or rejected.

This prevents an attractive framework name or one favorable demo query from
silently becoming the production default.

## V3.4 progress checkpoint

| Area | Current evidence | Remaining enterprise gate |
|---|---|---|
| Vue console | Admin-only engine lab, four-engine side-by-side run, route/reason and Provider capacity/circuit/deadline/retry-budget panels | SSO-driven identity, accessibility regression suite, deployed Docker image QA |
| Adaptive routing | Tuning set, held-out v1, challenge v2, and frozen challenge v3; v3 adds typo/noise, low-overlap and three-source cases with zero leakage checks and exposes lower adaptive scores | Production-log blind set, answer-generation/grounding scoring, Chinese embedding bake-off, evidence-driven routing improvement |
| Online concurrency | AsyncClient, `.ainvoke()`, off-loop work, bounded fair tenant scheduling, classified retry, breaker, explicit 503/504, one end-to-end deadline, bounded Retry-After+jitter, global/per-tenant retry token buckets | Soak/open-loop tests, Provider idempotency/duplicate-billing policy, client-disconnect evidence |
| Deployment-wide quota | Process-local limits are observable and explicitly labelled | Redis/gateway/provider-proxy lease with TTL, fencing and multi-worker socket tests |
| Background model work | Ingestion/summary jobs retain durable SQLite lease semantics; V3.4 records a fixed online/batch partition and migration contract | Implement async batch adapter, step fairness, lease fencing/heartbeat/cancel and Provider-call ledger |
| Data plane | SQLite WAL baseline remains reproducible | PostgreSQL/RLS migration, Qdrant decision gate, backup/restore and rollback drills |

V3.4 is therefore a verified single-process online-resilience and harder-evaluation milestone, not a claim
of production-scale horizontal deployment.
