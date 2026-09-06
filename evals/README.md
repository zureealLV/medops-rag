# Evaluations

## Job queue transport

`benchmark_job_queues.py` compares the SQLite lease transport against a real Redis/Celery worker. Install the
`distributed` extra and pass a disposable Redis database URL; the URL is never written to the report.

```powershell
python -m pip install -e ".[distributed]"
python evals/benchmark_job_queues.py --tasks 1000 --repetitions 3 `
  --redis-url "redis://:PASSWORD@HOST:6379/14" `
  --output reports/job-queue-benchmark-beta2.json
```

This directory will contain the reproducible offline RAG evaluation dataset, runner, and generated reports.
# Offline evaluation

`dataset.jsonl` contains 30 synthetic questions: 25 answerable operations questions and 5 questions that should be refused.

```powershell
.\.venv\Scripts\python.exe .\evals\run_eval.py
```

The generated JSON report is written to `reports/generated/evaluation.json` and is intentionally ignored by Git.
