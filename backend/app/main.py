"""FastAPI application entrypoint."""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessageChunk
from sse_starlette.sse import EventSourceResponse

from app import db, graph, llm, policy
from app import profile as user_profile
from app import recipes as saved_recipes
from app.prompts import decline_text
from app.schemas import (
    MAX_MESSAGE_CHARS,
    ChatDone,
    ChatRequest,
    ProfileUpdate,
    Recipe,
    SavedRecipe,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

LLM_UNAVAILABLE = "The assistant is unavailable right now. Try again in a moment."


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the database file and schema on startup, and close the checkpointer."""
    await db.init_db()
    yield
    # The profile store opens and closes a connection per call and needs no
    # teardown. The checkpointer does not: it holds one open on a non-daemon
    # thread, which keeps the process alive after uvicorn stops and turns a
    # `compose stop` into a ten second wait for SIGKILL.
    await graph.reset_graph()


app = FastAPI(title="PantryPal", version="0.1.0", lifespan=lifespan)

# Open, because the API carries no cookies or auth header: the user id travels in
# the request body, so there is no ambient credential for another origin to
# borrow. Restricting to the Vite origin would only break a reviewer who serves
# the built frontend from a different port.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    """Report liveness plus whether the database is currently reachable."""
    return {"status": "ok", "database": await db.healthy()}


def _event(name: str, payload: dict) -> dict:
    """Wrap a payload as a named SSE event with a JSON body."""
    # JSON rather than raw text: reply text is markdown and contains newlines,
    # which would otherwise be split across data: lines and reassembled wrong.
    return {"event": name, "data": json.dumps(payload)}


async def _reply(state: dict, user_id: str, collected: dict) -> AsyncIterator[str]:
    """Stream reply text from the agent graph, collecting what the done event needs."""
    # Referenced through the module rather than imported by name so a test can
    # swap the graph without patching import internals.
    # user_id travels in config, not in state, so the model can never see or set
    # it and therefore cannot reach another user's profile. thread_id is the same
    # value: one continuing conversation per user, which is what "remembers you
    # across sessions" means once the checkpointer is in play.
    config = {"configurable": {"user_id": user_id, "thread_id": user_id}}
    compiled = await graph.get_graph()
    async for mode, payload in compiled.astream(
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
            messages = payload.get("messages", [])
            collected["sources"] = graph.collect_sources(messages)
            collected["recipe"] = graph.collect_recipe(messages)


async def _events(first: str, rest: AsyncIterator[str], collected: dict) -> AsyncIterator[dict]:
    """Emit token events, then exactly one final event carrying the contract."""
    said: list[str] = [first] if first else []
    failed = False
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
        failed = True
        yield _event("error", {"detail": "The assistant stopped early. Try again."})

    if not failed and not "".join(said).strip():
        # A turn that produced no prose and no error would leave an empty bubble
        # and no way to tell that anything went wrong. Nothing raised, so there
        # is nothing to report as an error — but the user still asked a question
        # and is owed a sentence rather than silence. Never bare-refuses, R16.
        log.warning("the model returned no text at all; sending the fallback line")
        fallback = "I lost my thread there. Ask me again and I'll give you a proper answer."
        said.append(fallback)
        yield _event("token", {"text": fallback})

    recipe = collected.get("recipe")
    # Computed from the finished reply, never written by the model. Counsel's
    # concern was inconsistency, and deriving it server-side is what makes it
    # consistent by construction.
    #
    # A card counts as naming a recipe even when the prose around it somehow did
    # not, so the card alone is enough to trigger the notice. R18 says every
    # response naming a recipe or an ingredient, and a card is nothing else.
    notice = policy.needs_allergen_notice("".join(said)) or recipe is not None
    yield _event(
        "done",
        ChatDone(
            allergen_notice=notice,
            sources=collected.get("sources") or [],
            recipe=recipe,
        ).model_dump(),
    )


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
    # is why the same object is handed to both halves.
    collected: dict = {"sources": [], "recipe": None}

    # Pull the first chunk before returning, so an unreachable model is a clean
    # 503 instead of an empty 200 the client has to interpret.
    stream = _reply(state, request.user_id, collected)
    try:
        first = await anext(stream)
    except StopAsyncIteration:
        first = ""
    except Exception:
        log.exception("model call failed before streaming started")
        raise HTTPException(status_code=503, detail=LLM_UNAVAILABLE) from None

    return EventSourceResponse(_events(first, stream, collected))


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
    # Both stores, not just the profile one. Once conversations persist, the
    # transcript is as much "stored about them" as the profile row is.
    #
    # They cannot share a transaction — the checkpointer owns its own connection
    # and SQLite has no cross-connection transaction — so instead both deletes
    # are idempotent and the conversation goes first. A failure part way through
    # leaves a retry that converges, and this route never answers 204 unless
    # both actually succeeded. Reporting a deletion that did not happen is the
    # one failure mode counsel would care about.
    forgotten = await graph.forget_conversation(user_id)
    unsaved = await saved_recipes.delete_all(user_id)
    deleted = await user_profile.delete_profile(user_id)
    if not (forgotten and unsaved and deleted):
        raise HTTPException(
            status_code=503,
            detail="Could not delete everything right now. Some of it may still be stored. Try again.",
        )


@app.delete("/api/chat/{user_id}", status_code=204)
async def new_chat(user_id: str) -> None:
    """Start a fresh conversation, keeping everything the assistant knows about the user.

    Deliberately narrower than erase_profile above. This drops the transcript and
    nothing else: the profile and the saved recipes survive, so a new chat still
    knows what pans they own and what they will not eat. Forgetting the kitchen
    every time someone wanted a clean thread would undo the whole memory feature.

    Reported rather than swallowed. Clearing the thread only in the browser would
    look identical to the user and be a lie — history lives in the checkpointer,
    keyed on the user, so the model would answer the next message with the old
    conversation still in front of it.
    """
    if not await graph.forget_conversation(user_id):
        raise HTTPException(
            status_code=503,
            detail="Could not start a new chat right now. Try again.",
        )


@app.post("/api/recipes/{user_id}", status_code=201)
async def save_recipe(user_id: str, recipe: Recipe) -> SavedRecipe:
    """Keep one recipe for a user, returning it with the id it was stored under."""
    # Re-validated through Recipe on the way in rather than trusted from the
    # client, so a card cannot be edited into a different shape than the one the
    # tool produced before it reaches storage.
    stored = await saved_recipes.save_recipe(user_id, recipe.model_dump())
    if stored is None:
        raise HTTPException(status_code=503, detail="Could not save that recipe. Try again.")
    return SavedRecipe(**stored)


@app.get("/api/recipes/{user_id}")
async def list_recipes(user_id: str) -> list[SavedRecipe]:
    """Return a user's saved recipes, newest first."""
    return [SavedRecipe(**row) for row in await saved_recipes.list_recipes(user_id)]


@app.delete("/api/recipes/{user_id}/{recipe_id}", status_code=204)
async def forget_recipe(user_id: str, recipe_id: int) -> None:
    """Remove one saved recipe, if it belongs to this user."""
    removed = await saved_recipes.delete_recipe(user_id, recipe_id)
    if removed is None:
        raise HTTPException(status_code=503, detail="Could not delete that recipe. Try again.")
    if not removed:
        # 404 rather than a silent 204: the only way to reach this is a stale
        # list or someone else's id, and both are worth the client knowing about.
        raise HTTPException(status_code=404, detail="No such saved recipe.")
