import functools
import os

import pytest

import app as app_module
from agents import workflow
from tests.fakes import ScriptedChatModel

# Settings that would otherwise leak in from the developer's shell or .env.
_ENV_PREFIXES = ("OLLAMA_", "APP_")
_ENV_NAMES = {
    "MAX_CONCURRENT_RUNS",
    "RUN_TIME_BUDGET_SECONDS",
    "TRUSTED_PROXIES",
    "FLASK_DEBUG",
}


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """Run every test without the developer's settings or .env file.

    Settings are read once, so a test that changes the environment calls
    ``reload_settings()`` afterwards.
    """
    for name in list(os.environ):
        if name.startswith(_ENV_PREFIXES) or name in _ENV_NAMES:
            monkeypatch.delenv(name)
    monkeypatch.setattr(app_module, "load_dotenv", lambda *_a, **_k: False)
    workflow.reload_settings()
    yield
    workflow.get_settings.cache_clear()


@pytest.fixture
def fake():
    """A scripted model that runs Coder, then Reviewer, then finishes."""
    return ScriptedChatModel(routes=["Coder", "Reviewer", "FINISH"])


@pytest.fixture
def make_app(monkeypatch, fake):
    """Build the Flask app with every workflow call answered by ``fake``."""

    def factory(**config):
        monkeypatch.setattr(
            app_module,
            "stream_workflow",
            functools.partial(workflow.stream_workflow, llm=fake),
        )
        monkeypatch.setattr(
            app_module,
            "run_workflow",
            functools.partial(workflow.run_workflow, llm=fake),
        )
        return app_module.create_app({"TESTING": True, **config})

    return factory


@pytest.fixture
def client(make_app):
    return make_app().test_client()
