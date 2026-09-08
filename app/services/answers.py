"""Grounded text/visual answer workflow, citations, and refusal rules."""

from __future__ import annotations

import re
from pathlib import Path

from app.agents.model import generate
from app.config import Settings
from app.models.answers import AnswerRequest, AnswerResponse, Citation, VisualCitation
from app.models.artifacts import VisualEvidence, VisualSearchRequest
from app.models.retrieval import Evidence, SearchRequest
from app.retrieval.query_routing import ResolvedProfile, route_query
from app.security.policies import is_medical_advice_request
from app.security.prompt_injection import has_injection_signals
from app.services import artifacts as artifact_service
from app.services.retrieval import search as text_search


def _strip_inline_citation_markers(answer_text: str) -> str:
    """Keep the answer natural; structured citation cards are rendered separately."""
    result = re.sub(
        r"\s*\[(?:\d+:\d+|source:\d+|visual:\d+|image:\d+|来源\d+|图像\d+)\]",
        "",
        answer_text,
        flags=re.I,
    )
    result = re.sub(r"[ \t]+([，。！？；：,.!?;:])", r"\1", result)
    result = re.sub(r"[ \t]{2,}", " ", result)
    return result.strip()


def _visual_confident(evidence: list[VisualEvidence], settings: Settings) -> bool:
    if not evidence or evidence[0].image_similarity is None:
        return False
    top = float(evidence[0].image_similarity)
    other_scores = [
        float(item.image_similarity) for item in evidence[1:] if item.image_similarity is not None
    ]
    runner_up = max(other_scores, default=-1.0)
    return (
        top >= settings.visual_similarity_threshold and top - runner_up >= settings.visual_similarity_margin
    )


def _text_confident(evidence: list[Evidence], strategy: str, settings: Settings) -> bool:
    """Apply an absolute component floor when the final rank score is normalized.

    BM25 and RRF scores are normalized within each request, so the best irrelevant
    row can otherwise receive a misleading score of 1.0. The component floors were
    calibrated on the frozen 120-positive/20-negative V2 set and remain configurable.
    """
    if not evidence or evidence[0].score < settings.retrieval_threshold:
        return False
    top = evidence[0]
    lexical = top.keyword_score >= settings.retrieval_keyword_threshold
    dense = top.vector_score >= settings.retrieval_dense_threshold
    if strategy in {"keyword", "bm25", "parent_child"}:
        return lexical
    if strategy == "vector":
        return dense
    return lexical or dense


def _visual_payloads(
    path: Path,
    tenant_id: str,
    evidence: list[VisualEvidence],
    limit: int,
    max_bytes: int,
) -> list[tuple[VisualEvidence, bytes]]:
    payloads: list[tuple[VisualEvidence, bytes]] = []
    total_bytes = 0
    for item in evidence[: max(0, min(limit, 5))]:
        stored = artifact_service.content(path, tenant_id, item.id)
        if stored is None:
            continue
        content = stored[0]
        if len(content) > max_bytes or total_bytes + len(content) > max_bytes:
            continue
        payloads.append((item, content))
        total_bytes += len(content)
    return payloads


def _response(
    *,
    answer_text: str,
    text_evidence: list[Evidence],
    all_text_evidence: list[Evidence],
    visual_evidence: list[VisualEvidence],
    all_visual_evidence: list[VisualEvidence],
    resolved_profile: ResolvedProfile,
    abstained: bool,
    reason: str | None,
    provider: str,
    retrieval_ms: float,
    model_ms: float = 0.0,
    token_usage: int = 0,
) -> AnswerResponse:
    return AnswerResponse(
        answer=answer_text,
        citations=[
            Citation(
                source=item.source,
                document_id=item.document_id,
                chunk_id=item.chunk_id,
                parent_id=item.parent_id,
            )
            for item in text_evidence[:3]
        ],
        visual_citations=[
            VisualCitation(
                artifact_id=item.id,
                source=item.source,
                document_id=item.document_id,
                page_number=item.page_number,
                bbox=item.bbox,
                content_url=item.content_url,
                sha256=item.sha256,
            )
            for item in visual_evidence[:3]
        ],
        retrieved_chunks=all_text_evidence,
        retrieved_artifacts=all_visual_evidence,
        retrieval_profile=resolved_profile,
        abstained=abstained,
        reason=reason,
        provider=provider,
        retrieval_ms=round(retrieval_ms, 3),
        model_ms=round(model_ms, 3),
        token_usage=token_usage,
    )


