"""Recipes the user chose to keep.

Separate from `profile.py` because it answers a different question. The profile
is what the assistant knows about someone and reads back into every prompt; a
saved recipe is something they asked to hold on to and nothing else looks at.
Keeping them apart means the prompt cannot accidentally grow by a cookbook.

Stored as one JSON blob per row rather than a column per field. The recipe shape
belongs to `schemas.Recipe`, and a migration every time the card gains a field
would buy nothing here — nothing queries inside a recipe, only by user.
"""

import logging

from app import db

log = logging.getLogger(__name__)

# A user who has saved this many has stopped curating. The cap bounds both the
# list response and how much a single account can put in the volume.
MAX_PER_USER = 200

_SELECT = """
SELECT id, recipe, saved_at FROM saved_recipes
WHERE user_id = ? ORDER BY id DESC LIMIT ?
"""

_INSERT = "INSERT INTO saved_recipes (user_id, recipe) VALUES (?, ?)"

_SELECT_ONE = "SELECT id, recipe, saved_at FROM saved_recipes WHERE id = ?"


def _row(row) -> dict | None:
    """Turn one selected row into a flat saved-recipe dict, or None if unusable."""
    recipe = db.decode_recipe(row[1])
    # A row that will not parse, or that predates a field the card now requires,
    # is dropped rather than surfaced half-formed. The frontend renders these
    # unguarded, so a recipe with no title is worse than one missing from the list.
    if not recipe or not recipe.get("title"):
        return None
    return {**recipe, "id": row[0], "saved_at": row[2]}


async def save_recipe(user_id: str, recipe: dict) -> dict | None:
    """Store one recipe for a user, returning it with its id, or None on failure.

    Reported rather than swallowed: the user pressed save and is owed the truth
    about whether it worked, unlike the profile writes the model makes silently.
    """
    try:
        async with db.connect() as conn:
            conn.row_factory = None
            cursor = await conn.execute(_INSERT, (user_id, db.encode_recipe(recipe)))
            new_id = cursor.lastrowid
            # Trim oldest-first from the same connection, so the cap holds even
            # when two saves race. Scoped to this user: one enthusiastic account
            # must not evict anyone else's.
            await conn.execute(
                "DELETE FROM saved_recipes WHERE user_id = ? AND id NOT IN "
                "(SELECT id FROM saved_recipes WHERE user_id = ? ORDER BY id DESC LIMIT ?)",
                (user_id, user_id, MAX_PER_USER),
            )
            # Read saved_at back rather than computing it here, so the timestamp
            # the user sees is the one actually in the row.
            cursor = await conn.execute(_SELECT_ONE, (new_id,))
            row = await cursor.fetchone()
            await conn.commit()
    except Exception:
        log.exception("could not save a recipe for %s", user_id)
        return None

    return _row(row) if row else None


async def list_recipes(user_id: str) -> list[dict]:
    """Return a user's saved recipes, newest first, empty if none or unreadable."""
    try:
        async with db.connect() as conn:
            conn.row_factory = None
            cursor = await conn.execute(_SELECT, (user_id, MAX_PER_USER))
            rows = await cursor.fetchall()
    except Exception:
        # Same rule as the profile store: storage trouble degrades the feature
        # rather than failing the page.
        log.exception("could not list recipes for %s", user_id)
        return []

    return [saved for saved in (_row(row) for row in rows) if saved]


async def delete_recipe(user_id: str, recipe_id: int) -> bool | None:
    """Delete one saved recipe. True if it went, False if it was not theirs, None on failure."""
    try:
        async with db.connect() as conn:
            # user_id in the WHERE clause, not checked afterwards: without it,
            # guessing an integer would delete a stranger's recipe.
            cursor = await conn.execute(
                "DELETE FROM saved_recipes WHERE id = ? AND user_id = ?",
                (recipe_id, user_id),
            )
            await conn.commit()
    except Exception:
        log.exception("could not delete recipe %s for %s", recipe_id, user_id)
        return None
    return cursor.rowcount > 0


async def delete_all(user_id: str) -> bool:
    """Erase every recipe a user saved, returning whether they are actually gone.

    Reports its failures, because the only caller is the delete-everything route
    and a saved recipe is as much "stored about them" as their profile is (R22).
    """
    try:
        async with db.connect() as conn:
            await conn.execute("DELETE FROM saved_recipes WHERE user_id = ?", (user_id,))
            await conn.commit()
    except Exception:
        log.exception("could not delete saved recipes for %s", user_id)
        return False
    return True
