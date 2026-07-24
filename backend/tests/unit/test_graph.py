"""The agent loop.

These cover the brief's hardest requirement: the model decides when to call a
tool, and nothing in the code path decides for it. A test that only checked
"a search happened" would pass just as well against a hardcoded sequence, so
these assert on who made the choice.
"""

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app import graph, tools
from tests.fakes import ai


@pytest.fixture
def fake_search(monkeypatch):
    """Swap Tavily for a canned result, so the tool runs without network."""

    class FakeTavily:
        def __init__(self, **kwargs):
            pass

        async def ainvoke(self, payload):
            return {
                "results": [
                    {
                        "title": "What is nduja",
                        "url": "https://example.com/nduja",
                        "content": "A spreadable Calabrian salami.",
                    }
                ]
            }

    monkeypatch.setattr(tools, "TavilySearch", FakeTavily)
    monkeypatch.setattr(
        tools, "get_settings", lambda: type("S", (), {"tavily_api_key": "test-key"})()
    )


async def test_tools_are_bound_so_the_model_can_choose(patch_model, scripted_model):
    """The model is offered the tools; it is never called without them."""
    model = patch_model(scripted_model(ai("Sear it hot and rest it.")))

    await graph.GRAPH.ainvoke(graph.initial_state("how do I cook a steak"))

    assert model.bound_tools == [
        "search_web",
        "get_user_profile",
        "remember_about_user",
        "present_recipe",
    ]


async def test_no_tool_runs_when_the_model_does_not_ask(patch_model, scripted_model):
    """A confident answer costs no search. Nothing forces a tool call."""
    patch_model(scripted_model(ai("Chicken is done at 74C.")))

    result = await graph.GRAPH.ainvoke(graph.initial_state("when is chicken done"))

    assert not any(isinstance(m, ToolMessage) for m in result["messages"])


async def test_tool_runs_and_the_model_answers_from_it(
    patch_model, scripted_model, fake_search
):
    """When the model asks for a tool, it runs and control returns to the model."""
    patch_model(
        scripted_model(
            ai("", [{"name": "search_web", "args": {"query": "nduja"}}]),
            ai("Nduja is a spreadable Calabrian salami."),
        )
    )

    result = await graph.GRAPH.ainvoke(graph.initial_state("what is nduja"))

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert "Calabrian" in tool_messages[0].content
    assert result["messages"][-1].content == "Nduja is a spreadable Calabrian salami."


async def test_runaway_tool_loop_is_capped_and_still_answers(
    patch_model, scripted_model, fake_search
):
    """A model that keeps asking for tools gets cut off but the user still gets prose."""
    call = [{"name": "search_web", "args": {"query": "x"}}]
    # Six tool requests against a cap of five, plus the forced final answer.
    patch_model(scripted_model(*[ai("", call) for _ in range(6)], ai("Here is my answer.")))

    result = await graph.GRAPH.ainvoke(graph.initial_state("loop forever"))

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 5
    # The user is never left with a message that is only tool calls.
    assert result["messages"][-1].content == "Here is my answer."


async def test_the_forced_answer_carries_no_unanswered_tool_call(
    patch_model, scripted_model, fake_search
):
    """The capped path must not hand the provider a tool call nothing answered.

    _route sends the run to finalize precisely because the tools node was
    skipped, so the last message is a request that will never get a result.
    _finalize also binds no tools, so passing it on declares a function that was
    never offered and answers one that was never run.

    Asserted on the message list rather than on a provider error: the scripted
    model accepts any input, so a behavioural test here would stay green against
    a request the real API rejects. This assertion is model-independent.
    """
    call = [{"name": "search_web", "args": {"query": "x"}}]
    model = patch_model(
        scripted_model(*[ai("", call) for _ in range(6)], ai("Here is my answer."))
    )

    result = await graph.GRAPH.ainvoke(graph.initial_state("loop forever"))

    sent = model.calls[-1]
    answered = {m.tool_call_id for m in sent if isinstance(m, ToolMessage)}
    dangling = [
        c["id"]
        for m in sent
        for c in getattr(m, "tool_calls", None) or []
        if c["id"] not in answered
    ]
    assert dangling == [], f"unanswered tool calls sent to a model with no tools: {dangling}"
    # The results gathered before the cap are still there to answer from; only
    # the unanswered request at the tail is dropped.
    assert any(isinstance(m, ToolMessage) for m in sent)
    assert result["messages"][-1].content == "Here is my answer."


