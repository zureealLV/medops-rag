"""Durable continuous-conversation HTTP endpoints."""

from functools import partial
from typing import Annotated

from anyio import to_thread
from fastapi import APIRouter, Path, Response

from app.agents.conversation import run_conversation_graph
from app.api.answers import grounded_answer
from app.api.deps import ModelProviderDep, RequestIdDep, SettingsDep, TenantContext
from app.exceptions import AppError
from app.models.answers import AnswerRequest
from app.models.conversations import (
    ConversationCreate,
    ConversationDetail,
    ConversationSummary,
    ConversationTurnRequest,
    ConversationTurnResponse,
)
from app.repositories import conversations as repository

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
def list_conversations(context: TenantContext, settings: SettingsDep) -> list[ConversationSummary]:
    return repository.list_for_identity(settings.database_path, context.tenant_id, context.actor)


@router.post("", status_code=201)
def create_conversation(
    data: ConversationCreate, context: TenantContext, settings: SettingsDep
) -> ConversationSummary:
    result = repository.create(
        settings.database_path, context.tenant_id, context.actor, data.knowledge_base_id, data.title
    )
    if result is None:
        raise AppError(404, "knowledge_base_not_found", "Knowledge base not found")
    return result


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: Annotated[str, Path(min_length=8, max_length=64)],
    context: TenantContext,
    settings: SettingsDep,
) -> ConversationDetail:
    result = repository.get(settings.database_path, context.tenant_id, context.actor, conversation_id)
    if result is None:
        raise AppError(404, "conversation_not_found", "Conversation not found")
    return result


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: Annotated[str, Path(min_length=8, max_length=64)],
    context: TenantContext,
    settings: SettingsDep,
) -> Response:
    if not repository.delete(settings.database_path, context.tenant_id, context.actor, conversation_id):
        raise AppError(404, "conversation_not_found", "Conversation not found")
    return Response(status_code=204)


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: Annotated[str, Path(min_length=8, max_length=64)],
    data: ConversationTurnRequest,
    context: TenantContext,
    settings: SettingsDep,
    model_provider: ModelProviderDep,
    request_id: RequestIdDep,
) -> ConversationTurnResponse:
    detail = await to_thread.run_sync(
        partial(repository.get, settings.database_path, context.tenant_id, context.actor, conversation_id)
    )
    if detail is None:
        raise AppError(404, "conversation_not_found", "Conversation not found")
    previous = [message.content for message in detail.messages if message.role == "user"][-6:]
    user_message = await to_thread.run_sync(
        partial(
            repository.append,
            settings.database_path,
            context.tenant_id,
            context.actor,
            conversation_id,
            "user",
            data.content,
        )
    )
    assert user_message is not None

    async def answer_runner(question: str):
        return await grounded_answer(
            AnswerRequest(question=question, knowledge_base_id=detail.knowledge_base_id),
            Response(),
            context,
            settings,
            model_provider,
            request_id,
            conversation_id,
        )

    contextualized, answer = await run_conversation_graph(data.content, previous, answer_runner)
    assistant_message = await to_thread.run_sync(
        partial(
            repository.append,
            settings.database_path,
            context.tenant_id,
            context.actor,
            conversation_id,
            "assistant",
            answer.answer,
            contextualized_question=contextualized,
            answer=answer,
        )
    )
    assert assistant_message is not None
    return ConversationTurnResponse(
        conversation_id=conversation_id,
        contextualized_question=contextualized,
        user_message=user_message,
        assistant_message=assistant_message,
        answer=answer,
    )
