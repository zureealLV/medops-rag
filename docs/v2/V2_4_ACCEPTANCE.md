# V2.4 Official Chinese Corpus Acceptance

Date: 2026-09-09 (Asia/Shanghai)

## Delivered

- versioned six-document catalog for NHC, State Council regulation and NMPA material;
- allow-listed HTTPS downloader with redirect, byte, PDF signature and pinned SHA-256 checks;
- separate official-government knowledge base and local-only source snapshots;
- NFKC/whitespace normalization and Chinese sentence/semicolon-aware overlapping chunks;
- quantity-aware and class-list-aware offline extraction;
- frozen answer/citation, out-of-domain and medical-advice evaluation.

## Local evidence

```text
knowledge_base_id=7
documents=6
chunks=354
language=zh-CN
idempotent rerun: created=0 skipped=6
official evaluation: 8/8 passed, failures=[]
retrieval median=37.505 ms, p95=46.912 ms, limit=500 ms
release core: Ruff passed; 102 tests passed
```

The local runtime also retained 15,000 Huatuo Chinese research records and 1,016
MedlinePlus English topics. Source binaries are ignored by Git.

## Release boundary

V2.4 is a portfolio/education release, not a clinical decision-support system or
regulated medical device. The V3.0 gates still require corpus-rights review,
domain-owner sign-off, red-team, accessibility and disaster-recovery evidence.
