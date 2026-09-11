"""Offline adaptive-routing challenge v2 with disjoint metrics and tenant probes.

This benchmark is deliberately isolated from both the threshold-tuning dataset
and heldout-v1.  It does not tune routing policy.  Source ranking, multi-source
coverage, negative route inspection, and tenant isolation are evaluated as four
different contracts because combining them into one Hit@K value is misleading.

The dense encoder may only be opened from the checked local cache.  Hugging Face
offline flags are forced before importing FastEmbed, and a socket guard turns any
attempted network connection into a hard benchmark failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import statistics
import subprocess
import tempfile
import time
import tomllib
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
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

from app.config import Settings
from app.db import initialize, transaction
from app.models.documents import DocumentCreate
from app.models.knowledge_bases import KnowledgeBaseCreate
from app.models.retrieval import SearchRequest
from app.repositories import documents as document_repository
from app.repositories import knowledge_bases as knowledge_base_repository
from app.retrieval.adaptive import AdaptiveRoutingPolicy, route_retrieval
from app.retrieval.chunking import split_text
from app.retrieval.embeddings import tokenize
from app.services import documents as document_service
from app.services.retrieval import search

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS_PATH = ROOT / "evals/adaptive_challenge_v2_documents_zh.jsonl"
CASES_PATH = ROOT / "evals/adaptive_challenge_v2_cases_zh.jsonl"
DEFAULT_OUTPUT = ROOT / "reports/adaptive-routing-challenge-zh-v2.json"
ROUTER_PATH = ROOT / "app/retrieval/adaptive.py"
RUNNER_PATH = Path(__file__).resolve()
DENSE_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
BENCHMARK_VERSION = "2.0.0"
DATASET_VERSION = "2.0.0"

Ranking = list[str]


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalized(value: object) -> str:
    return "".join(str(value).casefold().split())


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
    """Make a network attempt observable instead of trusting environment flags."""

    def blocked(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("adaptive challenge v2 forbids all network connections")

    with (
        patch.object(socket.socket, "connect", blocked),
        patch.object(socket, "create_connection", blocked),
    ):
        yield


class TenantRankers:
    """Three fixed rankers built only from one tenant's already-filtered documents."""

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


def _source_ranking_metrics(rankings: list[Ranking], cases: list[dict[str, object]]) -> dict[str, object]:
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


