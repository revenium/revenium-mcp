"""Shared fixtures for unit tests."""
import pytest


@pytest.fixture(autouse=True)
def _isolate_auth_mode(monkeypatch):
    """Keep unit tests deterministic regardless of developer-machine env.

    Runtime load_dotenv calls (server startup, UCM factory) or shell exports
    can inject AUTH_MODE mid-suite, flipping tools into clerk/api_key mode
    and breaking tests that rely on the env-mode default. Tests that need a
    specific mode set it explicitly via monkeypatch.
    """
    monkeypatch.delenv("AUTH_MODE", raising=False)
