"""Deterministic, read-only tool registry for the answer agent.

The registry is intentionally code-owned.  A question may influence which
allowlisted tool is selected, but clients cannot submit a tool name or tool
arguments through the answer API.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

AgentToolName = Literal[
    "grounded_text_answer",
    "grounded_visual_answer",
    "verify_citation_scope",
]

MAX_AGENT_TOOL_CALLS = 2
MAX_AGENT_GRAPH_STEPS = 6


@dataclass(frozen=True, slots=True)
class ReadOnlyAgentTool:
    name: AgentToolName
    purpose: str
    requires_result: bool = False


READ_ONLY_AGENT_TOOLS = MappingProxyType(
    {
        "grounded_text_answer": ReadOnlyAgentTool(
            name="grounded_text_answer",
            purpose="Retrieve tenant-scoped text evidence and produce one grounded answer.",
        ),
        "grounded_visual_answer": ReadOnlyAgentTool(
            name="grounded_visual_answer",
            purpose="Retrieve tenant-scoped visual evidence and produce one grounded answer.",
        ),
        "verify_citation_scope": ReadOnlyAgentTool(
            name="verify_citation_scope",
            purpose="Fail closed unless every returned citation still belongs to the caller tenant.",
            requires_result=True,
        ),
    }
)


def select_read_only_tools(
    route: Literal["text", "visual"],
    policy_reason: str | None,
    *,
    verify_citations: bool = True,
) -> tuple[AgentToolName, ...]:
    """Build a bounded plan from server-derived routing and policy state."""
    if policy_reason is not None:
        return ()
    primary: AgentToolName = (
        "grounded_visual_answer" if route == "visual" else "grounded_text_answer"
    )
    plan = (primary, "verify_citation_scope") if verify_citations else (primary,)
    if len(plan) > MAX_AGENT_TOOL_CALLS:  # defensive invariant for future registry edits
        raise RuntimeError("agent tool plan exceeds MAX_AGENT_TOOL_CALLS")
    return plan
