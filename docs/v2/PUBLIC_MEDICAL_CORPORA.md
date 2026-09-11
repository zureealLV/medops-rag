# Public medical corpora for MedOps RAG

## Primary local corpus: Huatuo-26M Chinese medical QA

The V2.3 default import is a bounded, reproducible Chinese corpus assembled
from the Huatuo-26M knowledge-graph and encyclopedia subsets. It imports
12,000 knowledge-graph QA records plus 3,000 encyclopedia QA records. Together
with the 1,016 current English MedlinePlus topics, Chinese accounts for 93.7%
of the externally imported records in the validated local profile.

```powershell
# Recommended Chinese-first local profile
.\.venv\Scripts\python.exe -m scripts.import_huatuo

# Smaller development import
.\.venv\Scripts\python.exe -m scripts.import_huatuo `
  --knowledge-graph-limit 1000 --encyclopedia-limit 200

# Rebuild changed records from the same pinned revisions
.\.venv\Scripts\python.exe -m scripts.import_huatuo --refresh-existing
```

The importer does not execute the Hugging Face dataset loader. It streams a
bounded JSONL prefix directly from two immutable repository revisions, applies
per-record and aggregate byte limits, and writes exact revisions, URLs, counts
and local SHA-256 values to `data/external/huatuo/sources.json`.

The dataset repositories declare Apache-2.0. Their records were aggregated
from public medical knowledge graphs and online medical encyclopedias; MedOps
has not clinically reviewed each record. This corpus is therefore marked
**research use** and is not silently promoted to clinical guidance.

Example Chinese questions known to exist in the pinned snapshot:

- `遗传性帕金森病的病因是什么？`
- `IGT和2型糖尿病的预防措施有些什么？`
- `引起高血压肾病的原因`
- `高血压分级`

Chinese lexical search uses SQLite FTS5's trigram tokenizer for candidate
recall and then applies the existing BM25/evidence gates. If FTS5 is absent in
a custom SQLite build, retrieval safely falls back to the original full scan.

## Additional official corpus: MedlinePlus Health Topics XML

MedOps can download and import the official bulk health-topic feed published by
the U.S. National Library of Medicine. The feed is updated Tuesday through
Saturday and currently contains roughly one thousand English topics plus a
matching Spanish collection. Each imported document retains its canonical
MedlinePlus URL, topic ID, language, aliases, MeSH headings, NIH institute,
feed generation time, and attribution.

```powershell
# Full English corpus (recommended)
.\.venv\Scripts\python.exe -m scripts.import_medlineplus

# Fast smoke test
.\.venv\Scripts\python.exe -m scripts.import_medlineplus --limit 50

# English and Spanish; update changed documents from a newer snapshot
.\.venv\Scripts\python.exe -m scripts.import_medlineplus `
  --language English --language Spanish --refresh-existing
```

Raw archives and `sources.json` are written to
`data/external/medlineplus/` and intentionally ignored by Git. The manifest
records the exact download URL, access time, feed date, SHA-256, languages, and
imported record count.

Example English questions:

- `What does an A1C test measure?`
- `What are the symptoms of rheumatoid arthritis?`
- `How is asthma treated?`
- `What is the difference between type 1 and type 2 diabetes?`

The corpus is authoritative patient education, not a clinical decision-support
rule set. Answers must remain attributable and must not imply NLM endorsement.

## Evaluated alternatives

| Corpus | Strength | Limitation | Decision |
| --- | --- | --- | --- |
| MedQuAD | 47,457 QA pairs built from 12 NIH sites; CC BY 4.0 | Static research snapshot; three subsets omit answers for copyright reasons | Next QA/evaluation connector |
| openFDA | Current official JSON APIs for drugs and devices | Endpoint-specific records are not a general health encyclopedia | Next regulated-product connector |
| WikiMed/Kiwix | Broad multilingual offline medical encyclopedia | Large ZIM archives and community-edited content | Optional offline expansion |
| BIOS 2022V2 | Very large bilingual biomedical knowledge graph | CC BY-NC-ND and graph-scale storage requirements | Research-only future adapter |
| Huatuo-26M | 26M Chinese QA collection; repository declares Apache-2.0 | Mixed web-derived provenance; individual records are not clinically reviewed | Integrated as bounded research corpus |
| MIMIC | Real de-identified clinical records | Credentialed access, required training and a data-use agreement; not a knowledge base | Do not bundle |

For production use, add corpus version pinning, scheduled refresh review,
clinical-content governance, deletion/tombstone handling, and evaluation per
specialty before enabling automated updates.
