"""Conversation memory across turns, through the real app and the real checkpointer.

The profile store already remembered facts about a user. This covers the other
half: that the assistant remembers the conversation, so "what about with rice
instead?" has something to refer back to.

These use the actual AsyncSqliteSaver against the per-test database, not a stub.
A stubbed checkpointer would pass while the real thread key was wrong.
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


async def test_a_second_turn_can_see_the_first(client, patch_model, scripted_model):
    """The whole point: a follow-up has the earlier turn to refer back to."""
    model = patch_model(
        scripted_model(ai("Carbonara. One pan."), ai("Then use pearl barley."))
    )

    await collect_sse(client, {"user_id": "murad", "message": "what should I cook"})
    await collect_sse(client, {"user_id": "murad", "message": "what about with rice"})

    second_turn = [m.content for m in model.calls[1]]
    assert "what should I cook" in second_turn, "the first question was forgotten"
    assert "Carbonara. One pan." in second_turn, "its own answer was forgotten"
    assert second_turn[-1] == "what about with rice"


async def test_two_users_do_not_share_a_conversation(client, patch_model, scripted_model):
    """Threads are keyed per user. One person's chat is not another's context."""
    # Canaries chosen not to appear in the persona's own few-shot examples, which
    # are part of every system prompt and would otherwise match.
    model = patch_model(
        scripted_model(ai("Bagna cauda, obviously."), ai("Carbonara."), ai("Pearl barley."))
    )

    await collect_sse(client, {"user_id": "murad", "message": "artichokes and anchovies"})
    await collect_sse(client, {"user_id": "someone-else", "message": "what should I cook"})
    await collect_sse(client, {"user_id": "someone-else", "message": "and with rice"})

    stranger = " ".join(m.content for m in model.calls[2])
    assert "artichokes and anchovies" not in stranger
    assert "Bagna cauda, obviously." not in stranger
    # Their own history is intact, so this is isolation and not an empty thread.
    assert "what should I cook" in stranger


async def test_the_system_prompt_does_not_accumulate(client, patch_model, scripted_model):
    """It is rebuilt each turn, so stored history must not collect copies of it."""
    model = patch_model(
        scripted_model(ai("One."), ai("Two."), ai("Three."))
    )

    for message in ("first", "second", "third"):
        await collect_sse(client, {"user_id": "murad", "message": message})

    system_messages = [m for m in model.calls[2] if m.type == "system"]
    assert len(system_messages) == 1, "the persona is being appended every turn"
    assert system_messages[0] is model.calls[2][0], "it must lead the list"


async def test_a_profile_learned_this_turn_applies_on_the_next(
    client, patch_model, scripted_model
):
    """Rebuilding the prompt each turn is what makes a saved fact take effect."""
    model = patch_model(
        scripted_model(
            ai("", [{"name": "remember_about_user", "args": {"cookware": ["tagine"]}}]),
            ai("Chicken and preserved lemon, then."),
            ai("Still the tagine."),
        )
    )

    await collect_sse(client, {"user_id": "murad", "message": "I have a tagine"})
    await collect_sse(client, {"user_id": "murad", "message": "what now"})

    # Turn one is the first two calls: the tool request and the answer. The third
    # call is turn two, whose prompt must carry the fact turn one saved — a frozen
    # prompt would still describe the kitchen as unknown. "tagine" appears nowhere
    # in the persona, so matching on it cannot be the few-shot examples.
    assert "Equipment they own: tagine" not in model.calls[0][0].content
    assert "Equipment they own: tagine" in model.calls[2][0].content


async def test_sources_belong_to_the_turn_that_cited_them(
    client, patch_model, scripted_model, fake_search
):
    """A page cited earlier must not reappear on every later answer."""
    patch_model(
        scripted_model(
            ai("", [{"name": "search_web", "args": {"query": "nduja"}}]),
            ai("A spreadable Calabrian salami."),
            ai("Chicken is done at 74C."),
        )
    )

    _, first = await collect_sse(client, {"user_id": "murad", "message": "what is nduja"})
    _, second = await collect_sse(
        client, {"user_id": "murad", "message": "when is chicken done"}
    )

    assert [p for n, p in first if n == "done"][0]["sources"] == [
        {"title": "Nduja explained", "url": "https://example.com/nduja"}
    ]
    assert [p for n, p in second if n == "done"][0]["sources"] == []


async def test_chat_still_answers_when_the_checkpointer_cannot_open(
    client, patch_model, scripted_model, monkeypatch
):
    """Conversation memory is a feature, not a dependency, same as the profile."""
    from app import db, graph

    async def _broken() -> None:
        raise OSError("volume gone")

    monkeypatch.setattr(db, "checkpointer", _broken)
    await graph.reset_graph()
    patch_model(scripted_model(ai("Carbonara. One pan.")))

    status, events = await collect_sse(
        client, {"user_id": "murad", "message": "what should I cook"}
    )

    assert status == 200
    text = "".join(p["text"] for n, p in events if n == "token")
    assert text == "Carbonara. One pan."
