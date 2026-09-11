"""Integrity gates for the frozen adaptive-routing challenge V3."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from app.retrieval.adaptive import AdaptiveRoutingPolicy
from app.retrieval.embeddings import tokenize
from evals.benchmark_adaptive_challenge_v3 import NEAR_DUPLICATE_THRESHOLD, _leakage_audit

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS_PATH = ROOT / "evals/adaptive_challenge_v3_documents_zh.jsonl"
CASES_PATH = ROOT / "evals/adaptive_challenge_v3_cases_zh.jsonl"
FREEZE_PATH = ROOT / "evals/adaptive_challenge_v3_freeze.json"
RUNNER_PATH = ROOT / "evals/benchmark_adaptive_challenge_v3.py"
REPORT_PATH = ROOT / "reports/adaptive-routing-challenge-zh-v3.json"
ROUTER_PATH = ROOT / "app/retrieval/adaptive.py"


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v3_dataset_has_required_independent_contracts():
    documents = _jsonl(DOCUMENTS_PATH)
    cases = _jsonl(CASES_PATH)
    documents_by_source = {str(document["source"]): document for document in documents}

    assert len(documents) == 28
    assert len(documents_by_source) == 28
    assert Counter(document["tenant_id"] for document in documents) == {"hospital-cobalt": 28}
    assert len(cases) == 36
    assert Counter(case["category"] for case in cases) == {
        "typo_noise": 10,
        "low_lexical_overlap": 10,
        "three_source_conflict": 5,
        "three_source_combination": 3,
        "independent_unanswerable": 8,
    }
    assert Counter(case["evaluation"] for case in cases) == {
        "source_ranking": 20,
        "multi_source_coverage": 8,
        "negative_route_only": 8,
    }
    assert len({str(case["question"]) for case in cases}) == len(cases)
    assert all(str(case["id"]).startswith("ch3-") for case in cases)
    assert all(re.search(r"[\u4e00-\u9fff]", str(case["question"])) for case in cases)

    for case in cases:
        expected = [str(source) for source in case["expected_sources"]]
        if case["evaluation"] == "source_ranking":
            assert len(expected) == 1
            assert case["expected_abstain"] is False
        elif case["evaluation"] == "multi_source_coverage":
            assert len(expected) == 3
            assert case["expected_abstain"] is False
        else:
            assert case["category"] == "independent_unanswerable"
            assert expected == []
            assert case["expected_abstain"] is True
        for source in expected:
            assert source in documents_by_source
            assert documents_by_source[source]["tenant_id"] == case["tenant_id"]


def test_v3_noise_low_overlap_and_three_source_fixtures_are_real():
    documents = {str(document["source"]): document for document in _jsonl(DOCUMENTS_PATH)}
    cases = _jsonl(CASES_PATH)

    noise_cases = [case for case in cases if case["category"] == "typo_noise"]
    assert all(len(case.get("noise_tags", [])) >= 2 for case in noise_cases)
    noisy_markers = (
        "!!",
        "???",
        "🔒",
        "ㄋ",
        "2",
        "辣",
        "冰厢",
        "病仁",
        "采雪",
        "条马",
        "中秧",
    )
    assert all(any(marker in str(case["question"]) for marker in noisy_markers) for case in noise_cases)

    semantic_cases = [case for case in cases if case["category"] == "low_lexical_overlap"]
    for case in semantic_cases:
        question_tokens = set(tokenize(str(case["question"])))
        document_tokens = set(tokenize(str(documents[str(case["expected_sources"][0])]["text"])))
        assert len(question_tokens & document_tokens) / len(question_tokens) <= 0.40

    multi_cases = [case for case in cases if case["evaluation"] == "multi_source_coverage"]
    assert len({tuple(case["expected_sources"]) for case in multi_cases}) == 4
    assert all(len(set(case["expected_sources"])) == 3 for case in multi_cases)


def test_v3_freeze_manifest_matches_the_dataset_exactly():
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))

    assert freeze["dataset"] == "medops-adaptive-routing-challenge-zh-v3"
    assert freeze["dataset_version"] == "3.0.0"
    assert freeze["frozen_before_engine_run"] is True
    assert freeze["files"] == {
        DOCUMENTS_PATH.name: {"sha256": _sha256(DOCUMENTS_PATH), "rows": 28},
        CASES_PATH.name: {"sha256": _sha256(CASES_PATH), "rows": 36},
    }


def test_v3_strict_leakage_audit_passes_all_three_prior_sets():
    audit = _leakage_audit(_jsonl(DOCUMENTS_PATH), _jsonl(CASES_PATH))

    assert audit["near_duplicate_threshold"] == NEAR_DUPLICATE_THRESHOLD == 0.85
    assert set(audit["prior_sets"]) == {"threshold_tuning", "heldout_v1", "challenge_v2"}
    assert audit["totals"] == {
        "exact_normalized_question_overlap": 0,
        "source_name_overlap": 0,
        "exact_document_content_hash_overlap": 0,
        "near_duplicate_question_count": 0,
    }
    assert audit["near_duplicate_matches"] == []
    assert audit["all_leakage_checks_passed"] is True


def test_checked_v3_report_matches_frozen_inputs_current_router_and_denominators():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    policy = AdaptiveRoutingPolicy(dense_available=True)

    assert report["benchmark"] == "medops-adaptive-routing-challenge-zh-v3"
    assert report["benchmark_version"] == "3.0.0"
    assert report["dataset_version"] == "3.0.0"
    assert report["dataset"]["sha256"] == {
        DOCUMENTS_PATH.name: _sha256(DOCUMENTS_PATH),
        CASES_PATH.name: _sha256(CASES_PATH),
        FREEZE_PATH.name: _sha256(FREEZE_PATH),
        RUNNER_PATH.name: _sha256(RUNNER_PATH),
        "app/retrieval/adaptive.py": _sha256(ROUTER_PATH),
    }
    assert report["dataset"]["leakage_audit"]["all_leakage_checks_passed"] is True
    contract = report["evaluation_contract"]
    assert contract["dataset_frozen_before_engine_run"] is True
    assert contract["freeze_manifest_verified"] is True
    assert contract["thresholds_changed_for_this_dataset"] is False
    assert contract["application_router_modified_for_this_dataset"] is False
    assert contract["provider_or_application_api_calls"] == 0
    assert contract["source_ranking_denominator"] == 20
    assert contract["multi_source_coverage_denominator"] == 8
    assert contract["negative_cases_used_for_quality_metrics"] == 0
    assert report["policy_snapshot"]["semantic_score_threshold"] == policy.semantic_score_threshold
    assert report["policy_snapshot"]["parent_score_threshold"] == policy.parent_score_threshold
    assert set(report["source_ranking"]) == {"bm25", "rrf", "parent_child", "adaptive"}
    assert set(report["multi_source_coverage"]) == {"bm25", "rrf", "parent_child", "adaptive"}
    assert all(value["evaluated_cases"] == 20 for value in report["source_ranking"].values())
    assert all(value["evaluated_cases"] == 8 for value in report["multi_source_coverage"].values())


def test_v3_negative_scope_does_not_make_an_abstention_claim():
    negative = json.loads(REPORT_PATH.read_text(encoding="utf-8"))["negative_route_only"]

    assert negative["evaluated_cases"] == 8
    assert negative["quality_metrics_computed"] is False
    assert negative["abstention_accuracy_computed"] is False
    assert sum(negative["route_counts"].values()) == 8
    assert "hit_at_1" not in negative
    assert "abstention_accuracy" not in negative


def test_v3_runner_hard_disables_network_and_has_no_provider_path_or_tuning():
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
    assert "app.services.answers" not in source
    assert "app.agents.model" not in source
