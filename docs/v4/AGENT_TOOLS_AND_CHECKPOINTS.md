# V3.2 Agent tools and checkpoint baseline

## Scope delivered

The answer path now uses a code-owned, deterministic read-only tool registry.
It is a safety baseline for a future multi-tool LangGraph workflow, not a claim
that the agent can perform arbitrary actions.

| Tool | Selected when | Side effects |
|---|---|---|
| `grounded_text_answer` | The server routes the question to text evidence | Reads tenant-scoped knowledge and calls the configured answer model |
| `grounded_visual_answer` | The server routes the question to visual evidence | Reads tenant-scoped artifacts and calls the configured answer model |
| `verify_citation_scope` | An answer result exists in the HTTP answer path | Re-resolves every result document under the authenticated tenant |

The planner permits at most **2 tool calls** and **6 recorded graph steps** per
answer. Policy-denied questions execute zero tools. The tool plan is derived
from the effective server-side `AnswerRequest`; it is not accepted from model
output or from an end-user request.

Direct `POST /tools/call` remains available for administrator diagnostics and
benchmarking, but API-key viewers and editors receive `403 permission_denied`.
Viewers and editors also continue to have their retrieval and orchestration
fields replaced by managed defaults before the graph runs.

## Citation boundary

The answer service already retrieves by `tenant_id`. The graph now adds a
second fail-closed boundary after the primary grounded-answer tool:

1. collect document IDs from text citations, visual citations, retrieved text,
   and retrieved visual artifacts;
2. resolve every ID using the authenticated tenant;
3. if any resolution fails or the verifier raises, erase all evidence and
   citations and return `citation_scope_violation` as an abstention;
4. run the existing citation-presence grounding gate.

The verifier is server-injected. Neither the question nor a model response can
replace it.

## SQLite checkpoint contract

`POST /answer` accepts an optional opaque header:

```http
X-MedOps-Thread-Id: thread-demo-001
```

If omitted, the server generates a 32-character identifier. Every successful
response returns:

```http
X-MedOps-Thread-Id: <logical conversation id>
X-MedOps-Run-Id: <server request id>
```

If the most recent checkpoint for the same tenant, actor, and thread ended in
`running` or `failed`, the next read-only replay also returns:

```http
X-MedOps-Resumed-From-Run-Id: <previous run id>
```

The database lookup key is `(tenant_id, actor, thread_id)`. There is no fallback
lookup by `thread_id`, so guessing another tenant's identifier cannot expose or
resume its state.

Checkpoints store only:

- tenant and actor boundary;
- thread ID and server run ID;
- monotonically increasing phase sequence;
- route, bounded tool names, tool-call count, and terminal status;
- optional resumed-from run ID.

They deliberately do **not** store questions, prompts, model answers, retrieved
chunks, citations, credentials, or conversation messages. A resumed run starts
the read-only graph again under the current identity and policy. It does not
reuse previously authorized evidence. This makes the current implementation a
durable control-state/replay prototype, not semantic chat memory.

## Remaining production work

1. Move checkpoint persistence to PostgreSQL before enabling multi-worker
   recovery at scale; SQLite writes are suitable only for the current bounded
   baseline.
2. Add expiry and deletion policy for checkpoint rows.
3. Add optimistic ownership/lease fields before supporting concurrent retries
   of the same thread.
4. Store any future conversation memory in a separate encrypted, tenant-scoped
   store with explicit retention and redaction. Never inject memory into a new
   answer until the current request has passed authorization and retrieval
   policy again.
5. Add additional tools only after each has an argument schema, tenant-aware
   executor, timeout, per-tool call budget, audit event, and adversarial tests.
