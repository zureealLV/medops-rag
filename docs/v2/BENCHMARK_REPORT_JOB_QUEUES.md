# Beta.2 Job Queue Transport Benchmark

## Question and decision

Does the single-host V2 profile gain enough from Redis/Celery to justify an always-on broker? **No.** Celery
wins the no-op transport benchmark, but both transports are hundreds of tasks per second while real OCR and
model calls take tens of milliseconds to seconds. SQLite also already persists the application-specific
lease, progress, partial-map, error and citation state that Celery would not remove.

Decision:

- keep the fenced SQLite queue as the selected single-host V2 transport;
- keep `.[distributed]` as an explicit experiment/deployment extra;
- introduce a Celery adapter only when a measured multi-host or horizontal-scaling requirement exists.

## Environment and method

- Ubuntu 24.04 under WSL2, Linux `6.18.33.2-microsoft-standard-WSL2`;
- Python 3.12.3;
- Redis server 7.0.15 with authentication on a benchmark-only database;
- Celery 5.6.3, redis-py 6.4.0;
- one Celery `solo` worker with concurrency 1 and late acknowledgements;
- 1,000 integer no-op tasks, three independent repetitions;
- SQLite WAL queue uses one durable transaction per publish and an immediate claim transaction;
- worker startup and the single warm-up task are excluded; task publication and completion are included.

This measures transport overhead, not OCR/model throughput. Both candidates execute on the same WSL2 host;
SQLite uses a temporary Linux filesystem directory rather than Windows DrvFS.

## Results

| Transport | Publish p50 | Publish p95 | End-to-end | Throughput |
| --- | ---: | ---: | ---: | ---: |
| SQLite WAL lease queue | 1.351 ms | 2.091 ms | 2.881 s | 347.085 tasks/s |
| Redis 7 + Celery 5.6 | 0.565 ms | 0.755 ms | 2.081 s | 480.528 tasks/s |

Celery's median throughput is 38.4% higher and its publish p95 is 63.9% lower for this artificial no-op
payload. The absolute median difference is about 0.8 seconds per 1,000 tasks. That does not pay for an extra
service in the local portfolio profile, especially because real tasks are orders of magnitude heavier.

Raw per-run data is committed as `reports/job-queue-benchmark-beta2.json`.

## Reproduction

```powershell
python -m pip install -e ".[distributed]"
python evals/benchmark_job_queues.py --tasks 1000 --repetitions 3 `
  --redis-url "redis://:PASSWORD@HOST:6379/14" `
  --output reports/job-queue-benchmark-beta2.json
```

The benchmark URL is required at runtime but excluded from the JSON output. Do not use a production Redis
database: the script purges its Celery queue and writes temporary task/result keys.

## Limits

- one producer and one worker do not model horizontal scaling;
- no-op tasks favor transport measurement and say nothing about parser/model performance;
- the SQLite loop mirrors the lease protocol but does not import the full API/service stack;
- Redis durability, failover, TLS and network partitions are not evaluated;
- the result supports a single-host choice only, not a general claim that SQLite is superior to Celery.
