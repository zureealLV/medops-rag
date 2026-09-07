# V2 Beta.1 Filtered Vector Store Benchmark

Date: 2026-09-06. Windows 10, 64-dimensional normalized synthetic vectors, 100 tenant-filtered queries,
Top-10 recall measured against exact cosine. Qdrant `1.19.0` ran in embedded local mode and Chroma `1.5.9`
used persistent local mode. Raw reports are under `reports/vector-store-benchmark-*-v2-beta1.json`.

| vectors | store | index | p50 | p95 | Recall@10 | disk |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1k | NumPy exact baseline | 0.012 ms | 0.024 ms | 0.026 ms | 1.000 | 0.26 MB |
| 1k | Qdrant local | 1.920 s | 6.033 ms | 6.676 ms | 1.000 | 1.02 MB |
| 1k | Chroma persistent | 0.190 s | 1.730 ms | 2.091 ms | 1.000 | 1.22 MB |
| 10k | NumPy exact baseline | 0.531 ms | 0.359 ms | 0.424 ms | 1.000 | 2.56 MB |
| 10k | Qdrant local | 19.349 s | 60.542 ms | 63.263 ms | 1.000 | 10.54 MB |
| 10k | Chroma persistent | 1.700 s | 9.580 ms | 10.785 ms | 0.997 | 6.83 MB |
| 100k | NumPy exact baseline | 3.601 ms | 2.496 ms | 2.744 ms | 1.000 | 25.60 MB |
| 100k | Qdrant local | 264.502 s | 1071.046 ms | 1195.712 ms | 1.000 | 106.01 MB |
| 100k | Chroma persistent | 40.989 s | 160.754 ms | 174.110 ms | 0.938 | 63.82 MB |

The exact baseline wins on this small 64d in-memory workload. It excludes SQLite JSON decoding, startup, and
concurrent writes, so it is not a fair persistence-system victory. Chroma is much faster than embedded
Qdrant at scale but loses 6.2% Recall@10 at 100k. Qdrant itself warns local mode above 20k points and retained
exact recall, but its embedded latency is unacceptable here.

Decision: keep the exact local backend for the portfolio/local profile. Do not add a service merely for its
name. Chroma is not selected due to the measured recall loss.

## Qdrant server concurrency gate

Date: 2026-09-07. Qdrant Server `1.19.0` (Docker image digest
`sha256:057ee3a8da769fe7310dd3537b4dc7583bf87a95ce8ac43c0af5a46bc580d1fc`) and
`qdrant-client 1.19.0` were tested over HTTP from Windows. The workload used 10,000 normalized 64-dimensional
vectors split across 20 tenants, a keyword payload index, 400 Top-10 queries at concurrency 8, and
`hnsw_ef=128`. Every request filtered on its query tenant. The raw report is
`reports/qdrant-server-concurrent.json`; the reproducible driver is `evals/benchmark_qdrant_server.py`.

| index | throughput | mean | p50 | p95 | p99 | Recall@10 | tenant violations |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 14.329 s | 77.959 query/s | 94.726 ms | 94.451 ms | 119.350 ms | 131.626 ms | 1.000 | 0 |

This closes the server-mode release gate, but it is deliberately not a production-capacity claim: the test
used one local Docker/WSL node, synthetic low-dimensional vectors, no replication, no network fault, and no
concurrent ingestion. SQLite exact scan remains the shipped single-host default because it is simpler and
already wins the measured portfolio workload. Qdrant server is now an evidence-backed scale-out option for a
future workload that exceeds the local profile, not a dependency added for resume keyword density.
