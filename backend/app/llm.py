"""Chat model construction.

The only file in the app allowed to name a model provider. Everything else asks
for a tier — "fast" or "smart" — and gets back a LangChain `BaseChatModel`, so
swapping providers is a change here and nowhere else.
"""

from functools import lru_cache
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import get_settings

Tier = Literal["fast", "smart"]

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
    model = settings.model_smart if tier == "smart" else settings.model_fast
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=settings.gemini_api_key,
        temperature=TEMPERATURE,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=MAX_RETRIES,
    )
