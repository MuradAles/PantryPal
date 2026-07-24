"""The LangGraph agent.

Shape: agent -> (tools -> agent)* -> end. The model alone decides whether to
call a tool and which one; there is no branch anywhere that inspects the user's
text and calls a tool on its behalf. That is the brief's hardest requirement.

The only ceiling is a hard iteration cap, which exists to bound cost rather than
to steer the model.

Conversation history is persisted by a LangGraph checkpointer keyed on the user,
so a follow-up like "what about with rice instead?" has something to refer back
to. Two consequences run through this file:

- The message list now spans every earlier turn, so anything that reasons about
  "this turn" has to say so explicitly. See _this_turn.
- The system prompt is never stored in that list. It is rebuilt each turn from
  the current profile and prepended on the way to the model, which keeps it from
  accumulating and means a fact learned this turn is in force on the next one.
"""

import logging
from typing import Literal

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    trim_messages,
)
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from app import db, llm, policy
from app import profile as user_profile
from app.config import get_settings
from app.prompts import MEMORY_UNAVAILABLE, system_prompt
from app.tools import ALL_TOOLS

log = logging.getLogger(__name__)


class ChatState(MessagesState):
    """Conversation messages, the tier for this turn, and its system prompt."""

    # Decided by the classifier in prepare(), defaulting to the fast tier.
    tier: str

    # Rebuilt every turn rather than kept in `messages`. Storing it as a message
    # would append another copy to the persisted history on every single turn.
    system: str


def _this_turn(messages: list) -> list:
    """Return the messages from the user's most recent message onward.

    With history persisted, "how many tools has this run used" and "what did this
    answer cite" are both questions about the tail of the list, not about all of
    it. Counting the whole list would let five searches spread over a morning
    permanently trip the iteration cap.
    """
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return messages[index:]
    return messages


def _for_model(state: ChatState) -> list:
    """Build what the model actually sees: this turn's system prompt, then history."""
    # Trimmed from the end, so the recent turns survive and the oldest go first.
    # start_on="human" is load-bearing: a window that opened on a ToolMessage
    # would send the provider a tool result with no matching call.
    history = trim_messages(
        state["messages"],
        strategy="last",
        token_counter=len,
        max_tokens=get_settings().history_turns * 2,
        start_on="human",
        include_system=False,
        allow_partial=False,
    )
    return [SystemMessage(state.get("system") or system_prompt("")), *history]


async def _agent(state: ChatState) -> dict:
    """Call the model with tools bound and let it decide what to do next."""
    model = llm.get_model(state.get("tier") or "fast").bind_tools(ALL_TOOLS)
    return {"messages": [await model.ainvoke(_for_model(state))]}


async def _finalize(state: ChatState) -> dict:
    """Force a text answer when the iteration cap cut the tool loop short."""
    # Without this the run can end on a message that only contains tool calls,
    # leaving the user with silence. Re-asking without tools bound guarantees
    # prose, using whatever the model gathered before it ran out of turns.
    model = llm.get_model(state.get("tier") or "fast")
    nudge = SystemMessage(
        "You have gathered enough. Answer now in plain text without calling any more tools."
    )
    return {"messages": [await model.ainvoke([*_for_model(state), nudge])]}


def _route(state: ChatState) -> Literal["tools", "finalize", "__end__"]:
    """Continue the tool loop, force an answer, or stop."""
    last = state["messages"][-1]
    if not getattr(last, "tool_calls", None):
        return END

    used = sum(1 for m in _this_turn(state["messages"]) if isinstance(m, ToolMessage))
    if used >= get_settings().max_tool_iterations:
        log.warning("tool iteration cap reached, forcing a final answer")
        return "finalize"
    return "tools"


def build_graph(checkpointer=None):
    """Compile the agent graph, optionally persisting conversations to storage."""
    builder = StateGraph(ChatState)
    builder.add_node("agent", _agent)
    builder.add_node("tools", ToolNode(ALL_TOOLS))
    builder.add_node("finalize", _finalize)

    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", _route)
    builder.add_edge("tools", "agent")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


# Stateless: each run starts from whatever it is handed. Used directly by tests
# and as the fallback when storage is unreachable.
GRAPH = build_graph()

_checkpointed = None
_saver = None


async def get_graph():
    """Return the graph the app runs, compiled once against the checkpointer."""
    global _checkpointed, _saver
    if _checkpointed is not None:
        return _checkpointed
    try:
        _saver = await db.checkpointer()
    except Exception:
        # Same rule the profile store follows: memory is a feature, not a
        # dependency. Not cached, so a transient outage costs the conversation
        # its history for one turn rather than until the next deploy.
        log.exception("checkpointer unavailable; this turn has no conversation history")
        return GRAPH
    _checkpointed = build_graph(_saver)
    return _checkpointed


async def reset_graph() -> None:
    """Drop the cached graph and close its connection. For tests between databases."""
    global _checkpointed, _saver
    if _saver is not None:
        try:
            await _saver.conn.close()
        except Exception:
            log.warning("checkpointer connection did not close cleanly")
    _checkpointed = None
    _saver = None


async def prepare(message: str, user_id: str) -> tuple[ChatState, str]:
    """Classify the turn and build its starting state. Returns the state and topic.

    Blocked topics never reach the graph at all — the caller returns the canned
    decline directly. That ordering is what makes the legal limits hold under a
    prompt injection: there is no model in the path to be talked around.
    """
    verdict = await policy.classify(message)
    if verdict.topic != "OK":
        return {}, verdict.topic

    stored, memory_ok = await user_profile.load(user_id)
    # A dead database and a first-time user both read as empty. Passing that
    # distinction through means the reply says memory is down instead of
    # confidently behaving as though the user had never said anything.
    profile_text = MEMORY_UNAVAILABLE if not memory_ok else user_profile.profile_to_prompt(stored)
    tier = "smart" if verdict.difficulty == "HARD" else "fast"
    # Only the new message. Earlier turns arrive from the checkpointer, and
    # re-sending them here would double every one of them.
    state: ChatState = {
        "messages": [HumanMessage(message)],
        "tier": tier,
        "system": system_prompt(profile_text),
    }
    return state, "OK"


def initial_state(message: str, tier: str = "fast", profile_text: str = "") -> ChatState:
    """Build the starting state for one user turn, without classifying."""
    return {
        "messages": [HumanMessage(message)],
        "tier": tier,
        "system": system_prompt(profile_text),
    }


def collect_sources(messages: list) -> list[dict]:
    """Pull search results off this turn's tool messages, deduplicated by URL."""
    # Scoped to the current turn: the persisted list holds every earlier one, and
    # a page cited three turns ago is not a source for the answer on screen now.
    seen: dict[str, dict] = {}
    for message in _this_turn(messages):
        if isinstance(message, ToolMessage):
            for source in getattr(message, "artifact", None) or []:
                url = source.get("url")
                if url:
                    seen[url] = source
    return list(seen.values())
