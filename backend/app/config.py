"""Environment-backed settings, parsed once at import and cached."""

import os
from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration, sourced from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")

    # The provided .env spells this TRAVILY_API_KEY, so accept both spellings.
    tavily_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("TAVILY_API_KEY", "TRAVILY_API_KEY"),
    )

    # SQLite file path. Lives on a Docker volume so memory survives a restart.
    database_path: str = Field(default="/data/pantrypal.db", alias="DATABASE_PATH")

    # Model ids live in config so a provider rename is an env change, not a code change.
    # Every Pro tier is quota-0 on a free AI Studio key (verified against the live
    # API), so the tiers are three flash variants with a real capability gap.
    model_classifier: str = Field(default="gemini-flash-lite-latest", alias="MODEL_CLASSIFIER")
    model_fast: str = Field(default="gemini-2.5-flash", alias="MODEL_FAST")
    model_smart: str = Field(default="gemini-3.6-flash", alias="MODEL_SMART")

    # Ceiling on the agent's tool-calling loop. Guards against runaway cost.
    max_tool_iterations: int = 5

    # Conversation turns kept in context. Bounds prompt growth over a long chat.
    history_turns: int = 10


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings singleton, normalizing provider env vars."""
    settings = Settings()
    # langchain-tavily and langchain-google-genai read these names from the
    # environment directly, so republish them under the spellings they expect.
    if settings.tavily_api_key:
        os.environ["TAVILY_API_KEY"] = settings.tavily_api_key
    if settings.gemini_api_key:
        os.environ["GOOGLE_API_KEY"] = settings.gemini_api_key
    return settings
