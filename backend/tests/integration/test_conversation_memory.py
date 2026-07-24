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
def dead_storage(monkeypatch):
    """Point the app at a path SQLite cannot open, simulating a lost volume."""
    from app import config

    monkeypatch.setenv("DATABASE_PATH", "/nonexistent-directory/pantrypal.db")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


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


async def test_deleting_a_profile_also_erases_the_conversation(
    client, patch_model, scripted_model
):
    """Counsel's deletion requirement covers the transcript, not just the profile."""
    model = patch_model(
        scripted_model(ai("Bagna cauda."), ai("Still bagna cauda."), ai("Fresh start."))
    )

    await collect_sse(client, {"user_id": "murad", "message": "artichokes and anchovies"})
    await collect_sse(client, {"user_id": "murad", "message": "anything else"})
    assert "artichokes and anchovies" in [m.content for m in model.calls[1]]

    assert (await client.delete("/api/profile/murad")).status_code == 204

    await collect_sse(client, {"user_id": "murad", "message": "hello again"})
    after = [m.content for m in model.calls[2]]
    assert "artichokes and anchovies" not in after, "the deleted conversation came back"
    assert after[-1] == "hello again"


async def stored_checkpoint_rows(thread_id: str) -> int:
    """Count the checkpointer's own rows for one thread, without going through it."""
    from app import db

    total = 0
    async with db.connect() as conn:
        for table in ("checkpoints", "writes"):
            cursor = await conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE thread_id = ?", (thread_id,)
            )
            total += (await cursor.fetchone())[0]
    return total


async def test_delete_leaves_no_row_behind_in_the_checkpoint_tables(
    client, patch_model, scripted_model
):
    """Asserted against storage directly, because "it behaves as if gone" is not gone."""
    patch_model(scripted_model(ai("Bagna cauda."), ai("Still bagna cauda.")))
    await collect_sse(client, {"user_id": "murad", "message": "artichokes and anchovies"})
    await collect_sse(client, {"user_id": "murad", "message": "anything else"})
    assert await stored_checkpoint_rows("murad") > 0, "nothing was stored to delete"

    assert (await client.delete("/api/profile/murad")).status_code == 204

    assert await stored_checkpoint_rows("murad") == 0


async def test_deleting_one_user_does_not_touch_another(
    client, patch_model, scripted_model
):
    """A deletion is scoped to the person who asked for it."""
    model = patch_model(scripted_model(ai("One."), ai("Two."), ai("Three.")))
    await collect_sse(client, {"user_id": "murad", "message": "artichokes"})
    await collect_sse(client, {"user_id": "someone-else", "message": "anchovies"})

    await client.delete("/api/profile/murad")

    assert await stored_checkpoint_rows("murad") == 0
    assert await stored_checkpoint_rows("someone-else") > 0
    # And their conversation still works, rather than merely having rows on disk.
    await collect_sse(client, {"user_id": "someone-else", "message": "and now"})
    assert "anchovies" in [m.content for m in model.calls[2]]


async def test_a_deletion_that_cannot_finish_says_so(client, dead_storage):
    """A 204 the user cannot rely on is worse than an error they can retry."""
    response = await client.delete("/api/profile/murad")

    assert response.status_code == 503
    assert "try again" in response.json()["detail"].lower()


@pytest.mark.parametrize("failing", ["profile", "conversation"])
async def test_either_half_of_the_deletion_failing_is_reported(client, monkeypatch, failing):
    """Both halves are load-bearing, so each is failed on its own.

    Failing them together, as a dead database does, cannot tell whether the route
    checks both results or only one of them.
    """
    from app import graph
    from app import profile as user_profile

    async def _fails(user_id: str) -> bool:
        return False

    async def _succeeds(user_id: str) -> bool:
        return True

    monkeypatch.setattr(
        user_profile, "delete_profile", _fails if failing == "profile" else _succeeds
    )
    monkeypatch.setattr(
        graph, "forget_conversation", _fails if failing == "conversation" else _succeeds
    )

    response = await client.delete("/api/profile/murad")

    assert response.status_code == 503, f"a failed {failing} delete was reported as success"


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
