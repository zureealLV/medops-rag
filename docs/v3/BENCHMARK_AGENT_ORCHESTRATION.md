# Agent orchestration benchmark

Raw data:

- `reports/agent-orchestration-benchmark-v3.json`
- `reports/chunk-profile-benchmark-v3.json`
- `reports/chunk-profile-official-v3.json`
- `reports/deepseek-live-benchmark-v3.json`

## Controlled comparison

- Environment: local Windows CPU, deterministic offline answer provider.
- Dataset: `evals/dataset.jsonl`, 30 cases (25 answerable, 5 should abstain).
- Repetitions: 20 per mode, 600 end-to-end calls per mode.
- Versions: LangChain 1.4.0, LangGraph 1.2.11.
- Retriever, prompt, policy, evidence and generated answer are identical across modes.

| Mode | Hit@5 | Citation correctness | Correct abstention | Mean ms | Median ms | P95 ms | Mean overhead |
|---|---:|---:|---:|---:|---:|---:|---:|
| Classic Python | 1.0000 | 1.0000 | 1.0000 | 6.030 | 6.538 | 9.009 | baseline |
| LangChain LCEL | 1.0000 | 1.0000 | 1.0000 | 6.931 | 7.365 | 10.487 | +0.901 ms |
| LangGraph | 1.0000 | 1.0000 | 1.0000 | 8.016 | 8.381 | 11.985 | +1.986 ms |

Exact answer/refusal/citation parity with Classic is 1.0000 for both LangChain and LangGraph.

## Interpretation

LangGraph costs about 1.99 ms per local offline call in this small graph. That overhead is measurable but tiny
compared with network model latency. It does not improve answer quality by itself; its value is explicit state,
conditional edges, traceability, checkpointing and future human-in-the-loop/tool-node control.

LangChain LCEL is the lower-overhead choice for a fixed linear RAG chain. LangGraph is the better default only
when the product needs visible routing, bounded tools, recovery or stateful multi-step execution.

## Existing retrieval and chunk evidence

These results predate the Agent layer but remain authoritative because orchestration does not change retrieval:

| Experiment | Quality result | Mean latency | Decision |
|---|---|---:|---|
| BM25, frozen 120 positives | Hit@1 0.9583, Hit@5 1.0000 | 0.497 ms | strong CPU baseline |
| MiniLM dense | Hit@1 0.9417, Hit@5 0.9917 | 129.747 ms | not a default win |
| BM25 + MiniLM RRF | Hit@1 0.9917, Hit@5 1.0000 | 130.244 ms | quality gain, large latency cost |
| RRF + BGE rerank | Hit@1 1.0000 | 1082.388 ms | too slow for the default path |
| Legacy 600-char context | linked action recovered 0/50 | 13.628 ms | incomplete long-range context |
| Parent-child context | linked action recovered 50/50 | 19.702 ms | opt-in completeness win |

The parent-child test proves that chunk strategy can improve context completeness, while the Agent benchmark proves
that orchestration alone does not change retrieval quality.

## Direct chunk-profile comparison

This additional frozen test uses seven committed Chinese medical/device documents and seven source/answer checks.
BM25 is held constant so only the chunk plan changes.

| Chunk profile | Chunks | Duplicate chars | Mid-sentence cuts | Hit@1 | Complete@1 | Query mean |
|---|---:|---:|---:|---:|---:|---:|
| EnterpriseQA-style fixed 500/50 | 12 | 6.74% | 40.00% | 1.0000 | 1.0000 | 0.228 ms |
| MedOps semantic 500/50 | 12 | 10.11% | 0.00% | 1.0000 | 1.0000 | 0.163 ms |
| MedOps semantic 600/80 | 9 | 6.06% | 0.00% | 1.0000 | 1.0000 | 0.130 ms |
| Parent-child 1600/350/50 | 15 | 13.99% | 12.50% | 1.0000 | 1.0000 | 0.146 ms |

