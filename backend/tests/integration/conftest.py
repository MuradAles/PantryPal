"""Integration-level fixtures: a real ASGI app, a fake model, no network."""

import json
import re

import pytest
from httpx import ASGITransport, AsyncClient

from app import db, graph
from app.main import app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    """Yield an httpx client bound to the real app over ASGI, on a throwaway db."""
    from app import config

    # ASGITransport does not run lifespan events, so the schema is created here.
    # A per-test database also keeps these from touching the volume the running
    # container serves from.
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "integration.db"))
    config.get_settings.cache_clear()
    await db.init_db()
    # The checkpointer is cached across requests and binds to both a database
    # file and the event loop it was built on, so a leftover one from the
    # previous test would still be pointing at that test's database.
    await graph.reset_graph()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client

    await graph.reset_graph()
    config.get_settings.cache_clear()


def parse_sse(raw: str) -> list[tuple[str, dict | None]]:
    """Parse a raw SSE body into a list of (event_name, decoded_payload)."""
    events: list[tuple[str, dict | None]] = []
    for block in re.split(r"\r?\n\r?\n", raw):
        if not block.strip():
            continue
        name: str | None = None
        data: str | None = None
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = line[len("data:") :].strip()
        if name is not None:
            events.append((name, json.loads(data) if data else None))
    return events


async def collect_sse(client: AsyncClient, payload: dict) -> tuple[int, list]:
    """POST to /api/chat and return the status plus the parsed event list."""
    async with client.stream("POST", "/api/chat", json=payload) as response:
        if response.status_code != 200:
            await response.aread()
            return response.status_code, []
        body = "".join([chunk async for chunk in response.aiter_text()])
    return 200, parse_sse(body)


@pytest.fixture(autouse=True)
def keyword_only_classifier(monkeypatch):
    """Make classify() use the keyword layer alone, with no model call.

    Autouse because the LLM half of the classifier would otherwise consume a
    response from every test's script, silently shifting which reply the agent
    sees. The keyword layer is real code, so blocked-topic tests still exercise
    the production path.
    """
    from app import policy

    async def _classify(message: str) -> policy.Classification:
        blocked = policy.keyword_topic(message)
        return policy.Classification(
            topic=blocked or "OK", difficulty="SIMPLE"
        )

    monkeypatch.setattr(policy, "classify", _classify)
