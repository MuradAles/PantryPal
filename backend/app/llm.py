"""Chat model construction.

The only file in the app allowed to name a model provider. Everything else asks
for a tier — "classifier", "fast" or "smart" — and gets back a LangChain
`BaseChatModel`, so swapping providers is a change here and nowhere else.
"""

from functools import lru_cache
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import get_settings

Tier = Literal["classifier", "fast", "smart"]

# Warm enough to have opinions, which is the whole personality requirement, but
# not so warm it starts inventing ingredients.
TEMPERATURE = 0.7

# A stuck call should surface as a clean 503 rather than hold a request open.
# Two retries covers a transient 429 without turning a dead key into a minute
# of silence.
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 2


@lru_cache
def get_model(tier: Tier = "fast") -> BaseChatModel:
    """Return the chat model for a difficulty tier, cached per tier."""
    settings = get_settings()
    by_tier = {
        "classifier": settings.model_classifier,
        "fast": settings.model_fast,
        "smart": settings.model_smart,
    }
    # An unknown tier falls back to fast rather than raising; a routing bug
    # should degrade to a working answer, not a 503.
    model = by_tier.get(tier, settings.model_fast)

    options: dict = {}
    if tier != "smart":
        # The smart model has fixed sampling and warns that temperature is
        # ignored, so only send it where it changes something.
        options["temperature"] = TEMPERATURE
    if tier == "fast" and model.startswith("gemini-2.5-"):
        # Skipping the thinking pass takes first token from 2.3s to 0.5s, which
        # is the difference between a chat that feels live and one that looks
        # stuck. Hard questions route to the smart tier, which keeps thinking.
        # Gated on the model id, not just the tier: the 3.x models and the lite
        # models reject this argument with a 400, and MODEL_FAST is env-settable,
        # so an operator swapping it must not break every fast call.
        options["thinking_budget"] = 0

    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=settings.gemini_api_key,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=MAX_RETRIES,
        **options,
    )


def text_of(message: BaseMessage) -> str:
    """Flatten a message or stream chunk to plain text, whatever shape it uses."""
    # Some Gemini models return a list of content blocks instead of a string.
    # langchain-core's `.text` accessor normalizes both, so callers should never
    # reach for `.content` directly.
    return str(message.text)
