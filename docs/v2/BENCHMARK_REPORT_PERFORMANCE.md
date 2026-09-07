# V2 Hardened Local Performance Profile

Date: 2026-09-07. Raw samples: [`reports/v2-performance-profile.json`](../../reports/v2-performance-profile.json).

## Profile

- Windows 10 compatibility host (`10.0.22631`), Python 3.11.5;
- FastAPI `TestClient`, one process, temporary SQLite database;
- `AUTH_MODE=api_key`, so API timings include scrypt credential verification;
- 20 frozen bilingual synthetic runbooks, 120 search requests, 30 answer requests;
- OCR and remote model generation disabled; cached `BAAI/bge-reranker-base` used for 20 Top-10 calls.

| Stage | Samples | Mean | p95 |
|---|---:|---:|---:|
| async upload accept (multipart + auth + queue write) | 20 | 45.347 ms | 50.111 ms |
| worker total (claim + parse + persist/index + metrics) | 20 | 24.727 ms | 25.949 ms |
| Markdown parser stage | 20 | 0.125 ms | 0.087 ms |
| persist/index stage | 20 | 9.234 ms | 9.824 ms |
| authenticated search API, auto/BM25 | 120 | 56.127 ms | 76.903 ms |
| BGE CrossEncoder rerank, ten candidates | 20 | 369.715 ms | 409.762 ms |
| authenticated offline-answer API | 30 | 73.866 ms | 81.472 ms |

The parser mean exceeds its p95 because one warm-path outlier affects the mean while 95% of the tiny
Markdown parses remain below the reported p95 sample. The raw ordered-independent samples are committed so
this shape is inspectable rather than rounded away.

Cached reranker construction took `3718.187 ms`; network download time was excluded. All 30 answer requests
used `offline-extractive` and none abstained for this answerable slice.

## Decision

The selected local release profile remains SQLite + BM25/RRF without online BGE. On this small corpus,
authenticated BM25 search stays below 77 ms p95 and offline answer below 82 ms p95. BGE alone adds about
370 ms mean per query and has a multi-second process load cost. Its frozen retrieval-quality gain is real but
too small for the default latency budget, so it remains a reproducible offline experiment.

The result also shows the hardened API boundary cost: upload/search/answer wall time includes CPU-hard scrypt
verification, while the worker stages do not. This is intentional security work, not unexplained parser or
retrieval latency.

## Reproduce

```powershell
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe .\evals\benchmark_v2_performance.py `
  --answer-cases 30 --rerank-cases 20 `
  --output .\reports\v2-performance-profile.json
```

## Limits

This is a stage-level single-host latency profile, not a concurrent load or hospital-capacity claim. OCR has
its own generated-fixture benchmark, and remote model latency depends on a provider not configured in this
run. Model files were cached. The test corpus is synthetic and small; results must be rerun on the deployment
hardware and traffic distribution before setting an SLO.
