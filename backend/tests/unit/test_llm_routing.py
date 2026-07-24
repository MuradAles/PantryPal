"""Tier-to-model-id routing in app/llm.py.

Constructing a ChatGoogleGenerativeAI does not call the API — it only builds a
client object — so these assertions cost nothing and never touch the network.
They pin the routing table, which changed once already when the Pro tiers turned
out to be quota-0 on this key.
"""

import pytest

from app import config, llm

DUMMY_KEY = "dummy-key-not-a-real-credential"


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    """Give each test a dummy key, a clean model env, and a cold cache."""
    # Compose injects .env into the container, so the tier vars are cleared here
    # to keep these tests hermetic rather than reading the live deployment.
    for name in ("MODEL_CLASSIFIER", "MODEL_FAST", "MODEL_SMART"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", DUMMY_KEY)
    config.get_settings.cache_clear()
    llm.get_model.cache_clear()
    yield
    config.get_settings.cache_clear()
    llm.get_model.cache_clear()


def test_fast_tier_uses_the_configured_fast_model(monkeypatch):
    monkeypatch.setenv("MODEL_FAST", "fast-model-id")
    assert llm.get_model("fast").model == "fast-model-id"


def test_smart_tier_uses_the_configured_smart_model(monkeypatch):
    monkeypatch.setenv("MODEL_SMART", "smart-model-id")
    assert llm.get_model("smart").model == "smart-model-id"


def test_default_tier_is_fast(monkeypatch):
    # get_model() with no argument must not silently reach for the expensive tier.
    monkeypatch.setenv("MODEL_FAST", "fast-model-id")
    monkeypatch.setenv("MODEL_SMART", "smart-model-id")
    assert llm.get_model().model == "fast-model-id"


def test_tiers_resolve_to_different_models(monkeypatch):
    monkeypatch.setenv("MODEL_FAST", "fast-model-id")
    monkeypatch.setenv("MODEL_SMART", "smart-model-id")
    assert llm.get_model("fast").model != llm.get_model("smart").model


def test_models_are_cached_per_tier():
    # lru_cache keyed by tier: same tier returns the same object, different tiers
    # do not collide.
    assert llm.get_model("fast") is llm.get_model("fast")
    assert llm.get_model("fast") is not llm.get_model("smart")


def test_no_vendor_sdk_import_outside_llm():
    # SPEC: app/llm.py is the only file allowed to name a model provider, and all
    # LLM access goes through LangChain (R5). A vendor SDK import anywhere else
    # is an architecture violation, so assert on absence.
    import pathlib

    app_dir = pathlib.Path(llm.__file__).parent
    offenders = []
    for path in app_dir.glob("*.py"):
        if path.name == "llm.py":
            continue
        source = path.read_text()
        for banned in ("import google.generativeai", "from google.generativeai", "google.genai"):
            if banned in source:
                offenders.append(f"{path.name}: {banned}")
    assert offenders == []


def test_classifier_tier_uses_the_configured_classifier_model(monkeypatch):
    # MODEL_CLASSIFIER was briefly dead config: it was set in .env and read into
    # Settings while llm.Tier was still only ("fast","smart"), so the classifier
    # silently ran on the fast model. Keep this pinned.
    monkeypatch.setenv("MODEL_CLASSIFIER", "classifier-model-id")
    assert llm.get_model("classifier").model == "classifier-model-id"


def test_all_three_tiers_resolve_to_their_own_model(monkeypatch):
    monkeypatch.setenv("MODEL_CLASSIFIER", "classifier-model-id")
    monkeypatch.setenv("MODEL_FAST", "fast-model-id")
    monkeypatch.setenv("MODEL_SMART", "smart-model-id")
    resolved = {tier: llm.get_model(tier).model for tier in ("classifier", "fast", "smart")}
    assert resolved == {
        "classifier": "classifier-model-id",
        "fast": "fast-model-id",
        "smart": "smart-model-id",
    }


def test_unknown_tier_degrades_to_fast(monkeypatch):
    # Documented behavior: a routing bug should degrade to a working answer
    # rather than raising and turning into a 503.
    monkeypatch.setenv("MODEL_FAST", "fast-model-id")
    assert llm.get_model("nonsense-tier").model == "fast-model-id"
