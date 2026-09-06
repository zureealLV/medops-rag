# V2 Beta.1 Frozen Retrieval Benchmark

Date: 2026-09-06

Raw evidence: `reports/retrieval-benchmark-v2-beta1.json`

The frozen corpus contains 20 bilingual synthetic runbooks, 120 answerable questions across exact,
paraphrase, choice, and distractor categories, plus 20 out-of-scope negatives. SHA-256 identities are stored
in the raw report. Model files were cached; download time is excluded.

| Strategy | Hit@1 | MRR@5 | nDCG@5 | mean | p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| BM25 | 0.9583 | 0.9792 | 0.9846 | **0.497 ms** | **1.274 ms** |
| multilingual MiniLM | 0.9417 | 0.9628 | 0.9701 | 129.747 ms | 205.451 ms |
| BM25 + MiniLM RRF | **0.9917** | **0.9944** | **0.9958** | 130.244 ms | 206.169 ms |
| RRF + BGE reranker Top-10 | 1.0000 | 1.0000 | 1.0000 | 1082.388 ms | 1271.338 ms |

RRF gains 3.34 Hit@1 percentage points over BM25 at roughly 130 ms mean CPU cost. BGE gains only another
0.83 point while adding about 952 ms mean latency, so it is not enabled in the online path. `auto` resolves
to RRF when a real dense provider is enabled. Without it, `auto` uses BM25 for normal corpora and the legacy
weighted score for fewer than three rows because Okapi IDF can be non-positive in a one-row corpus.

This dataset is template-generated and has one relevant document per query. It is a versioned regression
gate, not evidence of production hospital quality. The negative set exposes raw score ranges but is not yet
sufficient for a universal abstention threshold.
