# V2 Alpha.2 Visual Retrieval Benchmark

Date: 2026-09-06

Raw evidence:

- `reports/visual-retrieval-benchmark-v2-alpha2.json`
- `reports/smoke-v2-alpha2-visual.json`

Code validation: Ruff passed; Pytest passed 44/44 tests. The visual smoke uses the real FastEmbed CLIP ONNX
models rather than the deterministic provider used by unit tests.

## 1. Question being tested

Can the system retrieve evidence that contains no searchable text, and does adding OCR help or hurt?

The fixture generator creates 20 white-background, 384x384 icons covering colors, geometric shapes, arrows,
cloud/lock/network/check symbols, and no intentional text. Each image has one English and one Chinese query,
for 40 positive text-to-image queries. Ten unrelated English and ten unrelated Chinese questions are also
run to measure false-match scores. This isolates cross-modal retrieval and abstention calibration; it is not
a chart-understanding benchmark.

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
| Qdrant CLIP-B/32 | ~0.59 GB | **1580.741 ms** | **430.679 ms** | **21.329 ms** | **37.905 ms** |
| Jina CLIP v1 | ~0.89 GB | 2008.758 ms | 1493.585 ms | 31.643 ms | 100.130 ms |

OCR processing for the same 20 icons took 16,783.431 ms before its sub-millisecond BM25 query stage. CLIP
therefore costs vector storage and model memory but supplies the missing visual signal and indexes these
fixtures much faster than OCR.

The declared sizes come from FastEmbed 0.7.4 model metadata. The complete local FastEmbed cache is 2.68 GiB
because it also contains earlier MiniLM and BGE benchmark models. Network download time is excluded.

## 4. Abstention calibration

Raw cosine similarity is kept separately from the normalized presentation score. On English queries:

| Profile | expected-positive minimum | positive winner-margin minimum | unrelated-query maximum |
| --- | ---: | ---: | ---: |
| Qdrant CLIP-B/32 | 0.304385 | 0.002336 | 0.262298 |
| Jina CLIP v1 | 0.207697 | 0.048603 | 0.145045 |

The default Qdrant alpha profile therefore uses a provisional raw-similarity threshold of `0.28` and a
top-versus-runner-up margin of `0.002`. Both gates must pass before `/answer` is allowed to cite an image.
These values separate this fixture, not arbitrary screenshots. They are model-specific: applying the Qdrant
threshold to Jina v1 would reject valid cases. Chinese positive and negative ranges overlap for both models,
which independently confirms that neither profile is safe as the Chinese default.

## 5. Decision

`Qdrant/clip-ViT-B-32-vision` + `Qdrant/clip-ViT-B-32-text` is retained as the **opt-in alpha profile**:

- it loses one of 20 English Hit@1 cases versus Jina v1;
- it indexes this fixture about 3.5x faster;
- its English mean query latency is about 1.5x lower and its p95 about 2.6x lower;
- it has a smaller declared paired footprint;
- it runs through the already selected FastEmbed/ONNX boundary.

Jina v1 has the stronger English quality and abstention separation, so it remains the quality challenger
rather than being dismissed by latency alone. The default is an engineering trade-off for the local alpha,
not a claim that Qdrant's CLIP model is universally better.

It is not the production Chinese default. Both tested models failed Chinese Hit@1. The default remains off,
and `image` search returns an explicit `409 image_embeddings_unavailable` instead of silently pretending to
perform visual retrieval.

## 6. Multilingual candidate gate

The next benchmark should add at least one Chinese-capable candidate:

- [Jina CLIP v2](https://huggingface.co/jinaai/jina-clip-v2) claims 89-language text/image retrieval and
  512x512 images, but its CC-BY-NC-4.0 license needs a separate suitability decision and it is not currently
  in FastEmbed's supported image-model list;
- [BAAI AltCLIP](https://huggingface.co/BAAI/AltCLIP) is explicitly bilingual Chinese/English, but introduces
  a different Transformers/runtime and model-access boundary.

Candidates must be measured on this host for Chinese Hit@1/MRR, memory, load/index/query latency, license,
and packaging impact. Marketing benchmark numbers cannot replace the repository's held-out result.

## 7. Runtime evidence

`scripts/smoke_visual.py` starts a real localhost Uvicorn process with OCR disabled and the CLIP profile
enabled. It uploads a red triangle and blue circle, persists their original bytes and vectors, retrieves the
red triangle through an English text query, then reads its tenant-scoped image citation. It also sends the
question through `/answer`, verifies automatic visual routing, and obtains the same citation from the offline
visual-locator fallback. The raw report records the route, provider, artifact URL, and SHA-256. A mocked
OpenAI-compatible contract test verifies the inline `image_url` payload; no real external VLM was benchmarked.

## 8. Known limits

- Icons are synthetic and intentionally easy; this does not prove screenshot, chart, or clinical-image
  understanding.
- The Chinese query set exposes a real failure but is too small to select a multilingual production model.
- Fusion weight 80/20 was fixed before the run and not tuned on the evaluated cases.
- The 20 unrelated questions are a useful rejection check, not a statistically robust calibration corpus.
- Thresholds are provider-specific and must be recalibrated when the image/text model changes.
- Exact SQLite vector scan is appropriate for 20 images, not a scale decision.
- Bounding boxes currently exist for PPTX picture shapes; PDF subregions and DOCX anchoring remain open.
