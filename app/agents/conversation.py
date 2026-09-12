"""LangGraph conversation wrapper around the existing grounded RAG agent."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.models.answers import AnswerResponse


class ConversationState(TypedDict, total=False):
    current: str
    previous_user_turns: list[str]
    contextualized: str
    answer: AnswerResponse


FOLLOWUP_MARKERS = (
    "它",
    "这个",
    "那个",
    "那",
    "还有",
    "呢",
    "刚才",
    "前面",
    "为啥",
    "怎么",
    "咋",
    "有啥",
    "再",
)

COLLOQUIAL_REWRITES = (
    ("血脂高", "高脂血症"),
    ("小孩", "儿童"),
    ("长得慢", "生长迟缓"),
    ("啥时候", "什么情况下"),
    ("啥", "什么"),
    ("一天", "每日"),
    ("油和盐", "烹调油和食盐"),
    ("吃多少", "控制在多少"),
    ("撸多少", "摄入多少"),
    ("瞧", "检查"),
    ("老是", "经常"),
    ("重新分一个", "分配新的标识"),
    ("得分配", "需要分配"),
)


def normalize_colloquial(value: str) -> str:
    normalized = value.strip()
    for informal, formal in COLLOQUIAL_REWRITES:
        normalized = normalized.replace(informal, formal)
    return normalized


def contextualize(current: str, previous_user_turns: list[str]) -> str:
    """Resolve short/elliptical follow-ups without inventing facts."""
    clean = normalize_colloquial(current)
    if not previous_user_turns:
        return clean
    is_followup = len(clean) <= 18 or any(marker in clean for marker in FOLLOWUP_MARKERS)
    if not is_followup:
        return clean
    # The first user turn is the durable topic anchor.  Repeating every previous
    # turn made retrieval drift toward filler such as "那个呢" as chats grew.
    context = normalize_colloquial(previous_user_turns[0]).replace("\n", " ")
    return f"{context}；{clean}"


async def run_conversation_graph(
    current: str,
    previous_user_turns: list[str],
    answer_runner: Callable[[str], Awaitable[AnswerResponse]],
) -> tuple[str, AnswerResponse]:
    async def understand(state: ConversationState) -> ConversationState:
        return {"contextualized": contextualize(state["current"], state.get("previous_user_turns", []))}

    async def answer(state: ConversationState) -> ConversationState:
        return {"answer": await answer_runner(state["contextualized"])}

    graph = StateGraph(ConversationState)
    graph.add_node("contextualize_followup", understand)
    graph.add_node("grounded_rag_agent", answer)
    graph.add_edge(START, "contextualize_followup")
    graph.add_edge("contextualize_followup", "grounded_rag_agent")
    graph.add_edge("grounded_rag_agent", END)
    result = await graph.compile().ainvoke({"current": current, "previous_user_turns": previous_user_turns})
    return result["contextualized"], result["answer"]
