"""Deterministic, explainable routing between the supported text retrievers.

The router deliberately has no ``requested_strategy`` argument.  Retrieval
strategy is an internal policy decision: ordinary answer callers provide a
question, while administrators decide which capabilities are available.

This module only chooses a route.  Tenant filtering, ranking and confidence
gates remain in :mod:`app.services.retrieval`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Literal

from app.retrieval.embeddings import tokenize

AdaptiveStrategy = Literal["bm25", "rrf", "parent_child"]

_QUOTED = re.compile(r"[\"'“”‘’《》](.{2,80}?)[\"'“”‘’《》]")
_EXACT_IDENTIFIER = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"[A-Z]{2,}(?:[-_/.][A-Z0-9]+)*|"
    r"[A-Z][A-Z0-9]*[-_/][A-Z0-9][A-Z0-9._/-]*|"
    r"\d{3,}(?:[-_/.]\d+)+|"
    r"(?:GB|WS|YY|ISO|IEC|RFC)\s*\d{2,}"
    r")(?![A-Za-z0-9])"
)
_MULTI_PART = re.compile(r"(?:以及|并且|同时|分别|对比|比较|与.+?的|and|versus|vs\.?|compare)", re.I)

_SEMANTIC_CUES = (
    "为什么",
    "原因",
    "如何",
    "怎样",
    "说明",
    "解释",
    "含义",
    "区别",
    "相似",
    "机制",
    "影响",
    "why",
    "how",
    "explain",
    "meaning",
    "difference",
    "similar",
    "mechanism",
    "impact",
    "what is the required response",
)
_LONG_CONTEXT_CUES = (
    "全文",
    "完整流程",
    "完整步骤",
    "所有步骤",
    "前后文",
    "上下文",
    "跨章节",
    "多个章节",
    "综合文档",
    "结合文档",
    "从前提到",
    "先决条件",
    "后续验证",
    "全篇",
    "entire document",
    "full procedure",
    "all steps",
    "across sections",
    "multiple sections",
    "prerequisite",
    "subsequent verification",
    "broader context",
)


@dataclass(frozen=True, slots=True)
class AdaptiveRoutingPolicy:
    """Administrator-owned thresholds and capability switches."""

    dense_available: bool
    parent_child_available: bool = True
    semantic_score_threshold: float = 1.25
    parent_score_threshold: float = 2.0

    def __post_init__(self) -> None:
        if self.semantic_score_threshold <= 0 or self.parent_score_threshold <= 0:
            raise ValueError("routing thresholds must be positive")


@dataclass(frozen=True, slots=True)
class QueryFeatures:
    character_count: int
    token_count: int
    exact_identifier_count: int
    quoted_phrase_count: int
    semantic_cue_count: int
    long_context_cue_count: int
    multi_part: bool


@dataclass(frozen=True, slots=True)
class AdaptiveRouteDecision:
    strategy: AdaptiveStrategy
    reason_code: str
    reason: str
    confidence: float
    features: QueryFeatures
    candidate_scores: Mapping[str, float]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe trace suitable for an admin/audit response."""
        return {
            "strategy": self.strategy,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "confidence": self.confidence,
            "features": asdict(self.features),
            "candidate_scores": dict(self.candidate_scores),
        }


def _count_cues(normalized: str, cues: tuple[str, ...]) -> int:
    return sum(1 for cue in cues if cue in normalized)


def extract_query_features(query: str) -> QueryFeatures:
    """Extract stable lexical features without an LLM or external service."""
    normalized = query.strip().casefold()
    if not normalized:
        raise ValueError("query must not be empty")
    return QueryFeatures(
        character_count=len(normalized),
        token_count=len(tokenize(normalized)),
        exact_identifier_count=len(_EXACT_IDENTIFIER.findall(query)),
        quoted_phrase_count=len(_QUOTED.findall(query)),
        semantic_cue_count=_count_cues(normalized, _SEMANTIC_CUES),
        long_context_cue_count=_count_cues(normalized, _LONG_CONTEXT_CUES),
        multi_part=bool(_MULTI_PART.search(normalized)),
    )


def route_retrieval(
    query: str,
    *,
    policy: AdaptiveRoutingPolicy,
) -> AdaptiveRouteDecision:
    """Choose an internal retrieval strategy from deterministic query features.

    Precedence is intentional: requests explicitly needing broad/cross-section
    context use child matching with parent expansion; semantic/paraphrased
    questions use sparse+dense RRF when the dense capability is enabled; short
    or identifier-heavy lookups stay on the low-latency BM25 path.
    """
    features = extract_query_features(query)

    exact_score = (
        2.0 * features.exact_identifier_count
        + 1.5 * features.quoted_phrase_count
        + (1.0 if features.token_count <= 8 else 0.0)
    )
    semantic_score = (
        1.25 * features.semantic_cue_count
        + (1.0 if features.multi_part else 0.0)
        + (0.75 if features.token_count >= 12 else 0.0)
        - min(1.0, 0.5 * features.exact_identifier_count)
    )
    parent_score = (
        2.0 * features.long_context_cue_count
        + (0.75 if features.multi_part else 0.0)
        + (0.5 if features.token_count >= 20 else 0.0)
    )
    scores = MappingProxyType(
        {
            "bm25": round(max(0.0, exact_score), 3),
            "rrf": round(max(0.0, semantic_score), 3),
            "parent_child": round(max(0.0, parent_score), 3),
        }
    )

    if policy.parent_child_available and parent_score >= policy.parent_score_threshold:
        strength = parent_score - policy.parent_score_threshold
        confidence = min(0.98, 0.78 + 0.04 * strength)
        return AdaptiveRouteDecision(
            strategy="parent_child",
            reason_code="broad_context_required",
            reason=(
                "The query asks for cross-section or full-procedure context; retrieve small child "
                "matches and return their bounded parent context."
            ),
            confidence=round(confidence, 3),
            features=features,
            candidate_scores=scores,
        )

    if policy.dense_available and semantic_score >= policy.semantic_score_threshold:
        strength = semantic_score - policy.semantic_score_threshold
        confidence = min(0.96, 0.72 + 0.04 * strength)
        return AdaptiveRouteDecision(
            strategy="rrf",
            reason_code="semantic_or_multi_concept_query",
            reason=(
                "The query is paraphrastic or relates multiple concepts; fuse BM25 and dense "
                "ranks with reciprocal-rank fusion."
            ),
            confidence=round(confidence, 3),
            features=features,
            candidate_scores=scores,
        )

    if not policy.dense_available and semantic_score >= policy.semantic_score_threshold:
        reason_code = "dense_unavailable_bm25_fallback"
        reason = (
            "Semantic fusion was indicated, but the administrator-disabled dense capability is "
            "unavailable; use the bounded BM25 fallback."
        )
        confidence = 0.6
    elif exact_score > 0:
        reason_code = "exact_or_identifier_lookup"
        reason = "The query is short, quoted, or identifier-heavy; use the low-latency BM25 path."
        confidence = min(0.97, 0.76 + 0.03 * exact_score)
    else:
        reason_code = "lexical_default"
        reason = "No strong semantic or broad-context signal was found; use the conservative BM25 default."
        confidence = 0.62

    return AdaptiveRouteDecision(
        strategy="bm25",
        reason_code=reason_code,
        reason=reason,
        confidence=round(confidence, 3),
        features=features,
        candidate_scores=scores,
    )
