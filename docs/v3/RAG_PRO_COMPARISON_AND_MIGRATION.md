# RAG-Pro comparison, MCP migration, and console redesign

[中文版本](RAG_PRO_COMPARISON_AND_MIGRATION_CN.md)

## Audit scope

- Source project: `D:/Codex Program files/RAG-Pro`, inspected as a local source snapshot rather than a Git worktree.
- Target project: MedOps RAG V3.4.
- Findings are based on source code, dependencies, routes, runtime-data layout, and browser inspection—not README claims alone.

## Transferable RAG-Pro advantages

| Advantage | RAG-Pro implementation evidence | MedOps decision |
|---|---|---|
| Broader end-user workflow | Conversation history, shortcuts, model settings, API/MCP test pages, `models/conversation.py`, `shortcut.py`, and dedicated Vue views | Reuse the interaction model, not its tenant-unaware persistence layer |
| True streaming chat UX | `api/v1/chat.py` and the Chat view emit and consume SSE incrementally | Worth adding later; MedOps `/answer` currently returns one bounded response |
| Rich presentation outputs | Chart, Report, Webpage, and Data agents with ECharts rendering, previews, and page publishing | Treat these as evidence-derived presentations; never bypass citation or read-only-tool gates |
| Broad model-provider coverage | LiteLLM connects OpenAI, Anthropic, DeepSeek, Ollama, Zhipu, Qwen, and vLLM | A Provider registry is useful, but MedOps keeps its verified fairness, deadline, retry, and circuit-breaker controls |
| Strong local semantic defaults | The snapshot bundles BGE-M3, BGE reranker v2 m3, Milvus Lite, and selectable chunking | Benchmark before adoption; model binaries and runtime data must remain outside the MedOps Git history |
| Approachable product design | Rounded dark navigation, soft radial gradients, colorful statistics, and direct feature entry points | Adopted without removing identity, role, health, audit, and medical-boundary controls |

RAG-Pro is ahead mainly in **product breadth and demonstration polish**, not medical production safety. MedOps remains
stronger in tenant isolation, server-side API-key identity resolution, role enforcement, PII-safe auditing,
prompt-injection isolation, medical-advice denial, official-source corpora, explainable retrieval, provider resilience,
and automated regression coverage.

## Why the RAG-Pro MCP files were not copied

The RAG-Pro MCP layer is a handwritten JSON-RPC/SSE adapter with several source-level defects:

1. It advertises a fixed legacy protocol version instead of using the official SDK for initialization, capability negotiation, and input schemas.
2. Documentation mentions `rag_search`, while the runtime tool registry only exposes knowledge-base listing and chat.
3. The tool schema accepts `top_k`, but the value is never propagated into the retrieval call.
4. It does not reuse tenant authentication, role enforcement, citation-scope verification, or the audit trail.
5. The LLM configuration field is named `encrypted`, but the implementation still stores and reads the key directly behind TODO comments.

The migration therefore reimplements the capability instead of copying the adapter.

## MedOps MCP implementation

- Endpoint: `POST /mcp/`, using Streamable HTTP, JSON responses, and stateless sessions.
- SDK constraint: `mcp>=2.2,<3.0`.
- Tools:
  - `list_knowledge_bases`: list knowledge bases visible to the authenticated tenant;
  - `rag_search`: perform evidence-only tenant-scoped retrieval with validated, effective `top_k`;
  - `rag_answer`: run the policy-controlled LangGraph answer path and return citations, abstention reasons, and Agent steps.
- Identity: local development may use `X-Tenant-ID` and `X-Actor-ID`; production `api_key` mode trusts only the
  tenant, role, and actor resolved from the server-side hashed credential.
- Safety: viewer/editor control reduction, medical-advice denial, tenant citation verification, PII-safe auditing,
  and read-only behavior remain enforced.
- Transport: Host and browser Origin are loopback-only by default, each message is limited to 1 MiB, and production
  deployments explicitly configure `MCP_ALLOWED_HOSTS` and `MCP_ALLOWED_ORIGINS`.

### Client configuration

Local trusted-header mode:

```json
{
  "url": "http://127.0.0.1:8000/mcp/",
  "headers": {
    "X-Tenant-ID": "hospital-a",
    "X-Actor-ID": "local-mcp"
  }
}
```

Production API-key mode:

```json
{
  "url": "https://medops.example.com/mcp/",
  "headers": {
    "Authorization": "Bearer <one-time-issued-api-key>"
  }
}
```

## Console redesign

The MedOps console does not copy RAG-Pro components. It transfers the information architecture and visual rhythm:

- the left enterprise sidebar becomes a rounded dark top navigation bar with five visible primary destinations;
- coral, cyan, mint, and violet gradients distinguish hero and statistics surfaces;
- tenant, actor, role, health, and medical-use boundary indicators remain visible;
- a dedicated MCP page performs real `initialize` and `tools/list` calls and displays the negotiated version and tool schemas;
- narrow layouts collapse into vertical navigation without sacrificing knowledge-base, document, evidence-QA, or admin workflows.

## Acceptance gates

```powershell
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m pytest -q
Push-Location .\frontend
npm run typecheck
npm run build
Pop-Location
git diff --check
```

MCP acceptance covers initialization, schemas, tenant isolation, server-side API-key binding, medical-advice denial,
Origin enforcement, and audit persistence. Console acceptance uses a live API to inspect the dashboard and MCP page;
a successful TypeScript build alone is not presented as visual proof.

## Explicitly excluded

- RAG-Pro model binaries, `venv`, SQLite runtime databases, uploads, and published HTML;
- LLM configuration persistence without an authentication boundary;
- the handwritten legacy MCP adapter and ineffective `top_k` argument;
- arbitrary Chart/Report/Webpage agents without citation enforcement;
- capabilities that appear only in documentation and cannot be verified in source or tests.
