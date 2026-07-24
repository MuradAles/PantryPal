"""Tests for the scripted model fixture itself.

The fixture is the thing standing between this suite and a real API bill, so it
gets the same scrutiny as application code.
"""

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from tests.fakes import ai


@tool
def sample_tool(query: str) -> str:
    """A stand-in tool used only to check binding."""
    return "result"


def test_replays_scripted_responses_in_order(scripted_model):
    model = scripted_model(ai("first"), ai("second"))
    assert model.invoke("x").content == "first"
    assert model.invoke("x").content == "second"


def test_bind_tools_returns_a_usable_model(scripted_model):
    # The stock langchain-core fakes raise NotImplementedError here, which is why
    # this class exists at all.
    model = scripted_model(ai("answer"))
    bound = model.bind_tools([sample_tool])
    assert bound.invoke("x").content == "answer"
    assert model.bound_tools == ["sample_tool"]


def test_streaming_tokens_rejoin_into_the_original_text(scripted_model):
    model = scripted_model(ai("sear it hot, do not crowd the pan"))
    streamed = "".join(chunk.content for chunk in model.stream("x"))
    assert streamed == "sear it hot, do not crowd the pan"


def test_streaming_preserves_tool_calls(scripted_model):
    # GenericFakeChatModel drops these on the streaming path. If they vanish, an
    # agent test would pass while never exercising a tool call.
    model = scripted_model(
        ai("", tool_calls=[{"name": "search_web", "args": {"query": "miso"}}])
    )
    chunks = list(model.stream("x"))
    merged = chunks[0]
    for chunk in chunks[1:]:
        merged = merged + chunk
    assert [call["name"] for call in merged.tool_calls] == ["search_web"]
    assert merged.tool_calls[0]["args"] == {"query": "miso"}


def test_injected_error_is_raised(scripted_model):
    model = scripted_model(error=RuntimeError("provider exploded"))
    with pytest.raises(RuntimeError, match="provider exploded"):
        model.invoke("x")


def test_running_out_of_responses_fails_loudly(scripted_model):
    model = scripted_model(ai("only one"))
    model.invoke("x")
    with pytest.raises(AssertionError, match="ran out of responses"):
        model.invoke("x")


def test_calls_are_recorded_for_assertions(scripted_model):
    model = scripted_model(ai("a"), ai("b"))
    model.invoke("first prompt")
    model.invoke("second prompt")
    assert len(model.calls) == 2
    assert model.calls[0][0].content == "first prompt"


@pytest.mark.asyncio
async def test_works_on_the_async_path(scripted_model):
    model = scripted_model(ai("async answer"))
    result = await model.ainvoke("x")
    assert result.content == "async answer"


def test_ai_helper_builds_well_formed_tool_calls():
    message = ai("", tool_calls=[{"name": "a"}, {"name": "b"}])
    assert isinstance(message, AIMessage)
    # Distinct ids: a duplicate id makes LangGraph mismatch tool results.
    ids = [call["id"] for call in message.tool_calls]
    assert len(set(ids)) == 2
