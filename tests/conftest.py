"""Core regression tests are offline; provider tests explicitly enable mocked AI."""
import pytest


@pytest.fixture(autouse=True)
def isolate_ai_environment(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("PRECEDENT_AI", "0")

    def deny_network(*args, **kwargs):
        raise AssertionError("Tests must mock external HTTP transport")
    monkeypatch.setattr("urllib.request.OpenerDirector.open", deny_network)
