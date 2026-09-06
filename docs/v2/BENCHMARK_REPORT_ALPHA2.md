# V2 Alpha.2 Visual Retrieval Benchmark

Date: 2026-09-06

Raw evidence:

- `reports/visual-retrieval-benchmark-v2-alpha2.json`
- `reports/smoke-v2-alpha2-visual.json`

Code validation: Ruff passed; Pytest passed 38/38 tests. The visual smoke uses the real FastEmbed CLIP ONNX
models rather than the deterministic provider used by unit tests.

## 1. Question being tested

Can the system retrieve evidence that contains no searchable text, and does adding OCR help or hurt?

The fixture generator creates 20 white-background, 384x384 icons covering colors, geometric shapes, arrows,
cloud/lock/network/check symbols, and no intentional text. Each image has one English and one Chinese query,
for 40 text-to-image queries. This isolates cross-modal retrieval; it is not a chart-understanding benchmark.

## 2. Results

| Model/strategy | EN Hit@1 | EN MRR | ZH Hit@1 | ZH MRR |
| --- | ---: | ---: | ---: | ---: |
| OCR-only | 0.05 | 0.1799 | 0.05 | 0.1799 |
| Qdrant CLIP-B/32 image | 0.95 | 0.9750 | 0.10 | 0.2265 |
| Qdrant CLIP-B/32 80% + OCR 20% | 0.95 | 0.9750 | 0.10 | 0.2265 |
| Jina CLIP v1 image | **1.00** | **1.0000** | 0.10 | 0.2699 |
| Jina CLIP v1 80% + OCR 20% | **1.00** | **1.0000** | 0.10 | 0.2699 |

RapidOCR returned non-empty noise for 8/20 text-free icons. Fusion did not improve either CLIP model,
demonstrating why OCR output must not be treated as equivalent to visual semantics.

## 3. Local CPU latency and footprint

| Profile | Declared paired model size | Cached construction | Index 20 images | EN query mean | EN p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Qdrant CLIP-B/32 | ~0.59 GB | 1407.235 ms | **410.448 ms** | **12.122 ms** | **23.355 ms** |
| Jina CLIP v1 | ~0.89 GB | 1841.722 ms | 1428.047 ms | 32.633 ms | 81.631 ms |

OCR processing for the same 20 icons took 13,568.450 ms before its sub-millisecond BM25 query stage. CLIP
therefore costs vector storage and model memory but supplies the missing visual signal and indexes these
fixtures much faster than OCR.

The declared sizes come from FastEmbed 0.7.4 model metadata. The complete local FastEmbed cache is 2.68 GiB
because it also contains earlier MiniLM and BGE benchmark models. Network download time is excluded.

## 4. Decision

`Qdrant/clip-ViT-B-32-vision` + `Qdrant/clip-ViT-B-32-text` is retained as the **opt-in alpha profile**:

- it loses one of 20 English Hit@1 cases versus Jina v1;
- it indexes this fixture about 3.5x faster;
- its English mean query latency is about 2.7x lower;
- it has a smaller declared paired footprint;
- it runs through the already selected FastEmbed/ONNX boundary.

It is not the production Chinese default. Both tested models failed Chinese Hit@1. The default remains off,
and `image` search returns an explicit `409 image_embeddings_unavailable` instead of silently pretending to
perform visual retrieval.

## 5. Multilingual candidate gate

The next benchmark should add at least one Chinese-capable candidate:

- [Jina CLIP v2](https://huggingface.co/jinaai/jina-clip-v2) claims 89-language text/image retrieval and
  512x512 images, but its CC-BY-NC-4.0 license needs a separate suitability decision and it is not currently
  in FastEmbed's supported image-model list;
- [BAAI AltCLIP](https://huggingface.co/BAAI/AltCLIP) is explicitly bilingual Chinese/English, but introduces
  a different Transformers/runtime and model-access boundary.

Candidates must be measured on this host for Chinese Hit@1/MRR, memory, load/index/query latency, license,
and packaging impact. Marketing benchmark numbers cannot replace the repository's held-out result.

## 6. Runtime evidence

`scripts/smoke_visual.py` starts a real localhost Uvicorn process with OCR disabled and the CLIP profile
enabled. It uploads a red triangle and blue circle, persists their original bytes and vectors, retrieves the
red triangle through an English text query, then reads its tenant-scoped image citation. The raw report records
the returned artifact URL and SHA-256.

## 7. Known limits

- Icons are synthetic and intentionally easy; this does not prove screenshot, chart, or clinical-image
  understanding.
- The Chinese query set exposes a real failure but is too small to select a multilingual production model.
- Fusion weight 80/20 was fixed before the run and not tuned on the evaluated cases.
- Exact SQLite vector scan is appropriate for 20 images, not a scale decision.
- Bounding boxes currently exist for PPTX picture shapes; PDF subregions and DOCX anchoring remain open.
