"""Integrity gates for the disjoint adaptive-routing challenge v2."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from app.retrieval.adaptive import AdaptiveRoutingPolicy
from app.retrieval.chunking import split_text

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS_PATH = ROOT / "evals/adaptive_challenge_v2_documents_zh.jsonl"
CASES_PATH = ROOT / "evals/adaptive_challenge_v2_cases_zh.jsonl"
RUNNER_PATH = ROOT / "evals/benchmark_adaptive_challenge_v2.py"
REPORT_PATH = ROOT / "reports/adaptive-routing-challenge-zh-v2.json"
ROUTER_PATH = ROOT / "app/retrieval/adaptive.py"
PRIOR_CASE_PATHS = (
    ROOT / "evals/v2_retrieval_cases.jsonl",
    ROOT / "evals/adaptive_heldout_cases_zh.jsonl",
)
PRIOR_DOCUMENT_PATHS = (
    ROOT / "evals/v2_retrieval_documents.jsonl",
    ROOT / "evals/adaptive_heldout_documents_zh.jsonl",
)


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _normalized(value: object) -> str:
    return re.sub(r"\s+", "", str(value)).casefold()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_challenge_v2_has_four_disjoint_evaluation_contracts():
    documents = _jsonl(DOCUMENTS_PATH)
    cases = _jsonl(CASES_PATH)
    documents_by_source = {str(document["source"]): document for document in documents}

    assert len(documents) == 28
    assert len(documents_by_source) == 28
    assert Counter(document["tenant_id"] for document in documents) == {
        "hospital-green": 20,
        "hospital-amber": 4,
        "hospital-violet": 4,
    }
    assert len(cases) == 48
    assert Counter(case["category"] for case in cases) == {
        "ambiguous_short": 8,
        "table_text": 8,
        "long_context": 8,
        "multi_source": 8,
        "unanswerable": 8,
        "tenant_isolation": 8,
    }
    assert Counter(case["evaluation"] for case in cases) == {
        "source_ranking": 24,
        "multi_source_coverage": 8,
        "negative_route_only": 8,
        "tenant_isolation": 8,
    }
    assert len({_normalized(case["question"]) for case in cases}) == len(cases)
    assert all(str(case["id"]).startswith("ch2-") for case in cases)
    assert all(re.search(r"[\u4e00-\u9fff]", str(case["question"])) for case in cases)

    for case in cases:
        expected = [str(source) for source in case["expected_sources"]]
        evaluation = case["evaluation"]
        if evaluation == "source_ranking":
            assert len(expected) == 1
            assert case["expected_abstain"] is False
        elif evaluation == "multi_source_coverage":
            assert len(expected) == 2
            assert case["expected_abstain"] is False
        else:
            assert expected == []
            assert case["expected_abstain"] is True
        for source in expected:
            assert source in documents_by_source
            assert documents_by_source[source]["tenant_id"] == case["tenant_id"]


def test_challenge_v2_has_zero_exact_reuse_from_both_prior_sets():
    questions = {_normalized(case["question"]) for case in _jsonl(CASES_PATH)}
    prior_questions = {_normalized(case["question"]) for path in PRIOR_CASE_PATHS for case in _jsonl(path)}
    sources = {str(document["source"]) for document in _jsonl(DOCUMENTS_PATH)}
    prior_sources = {str(document["source"]) for path in PRIOR_DOCUMENT_PATHS for document in _jsonl(path)}
    content_hashes = {
        hashlib.sha256(str(document["text"]).encode()).hexdigest() for document in _jsonl(DOCUMENTS_PATH)
    }
    prior_content_hashes = {
        hashlib.sha256(str(document["text"]).encode()).hexdigest()
        for path in PRIOR_DOCUMENT_PATHS
        for document in _jsonl(path)
    }

    assert questions.isdisjoint(prior_questions)
    assert sources.isdisjoint(prior_sources)
    assert content_hashes.isdisjoint(prior_content_hashes)


def test_short_table_long_and_multi_source_fixtures_have_real_structure():
    documents = {str(document["source"]): document for document in _jsonl(DOCUMENTS_PATH)}
    cases = _jsonl(CASES_PATH)

    short_cases = [case for case in cases if case["category"] == "ambiguous_short"]
    assert all(len(_normalized(case["question"])) <= 8 for case in short_cases)

    table_sources = {str(case["expected_sources"][0]) for case in cases if case["category"] == "table_text"}
    assert len(table_sources) == 4
    for source in table_sources:
        text = str(documents[source]["text"])
        assert text.count("|") >= 10
        assert "\n|" in text

    long_sources = {str(case["expected_sources"][0]) for case in cases if case["category"] == "long_context"}
    assert len(long_sources) == 4
    for source in long_sources:
        text = str(documents[source]["text"])
        assert len(text) > 350
        assert len(split_text(text, size=350, overlap=50)) >= 2

    multi_cases = [case for case in cases if case["evaluation"] == "multi_source_coverage"]
    assert len({tuple(case["expected_sources"]) for case in multi_cases}) == 4


def test_tenant_cases_target_real_foreign_only_markers():
    documents = _jsonl(DOCUMENTS_PATH)
    cases = [case for case in _jsonl(CASES_PATH) if case["evaluation"] == "tenant_isolation"]

    for case in cases:
        targets = [
            document
            for document in documents
            if document["tenant_id"] == case["forbidden_tenant"]
            and document["source"] == case["forbidden_source"]
        ]
        assert len(targets) == 1
        marker = str(case["forbidden_marker"])
        assert marker in str(targets[0]["text"])
        assert case["tenant_id"] != case["forbidden_tenant"]
        assert not any(
            marker in str(document["text"])
            for document in documents
            if document["tenant_id"] == case["tenant_id"]
        )


def test_checked_report_matches_hashes_versions_and_metric_denominators():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    policy = AdaptiveRoutingPolicy(dense_available=True)

    assert report["benchmark"] == "medops-adaptive-routing-challenge-zh-v2"
    assert report["benchmark_version"] == "2.0.0"
    assert report["dataset_version"] == "2.0.0"
    assert report["dataset"]["sha256"] == {
        DOCUMENTS_PATH.name: _sha256(DOCUMENTS_PATH),
        CASES_PATH.name: _sha256(CASES_PATH),
        RUNNER_PATH.name: _sha256(RUNNER_PATH),
        "app/retrieval/adaptive.py": _sha256(ROUTER_PATH),
    }
    assert report["dataset"]["exact_normalized_question_overlap_with_tuning_and_heldout_v1"] == 0
    assert report["dataset"]["source_name_overlap_with_tuning_and_heldout_v1"] == 0
    contract = report["evaluation_contract"]
    assert contract["thresholds_changed_for_this_dataset"] is False
    assert contract["source_ranking_denominator"] == 24
    assert contract["multi_source_coverage_denominator"] == 8
    assert contract["negative_cases_used_for_quality_metrics"] == 0
    assert contract["tenant_cases_used_for_quality_metrics"] == 0
    assert contract["provider_or_application_api_calls"] == 0
    assert report["policy_snapshot"]["semantic_score_threshold"] == policy.semantic_score_threshold
    assert report["policy_snapshot"]["parent_score_threshold"] == policy.parent_score_threshold
    assert set(report["source_ranking"]) == {"bm25", "rrf", "parent_child", "adaptive"}
    assert set(report["multi_source_coverage"]) == {
        "bm25",
        "rrf",
        "parent_child",
        "adaptive",
    }
    assert all(value["evaluated_cases"] == 24 for value in report["source_ranking"].values())
    assert all(value["evaluated_cases"] == 8 for value in report["multi_source_coverage"].values())


def test_negative_scope_makes_no_abstention_or_hit_claim():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    negative = report["negative_route_only"]

    assert negative["evaluated_cases"] == 8
    assert negative["quality_metrics_computed"] is False
    assert sum(negative["route_counts"].values()) == 8
    assert "hit_at_1" not in negative
    assert "abstention_accuracy" not in negative


def test_actual_sqlite_tenant_probes_are_all_fail_closed():
    isolation = json.loads(REPORT_PATH.read_text(encoding="utf-8"))["tenant_isolation"]

    assert "app.repositories.documents" in isolation["contract"]
    assert "app.services.retrieval" in isolation["contract"]
    assert isolation["evaluated_probes"] == 8
    assert isolation["foreign_targets_proven_present"] == 8
    assert isolation["leak_count"] == 0
    assert isolation["foreign_kb_id_hidden_count"] == 8
    assert isolation["all_passed"] is True
    assert len(isolation["trace"]) == 8
    for item in isolation["trace"]:
        assert item["foreign_source_exists"] is True
        assert item["repository_prefilter_excludes_foreign_source"] is True
        assert item["fts_prefilter_excludes_foreign_source"] is True
        assert item["search_results_exclude_foreign_source"] is True
        assert item["search_results_exclude_foreign_marker"] is True
        assert item["foreign_kb_id_hidden"] is True
        assert item["leaked"] is False


def test_runner_hard_disables_network_and_contains_no_provider_path():
    source = RUNNER_PATH.read_text(encoding="utf-8")

    assert 'os.environ["HF_HUB_OFFLINE"] = "1"' in source
    assert 'os.environ["TRANSFORMERS_OFFLINE"] = "1"' in source
    assert "local_files_only=True" in source
    assert 'patch.object(socket.socket, "connect", blocked)' in source
    assert "DEEPSEEK_API_KEY" not in source
    assert "MODEL_API_KEY" not in source
    assert "httpx" not in source
    assert "semantic_score_threshold=" not in source
    assert "parent_score_threshold=" not in source
