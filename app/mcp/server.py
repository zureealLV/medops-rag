"""Standards-based MCP tools backed by MedOps tenant-safe services."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Annotated, Any

from anyio import to_thread
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from app.agents.model import ModelProvider
from app.agents.orchestration import orchestrate_answer_async
from app.config import Settings
from app.exceptions import AppError
from app.models.answers import AnswerRequest, AnswerResponse
from app.models.retrieval import SearchRequest
from app.repositories.documents import get as get_document
from app.security.audit import write_audit
from app.security.tenant import RequestContext, resolve_request_context
from app.services import knowledge_bases as knowledge_base_service
from app.services.answers import answer_async
from app.services.retrieval import search

IdentityResolver = Callable[[Context, str, str], RequestContext]


def _tool_error(error: AppError) -> ToolError:
    return ToolError(f"{error.code}: {error.message}")


def _header(headers: Any, name: str) -> str | None:
    if not headers:
        return None
    lowered = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lowered:
            return str(value)
    return None


def _default_identity_resolver(settings: Settings) -> IdentityResolver:
    def resolve(ctx: Context, method: str, path: str) -> RequestContext:
        headers = ctx.headers
        try:
            return resolve_request_context(
                settings,
                tenant_id=_header(headers, "X-Tenant-ID"),
                actor=_header(headers, "X-Actor-ID") or "mcp-client",
                authorization=_header(headers, "Authorization"),
                method=method,
                path=path,
            )
        except AppError as exc:
            raise _tool_error(exc) from exc

    return resolve


def _public_answer(result: AnswerResponse) -> dict[str, Any]:
    """Keep useful evidence while hiding internal prompt and raw visual payloads."""
    return {
        "answer": result.answer,
        "abstained": result.abstained,
        "reason": result.reason,
        "citations": [citation.model_dump() for citation in result.citations],
        "visual_citations": [citation.model_dump() for citation in result.visual_citations],
        "retrieval_profile": result.retrieval_profile,
        "retrieval_strategy": result.retrieval_strategy,
        "provider": result.provider,
        "orchestration": result.orchestration,
        "agent_steps": [step.model_dump() for step in result.agent_steps],
    }


def _citations_belong_to_tenant(
    database_path: Path, tenant_id: str, result: AnswerResponse
) -> bool:
    """Apply the same defense-in-depth citation scope check as the HTTP API."""
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


def _effective_search(data: SearchRequest, identity: RequestContext) -> SearchRequest:
    if identity.role == "admin":
        return data
    return data.model_copy(update={"top_k": 5, "strategy": "auto", "query_transform": "auto"})


def _effective_answer(data: AnswerRequest, identity: RequestContext) -> AnswerRequest:
    if identity.role == "admin":
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


def create_mcp_server(
    settings: Settings,
    model_provider: ModelProvider,
    *,
    identity_resolver: IdentityResolver | None = None,
    settings_resolver: Callable[[], Settings] | None = None,
) -> MCPServer:
    """Create the mounted MCP server for one MedOps application instance."""
    resolve_settings = settings_resolver or (lambda: settings)

    def resolve_identity(ctx: Context, method: str, path: str) -> RequestContext:
        if identity_resolver is not None:
            return identity_resolver(ctx, method, path)
        return _default_identity_resolver(resolve_settings())(ctx, method, path)

    server = MCPServer(
        name="MedOps RAG",
        description="Tenant-scoped medical and medical-device evidence retrieval.",
        instructions=(
            "List the caller's knowledge bases first when no knowledge_base_id is known. "
            "Use rag_search for evidence discovery and rag_answer for a grounded answer. "
            "Preserve returned citations and never present the system as medical advice."
        ),
        version="3.4.0",
    )

    @server.tool()
    def list_knowledge_bases(ctx: Context) -> dict[str, Any]:
        """List knowledge bases visible to the authenticated MedOps tenant."""
        settings = resolve_settings()
        identity = resolve_identity(ctx, "GET", "/knowledge-bases")
        items = knowledge_base_service.list_all(settings.database_path, identity.tenant_id)
        return {"knowledge_bases": [item.model_dump() for item in items]}

    @server.tool()
    def rag_search(
        query: Annotated[str, Field(min_length=2, max_length=1000)],
        ctx: Context,
        knowledge_base_id: Annotated[int | None, Field(ge=1)] = None,
        top_k: Annotated[int, Field(ge=1, le=10)] = 5,
    ) -> dict[str, Any]:
        """Search tenant-scoped medical evidence without generating an answer."""
        settings = resolve_settings()
        identity = resolve_identity(ctx, "POST", "/search")
        request = _effective_search(
            SearchRequest(
                query=query,
                knowledge_base_id=knowledge_base_id,
                top_k=top_k,
                strategy="auto",
                query_transform="auto",
            ),
            identity,
        )
        result = search(
            settings.database_path,
            identity.tenant_id,
            request,
            settings,
        )
        if result is None:
            write_audit(
                settings.database_path,
                request_id=str(ctx.request_id),
                actor=identity.actor,
                tenant_id=identity.tenant_id,
                action="mcp_search",
                resource=str(knowledge_base_id),
                result="denied",
                details={"reason": "knowledge_base_not_found"},
            )
            raise ToolError("knowledge_base_not_found: Knowledge base not found")
        write_audit(
            settings.database_path,
            request_id=str(ctx.request_id),
            actor=identity.actor,
            tenant_id=identity.tenant_id,
            action="mcp_search",
            resource="chunks",
            result="ok",
            details={
                "query": request.query,
                "result_count": len(result.results),
                "strategy": result.strategy,
                "routing_reason": result.routing.reason_code if result.routing else None,
            },
        )
        return result.model_dump()

    @server.tool()
    async def rag_answer(
        question: Annotated[str, Field(min_length=2, max_length=2000)],
        ctx: Context,
        knowledge_base_id: Annotated[int | None, Field(ge=1)] = None,
        top_k: Annotated[int, Field(ge=1, le=10)] = 5,
    ) -> dict[str, Any]:
        """Generate a policy-checked answer grounded in the caller's MedOps evidence."""
        settings = resolve_settings()
        identity = resolve_identity(ctx, "POST", "/answer")
        request = _effective_answer(
            AnswerRequest(
                question=question,
                knowledge_base_id=knowledge_base_id,
                top_k=top_k,
                retrieval_profile="auto",
                text_strategy="auto",
                query_transform="auto",
                visual_strategy="fusion",
                orchestration="langgraph",
            ),
            identity,
        )
        result = await orchestrate_answer_async(
            request.orchestration,
            request,
            lambda: answer_async(
                settings.database_path,
                settings,
                identity.tenant_id,
                request,
                model_provider,
            ),
            policy_profile=settings.policy_profile,
            citation_scope_checker=lambda candidate: _citations_belong_to_tenant(
                settings.database_path, identity.tenant_id, candidate
            ),
        )
        if result is None:
            await to_thread.run_sync(
                partial(
                    write_audit,
                    settings.database_path,
                    request_id=str(ctx.request_id),
                    actor=identity.actor,
                    tenant_id=identity.tenant_id,
                    action="mcp_answer",
                    resource=str(knowledge_base_id),
                    result="denied",
                    details={"reason": "knowledge_base_not_found"},
                )
            )
            raise ToolError("knowledge_base_not_found: Knowledge base not found")
        await to_thread.run_sync(
            partial(
                write_audit,
                settings.database_path,
                request_id=str(ctx.request_id),
                actor=identity.actor,
                tenant_id=identity.tenant_id,
                action="mcp_answer",
                resource="rag",
                result="abstained" if result.abstained else "ok",
                details={
                    "question": request.question,
                    "reason": result.reason,
                    "documents": [citation.document_id for citation in result.citations],
                    "chunks": [citation.chunk_id for citation in result.citations],
                    "artifacts": [
                        citation.artifact_id for citation in result.visual_citations
                    ],
                    "retrieval_profile": result.retrieval_profile,
                    "retrieval_strategy": result.retrieval_strategy,
                    "provider": result.provider,
                    "orchestration": result.orchestration,
                    "agent_steps": [step.node for step in result.agent_steps],
                },
            )
        )
        return _public_answer(result)

    return server
