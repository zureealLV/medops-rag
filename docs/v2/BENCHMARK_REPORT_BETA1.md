# V2 Beta.1 Parent-Child Retrieval Benchmark

Date: 2026-09-06

Raw evidence: `reports/parent-child-benchmark-v2-beta1.json`

Current repository validation: Ruff passed; Pytest passed 48/48 tests.

## Question

Does retrieving a small child chunk and reconstructing its larger structural parent preserve context that fixed
600-character chunks lose, and what local latency does that add?

The generated fixture contains 50 documents. Each has a unique alert marker near the beginning and its linked
action after the first legacy chunk boundary. Each question names exactly one marker. This deliberately makes
document selection easy and isolates context reconstruction rather than pretending to benchmark semantic
paraphrase quality.

## Result

| Strategy | Hit@1 | linked action in returned context | mean context chars | query mean | p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| fixed 600-char chunk + BM25 | 1.00 | 0.00 | 563 | **13.628 ms** | **16.097 ms** |
| child BM25 + parent reconstruction | 1.00 | **1.00** | 1132 | 19.702 ms | 21.210 ms |

Parent reconstruction doubled the returned context and retained the linked action in all 50 cases, at an
observed mean latency cost of 6.074 ms (44.6%) on this small exact-scan fixture. Both strategies found the
right document, so the gain is context completeness, not retrieval accuracy.

## Engineering decision

`parent_child` is added as an explicit, opt-in search/answer strategy. Ingestion now persists:

- parents packed along normalized element and heading boundaries with page/element provenance;
- smaller overlapping children carrying deterministic embeddings;
- SQL tenant and knowledge-base fields on both levels;
- child match text separately from the reconstructed parent text.

The child scorer is BM25 for now. The existing benchmark showed the hashing-vector baseline could hurt lexical
quality, and this fixture does not justify calling it production hybrid retrieval. A real multilingual dense
model must win a frozen held-out set before BM25+dense fusion becomes the default.

## Limits

- Unique lexical markers make Hit@1 artificially easy.
- The benchmark measures returned context, not LLM answer correctness.
- Fifty documents and SQLite exact scoring do not establish a vector-database choice.
- Parents are structure-aware for normalized headings/pages, but tables and visual-region adjacency still
  need harder fixtures.
