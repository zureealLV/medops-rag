"""Benchmark Qdrant server under concurrent tenant-filtered vector load."""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import time
import urllib.request
from importlib.metadata import version
from pathlib import Path

import numpy as np
from qdrant_client import AsyncQdrantClient, QdrantClient, models


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[int((len(ordered) - 1) * fraction)]


def server_info(url: str) -> dict[str, str]:
    with urllib.request.urlopen(f"{url.rstrip('/')}/", timeout=5) as response:  # noqa: S310
        return json.load(response)


def expected_results(
    vectors: np.ndarray,
    tenants: np.ndarray,
    query_ids: np.ndarray,
    limit: int,
) -> list[list[int]]:
    expected: list[list[int]] = []
    for query_id in query_ids:
        eligible = np.flatnonzero(tenants == tenants[query_id])
        scores = vectors[eligible] @ vectors[query_id]
        expected.append(eligible[np.argsort(-scores)[:limit]].tolist())
    return expected


async def run_queries(
    *,
    url: str,
    collection: str,
    vectors: np.ndarray,
    tenants: np.ndarray,
    query_ids: np.ndarray,
    concurrency: int,
    limit: int,
) -> tuple[list[float], list[list[int]], float]:
    client = AsyncQdrantClient(url=url, timeout=30, pool_size=max(10, concurrency * 2))
    semaphore = asyncio.Semaphore(concurrency)

    async def query_one(query_id: int) -> tuple[float, list[int]]:
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="tenant_id",
                    match=models.MatchValue(value=str(tenants[query_id])),
                )
            ]
        )
        async with semaphore:
            started = time.perf_counter()
            response = await client.query_points(
                collection,
                query=vectors[query_id].tolist(),
                query_filter=query_filter,
                search_params=models.SearchParams(hnsw_ef=128, exact=False),
                limit=limit,
                with_payload=False,
                with_vectors=False,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
        return elapsed_ms, [int(point.id) for point in response.points]

    started = time.perf_counter()
    results = await asyncio.gather(*(query_one(int(query_id)) for query_id in query_ids))
    wall_seconds = time.perf_counter() - started
    await client.close()
    return [item[0] for item in results], [item[1] for item in results], wall_seconds


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:6333")
    parser.add_argument("--collection", default="medops_concurrent_bench")
    parser.add_argument("--vectors", type=int, default=10_000)
    parser.add_argument("--dimensions", type=int, default=64)
    parser.add_argument("--tenants", type=int, default=20)
    parser.add_argument("--queries", type=int, default=400)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if min(args.vectors, args.dimensions, args.tenants, args.queries, args.concurrency, args.limit) < 1:
        parser.error("all numeric options must be positive")
    if args.tenants > args.vectors:
        parser.error("tenants cannot exceed vectors")

    rng = np.random.default_rng(417)
    vectors = rng.normal(size=(args.vectors, args.dimensions)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    tenants = np.asarray([f"tenant-{index % args.tenants}" for index in range(args.vectors)])
    query_ids = rng.choice(args.vectors, size=min(args.queries, args.vectors), replace=False)
    expected = expected_results(vectors, tenants, query_ids, args.limit)

    info = server_info(args.url)
    client = QdrantClient(url=args.url, timeout=60)
    if client.collection_exists(args.collection):
        client.delete_collection(args.collection)
    started = time.perf_counter()
    client.create_collection(
        args.collection,
        vectors_config=models.VectorParams(
            size=args.dimensions,
            distance=models.Distance.COSINE,
        ),
        hnsw_config=models.HnswConfigDiff(m=16, ef_construct=100),
    )
    client.create_payload_index(
        args.collection,
        field_name="tenant_id",
        field_schema=models.PayloadSchemaType.KEYWORD,
        wait=True,
    )
    for offset in range(0, args.vectors, 1_000):
        end = min(offset + 1_000, args.vectors)
        client.upload_collection(
            args.collection,
            vectors=vectors[offset:end].tolist(),
            ids=list(range(offset, end)),
            payload=[{"tenant_id": str(value)} for value in tenants[offset:end]],
            batch_size=256,
        )
    index_seconds = time.perf_counter() - started
    collection_info = client.get_collection(args.collection)
    client.close()

    latencies, actual, wall_seconds = asyncio.run(
        run_queries(
            url=args.url,
            collection=args.collection,
            vectors=vectors,
            tenants=tenants,
            query_ids=query_ids,
            concurrency=args.concurrency,
            limit=args.limit,
        )
    )
    recall = statistics.mean(
        len(set(got) & set(want)) / len(want)
        for got, want in zip(actual, expected, strict=True)
    )
    tenant_violations = sum(
        any(tenants[point_id] != tenants[query_id] for point_id in got)
        for query_id, got in zip(query_ids, actual, strict=True)
    )
    report = {
        "status": "pass" if tenant_violations == 0 and recall >= 0.95 else "fail",
        "server": {
            "url": args.url,
            "version": info.get("version", "unknown"),
            "commit": info.get("commit", "unknown"),
            "client_version": version("qdrant-client"),
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "workload": {
            "vectors": args.vectors,
            "dimensions": args.dimensions,
            "tenants": args.tenants,
            "queries": len(query_ids),
            "concurrency": args.concurrency,
            "limit": args.limit,
            "filter": "tenant_id equals the query tenant",
            "hnsw_ef": 128,
        },
        "results": {
            "index_seconds": round(index_seconds, 3),
            "points_count": collection_info.points_count,
            "wall_seconds": round(wall_seconds, 3),
            "throughput_qps": round(len(query_ids) / wall_seconds, 3),
            "latency_ms": {
                "mean": round(statistics.mean(latencies), 3),
                "p50": round(statistics.median(latencies), 3),
                "p95": round(percentile(latencies, 0.95), 3),
                "p99": round(percentile(latencies, 0.99), 3),
                "max": round(max(latencies), 3),
            },
            "recall_at_limit": round(recall, 4),
            "tenant_filter_violations": tenant_violations,
        },
        "decision": (
            "Keep SQLite exact scan as the shipped default for the measured portfolio workload; "
            "Qdrant server is a validated scale-out option, not a production-readiness claim."
        ),
    }
    payload = json.dumps(report, indent=2)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
