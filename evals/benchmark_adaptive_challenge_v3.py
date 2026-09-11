"""Run the frozen, offline adaptive-routing challenge V3.

V3 is independent of the threshold-tuning, heldout-v1, and challenge-v2
datasets.  It evaluates noisy/typo queries, low lexical-overlap paraphrases,
and three-source evidence questions under separate ranking contracts.  The
independent unanswerable cases inspect router behaviour only: this retrieval
benchmark has no answer/evidence gate and therefore makes no abstention claim.

The dataset freeze manifest is verified before the current production router
is exercised or the dense model is loaded.  The encoder may only be opened from the local
cache, and a socket guard converts every network attempt into a hard failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import socket
import statistics
import subprocess
import time
import tomllib
import unicodedata
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from difflib import SequenceMatcher
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

# Assignment, not setdefault: caller environment cannot weaken offline mode.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import numpy as np
from fastembed import TextEmbedding
from rank_bm25 import BM25Okapi

from app.retrieval.adaptive import AdaptiveRoutingPolicy, route_retrieval
from app.retrieval.chunking import split_text
from app.retrieval.embeddings import tokenize

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS_PATH = ROOT / "evals/adaptive_challenge_v3_documents_zh.jsonl"
CASES_PATH = ROOT / "evals/adaptive_challenge_v3_cases_zh.jsonl"
FREEZE_PATH = ROOT / "evals/adaptive_challenge_v3_freeze.json"
DEFAULT_OUTPUT = ROOT / "reports/adaptive-routing-challenge-zh-v3.json"
ROUTER_PATH = ROOT / "app/retrieval/adaptive.py"
RUNNER_PATH = Path(__file__).resolve()
DENSE_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
BENCHMARK_VERSION = "3.0.0"
DATASET_VERSION = "3.0.0"
NEAR_DUPLICATE_THRESHOLD = 0.85

PRIOR_DATASETS = {
    "threshold_tuning": {
        "cases": ROOT / "evals/v2_retrieval_cases.jsonl",
        "documents": ROOT / "evals/v2_retrieval_documents.jsonl",
    },
    "heldout_v1": {
        "cases": ROOT / "evals/adaptive_heldout_cases_zh.jsonl",
        "documents": ROOT / "evals/adaptive_heldout_documents_zh.jsonl",
    },
    "challenge_v2": {
        "cases": ROOT / "evals/adaptive_challenge_v2_cases_zh.jsonl",
        "documents": ROOT / "evals/adaptive_challenge_v2_documents_zh.jsonl",
    },
}

Ranking = list[str]


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalized(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value)).casefold()
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", normalized)


def _verify_dataset_freeze() -> dict[str, object]:
    manifest = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    if manifest.get("dataset") != "medops-adaptive-routing-challenge-zh-v3":
        raise RuntimeError("unexpected V3 freeze manifest dataset")
    if manifest.get("dataset_version") != DATASET_VERSION:
        raise RuntimeError("V3 freeze manifest version mismatch")
    if manifest.get("frozen_before_engine_run") is not True:
        raise RuntimeError("V3 dataset was not declared frozen before evaluation")

    expected_files = manifest.get("files")
    if not isinstance(expected_files, dict):
        raise RuntimeError("V3 freeze manifest has no files object")
    for path in (DOCUMENTS_PATH, CASES_PATH):
        entry = expected_files.get(path.name)
        if not isinstance(entry, dict):
            raise RuntimeError(f"V3 freeze manifest is missing {path.name}")
        actual_hash = _sha256(path)
        actual_rows = len(_read_jsonl(path))
        if entry.get("sha256") != actual_hash or entry.get("rows") != actual_rows:
            raise RuntimeError(f"frozen V3 dataset mismatch: {path.name}")
    return manifest


def _normalize_vector(vector: object) -> np.ndarray:
    values = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(values))
    return values / norm if norm else values


def _order(scores: list[float] | np.ndarray) -> list[int]:
    return sorted(range(len(scores)), key=lambda index: (-float(scores[index]), index))


def _ranks(scores: list[float]) -> list[int]:
    result = [0] * len(scores)
    for rank, index in enumerate(_order(scores), start=1):
        result[index] = rank
    return result


@contextmanager
def _network_disabled():
    """Make network use observable instead of trusting only offline flags."""

    def blocked(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("adaptive challenge V3 forbids all network connections")

    with (
        patch.object(socket.socket, "connect", blocked),
        patch.object(socket, "create_connection", blocked),
    ):
        yield


class TenantRankers:
    """Fixed local rankers over the already tenant-filtered V3 documents."""

    def __init__(self, documents: list[dict[str, object]], dense: TextEmbedding) -> None:
        self.sources = [str(document["source"]) for document in documents]
        self.texts = [str(document["text"]) for document in documents]
        self.sparse = BM25Okapi([tokenize(text) for text in self.texts])
        self.document_vectors = [_normalize_vector(vector) for vector in dense.embed(self.texts)]
        self.dense = dense

        self.child_sources: list[str] = []
        child_texts: list[str] = []
        for source, text in zip(self.sources, self.texts, strict=True):
            for child in split_text(text, size=350, overlap=50):
                self.child_sources.append(source)
                child_texts.append(child)
        self.child_sparse = BM25Okapi([tokenize(text) for text in child_texts])

    def bm25(self, query: str) -> Ranking:
        return [self.sources[index] for index in _order(self.sparse.get_scores(tokenize(query)))[:5]]

    def rrf(self, query: str) -> Ranking:
        sparse_scores = [float(value) for value in self.sparse.get_scores(tokenize(query))]
        query_vector = _normalize_vector(next(self.dense.query_embed(query)))
        dense_scores = [
            float(np.dot(query_vector, document_vector)) for document_vector in self.document_vectors
        ]
        sparse_ranks = _ranks(sparse_scores)
        dense_ranks = _ranks(dense_scores)
        fused_scores = [
            1 / (60 + sparse_rank) + 1 / (60 + dense_rank)
            for sparse_rank, dense_rank in zip(sparse_ranks, dense_ranks, strict=True)
        ]
        return [self.sources[index] for index in _order(fused_scores)[:5]]

    def parent_child(self, query: str) -> Ranking:
        ranking: Ranking = []
        for child_index in _order(self.child_sparse.get_scores(tokenize(query))):
            source = self.child_sources[child_index]
            if source not in ranking:
                ranking.append(source)
            if len(ranking) == 5:
                break
        return ranking

    def rank(self, strategy: str, query: str) -> Ranking:
        if strategy == "bm25":
            return self.bm25(query)
        if strategy == "rrf":
            return self.rrf(query)
        if strategy == "parent_child":
            return self.parent_child(query)
        raise ValueError(f"unsupported strategy: {strategy}")


def _source_ranking_metrics(
    rankings: list[Ranking], cases: list[dict[str, object]]
) -> dict[str, object]:
    hits = {1: 0, 3: 0, 5: 0}
    reciprocal_ranks: list[float] = []
    discounted_gains: list[float] = []
    category_hits: dict[str, list[int]] = {}
    trace: list[dict[str, object]] = []

    for ranking, case in zip(rankings, cases, strict=True):
        expected = str(list(case["expected_sources"])[0])
        rank = next(
            (position for position, source in enumerate(ranking, start=1) if source == expected),
            None,
        )
        for cutoff in hits:
            hits[cutoff] += int(rank is not None and rank <= cutoff)
        reciprocal_ranks.append(1 / rank if rank is not None and rank <= 5 else 0.0)
        discounted_gains.append(1 / float(np.log2(rank + 1)) if rank and rank <= 5 else 0.0)
        category = str(case["category"])
        category_hits.setdefault(category, []).append(int(rank == 1))
        trace.append(
            {
                "case_id": case["id"],
                "category": category,
                "expected_source": expected,
                "rank": rank,
                "top_sources": ranking,
            }
        )

    count = len(cases)
    return {
        "evaluated_cases": count,
        "hit_at_1": round(hits[1] / count, 4),
        "hit_at_3": round(hits[3] / count, 4),
        "hit_at_5": round(hits[5] / count, 4),
        "mrr_at_5": round(statistics.fmean(reciprocal_ranks), 4),
        "ndcg_at_5": round(statistics.fmean(discounted_gains), 4),
        "hit_at_1_by_category": {
            category: round(sum(values) / len(values), 4)
            for category, values in sorted(category_hits.items())
        },
        "trace": trace,
    }


def _multi_source_metrics(
    rankings: list[Ranking], cases: list[dict[str, object]]
) -> dict[str, object]:
    recalls = {3: [], 5: []}
    full_coverage = {3: [], 5: []}
    category_recall: dict[str, list[float]] = {}
    traces: list[dict[str, object]] = []
    for ranking, case in zip(rankings, cases, strict=True):
        expected = {str(source) for source in case["expected_sources"]}
        case_metrics: dict[str, object] = {}
        for cutoff in (3, 5):
            retrieved = set(ranking[:cutoff])
            recall = len(expected & retrieved) / len(expected)
            covered = expected <= retrieved
            recalls[cutoff].append(recall)
            full_coverage[cutoff].append(int(covered))
            case_metrics[f"recall_at_{cutoff}"] = round(recall, 4)
            case_metrics[f"full_coverage_at_{cutoff}"] = covered
        category_recall.setdefault(str(case["category"]), []).append(float(case_metrics["recall_at_5"]))
        traces.append(
            {
                "case_id": case["id"],
                "category": case["category"],
                "expected_sources": sorted(expected),
                "top_sources": ranking,
                **case_metrics,
            }
        )
    return {
        "evaluated_cases": len(cases),
        "mean_recall_at_3": round(statistics.fmean(recalls[3]), 4),
        "mean_recall_at_5": round(statistics.fmean(recalls[5]), 4),
        "full_coverage_at_3": round(statistics.fmean(full_coverage[3]), 4),
        "full_coverage_at_5": round(statistics.fmean(full_coverage[5]), 4),
        "mean_recall_at_5_by_category": {
            category: round(statistics.fmean(values), 4)
            for category, values in sorted(category_recall.items())
        },
        "trace": traces,
    }


def _leakage_audit(
    documents: list[dict[str, object]], cases: list[dict[str, object]]
) -> dict[str, object]:
    current_questions = {_normalized(case["question"]): str(case["id"]) for case in cases}
    current_sources = {str(document["source"]) for document in documents}
    current_content_hashes = {
        hashlib.sha256(str(document["text"]).encode("utf-8")).hexdigest() for document in documents
    }
    by_dataset: dict[str, object] = {}
    global_near_matches: list[dict[str, object]] = []

    for name, paths in PRIOR_DATASETS.items():
        prior_cases = _read_jsonl(paths["cases"])
        prior_documents = _read_jsonl(paths["documents"])
        prior_questions = {_normalized(case["question"]): str(case["id"]) for case in prior_cases}
        prior_sources = {str(document["source"]) for document in prior_documents}
        prior_content_hashes = {
            hashlib.sha256(str(document["text"]).encode("utf-8")).hexdigest()
            for document in prior_documents
        }

        near_matches: list[dict[str, object]] = []
        maximum = {"ratio": 0.0, "v3_case_id": None, "prior_case_id": None}
        for current_question, current_id in current_questions.items():
            for prior_question, prior_id in prior_questions.items():
                ratio = SequenceMatcher(None, current_question, prior_question).ratio()
                if ratio > maximum["ratio"]:
                    maximum = {
                        "ratio": round(ratio, 4),
                        "v3_case_id": current_id,
                        "prior_case_id": prior_id,
                    }
                if ratio >= NEAR_DUPLICATE_THRESHOLD:
                    near_matches.append(
                        {
                            "ratio": round(ratio, 4),
                            "v3_case_id": current_id,
                            "prior_case_id": prior_id,
                        }
                    )
        global_near_matches.extend({"prior_dataset": name, **match} for match in near_matches)
        by_dataset[name] = {
            "exact_normalized_question_overlap": len(current_questions.keys() & prior_questions.keys()),
            "source_name_overlap": len(current_sources & prior_sources),
            "exact_document_content_hash_overlap": len(current_content_hashes & prior_content_hashes),
            "near_duplicate_question_threshold": NEAR_DUPLICATE_THRESHOLD,
            "near_duplicate_question_count": len(near_matches),
            "maximum_question_similarity": maximum,
        }

    exact_question_total = sum(
        int(result["exact_normalized_question_overlap"])
        for result in by_dataset.values()
        if isinstance(result, dict)
    )
    source_total = sum(
        int(result["source_name_overlap"])
        for result in by_dataset.values()
        if isinstance(result, dict)
    )
    content_total = sum(
        int(result["exact_document_content_hash_overlap"])
        for result in by_dataset.values()
        if isinstance(result, dict)
    )
    return {
        "normalization": "Unicode NFKC + casefold + remove whitespace/punctuation",
        "near_duplicate_method": "difflib.SequenceMatcher over normalized question text",
        "near_duplicate_threshold": NEAR_DUPLICATE_THRESHOLD,
        "prior_sets": by_dataset,
        "totals": {
            "exact_normalized_question_overlap": exact_question_total,
            "source_name_overlap": source_total,
            "exact_document_content_hash_overlap": content_total,
            "near_duplicate_question_count": len(global_near_matches),
        },
        "near_duplicate_matches": global_near_matches,
        "all_leakage_checks_passed": not any(
            (exact_question_total, source_total, content_total, len(global_near_matches))
        ),
    }


def _git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def run_benchmark(*, repetitions: int = 1) -> dict[str, object]:
    if repetitions < 1:
        raise ValueError("repetitions must be at least one")

    freeze = _verify_dataset_freeze()
    documents = _read_jsonl(DOCUMENTS_PATH)
    cases = _read_jsonl(CASES_PATH)
    leakage = _leakage_audit(documents, cases)
    if not leakage["all_leakage_checks_passed"]:
        raise RuntimeError("V3 leakage audit failed; evaluation aborted")

    source_cases = [case for case in cases if case["evaluation"] == "source_ranking"]
    multi_cases = [case for case in cases if case["evaluation"] == "multi_source_coverage"]
    negative_cases = [case for case in cases if case["evaluation"] == "negative_route_only"]

    documents_by_tenant: dict[str, list[dict[str, object]]] = {}
    for document in documents:
        documents_by_tenant.setdefault(str(document["tenant_id"]), []).append(document)

    policy = AdaptiveRoutingPolicy(dense_available=True, parent_child_available=True)
    fixed_strategies = ("bm25", "rrf", "parent_child")
    all_strategies = (*fixed_strategies, "adaptive")
    source_rankings: dict[str, list[Ranking]] = {strategy: [] for strategy in all_strategies}
    multi_rankings: dict[str, list[Ranking]] = {strategy: [] for strategy in all_strategies}
    latency_samples: dict[str, list[float]] = {strategy: [] for strategy in all_strategies}
    adaptive_route_counts: dict[str, Counter[str]] = {
        "source_ranking": Counter(),
        "multi_source_coverage": Counter(),
        "negative_route_only": Counter(),
    }
    adaptive_reason_counts: dict[str, Counter[str]] = {
        scope: Counter() for scope in adaptive_route_counts
    }
    route_trace: list[dict[str, object]] = []

    model_load_started = time.perf_counter()
    with _network_disabled():
        try:
            dense = TextEmbedding(
                model_name=DENSE_MODEL,
                cache_dir=str(ROOT / "data/models/fastembed"),
                local_files_only=True,
            )
            rankers_by_tenant = {
                tenant_id: TenantRankers(tenant_documents, dense)
                for tenant_id, tenant_documents in documents_by_tenant.items()
            }
        except Exception as error:  # pragma: no cover - depends on workstation cache
            raise RuntimeError(
                "Offline dense model unavailable or a network attempt was blocked. Populate "
                "data/models/fastembed separately; this benchmark will not download."
            ) from error
        model_load_and_index_ms = (time.perf_counter() - model_load_started) * 1000

        for scope, selected_cases, destination in (
            ("source_ranking", source_cases, source_rankings),
            ("multi_source_coverage", multi_cases, multi_rankings),
        ):
            for case in selected_cases:
                query = str(case["question"])
                rankers = rankers_by_tenant[str(case["tenant_id"])]
                for strategy in fixed_strategies:
                    first: Ranking | None = None
                    for _ in range(repetitions):
                        started = time.perf_counter()
                        ranking = rankers.rank(strategy, query)
                        latency_samples[strategy].append((time.perf_counter() - started) * 1000)
                        first = first or ranking
                    destination[strategy].append(first or [])

                decision = route_retrieval(query, policy=policy)
                first_adaptive: Ranking | None = None
                for _ in range(repetitions):
                    started = time.perf_counter()
                    repeated = route_retrieval(query, policy=policy)
                    ranking = rankers.rank(repeated.strategy, query)
                    latency_samples["adaptive"].append((time.perf_counter() - started) * 1000)
                    first_adaptive = first_adaptive or ranking
                destination["adaptive"].append(first_adaptive or [])
                adaptive_route_counts[scope][decision.strategy] += 1
                adaptive_reason_counts[scope][decision.reason_code] += 1
                route_trace.append(
                    {
                        "case_id": case["id"],
                        "evaluation": scope,
                        "strategy": decision.strategy,
                        "reason_code": decision.reason_code,
                        "confidence": decision.confidence,
                    }
                )

        # Routing is not an answer/evidence gate.  These negative cases are
        # intentionally excluded from all retrieval-quality denominators.
        for case in negative_cases:
            decision = route_retrieval(str(case["question"]), policy=policy)
            adaptive_route_counts["negative_route_only"][decision.strategy] += 1
            adaptive_reason_counts["negative_route_only"][decision.reason_code] += 1
            route_trace.append(
                {
                    "case_id": case["id"],
                    "evaluation": "negative_route_only",
                    "strategy": decision.strategy,
                    "reason_code": decision.reason_code,
                    "confidence": decision.confidence,
                }
            )

    source_results = {
        strategy: _source_ranking_metrics(source_rankings[strategy], source_cases)
        for strategy in source_rankings
    }
    multi_results = {
        strategy: _multi_source_metrics(multi_rankings[strategy], multi_cases)
        for strategy in multi_rankings
    }
    latency = {
        strategy: {
            "samples": len(values),
            "mean_ms": round(statistics.fmean(values), 3),
            "p50_ms": round(statistics.median(values), 3),
            "p95_ms": round(sorted(values)[int(0.95 * (len(values) - 1))], 3),
        }
        for strategy, values in latency_samples.items()
    }
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    return {
        "benchmark": "medops-adaptive-routing-challenge-zh-v3",
        "benchmark_version": BENCHMARK_VERSION,
        "dataset_version": DATASET_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(),
        "evaluation_contract": {
            "dataset_frozen_before_engine_run": True,
            "freeze_manifest_verified": True,
            "thresholds_changed_for_this_dataset": False,
            "application_router_modified_for_this_dataset": False,
            "user_strategy_override": False,
            "provider_or_application_api_calls": 0,
            "network_access": "hard-disabled-by-socket-guard",
            "source_ranking_denominator": len(source_cases),
            "multi_source_coverage_denominator": len(multi_cases),
            "negative_cases_used_for_quality_metrics": 0,
            "negative_case_purpose": "adaptive route/reason distribution only; no abstention claim",
        },
        "dataset": {
            "language": "zh-CN",
            "documents": len(documents),
            "documents_by_tenant": dict(
                sorted(Counter(str(doc["tenant_id"]) for doc in documents).items())
            ),
            "cases": len(cases),
            "category_counts": dict(sorted(Counter(str(case["category"]) for case in cases).items())),
            "evaluation_counts": dict(
                sorted(Counter(str(case["evaluation"]) for case in cases).items())
            ),
            "freeze": {
                "frozen_at": freeze["frozen_at"],
                "manifest_sha256": _sha256(FREEZE_PATH),
                "files": freeze["files"],
            },
            "leakage_audit": leakage,
            "sha256": {
                DOCUMENTS_PATH.name: _sha256(DOCUMENTS_PATH),
                CASES_PATH.name: _sha256(CASES_PATH),
                FREEZE_PATH.name: _sha256(FREEZE_PATH),
                RUNNER_PATH.name: _sha256(RUNNER_PATH),
                "app/retrieval/adaptive.py": _sha256(ROUTER_PATH),
            },
        },
        "runtime": {
            "project": project["project"]["name"],
            "project_version": project["project"]["version"],
            "git_commit": _git_revision(),
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
        "policy_snapshot": {
            "dense_available": policy.dense_available,
            "parent_child_available": policy.parent_child_available,
            "semantic_score_threshold": policy.semantic_score_threshold,
            "parent_score_threshold": policy.parent_score_threshold,
        },
        "source_ranking": source_results,
        "multi_source_coverage": multi_results,
        "negative_route_only": {
            "evaluated_cases": len(negative_cases),
            "quality_metrics_computed": False,
            "abstention_accuracy_computed": False,
            "route_counts": dict(sorted(adaptive_route_counts["negative_route_only"].items())),
            "reason_counts": dict(sorted(adaptive_reason_counts["negative_route_only"].items())),
        },
        "adaptive_selection": {
            "route_counts_by_scope": {
                scope: dict(sorted(counts.items())) for scope, counts in adaptive_route_counts.items()
            },
            "reason_counts_by_scope": {
                scope: dict(sorted(counts.items())) for scope, counts in adaptive_reason_counts.items()
            },
            "trace": route_trace,
        },
        "latency": latency,
        "findings_scope": [
            "Source ranking evaluates 20 cases with exactly one relevant source.",
            "Three-source questions use macro recall and all-three coverage, never Hit@1.",
            "Independent unanswerable questions inspect deterministic routing only.",
            (
                "Leakage gates cover exact questions, near-duplicate questions, source names, "
                "and content hashes."
            ),
        ],
        "limitations": [
            "This is a frozen handcrafted synthetic challenge, not blinded production traffic.",
            "Labels were authored before the run but were not independently double-annotated.",
            "Typo and noise patterns are selected examples, not an empirical hospital error distribution.",
            (
                "Low lexical-overlap labels express author intent; retrieval success does not prove "
                "clinical semantic equivalence."
            ),
            (
                "Three-source coverage proves only that sources appear in top-K, not that generated "
                "prose resolves conflicts or faithfully composes every required fact."
            ),
            (
                "The router is a strategy selector, not an abstention classifier; negative cases "
                "cannot establish correct refusal or answer safety."
            ),
            (
                "No provider, answer-generation API, application endpoint, authentication layer, "
                "or tenant-isolation path is exercised in this V3 run."
            ),
            "Latency is a single-machine snapshot and excludes model load/index construction.",
            "No routing threshold or application code was changed after inspecting V3 scores.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run_benchmark(repetitions=args.repetitions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
