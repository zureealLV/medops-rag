# Evaluations

This directory will contain the reproducible offline RAG evaluation dataset, runner, and generated reports.
# Offline evaluation

`dataset.jsonl` contains 30 synthetic questions: 25 answerable operations questions and 5 questions that should be refused.

```powershell
.\.venv\Scripts\python.exe .\evals\run_eval.py
```

The generated JSON report is written to `reports/generated/evaluation.json` and is intentionally ignored by Git.
