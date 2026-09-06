"""No-op Celery task used only by the queue transport benchmark."""

from __future__ import annotations

import os

from celery import Celery

REDIS_URL = os.environ.get("BENCHMARK_REDIS_URL", "redis://127.0.0.1:6379/14")
app = Celery("medops_queue_benchmark", broker=REDIS_URL, backend=REDIS_URL)
app.conf.update(
    accept_content=["json"],
    broker_transport_options={"visibility_timeout": 60},
    result_expires=300,
    result_serializer="json",
    task_acks_late=True,
    task_serializer="json",
    worker_prefetch_multiplier=1,
)


@app.task(name="medops.benchmark.noop")
def noop(value: int) -> int:
    return value
