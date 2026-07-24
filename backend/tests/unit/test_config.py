"""Settings parsing, especially the two accepted spellings of the Tavily key.

The supplied .env spells it TRAVILY_API_KEY. Config accepts both so a corrected
.env later does not silently disable search.
"""

import pytest

from app import config
from app.config import Settings, get_settings

# Both spellings plus the provider names config republishes to. Cleared before
# every test so a value leaking in from the container env cannot mask a bug.
KEY_VARS = [
    "TAVILY_API_KEY",
    "TRAVILY_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Strip every key-related var and reset the settings cache around each test."""
    for name in KEY_VARS:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def build() -> Settings:
    """Construct Settings from the environment only, ignoring any .env on disk."""
    return Settings(_env_file=None)


def test_correct_spelling_is_accepted(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "correct-spelling")
    assert build().tavily_api_key == "correct-spelling"


def test_misspelled_variant_is_accepted(monkeypatch):
    monkeypatch.setenv("TRAVILY_API_KEY", "misspelled-variant")
    assert build().tavily_api_key == "misspelled-variant"


def test_correct_spelling_wins_when_both_are_set(monkeypatch):
    # AliasChoices resolves left to right. Pinning the precedence stops a future
    # reorder from making the resolved key depend on dict ordering.
    monkeypatch.setenv("TAVILY_API_KEY", "correct-spelling")
    monkeypatch.setenv("TRAVILY_API_KEY", "misspelled-variant")
    assert build().tavily_api_key == "correct-spelling"


def test_missing_key_defaults_to_empty_string():
    # Absent search credentials must not raise at import; search degrades instead.
    assert build().tavily_api_key == ""


def test_get_settings_republishes_keys_under_provider_names(monkeypatch):
    # langchain-tavily and langchain-google-genai read these names off the
    # environment themselves, so the republishing step is load-bearing.
    monkeypatch.setenv("TRAVILY_API_KEY", "misspelled-variant")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")

    settings = get_settings()

    import os

    assert os.environ["TAVILY_API_KEY"] == "misspelled-variant"
    assert os.environ["GOOGLE_API_KEY"] == "gemini-key"
    assert settings.gemini_api_key == "gemini-key"


def test_get_settings_is_cached():
    assert get_settings() is get_settings()


def test_defaults_match_the_spec():
    settings = build()
    assert settings.model_fast == "gemini-2.5-flash"
    assert settings.model_smart == "gemini-2.5-pro"
    # SPEC: tool loop capped at 5 iterations, history trimmed to 10 turns.
    assert settings.max_tool_iterations == 5
    assert settings.history_turns == 10


def test_model_ids_are_env_overridable(monkeypatch):
    monkeypatch.setenv("MODEL_FAST", "gemini-9.9-flash")
    monkeypatch.setenv("MODEL_SMART", "gemini-9.9-pro")
    settings = build()
    assert settings.model_fast == "gemini-9.9-flash"
    assert settings.model_smart == "gemini-9.9-pro"


def test_unknown_env_vars_are_ignored(monkeypatch):
    # extra="ignore": the shared .env carries frontend vars too, and an unknown
    # name must not crash startup.
    monkeypatch.setenv("SOME_UNRELATED_VAR", "whatever")
    assert build().tavily_api_key == ""
