"""Compare deterministic adaptive routing with frozen fixed retrieval paths.

The benchmark intentionally reuses the V2 frozen corpus so its numbers can be
compared with the existing retrieval report.  It measures routing, not answer
generation.  The corpus contains one short parent per document, so the fixed
parent/child result is expected to match document-level BM25; that limitation is
recorded instead of manufacturing a parent/child advantage.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding
from rank_bm25 import BM25Okapi

from app.retrieval.adaptive import AdaptiveRoutingPolicy, route_retrieval
from app.retrieval.chunking import split_text
from app.retrieval.embeddings import tokenize

ROOT = Path(__file__).resolve().parents[1]
DENSE_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def _normalize(vector) -> np.ndarray:
    materialized = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(materialized))
    return materialized / norm if norm else materialized


def _order(scores) -> list[int]:
    return sorted(range(len(scores)), key=lambda index: (-scores[index], index))


def _ranks(scores) -> list[int]:
    ranked = [0] * len(scores)
    for rank, index in enumerate(_order(scores), start=1):
        ranked[index] = rank
    return ranked


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[int(fraction * (len(ordered) - 1))]


def _metrics(rankings: list[list[str]], cases: list[dict], latencies: list[float]) -> dict:
    reciprocal_ranks: list[float] = []
    discounted_gains: list[float] = []
    hits = {1: 0, 3: 0, 5: 0}
    by_category: dict[str, list[int]] = {}
    for ranking, case in zip(rankings, cases, strict=True):
        rank = next(
            (index for index, source in enumerate(ranking, start=1) if source == case["expected_source"]),
            None,
        )
        reciprocal_ranks.append(1 / rank if rank else 0)
        discounted_gains.append(1 / np.log2(rank + 1) if rank else 0)
        for cutoff in hits:
            hits[cutoff] += int(rank is not None and rank <= cutoff)
        by_category.setdefault(case["category"], []).append(int(rank == 1))
    count = len(cases)
    return {
        "hit_at_1": round(hits[1] / count, 4),
        "hit_at_3": round(hits[3] / count, 4),
        "hit_at_5": round(hits[5] / count, 4),
        "mrr_at_5": round(statistics.fmean(reciprocal_ranks), 4),
        "ndcg_at_5": round(statistics.fmean(discounted_gains), 4),
        "mean_ms": round(statistics.fmean(latencies), 3),
        "p95_ms": round(_percentile(latencies, 0.95), 3),
        "hit_at_1_by_category": {
            category: round(sum(values) / len(values), 4)
            for category, values in sorted(by_category.items())
        },
    }


def main() -> None:
    documents_path = ROOT / "evals/v2_retrieval_documents.jsonl"
    cases_path = ROOT / "evals/v2_retrieval_cases.jsonl"
    documents = [
        json.loads(line) for line in documents_path.read_text(encoding="utf-8").splitlines()
    ]
    all_cases = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines()]
    cases = [case for case in all_cases if not case["expected_abstain"]]
    sources = [document["source"] for document in documents]
    texts = [document["text"] for document in documents]

    bm25 = BM25Okapi([tokenize(text) for text in texts])
    cache_dir = str(ROOT / "data/models/fastembed")
    load_started = time.perf_counter()
    dense = TextEmbedding(model_name=DENSE_MODEL, cache_dir=cache_dir)
    dense_load_ms = (time.perf_counter() - load_started) * 1000
    index_started = time.perf_counter()
    document_vectors = [_normalize(vector) for vector in dense.embed(texts)]
    dense_index_ms = (time.perf_counter() - index_started) * 1000

    child_texts: list[str] = []
    child_sources: list[str] = []
    for source, text in zip(sources, texts, strict=True):
        for child in split_text(text, size=350, overlap=50):
            child_texts.append(child)
            child_sources.append(source)
    parent_child_bm25 = BM25Okapi([tokenize(text) for text in child_texts])

    def rank_bm25(question: str) -> list[str]:
        return [sources[index] for index in _order(bm25.get_scores(tokenize(question)))[:5]]

    def rank_rrf(question: str) -> list[str]:
        sparse_scores = [float(score) for score in bm25.get_scores(tokenize(question))]
        query_vector = _normalize(next(dense.query_embed(question)))
        dense_scores = [float(np.dot(query_vector, vector)) for vector in document_vectors]
        sparse_ranks = _ranks(sparse_scores)
        dense_ranks = _ranks(dense_scores)
        fused_scores = [
            1 / (60 + sparse_rank) + 1 / (60 + dense_rank)
            for sparse_rank, dense_rank in zip(sparse_ranks, dense_ranks, strict=True)
        ]
        return [sources[index] for index in _order(fused_scores)[:5]]

    def rank_parent_child(question: str) -> list[str]:
        ordered_children = _order(parent_child_bm25.get_scores(tokenize(question)))
        results: list[str] = []
        for child_index in ordered_children:
            source = child_sources[child_index]
            if source not in results:
                results.append(source)
            if len(results) == 5:
                break
        return results

    rankers = {
        "bm25": rank_bm25,
        "rrf": rank_rrf,
        "parent_child": rank_parent_child,
    }
    rankings: dict[str, list[list[str]]] = {name: [] for name in (*rankers, "adaptive")}
    latencies: dict[str, list[float]] = {name: [] for name in rankings}
    route_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    route_trace: list[dict[str, object]] = []
    policy = AdaptiveRoutingPolicy(dense_available=True, parent_child_available=True)

    for case in cases:
        for name, ranker in rankers.items():
            started = time.perf_counter()
            ranking = ranker(case["question"])
            latencies[name].append((time.perf_counter() - started) * 1000)
            rankings[name].append(ranking)

        started = time.perf_counter()
        decision = route_retrieval(case["question"], policy=policy)
        adaptive_ranking = rankers[decision.strategy](case["question"])
        latencies["adaptive"].append((time.perf_counter() - started) * 1000)
        rankings["adaptive"].append(adaptive_ranking)
        route_counts[decision.strategy] += 1
        reason_counts[decision.reason_code] += 1
        route_trace.append(
            {
                "case_id": case["id"],
                "category": case["category"],
                "strategy": decision.strategy,
                "reason_code": decision.reason_code,
                "confidence": decision.confidence,
            }
        )

    all_route_decisions = [route_retrieval(case["question"], policy=policy) for case in all_cases]
    all_route_counts = Counter(decision.strategy for decision in all_route_decisions)
    result_metrics = {
        name: _metrics(rankings[name], cases, latencies[name]) for name in rankings
    }
    best_fixed_hit_at_1 = max(result_metrics[name]["hit_at_1"] for name in rankers)

    probes = [
        "PACS DICOM TLS 握手失败的处置要求是什么？",
        "为什么接口拥塞会同时影响消息确认和消费延迟，请解释两者区别？",
        "结合全文和多个章节，说明 ZEBRA-417 的先决条件、完整步骤以及后续验证。",
    ]
    report = {
        "benchmark": "medops-adaptive-routing-frozen-v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "dataset": {
            "documents": len(documents),
            "answerable_questions": len(cases),
            "negative_questions": len(all_cases) - len(cases),
            "sha256": {
                documents_path.name: hashlib.sha256(documents_path.read_bytes()).hexdigest(),
                cases_path.name: hashlib.sha256(cases_path.read_bytes()).hexdigest(),
            },
        },
        "model": {
            "dense": DENSE_MODEL,
            "dense_load_ms": round(dense_load_ms, 3),
            "dense_index_ms": round(dense_index_ms, 3),
        },
        "policy": {
            "dense_available": policy.dense_available,
            "parent_child_available": policy.parent_child_available,
            "semantic_score_threshold": policy.semantic_score_threshold,
            "parent_score_threshold": policy.parent_score_threshold,
            "user_strategy_override": False,
        },
        "results": result_metrics,
        "adaptive_selection": {
            "answerable_route_counts": dict(sorted(route_counts.items())),
            "all_query_route_counts": dict(sorted(all_route_counts.items())),
            "answerable_reason_counts": dict(sorted(reason_counts.items())),
            "mean_confidence": round(
                statistics.fmean(item["confidence"] for item in route_trace), 4
            ),
            "quality_delta_hit_at_1_vs_best_fixed": round(
                result_metrics["adaptive"]["hit_at_1"] - best_fixed_hit_at_1, 4
            ),
            "trace": route_trace,
        },
        "route_probes": [route_retrieval(query, policy=policy).as_dict() for query in probes],
        "findings": [
            (
                "The router is deterministic and exposes reason, confidence, features, and "
                "candidate scores."
            ),
            (
                "Identifier-heavy queries prefer BM25; paraphrastic or multi-concept queries use "
                "RRF; explicit broad-context queries use parent-child retrieval."
            ),
            (
                "The adaptive route must be connected behind the ordinary answer API; no user "
                "strategy override is part of the router interface."
            ),
            (
                "Quality on this small template corpus is close to saturation, so a zero or small "
                "delta does not prove general superiority."
            ),
        ],
        "limitations": [
            "Template-generated operations corpus, not production traffic or a clinical-validity evaluation.",
            "Only 120 answerable and 20 negative questions with one relevant document per answerable query.",
            (
                "All frozen documents fit in one 350-character retrieval child, so parent-child "
                "collapses to document-level BM25 on this corpus."
            ),
            (
                "The frozen set has no explicit cross-section questions; parent-child selection is "
                "demonstrated by deterministic route probes and separate existing long-context "
                "benchmarks."
            ),
            "Dense model files are cached and model download/load time is excluded from per-query latency.",
            (
                "The router does not perform abstention; domain, safety, score-threshold, and "
                "citation gates remain separate stages."
            ),
            (
                "The deterministic threshold was calibrated while inspecting this frozen corpus; "
                "its quality result is in-sample and needs a separately held-out traffic set."
            ),
        ],
    }
    output = ROOT / "reports/adaptive-routing-benchmark-v3.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
