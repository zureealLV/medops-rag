"""Comparable classic, LangChain LCEL, and LangGraph RAG orchestration.

The retrieval, policy, grounding, and model implementation stays identical in all
three modes.  This keeps evaluation honest: measurements isolate orchestration
overhead instead of quietly changing the retriever or prompt between variants.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Literal, TypedDict

from langchain_core.runnables import RunnableBranch, RunnableLambda
from langgraph.graph import END, START, StateGraph

from app.models.answers import AgentStep, AnswerRequest, AnswerResponse
from app.retrieval.query_routing import route_query
from app.security.policies import is_medical_advice_request, is_supported_domain_query

Orchestration = Literal["classic", "langchain", "langgraph"]
READ_ONLY_AGENT_TOOLS = frozenset({"grounded_medical_answer"})


class _ToolCall(TypedDict):
    name: str
    arguments: dict[str, object]


class _WorkflowState(TypedDict, total=False):
    request: AnswerRequest
    runner: Callable[[], AnswerResponse | None]
    result: AnswerResponse | None
    route: str
    needs_tool: bool
    policy_reason: str | None
    tool_call: _ToolCall
    steps: list[AgentStep]


def _record(
    state: _WorkflowState,
    node: str,
    started: float,
    *,
    status: Literal["completed", "abstained", "failed"] = "completed",
    detail: str | None = None,
) -> list[AgentStep]:
    return [
        *state.get("steps", []),
        AgentStep(
            node=node,
            status=status,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            detail=detail,
        ),
    ]


def _prepare(state: _WorkflowState) -> _WorkflowState:
    started = time.perf_counter()
    request = state["request"]
    route = route_query(request.question, request.retrieval_profile)
    policy_reason = None
    if is_medical_advice_request(request.question):
        policy_reason = "medical_advice_denied"
    elif route == "text" and not is_supported_domain_query(request.question):
        policy_reason = "insufficient_evidence"
    return {
        **state,
        "route": route,
        "needs_tool": policy_reason is None,
        "policy_reason": policy_reason,
        "steps": _record(
            state,
            "route_question",
            started,
            detail=(
                f"profile={route}; strategy={request.text_strategy}; "
                f"policy={policy_reason or 'passed'}"
            ),
        ),
    }


def _select_tool(state: _WorkflowState) -> _WorkflowState:
    """Create one bounded, tenant-neutral tool call from validated request state."""
    started = time.perf_counter()
    request = state["request"]
    tool_call: _ToolCall = {
        "name": "grounded_medical_answer",
        "arguments": {
            "question": request.question,
            "knowledge_base_id": request.knowledge_base_id,
            "top_k": request.top_k,
            "retrieval_profile": state["route"],
            "text_strategy": request.text_strategy,
            "visual_strategy": request.visual_strategy,
        },
    }
    return {
        **state,
        "tool_call": tool_call,
        "steps": _record(
            state,
            "select_read_only_tool",
            started,
            detail="tool=grounded_medical_answer; max_calls=1",
        ),
    }


def _execute_tool(state: _WorkflowState) -> _WorkflowState:
    started = time.perf_counter()
    tool_call = state["tool_call"]
    tool_name = tool_call["name"]
    if tool_name not in READ_ONLY_AGENT_TOOLS:
        return {
            **state,
            "result": None,
            "steps": _record(
                state,
                "execute_read_only_tool",
                started,
                status="failed",
                detail=f"tool_not_allowed={tool_name}",
            ),
        }
    result = state["runner"]()
    status = "abstained" if result is not None and result.abstained else "completed"
    detail = None if result is None else f"provider={result.provider}; profile={result.retrieval_profile}"
    return {
        **state,
        "result": result,
        "steps": _record(
            state,
            "execute_grounded_medical_answer",
            started,
            status=status,
            detail=detail,
        ),
    }


def _apply_policy(state: _WorkflowState) -> _WorkflowState:
    """Return the existing policy response without pretending a search tool ran."""
    started = time.perf_counter()
    result = state["runner"]()
    return {
        **state,
        "result": result,
        "steps": _record(
            state,
            "apply_safety_policy",
            started,
            status="abstained",
            detail=f"reason={state.get('policy_reason') or 'policy'}",
        ),
    }


def _verify_grounding(state: _WorkflowState) -> _WorkflowState:
    started = time.perf_counter()
    result = state.get("result")
    if result is None:
        return {
            **state,
            "steps": _record(
                state,
                "verify_grounding",
                started,
                status="failed",
                detail="knowledge_base_not_found",
            ),
        }
    grounded = result.abstained or bool(result.citations or result.visual_citations)
    if not grounded:
        result = result.model_copy(
            update={
                "answer": "现有知识库中没有可核验的引用证据，本次拒绝作答。",
                "abstained": True,
                "reason": "missing_citation",
                "provider": "policy",
            }
        )
    return {
        **state,
        "result": result,
        "steps": _record(
            state,
            "verify_grounding",
            started,
            status="abstained" if result.abstained else "completed",
            detail=f"grounded={str(grounded).lower()}",
        ),
    }


_langchain_tool_path = RunnableLambda(_select_tool) | RunnableLambda(_execute_tool)
_langchain_pipeline = RunnableLambda(_prepare) | RunnableBranch(
    (lambda state: state["needs_tool"], _langchain_tool_path),
    RunnableLambda(_apply_policy),
)
_langchain_pipeline = _langchain_pipeline | RunnableLambda(_verify_grounding)


def _route_after_policy(state: _WorkflowState) -> Literal["tool", "policy"]:
    return "tool" if state["needs_tool"] else "policy"


_graph_builder = StateGraph(_WorkflowState)
_graph_builder.add_node("route_question", _prepare)
_graph_builder.add_node("select_read_only_tool", _select_tool)
_graph_builder.add_node("execute_grounded_medical_answer", _execute_tool)
_graph_builder.add_node("apply_safety_policy", _apply_policy)
_graph_builder.add_node("verify_grounding", _verify_grounding)
_graph_builder.add_edge(START, "route_question")
_graph_builder.add_conditional_edges(
    "route_question",
    _route_after_policy,
    {"tool": "select_read_only_tool", "policy": "apply_safety_policy"},
)
_graph_builder.add_edge("select_read_only_tool", "execute_grounded_medical_answer")
_graph_builder.add_edge("execute_grounded_medical_answer", "verify_grounding")
_graph_builder.add_edge("apply_safety_policy", "verify_grounding")
_graph_builder.add_edge("verify_grounding", END)
_langgraph_pipeline = _graph_builder.compile()


def orchestrate_answer(
    mode: Orchestration,
    request: AnswerRequest,
    runner: Callable[[], AnswerResponse | None],
) -> AnswerResponse | None:
    """Run one grounded answer through a selected, measurable orchestrator."""
    started = time.perf_counter()
    if mode == "classic":
        result = runner()
        if result is None:
            return None
        step = AgentStep(
            node="classic_rag",
            status="abstained" if result.abstained else "completed",
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            detail=f"provider={result.provider}; profile={result.retrieval_profile}",
        )
        return result.model_copy(update={"orchestration": mode, "agent_steps": [step]})

    initial: _WorkflowState = {"request": request, "runner": runner, "steps": []}
    state = (
        _langchain_pipeline.invoke(initial)
        if mode == "langchain"
        else _langgraph_pipeline.invoke(initial)
    )
    result = state.get("result")
    if result is None:
        return None
    return result.model_copy(update={"orchestration": mode, "agent_steps": state["steps"]})
