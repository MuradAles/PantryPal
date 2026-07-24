"""PRD section 8, end to end through the real app.

The rule these share: nothing the grader can type produces a 500 or puts a
traceback in a response body. Bad input is a 4xx, a broken dependency is either
a 503 or a degraded answer, and the user is told which.
"""

import pytest

from app import config
from tests.fakes import ScriptedChatModel, ai
from tests.integration.conftest import collect_sse


class FailsOnSecondCall(ScriptedChatModel):
    """Answers once, then fails the way a provider timeout does mid-generation."""

    def _next(self, messages):
        """Replay the script for the first call and raise on every one after it."""
        if self.calls:
            self.calls.append(list(messages))
            raise RuntimeError("provider timeout")
        return super()._next(messages)


@pytest.fixture
def dead_database(monkeypatch):
    """Point the app at a path SQLite cannot open, simulating a lost volume."""
    monkeypatch.setenv("DATABASE_PATH", "/nonexistent-directory/pantrypal.db")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


async def test_health_reports_a_dead_database_without_failing(client, dead_database):
    """The healthcheck degrades to database:false rather than 500ing the container."""
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": False}


async def test_chat_still_answers_with_the_database_gone(
    client, patch_model, scripted_model, dead_database
):
    """Memory is a feature, not a dependency. The conversation survives losing it."""
    model = patch_model(scripted_model(ai("Carbonara. One pan, ten minutes.")))

    status, events = await collect_sse(
        client, {"user_id": "murad", "message": "what should I cook"}
    )

    assert status == 200
    text = "".join(payload["text"] for name, payload in events if name == "token")
    assert text == "Carbonara. One pan, ten minutes."

    # Degraded, and the model is told so. Without this it answers a returning
    # user as though they had never said anything, which reads as amnesia rather
    # than as an outage.
    system = model.calls[0][0].content
    assert "memory is offline" in system.lower()


async def test_profile_reads_and_writes_degrade_instead_of_erroring(client, dead_database):
    """Reads and edits stay 2xx with storage gone, so the panel still renders."""
    assert (await client.get("/api/profile/murad")).json() == {
        "cookware": [], "likes": [], "dislikes": [], "avoid": []
    }
    assert (await client.patch("/api/profile/murad", json={"likes": ["thai"]})).status_code == 200

    # Deletion is the exception, and deliberately so. Degrading a read to empty
    # costs the user a suggestion; degrading a deletion to a cheerful 204 tells
    # them they were forgotten when they were not. See SPEC R22.
    assert (await client.delete("/api/profile/murad")).status_code == 503


@pytest.mark.parametrize(
    "payload",
    [
        {"user_id": "u1", "message": ""},
        {"user_id": "u1", "message": "   \n\t "},
        {"user_id": "", "message": "hello"},
        {"user_id": "u1"},
        {"user_id": "u1", "message": 17},
        {},
    ],
)
async def test_malformed_payloads_are_rejected_before_the_model(
    client, patch_model, scripted_model, payload
):
    """422, and not one token of quota spent on it."""
    model = patch_model(scripted_model(ai("this should never be sent")))

    response = await client.post("/api/chat", json=payload)

    assert response.status_code == 422
    assert model.calls == []


async def test_a_pasted_wall_of_text_is_a_413_not_a_500(
    client, patch_model, scripted_model
):
    """Over the limit the route answers before the model is ever reached."""
    model = patch_model(scripted_model(ai("this should never be sent")))

    response = await client.post(
        "/api/chat", json={"user_id": "u1", "message": "risotto " * 2000}
    )

    assert response.status_code == 413
    assert model.calls == []
    assert "too long" in response.json()["detail"].lower()


async def test_an_unreachable_model_is_a_clean_503(client, patch_model, scripted_model):
    """A provider outage gets a plain sentence, never a stack trace."""
    patch_model(scripted_model(error=RuntimeError("google api is down")))

    response = await client.post("/api/chat", json={"user_id": "u1", "message": "hello"})

    assert response.status_code == 503
    body = response.text
    assert "Traceback" not in body
    assert "google api is down" not in body
    assert "unavailable" in response.json()["detail"].lower()


async def test_a_failure_mid_stream_ends_the_stream_politely(client, patch_model):
    """The status line is already sent, so the apology has to travel in the stream."""
    # The model answers, asks for a tool, then dies on the follow-up call — the
    # one shape that cannot be reported as a status code.
    patch_model(
        FailsOnSecondCall(
            responses=[ai("Let me check.", [{"name": "get_user_profile", "args": {}}])]
        )
    )

    status, events = await collect_sse(
        client, {"user_id": "u1", "message": "what do I own"}
    )

    assert status == 200
    names = [name for name, _ in events]
    assert "error" in names, "the client is told the answer was cut short"
    assert names[-1] == "done", "the contract still closes the stream"
    assert "Traceback" not in "".join(str(payload) for _, payload in events)


@pytest.mark.parametrize(
    "message",
    [
        "что приготовить из курицы и риса",
        "¿qué puedo cocinar con arroz?",
        "鶏肉で何が作れますか",
        "🍳🍅",
    ],
)
async def test_non_english_input_gets_an_answer(
    client, patch_model, scripted_model, message
):
    """Answer or redirect, never crash. The model handles the language itself."""
    model = patch_model(scripted_model(ai("Arroz con pollo. One pot.")))

    status, events = await collect_sse(client, {"user_id": "u1", "message": message})

    assert status == 200
    assert len(model.calls) == 1
    assert "".join(payload["text"] for name, payload in events if name == "token")
