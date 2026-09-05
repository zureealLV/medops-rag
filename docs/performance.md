# V1 Local Performance Baseline

The reproducible command is:

```powershell
.\.venv\Scripts\python.exe .\scripts\performance_baseline.py
```

It creates an isolated SQLite database, imports the bundled corpus and sends all 30 evaluation questions through `POST /answer`. Results are written to `reports/generated/performance.json`.

Numbers are environment-specific and must be regenerated before quoting them. The baseline covers the offline extractive provider; network model latency is intentionally excluded.

Historical local run on 2026-09-05 (Python 3.11.5, 30 requests): P50 `17.173 ms`, P95 `33.614 ms`, maximum `41.452 ms`, error rate `0.00`. Treat these as machine-specific evidence rather than a guarantee.
