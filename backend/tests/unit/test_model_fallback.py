"""The backup model underneath every tier.

Free-tier daily caps are per model id, not per project, so one tier running dry
is an outage for the rest of the day unless something else can answer. These
assert the fallback is composed in the order that keeps the tools attached,
which is the part that breaks silently: RunnableWithFallbacks has no bind_tools,
so composing it the other way round loses them without raising.
"""

import pytest

from app import config, graph, llm, policy
from tests.fakes import ai


@pytest.fixture
def two_models(monkeypatch, scripted_model):
    """Return a factory giving the primary and backup tiers different models.

    The shared patch_model fixture hands the same object back for every tier,
    which cannot show a fallback: the backup would be the failing model again.
    """

    def _build(primary, backup, backup_id: str = "gemini-a-different-id"):
        # A backup on the same id shares the same exhausted quota, so the
        # composition is skipped entirely unless the ids actually differ.
        monkeypatch.setenv("MODEL_BACKUP", backup_id)
        config.get_settings.cache_clear()
        llm.get_model.cache_clear()
        monkeypatch.setattr(
            llm, "get_model", lambda tier="fast": backup if tier == "backup" else primary
        )
        return primary, backup

    yield _build
    config.get_settings.cache_clear()


async def test_a_dead_primary_still_answers_from_the_backup(two_models, scripted_model):
    """A spent daily quota degrades to a weaker model rather than to a 503."""
    two_models(
        scripted_model(error=RuntimeError("429 quota exceeded for gemini-3.1-flash-lite")),
        scripted_model(ai("Pearl barley, and don't stop stirring.")),
    )

    result = await graph.GRAPH.ainvoke(graph.initial_state("can I make risotto"))

    assert result["messages"][-1].content == "Pearl barley, and don't stop stirring."


async def test_the_backup_can_still_call_tools(two_models, scripted_model):
    """Tools are bound to both models, so falling back does not disarm the agent.

    This is the failure the composition order exists to prevent. Bound after the
    fallback instead of before it, the backup answers with no tools at all and
    the agent quietly loses its memory and its search.
    """
    primary, backup = two_models(
        scripted_model(error=RuntimeError("429 quota exceeded")),
        scripted_model(
            ai("", [{"name": "get_user_profile", "args": {}}]),
            ai("You've got one pan, so: carbonara."),
        ),
    )

    result = await graph.GRAPH.ainvoke(graph.initial_state("what's for dinner"))

    assert backup.bound_tools == [
        "search_web",
        "get_user_profile",
        "remember_about_user",
        "present_recipe",
    ]
    assert result["messages"][-1].content == "You've got one pan, so: carbonara."


async def test_both_models_failing_is_still_reported(two_models, scripted_model):
    """The fallback buys a second chance, not immunity. A real outage still raises."""
    two_models(
        scripted_model(error=RuntimeError("primary is down")),
        scripted_model(error=RuntimeError("backup is down")),
    )

    with pytest.raises(Exception):
        await graph.GRAPH.ainvoke(graph.initial_state("what's for dinner"))


async def test_the_classifier_falls_back_too(two_models, scripted_model):
    """A quota-dead classifier would otherwise fail open on every message all day.

    HARD rather than SIMPLE deliberately: the fail-open branch in classify()
    returns OK/SIMPLE, so asserting on SIMPLE could not tell the backup answering
    apart from the classifier giving up.
    """
    primary, backup = two_models(
        scripted_model(error=RuntimeError("429 quota exceeded")),
        scripted_model(ai('{"topic": "OK", "difficulty": "HARD"}')),
    )

    verdict = await policy.classify("what wine goes with lamb, and what do I cook first")

    assert verdict.difficulty == "HARD", "this is the fail-open default, not the backup"
    assert len(backup.calls) == 1, "the classifier never reached the backup model"


async def test_no_fallback_is_composed_when_the_backup_shares_the_id(
    two_models, scripted_model
):
    """Same model id means the same daily allowance, so a retry buys nothing.

    Skipping it is the point: composing anyway would spend a second round trip
    to receive the identical 429 the primary just returned.
    """
    primary, backup = two_models(
        scripted_model(error=RuntimeError("429 quota exceeded")),
        scripted_model(ai("Never reached.")),
        backup_id=llm.model_id("fast"),
    )

    with pytest.raises(Exception):
        await graph.GRAPH.ainvoke(graph.initial_state("what's for dinner"))

    assert backup.calls == [], "the backup was tried despite sharing the exhausted quota"


def test_every_tier_resolves_to_a_configured_id():
    """A tier with no id would build a model named None and 404 at request time."""
    config.get_settings.cache_clear()
    assert all(
        llm.model_id(tier) for tier in ("classifier", "fast", "smart", "backup")
    )
    # An unknown tier degrades to fast rather than raising mid-conversation.
    assert llm.model_id("nonsense") == llm.model_id("fast")
