"""Integrity gates for the independent Chinese adaptive-routing evaluation."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from app.retrieval.chunking import split_text

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS_PATH = ROOT / "evals/adaptive_heldout_documents_zh.jsonl"
CASES_PATH = ROOT / "evals/adaptive_heldout_cases_zh.jsonl"
TUNING_DOCUMENTS_PATH = ROOT / "evals/v2_retrieval_documents.jsonl"
TUNING_CASES_PATH = ROOT / "evals/v2_retrieval_cases.jsonl"
REPORT_PATH = ROOT / "reports/adaptive-routing-heldout-zh-v1.json"
RUNNER_PATH = ROOT / "evals/benchmark_adaptive_heldout_zh.py"


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _normalized_question(value: object) -> str:
    return re.sub(r"\s+", "", str(value)).casefold()


def test_heldout_dataset_is_chinese_balanced_and_referentially_valid():
    documents = _jsonl(DOCUMENTS_PATH)
    cases = _jsonl(CASES_PATH)
    sources = {document["source"] for document in documents}

    assert len(documents) == 20
    assert len(sources) == len(documents)
    assert Counter(case["category"] for case in cases) == {
        "exact": 8,
        "paraphrase": 8,
        "multi_concept": 8,
        "long_context": 8,
        "unanswerable": 8,
    }
    assert len({_normalized_question(case["question"]) for case in cases}) == len(cases)
    assert len({str(case["question"])[:6] for case in cases}) == len(cases)
    assert all(re.search(r"[\u4e00-\u9fff]", str(case["question"])) for case in cases)

    for case in cases:
        if case["expected_abstain"]:
            assert case["category"] == "unanswerable"
            assert case["expected_source"] is None
        else:
            assert case["category"] != "unanswerable"
            assert case["expected_source"] in sources


def test_heldout_questions_have_zero_exact_reuse_from_threshold_tuning_set():
    heldout = {
        _normalized_question(case["question"])
        for case in _jsonl(CASES_PATH)
    }
    tuning = {
        _normalized_question(case["question"])
        for case in _jsonl(TUNING_CASES_PATH)
    }
    assert heldout.isdisjoint(tuning)
    assert all(str(case["id"]).startswith("hd-") for case in _jsonl(CASES_PATH))

    heldout_sources = {document["source"] for document in _jsonl(DOCUMENTS_PATH)}
    tuning_sources = {document["source"] for document in _jsonl(TUNING_DOCUMENTS_PATH)}
    assert heldout_sources.isdisjoint(tuning_sources)


def test_long_context_cases_target_documents_that_really_split_into_children():
    documents = {document["source"]: document for document in _jsonl(DOCUMENTS_PATH)}
    long_sources = {
        case["expected_source"]
        for case in _jsonl(CASES_PATH)
        if case["category"] == "long_context"
    }

    assert len(long_sources) == 8
    for source in long_sources:
        text = str(documents[source]["text"])
        assert len(text) > 350
        assert len(split_text(text, size=350, overlap=50)) >= 2


def test_checked_in_report_matches_dataset_and_excludes_negatives_from_hit_metrics():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    contract = report["evaluation_contract"]

    assert report["benchmark"] == "medops-adaptive-routing-heldout-zh-v1"
    assert report["dataset"]["answerable_questions"] == 32
    assert report["dataset"]["negative_questions"] == 8
    assert report["dataset"]["sha256"] == {
        DOCUMENTS_PATH.name: hashlib.sha256(DOCUMENTS_PATH.read_bytes()).hexdigest(),
        CASES_PATH.name: hashlib.sha256(CASES_PATH.read_bytes()).hexdigest(),
    }
    assert contract["relationship_to_threshold_tuning_set"] == (
        "independent_files_with_zero_exact_question_reuse"
    )
    assert contract["thresholds_changed_for_this_dataset"] is False
    assert contract["answerable_cases_used_for_hit_metrics"] == 32
    assert contract["negative_cases_used_for_hit_metrics"] == 0
    assert contract["provider_or_application_api_calls"] == 0
    assert set(report["results"]) == {"bm25", "rrf", "parent_child", "adaptive"}
    assert all(
        result["evaluated_answerable_questions"] == 32
        for result in report["results"].values()
    )
    assert sum(report["adaptive_selection"]["negative_route_counts"].values()) == 8
    assert len(report["adaptive_selection"]["negative_trace"]) == 8


def test_report_freezes_honest_heldout_result_instead_of_claiming_adaptive_superiority():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert report["results"]["bm25"]["hit_at_1"] == 1.0
    assert report["results"]["rrf"]["hit_at_1"] == 0.9062
    assert report["results"]["parent_child"]["hit_at_1"] == 1.0
    assert report["results"]["adaptive"]["hit_at_1"] == 1.0
    assert report["adaptive_selection"]["hit_at_1_delta_vs_best_fixed"] == 0.0
    assert report["adaptive_selection"]["answerable_route_counts"] == {
        "bm25": 16,
        "parent_child": 6,
        "rrf": 10,
    }
    assert any("not blinded" in limitation for limitation in report["limitations"])


def test_runner_forces_local_dense_model_and_has_no_provider_secret_path():
    source = RUNNER_PATH.read_text(encoding="utf-8")

    assert 'os.environ["HF_HUB_OFFLINE"] = "1"' in source
    assert 'os.environ["TRANSFORMERS_OFFLINE"] = "1"' in source
    assert "local_files_only=True" in source
    assert "DEEPSEEK_API_KEY" not in source
    assert "MODEL_API_KEY" not in source
    assert "httpx" not in source
