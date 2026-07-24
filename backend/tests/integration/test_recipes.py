"""Structured recipes: the card the model presents, and the ones the user keeps.

The frontend renders the card from fields rather than by parsing markdown out of
the reply, so these assert on the shape of the `recipe` object rather than on
prose. The saving half is here too because the interesting property is a
crossing one: a recipe is stored about a user, so deleting the user must take it.
"""

from app import recipes as saved_recipes
from tests.fakes import ai
from tests.integration.conftest import collect_sse

CARBONARA = {
    "name": "present_recipe",
    "args": {
        "title": "One-pan carbonara",
        "time_mins": 20,
        "difficulty": "easy",
        "serves": 2,
        "ingredients": ["200g spaghetti", "2 egg yolks", "pecorino"],
        "steps": ["Boil the pasta.", "Toss it off the heat with the yolks."],
    },
}


async def test_a_presented_recipe_arrives_as_fields_on_the_done_event(
    client, patch_model, scripted_model
):
    """The card is structured data, not markdown the frontend has to parse back apart."""
    patch_model(
        scripted_model(
            ai("", [CARBONARA]),
            ai("Carbonara, then. Keep a mug of the pasta water back."),
        )
    )

    status, events = await collect_sse(
        client, {"user_id": "murad", "message": "something warm, one pan"}
    )

    assert status == 200
    done = [payload for name, payload in events if name == "done"]
    assert len(done) == 1
    assert done[0]["recipe"] == {
        "title": "One-pan carbonara",
        "steps": ["Boil the pasta.", "Toss it off the heat with the yolks."],
        "ingredients": ["200g spaghetti", "2 egg yolks", "pecorino"],
        "time_mins": 20,
        "difficulty": "easy",
        "serves": 2,
    }
    # The persona is a product requirement: the card is in addition to the
    # assistant talking, never instead of it.
    text = "".join(payload["text"] for name, payload in events if name == "token")
    assert "Carbonara, then." in text
    # A card names a dish, so R18's notice applies whatever the prose looked like.
    assert done[0]["allergen_notice"] is True


async def test_a_turn_with_no_recipe_leaves_it_null(client, patch_model, scripted_model):
    """Most turns are conversation. Null, not a missing key the frontend must guard."""
    patch_model(scripted_model(ai("Pearl barley, and don't stop stirring.")))

    status, events = await collect_sse(
        client, {"user_id": "murad", "message": "can I make risotto without arborio"}
    )

    assert status == 200
    done = [payload for name, payload in events if name == "done"]
    assert done[0]["recipe"] is None
    assert "recipe" in done[0], "the key is always present, only its value varies"


async def test_a_recipe_without_a_time_or_a_serving_count_still_shows(
    client, patch_model, scripted_model
):
    """Omitting what it does not know beats inventing it, so the card must allow gaps."""
    patch_model(
        scripted_model(
            ai(
                "",
                [
                    {
                        "name": "present_recipe",
                        "args": {
                            "title": "Smash burgers",
                            "steps": ["Press the patties hard for thirty seconds."],
                            # No time_mins, no serves, and a difficulty word that
                            # is not one of the three the schema allows.
                            "difficulty": "beginner",
                        },
                    }
                ],
            ),
            ai("Smash burgers. The crust is the whole point."),
        )
    )

    status, events = await collect_sse(
        client, {"user_id": "murad", "message": "a pound of ground beef"}
    )

    assert status == 200
    recipe = [payload for name, payload in events if name == "done"][0]["recipe"]
    assert recipe["title"] == "Smash burgers"
    assert recipe["time_mins"] is None
    assert recipe["serves"] is None
    # Coerced to null rather than taking the whole card down with it.
    assert recipe["difficulty"] is None
    # Always lists, so the frontend can map over them without a guard.
    assert recipe["ingredients"] == []
    assert recipe["steps"] == ["Press the patties hard for thirty seconds."]


