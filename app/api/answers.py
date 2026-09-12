"""Grounded question-answering HTTP endpoint."""

from functools import partial
from pathlib import Path
from typing import Annotated

from anyio import to_thread
from fastapi import APIRouter, Header, Response

from app.agents.checkpoints import CheckpointSession, new_or_validated_thread_id
from app.agents.model import (
    ModelProviderCircuitOpenError,
    ModelProviderDeadlineExceededError,
    ModelProviderOverloadedError,
)
from app.agents.orchestration import orchestrate_answer_async
from app.api.deps import ModelProviderDep, RequestIdDep, SettingsDep, TenantContext
from app.exceptions import AppError
from app.models.answers import AnswerRequest, AnswerResponse
from app.repositories.documents import get as get_document
from app.security.audit import write_audit
from app.services.answers import answer_async

router = APIRouter(prefix="/answer", tags=["answers"])


def _citations_belong_to_tenant(
    database_path: Path, tenant_id: str, result: AnswerResponse
) -> bool:
    """Re-resolve every document-bearing result through the caller tenant."""
    document_ids = {
        *(citation.document_id for citation in result.citations),
        *(citation.document_id for citation in result.visual_citations),
        *(evidence.document_id for evidence in result.retrieved_chunks),
        *(artifact.document_id for artifact in result.retrieved_artifacts),
    }
    return all(
        get_document(database_path, tenant_id, document_id) is not None
        for document_id in document_ids
    )


def _effective_request(data: AnswerRequest, context: TenantContext) -> AnswerRequest:
    """Keep retrieval and orchestration controls behind the admin boundary.

    Viewer/editor callers describe the business question only.  The service owns
    technical routing defaults so clients cannot silently weaken the production
    retrieval path by sending the same fields that are useful to administrators
    and benchmark tooling.
    """
    if context.role == "admin":
        return data
    return data.model_copy(
        update={
            "top_k": 5,
            "retrieval_profile": "auto",
            "text_strategy": "auto",
            "query_transform": "auto",
            "visual_strategy": "fusion",
            "orchestration": "langgraph",
        }
    )