On this small corpus, all profiles retrieve the correct source and complete answer context. Semantic 600/80 uses
the fewest chunks, has the lowest duplicate-character ratio, avoids mid-sentence cuts and is the fastest measured
profile. This supports keeping it as the concise-document default. Parent-child remains valuable for long-range
context because the separate 50-case fixture recovered linked actions in 50/50 cases instead of 0/50.

## Official Chinese PDF chunk comparison

The larger direct comparison parses the six hash-pinned Chinese government PDFs (157,761 extracted characters)
and evaluates six answerable questions using the same BM25 0.2.2 retriever.

| Chunk profile | Chunks | Duplicate chars | Mid-sentence cuts | Hit@1 / Hit@5 | Complete@1 / @5 | Query mean |
|---|---:|---:|---:|---:|---:|---:|
| EnterpriseQA-style fixed 500/50 | 353 | 11.00% | 98.27% | 1.0000 / 1.0000 | 0.8333 / 1.0000 | 2.139 ms |
| MedOps semantic 500/50 | 393 | 14.17% | 45.74% | 1.0000 / 1.0000 | 0.8333 / 1.0000 | 2.260 ms |
| MedOps semantic 600/80 | 354 | 20.38% | 42.53% | 1.0000 / 1.0000 | 0.8333 / 1.0000 | 2.233 ms |
| Parent-child 1600/350/50 | 616 | 18.04% | 44.26% | 1.0000 / 1.0000 | 0.8333 / 1.0000 | 3.172 ms |

The fixed windows cut nearly every internal PDF chunk mid-sentence (98.27%). Semantic 600/80 lowers this to
42.53%, while all profiles recover complete answer context by top 5. Parent-child is not a universal winner here:
it creates the largest index and highest query latency, but remains justified by the separate long-range 50-case
test where it recovered linked context that fixed chunks missed entirely.

## Live DeepSeek V4 Flash comparison

- Observed: 2026-09-09 11:13:49 UTC.
- Dataset: 8 official-corpus cases (6 answerable, 2 policy refusals), three repetitions and 24 runs per mode.
- Order: counterbalanced across modes to reduce consistent connection/cache position bias.
- Model: `deepseek-v4-flash` at `https://api.deepseek.com`; all 54 answerable calls used the live provider.
- The API key was loaded from a user-supplied external dotenv file and was not written to the report.

| Mode | Case / retrieval / citation / answer / refusal | Mean | Median | P95 | Total tokens | Estimated USD off-peak / peak |
|---|---:|---:|---:|---:|---:|---:|
| Classic Python | all 1.0000 | 2332.197 ms | 2181.591 ms | 4854.881 ms | 29,707 | $0.00288798 / $0.00577596 |
| LangChain LCEL | all 1.0000 | 2269.603 ms | 2382.796 ms | 4530.450 ms | 29,800 | $0.00294936 / $0.00589872 |
| LangGraph | all 1.0000 | 2294.754 ms | 2431.416 ms | 5323.582 ms | 29,638 | $0.00284244 / $0.00568488 |

This live smoke run proves endpoint compatibility, provider success, citation/refusal behavior and real token/cost
capture. It does **not** prove small latency differences between frameworks: each framework received separate
generative responses, the suite has only eight distinct cases, and network/model variance dominates the 1.986 ms
framework overhead isolated by the repeated offline benchmark.

## Reproduce

```powershell
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe .\evals\run_eval.py
.\.venv\Scripts\python.exe .\evals\benchmark_agent_orchestration.py --repetitions 20
.\.venv\Scripts\python.exe .\evals\benchmark_chunk_profiles.py
.\.venv\Scripts\python.exe .\evals\benchmark_official_chunk_profiles.py
# Paid live run; key may be MODEL_API_KEY/DEEPSEEK_API_KEY in the process or dotenv file.
.\.venv\Scripts\python.exe .\evals\benchmark_deepseek_live.py --env-file <external-.env-path>
```

## Limitations

- The repeated orchestration benchmark uses the deterministic provider to isolate framework overhead.
- The live benchmark has only eight distinct cases; it is evidence of compatibility, not a stable latency ranking.
- Both chunk suites have saturated source retrieval; boundary/context metrics are more informative than Hit@1.
- None of these educational benchmarks establishes clinical validity.
