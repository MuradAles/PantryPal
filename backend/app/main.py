"""FastAPI application entrypoint."""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from langchain_core.messages import AIMessageChunk
from sse_starlette.sse import EventSourceResponse

from app import db, graph, llm
from app.schemas import MAX_MESSAGE_CHARS, ChatDone, ChatRequest

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


async def _reply(message: str, collected: list[dict]) -> AsyncIterator[str]:
    """Stream reply text from the agent graph, collecting any sources it used."""
    # Referenced through the module rather than imported by name so a test can
    # swap graph.GRAPH without patching import internals.
    state = graph.initial_state(message)
    async for mode, payload in graph.GRAPH.astream(
        state, stream_mode=["messages", "values"]
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
    try:
        if first:
            yield _event("token", {"text": first})
        async for text in rest:
            yield _event("token", {"text": text})
    except Exception:
        # The 200 and its headers are already on the wire, so a failure this
        # late can only be reported inside the stream, not as a status code.
        log.exception("model call failed mid-stream")
        yield _event("error", {"detail": "The assistant stopped early. Try again."})
    yield _event("done", ChatDone(sources=sources).model_dump())


@app.post("/api/chat")
async def chat(request: ChatRequest) -> EventSourceResponse:
    """Stream a reply to one message over SSE, ending with the response contract."""
    if len(request.message) > MAX_MESSAGE_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Message too long. Keep it under {MAX_MESSAGE_CHARS} characters.",
        )

    # Filled by the graph as it runs; read once the stream is exhausted, which
    # is why the same list object is handed to both halves.
    sources: list[dict] = []

    # Pull the first chunk before returning, so an unreachable model is a clean
    # 503 instead of an empty 200 the client has to interpret.
    stream = _reply(request.message, sources)
    try:
        first = await anext(stream)
    except StopAsyncIteration:
        first = ""
    except Exception:
        log.exception("model call failed before streaming started")
        raise HTTPException(status_code=503, detail=LLM_UNAVAILABLE) from None

    return EventSourceResponse(_events(first, stream, sources))
