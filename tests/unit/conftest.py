"""Shared fixtures for unit tests."""
from datetime import datetime, timezone

import pytest

import src.revenium_mcp_server.date_parser
from src.revenium_mcp_server.client import get_shared_http_client
from src.revenium_mcp_server.common.recent_writes import RECENT_WRITES


@pytest.fixture(autouse=True)
def _isolate_auth_mode(monkeypatch):
    """Keep unit tests deterministic regardless of developer-machine env.

    Runtime load_dotenv calls (server startup, UCM factory) or shell exports
    can inject AUTH_MODE mid-suite, flipping tools into clerk/api_key mode
    and breaking tests that rely on the env-mode default. Tests that need a
    specific mode set it explicitly via monkeypatch.
    """
    monkeypatch.delenv("AUTH_MODE", raising=False)


@pytest.fixture(autouse=True)
def _forget_recent_writes():
    """Tests reuse record ids with different stored records, so no update may see another test's write."""
    RECENT_WRITES.clear()
    yield
    RECENT_WRITES.clear()


@pytest.fixture(autouse=True)
def _unshadow_the_shared_http_client():
    """Give the next test the shared HTTP client's own methods back.

    Every ReveniumClient shares one cached httpx.AsyncClient. When a test
    monkeypatches ``request`` on that instance, the undo stores the original
    bound method on the instance, and that copy hides any later class-level
    patch of httpx.AsyncClient (the recorder in test_dry_run_guard.py).
    The sweep runs at setup because that undo happens in monkeypatch's own
    teardown, after any teardown code here.
    """
    if get_shared_http_client.cache_info().currsize > 0:
        shared = get_shared_http_client()
        shadowing = [name for name in vars(shared) if callable(getattr(type(shared), name, None))]
        for name in shadowing:
            delattr(shared, name)
    yield


class _FrozenUtcClock(datetime):
    """A datetime whose now() is whatever the test last set ``current`` to."""

    current = datetime(2026, 10, 15, 15, 30, 45, 123456, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current


@pytest.fixture
def frozen_utc_clock(monkeypatch):
    """Freeze the date parser's clock at Thursday 2026-10-15 15:30:45.123456 UTC.

    Set ``frozen_utc_clock.current`` to move it. Only the ``src.`` module is
    patched: ``revenium_mcp_server.date_parser`` without the prefix is a
    different module object.
    """
    _FrozenUtcClock.current = datetime(2026, 10, 15, 15, 30, 45, 123456, tzinfo=timezone.utc)
    monkeypatch.setattr(src.revenium_mcp_server.date_parser, "datetime", _FrozenUtcClock)
    return _FrozenUtcClock


ALERT_OWNER_EMAIL = "alert.owner@example.test"


@pytest.fixture
def alert_owner_email(monkeypatch):
    """A default recipient for a generic alert create that names none, which is otherwise refused."""
    monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", ALERT_OWNER_EMAIL)
    return ALERT_OWNER_EMAIL


@pytest.fixture
def placeholder_notification_email(monkeypatch, tmp_path):
    """REVENIUM_DEFAULT_EMAIL holds the placeholder and no other layer holds an address."""
    from src.revenium_mcp_server.config_cache import _default_cache
    from src.revenium_mcp_server.config_store import ConfigurationStore

    monkeypatch.setattr(_default_cache, "cache_file", tmp_path / "no-cache.json")
    monkeypatch.setattr(ConfigurationStore, "_discovered_value", lambda self, *args: None)
    monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "dummy@email.com")
