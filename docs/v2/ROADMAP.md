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
- [ ] add bounding boxes/shape coordinates to element provenance;
- [x] implement `ImageEmbeddingProvider` with a disabled-by-default local ONNX profile;
- [x] compare OCR-only, image-only, and fused image+text retrieval;
- [ ] return page/slide/region visual citations;
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
- [ ] freeze the V2 evaluation split and record dataset hashes;
- [ ] implement pluggable hashing/MiniLM/BGE-M3-or-E5 embedding profiles;
- [ ] compare SQLite scan, Chroma, and Qdrant on 1k/10k/100k synthetic chunks;
- [ ] select fusion method from held-out Hit@K/MRR/nDCG and filtered-query behavior;
- [ ] enable BGE reranking only when quality gain justifies CPU/memory/latency;
- [ ] implement HyDE behind a query policy and compare against rewrite/multi-query/no-transform baselines.

Acceptance: the selected default wins on the held-out set under a documented latency/memory budget. A more
complex pipeline that ties a simpler one does not win.

Foundation evidence: on 50 synthetic long sections, both fixed BM25 and parent-child retrieval reached 1.00
Hit@1, but the linked action was present in 0/50 fixed contexts versus 50/50 reconstructed parents. Mean
latency increased from 13.628 ms to 19.702 ms. This validates reconstruction, not the final dense/fusion choice.

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
