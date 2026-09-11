# Adaptive retrieval held-out Chinese evaluation

## Why this dataset exists

The first V3 adaptive-routing report reused `v2_retrieval_cases.jsonl`, the same
small corpus observed while the deterministic thresholds were developed.  Its
result is useful as a regression check, but it cannot be treated as independent
evidence of generalization.

This evaluation therefore uses two new, manually authored files:

- `evals/adaptive_heldout_documents_zh.jsonl`
- `evals/adaptive_heldout_cases_zh.jsonl`

There is zero exact normalized-question overlap with the V2 tuning cases.  The
40 questions are Chinese and contain eight each of `exact`, `paraphrase`,
`multi_concept`, `long_context`, and `unanswerable`.  They are individually
worded rather than generated from one repeated question template.  All eight
long-context targets exceed the 350-character child boundary and split into at
least two retrieval children.

This is an **independent file-level holdout**, not a blinded or preregistered
production study.  The corpus was written after the routing policy existed, so
the report deliberately does not call it an unbiased estimate of production
quality.

## Reproduce safely

Prerequisite: the multilingual MiniLM model must already exist under
`data/models/fastembed`.  The runner forces `HF_HUB_OFFLINE=1`, forces
`TRANSFORMERS_OFFLINE=1`, and passes `local_files_only=True`.  It fails with a
clear message rather than downloading a missing model.  It never reads the
DeepSeek dotenv file and makes zero provider/application API calls.

```powershell
uv run python evals/benchmark_adaptive_heldout_zh.py --repetitions 3
uv run pytest -q tests/test_adaptive_heldout_benchmark.py
```

The versioned output is `reports/adaptive-routing-heldout-zh-v1.json`.  Dataset
SHA-256 hashes, dependency versions, offline flags, model identity and query
repetition count are embedded in the report.

## Current measured result

Environment: Python 3.11.5, FastEmbed 0.7.4, NumPy 2.4.6, rank-bm25 0.2.2,
Windows 10 build 22631.  Per-query latency excludes the one-time 3,922.137 ms
model load plus document indexing cost.

| Retrieval path | Hit@1 | Hit@3 | Hit@5 | mean | p95 |
|---|---:|---:|---:|---:|---:|
| Fixed BM25 | 1.0000 | 1.0000 | 1.0000 | 0.568 ms | 0.926 ms |
| Fixed RRF | 0.9062 | 0.9688 | 1.0000 | 73.764 ms | 86.704 ms |
| Fixed parent-child | 1.0000 | 1.0000 | 1.0000 | 0.707 ms | 1.221 ms |
| Adaptive | 1.0000 | 1.0000 | 1.0000 | 24.064 ms | 81.143 ms |

Adaptive selected BM25 for 16 questions, RRF for 10, and parent-child for six.
It tied the best fixed Hit@1 rather than beating it.  The result is still useful:

1. RRF was not universally better; it lost three exact/long-context top ranks,
   while all relevant documents remained inside Top-5.
2. Adaptive retained perfect Hit@1 on this set and avoided paying dense-query
   latency for 22 of 32 answerable questions.
3. Two manually labeled multi-concept questions and two long-context questions
   did not select the matching conceptual route.  Labels describe evaluation
   intent, not an oracle strategy, but these traces are candidates for the next
   **training/development** set.  The held-out result must not be tuned in place.
4. Parent-child and BM25 both reached 1.0 at source-level ranking.  This report
   does not claim that their returned context completeness is equal; it does not
   score generated answers or evidence coverage.

## Why negatives are excluded from Hit@K

The eight unanswerable questions deliberately have no relevant document.
Therefore they do not enter Hit@K, MRR, or nDCG denominators.  The report still
records their route and reason distributions: BM25 4, RRF 3, parent-child 1.
Those selections are not false answers—the retrieval router is not the domain,
abstention, tenant-policy, or citation-sufficiency gate.

## What this result does not prove

- It is 20 synthetic operations documents, not production traffic or clinical
  validation.
- Relevance is one source per question; there are no graded or multi-source
  judgments.
- Latency is a workstation snapshot, not a concurrency or capacity result.
- MiniLM was available from cache; this does not establish it as the best
  Chinese embedding model.
- A future threshold change requires a separate development split and another
  untouched evaluation set.  Repeatedly tuning against this file would destroy
  its held-out status.
