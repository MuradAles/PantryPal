"""Schema bootstrap and health reporting in app/db.py.

These touch a real SQLite file under tmp_path. No network, no container state,
and nothing is written to the volume the running app uses.
"""

import aiosqlite
import pytest

from app import config, db


@pytest.fixture
def db_at(tmp_path, monkeypatch):
    """Return a function pointing db_path() at a named file under tmp_path."""

    def _point(name: str = "test.db"):
        path = tmp_path / name
        monkeypatch.setenv("DATABASE_PATH", str(path))
        config.get_settings.cache_clear()
        return path

    yield _point
    config.get_settings.cache_clear()


async def test_init_db_creates_the_file_and_schema(db_at):
    path = db_at()
    await db.init_db()
    assert path.exists()
    async with aiosqlite.connect(path) as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='profiles'"
        )
        assert await cursor.fetchone() is not None


async def test_init_db_creates_missing_parent_directories(db_at):
    path = db_at("nested/deeper/test.db")
    await db.init_db()
    assert path.exists()


def test_schema_creates_conditionally_and_never_drops():
    # Structural, on purpose. The data-survival test below cannot tell "the table
    # was preserved by IF NOT EXISTS" from "the DROP failed on a locked table and
    # init_db swallowed the error" — both leave the row in place. This assertion
    # can, and a destructive boot would silently break session memory (R13).
    assert "IF NOT EXISTS" in db.SCHEMA
    assert "DROP" not in db.SCHEMA.upper()
    assert "TRUNCATE" not in db.SCHEMA.upper()


async def test_init_db_is_idempotent(db_at):
    db_at()
    await db.init_db()
    await db.init_db()
    # Second run must not wipe existing rows. A restart that empties the profile
    # table would silently break the "remembers you across sessions" requirement.
    async with db.connect() as conn:
        await conn.execute("INSERT INTO profiles (user_id) VALUES ('u1')")
        await conn.commit()
    await db.init_db()
    async with db.connect() as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM profiles")
        assert (await cursor.fetchone())[0] == 1


async def test_profiles_table_has_no_medical_column(db_at):
    # SPEC R21: medical conditions are never persisted, enforced structurally.
    # A condition the model tries to save must have nowhere to land.
    db_at()
    await db.init_db()
    async with db.connect() as conn:
        cursor = await conn.execute("PRAGMA table_info(profiles)")
        columns = {row[1] for row in await cursor.fetchall()}
    assert columns == {"user_id", "cookware", "likes", "dislikes", "avoid", "updated_at"}
    for banned in ("medical", "conditions", "health", "diagnosis", "allergies"):
        assert banned not in columns


async def test_list_columns_default_to_empty_json_arrays(db_at):
    # Assert on the raw stored text, not on decode(). decode() maps NULL to []
    # by design, so going through it would pass even if the column defaulted to
    # NULL — the assertion has to look at what SQLite actually wrote.
    db_at()
    await db.init_db()
    async with db.connect() as conn:
        await conn.execute("INSERT INTO profiles (user_id) VALUES ('u1')")
        await conn.commit()
        cursor = await conn.execute(
            "SELECT cookware, likes, dislikes, avoid FROM profiles WHERE user_id='u1'"
        )
        row = await cursor.fetchone()
    assert list(row) == ["[]", "[]", "[]", "[]"]


async def test_list_columns_reject_nulls(db_at):
    # NOT NULL on the list columns is what keeps the "[]" default meaningful.
    db_at()
    await db.init_db()
    async with db.connect() as conn:
        with pytest.raises(Exception, match="NOT NULL"):
            await conn.execute("INSERT INTO profiles (user_id, likes) VALUES ('u2', NULL)")


async def test_healthy_is_true_for_a_reachable_database(db_at):
    db_at()
    await db.init_db()
    assert await db.healthy() is True


async def test_healthy_is_false_when_the_path_is_unwritable(db_at, monkeypatch):
    # healthy() does not create parent directories the way init_db does, so an
    # unreachable path is the realistic "volume went away" case.
    monkeypatch.setenv("DATABASE_PATH", "/nonexistent-directory/pantrypal.db")
    config.get_settings.cache_clear()
    assert await db.healthy() is False


async def test_healthy_reports_false_rather_than_raising(monkeypatch):
    # The health endpoint must degrade to {"database": false}, never 500.
    monkeypatch.setattr(db, "connect", lambda: (_ for _ in ()).throw(OSError("disk gone")))
    assert await db.healthy() is False


async def test_init_db_survives_an_unusable_path(monkeypatch):
    # SPEC 8: database unavailable must not stop the app from starting. init_db
    # logs and continues rather than raising out of the lifespan handler.
    monkeypatch.setenv("DATABASE_PATH", "/proc/definitely/not/writable.db")
    config.get_settings.cache_clear()
    await db.init_db()  # must not raise
