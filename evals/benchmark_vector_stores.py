"""Filtered vector-store benchmark for SQLite-style exact scan, Qdrant local and Chroma."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

import numpy as np


def pct(v, p):
    s = sorted(v)
    return s[int((len(s) - 1) * p)]


def size(path):
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=1000)
    ap.add_argument("--queries", type=int, default=100)
    ap.add_argument("--output", type=Path)
    a = ap.parse_args()
    rng = np.random.default_rng(417)
    vectors = rng.normal(size=(a.size, 64)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    tenants = np.asarray(["a" if i % 2 == 0 else "b" for i in range(a.size)])
    qids = np.arange(0, min(a.queries * 2, a.size), 2)[: a.queries]
    expected = []
    for i in qids:
        scores = vectors @ vectors[i]
        valid = np.where(tenants == "a")[0]
        expected.append(list(valid[np.argsort(-scores[valid])[:10]]))
    report = {"vectors": a.size, "dimensions": 64, "queries": len(qids), "filter": "tenant=a", "stores": {}}
    t = time.perf_counter()
    matrix = vectors.copy()
    sqlite_index = (time.perf_counter() - t) * 1000
    lat = []
    got = []
    for i in qids:
        t = time.perf_counter()
        scores = matrix @ vectors[i]
        valid = np.where(tenants == "a")[0]
        got.append(list(valid[np.argsort(-scores[valid])[:10]]))
        lat.append((time.perf_counter() - t) * 1000)
    report["stores"]["sqlite_exact"] = {
        "index_ms": round(sqlite_index, 3),
        "p50_ms": round(statistics.median(lat), 3),
        "p95_ms": round(pct(lat, 0.95), 3),
        "recall_at_10": round(
            sum(len(set(x) & set(y)) / 10 for x, y in zip(got, expected, strict=True)) / len(expected), 4
        ),
        "disk_bytes": int(matrix.nbytes),
    }
    # Chroma's Rust HNSW layer can keep Windows file handles alive until process exit.
    # Ignore cleanup failures for this disposable benchmark directory rather than
    # turning a successful measurement into a false failure.
    with tempfile.TemporaryDirectory(
        prefix="medops-vectorstores-", ignore_cleanup_errors=True
    ) as d:
        root = Path(d)
        from qdrant_client import QdrantClient, models

        qp = root / "qdrant"
        client = QdrantClient(path=str(qp))
        t = time.perf_counter()
        client.create_collection(
            "bench", vectors_config=models.VectorParams(size=64, distance=models.Distance.COSINE)
        )
        for start in range(0, a.size, 1000):
            client.upload_collection(
                "bench",
                vectors=vectors[start : start + 1000].tolist(),
                ids=list(range(start, min(start + 1000, a.size))),
                payload=[{"tenant": str(x)} for x in tenants[start : start + 1000]],
            )
        qi = (time.perf_counter() - t) * 1000
        lat = []
        got = []
        flt = models.Filter(must=[models.FieldCondition(key="tenant", match=models.MatchValue(value="a"))])
        for i in qids:
            t = time.perf_counter()
            res = client.query_points("bench", query=vectors[i].tolist(), query_filter=flt, limit=10).points
            lat.append((time.perf_counter() - t) * 1000)
            got.append([int(x.id) for x in res])
        report["stores"]["qdrant_local"] = {
            "version": "1.19.0",
            "index_ms": round(qi, 3),
            "p50_ms": round(statistics.median(lat), 3),
            "p95_ms": round(pct(lat, 0.95), 3),
            "recall_at_10": round(
                sum(len(set(x) & set(y)) / 10 for x, y in zip(got, expected, strict=True)) / len(expected), 4
            ),
            "disk_bytes": size(qp),
        }
        client.close()
        import chromadb

        cp = root / "chroma"
        cc = chromadb.PersistentClient(path=str(cp))
        col = cc.create_collection("bench", metadata={"hnsw:space": "cosine"})
        t = time.perf_counter()
        for start in range(0, a.size, 1000):
            end = min(start + 1000, a.size)
            col.add(
                ids=[str(x) for x in range(start, end)],
                embeddings=vectors[start:end].tolist(),
                metadatas=[{"tenant": str(x)} for x in tenants[start:end]],
            )
        ci = (time.perf_counter() - t) * 1000
        lat = []
        got = []
        for i in qids:
            t = time.perf_counter()
            res = col.query(query_embeddings=[vectors[i].tolist()], where={"tenant": "a"}, n_results=10)
            lat.append((time.perf_counter() - t) * 1000)
            got.append([int(x) for x in res["ids"][0]])
        report["stores"]["chroma_persistent"] = {
            "version": "1.5.9",
            "index_ms": round(ci, 3),
            "p50_ms": round(statistics.median(lat), 3),
            "p95_ms": round(pct(lat, 0.95), 3),
            "recall_at_10": round(
                sum(len(set(x) & set(y)) / 10 for x, y in zip(got, expected, strict=True)) / len(expected), 4
            ),
            "disk_bytes": size(cp),
        }
    payload = json.dumps(report, indent=2)
    print(payload)
    if a.output:
        a.output.write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
