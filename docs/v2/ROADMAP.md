# MedOps Multimodal RAG V2 — Execution Roadmap

The project is implemented as an evolving branch, not as disconnected daily demos. Every gate requires code,
tests, benchmark evidence, and an explicit non-goal list.

## Gate 1 — Alpha.1: multiformat ingestion and baseline evidence

Status: implemented, locally verified, and published on the feature branch.

- [x] parser registry for TXT/MD/PDF/DOCX/PPTX/PNG/JPEG/WebP;
- [x] native text, table, and OCR element normalization;
- [x] conditional PDF OCR and embedded-picture OCR;
- [x] SHA-256 idempotent uploads and provenance endpoint;
- [x] upload byte and decoded-pixel limits;
- [x] BM25/RRF strategy surface;
- [x] local parser, retrieval, semantic, and reranker benchmarks;
- [x] runtime HTTP smoke test after all documentation changes;
- [x] commit and publish feature branch after review.

Non-goals: background workers, visual embeddings, VLM reasoning, Chroma/Qdrant, HyDE, production auth.

## Gate 2 — Alpha.2: first-class image evidence

- [x] add artifact storage with SHA-256, MIME, dimensions, and source location;
- [x] persist rendered PDF/PPTX/DOCX/raster image bytes without duplicating identical tenant blobs;
- [x] persist element bounding boxes for raster, PDF and PPTX fixed-layout sources;
- [x] implement `ImageEmbeddingProvider` with a disabled-by-default local ONNX profile;
- [x] compare OCR-only, image-only, and fused image+text retrieval;
- [x] return page/slide/region visual citations for fixed-layout sources;
- [x] add 20 visual-only fixtures with 20 English and 20 Chinese queries;
- [x] prove tenant isolation and tenant-local blob deduplication for image artifacts.
- [x] route `/answer` between text/visual retrieval and enforce similarity-plus-margin abstention;
- [x] return only model-loaded image evidence as answer citations and cap vision payload count/bytes.

Current evidence: English text-to-image Hit@1 is 0.95 for CLIP-B/32 and 1.00 for Jina CLIP v1 versus 0.05
for OCR-only. Both tested profiles score only 0.10 Chinese Hit@1, so the multilingual model gate remains open.

Acceptance: a question whose answer exists only in a screenshot or diagram retrieves the correct artifact and
returns a verifiable visual citation. OCR text alone must not be sufficient for every visual test.

The text-free icon acceptance path now passes through real CLIP retrieval and `/answer`. Full page/region
coordinates and real VLM chart reasoning remain open; the offline path deliberately returns only a locator.

## Gate 3 — Beta.1: parent-child hybrid retrieval

- [x] add parent/child chunk schema and additive migration;
- [x] build structure-aware chunks from normalized elements;
- [x] freeze a 120-answerable/20-negative V2 evaluation set and record dataset hashes;
- [x] implement pluggable hashing/MiniLM embedding profiles with persisted model identity;
- [x] compare exact local scan, Chroma persistent, and Qdrant local at 1k/10k/100k;
- [x] benchmark Qdrant Server 1.19.0 with 400 concurrent tenant-filtered queries over 10k vectors;
- [x] select BM25+MiniLM RRF for the opt-in dense profile from Hit@K/MRR/nDCG evidence;
- [x] keep BGE reranking offline because +0.83 Hit@1 point costs about +952 ms mean latency;
- [x] implement policy-gated template HyDE and compare it with rewrite/multi-query/no-transform baselines;
- [x] keep transformation off by default: HyDE dropped Hit@1 from 0.9917 to 0.7833.

Acceptance: the selected default wins on the held-out set under a documented latency/memory budget. A more
complex pipeline that ties a simpler one does not win.

Foundation evidence: on 50 synthetic long sections, both fixed BM25 and parent-child retrieval reached 1.00
Hit@1, but the linked action was present in 0/50 fixed contexts versus 50/50 reconstructed parents. Mean
latency increased from 13.628 ms to 19.702 ms. This validates reconstruction, not the final dense/fusion choice.

## Gate 4 — Beta.2: asynchronous ingestion and summaries

- [x] persisted single-file job states: queued/running/succeeded/failed/cancelled;
- [x] per-document summary maps, aggregate progress, and terminal `partial` state;
- [x] tenant-scoped idempotency keys, fenced leases, three-attempt retry bound, and expired-lease recovery;
- [x] isolated polling worker for parsing/OCR/chunking/embedding;
- [x] Map-Reduce multi-document summary with persisted per-map and final citations;
- [x] partial result semantics and hard 30-second per-model-call timeout;
- [x] benchmark real Redis/Celery against the database-backed worker and select SQLite for single-host V2;
- [x] lease restart, duplicate-delivery fencing, transient retry, cancellation and poison-document tests;
- [x] multi-process contention and abrupt worker-exit recovery tests for summary jobs;
- [x] abrupt worker-exit integration test during a blocking OCR/parser stage.

Acceptance: kill the worker during OCR and Map-Reduce, restart it, and prove completed work is not duplicated
and partial failures remain visible.

## Gate 5 — V2.0: release hardening

- [x] hashed API-key identity, immediate revocation, tenant binding, and viewer/editor/admin authorization;
- [x] deterministic malformed-input fuzzing plus Office expansion, entry, ratio, path and macro abuse gates;
- [x] raw-sample local profile for authenticated upload, parse/index, search, BGE rerank, and answer;
- [x] tenant-scoped queue age/state, parser/OCR, index, retrieval, model, provider and fallback metrics;
- [x] verified Compose for API, ingestion/summary workers, selected SQLite exact index, and persistent volumes;
- [x] exact V1 fixture migration, schema versioning, integrity-checked backup and tested full rollback;
- [x] bilingual README, architecture diagram, threat model, demo, and benchmark reproduction;
- [ ] release tag only after fresh-clone validation.
