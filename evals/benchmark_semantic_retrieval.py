"""Benchmark local multilingual dense retrieval and BGE reranking on CPU."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder.text_cross_encoder import TextCrossEncoder
from rank_bm25 import BM25Okapi

from app.config import Settings
from app.repositories.documents import retrieval_rows
from app.retrieval.embeddings import embed as hash_embed
from app.retrieval.embeddings import tokenize
from scripts.seed_sample_data import seed

ROOT = Path(__file__).resolve().parents[1]
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
RERANKER_MODEL = "BAAI/bge-reranker-base"


def normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


def ranks(values: list[float]) -> list[int]:
    order = sorted(range(len(values)), key=lambda index: (-values[index], index))
    output = [0] * len(values)
    for rank, index in enumerate(order, start=1):
        output[index] = rank
    return output


def ranked_indices(values: list[float]) -> list[int]:
    return sorted(range(len(values)), key=lambda index: (-values[index], index))


def rrf(left: list[float], right: list[float], constant: int = 60) -> list[float]:
    left_ranks = ranks(left)
    right_ranks = ranks(right)
    return [
        1.0 / (constant + left_rank) + 1.0 / (constant + right_rank)
        for left_rank, right_rank in zip(left_ranks, right_ranks, strict=True)
    ]


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def summarize(
    name: str,
    source_rankings: list[list[str]],
    expected_sources: list[str],
    latencies: list[float],
) -> dict[str, float | int | str]:
    reciprocal: list[float] = []
    hits = {1: 0, 3: 0, 5: 0}
    for sources, expected in zip(source_rankings, expected_sources, strict=True):
        rank = next((index for index, source in enumerate(sources, start=1) if source == expected), None)
        reciprocal.append(1.0 / rank if rank else 0.0)
        for cutoff in hits:
            hits[cutoff] += int(rank is not None and rank <= cutoff)
    count = len(expected_sources)
    return {
        "strategy": name,
        "cases": count,
        "hit_at_1": round(hits[1] / count, 4),
        "hit_at_3": round(hits[3] / count, 4),
        "hit_at_5": round(hits[5] / count, 4),
        "mrr_at_5": round(statistics.fmean(reciprocal), 4),
        "latency_mean_ms": round(statistics.fmean(latencies), 3),
        "latency_p95_ms": round(percentile(latencies, 0.95), 3),
    }


def measure_load(factory: Callable[[], object]) -> tuple[object, float]:
    started = time.perf_counter()
    instance = factory()
    return instance, (time.perf_counter() - started) * 1000


def run(cache_dir: Path) -> dict[str, object]:
    cases = [
        json.loads(line)
        for line in (ROOT / "evals" / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line and not json.loads(line)["expected_abstain"]
    ]
    with tempfile.TemporaryDirectory(prefix="medops-semantic-benchmark-") as directory:
        settings = Settings(database_path=Path(directory) / "benchmark.db")
        kb_id, _ = seed(settings)
        rows = retrieval_rows(settings.database_path, "hospital-a", kb_id)
        texts = [str(row["text"]) for row in rows]
        sources = [str(row["source"]) for row in rows]

    dense_model, dense_load_ms = measure_load(
        lambda: TextEmbedding(model_name=EMBEDDING_MODEL, cache_dir=str(cache_dir))
    )
    reranker, reranker_load_ms = measure_load(
        lambda: TextCrossEncoder(model_name=RERANKER_MODEL, cache_dir=str(cache_dir))
    )
    assert isinstance(dense_model, TextEmbedding)
    assert isinstance(reranker, TextCrossEncoder)

    started = time.perf_counter()
    dense_corpus = [normalize(np.asarray(vector, dtype=np.float32)) for vector in dense_model.embed(texts)]
    dense_index_ms = (time.perf_counter() - started) * 1000
    hash_corpus = [np.asarray(hash_embed(text), dtype=np.float32) for text in texts]
    bm25 = BM25Okapi([tokenize(text) for text in texts])

    rankings: dict[str, list[list[str]]] = {
        "hash_dense": [],
        "multilingual_minilm_dense": [],
        "bm25": [],
        "bm25_minilm_rrf": [],
        "bm25_minilm_rrf_bge_rerank_top10": [],
    }
    latencies: dict[str, list[float]] = {name: [] for name in rankings}
    expected_sources: list[str] = []

    for case in cases:
        query = str(case["question"])
        expected_sources.append(str(case["expected_source"]))

        started = time.perf_counter()
        query_hash = np.asarray(hash_embed(query), dtype=np.float32)
        hash_scores = [float(np.dot(query_hash, vector)) for vector in hash_corpus]
        hash_order = ranked_indices(hash_scores)
        latencies["hash_dense"].append((time.perf_counter() - started) * 1000)
        rankings["hash_dense"].append([sources[index] for index in hash_order[:5]])

        started = time.perf_counter()
        query_dense = normalize(next(dense_model.query_embed(query)).astype(np.float32))
        dense_scores = [float(np.dot(query_dense, vector)) for vector in dense_corpus]
        dense_order = ranked_indices(dense_scores)
        dense_elapsed = (time.perf_counter() - started) * 1000
        latencies["multilingual_minilm_dense"].append(dense_elapsed)
        rankings["multilingual_minilm_dense"].append([sources[index] for index in dense_order[:5]])

        started = time.perf_counter()
        bm25_scores = [float(value) for value in bm25.get_scores(tokenize(query))]
        bm25_order = ranked_indices(bm25_scores)
        latencies["bm25"].append((time.perf_counter() - started) * 1000)
        rankings["bm25"].append([sources[index] for index in bm25_order[:5]])

        started = time.perf_counter()
        fused_scores = rrf(bm25_scores, dense_scores)
        fused_order = ranked_indices(fused_scores)
        fused_elapsed = dense_elapsed + (time.perf_counter() - started) * 1000
        latencies["bm25_minilm_rrf"].append(fused_elapsed)
        rankings["bm25_minilm_rrf"].append([sources[index] for index in fused_order[:5]])

        started = time.perf_counter()
        candidates = fused_order[:10]
        rerank_scores = list(reranker.rerank(query, [texts[index] for index in candidates]))
        reranked = sorted(
            range(len(candidates)), key=lambda index: (-float(rerank_scores[index]), index)
        )
        rerank_elapsed = fused_elapsed + (time.perf_counter() - started) * 1000
        latencies["bm25_minilm_rrf_bge_rerank_top10"].append(rerank_elapsed)
        rankings["bm25_minilm_rrf_bge_rerank_top10"].append(
            [sources[candidates[index]] for index in reranked[:5]]
        )

    return {
        "benchmark": "synthetic-operations-v1-semantic",
        "generated_at": datetime.now(UTC).isoformat(),
        "corpus_documents": len(set(sources)),
        "corpus_chunks": len(texts),
        "answerable_cases": len(cases),
        "environment": "Windows 10 CPU / ONNX Runtime",
        "models": {
            "dense": EMBEDDING_MODEL,
            "reranker": RERANKER_MODEL,
            "dense_load_ms": round(dense_load_ms, 3),
            "reranker_load_ms": round(reranker_load_ms, 3),
            "dense_corpus_index_ms": round(dense_index_ms, 3),
        },
        "results": [
            summarize(name, rankings[name], expected_sources, latencies[name]) for name in rankings
        ],
        "limitations": [
            "The corpus has only six synthetic documents; Hit@5 is not discriminative.",
            "Model files were already cached, so load times exclude network download.",
            "The reranker receives at most ten candidate chunks per query.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "models" / "fastembed")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run(args.cache_dir)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
