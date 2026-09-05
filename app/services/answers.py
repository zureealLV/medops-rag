"""Grounded-answer workflow, citation checks, and refusal rules."""

from __future__ import annotations

from pathlib import Path

from app.agents.model import generate
from app.config import Settings
from app.models.answers import AnswerRequest, AnswerResponse, Citation
from app.models.retrieval import SearchRequest
from app.security.policies import is_medical_advice_request
from app.security.prompt_injection import has_injection_signals
from app.services.retrieval import search


def answer(path: Path, settings: Settings, tenant_id: str, request: AnswerRequest) -> AnswerResponse | None:
    if is_medical_advice_request(request.question):
        return AnswerResponse(
            answer="该系统只回答医院信息化运维问题，不提供诊断、处方或治疗建议。",
            citations=[],
            retrieved_chunks=[],
            abstained=True,
            reason="medical_advice_denied",
            provider="policy",
            retrieval_ms=0,
            model_ms=0,
            token_usage=0,
        )
    result = search(
        path,
        tenant_id,
        SearchRequest(
            query=request.question, knowledge_base_id=request.knowledge_base_id, top_k=request.top_k
        ),
    )
    if result is None:
        return None
    safe_evidence = [item for item in result.results if not has_injection_signals(item.text)]
    if not safe_evidence or safe_evidence[0].score < settings.retrieval_threshold:
        reason = "unsafe_evidence" if result.results and not safe_evidence else "insufficient_evidence"
        return AnswerResponse(
            answer="现有知识库中没有足够可靠的证据，我不能据此回答。",
            citations=[],
            retrieved_chunks=result.results,
            abstained=True,
            reason=reason,
            provider="policy",
            retrieval_ms=result.retrieval_ms,
            model_ms=0,
            token_usage=0,
        )
    response_text, provider, model_ms, token_usage = generate(request.question, safe_evidence, settings)
    citations = [
        Citation(source=item.source, document_id=item.document_id, chunk_id=item.chunk_id)
        for item in safe_evidence[:3]
    ]
    return AnswerResponse(
        answer=response_text,
        citations=citations,
        retrieved_chunks=result.results,
        abstained=False,
        provider=provider,
        retrieval_ms=result.retrieval_ms,
        model_ms=round(model_ms, 3),
        token_usage=token_usage,
    )
