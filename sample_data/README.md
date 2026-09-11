# Sample Data

Only public, licensed or synthetic healthcare and medical-device documents belong here. Never add real patient data.

## Medical starter corpus

`medical_knowledge/` contains Chinese educational summaries with source URL and access date in every file. The default seed command creates separate clinical-fundamentals and medical-device knowledge bases. It does not copy patient records or institution-specific procedures.

## Multimodal import pack

`multimodal_demo/` contains synthetic CSV, JSONL, PNG, JPEG, WebP, DOCX, PDF and PPTX fixtures. Follow [`multimodal_demo/README.md`](multimodal_demo/README.md) to test text, table, OCR and embedded-image extraction.

## Legacy synthetic operations corpus

All files under `documents/` are original synthetic runbooks for testing this repository.
They contain no real patient records, credentials, proprietary hospital procedures, or medical advice.
