"""The LangGraph agent.

Shape: agent -> (tools -> agent)* -> end. The model alone decides whether to
call a tool and which one; there is no branch anywhere that inspects the user's
text and calls a tool on its behalf. That is the brief's hardest requirement.

The only ceiling is a hard iteration cap, which exists to bound cost rather than
to steer the model.
"""

import logging
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from app import llm, policy
from app import profile as user_profile
from app.config import get_settings
from app.prompts import system_prompt
from app.tools import ALL_TOOLS

log = logging.getLogger(__name__)


class ChatState(MessagesState):
    """Conversation messages plus the tier this turn was routed to."""

    # Set by the caller. Phase 5's classifier will decide it; until then the
    # route defaults to the fast tier.
    tier: str


async def _agent(state: ChatState) -> dict:
    """Call the model with tools bound and let it decide what to do next."""
    model = llm.get_model(state.get("tier") or "fast").bind_tools(ALL_TOOLS)
    return {"messages": [await model.ainvoke(state["messages"])]}


async def _finalize(state: ChatState) -> dict:
    """Force a text answer when the iteration cap cut the tool loop short."""
    # Without this the run can end on a message that only contains tool calls,
    # leaving the user with silence. Re-asking without tools bound guarantees
    # prose, using whatever the model gathered before it ran out of turns.
    model = llm.get_model(state.get("tier") or "fast")
    nudge = SystemMessage(
        "You have gathered enough. Answer now in plain text without calling any more tools."
    )
    return {"messages": [await model.ainvoke([*state["messages"], nudge])]}


def _route(state: ChatState) -> Literal["tools", "finalize", "__end__"]:
    """Continue the tool loop, force an answer, or stop."""
    last = state["messages"][-1]
    if not getattr(last, "tool_calls", None):
        return END

    used = sum(1 for m in state["messages"] if isinstance(m, ToolMessage))
    if used >= get_settings().max_tool_iterations:
        log.warning("tool iteration cap reached, forcing a final answer")
        return "finalize"
    return "tools"


def build_graph():
    """Compile the agent graph. Cheap enough to call once at import."""
    builder = StateGraph(ChatState)
    builder.add_node("agent", _agent)
    builder.add_node("tools", ToolNode(ALL_TOOLS))
    builder.add_node("finalize", _finalize)

    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", _route)
    builder.add_edge("tools", "agent")
    builder.add_edge("finalize", END)
    return builder.compile()


GRAPH = build_graph()


async def prepare(message: str, user_id: str) -> tuple[ChatState, str]:
    """Classify the turn and build its starting state. Returns the state and topic.

    Blocked topics never reach the graph at all — the caller returns the canned
    decline directly. That ordering is what makes the legal limits hold under a
    prompt injection: there is no model in the path to be talked around.
    """
    verdict = await policy.classify(message)
    if verdict.topic != "OK":
        return {}, verdict.topic

    stored = await user_profile.get_profile(user_id)
    tier = "smart" if verdict.difficulty == "HARD" else "fast"
    state: ChatState = {
        "messages": [
            SystemMessage(system_prompt(user_profile.profile_to_prompt(stored))),
            HumanMessage(message),
        ],
        "tier": tier,
    }
    return state, "OK"


def initial_state(message: str, tier: str = "fast", profile_text: str = "") -> ChatState:
    """Build the starting state for one user turn, without classifying."""
    return {
        "messages": [SystemMessage(system_prompt(profile_text)), HumanMessage(message)],
        "tier": tier,
    }


def collect_sources(messages: list) -> list[dict]:
    """Pull search results off the tool messages, newest last, deduplicated by URL."""
    seen: dict[str, dict] = {}
    for message in messages:
        if isinstance(message, ToolMessage):
            for source in getattr(message, "artifact", None) or []:
                url = source.get("url")
                if url:
                    seen[url] = source
    return list(seen.values())
