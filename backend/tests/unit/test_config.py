"""Settings parsing, especially the two accepted spellings of the Tavily key.

The supplied .env spells it TRAVILY_API_KEY. Config accepts both so a corrected
.env later does not silently disable search.
"""

import pytest

from app import config
from app.config import Settings, get_settings

# Every var Settings reads. All of them are cleared before each test: compose
# passes .env into the container, so without this the "default" tests would be
# reading the running deployment's values and would keep passing even if the
# declared defaults in config.py were changed to something broken.
SETTINGS_VARS = [
    "TAVILY_API_KEY",
    "TRAVILY_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "MODEL_CLASSIFIER",
    "MODEL_FAST",
    "MODEL_SMART",
    "DATABASE_PATH",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Strip every settings var and reset the settings cache around each test."""
    for name in SETTINGS_VARS:
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
    # SPEC: tool loop capped at 5 iterations, history trimmed to 10 turns.
    assert settings.max_tool_iterations == 5
    assert settings.history_turns == 10
    assert settings.database_path == "/data/pantrypal.db"


def test_no_default_model_is_a_pro_tier():
    # Every Pro tier is quota-0 on this AI Studio key, so a Pro default would
    # make a fresh clone 429 on the first request. Asserting on the absence of
    # "-pro" survives the next model rename in a way pinning exact ids does not.
    settings = build()
    tiers = [settings.model_classifier, settings.model_fast, settings.model_smart]
    assert [t for t in tiers if "-pro" in t] == []


def test_routing_has_something_to_route_between():
    """The fast and smart tiers must differ or the routing is decoration.

    Originally asserted three distinct ids. That is now wrong: the deployment
    runs two models on purpose, with the classifier sharing the cheap tier. What
    actually has to hold is that a hard question reaches a stronger model than a
    simple one — if fast and smart are equal, the cost/quality tradeoff the
    product was asked for silently does nothing.
    """
    settings = build()
    assert settings.model_fast != settings.model_smart


def test_the_backup_is_a_different_model_from_the_primary():
    """Free-tier daily caps are per model id, so a same-id backup buys nothing."""
    settings = build()
    assert settings.model_backup != settings.model_smart


def test_model_ids_are_env_overridable(monkeypatch):
    monkeypatch.setenv("MODEL_CLASSIFIER", "override-classifier")
    monkeypatch.setenv("MODEL_FAST", "override-fast")
    monkeypatch.setenv("MODEL_SMART", "override-smart")
    settings = build()
    assert settings.model_classifier == "override-classifier"
    assert settings.model_fast == "override-fast"
    assert settings.model_smart == "override-smart"


def test_unknown_env_vars_are_ignored(monkeypatch):
    # extra="ignore": the shared .env carries frontend vars too, and an unknown
    # name must not crash startup.
    monkeypatch.setenv("SOME_UNRELATED_VAR", "whatever")
    assert build().tavily_api_key == ""
