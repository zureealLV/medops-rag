"""Compare no-transform, rewrite, multi-query and template-HyDE on frozen V2 retrieval."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding
from rank_bm25 import BM25Okapi

from app.retrieval.embeddings import tokenize
from app.retrieval.query_transform import transform_queries

ROOT = Path(__file__).resolve().parents[1]
DENSE = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODES = ("none", "rewrite", "multi_query", "hyde")


def _norm(values):
    vector = np.asarray(values, dtype=np.float32)
    magnitude = float(np.linalg.norm(vector))
    return vector / magnitude if magnitude else vector


def _order(values):
    return sorted(range(len(values)), key=lambda index: (-values[index], index))


def _ranks(values):
    result = [0] * len(values)
    for value, index in enumerate(_order(values), start=1):
        result[index] = value
    return result


def _metrics(rankings, cases, latencies):
    reciprocal = []
    ndcg = []
    hits = {1: 0, 3: 0, 5: 0}
    groups: dict[str, list[int]] = {}
    for ranking, case in zip(rankings, cases, strict=True):
        found = next(
            (index for index, source in enumerate(ranking, start=1) if source == case["expected_source"]),
            None,
        )
        reciprocal.append(1 / found if found else 0)
        ndcg.append(1 / np.log2(found + 1) if found else 0)
        for top_k in hits:
            hits[top_k] += int(found is not None and found <= top_k)
        groups.setdefault(case["category"], []).append(int(found == 1))
    ordered_latency = sorted(latencies)
    count = len(cases)
    return {
        "hit_at_1": round(hits[1] / count, 4),
        "hit_at_3": round(hits[3] / count, 4),
        "hit_at_5": round(hits[5] / count, 4),
        "mrr_at_5": round(statistics.fmean(reciprocal), 4),
        "ndcg_at_5": round(statistics.fmean(ndcg), 4),
        "mean_ms": round(statistics.fmean(latencies), 3),
        "p95_ms": round(ordered_latency[int(0.95 * (count - 1))], 3),
        "hit_at_1_by_category": {
            key: round(sum(values) / len(values), 4) for key, values in groups.items()
        },
    }


def main() -> None:
    document_path = ROOT / "evals/v2_retrieval_documents.jsonl"
    case_path = ROOT / "evals/v2_retrieval_cases.jsonl"
    documents = [json.loads(line) for line in document_path.read_text(encoding="utf-8").splitlines()]
    cases = [
        value
        for value in (
            json.loads(line) for line in case_path.read_text(encoding="utf-8").splitlines()
        )
        if not value["expected_abstain"]
    ]
    texts = [value["text"] for value in documents]
    sources = [value["source"] for value in documents]
    sparse = BM25Okapi([tokenize(value) for value in texts])
    dense = TextEmbedding(model_name=DENSE, cache_dir=str(ROOT / "data/models/fastembed"))
    document_vectors = [_norm(value) for value in dense.embed(texts)]
    rankings: dict[str, list[list[str]]] = {mode: [] for mode in MODES}
    latencies: dict[str, list[float]] = {mode: [] for mode in MODES}

    for case in cases:
        for mode in MODES:
            started = time.perf_counter()
            _, queries = transform_queries(case["question"], mode, None)
            per_query_fusion = []
            for query in queries:
                sparse_scores = [float(value) for value in sparse.get_scores(tokenize(query))]
                query_vector = _norm(next(dense.query_embed(query)))
                dense_scores = [float(np.dot(query_vector, value)) for value in document_vectors]
                sparse_ranks = _ranks(sparse_scores)
                dense_ranks = _ranks(dense_scores)
                per_query_fusion.append(
                    [
                        1 / (60 + sparse_rank) + 1 / (60 + dense_rank)
                        for sparse_rank, dense_rank in zip(sparse_ranks, dense_ranks, strict=True)
                    ]
                )
            if len(per_query_fusion) == 1:
                final_scores = per_query_fusion[0]
            else:
                query_ranks = [_ranks(values) for values in per_query_fusion]
                final_scores = [
                    sum(1 / (60 + ranks[index]) for ranks in query_ranks)
                    for index in range(len(texts))
                ]
            ranking = _order(final_scores)
            rankings[mode].append([sources[index] for index in ranking[:5]])
            latencies[mode].append((time.perf_counter() - started) * 1000)

    report = {
        "benchmark": "medops-v2-query-transforms-v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "documents": len(documents),
        "answerable_questions": len(cases),
        "dense_model": DENSE,
        "fastembed_version": importlib.metadata.version("fastembed"),
        "dataset_sha256": {
            document_path.name: hashlib.sha256(document_path.read_bytes()).hexdigest(),
            case_path.name: hashlib.sha256(case_path.read_bytes()).hexdigest(),
        },
        "results": {
            mode: _metrics(rankings[mode], cases, latencies[mode]) for mode in MODES
        },
        "policy": (
            "Keep query transformation disabled by default unless a transform wins held-out quality "
            "without an unacceptable latency increase. Template HyDE is not an LLM-generated claim."
        ),
        "limitations": [
            "Synthetic operations corpus with one relevant document per question.",
            "HyDE uses the committed deterministic template, not an external language model.",
            "Cached model load and document indexing time are excluded.",
        ],
    }
    output = ROOT / "reports/query-transform-benchmark-v2-beta1.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
