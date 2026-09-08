# Public medical corpora for MedOps RAG

## Integrated now: MedlinePlus Health Topics XML

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
| Huatuo-26M | Very large Chinese QA collection | Mixed web-derived provenance and redistribution/licensing caveats | Not a default trusted corpus |
| MIMIC | Real de-identified clinical records | Credentialed access, required training and a data-use agreement; not a knowledge base | Do not bundle |

For production use, add corpus version pinning, scheduled refresh review,
clinical-content governance, deletion/tombstone handling, and evaluation per
specialty before enabling automated updates.
