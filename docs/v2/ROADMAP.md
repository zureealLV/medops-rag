# MedOps Multimodal RAG V2 — Execution Roadmap

The project is implemented as an evolving branch, not as disconnected daily demos. Every gate requires code,
tests, benchmark evidence, and an explicit non-goal list.

## Gate 1 — Alpha.1: multiformat ingestion and baseline evidence

Status: implemented and locally verified; feature-branch publication pending.

- [x] parser registry for TXT/MD/PDF/DOCX/PPTX/PNG/JPEG/WebP;
- [x] native text, table, and OCR element normalization;
- [x] conditional PDF OCR and embedded-picture OCR;
- [x] SHA-256 idempotent uploads and provenance endpoint;
- [x] upload byte and decoded-pixel limits;
- [x] BM25/RRF strategy surface;
- [x] local parser, retrieval, semantic, and reranker benchmarks;
- [x] runtime HTTP smoke test after all documentation changes;
- [ ] commit and publish feature branch after review.

Non-goals: background workers, visual embeddings, VLM reasoning, Chroma/Qdrant, HyDE, production auth.

## Gate 2 — Alpha.2: first-class image evidence

- [ ] add `artifacts` storage with SHA-256, MIME, dimensions, and source location;
- [ ] persist PDF/PPTX/DOCX image bytes without duplicating identical artifacts;
- [ ] add bounding boxes/shape coordinates to element provenance;
- [ ] implement `ImageEmbeddingProvider` with an offline model and a disabled remote-provider adapter;
- [ ] compare OCR-only, image-only, and fused image+text retrieval;
- [ ] return page/slide/region visual citations;
- [ ] add at least 20 visual-only or image-essential held-out questions;
- [ ] prove tenant isolation for image artifacts.

Acceptance: a question whose answer exists only in a screenshot or diagram retrieves the correct artifact and
returns a verifiable visual citation. OCR text alone must not be sufficient for every visual test.

## Gate 3 — Beta.1: parent-child hybrid retrieval

- [ ] add parent/child chunk schema and migration;
- [ ] build structure-aware chunks from normalized elements;
- [ ] freeze the V2 evaluation split and record dataset hashes;
- [ ] implement pluggable hashing/MiniLM/BGE-M3-or-E5 embedding profiles;
- [ ] compare SQLite scan, Chroma, and Qdrant on 1k/10k/100k synthetic chunks;
- [ ] select fusion method from held-out Hit@K/MRR/nDCG and filtered-query behavior;
- [ ] enable BGE reranking only when quality gain justifies CPU/memory/latency;
- [ ] implement HyDE behind a query policy and compare against rewrite/multi-query/no-transform baselines.

Acceptance: the selected default wins on the held-out set under a documented latency/memory budget. A more
complex pipeline that ties a simpler one does not win.

## Gate 4 — Beta.2: asynchronous ingestion and summaries

- [ ] persisted job state machine: queued/running/succeeded/failed/partial/cancelled;
- [ ] idempotency keys, leases, bounded retries, timeouts, and crash recovery;
- [ ] isolated worker for parsing/OCR/embedding;
- [ ] Map-Reduce multi-document summary with per-map and final citations;
- [ ] partial result semantics and 30-second model timeout;
- [ ] Redis/Celery versus database-backed worker benchmark before selection;
- [ ] concurrency, restart, duplicate-delivery, and poison-document tests.

Acceptance: kill the worker during OCR and Map-Reduce, restart it, and prove completed work is not duplicated
and partial failures remain visible.

## Gate 5 — V2.0: release hardening

- [ ] authenticated user identity and authorization policy;
- [ ] parser fuzzing and decompression-bomb/archive abuse cases;
- [ ] performance profile for upload, index, search, rerank, and answer;
- [ ] observability for job queue, parser/OCR, retrieval stages, model calls, and fallback;
- [ ] Docker Compose for API, worker, selected vector index, and persistent volumes;
- [ ] migration-from-v1 test and rollback instructions;
- [ ] bilingual README, architecture diagram, threat model, demo, and benchmark reproduction;
- [ ] release tag only after fresh-clone validation.
