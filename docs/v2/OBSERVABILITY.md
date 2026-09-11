# V2 Operational Observability

Status: implemented and covered by `tests/test_observability_metrics.py`.

`GET /system/metrics` returns a tenant-scoped rolling 24-hour snapshot. In API-key mode it is admin-only.
It deliberately uses the selected SQLite deployment profile, so the numbers survive API/worker restarts
without adding a second metrics service to the local portfolio stack.

## Signals

- ingestion and summary queue counts by state, plus oldest queued age;
- request count, error/abstention count, mean and p95 request latency;
- retrieval and model p95 latency, token total, retrieval profile and provider counts;
- explicit offline-fallback count;
- parser/OCR, persist/index, summary-map and summary-reduce count, error count, mean and p95 latency;
- summary map/reduce provider counts.

The search and answer routes pass timing/provider facts to the request middleware through internal response
headers. Worker services write bounded stage metrics around parser/OCR, persistence/indexing and model calls.
Metric write failure is fail-open: telemetry can never turn a successful business operation into a failed job
or response.

## Example

```powershell
$headers = @{ Authorization = "Bearer <admin-api-key>" }
Invoke-RestMethod http://127.0.0.1:8000/system/metrics -Headers $headers |
  ConvertTo-Json -Depth 8
```

## Privacy and limits

Metrics carry tenant ID, job/document IDs, stage names, stable error codes, counts, timing, providers and token
usage. They do not store query text, document text, filenames, model keys or API keys. Tenant predicates are
applied before aggregation, and the cross-tenant test proves an empty snapshot for another tenant.

This endpoint is an operational snapshot rather than a Prometheus/OpenTelemetry implementation. A multi-host
deployment should export equivalent signals to a centralized backend, define retention and sampling, and add
alerts for queue age, failure rate, fallback rate and latency SLOs.