def _multi_source_metrics(rankings: list[Ranking], cases: list[dict[str, object]]) -> dict[str, object]:
    recalls = {3: [], 5: []}
    full_coverage = {3: [], 5: []}
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
        traces.append(
            {
                "case_id": case["id"],
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
        "trace": traces,
    }


def _actual_tenant_isolation_probe(
    documents: list[dict[str, object]], cases: list[dict[str, object]]
) -> dict[str, object]:
    """Exercise production SQLite repository/service filtering, not a fake corpus slice."""
    traces: list[dict[str, object]] = []
    leaks = 0
    foreign_kb_hidden = 0
    with tempfile.TemporaryDirectory(prefix="medops-challenge-v2-") as directory:
        db_path = Path(directory) / "challenge.db"
        initialize(db_path)
        settings = Settings(database_path=db_path, text_embedding_enabled=False)
        kb_ids: dict[str, int] = {}
        for tenant_id in sorted({str(document["tenant_id"]) for document in documents}):
            kb = knowledge_base_repository.create(
                db_path,
                tenant_id,
                KnowledgeBaseCreate(name="challenge-v2", description="ephemeral offline probe"),
            )
            kb_ids[tenant_id] = kb.id
        for document in documents:
            tenant_id = str(document["tenant_id"])
            created = document_service.create(
                db_path,
                settings,
                tenant_id,
                kb_ids[tenant_id],
                DocumentCreate(
                    title=str(document["title"]),
                    content=str(document["text"]),
                    source=str(document["source"]),
                ),
            )
            if created is None:  # pragma: no cover - indicates a broken fixture setup
                raise AssertionError(f"failed to seed {document['source']}")

        for case in cases:
            actor_tenant = str(case["tenant_id"])
            forbidden_tenant = str(case["forbidden_tenant"])
            forbidden_source = str(case["forbidden_source"])
            forbidden_marker = str(case["forbidden_marker"])

            with transaction(db_path) as connection:
                foreign = connection.execute(
                    "SELECT source, content FROM documents WHERE tenant_id = ? AND source = ?",
                    (forbidden_tenant, forbidden_source),
                ).fetchone()
            if foreign is None or forbidden_marker not in str(foreign["content"]):
                raise AssertionError("isolation probe has no real foreign target")

            repository_sources = {
                str(row["source"]) for row in document_repository.retrieval_rows(db_path, actor_tenant)
            }
            lexical_rows = document_repository.lexical_candidate_rows(
                db_path, actor_tenant, None, str(case["question"]), limit=50
            )
            lexical_sources = {str(row["source"]) for row in (lexical_rows or [])}
            response = search(
                db_path,
                actor_tenant,
                SearchRequest(
                    query=str(case["question"]),
                    strategy="auto",
                    query_transform="none",
                    top_k=5,
                ),
                settings,
            )
            if response is None:  # pragma: no cover - global tenant search must return an object
                raise AssertionError("global scoped search unexpectedly returned None")
            returned_sources = {item.source for item in response.results}
            returned_text = "\n".join(item.text for item in response.results)
            cross_kb_response = search(
                db_path,
                actor_tenant,
                SearchRequest(
                    query=str(case["question"]),
                    knowledge_base_id=kb_ids[forbidden_tenant],
                    strategy="auto",
                    query_transform="none",
                    top_k=5,
                ),
                settings,
            )
            kb_hidden = cross_kb_response is None
            leaked = any(
                (
                    forbidden_source in repository_sources,
                    forbidden_source in lexical_sources,
                    forbidden_source in returned_sources,
                    forbidden_marker in returned_text,
                    not kb_hidden,
                )
            )
            leaks += int(leaked)
            foreign_kb_hidden += int(kb_hidden)
            traces.append(
                {
                    "case_id": case["id"],
                    "actor_tenant": actor_tenant,
                    "foreign_tenant": forbidden_tenant,
                    "foreign_source_exists": True,
                    "repository_prefilter_excludes_foreign_source": (
                        forbidden_source not in repository_sources
                    ),
                    "fts_prefilter_excludes_foreign_source": forbidden_source not in lexical_sources,
                    "search_results_exclude_foreign_source": forbidden_source not in returned_sources,
                    "search_results_exclude_foreign_marker": forbidden_marker not in returned_text,
                    "foreign_kb_id_hidden": kb_hidden,
                    "resolved_strategy": response.strategy,
                    "leaked": leaked,
                }
            )

    return {
        "contract": (
            "real app.repositories.documents + app.services.retrieval over an ephemeral SQLite "
            "database; tenant predicate is applied before ranking"
        ),
        "evaluated_probes": len(cases),
        "foreign_targets_proven_present": len(cases),
        "leak_count": leaks,
        "foreign_kb_id_hidden_count": foreign_kb_hidden,
        "all_passed": leaks == 0 and foreign_kb_hidden == len(cases),
        "trace": traces,
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

    documents = _read_jsonl(DOCUMENTS_PATH)
    cases = _read_jsonl(CASES_PATH)
    source_cases = [case for case in cases if case["evaluation"] == "source_ranking"]
    multi_cases = [case for case in cases if case["evaluation"] == "multi_source_coverage"]
    negative_cases = [case for case in cases if case["evaluation"] == "negative_route_only"]
    tenant_cases = [case for case in cases if case["evaluation"] == "tenant_isolation"]

    documents_by_tenant: dict[str, list[dict[str, object]]] = {}
    for document in documents:
        documents_by_tenant.setdefault(str(document["tenant_id"]), []).append(document)

    policy = AdaptiveRoutingPolicy(dense_available=True, parent_child_available=True)
    fixed_strategies = ("bm25", "rrf", "parent_child")
    source_rankings: dict[str, list[Ranking]] = {strategy: [] for strategy in (*fixed_strategies, "adaptive")}
    multi_rankings: dict[str, list[Ranking]] = {strategy: [] for strategy in (*fixed_strategies, "adaptive")}
    latency_samples: dict[str, list[float]] = {strategy: [] for strategy in (*fixed_strategies, "adaptive")}
    adaptive_route_counts: dict[str, Counter[str]] = {
        "source_ranking": Counter(),
        "multi_source_coverage": Counter(),
        "negative_route_only": Counter(),
        "tenant_isolation": Counter(),
    }
    adaptive_reason_counts: dict[str, Counter[str]] = {scope: Counter() for scope in adaptive_route_counts}
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
                "data/models/fastembed in a separate approved step; this benchmark will not download."
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

        # These two scopes inspect deterministic routing only.  They never run a
        # ranker and are excluded from every retrieval-quality denominator.
        for scope, selected_cases in (
            ("negative_route_only", negative_cases),
            ("tenant_isolation", tenant_cases),
        ):
            for case in selected_cases:
                decision = route_retrieval(str(case["question"]), policy=policy)
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

        tenant_isolation = _actual_tenant_isolation_probe(documents, tenant_cases)

    source_results = {
        strategy: _source_ranking_metrics(source_rankings[strategy], source_cases)
        for strategy in source_rankings
    }
    multi_results = {
        strategy: _multi_source_metrics(multi_rankings[strategy], multi_cases) for strategy in multi_rankings
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

    prior_case_paths = (
        ROOT / "evals/v2_retrieval_cases.jsonl",
        ROOT / "evals/adaptive_heldout_cases_zh.jsonl",
    )
    prior_document_paths = (
        ROOT / "evals/v2_retrieval_documents.jsonl",
        ROOT / "evals/adaptive_heldout_documents_zh.jsonl",
    )
    current_questions = {_normalized(case["question"]) for case in cases}
    prior_questions = {
        _normalized(case["question"]) for path in prior_case_paths for case in _read_jsonl(path)
    }
    current_sources = {str(document["source"]) for document in documents}
    prior_sources = {
        str(document["source"]) for path in prior_document_paths for document in _read_jsonl(path)
    }
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    return {
        "benchmark": "medops-adaptive-routing-challenge-zh-v2",
        "benchmark_version": BENCHMARK_VERSION,
        "dataset_version": DATASET_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(),
        "evaluation_contract": {
            "thresholds_changed_for_this_dataset": False,
            "user_strategy_override": False,
            "provider_or_application_api_calls": 0,
            "network_access": "hard-disabled-by-socket-guard",
            "source_ranking_denominator": len(source_cases),
            "multi_source_coverage_denominator": len(multi_cases),
            "negative_cases_used_for_quality_metrics": 0,
            "tenant_cases_used_for_quality_metrics": 0,
            "negative_case_purpose": "adaptive route/reason distribution only; no abstention claim",
            "tenant_case_purpose": "actual repository/service pre-ranking scope enforcement",
        },
        "dataset": {
            "language": "zh-CN",
            "documents": len(documents),
            "documents_by_tenant": dict(sorted(Counter(str(doc["tenant_id"]) for doc in documents).items())),
            "cases": len(cases),
            "category_counts": dict(sorted(Counter(str(case["category"]) for case in cases).items())),
            "evaluation_counts": dict(sorted(Counter(str(case["evaluation"]) for case in cases).items())),
            "exact_normalized_question_overlap_with_tuning_and_heldout_v1": len(
                current_questions & prior_questions
            ),
            "source_name_overlap_with_tuning_and_heldout_v1": len(current_sources & prior_sources),
            "sha256": {
                DOCUMENTS_PATH.name: _sha256(DOCUMENTS_PATH),
                CASES_PATH.name: _sha256(CASES_PATH),
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
            "route_counts": dict(sorted(adaptive_route_counts["negative_route_only"].items())),
            "reason_counts": dict(sorted(adaptive_reason_counts["negative_route_only"].items())),
        },
        "tenant_isolation": tenant_isolation,
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
            "Source ranking evaluates only cases with exactly one relevant source.",
            "Multi-source questions use macro recall and all-required-sources coverage, not Hit@1.",
            "Unanswerable questions inspect routing only; this benchmark does not claim abstention quality.",
            (
                "Tenant isolation uses the production SQLite repository and retrieval service against "
                "foreign documents proven present in the same ephemeral database."
            ),
        ],
        "limitations": [
            (
                "This is a handcrafted synthetic challenge, not blinded production traffic "
                "or clinical validation."
            ),
            (
                "Ambiguous short-query labels assume a hospital-green operator context; real query logs may "
                "contain more ambiguity and spelling noise."
            ),
            "Markdown tables are evaluated as normalized text; PDF table extraction quality is out of scope.",
            (
                "Multi-source coverage measures source retrieval only and does not verify that a generated "
                "answer faithfully combines every required fact."
            ),
            (
                "Tenant probes exercise production SQLite repository/service predicates, not API-key "
                "authentication, PostgreSQL row-level security, or distributed vector-store filtering."
            ),
            (
                "Latency is a single-machine snapshot and excludes model load/index construction "
                "from query timing."
            ),
            (
                "The cached multilingual MiniLM model was not selected by an independent Chinese "
                "embedding bake-off."
            ),
            "No routing thresholds or application code were changed to improve this report.",
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