def answer(path: Path, settings: Settings, tenant_id: str, request: AnswerRequest) -> AnswerResponse | None:
    resolved_profile = route_query(request.question, request.retrieval_profile)
    if is_medical_advice_request(request.question):
        return _response(
            answer_text="该系统只提供医疗知识与医疗器械资料检索，不提供个体诊断、处方或治疗建议。",
            text_evidence=[],
            all_text_evidence=[],
            visual_evidence=[],
            all_visual_evidence=[],
            resolved_profile=resolved_profile,
            abstained=True,
            reason="medical_advice_denied",
            provider="policy",
            retrieval_ms=0,
        )

    text_result = text_search(
        path,
        tenant_id,
        SearchRequest(
            query=request.question,
            knowledge_base_id=request.knowledge_base_id,
            top_k=request.top_k,
            strategy=request.text_strategy,
        ),
        settings,
    )
    if text_result is None:
        return None
    safe_text = [item for item in text_result.results if not has_injection_signals(item.text)]
    text_confident = _text_confident(safe_text, text_result.strategy, settings)

    visual_result = None
    needs_visual = resolved_profile == "visual" or (
        request.retrieval_profile == "auto" and not text_confident and settings.image_embedding_enabled
    )
    if needs_visual:
        visual_result = artifact_service.search(
            path,
            settings,
            tenant_id,
            VisualSearchRequest(
                query=request.question,
                knowledge_base_id=request.knowledge_base_id,
                top_k=request.top_k,
                strategy=request.visual_strategy,
            ),
        )
        if visual_result is None:
            return None

    all_visual = visual_result.results if visual_result is not None else []
    safe_visual = [item for item in all_visual if not has_injection_signals(item.ocr_text)]
    visual_confident = _visual_confident(safe_visual, settings)
    if (
        request.retrieval_profile == "auto"
        and resolved_profile == "text"
        and not text_confident
        and visual_confident
    ):
        resolved_profile = "visual"

    if resolved_profile == "visual":
        accepted = visual_confident
        accepted_text = safe_text if text_confident else []
        accepted_visual = safe_visual if visual_confident else []
        insufficient_reason = "insufficient_visual_evidence"
    else:
        accepted = text_confident
        accepted_text = safe_text if text_confident else []
        accepted_visual = []
        insufficient_reason = "insufficient_evidence"

    if not accepted:
        unsafe = bool(text_result.results and not safe_text) or bool(all_visual and not safe_visual)
        return _response(
            answer_text="现有知识库中没有足够可靠的证据，我不能据此回答。",
            text_evidence=[],
            all_text_evidence=text_result.results,
            visual_evidence=[],
            all_visual_evidence=all_visual,
            resolved_profile=resolved_profile,
            abstained=True,
            reason="unsafe_evidence" if unsafe else insufficient_reason,
            provider="policy",
            retrieval_ms=text_result.retrieval_ms + (visual_result.retrieval_ms if visual_result else 0.0),
        )

    payloads = _visual_payloads(
        path,
        tenant_id,
        accepted_visual,
        settings.model_max_visual_images,
        settings.model_max_visual_bytes,
    )
    if accepted_visual and not payloads:
        return _response(
            answer_text="视觉证据已命中，但原图无法在安全大小限制内加载，因此本次拒绝作答。",
            text_evidence=[],
            all_text_evidence=text_result.results,
            visual_evidence=[],
            all_visual_evidence=all_visual,
            resolved_profile=resolved_profile,
            abstained=True,
            reason="visual_payload_unavailable",
            provider="policy",
            retrieval_ms=text_result.retrieval_ms + (visual_result.retrieval_ms if visual_result else 0.0),
        )
    payload_evidence = [item for item, _ in payloads]
    answer_text_evidence = accepted_text[:3]
    response_text, provider, model_ms, token_usage = generate(
        request.question,
        answer_text_evidence,
        settings,
        payloads,
    )
    response_text = _strip_inline_citation_markers(response_text)
    return _response(
        answer_text=response_text,
        text_evidence=answer_text_evidence,
        all_text_evidence=text_result.results,
        visual_evidence=payload_evidence,
        all_visual_evidence=all_visual,
        resolved_profile=resolved_profile,
        abstained=False,
        reason=None,
        provider=provider,
        retrieval_ms=text_result.retrieval_ms + (visual_result.retrieval_ms if visual_result else 0.0),
        model_ms=model_ms,
        token_usage=token_usage,
    )
