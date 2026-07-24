"""What the assistant remembers about a user.

The three-tier rule from SCOPING.md lives here:

- Preferences, equipment and dislikes persist normally.
- An allergy persists as a bare ingredient name in `avoid`, with no record of
  *why* it is there. That satisfies "don't suggest shrimp" while storing a
  filter rule rather than a diagnosis.
- A medical condition is never persisted at all.

The third tier is enforced in `save_profile` rather than in the system prompt.
The model decides on its own when to save something, so it will eventually try
to save a condition; the prompt is a request and this needs to be a guarantee.
The schema backs it up by having no column a condition could live in.
"""

import logging

from app import db, policy

log = logging.getLogger(__name__)

FIELDS = ("cookware", "likes", "dislikes", "avoid")

# One entry is a short phrase like "air fryer" or "shellfish". Anything longer is
# the model narrating rather than recording, and would poison the prompt.
MAX_ENTRY_CHARS = 60
MAX_ENTRIES_PER_FIELD = 40


class Profile(dict):
    """A user's stored facts. A plain dict of field name to list of entries."""


EMPTY: dict[str, list[str]] = {field: [] for field in FIELDS}

_SELECT = f"SELECT {', '.join(FIELDS)} FROM profiles WHERE user_id = ?"

_UPSERT = f"""
INSERT INTO profiles (user_id, {', '.join(FIELDS)}, updated_at)
VALUES (?, {', '.join('?' for _ in FIELDS)}, datetime('now'))
ON CONFLICT(user_id) DO UPDATE SET
    {', '.join(f'{f} = excluded.{f}' for f in FIELDS)},
    updated_at = excluded.updated_at
"""


def _clean(values: list[str] | None) -> list[str]:
    """Normalize incoming entries and drop anything unusable or medical."""
    out: list[str] = []
    for raw in values or []:
        value = " ".join(str(raw).split()).strip().lower()
        if not value or len(value) > MAX_ENTRY_CHARS:
            continue
        if policy.contains_medical(value):
            # Dropped silently rather than raised. The model gets a success and
            # carries on; surfacing this as an error would leak the rule and
            # invite a retry with different wording.
            log.warning("refused to store a medical mention in the profile")
            continue
        if value not in out:
            out.append(value)
    return out


def _row_to_profile(row) -> dict[str, list[str]]:
    """Turn one selected row into a profile dict, or empty lists if there was none."""
    if row is None:
        return dict(EMPTY)
    return {field: db.decode(row[index]) for index, field in enumerate(FIELDS)}


async def load(user_id: str) -> tuple[dict[str, list[str]], bool]:
    """Return a user's stored facts plus whether storage was actually reachable.

    An unreachable database and a brand new user both read as empty, and the
    assistant must not treat the first as the second. Callers that can act on
    the difference use this; the rest use get_profile.
    """
    try:
        async with db.connect() as conn:
            conn.row_factory = None
            cursor = await conn.execute(_SELECT, (user_id,))
            row = await cursor.fetchone()
    except Exception:
        # Memory is a feature, not a dependency. A database problem degrades the
        # assistant to a stateless one rather than failing the request.
        log.exception("could not read profile for %s", user_id)
        return dict(EMPTY), False

    return _row_to_profile(row), True


async def get_profile(user_id: str) -> dict[str, list[str]]:
    """Return everything stored for a user, or empty lists if nothing is."""
    stored, _ = await load(user_id)
    return stored


async def save_profile(user_id: str, **updates: list[str] | None) -> dict[str, list[str]]:
    """Merge new entries into a user's profile, stripping anything medical."""
    additions = {field: _clean(updates.get(field)) for field in FIELDS}
    if not any(additions.values()):
        return await get_profile(user_id)

    try:
        async with db.connect() as conn:
            conn.row_factory = None
            # Read and write inside one write transaction. Two turns for the same
            # user overlap routinely — the model saves facts mid-conversation
            # while the profile panel is also writing — and a read-merge-write
            # spread across two connections loses whichever write committed
            # first. BEGIN IMMEDIATE takes the write lock before the read, so the
            # second caller waits and then merges on top instead of clobbering.
            await conn.execute("BEGIN IMMEDIATE")
            cursor = await conn.execute(_SELECT, (user_id,))
            current = _row_to_profile(await cursor.fetchone())

            merged = dict(current)
            for field, new in additions.items():
                if not new:
                    continue
                # Append rather than replace: a turn that mentions one new pan
                # should not wipe the rest of the kitchen.
                existing = current.get(field, [])
                merged[field] = (existing + [a for a in new if a not in existing])[
                    -MAX_ENTRIES_PER_FIELD:
                ]

            if merged == current:
                await conn.rollback()
                return current

            await conn.execute(
                _UPSERT, (user_id, *(db.encode(merged[field]) for field in FIELDS))
            )
            await conn.commit()
    except Exception:
        log.exception("could not save profile for %s", user_id)
        return await get_profile(user_id)

    return merged


async def delete_profile(user_id: str) -> None:
    """Erase everything stored about a user. Counsel requires this to exist."""
    try:
        async with db.connect() as conn:
            await conn.execute("DELETE FROM profiles WHERE user_id = ?", (user_id,))
            await conn.commit()
    except Exception:
        log.exception("could not delete profile for %s", user_id)


async def replace_profile(user_id: str, **fields: list[str] | None) -> dict[str, list[str]]:
    """Overwrite named fields outright. Backs the user editing their own profile."""
    current = await get_profile(user_id)
    merged = {f: (_clean(fields[f]) if fields.get(f) is not None else current.get(f, [])) for f in FIELDS}
    try:
        async with db.connect() as conn:
            await conn.execute(
                _UPSERT, (user_id, *(db.encode(merged[field]) for field in FIELDS))
            )
            await conn.commit()
    except Exception:
        log.exception("could not replace profile for %s", user_id)
        return current
    return merged


def profile_to_prompt(profile: dict[str, list[str]]) -> str:
    """Render a profile as the lines injected into the system prompt."""
    labels = {
        "cookware": "Equipment they own",
        "likes": "Food they like",
        "dislikes": "Food they dislike",
        "avoid": "Never suggest these ingredients",
    }
    lines = [f"- {labels[f]}: {', '.join(profile[f])}" for f in FIELDS if profile.get(f)]
    return "\n".join(lines)
