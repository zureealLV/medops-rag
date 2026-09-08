# V2.3 Chinese-first Corpus Acceptance

## Delivered scope

- revision-pinned, bounded streaming import of 12,000 Huatuo-26M medical
  knowledge-graph QA records and 3,000 medical encyclopedia QA records;
- Chinese records comprise 93.7% of the validated external-corpus record count;
- per-source URL, row locator, revision, declared license, local SHA-256 and
  record count in an ignored local manifest;
- Chinese-aware SQLite FTS5 trigram candidate recall followed by the existing
  tenant-scoped BM25 and evidence gates;
- structured offline extraction of a retrieved dataset answer instead of
  repeating its question or provenance metadata;
- Chinese knowledge base preference on a fresh Web console session.

## Acceptance commands

```powershell
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe -m scripts.import_huatuo
.\.venv\Scripts\python.exe -m scripts.import_huatuo
.\scripts\run_tests.ps1
```

The second import must report `created=0 updated=0 skipped=15000`. Runtime
acceptance requires `/health` to report V2.3.0 and the three documented Chinese
questions to return cited, non-abstained answers from knowledge base 6 in the
validated local snapshot.

## Safety and quality boundary

Huatuo-26M is a real public research dataset, not an official Chinese clinical
guideline service. Its mixed knowledge-graph and web-encyclopedia provenance
must remain visible. Answers are for retrieval testing and education only; no
record is treated as a diagnosis, prescription or patient-specific treatment
instruction. Production promotion still requires rights review, clinical
content review, specialty evaluation and an accountable domain owner.
