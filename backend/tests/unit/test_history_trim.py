"""What the model is actually sent once history persists.

Two things go wrong quietly when a conversation is kept: the prompt grows
without bound, and code that counts things over the whole message list starts
counting other turns. Both are asserted here on what reached the model, not on
what the graph returned.
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app import graph, tools
from app.config import get_settings
from tests.fakes import ai


@pytest.fixture
def fake_search(monkeypatch):
    """Swap Tavily for a canned result, so the tool runs without network."""

    class FakeTavily:
        def __init__(self, **kwargs):
            pass

        async def ainvoke(self, payload):
            return {"results": [{"title": "T", "url": "https://example.com/x", "content": "c"}]}

    monkeypatch.setattr(tools, "TavilySearch", FakeTavily)
    monkeypatch.setattr(
        tools, "get_settings", lambda: type("S", (), {"tavily_api_key": "test-key"})()
    )


def long_history(turns: int) -> list:
    """Build a well-formed alternating conversation of the given number of turns."""
    messages: list = []
    for n in range(turns):
        messages.append(HumanMessage(f"question {n}"))
        messages.append(AIMessage(f"answer {n}"))
    return messages


async def test_a_long_conversation_is_trimmed_to_the_limit(patch_model, scripted_model):
    """Prompt growth is bounded, or a long chat eventually costs a fortune per turn."""
    model = patch_model(scripted_model(ai("Fine.")))
    limit = get_settings().history_turns

    await graph.GRAPH.ainvoke(
        {
            "messages": [*long_history(40), HumanMessage("the latest question")],
            "tier": "fast",
            "system": "SYSTEM PROMPT",
        }
    )

    sent = model.calls[0]
    # At most, rather than exactly: the window is nudged forward when it would
    # otherwise open on an assistant message, so it can come in one short.
    assert len(sent) <= 1 + limit * 2, "history is not being trimmed to history_turns"
    assert len(sent) >= limit, "trimming is throwing away more than it should"
    assert sent[0].content == "SYSTEM PROMPT", "the persona was trimmed away"
    assert sent[-1].content == "the latest question", "the newest turn was dropped"
    # Trimmed from the front, so the oldest turns are the ones that go and the
    # most recent complete exchange survives.
    contents = [m.content for m in sent]
    assert "question 0" not in contents
    assert "question 39" in contents and "answer 39" in contents


async def test_a_short_conversation_is_left_alone(patch_model, scripted_model):
    """Under the limit, nothing is dropped. Trimming must not be eager."""
    model = patch_model(scripted_model(ai("Fine.")))

    await graph.GRAPH.ainvoke(
        {
            "messages": [*long_history(2), HumanMessage("latest")],
            "tier": "fast",
            "system": "SYSTEM PROMPT",
        }
    )

    assert len(model.calls[0]) == 1 + 5


async def test_the_trim_never_opens_on_an_orphan_tool_result(patch_model, scripted_model):
    """A window starting on a tool result would send a result with no matching call."""
    model = patch_model(scripted_model(ai("Fine.")))
    # Deep enough that the cut lands inside a tool exchange rather than between turns.
    history = long_history(12)
    history[8:8] = [
        AIMessage("", tool_calls=[{"name": "search_web", "args": {"query": "x"}, "id": "c1"}]),
        ToolMessage(content="result", tool_call_id="c1"),
    ]

    await graph.GRAPH.ainvoke(
        {"messages": [*history, HumanMessage("latest")], "tier": "fast", "system": "S"}
    )

    body = model.calls[0][1:]
    assert isinstance(body[0], HumanMessage), "history opened mid tool exchange"
    for index, message in enumerate(body):
        if isinstance(message, ToolMessage):
            assert getattr(body[index - 1], "tool_calls", None), "orphaned tool result"


async def test_the_tool_cap_counts_this_turn_only(
    patch_model, scripted_model, fake_search
):
    """Five searches yesterday must not leave the agent unable to search today."""
    spent = [
        AIMessage("", tool_calls=[{"name": "search_web", "args": {"query": "x"}, "id": f"c{n}"}])
        for n in range(5)
    ]
    prior: list = [HumanMessage("an earlier question")]
    for index, call in enumerate(spent):
        prior.append(call)
        prior.append(ToolMessage(content="result", tool_call_id=f"c{index}"))

    patch_model(
        scripted_model(
            ai("", [{"name": "search_web", "args": {"query": "nduja"}}]),
            ai("Nduja is a spreadable Calabrian salami."),
        )
    )

    result = await graph.GRAPH.ainvoke(
        {"messages": [*prior, HumanMessage("what is nduja")], "tier": "fast", "system": "S"}
    )

    fresh = graph._this_turn(result["messages"])
    assert [m for m in fresh if isinstance(m, ToolMessage)], "the cap leaked across turns"
    assert result["messages"][-1].content == "Nduja is a spreadable Calabrian salami."


def test_this_turn_falls_back_to_everything_when_no_user_message_is_present():
    """Tool-only lists still work, which is what the source collector is handed in tests."""
    messages = [SystemMessage("s"), AIMessage("a")]

    assert graph._this_turn(messages) == messages
