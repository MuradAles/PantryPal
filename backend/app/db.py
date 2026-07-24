"""SQLite storage and schema bootstrap.

SQLite keeps v1 to a single container with nothing to provision. The access
layer here is deliberately thin, so moving to Postgres later means rewriting
this file and nothing else.

SQLite has no array type, so the list columns are stored as JSON text and
encoded/decoded at this boundary.

LangGraph's conversation checkpointer shares this same file rather than taking a
second one. It owns its own tables, and one file means one volume to mount and
one thing to delete when a user asks for everything to go.
"""

import json
import logging
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.config import get_settings

log = logging.getLogger(__name__)

# No medical column exists here, by design. A condition the model tries to save
# has nowhere to land even if the write guard were bypassed. See PRD.md 5.1.
SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    user_id    TEXT PRIMARY KEY,
    cookware   TEXT NOT NULL DEFAULT '[]',
    likes      TEXT NOT NULL DEFAULT '[]',
    dislikes   TEXT NOT NULL DEFAULT '[]',
    avoid      TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def db_path() -> Path:
    """Return the configured database file path."""
    return Path(get_settings().database_path)


async def init_db() -> None:
    """Create the database file and schema if absent, tolerating a failure."""
    try:
        path = db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(path) as conn:
            # WAL lets reads proceed during writes, which matters once the agent
            # is saving profile facts mid-conversation.
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.executescript(SCHEMA)
            await conn.commit()
        log.info("database ready at %s", path)
    except Exception:
        log.exception("database unavailable at startup; continuing without memory")


def connect() -> aiosqlite.Connection:
    """Open a short-lived connection; callers use it as an async context manager."""
    return aiosqlite.connect(db_path())


async def checkpointer() -> AsyncSqliteSaver:
    """Open the conversation checkpointer over the same database file.

    Unlike connect(), this connection is long-lived: LangGraph holds it for the
    life of the process and binds it to the running event loop, so it cannot be
    the short-lived per-call shape the profile store uses.

    Raises if the file is unreachable. The caller decides what an absent
    checkpointer means, which is the only reason this does not swallow it like
    the rest of this module.
    """
    # Deliberately no mkdir here. init_db creates the directory at startup, and
    # silently recreating a volume that has gone missing would turn a visible
    # outage into a chat that quietly forgets everything every restart.
    conn = await aiosqlite.connect(db_path())
    await conn.execute("PRAGMA journal_mode=WAL")
    saver = AsyncSqliteSaver(conn)
    await saver.setup()
    return saver


def encode(values: list[str]) -> str:
    """Serialize a list column for storage."""
    return json.dumps(values)


def decode(raw: str | None) -> list[str]:
    """Deserialize a list column, returning an empty list on missing or bad data."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        log.warning("corrupt list column, treating as empty")
        return []


async def healthy() -> bool:
    """Return True when a trivial query against the database succeeds."""
    try:
        async with connect() as conn:
            await conn.execute("SELECT 1")
        return True
    except Exception:
        log.warning("database health check failed")
        return False