@router.post("")
async def grounded_answer(
    data: AnswerRequest,
    response: Response,
    context: TenantContext,
    settings: SettingsDep,
    model_provider: ModelProviderDep,
    request_id: RequestIdDep,
    thread_id_header: Annotated[str | None, Header(alias="X-MedOps-Thread-Id")] = None,
) -> AnswerResponse:
    effective = _effective_request(data, context)
    try:
        thread_id = new_or_validated_thread_id(thread_id_header)
    except ValueError as exc:
        raise AppError(422, "invalid_thread_id", str(exc)) from exc
    checkpoint = await to_thread.run_sync(
        partial(
            CheckpointSession,
            settings.database_path,
            tenant_id=context.tenant_id,
            actor=context.actor,
            thread_id=thread_id,
            run_id=request_id,
        )
    )
    try:
        result = await orchestrate_answer_async(
            effective.orchestration,
            effective,
            lambda: answer_async(
                settings.database_path,
                settings,
                context.tenant_id,
                effective,
                model_provider,
            ),
            policy_profile=settings.policy_profile,
            citation_scope_checker=lambda result: _citations_belong_to_tenant(
                settings.database_path, context.tenant_id, result
            ),
            checkpoint=checkpoint,
        )
    except ModelProviderOverloadedError as exc:
        await to_thread.run_sync(
            partial(
                write_audit,
                settings.database_path,
                request_id=request_id,
                actor=context.actor,
                tenant_id=context.tenant_id,
                action="answer",
                resource="rag",
                result="rejected",
                details={
                    "question": effective.question,
                    "reason": "model_provider_overloaded",
                    "overload_reason": exc.reason,
                    "max_concurrency": exc.max_concurrency,
                    "max_queue_waiters": exc.max_queue_waiters,
                    "waited_ms": exc.waited_ms,
                },
            )
        )
        raise AppError(
            503,
            "model_provider_overloaded",
            "Model provider is at capacity; retry later",
            details={
                "reason": exc.reason,
                "max_concurrency": exc.max_concurrency,
                "max_queue_waiters": exc.max_queue_waiters,
                "waited_ms": exc.waited_ms,
            },
            headers={
                "Retry-After": str(exc.retry_after_seconds),
                "X-MedOps-Provider-Overloaded": "true",
                "X-MedOps-Overload-Reason": exc.reason,
            },
        ) from exc
    except ModelProviderDeadlineExceededError as exc:
        await to_thread.run_sync(
            partial(
                write_audit,
                settings.database_path,
                request_id=request_id,
                actor=context.actor,
                tenant_id=context.tenant_id,
                action="answer",
                resource="rag",
                result="rejected",
                details={
                    "question": effective.question,
                    "reason": "model_provider_deadline_exceeded",
                    "deadline_phase": exc.phase,
                    "deadline_seconds": exc.deadline_seconds,
                    "elapsed_ms": exc.elapsed_ms,
                },
            )
        )
        raise AppError(
            504,
            "model_provider_deadline_exceeded",
            "Model provider request deadline exceeded",
            details={
                "phase": exc.phase,
                "deadline_seconds": exc.deadline_seconds,
                "elapsed_ms": exc.elapsed_ms,
            },
            headers={
                "X-MedOps-Provider-Deadline": "exceeded",
                "X-MedOps-Deadline-Phase": exc.phase,
            },
        ) from exc
    except ModelProviderCircuitOpenError as exc:
        await to_thread.run_sync(
            partial(
                write_audit,
                settings.database_path,
                request_id=request_id,
                actor=context.actor,
                tenant_id=context.tenant_id,
                action="answer",
                resource="rag",
                result="rejected",
                details={
                    "question": effective.question,
                    "reason": "model_provider_circuit_open",
                    "circuit_state": exc.state,
                },
            )
        )
        raise AppError(
            503,
            "model_provider_circuit_open",
            "Model provider circuit is open; retry later",
            details={"state": exc.state},
            headers={
                "Retry-After": str(exc.retry_after_seconds),
                "X-MedOps-Circuit-State": exc.state,
            },
        ) from exc
    if result is None:
        raise AppError(404, "knowledge_base_not_found", "Knowledge base not found")
    response.headers["X-MedOps-Abstained"] = str(result.abstained).lower()
    response.headers["X-MedOps-Retrieval-Ms"] = str(result.retrieval_ms)
    response.headers["X-MedOps-Model-Ms"] = str(result.model_ms)
    response.headers["X-MedOps-Token-Usage"] = str(result.token_usage)
    response.headers["X-MedOps-Prompt-Tokens"] = str(result.prompt_tokens)
    response.headers["X-MedOps-Completion-Tokens"] = str(result.completion_tokens)
    response.headers["X-MedOps-Cached-Prompt-Tokens"] = str(result.cached_prompt_tokens)
    response.headers["X-MedOps-Retrieval-Profile"] = result.retrieval_profile
    if result.retrieval_strategy:
        response.headers["X-MedOps-Retrieval-Strategy"] = result.retrieval_strategy
    response.headers["X-MedOps-Provider"] = result.provider
    response.headers["X-MedOps-Orchestration"] = result.orchestration
    response.headers["X-MedOps-Thread-Id"] = thread_id
    response.headers["X-MedOps-Run-Id"] = request_id
    if checkpoint.resumed_from_run_id:
        response.headers["X-MedOps-Resumed-From-Run-Id"] = checkpoint.resumed_from_run_id
    await to_thread.run_sync(
        partial(
            write_audit,
            settings.database_path,
            request_id=request_id,
            actor=context.actor,
            tenant_id=context.tenant_id,
            action="answer",
            resource="rag",
            result="abstained" if result.abstained else "ok",
            details={
                "question": effective.question,
                "reason": result.reason,
                "documents": [citation.document_id for citation in result.citations],
                "chunks": [citation.chunk_id for citation in result.citations],
                "artifacts": [citation.artifact_id for citation in result.visual_citations],
                "retrieval_profile": result.retrieval_profile,
                "retrieval_strategy": result.retrieval_strategy,
                "routing_reason": (
                    result.retrieval_routing.reason_code if result.retrieval_routing else None
                ),
                "text_strategy": effective.text_strategy,
                "query_transform": effective.query_transform,
                "visual_strategy": effective.visual_strategy,
                "provider": result.provider,
                "orchestration": result.orchestration,
                "agent_steps": [step.node for step in result.agent_steps],
            },
        )
    )
    return result
