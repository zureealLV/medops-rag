# MedOps V3 Agent RAG upgrade

Status: implemented experimental bounded Agent layer; a live DeepSeek quality/latency/token/cost run is recorded.

## Goal

Upgrade MedOps into a bounded medical-health knowledge Agent without weakening its existing tenant isolation,
evidence thresholds, citations, abstention, prompt-injection isolation, or medical-advice refusal.

The EnterpriseQA reference project contributes two useful ideas: a visible knowledge-base-first chat flow and a
simple, explainable chunking pipeline. MedOps keeps its stronger FastAPI, audit, parser-security, multimodal,
hybrid-retrieval, worker, and benchmark foundations instead of replacing them with the reference project's
synchronous Flask/Chroma implementation.

## Implemented request path

`POST /answer` now accepts `orchestration`:

- `classic`: existing imperative Python workflow;
- `langchain`: the same workflow composed as LangChain LCEL runnables;
- `langgraph`: the default bounded state graph.

The LangGraph topology is deliberately small and inspectable. Policy-denied requests never pretend to execute a
retrieval tool, while accepted requests can execute at most one tenant-scoped evidence search:

```text
START
  -> route_question
       |-- policy denied -> apply_safety_policy --------|
       `-- policy passed -> select_read_only_tool       |
                            -> execute_grounded_medical_answer
  -> verify_grounding
  -> END
```

Every mode uses the same policy, retriever, prompt, model adapter and evidence thresholds. This is important for
fair comparisons: changing the retriever and the orchestration framework at the same time would make latency and
quality differences impossible to attribute.

The response contains `orchestration` and `agent_steps[]` alongside the existing answer, citations, retrieved
evidence, refusal reason, provider, latency and token usage. The Web console exposes all three engines and renders
the Agent path. The default is LangGraph.

## Why this is a bounded Agent

The graph has explicit state, a conditional policy edge, a named allowlisted read-only tool call, a hard
`max_calls=1` bound, a post-retrieval grounding verifier and a machine-readable execution trace. It is more than a
one-shot prompt chain, but it is intentionally not an unbounded ReAct loop. A medical knowledge system should not
let the model repeatedly invent tool calls or perform state-changing actions.

The answer graph exposes only this tool:

1. `grounded_medical_answer` — a composite read-only RAG tool that runs tenant-filtered retrieval, evidence
   thresholds, prompt-injection quarantine, generation and structured citation assembly as one atomic action.

The separate administrative tool endpoint retains these tenant-scoped read-only operations:

1. `search_documents`;
2. `get_document_metadata`;
3. `get_system_status`.

The existing allowlist continues to reject shell execution and unknown tools.

## DeepSeek V4 Flash

The default model endpoint is now the official OpenAI-compatible endpoint:

```dotenv
MODEL_API_KEY=<local secret; never commit>
MODEL_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-v4-flash
```

The adapter sends `POST /chat/completions`, uses a bounded timeout/retry policy, records reported token usage and
cache-hit/prompt/completion breakdowns, and falls back to the deterministic offline extractor on provider failure.
The API key remains empty in
`.env.example` and must be supplied locally. Both `MODEL_API_KEY` and `DEEPSEEK_API_KEY` are accepted. On Windows,
`scripts/run_dev.ps1 -EnvFile <external-.env-path>` loads only the allowlisted model settings into the child
development process and does not copy the secret into this repository.

The captured live run on 2026-09-09 used 8 official-corpus cases, 3 repetitions and 24 runs per mode. All three
modes reached 1.0000 case, retrieval, citation, answer-content and refusal accuracy. Mean end-to-end latency was
2332.197 ms for Classic, 2269.603 ms for LangChain LCEL and 2294.754 ms for LangGraph. See the benchmark document
for scope, token/cost figures and why eight distinct cases are not enough to rank network latency.

Official references:

- https://api-docs.deepseek.com/
- https://api-docs.deepseek.com/updates/
- https://docs.langchain.com/oss/python/langgraph/overview
- https://docs.langchain.com/oss/python/langgraph/graph-api

## What is not yet claimed

- The graph deliberately uses deterministic, policy-controlled tool selection rather than model-selected tools.
- Durable cross-request conversation memory and resumable checkpoints are not enabled yet.
- This remains an educational knowledge assistant, not a diagnostic or treatment system.

## Next measured gates

1. Expand the live suite beyond the completed 8-case/three-repetition smoke run.
2. Add a multi-turn ambiguity set and compare stateless, LangChain message history and LangGraph checkpoint state.
3. Expand the completed six-PDF/157,761-character chunk benchmark beyond six labelled answer questions.
4. Only promote a new default after it wins a held-out quality gate without unacceptable latency/cost regression.
