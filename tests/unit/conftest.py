"""Shared fixtures for unit tests."""
from datetime import datetime, timezone

import pytest

import src.revenium_mcp_server.date_parser
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
