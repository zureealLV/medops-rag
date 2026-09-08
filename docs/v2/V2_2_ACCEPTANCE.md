# V2.2 Medical Knowledge and UX Acceptance

## Scope delivered

- the default seed profile creates separate clinical-fundamentals and medical-device knowledge bases;
- the former synthetic IT-operations corpus remains available only through `--profile operations` or `--profile all`;
- CSV, JSON and JSONL exports join the existing text, Office, PDF and image parser surface;
- a read-only SQLite table exporter requires an explicit table, selected columns and output path;
- answer text uses `[来源N]` and `[图像N]`; raw document/chunk locators and retrieval scores remain machine-facing only;
- the browser console uses a bright white/teal visual system and prefers a medical knowledge base on first load;
- a synthetic eight-format import pack supports repeatable local verification.

## Safety boundary

The starter corpus is educational. It contains no diagnosis, prescription, patient record, institution-specific protocol or real device telemetry. Source URLs and access dates are stored in each medical Markdown file. External data must be authorized, reviewed and de-identified before export.

## Acceptance commands

```powershell
.\scripts\run_tests.ps1
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe .\evals\run_eval.py
.\.venv\Scripts\python.exe .\scripts\seed_sample_data.py --profile medical
```

Runtime acceptance additionally requires `/health`, `/knowledge-bases`, a cited medical answer, upload of the supplied multimodal fixtures, and visual inspection of the Web console.

## What V2.2 does not claim

- clinical decision support, diagnosis or treatment recommendations;
- correctness on local hospital protocols or manufacturer-specific service manuals;
- direct production-database connectivity;
- production Chinese chart/diagram reasoning;
- hospital-scale availability, disaster recovery, identity federation or compliance certification.

Those gates require authorized domain data, clinical/device subject-matter review, domain-specific evaluation and a production deployment target.
