"""Durable, identity-scoped chat conversation models."""

from pydantic import BaseModel, Field

from app.models.answers import AnswerResponse


class ConversationCreate(BaseModel):
    knowledge_base_id: int = Field(ge=1)
    title: str = Field(default="新对话", min_length=1, max_length=80)


class ConversationSummary(BaseModel):
    id: str
    knowledge_base_id: int
    title: str
    message_count: int
    created_at: str
    updated_at: str


class ConversationMessage(BaseModel):
    id: int
    role: str
    content: str
    contextualized_question: str | None = None
    answer: AnswerResponse | None = None
    created_at: str


class ConversationDetail(ConversationSummary):
    messages: list[ConversationMessage]


class ConversationTurnRequest(BaseModel):
    content: str = Field(min_length=2, max_length=2000)


class ConversationTurnResponse(BaseModel):
    conversation_id: str
    contextualized_question: str
    user_message: ConversationMessage
    assistant_message: ConversationMessage
    answer: AnswerResponse