async def test_search_failure_does_not_break_the_conversation(
    patch_model, scripted_model, monkeypatch
):
    """A search outage degrades to an unaided answer instead of a 500."""

    class BrokenTavily:
        def __init__(self, **kwargs):
            pass

        async def ainvoke(self, payload):
            raise RuntimeError("tavily is down")

    monkeypatch.setattr(tools, "TavilySearch", BrokenTavily)
    monkeypatch.setattr(
        tools, "get_settings", lambda: type("S", (), {"tavily_api_key": "test-key"})()
    )
    patch_model(
        scripted_model(
            ai("", [{"name": "search_web", "args": {"query": "x"}}]),
            ai("Going from memory here."),
        )
    )

    result = await graph.GRAPH.ainvoke(graph.initial_state("what is nduja"))

    assert result["messages"][-1].content == "Going from memory here."


async def test_missing_search_key_is_reported_not_raised(monkeypatch):
    """No key configured is a config problem, not a crash mid-conversation."""
    monkeypatch.setattr(
        tools, "get_settings", lambda: type("S", (), {"tavily_api_key": ""})()
    )

    # Invoked as a tool call rather than with bare args, so the artifact comes
    # back alongside the content instead of being discarded.
    message = await tools.search_web.ainvoke(
        {"name": "search_web", "args": {"query": "anything"}, "id": "1", "type": "tool_call"}
    )

    assert "unavailable" in message.content.lower()
    assert message.artifact == []


async def test_concurrent_cold_starts_open_exactly_one_checkpointer(monkeypatch, tmp_path):
    """The first requests after startup race, because the cache is still cold.

    Each unguarded caller opened its own long-lived aiosqlite connection and then
    overwrote the module globals, so all but the last were left unreferenced,
    never closed, and invisible to reset_graph. lifespan calls reset_graph
    specifically to keep a non-daemon connection from holding the process open
    past `compose stop`, so a leak here defeats the thing it exists to do.
    """
    import asyncio

    from app import config, db

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "race.db"))
    config.get_settings.cache_clear()
    await db.init_db()
    await graph.reset_graph()

    built = []
    real_checkpointer = db.checkpointer

    async def counting_checkpointer():
        """Build a real saver and record it, so the count is of open connections."""
        saver = await real_checkpointer()
        built.append(saver)
        return saver

    monkeypatch.setattr(db, "checkpointer", counting_checkpointer)

    graphs = await asyncio.gather(*(graph.get_graph() for _ in range(5)))

    assert len(built) == 1, (
        f"{len(built)} checkpointer connections opened, {len(built) - 1} leaked"
    )
    # And every caller got that one graph, rather than four of them holding
    # compiled graphs over connections nothing will ever close.
    assert all(compiled is graphs[0] for compiled in graphs)

    await graph.reset_graph()
    config.get_settings.cache_clear()


def test_sources_are_deduplicated_by_url():
    """The same page cited twice appears once in the UI."""
    messages = [
        ToolMessage(content="a", tool_call_id="1", artifact=[{"title": "A", "url": "u1"}]),
        ToolMessage(content="b", tool_call_id="2", artifact=[{"title": "A again", "url": "u1"}]),
        ToolMessage(content="c", tool_call_id="3", artifact=[{"title": "B", "url": "u2"}]),
    ]

    assert [s["url"] for s in graph.collect_sources(messages)] == ["u1", "u2"]


def test_sources_ignore_messages_that_carry_none():
    """Tool messages without artifacts are skipped rather than crashing."""
    messages = [
        AIMessage(content="hello"),
        ToolMessage(content="no artifact", tool_call_id="1"),
    ]

    assert graph.collect_sources(messages) == []
