"""Unit tests for mcp_compliance session_manager module.

Tests MCPSessionManager including session CRUD, header-based lookups,
expiry, data storage, and statistics.
"""

import pytest
from datetime import timedelta

from src.revenium_mcp_server.mcp_compliance.session_manager import MCPSessionManager


@pytest.fixture
def mgr():
    """Create a fresh MCPSessionManager."""
    return MCPSessionManager()


class TestSessionCreation:
    """Test session creation behavior."""

    def test_create_session_returns_session_info(self, mgr):
        """Created session has a valid session_id and is stored."""
        session = mgr.create_session(
            client_info={"name": "test"},
            protocol_version="2025-06-18",
        )
        assert session.session_id in mgr.sessions
        assert session.client_info == {"name": "test"}
        assert mgr.sessions_created == 1

    def test_create_session_with_custom_idle_time(self, mgr):
        """Custom idle time is applied to the session."""
        session = mgr.create_session(max_idle_time=timedelta(minutes=30))
        assert session.max_idle_time == timedelta(minutes=30)

    def test_create_session_uses_default_idle_time(self, mgr):
        """Default idle time is used when none specified."""
        session = mgr.create_session()
        assert session.max_idle_time == mgr.default_max_idle_time


class TestSessionRetrieval:
    """Test session lookup operations."""

    def test_get_existing_session(self, mgr):
        """Getting an active session returns it and touches it."""
        session = mgr.create_session()
        retrieved = mgr.get_session(session.session_id)
        assert retrieved is not None
        assert retrieved.session_id == session.session_id
        assert retrieved.request_count >= 1  # touched on retrieval

    def test_get_nonexistent_session(self, mgr):
        """Getting a missing session returns None."""
        assert mgr.get_session("nonexistent") is None

    def test_get_expired_session_returns_none(self, mgr):
        """Getting an expired session returns None and cleans it up."""
        session = mgr.create_session()
        session.is_active = False  # force expiry
        result = mgr.get_session(session.session_id)
        assert result is None
        assert session.session_id not in mgr.sessions


class TestSessionValidation:
    """Test session validation."""

    def test_validate_active_session(self, mgr):
        """Active session validates as True."""
        session = mgr.create_session()
        assert mgr.validate_session(session.session_id) is True

    def test_validate_missing_session(self, mgr):
        """Missing session validates as False."""
        assert mgr.validate_session("missing") is False


class TestSessionTermination:
    """Test session termination."""

    def test_terminate_existing_session(self, mgr):
        """Terminating a session removes it and updates counter."""
        session = mgr.create_session()
        result = mgr.terminate_session(session.session_id)
        assert result is True
        assert session.session_id not in mgr.sessions
        assert mgr.sessions_terminated == 1

    def test_terminate_nonexistent_session(self, mgr):
        """Terminating a missing session returns False."""
        assert mgr.terminate_session("missing") is False


class TestSessionHeaders:
    """Test header-based session operations."""

    def test_get_session_from_headers(self, mgr):
        """Session is found via HTTP headers."""
        session = mgr.create_session()
        headers = {mgr.session_id_header: session.session_id}
        result = mgr.get_session_from_headers(headers)
        assert result is not None
        assert result.session_id == session.session_id

    def test_get_session_from_empty_headers(self, mgr):
        """Empty headers return None."""
        assert mgr.get_session_from_headers({}) is None

    def test_create_session_headers(self, mgr):
        """create_session_headers returns correct header dict."""
        headers = mgr.create_session_headers("s1")
        assert headers == {mgr.session_id_header: "s1"}


class TestListActiveSessions:
    """Test listing active sessions."""

    def test_list_returns_only_active(self, mgr):
        """Only active, non-expired sessions are listed."""
        s1 = mgr.create_session()
        s2 = mgr.create_session()
        s2.is_active = False  # force expired

        active = mgr.list_active_sessions()
        active_ids = {s.session_id for s in active}
        assert s1.session_id in active_ids
        assert s2.session_id not in active_ids


class TestCleanupAndStats:
    """Test cleanup and statistics."""

    def test_cleanup_expired_sessions(self, mgr):
        """cleanup_expired_sessions removes expired sessions."""
        s1 = mgr.create_session()
        s1.is_active = False

        count = mgr.cleanup_expired_sessions()
        assert count == 1
        assert s1.session_id not in mgr.sessions

    def test_should_cleanup_returns_false_when_recent(self, mgr):
        """should_cleanup returns False right after init."""
        assert mgr.should_cleanup() is False

    def test_get_session_stats(self, mgr):
        """Session stats contain expected fields."""
        mgr.create_session()
        stats = mgr.get_session_stats()
        assert "total_sessions" in stats
        assert "active_sessions" in stats
        assert "max_sessions" in stats
        assert "sessions_created" in stats
        assert stats["sessions_created"] == 1


class TestSessionData:
    """Test session data storage operations."""

    def test_set_and_get_session_data(self, mgr):
        """Data can be stored and retrieved from a session."""
        session = mgr.create_session()
        result = mgr.set_session_data(session.session_id, "key", "value")
        assert result is True
        assert mgr.get_session_data(session.session_id, "key") == "value"

    def test_set_data_on_missing_session(self, mgr):
        """Setting data on missing session returns False."""
        assert mgr.set_session_data("missing", "key", "val") is False

    def test_get_data_from_missing_session(self, mgr):
        """Getting data from missing session returns default."""
        assert mgr.get_session_data("missing", "key", "default") == "default"

    def test_get_session_details(self, mgr):
        """get_session_details returns dict with session info."""
        session = mgr.create_session()
        details = mgr.get_session_details(session.session_id)
        assert details is not None
        assert details["session_id"] == session.session_id

    def test_get_session_details_missing(self, mgr):
        """get_session_details returns None for missing session."""
        assert mgr.get_session_details("missing") is None
