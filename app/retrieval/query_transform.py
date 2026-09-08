"""Deterministic query transformations and policy-gated template HyDE."""

from __future__ import annotations

import re

from app.config import Settings
from app.models.retrieval import QueryTransform
from app.retrieval.embeddings import tokenize

ENGLISH_FILLER = re.compile(
    r"\b(?:what is|how should|which controlled action|please|operators?|the required response|"
    r"for this issue|resolves? this issue)\b",
    re.IGNORECASE,
)
CHINESE_FILLER = re.compile(r"(?:请用运行手册说明|应该如何处置|第一项受控操作是什么|为什么不能|遇到)")


def rewrite_query(query: str) -> str:
    rewritten = ENGLISH_FILLER.sub(" ", query)
    rewritten = CHINESE_FILLER.sub(" ", rewritten)
    rewritten = re.sub(r"[?？:：,，;；]", " ", rewritten)
    rewritten = re.sub(r"\s+", " ", rewritten).strip()
    return rewritten or query


def hypothetical_document(query: str) -> str:
    focus = rewrite_query(query)
    if re.search(r"[\u4e00-\u9fff]", focus):
        return (
            f"医院信息系统运维运行手册。故障现象：{focus}。"
            "处置步骤包括核对告警与日志、确认根因、执行受控变更、验证恢复结果并保留回滚路径。"
        )[:1800]
    return (
        "Healthcare or medical-device knowledge document. "
        f"Incident symptom and required response: {focus}. "
        "Verify alerts and logs, confirm the root cause, perform the controlled remediation, validate "
        "recovery, and retain a rollback path."
    )[:1800]


def should_auto_hyde(query: str) -> bool:
    lowered = query.lower()
    cues = ("why", "how", "explain", "为什么", "如何", "说明")
    return len(tokenize(query)) >= 8 and any(value in lowered for value in cues)


def transform_queries(
    query: str, requested: QueryTransform, settings: Settings | None
) -> tuple[QueryTransform, list[str]]:
    resolved: QueryTransform = requested
    if requested == "auto":
        resolved = "hyde" if settings and settings.hyde_auto_enabled and should_auto_hyde(query) else "none"
    if resolved == "none":
        return resolved, [query]
    rewritten = rewrite_query(query)
    if resolved == "rewrite":
        return resolved, [rewritten]
    if resolved == "multi_query":
        return resolved, list(dict.fromkeys((query, rewritten)))
    if resolved == "hyde":
        return resolved, [hypothetical_document(query)]
    raise ValueError(f"Unknown query transform: {resolved}")
