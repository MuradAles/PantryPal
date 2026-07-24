"""FastAPI application entrypoint."""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from langchain_core.messages import AIMessageChunk
from sse_starlette.sse import EventSourceResponse

from app import db, graph, llm, policy
from app import profile as user_profile
from app.prompts import decline_text
from app.schemas import MAX_MESSAGE_CHARS, ChatDone, ChatRequest, ProfileUpdate

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

LLM_UNAVAILABLE = "The assistant is unavailable right now. Try again in a moment."


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the database file and schema on startup. SQLite needs no teardown."""
    await db.init_db()
    yield


app = FastAPI(title="PantryPal", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    """Report liveness plus whether the database is currently reachable."""
    return {"status": "ok", "database": await db.healthy()}


def _event(name: str, payload: dict) -> dict:
    """Wrap a payload as a named SSE event with a JSON body."""
    # JSON rather than raw text: reply text is markdown and contains newlines,
    # which would otherwise be split across data: lines and reassembled wrong.
    return {"event": name, "data": json.dumps(payload)}


async def _reply(state: dict, user_id: str, collected: list[dict]) -> AsyncIterator[str]:
    """Stream reply text from the agent graph, collecting any sources it used."""
    # Referenced through the module rather than imported by name so a test can
    # swap graph.GRAPH without patching import internals.
    # user_id travels in config, not in state, so the model can never see or set
    # it and therefore cannot reach another user's profile.
    config = {"configurable": {"user_id": user_id}}
    async for mode, payload in graph.GRAPH.astream(
        state, config=config, stream_mode=["messages", "values"]
    ):
        if mode == "messages":
            chunk, _meta = payload
            # Only the model's own words. This stream also carries ToolMessages,
            # and without the type check raw search results land in the chat
            # window ahead of the answer. Tool-calling turns from the model are
            # filtered by the empty-text check, since they carry no prose.
            if isinstance(chunk, AIMessageChunk) and (text := llm.text_of(chunk)):
                yield text
        elif mode == "values":
            # Overwritten each pass, so the last one holds the full history.
            collected[:] = graph.collect_sources(payload.get("messages", []))


async def _events(first: str, rest: AsyncIterator[str], sources: list[dict]) -> AsyncIterator[dict]:
    """Emit token events, then exactly one final event carrying the contract."""
    said: list[str] = [first] if first else []
    try:
        if first:
            yield _event("token", {"text": first})
        async for text in rest:
            said.append(text)
            yield _event("token", {"text": text})
    except Exception:
        # The 200 and its headers are already on the wire, so a failure this
        # late can only be reported inside the stream, not as a status code.
        log.exception("model call failed mid-stream")
        yield _event("error", {"detail": "The assistant stopped early. Try again."})

    # Computed from the finished reply, never written by the model. Counsel's
    # concern was inconsistency, and deriving it server-side is what makes it
    # consistent by construction.
    notice = policy.needs_allergen_notice("".join(said))
    yield _event("done", ChatDone(allergen_notice=notice, sources=sources).model_dump())


async def _canned(topic: str) -> AsyncIterator[dict]:
    """Emit a blocked-topic decline as an ordinary assistant message."""
    # Streamed like any other reply so it reads as the assistant talking, not as
    # an error state. A decline is still a conversation.
    text = decline_text(topic)
    yield _event("token", {"text": text})
    yield _event("done", ChatDone(allergen_notice=False, sources=[]).model_dump())


@app.post("/api/chat")
async def chat(request: ChatRequest) -> EventSourceResponse:
    """Stream a reply to one message over SSE, ending with the response contract."""
    if len(request.message) > MAX_MESSAGE_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Message too long. Keep it under {MAX_MESSAGE_CHARS} characters.",
        )

    state, topic = await graph.prepare(request.message, request.user_id)
    if topic != "OK":
        # The model is never invoked for a blocked topic. Nothing to talk around.
        return EventSourceResponse(_canned(topic))

    # Filled by the graph as it runs; read once the stream is exhausted, which
    # is why the same list object is handed to both halves.
    sources: list[dict] = []

    # Pull the first chunk before returning, so an unreachable model is a clean
    # 503 instead of an empty 200 the client has to interpret.
    stream = _reply(state, request.user_id, sources)
    try:
        first = await anext(stream)
    except StopAsyncIteration:
        first = ""
    except Exception:
        log.exception("model call failed before streaming started")
        raise HTTPException(status_code=503, detail=LLM_UNAVAILABLE) from None

    return EventSourceResponse(_events(first, stream, sources))


@app.get("/api/profile/{user_id}")
async def read_profile(user_id: str) -> dict:
    """Return everything stored about a user, for the profile panel."""
    return await user_profile.get_profile(user_id)


@app.patch("/api/profile/{user_id}")
async def edit_profile(user_id: str, update: ProfileUpdate) -> dict:
    """Overwrite the fields the user edited, leaving the others alone."""
    return await user_profile.replace_profile(user_id, **update.model_dump(exclude_unset=True))


@app.delete("/api/profile/{user_id}", status_code=204)
async def erase_profile(user_id: str) -> None:
    """Erase everything stored about a user. Required by counsel."""
    await user_profile.delete_profile(user_id)
