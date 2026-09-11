# V2.3 Chinese Corpus and Retrieval Benchmark

Date: 2026-09-08

Host: Windows 10, Python 3.11.5, SQLite 3.42.0

Database: `data/runtime/medops.db`

## Corpus state

| Knowledge base | Records/documents | Chunks |
| --- | ---: | ---: |
| 华佗中文医学知识库（研究用途） | 15,000 | 18,097 |
| MedlinePlus 健康主题（NLM 官方） | 1,016 | 5,852 |

The Chinese corpus contains 12,000 knowledge-graph QA records and 3,000
encyclopedia QA records. It accounts for 93.7% of the two external-corpus
record count. The resulting local SQLite file was 331,575,296 bytes.

## Import behavior

- first Huatuo download and import: 208.45 seconds;
- immediate repeat: 1.9 seconds wall time;
- repeat result: `created=0 updated=0 skipped=15000`;
- raw subset files: 2,403,645 bytes (knowledge graph) and 5,000,639 bytes
  (encyclopedia);
- source revisions and subset SHA-256 values are recorded in
  `data/external/huatuo/sources.json`.

## Retrieval behavior

Before FTS candidate recall, three Chinese requests over 18,097 chunks took
7.0–7.6 seconds inside retrieval. With the trigger-maintained SQLite FTS5
trigram index, the same local profile returned documented questions in about
0.30–0.53 seconds inside retrieval. A live HTTP request for
`IGT和2型糖尿病的预防措施有些什么？` completed in 620 ms and returned
`合理的膳食和运动；控制体重` with its Huatuo source card.

This is a local functional benchmark, not a cross-machine service-level
guarantee. FTS narrows candidates; the existing BM25 and evidence-threshold
logic still makes the final retrieval decision.

The frozen 14-case Chinese acceptance gate produced 100% answer-and-citation
accuracy on ten exact medical cases, 100% correct abstention on two unrelated
questions and two patient-specific advice requests, 269.625 ms median retrieval
and 387.117 ms p95. The gate limit is 1,000 ms p95 on this local profile.

## Verification

```text
Ruff: all checks passed
Pytest: 97 passed, 2 dependency deprecation warnings
/health: {"status":"ok","version":"2.3.0","database":"ok"}
SQLite integrity_check: ok
```

The warnings originate from the installed Starlette/httpx compatibility shim
and are unrelated to corpus import or indexed retrieval.
