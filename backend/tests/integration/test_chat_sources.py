"""Search results reaching the SSE contract.

The frontend renders sources as chrome, so they have to arrive as structured
data on the final event rather than as text the model wrote into its answer.
"""

import pytest

from app import tools
from tests.fakes import ai
from tests.integration.conftest import collect_sse


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
                        "title": "Nduja explained",
                        "url": "https://example.com/nduja",
                        "content": "A spreadable Calabrian salami.",
                    }
                ]
            }

    monkeypatch.setattr(tools, "TavilySearch", FakeTavily)
    monkeypatch.setattr(
        tools, "get_settings", lambda: type("S", (), {"tavily_api_key": "test-key"})()
    )


async def test_sources_arrive_on_the_done_event(
    client, patch_model, scripted_model, fake_search
):
    """A searched answer carries its sources as objects, not as prose."""
    patch_model(
        scripted_model(
            ai("", [{"name": "search_web", "args": {"query": "nduja"}}]),
            ai("Nduja is a spreadable Calabrian salami."),
        )
    )

    status, events = await collect_sse(client, {"user_id": "u1", "message": "what is nduja"})

    assert status == 200
    done = [payload for name, payload in events if name == "done"]
    assert len(done) == 1, "exactly one done event closes the stream"
    assert done[0]["sources"] == [
        {"title": "Nduja explained", "url": "https://example.com/nduja"}
    ]


async def test_unsearched_answer_carries_no_sources(client, patch_model, scripted_model):
    """No search means an empty list, not a missing key the frontend has to guard."""
    patch_model(scripted_model(ai("Chicken is done at 74C.")))

    status, events = await collect_sse(
        client, {"user_id": "u1", "message": "when is chicken done"}
    )

    assert status == 200
    done = [payload for name, payload in events if name == "done"]
    assert done[0]["sources"] == []
    assert done[0]["allergen_notice"] is False


async def test_answer_text_still_streams_with_tools_in_play(
    client, patch_model, scripted_model, fake_search
):
    """Tool-calling turns are silent; only the final prose reaches the user."""
    patch_model(
        scripted_model(
            ai("", [{"name": "search_web", "args": {"query": "nduja"}}]),
            ai("Nduja is a spreadable Calabrian salami."),
        )
    )

    status, events = await collect_sse(client, {"user_id": "u1", "message": "what is nduja"})

    text = "".join(payload["text"] for name, payload in events if name == "token")
    assert text == "Nduja is a spreadable Calabrian salami."
