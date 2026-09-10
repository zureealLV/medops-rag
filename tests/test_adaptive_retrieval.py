"""Boundary tests for internal adaptive text-retrieval routing."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from app.retrieval.adaptive import (
    AdaptiveRoutingPolicy,
    extract_query_features,
    route_retrieval,
)


def test_exact_identifier_query_uses_low_latency_bm25():
    decision = route_retrieval(
        "PACS DICOM TLS 握手失败的处置要求是什么？",
        policy=AdaptiveRoutingPolicy(dense_available=True),
    )
    assert decision.strategy == "bm25"
    assert decision.reason_code == "exact_or_identifier_lookup"
    assert decision.features.exact_identifier_count >= 3
    assert 0.5 <= decision.confidence <= 1


def test_paraphrastic_multi_concept_query_uses_rrf_when_dense_is_available():
    decision = route_retrieval(
        "为什么同一种接口拥塞会同时影响消息确认和消费延迟，请解释两者区别？",
        policy=AdaptiveRoutingPolicy(dense_available=True),
    )
    assert decision.strategy == "rrf"
    assert decision.reason_code == "semantic_or_multi_concept_query"
    assert decision.features.semantic_cue_count >= 2
    assert decision.features.multi_part is True


def test_semantic_query_has_explicit_bm25_fallback_when_dense_is_disabled():
    decision = route_retrieval(
        "为什么同一种接口拥塞会同时影响消息确认和消费延迟，请解释两者区别？",
        policy=AdaptiveRoutingPolicy(dense_available=False),
    )
    assert decision.strategy == "bm25"
    assert decision.reason_code == "dense_unavailable_bm25_fallback"
    assert "administrator-disabled" in decision.reason


def test_cross_section_request_takes_parent_child_precedence_over_identifiers():
    decision = route_retrieval(
        "结合全文和多个章节，说明 ZEBRA-417 的先决条件、完整步骤以及后续验证。",
        policy=AdaptiveRoutingPolicy(dense_available=True),
    )
    assert decision.strategy == "parent_child"
    assert decision.reason_code == "broad_context_required"
    assert decision.features.long_context_cue_count >= 3
    assert decision.features.exact_identifier_count >= 1


def test_parent_child_capability_can_only_be_disabled_by_internal_policy():
    decision = route_retrieval(
        "结合全文和多个章节说明完整流程以及后续验证。",
        policy=AdaptiveRoutingPolicy(dense_available=True, parent_child_available=False),
    )
    assert decision.strategy == "rrf"
    assert decision.reason_code == "semantic_or_multi_concept_query"


def test_default_route_is_deterministic_and_trace_is_json_safe():
    policy = AdaptiveRoutingPolicy(dense_available=True)
    first = route_retrieval("归档存储容量告警处理要求", policy=policy)
    second = route_retrieval("归档存储容量告警处理要求", policy=policy)
    assert first == second
    assert first.strategy == "bm25"
    assert first.reason_code == "lexical_default"
    payload = first.as_dict()
    assert payload["strategy"] == "bm25"
    assert set(payload["candidate_scores"]) == {"bm25", "rrf", "parent_child"}


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
def test_empty_query_is_rejected(query: str):
    with pytest.raises(ValueError, match="must not be empty"):
        extract_query_features(query)


def test_router_has_no_user_requested_strategy_escape_hatch():
    parameters = inspect.signature(route_retrieval).parameters
    assert set(parameters) == {"query", "policy"}
    with pytest.raises(TypeError):
        route_retrieval(  # type: ignore[call-arg]
            "LIS queue backlog",
            policy=AdaptiveRoutingPolicy(dense_available=True),
            requested_strategy="vector",
        )


def test_policy_thresholds_reject_non_positive_values():
    with pytest.raises(ValueError, match="thresholds must be positive"):
        AdaptiveRoutingPolicy(dense_available=True, semantic_score_threshold=0)


def test_checked_in_frozen_benchmark_compares_all_routes_and_records_limitations():
    root = Path(__file__).resolve().parents[1]
    report = json.loads(
        (root / "reports/adaptive-routing-benchmark-v3.json").read_text(encoding="utf-8")
    )
    assert report["dataset"]["answerable_questions"] == 120
    assert set(report["results"]) == {"bm25", "rrf", "parent_child", "adaptive"}
    assert report["results"]["adaptive"]["hit_at_1"] >= report["results"]["bm25"]["hit_at_1"]
    assert report["adaptive_selection"]["answerable_route_counts"] == {"bm25": 60, "rrf": 60}
    assert any("in-sample" in limitation for limitation in report["limitations"])
