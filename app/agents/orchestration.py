"""Comparable classic, LangChain LCEL, and LangGraph RAG orchestration.

The retrieval, policy, grounding, and model implementation stays identical in all
three modes.  This keeps evaluation honest: measurements isolate orchestration
overhead instead of quietly changing the retriever or prompt between variants.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Literal, TypedDict

from anyio import to_thread
from langchain_core.runnables import RunnableBranch, RunnableLambda
from langgraph.graph import END, START, StateGraph

from app.agents.checkpoints import CheckpointSession
from app.agents.tools import (
    MAX_AGENT_GRAPH_STEPS,
    MAX_AGENT_TOOL_CALLS,
    READ_ONLY_AGENT_TOOLS,
    select_read_only_tools,
)
from app.models.answers import AgentStep, AnswerRequest, AnswerResponse
from app.retrieval.query_routing import route_query
from app.security.policies import is_medical_advice_request, is_supported_domain_query

Orchestration = Literal["classic", "langchain", "langgraph"]


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
    tool_plan: tuple[_ToolCall, ...]
    tool_calls: int
    citation_scope_checker: Callable[[AnswerResponse], bool] | None
    checkpoint: CheckpointSession | None
    steps: list[AgentStep]


def _record(
    state: _WorkflowState,
    node: str,
    started: float,
    *,
    status: Literal["completed", "abstained", "failed"] = "completed",
    detail: str | None = None,
) -> list[AgentStep]:
    if len(state.get("steps", [])) >= MAX_AGENT_GRAPH_STEPS:
        raise RuntimeError("agent graph exceeded MAX_AGENT_GRAPH_STEPS")
    return [
        *state.get("steps", []),
        AgentStep(
            node=node,
            status=status,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            detail=detail,
        ),
    ]


def _checkpoint(
    state: _WorkflowState,
    phase: str,
    *,
    status: Literal["running", "completed", "failed", "abstained"] = "running",
) -> _WorkflowState:
    """Persist only bounded control metadata, never prompts, evidence, or answers."""
    session = state.get("checkpoint")
    if session is not None:
        session.record(
            phase=phase,
            route=state.get("route"),
            tool_plan=tuple(call["name"] for call in state.get("tool_plan", ())),
            tool_calls=state.get("tool_calls", 0),
            status=status,
        )
    return state


def _prepare(state: _WorkflowState) -> _WorkflowState:
    started = time.perf_counter()
    request = state["request"]
    route = route_query(request.question, request.retrieval_profile)
    policy_reason = None
    if is_medical_advice_request(request.question):
        policy_reason = "medical_advice_denied"
    elif route == "text" and not is_supported_domain_query(request.question):
        policy_reason = "insufficient_evidence"
    next_state: _WorkflowState = {
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
    return _checkpoint(next_state, "route_question")


def _select_tool(state: _WorkflowState) -> _WorkflowState:
    """Create a bounded plan exclusively from validated, server-owned state."""
    started = time.perf_counter()
    request = state["request"]
    names = select_read_only_tools(
        state["route"],
        state.get("policy_reason"),
        verify_citations=state.get("citation_scope_checker") is not None,
    )
    plan = tuple(
        _ToolCall(
            name=name,
            arguments={
                "knowledge_base_id": request.knowledge_base_id,
                "top_k": request.top_k,
                "retrieval_profile": state["route"],
            },
        )
        for name in names
    )
    next_state: _WorkflowState = {
        **state,
        "tool_plan": plan,
        "tool_calls": 0,
        "steps": _record(
            state,
            "select_read_only_tool",
            started,
            detail=f"tools={','.join(names)}; max_calls={MAX_AGENT_TOOL_CALLS}",
        ),
    }
    return _checkpoint(next_state, "select_read_only_tools")


def _execute_tool(state: _WorkflowState) -> _WorkflowState:
    started = time.perf_counter()
    plan = state.get("tool_plan", ())
    if not plan or len(plan) > MAX_AGENT_TOOL_CALLS:
        failed: _WorkflowState = {
            **state,
            "result": None,
            "steps": _record(
                state,
                "execute_read_only_tools",
                started,
                status="failed",
                detail="invalid_or_empty_tool_plan",
            ),
        }
        return _checkpoint(failed, "execute_read_only_tools", status="failed")
    for call in plan:
        if call["name"] not in READ_ONLY_AGENT_TOOLS:
            failed = {
                **state,
                "result": None,
                "steps": _record(
                    state,
                    "execute_read_only_tools",
                    started,
                    status="failed",
                    detail=f"tool_not_allowed={call['name']}",
                ),
            }
            return _checkpoint(failed, "execute_read_only_tools", status="failed")

    primary_name = plan[0]["name"]
    result = state["runner"]()
    tool_calls = 1
    status = "abstained" if result is not None and result.abstained else "completed"
    detail = (
        f"tool={primary_name}; provider={result.provider}; profile={result.retrieval_profile}"
        if result is not None
        else f"tool={primary_name}; knowledge_base_not_found"
    )
    steps = _record(
        state,
        f"execute_{primary_name}",
        started,
        status=status,
        detail=detail,
    )

    if len(plan) == 2 and plan[1]["name"] == "verify_citation_scope" and result is not None:
        scope_started = time.perf_counter()
        tool_calls += 1
        checker = state.get("citation_scope_checker")
        try:
            scoped = checker(result) if checker is not None else False
        except Exception:
            scoped = False
        if not scoped:
            result = result.model_copy(
                update={
                    "answer": "引用证据未通过当前租户权限校验，本次拒绝作答。",
                    "citations": [],
                    "visual_citations": [],
                    "retrieved_chunks": [],
                    "retrieved_artifacts": [],
                    "abstained": True,
                    "reason": "citation_scope_violation",
                    "provider": "policy",
                }
            )
        verification_state: _WorkflowState = {**state, "steps": steps}
        steps = _record(
            verification_state,
            "verify_citation_scope",
            scope_started,
            status="completed" if scoped else "abstained",
            detail=f"tenant_scoped={str(scoped).lower()}",
        )

    next_state = {
        **state,
        "result": result,
        "tool_calls": tool_calls,
        "steps": steps,
    }
    return _checkpoint(next_state, "execute_read_only_tools")


def _apply_policy(state: _WorkflowState) -> _WorkflowState:
    """Return the existing policy response without pretending a search tool ran."""
    started = time.perf_counter()
    result = state["runner"]()
    next_state: _WorkflowState = {
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
    return _checkpoint(next_state, "apply_safety_policy", status="abstained")


def _verify_grounding(state: _WorkflowState) -> _WorkflowState:
    started = time.perf_counter()
    result = state.get("result")
    if result is None:
        next_state: _WorkflowState = {
            **state,
            "steps": _record(
                state,
                "verify_grounding",
                started,
                status="failed",
                detail="knowledge_base_not_found",
            ),
        }
        return _checkpoint(next_state, "verify_grounding", status="failed")
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
    next_state = {
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
    return _checkpoint(
        next_state,
        "finished",
        status="abstained" if result.abstained else "completed",
    )


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
_graph_builder.add_node("execute_read_only_tools", _execute_tool)
_graph_builder.add_node("apply_safety_policy", _apply_policy)
_graph_builder.add_node("verify_grounding", _verify_grounding)
_graph_builder.add_edge(START, "route_question")
_graph_builder.add_conditional_edges(
    "route_question",
    _route_after_policy,
    {"tool": "select_read_only_tool", "policy": "apply_safety_policy"},
)
_graph_builder.add_edge("select_read_only_tool", "execute_read_only_tools")
_graph_builder.add_edge("execute_read_only_tools", "verify_grounding")
_graph_builder.add_edge("apply_safety_policy", "verify_grounding")
_graph_builder.add_edge("verify_grounding", END)
_langgraph_pipeline = _graph_builder.compile()


def orchestrate_answer(
    mode: Orchestration,
    request: AnswerRequest,
    runner: Callable[[], AnswerResponse | None],
    *,
    citation_scope_checker: Callable[[AnswerResponse], bool] | None = None,
    checkpoint: CheckpointSession | None = None,
) -> AnswerResponse | None:
    """Run one grounded answer through a selected, measurable orchestrator."""
    started = time.perf_counter()
    if mode == "classic":
        if checkpoint is not None:
            checkpoint.record(
                phase="classic_rag", route=None, tool_plan=(), tool_calls=0, status="running"
            )
        result = runner()
        if result is None:
            if checkpoint is not None:
                checkpoint.record(
                    phase="finished", route=None, tool_plan=(), tool_calls=0, status="failed"
                )
            return None
        step = AgentStep(
            node="classic_rag",
            status="abstained" if result.abstained else "completed",
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            detail=f"provider={result.provider}; profile={result.retrieval_profile}",
        )
        if checkpoint is not None:
            checkpoint.record(
                phase="finished",
                route=result.retrieval_profile,
                tool_plan=(),
                tool_calls=0,
                status="abstained" if result.abstained else "completed",
            )
        return result.model_copy(update={"orchestration": mode, "agent_steps": [step]})

    initial: _WorkflowState = {
        "request": request,
        "runner": runner,
        "steps": [],
        "tool_calls": 0,
        "citation_scope_checker": citation_scope_checker,
        "checkpoint": checkpoint,
    }
    try:
        state = (
            _langchain_pipeline.invoke(initial)
            if mode == "langchain"
            else _langgraph_pipeline.invoke(initial)
        )
    except Exception:
        if checkpoint is not None:
            checkpoint.record(
                phase="failed", route=None, tool_plan=(), tool_calls=0, status="failed"
            )
        raise
    result = state.get("result")
    if result is None:
        return None
    return result.model_copy(update={"orchestration": mode, "agent_steps": state["steps"]})


class _AsyncWorkflowState(TypedDict, total=False):
    request: AnswerRequest
    runner: Callable[[], Awaitable[AnswerResponse | None]]
    result: AnswerResponse | None
    route: str
    needs_tool: bool
    policy_reason: str | None
    tool_plan: tuple[_ToolCall, ...]
    tool_calls: int
    citation_scope_checker: Callable[[AnswerResponse], bool] | None
    checkpoint: CheckpointSession | None
    steps: list[AgentStep]


async def _prepare_async(state: _AsyncWorkflowState) -> _AsyncWorkflowState:
    return await to_thread.run_sync(partial(_prepare, state))  # type: ignore[arg-type,return-value]


async def _select_tool_async(state: _AsyncWorkflowState) -> _AsyncWorkflowState:
    return await to_thread.run_sync(partial(_select_tool, state))  # type: ignore[arg-type,return-value]


async def _checkpoint_async(
    state: _AsyncWorkflowState,
    phase: str,
    *,
    status: Literal["running", "completed", "failed", "abstained"] = "running",
) -> _AsyncWorkflowState:
    return await to_thread.run_sync(  # type: ignore[return-value]
        partial(_checkpoint, state, phase, status=status)  # type: ignore[arg-type]
    )


async def _execute_tool_async(state: _AsyncWorkflowState) -> _AsyncWorkflowState:
    started = time.perf_counter()
    plan = state.get("tool_plan", ())
    if not plan or len(plan) > MAX_AGENT_TOOL_CALLS:
        failed: _AsyncWorkflowState = {
            **state,
            "result": None,
            "steps": _record(
                state,  # type: ignore[arg-type]
                "execute_read_only_tools",
                started,
                status="failed",
                detail="invalid_or_empty_tool_plan",
            ),
        }
        return await _checkpoint_async(failed, "execute_read_only_tools", status="failed")
    for call in plan:
        if call["name"] not in READ_ONLY_AGENT_TOOLS:
            failed = {
                **state,
                "result": None,
                "steps": _record(
                    state,  # type: ignore[arg-type]
                    "execute_read_only_tools",
                    started,
                    status="failed",
                    detail=f"tool_not_allowed={call['name']}",
                ),
            }
            return await _checkpoint_async(failed, "execute_read_only_tools", status="failed")

    primary_name = plan[0]["name"]
    result = await state["runner"]()
    tool_calls = 1
    status = "abstained" if result is not None and result.abstained else "completed"
    detail = (
        f"tool={primary_name}; provider={result.provider}; profile={result.retrieval_profile}"
        if result is not None
        else f"tool={primary_name}; knowledge_base_not_found"
    )
    steps = _record(
        state,  # type: ignore[arg-type]
        f"execute_{primary_name}",
        started,
        status=status,
        detail=detail,
    )
    if len(plan) == 2 and plan[1]["name"] == "verify_citation_scope" and result is not None:
        scope_started = time.perf_counter()
        tool_calls += 1
        checker = state.get("citation_scope_checker")
        try:
            scoped = (
                await to_thread.run_sync(partial(checker, result))
                if checker is not None
                else False
            )
        except Exception:
            scoped = False
        if not scoped:
            result = result.model_copy(
                update={
                    "answer": "引用证据未通过当前租户权限校验，本次拒绝作答。",
                    "citations": [],
                    "visual_citations": [],
                    "retrieved_chunks": [],
                    "retrieved_artifacts": [],
                    "abstained": True,
                    "reason": "citation_scope_violation",
                    "provider": "policy",
                }
            )
        steps = _record(
            {**state, "steps": steps},  # type: ignore[arg-type]
            "verify_citation_scope",
            scope_started,
            status="completed" if scoped else "abstained",
            detail=f"tenant_scoped={str(scoped).lower()}",
        )
    next_state: _AsyncWorkflowState = {
        **state,
        "result": result,
        "tool_calls": tool_calls,
        "steps": steps,
    }
    return await _checkpoint_async(next_state, "execute_read_only_tools")


async def _apply_policy_async(state: _AsyncWorkflowState) -> _AsyncWorkflowState:
    started = time.perf_counter()
    result = await state["runner"]()
    next_state: _AsyncWorkflowState = {
        **state,
        "result": result,
        "steps": _record(
            state,  # type: ignore[arg-type]
            "apply_safety_policy",
            started,
            status="abstained",
            detail=f"reason={state.get('policy_reason') or 'policy'}",
        ),
    }
    return await _checkpoint_async(next_state, "apply_safety_policy", status="abstained")


async def _verify_grounding_async(state: _AsyncWorkflowState) -> _AsyncWorkflowState:
    return await to_thread.run_sync(  # type: ignore[return-value]
        partial(_verify_grounding, state)  # type: ignore[arg-type]
    )


_async_langchain_tool_path = RunnableLambda(_select_tool_async) | RunnableLambda(
    _execute_tool_async
)
_async_langchain_pipeline = RunnableLambda(_prepare_async) | RunnableBranch(
    (lambda state: state["needs_tool"], _async_langchain_tool_path),
    RunnableLambda(_apply_policy_async),
)
_async_langchain_pipeline = _async_langchain_pipeline | RunnableLambda(
    _verify_grounding_async
)

_async_graph_builder = StateGraph(_AsyncWorkflowState)
_async_graph_builder.add_node("route_question", _prepare_async)
_async_graph_builder.add_node("select_read_only_tool", _select_tool_async)
_async_graph_builder.add_node("execute_read_only_tools", _execute_tool_async)
_async_graph_builder.add_node("apply_safety_policy", _apply_policy_async)
_async_graph_builder.add_node("verify_grounding", _verify_grounding_async)
_async_graph_builder.add_edge(START, "route_question")
_async_graph_builder.add_conditional_edges(
    "route_question",
    _route_after_policy,
    {"tool": "select_read_only_tool", "policy": "apply_safety_policy"},
)
_async_graph_builder.add_edge("select_read_only_tool", "execute_read_only_tools")
_async_graph_builder.add_edge("execute_read_only_tools", "verify_grounding")
_async_graph_builder.add_edge("apply_safety_policy", "verify_grounding")
_async_graph_builder.add_edge("verify_grounding", END)
_async_langgraph_pipeline = _async_graph_builder.compile()


async def orchestrate_answer_async(
    mode: Orchestration,
    request: AnswerRequest,
    runner: Callable[[], Awaitable[AnswerResponse | None]],
    *,
    citation_scope_checker: Callable[[AnswerResponse], bool] | None = None,
    checkpoint: CheckpointSession | None = None,
) -> AnswerResponse | None:
    """Async orchestration whose blocking nodes are explicitly worker-offloaded."""
    started = time.perf_counter()
    if mode == "classic":
        if checkpoint is not None:
            await to_thread.run_sync(
                partial(
                    checkpoint.record,
                    phase="classic_rag",
                    route=None,
                    tool_plan=(),
                    tool_calls=0,
                    status="running",
                )
            )
        result = await runner()
        if result is None:
            if checkpoint is not None:
                await to_thread.run_sync(
                    partial(
                        checkpoint.record,
                        phase="finished",
                        route=None,
                        tool_plan=(),
                        tool_calls=0,
                        status="failed",
                    )
                )
            return None
        step = AgentStep(
            node="classic_rag",
            status="abstained" if result.abstained else "completed",
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            detail=f"provider={result.provider}; profile={result.retrieval_profile}",
        )
        if checkpoint is not None:
            await to_thread.run_sync(
                partial(
                    checkpoint.record,
                    phase="finished",
                    route=result.retrieval_profile,
                    tool_plan=(),
                    tool_calls=0,
                    status="abstained" if result.abstained else "completed",
                )
            )
        return result.model_copy(update={"orchestration": mode, "agent_steps": [step]})

    initial: _AsyncWorkflowState = {
        "request": request,
        "runner": runner,
        "steps": [],
        "tool_calls": 0,
        "citation_scope_checker": citation_scope_checker,
        "checkpoint": checkpoint,
    }
    try:
        state = (
            await _async_langchain_pipeline.ainvoke(initial)
            if mode == "langchain"
            else await _async_langgraph_pipeline.ainvoke(initial)
        )
    except Exception:
        if checkpoint is not None:
            await to_thread.run_sync(
                partial(
                    checkpoint.record,
                    phase="failed",
                    route=None,
                    tool_plan=(),
                    tool_calls=0,
                    status="failed",
                )
            )
        raise
    result = state.get("result")
    if result is None:
        return None
    return result.model_copy(update={"orchestration": mode, "agent_steps": state["steps"]})
