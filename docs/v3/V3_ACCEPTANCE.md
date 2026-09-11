# MedOps V3.0 acceptance record

## Scope

V3.0 promotes MedOps from a fixed RAG answer chain to a bounded medical-health knowledge Agent while retaining
the existing public-evidence, tenant-isolation and educational-safety boundaries.

## Requirement evidence

| Requirement | Implemented evidence | Verification evidence |
|---|---|---|
| Agent RAG | `app/agents/orchestration.py`: conditional policy branch, allowlisted `grounded_medical_answer` tool, maximum one tool call, grounding verifier and trace | `tests/test_agent_orchestration.py`; 30-case three-mode benchmark |
| DeepSeek instead of local Ollama | `app/config.py` defaults to `https://api.deepseek.com` / `deepseek-v4-flash`; `MODEL_API_KEY` and `DEEPSEEK_API_KEY` accepted | mocked payload test plus live report with 18 successful answerable provider calls per mode, 54 total |
| MedOps + EnterpriseQA lessons | `docs/v3/ENTERPRISEQA_SOURCE_REVIEW.md` records the original functions, exact stack, structure, fixed LCEL chain and security gaps; V3 keeps the product loop but not unsafe defaults | browser JavaScript syntax check and chunk reports |
| LangGraph vs LangChain | Classic, LCEL and LangGraph run the same retriever, policy, prompt, model and thresholds | 600 offline calls per mode plus 24 live runs per mode |
| Chunk strategy comparison | fixed 500/50, semantic 500/50, semantic 600/80 and parent-child 1600/350/50 | concise seven-document and official six-PDF reports |
| Medical safety | advice refusal, unsupported-domain abstention, evidence-injection quarantine and citation enforcement remain before/after tool execution | full automated suite and frozen evaluation |

## Accepted measured results

- Offline orchestration: 600 calls per mode; all three modes reached Hit@5, citation correctness and correct
  abstention of 1.0000. Mean overhead over Classic was 0.901 ms for LangChain LCEL and 1.986 ms for LangGraph.
- Live DeepSeek: 8 cases, 3 repetitions and 24 runs per mode, with 54 answerable live calls total; all quality
  metrics and live provider success were 1.0000. This proves compatibility and telemetry, not latency superiority
  on a broad workload.
- Official chunk corpus: 6 PDFs, 157,761 extracted characters. Every profile reached Hit@5 and complete context
  at 5 of 1.0000. Fixed 500/50 cut 98.27% of internal chunks mid-sentence; semantic 600/80 reduced that metric to
  42.53%. Parent-child produced the largest index here, so it remains opt-in for long-range context rather than a
  blanket default.
- The separate long-range fixture remains decisive for parent-child: linked context recovered 50/50 versus 0/50
  for legacy fixed context, at 19.702 ms versus 13.628 ms mean retrieval.
- The 15,000-document Huatuo catalog previously returned 20,291,013 bytes and rendered 15,000 table rows. The
  metadata-only 50-row page returned 16,124 bytes in 22.1 ms on the same database: 1,258.4x less payload, with
  exactly 50 rows rendered, bounded pagination and debounced title/source filtering.

## Reproduction gates

```powershell
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe -m ruff check app tests evals scripts
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe .\evals\run_eval.py
.\.venv\Scripts\python.exe .\evals\benchmark_agent_orchestration.py --repetitions 20
.\.venv\Scripts\python.exe .\evals\benchmark_chunk_profiles.py
.\.venv\Scripts\python.exe .\evals\benchmark_official_chunk_profiles.py
node --check .\web\app.js
```

Paid live reproduction is intentionally separate:

```powershell
.\.venv\Scripts\python.exe .\evals\benchmark_deepseek_live.py --env-file <external-.env-path>
```

The live runner writes answers and telemetry but never the API key.

## Non-claims

- V3.0 is not a diagnostic, prescribing or clinical decision-support system.
- Deterministic policy-controlled tool selection is intentional; the model cannot invent arbitrary tool loops.
- The current answer endpoint is request-stateless; durable conversation checkpoints remain future work.
- The benchmark sets are portfolio regression evidence, not proof of clinical validity.
