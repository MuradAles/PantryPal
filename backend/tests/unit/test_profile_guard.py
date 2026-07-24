"""The medical write guard.

This is the highest-stakes code in the build. The CEO wants the assistant to
remember people; counsel forbids storing health data. The reconciliation is that
`remember_about_user` is model-driven, so the model *will* eventually try to
save a condition, and `save_profile` has to refuse it every time.

If any test in this file goes red, the product is storing something it is not
allowed to store.
"""

import pytest

from app import policy, profile


@pytest.mark.parametrize(
    "condition",
    [
        "diabetic",
        "diabetes",
        "i have diabetes",
        "pregnant",
        "celiac",
        "crohn",
        "on blood pressure medication",
        "chemotherapy",
        "hypertension",
        "thyroid",
    ],
)
async def test_medical_conditions_never_reach_storage(tmp_db, condition):
    """Whatever the model sends, a condition does not land in the table."""
    from app import db

    await db.init_db()

    # Tried through every field, because a model that is refused on one will
    # reasonably try another.
    await profile.save_profile(
        "u1", cookware=[condition], likes=[condition], dislikes=[condition], avoid=[condition]
    )
    stored = await profile.get_profile("u1")

    everything = sum(stored.values(), [])
    assert everything == [], f"{condition!r} was stored as {everything}"


async def test_allergies_are_stored_as_bare_ingredients(tmp_db):
    """An allergy persists as the ingredient alone, which is the whole design."""
    from app import db

    await db.init_db()

    await profile.save_profile("u1", avoid=["shellfish"])
    stored = await profile.get_profile("u1")

    # The CEO's own example: told once, never suggested again. No record of why.
    assert stored["avoid"] == ["shellfish"]


async def test_preferences_are_stored_normally(tmp_db):
    """Counsel explicitly allows plain preferences, so vegetarian must survive."""
    from app import db

    await db.init_db()

    await profile.save_profile("u1", likes=["vegetarian", "thai"], cookware=["hot plate"])
    stored = await profile.get_profile("u1")

    assert stored["likes"] == ["vegetarian", "thai"]
    assert stored["cookware"] == ["hot plate"]


async def test_a_medical_mention_does_not_discard_the_valid_entries(tmp_db):
    """One bad value in a list must not cost the user the good ones."""
    from app import db

    await db.init_db()

    await profile.save_profile("u1", likes=["thai", "diabetic", "very spicy"])
    stored = await profile.get_profile("u1")

    assert stored["likes"] == ["thai", "very spicy"]


async def test_saving_appends_rather_than_replaces(tmp_db):
    """Mentioning one new pan must not wipe the rest of the kitchen."""
    from app import db

    await db.init_db()

    await profile.save_profile("u1", cookware=["hot plate"])
    await profile.save_profile("u1", cookware=["one pan"])
    stored = await profile.get_profile("u1")

    assert stored["cookware"] == ["hot plate", "one pan"]


async def test_repeated_facts_are_not_duplicated(tmp_db):
    """Saying it twice does not put it in the profile twice."""
    from app import db

    await db.init_db()

    await profile.save_profile("u1", likes=["Thai"])
    await profile.save_profile("u1", likes=["thai  "])
    stored = await profile.get_profile("u1")

    assert stored["likes"] == ["thai"]


async def test_delete_removes_everything(tmp_db):
    """Counsel requires a deletion path, so it has to actually empty the record."""
    from app import db

    await db.init_db()

    await profile.save_profile("u1", cookware=["wok"], likes=["thai"], avoid=["shellfish"])
    await profile.delete_profile("u1")
    stored = await profile.get_profile("u1")

    assert sum(stored.values(), []) == []


async def test_profile_survives_being_read_before_it_exists(tmp_db):
    """A first-time user reads as empty, not as an error."""
    from app import db

    await db.init_db()

    assert await profile.get_profile("nobody") == {
        "cookware": [], "likes": [], "dislikes": [], "avoid": []
    }


def test_the_denylist_does_not_catch_ordinary_food_words():
    """A guard that blocks 'rice' would quietly empty every profile."""
    harmless = [
        "rice", "shellfish", "vegetarian", "air fryer", "thai", "spicy", "coriander",
        # The bare ingredient behind a condition has to stay storable — that is
        # the entire avoid-list design. "lactose intolerant" is refused;
        # "lactose" is a filter rule with no diagnosis attached to it.
        "lactose", "gluten", "dairy", "peanuts", "histamine",
        # Words the widened list could plausibly have caught by accident.
        "heart of palm", "artichoke hearts", "bypass the oven", "sugar",
        "chicken stock", "blood orange", "sweetbreads",
    ]
    for value in harmless:
        assert not policy.contains_medical(value), value


@pytest.mark.parametrize(
    "condition",
    [
        "lactose intolerant", "lactose intolerance", "gluten intolerant",
        "acid reflux", "gerd", "heartburn", "epilepsy", "migraine", "lupus",
        "endometriosis", "gallbladder removed", "no gallbladder", "gastric bypass",
        "on warfarin", "taking metformin", "on ozempic", "histamine intolerance",
        "low fodmap", "anaphylaxis", "autoimmune", "hiv", "asthma",
        "low sodium for my heart",
    ],
)
async def test_the_conditions_the_first_denylist_missed_do_not_persist(tmp_db, condition):
    """Every phrase the reviewer found stored verbatim. Regression coverage.

    The mechanism was always sound; the list was the weak part. These are the
    high-frequency ways people actually state a condition, and each one reached
    SQLite and came back out in the profile panel.
    """
    from app import db

    await db.init_db()

    await profile.save_profile(
        "u1", cookware=[condition], likes=[condition], dislikes=[condition], avoid=[condition]
    )
    stored = await profile.get_profile("u1")

    everything = sum(stored.values(), [])
    assert everything == [], f"{condition!r} was stored as {everything}"
