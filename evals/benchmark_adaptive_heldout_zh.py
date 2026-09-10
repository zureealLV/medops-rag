"""Offline held-out evaluation for MedOps adaptive retrieval routing.

This benchmark is intentionally separate from ``v2_retrieval_cases.jsonl``,
which was used while the current routing thresholds were developed.  It makes
no model-provider or application API calls: the dense encoder is loaded only
from the checked local FastEmbed cache with Hugging Face offline mode forced.

Retrieval-quality metrics are calculated only for answerable cases.  Negative
cases have no relevant document, so they are used only to inspect route/reason
distribution; treating them as misses would make Hit@K mathematically invalid.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

# Enforce offline behavior before FastEmbed/Hugging Face is imported.  Assignment
# (rather than setdefault) prevents a caller's online setting from weakening the gate.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import numpy as np
from fastembed import TextEmbedding
from rank_bm25 import BM25Okapi

from app.retrieval.adaptive import AdaptiveRoutingPolicy, route_retrieval
from app.retrieval.chunking import split_text
from app.retrieval.embeddings import tokenize

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS_PATH = ROOT / "evals/adaptive_heldout_documents_zh.jsonl"
CASES_PATH = ROOT / "evals/adaptive_heldout_cases_zh.jsonl"
DEFAULT_OUTPUT = ROOT / "reports/adaptive-routing-heldout-zh-v1.json"
DENSE_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

Ranking = list[str]
Ranker = Callable[[str], Ranking]


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalize(vector: object) -> np.ndarray:
    materialized = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(materialized))
    return materialized / norm if norm else materialized


def _order(scores: list[float] | np.ndarray) -> list[int]:
    return sorted(range(len(scores)), key=lambda index: (-float(scores[index]), index))


def _ranks(scores: list[float]) -> list[int]:
    result = [0] * len(scores)
    for rank, index in enumerate(_order(scores), start=1):
        result[index] = rank
    return result


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[int(fraction * (len(ordered) - 1))]


def _quality_metrics(rankings: list[Ranking], cases: list[dict[str, object]]) -> dict[str, object]:
    hits = {1: 0, 3: 0, 5: 0}
    reciprocal_ranks: list[float] = []
    discounted_gains: list[float] = []
    hit_at_1_by_category: dict[str, list[int]] = {}

    for ranking, case in zip(rankings, cases, strict=True):
        expected_source = str(case["expected_source"])
        rank = next(
            (position for position, source in enumerate(ranking, start=1) if source == expected_source),
            None,
        )
        reciprocal_ranks.append(1 / rank if rank is not None and rank <= 5 else 0.0)
        discounted_gains.append(
            1 / float(np.log2(rank + 1)) if rank is not None and rank <= 5 else 0.0
        )
        for cutoff in hits:
            hits[cutoff] += int(rank is not None and rank <= cutoff)
        category = str(case["category"])
        hit_at_1_by_category.setdefault(category, []).append(int(rank == 1))

    count = len(cases)
    return {
        "evaluated_answerable_questions": count,
        "hit_at_1": round(hits[1] / count, 4),
        "hit_at_3": round(hits[3] / count, 4),
        "hit_at_5": round(hits[5] / count, 4),
        "mrr_at_5": round(statistics.fmean(reciprocal_ranks), 4),
        "ndcg_at_5": round(statistics.fmean(discounted_gains), 4),
        "hit_at_1_by_category": {
            category: round(sum(values) / len(values), 4)
            for category, values in sorted(hit_at_1_by_category.items())
        },
    }


def _latency_metrics(latencies: list[float]) -> dict[str, float]:
    return {
        "samples": len(latencies),
        "mean_ms": round(statistics.fmean(latencies), 3),
        "p50_ms": round(statistics.median(latencies), 3),
        "p95_ms": round(_percentile(latencies, 0.95), 3),
    }


def run_benchmark(*, repetitions: int = 3) -> dict[str, object]:
    """Run a provider-free benchmark and return a JSON-serializable report."""
    if repetitions < 1:
        raise ValueError("repetitions must be at least one")

    documents = _read_jsonl(DOCUMENTS_PATH)
    all_cases = _read_jsonl(CASES_PATH)
    answerable_cases = [case for case in all_cases if not bool(case["expected_abstain"])]
    negative_cases = [case for case in all_cases if bool(case["expected_abstain"])]
    sources = [str(document["source"]) for document in documents]
    texts = [str(document["text"]) for document in documents]

    sparse = BM25Okapi([tokenize(text) for text in texts])
    child_texts: list[str] = []
    child_sources: list[str] = []
    for source, text in zip(sources, texts, strict=True):
        for child in split_text(text, size=350, overlap=50):
            child_texts.append(child)
            child_sources.append(source)
    child_sparse = BM25Okapi([tokenize(text) for text in child_texts])

    cache_dir = ROOT / "data/models/fastembed"
    model_load_started = time.perf_counter()
    try:
        dense = TextEmbedding(
            model_name=DENSE_MODEL,
            cache_dir=str(cache_dir),
            local_files_only=True,
        )
        document_vectors = [_normalize(vector) for vector in dense.embed(texts)]
    except Exception as error:  # pragma: no cover - failure depends on workstation cache
        raise RuntimeError(
            "Offline dense model is unavailable. Populate data/models/fastembed in a separate "
            "approved step, then rerun; this benchmark will not download a model automatically."
        ) from error
    model_load_and_index_ms = (time.perf_counter() - model_load_started) * 1000

    def rank_bm25(question: str) -> Ranking:
        scores = sparse.get_scores(tokenize(question))
        return [sources[index] for index in _order(scores)[:5]]

    def rank_rrf(question: str) -> Ranking:
        sparse_scores = [float(score) for score in sparse.get_scores(tokenize(question))]
        query_vector = _normalize(next(dense.query_embed(question)))
        dense_scores = [float(np.dot(query_vector, vector)) for vector in document_vectors]
        sparse_ranks = _ranks(sparse_scores)
        dense_ranks = _ranks(dense_scores)
        fused_scores = [
            1 / (60 + sparse_rank) + 1 / (60 + dense_rank)
            for sparse_rank, dense_rank in zip(sparse_ranks, dense_ranks, strict=True)
        ]
        return [sources[index] for index in _order(fused_scores)[:5]]

    def rank_parent_child(question: str) -> Ranking:
        child_order = _order(child_sparse.get_scores(tokenize(question)))
        ranking: list[str] = []
        for child_index in child_order:
            source = child_sources[child_index]
            if source not in ranking:
                ranking.append(source)
            if len(ranking) == 5:
                break
        return ranking

    fixed_rankers: dict[str, Ranker] = {
        "bm25": rank_bm25,
        "rrf": rank_rrf,
        "parent_child": rank_parent_child,
    }
    policy = AdaptiveRoutingPolicy(dense_available=True, parent_child_available=True)
    rankings: dict[str, list[Ranking]] = {
        name: [] for name in (*fixed_rankers, "adaptive")
    }
    latencies: dict[str, list[float]] = {name: [] for name in rankings}
    answerable_route_counts: Counter[str] = Counter()
    answerable_reason_counts: Counter[str] = Counter()
    adaptive_trace: list[dict[str, object]] = []

    for case in answerable_cases:
        question = str(case["question"])
        for name, ranker in fixed_rankers.items():
            first_ranking: Ranking | None = None
            for _ in range(repetitions):
                started = time.perf_counter()
                ranking = ranker(question)
                latencies[name].append((time.perf_counter() - started) * 1000)
                first_ranking = first_ranking or ranking
            rankings[name].append(first_ranking or [])

        first_adaptive_ranking: Ranking | None = None
        decision = route_retrieval(question, policy=policy)
        for _ in range(repetitions):
            started = time.perf_counter()
            repeated_decision = route_retrieval(question, policy=policy)
            ranking = fixed_rankers[repeated_decision.strategy](question)
            latencies["adaptive"].append((time.perf_counter() - started) * 1000)
            first_adaptive_ranking = first_adaptive_ranking or ranking
        rankings["adaptive"].append(first_adaptive_ranking or [])
        answerable_route_counts[decision.strategy] += 1
        answerable_reason_counts[decision.reason_code] += 1
        adaptive_trace.append(
            {
                "case_id": case["id"],
                "category": case["category"],
                "strategy": decision.strategy,
                "reason_code": decision.reason_code,
                "confidence": decision.confidence,
                "top_source": (first_adaptive_ranking or [None])[0],
                "expected_source": case["expected_source"],
            }
        )

    negative_decisions = [
        (case, route_retrieval(str(case["question"]), policy=policy)) for case in negative_cases
    ]
    negative_route_counts = Counter(decision.strategy for _, decision in negative_decisions)
    negative_reason_counts = Counter(decision.reason_code for _, decision in negative_decisions)

    results: dict[str, dict[str, object]] = {}
    for name in rankings:
        results[name] = {
            **_quality_metrics(rankings[name], answerable_cases),
            "latency": _latency_metrics(latencies[name]),
        }

    best_fixed_hit_at_1 = max(float(results[name]["hit_at_1"]) for name in fixed_rankers)
    category_counts = Counter(str(case["category"]) for case in all_cases)
    long_sources = {
        str(case["expected_source"])
        for case in answerable_cases
        if case["category"] == "long_context"
    }
    long_source_lengths = {
        str(document["source"]): len(str(document["text"]))
        for document in documents
        if str(document["source"]) in long_sources
    }

    return {
        "benchmark": "medops-adaptive-routing-heldout-zh-v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "evaluation_contract": {
            "relationship_to_threshold_tuning_set": "independent_files_with_zero_exact_question_reuse",
            "thresholds_changed_for_this_dataset": False,
            "answerable_cases_used_for_hit_metrics": len(answerable_cases),
            "negative_cases_used_for_hit_metrics": 0,
            "negative_case_purpose": "route/reason distribution only; abstention is a later gate",
            "provider_or_application_api_calls": 0,
        },
        "dataset": {
            "language": "zh-CN",
            "documents": len(documents),
            "answerable_questions": len(answerable_cases),
            "negative_questions": len(negative_cases),
            "category_counts": dict(sorted(category_counts.items())),
            "long_context_source_characters": dict(sorted(long_source_lengths.items())),
            "sha256": {
                DOCUMENTS_PATH.name: _sha256(DOCUMENTS_PATH),
                CASES_PATH.name: _sha256(CASES_PATH),
            },
        },
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "fastembed": version("fastembed"),
            "rank_bm25": version("rank-bm25"),
            "numpy": version("numpy"),
            "dense_model": DENSE_MODEL,
            "dense_cache": "data/models/fastembed",
            "dense_local_files_only": True,
            "hf_hub_offline": os.environ["HF_HUB_OFFLINE"],
            "transformers_offline": os.environ["TRANSFORMERS_OFFLINE"],
            "model_load_and_document_index_ms": round(model_load_and_index_ms, 3),
            "query_repetitions": repetitions,
        },
        "policy": {
            "dense_available": policy.dense_available,
            "parent_child_available": policy.parent_child_available,
            "semantic_score_threshold": policy.semantic_score_threshold,
            "parent_score_threshold": policy.parent_score_threshold,
            "user_strategy_override": False,
        },
        "results": results,
        "adaptive_selection": {
            "answerable_route_counts": dict(sorted(answerable_route_counts.items())),
            "answerable_reason_counts": dict(sorted(answerable_reason_counts.items())),
            "negative_route_counts": dict(sorted(negative_route_counts.items())),
            "negative_reason_counts": dict(sorted(negative_reason_counts.items())),
            "hit_at_1_delta_vs_best_fixed": round(
                float(results["adaptive"]["hit_at_1"]) - best_fixed_hit_at_1, 4
            ),
            "trace": adaptive_trace,
            "negative_trace": [
                {
                    "case_id": case["id"],
                    "strategy": decision.strategy,
                    "reason_code": decision.reason_code,
                    "confidence": decision.confidence,
                }
                for case, decision in negative_decisions
            ],
        },
        "findings_scope": [
            (
                "This measures retrieval ranking and deterministic route selection, not "
                "generated-answer correctness."
            ),
            "Hit@K, MRR, and nDCG exclude unanswerable cases because no relevant source exists for them.",
            "Negative cases expose route behavior only; domain and abstention gates remain separate stages.",
        ],
        "limitations": [
            (
                "The set is independent from the existing threshold-tuning files but was not "
                "blinded or preregistered."
            ),
            (
                "It contains 20 synthetic Chinese operations documents and is not production "
                "traffic or clinical validation."
            ),
            (
                "Each answerable question has one labeled relevant source; graded or "
                "multi-source relevance is not measured."
            ),
            "Latency is a single-machine snapshot and excludes model load/index time from per-query samples.",
            (
                "RRF uses a locally cached multilingual MiniLM encoder, not a separately selected "
                "Chinese embedding winner."
            ),
            (
                "The routing policy does not itself decide abstention, tenant authorization, or "
                "citation sufficiency."
            ),
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    report = run_benchmark(repetitions=args.repetitions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