async def test_a_searched_answer_can_still_carry_a_card(
    client, patch_model, scripted_model, monkeypatch
):
    """Two tools now put artifacts on the wire, carrying different shapes.

    Looking something up and then recommending a dish is an ordinary turn, and
    the collectors have to pick their own artifact out without tripping over the
    other one. Without a shape check the recipe dict is iterated as its keys.
    """
    from app import tools

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
        tools, "get_settings", lambda: type("S", (), {"tavily_api_key": "k"})()
    )
    patch_model(
        scripted_model(
            ai("", [{"name": "search_web", "args": {"query": "nduja"}}]),
            ai("", [CARBONARA]),
            ai("Nduja pasta, then."),
        )
    )

    status, events = await collect_sse(
        client, {"user_id": "murad", "message": "what do I do with nduja"}
    )

    assert status == 200
    done = [payload for name, payload in events if name == "done"][0]
    assert done["sources"] == [{"title": "Nduja explained", "url": "https://example.com/nduja"}]
    assert done["recipe"]["title"] == "One-pan carbonara"


async def test_a_reply_with_no_text_still_says_something(client, patch_model, scripted_model):
    """An empty bubble with no error is the one outcome the user cannot act on.

    Nothing raised, so there is no error frame to send, but the model produced no
    prose either. R16 says never leave them with nothing.
    """
    patch_model(scripted_model(ai("")))

    status, events = await collect_sse(client, {"user_id": "murad", "message": "hello"})

    assert status == 200
    text = "".join(payload["text"] for name, payload in events if name == "token")
    assert text.strip(), "the turn ended with no words at all"
    assert "error" not in [name for name, _ in events], "nothing failed, so nothing to report"


async def test_saved_recipes_round_trip_and_are_scoped_to_one_user(client):
    """Saving returns an id, listing returns newest first, and neither leaks across users."""
    first = await client.post("/api/recipes/murad", json=CARBONARA["args"])
    assert first.status_code == 201
    assert first.json()["id"]
    assert first.json()["title"] == "One-pan carbonara"
    assert first.json()["saved_at"].endswith("Z"), "ISO 8601, so new Date() parses it"

    second = await client.post(
        "/api/recipes/murad", json={"title": "Pearl barley risotto", "steps": ["Stir."]}
    )
    assert second.status_code == 201
    await client.post(
        "/api/recipes/someone-else", json={"title": "Not yours", "steps": ["Nope."]}
    )

    mine = (await client.get("/api/recipes/murad")).json()
    assert [r["title"] for r in mine] == ["Pearl barley risotto", "One-pan carbonara"]
    assert (await client.get("/api/recipes/someone-else")).json()[0]["title"] == "Not yours"

    # Deleting one leaves the rest, and cannot reach across to another user's.
    assert (await client.delete(f"/api/recipes/murad/{second.json()['id']}")).status_code == 204
    assert [r["title"] for r in (await client.get("/api/recipes/murad")).json()] == [
        "One-pan carbonara"
    ]
    assert (await client.delete(f"/api/recipes/murad/{second.json()['id']}")).status_code == 404


async def test_one_user_cannot_delete_another_users_recipe(client):
    """Ownership is in the WHERE clause, so guessing an id gets you a 404, not a deletion."""
    theirs = await client.post(
        "/api/recipes/someone-else", json={"title": "Theirs", "steps": ["Mine."]}
    )

    response = await client.delete(f"/api/recipes/murad/{theirs.json()['id']}")

    assert response.status_code == 404
    assert (await client.get("/api/recipes/someone-else")).json()[0]["title"] == "Theirs"


async def test_deleting_a_user_takes_their_saved_recipes_too(client, patch_model, scripted_model):
    """R22 is everything stored about them, and a saved recipe is stored about them."""
    patch_model(scripted_model(ai("Noted.")))
    await collect_sse(client, {"user_id": "murad", "message": "artichokes"})
    await client.post("/api/recipes/murad", json=CARBONARA["args"])
    await client.post("/api/recipes/someone-else", json={"title": "Theirs", "steps": ["Mine."]})
    assert await saved_recipes.list_recipes("murad")

    assert (await client.delete("/api/profile/murad")).status_code == 204

    # Read through the store rather than the route, so this fails even if the
    # route were to start filtering what it returns instead of deleting rows.
    assert await saved_recipes.list_recipes("murad") == []
    assert len(await saved_recipes.list_recipes("someone-else")) == 1


async def test_a_saved_recipe_delete_that_cannot_finish_is_reported(client, monkeypatch):
    """The delete-everything route must not answer 204 when the recipes half failed."""

    async def _fails(user_id: str) -> bool:
        return False

    monkeypatch.setattr(saved_recipes, "delete_all", _fails)

    response = await client.delete("/api/profile/murad")

    assert response.status_code == 503, "a failed recipe wipe was reported as success"
