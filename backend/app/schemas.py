"""Request and response shapes for the HTTP API."""

from pydantic import BaseModel, Field, field_validator

# Past this a message is a paste, not a question. The route answers 413 rather
# than letting it reach the model, where it would cost tokens and time.
MAX_MESSAGE_CHARS = 4000


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


class ChatDone(BaseModel):
    """Final SSE event: the UI chrome the model is not allowed to write itself."""

    # Stays False until phase 5 computes it from the reply text. Rendered by the
    # frontend from this flag, never from anything the model says. See SPEC R18.
    allergen_notice: bool = False

    # Result URLs, populated once the search tool lands in phase 3.
    sources: list[str] = Field(default_factory=list)
