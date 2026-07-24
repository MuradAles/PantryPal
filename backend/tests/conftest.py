"""Shared test fixtures.

No test in this suite may reach a real API. Every model used here is scripted
locally, so the suite costs nothing to run and cannot be made flaky by a
provider outage.
"""

import pytest
from langchain_core.messages import AIMessage

from tests.fakes import ScriptedChatModel


@pytest.fixture
def scripted_model():
    """Return a factory building a ScriptedChatModel from scripted replies."""

    def _build(
        *responses: AIMessage, error: BaseException | None = None
    ) -> ScriptedChatModel:
        return ScriptedChatModel(responses=list(responses), error=error)

    return _build


@pytest.fixture
def patch_model(monkeypatch):
    """Return a function that makes app.llm.get_model hand back a scripted model.

    get_model is lru_cache'd, so the cache is cleared on both sides of the swap;
    a leftover entry would otherwise leak a real ChatGoogleGenerativeAI into the
    next test, or a fake into the running app.
    """
    from app import llm

    def _patch(model: ScriptedChatModel) -> ScriptedChatModel:
        llm.get_model.cache_clear()
        monkeypatch.setattr(llm, "get_model", lambda tier="fast": model)
        return model

    yield _patch
    llm.get_model.cache_clear()


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Point the settings singleton at a throwaway SQLite file for one test."""
    from app import config

    path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    config.get_settings.cache_clear()
    yield path
    config.get_settings.cache_clear()
