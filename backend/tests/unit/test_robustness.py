"""The failure modes in PRD section 8 that the other unit files do not cover.

Concurrency, an unreachable database, and input the English keyword layer was
never going to understand. Each of these is a row in that table, and each one is
a way the product misbehaves quietly rather than loudly.
"""

import asyncio

import pytest

from app import config, db, policy, profile


async def test_concurrent_saves_for_one_user_all_survive(tmp_db):
    """Ten overlapping writes, ten entries. A lost profile write is silent damage."""
    await db.init_db()

    await asyncio.gather(
        *(profile.save_profile("u1", cookware=[f"pan {n}"]) for n in range(10))
    )

    stored = await profile.get_profile("u1")
    assert sorted(stored["cookware"]) == sorted(f"pan {n}" for n in range(10))


async def test_concurrent_saves_across_fields_do_not_clobber_each_other(tmp_db):
    """Writes to different fields interleave too; none of them may drop the others."""
    await db.init_db()

    await asyncio.gather(
        profile.save_profile("u1", cookware=["wok"]),
        profile.save_profile("u1", likes=["thai"]),
        profile.save_profile("u1", dislikes=["coriander"]),
        profile.save_profile("u1", avoid=["shellfish"]),
    )

    stored = await profile.get_profile("u1")
    assert stored == {
        "cookware": ["wok"],
        "likes": ["thai"],
        "dislikes": ["coriander"],
        "avoid": ["shellfish"],
    }


async def test_a_save_that_adds_nothing_leaves_the_profile_intact(tmp_db):
    """An empty or wholly medical call must not roll back what is already stored."""
    await db.init_db()
    await profile.save_profile("u1", likes=["thai"])

    await profile.save_profile("u1")
    await profile.save_profile("u1", likes=["diabetic"])

    assert (await profile.get_profile("u1"))["likes"] == ["thai"]


async def test_reads_report_when_storage_is_unreachable(monkeypatch):
    """load() separates "nothing stored" from "cannot reach storage"."""
    monkeypatch.setenv("DATABASE_PATH", "/nonexistent-directory/pantrypal.db")
    config.get_settings.cache_clear()

    stored, memory_ok = await profile.load("u1")

    assert stored == dict(profile.EMPTY)
    assert memory_ok is False
    config.get_settings.cache_clear()


async def test_a_save_against_a_dead_database_returns_rather_than_raises(monkeypatch):
    """The model calling remember_about_user must not blow up the whole turn."""
    monkeypatch.setenv("DATABASE_PATH", "/nonexistent-directory/pantrypal.db")
    config.get_settings.cache_clear()

    assert await profile.save_profile("u1", likes=["thai"]) == dict(profile.EMPTY)
    # A delete that could not run must report False, not merely decline to raise.
    # delete_profile is the one function here allowed to fail loudly, because the
    # route above it turns True into a 204 that tells the user they are erased.
    assert await profile.delete_profile("u1") is False
    config.get_settings.cache_clear()


@pytest.mark.parametrize(
    "message",
    [
        "что приготовить из курицы и риса",   # what to cook from chicken and rice
        "¿qué puedo cocinar con arroz?",       # what can I cook with rice
        "鶏肉で何が作れますか",                    # what can I make with chicken
    ],
)
def test_non_english_cooking_questions_are_not_falsely_blocked(message):
    """The keyword layer stays out of the way rather than guessing at other scripts."""
    assert policy.keyword_topic(message) is None


@pytest.mark.parametrize(
    "message",
    [
        "это молоко еще можно пить?",   # is this milk still safe to drink?
        "¿este pollo sigue estando bien?",  # is this chicken still fine?
    ],
)
def test_non_english_food_safety_slips_past_the_keyword_layer(message):
    """A known limitation, asserted rather than assumed. Goes in TRADEOFFS.md.

    FOOD_SAFETY_PATTERNS are English regexes, so a non-English safety question
    reaches the LLM classifier instead of being blocked for free. That layer
    does understand other languages, so the guarantee holds while the classifier
    is up; what a non-English user loses is the deterministic backstop that an
    English one keeps when the classifier is down.
    """
    assert policy.keyword_topic(message) is None
