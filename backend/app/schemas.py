"""Request and response shapes for the HTTP API."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Past this a message is a paste, not a question. The route answers 413 rather
# than letting it reach the model, where it would cost tokens and time.
MAX_MESSAGE_CHARS = 4000

Difficulty = Literal["easy", "medium", "hard"]


class ChatRequest(BaseModel):
    """One user turn: who is asking, and what they said."""

    user_id: str = Field(min_length=1, max_length=200)
    message: str

    @field_validator("user_id", "message")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        """Strip surrounding whitespace and reject anything left empty."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be empty or whitespace")
        return cleaned


class Source(BaseModel):
    """One web result the answer drew on. Titled, because a bare URL is poor link text."""

    title: str
    url: str


class Recipe(BaseModel):
    """One dish, structured enough for the frontend to render as a card.

    Only the title and the steps are required. A model that does not know how
    long something takes or how many it feeds should leave those out — a card
    with a blank slot is honest, an invented forty-five minutes is not.

    The same shape serves three places: what present_recipe records, what rides
    on the done event, and what POST /api/recipes accepts. One definition means
    a card the user saves is byte-identical to the card they were shown.
    """

    title: str = Field(min_length=1, max_length=200)
    # Always lists, never null, so the frontend can map over them unguarded.
    steps: list[str] = Field(default_factory=list)
    ingredients: list[str] = Field(default_factory=list)
    time_mins: int | None = Field(default=None, ge=1, le=6000)
    difficulty: Difficulty | None = None
    serves: int | None = Field(default=None, ge=1, le=100)


class SavedRecipe(Recipe):
    """A recipe the user kept, with the two fields storage adds to it.

    Flat rather than nesting the recipe under a key, so one card component
    renders both a suggestion off the chat stream and a row off the saved list.
    """

    id: int
    # ISO 8601 UTC. SQLite's own datetime() format has no T and no Z, and
    # `new Date()` on it is only reliable in some browsers.
    saved_at: str


class ChatDone(BaseModel):
    """Final SSE event: the UI chrome the model is not allowed to write itself."""

    # Stays False until phase 5 computes it from the reply text. Rendered by the
    # frontend from this flag, never from anything the model says. See SPEC R18.
    allergen_notice: bool = False

    # Populated once the search tool lands in phase 3.
    sources: list[Source] = Field(default_factory=list)

    # Null on every turn the model did not present a specific dish, which is
    # most of them. Conversation is not a recipe.
    recipe: Recipe | None = None


class ProfileUpdate(BaseModel):
    """A user editing their own stored facts from the profile panel.

    Every field is optional: an omitted field is left untouched rather than
    cleared, so removing one tag cannot wipe the rest of the profile.
    """

    cookware: list[str] | None = None
    likes: list[str] | None = None
    dislikes: list[str] | None = None
    avoid: list[str] | None = None
