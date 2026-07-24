"""Chat model construction.

The only file in the app allowed to name a model provider. Everything else asks
for a tier — "classifier", "fast" or "smart" — and gets back a LangChain
`BaseChatModel`, so swapping providers is a change here and nowhere else.

Callers that run a model in the request path should ask for it through
`bound_model`, `structured_model` or `resilient_model` rather than `get_model`,
because those add the backup model underneath. Free-tier daily caps are per
model id, not per project, so one tier running dry would otherwise take the
whole product down for the rest of the day.
"""

import logging
from collections.abc import Callable, Sequence
from functools import lru_cache
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import get_settings

log = logging.getLogger(__name__)

Tier = Literal["classifier", "fast", "smart", "backup"]

# Warm enough to have opinions, which is the whole personality requirement, but
# not so warm it starts inventing ingredients.
TEMPERATURE = 0.7

# A stuck call should surface as a clean 503 rather than hold a request open.
# Two retries covers a transient 429 without turning a dead key into a minute
# of silence.
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 2


def model_id(tier: Tier = "fast") -> str:
    """Return the configured model id for a tier."""
    settings = get_settings()
    by_tier = {
        "classifier": settings.model_classifier,
        "fast": settings.model_fast,
        "smart": settings.model_smart,
        "backup": settings.model_backup,
    }
    # An unknown tier falls back to fast rather than raising; a routing bug
    # should degrade to a working answer, not a 503.
    return by_tier.get(tier, settings.model_fast)


@lru_cache
def get_model(tier: Tier = "fast") -> BaseChatModel:
    """Return the chat model for a difficulty tier, cached per tier."""
    settings = get_settings()
    model = model_id(tier)

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


def _worth_falling_back(tier: Tier) -> bool:
    """Whether the backup model is a different allowance from this tier's."""
    # Daily caps are per model id. A backup pointing at the same id shares the
    # same exhausted quota, so falling back to it would retry into the identical
    # 429 and cost the user a second round trip to learn nothing. Compared on the
    # configured id rather than on the tier name, because MODEL_BACKUP is
    # env-settable and an operator can quietly make them equal.
    return tier != "backup" and model_id("backup") != model_id(tier)


def _compose(tier: Tier, adapt: Callable[[BaseChatModel], Runnable]) -> Runnable:
    """Adapt a tier's model, with the backup model adapted the same way beneath it.

    The adaptation has to happen before the fallback rather than after. bind_tools
    and with_structured_output live on BaseChatModel, and RunnableWithFallbacks
    has neither — so `model.with_fallbacks(...).bind_tools(...)` raises, and the
    tools would be silently absent even if it did not.
    """
    primary = adapt(get_model(tier))
    if not _worth_falling_back(tier):
        return primary
    return primary.with_fallbacks([adapt(get_model("backup"))])


def bound_model(tier: Tier, tools: Sequence[Any]) -> Runnable:
    """Return a tier's model with tools bound, backed by the backup model."""
    return _compose(tier, lambda model: model.bind_tools(tools))


def structured_model(tier: Tier, schema: Any) -> Runnable:
    """Return a tier's model constrained to a schema, backed by the backup model."""
    return _compose(tier, lambda model: model.with_structured_output(schema))


def resilient_model(tier: Tier) -> Runnable:
    """Return a tier's model unadapted, backed by the backup model."""
    return _compose(tier, lambda model: model)


def text_of(message: BaseMessage) -> str:
    """Flatten a message or stream chunk to plain text, whatever shape it uses."""
    # Some Gemini models return a list of content blocks instead of a string.
    # langchain-core's `.text` accessor normalizes both, so callers should never
    # reach for `.content` directly.
    return str(message.text)
