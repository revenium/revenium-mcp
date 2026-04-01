"""Unit tests for mcp_compliance session_operations_helpers.

Covers session ID generation, session creation, limit checking, active session
filtering, cleanup, validation, termination, and header-based lookups.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from src.revenium_mcp_server.mcp_compliance.session_operations_helpers import (
    build_session_stats,
    check_session_limit,
    cleanup_expired_sessions,
    create_session_headers,
    create_session_info,
    expire_session_by_id,
    generate_unique_session_id,
    get_active_sessions,
    get_session_from_headers,
    should_perform_cleanup,
    terminate_session_by_id,
    validate_session_exists,
)
from src.revenium_mcp_server.mcp_compliance.session_info import SessionInfo


class TestGenerateUniqueSessionId:
    """Test session ID generation."""

    def test_generates_uuid_string(self):
        """Generated ID is a valid UUID string."""
        sid = generate_unique_session_id()
        assert isinstance(sid, str)
        assert len(sid) == 36  # UUID format: 8-4-4-4-12

    def test_ids_are_unique(self):
        """Multiple calls produce distinct IDs."""
        ids = {generate_unique_session_id() for _ in range(100)}
        assert len(ids) == 100


class TestCreateSessionInfo:
    """Test session info factory function."""

    def test_creates_session_with_provided_values(self):
        """Session info reflects provided parameters."""
        session = create_session_info("s1", {"name": "client"}, "2025-06-18", timedelta(hours=2))
        assert session.session_id == "s1"
        assert session.client_info == {"name": "client"}
        assert session.protocol_version == "2025-06-18"
        assert session.max_idle_time == timedelta(hours=2)


class TestCheckSessionLimit:
    """Test session limit enforcement."""

    def test_no_action_when_under_limit(self):
        """No cleanup or error when session count is below limit."""
        sessions = {"s1": MagicMock()}
        cleanup = MagicMock()
        check_session_limit(sessions, 10, cleanup)
        cleanup.assert_not_called()

    def test_cleanup_called_at_limit(self):
        """Cleanup function is called when at max capacity."""
        sessions = {f"s{i}": MagicMock() for i in range(5)}
        # Cleanup should remove some sessions
        def do_cleanup():
            sessions.pop("s0")

        check_session_limit(sessions, 5, do_cleanup)
        assert "s0" not in sessions

    def test_raises_when_still_at_limit_after_cleanup(self):
        """Raises MCPError when cleanup doesn't free any slots."""
        sessions = {f"s{i}": MagicMock() for i in range(5)}
        cleanup = MagicMock()  # does nothing
        with pytest.raises(Exception, match="Maximum number of sessions"):
            check_session_limit(sessions, 5, cleanup)


class TestGetActiveSessions:
    """Test filtering active sessions."""

    def test_returns_only_non_expired(self):
        """Only sessions where is_expired() returns False are included."""
        active = SessionInfo(session_id="a1")
        expired = SessionInfo(session_id="e1")
        expired.is_active = False

        sessions = {"a1": active, "e1": expired}
        result = get_active_sessions(sessions)
        assert len(result) == 1
        assert result[0].session_id == "a1"


class TestCleanupExpiredSessions:
    """Test expired session cleanup."""

    def test_removes_expired_and_updates_counter(self):
        """Expired sessions are removed and stats counter incremented."""
        expired = SessionInfo(session_id="e1")
        expired.is_active = False
        active = SessionInfo(session_id="a1")

        sessions = {"e1": expired, "a1": active}
        stats = {"sessions_expired": 0}

        count = cleanup_expired_sessions(sessions, stats)
        assert count == 1
        assert "e1" not in sessions
        assert "a1" in sessions
        assert stats["sessions_expired"] == 1

    def test_no_expired_sessions(self):
        """When nothing is expired, returns 0 and sessions untouched."""
        sessions = {"a1": SessionInfo(session_id="a1")}
        stats = {"sessions_expired": 0}
        count = cleanup_expired_sessions(sessions, stats)
        assert count == 0
        assert len(sessions) == 1


class TestShouldPerformCleanup:
    """Test cleanup interval check."""

    def test_true_when_past_interval(self):
        """Returns True when enough time has elapsed."""
        old_time = datetime.now() - timedelta(minutes=20)
        assert should_perform_cleanup(old_time, timedelta(minutes=15)) is True

    def test_false_when_within_interval(self):
        """Returns False when not enough time has elapsed."""
        recent = datetime.now() - timedelta(minutes=5)
        assert should_perform_cleanup(recent, timedelta(minutes=15)) is False


class TestValidateSessionExists:
    """Test session existence validation."""

    def test_valid_active_session(self):
        """Valid active session returns True and gets touched."""
        session = SessionInfo(session_id="s1")
        sessions = {"s1": session}
        assert validate_session_exists(sessions, "s1") is True
        assert session.request_count == 1

    def test_missing_session(self):
        """Missing session returns False."""
        assert validate_session_exists({}, "s1") is False

    def test_expired_session(self):
        """Expired session returns False."""
        session = SessionInfo(session_id="s1")
        session.is_active = False
        assert validate_session_exists({"s1": session}, "s1") is False


class TestTerminateAndExpireSession:
    """Test session termination and expiration."""

    def test_terminate_existing_session(self):
        """Terminating an existing session removes it and updates counter."""
        sessions = {"s1": SessionInfo(session_id="s1")}
        stats = {"sessions_terminated": 0}
        result = terminate_session_by_id(sessions, "s1", stats)
        assert result is True
        assert "s1" not in sessions
        assert stats["sessions_terminated"] == 1

    def test_terminate_nonexistent_session(self):
        """Terminating a missing session returns False."""
        stats = {"sessions_terminated": 0}
        assert terminate_session_by_id({}, "s1", stats) is False

    def test_expire_existing_session(self):
        """Expiring an existing session removes it and updates counter."""
        sessions = {"s1": SessionInfo(session_id="s1")}
        stats = {"sessions_expired": 0}
        result = expire_session_by_id(sessions, "s1", stats)
        assert result is True
        assert "s1" not in sessions
        assert stats["sessions_expired"] == 1

    def test_expire_nonexistent_session(self):
        """Expiring a missing session returns False."""
        stats = {"sessions_expired": 0}
        assert expire_session_by_id({}, "s1", stats) is False


class TestSessionHeaders:
    """Test header-based session operations."""

    def test_get_session_from_headers_found(self):
        """Session is returned when header contains valid session ID."""
        session = SessionInfo(session_id="s1")
        sessions = {"s1": session}
        result = get_session_from_headers(sessions, {"X-Session": "s1"}, "X-Session")
        assert result is session

    def test_get_session_from_headers_not_found(self):
        """Returns None when header has no matching session."""
        result = get_session_from_headers({}, {"X-Session": "s1"}, "X-Session")
        assert result is None

    def test_get_session_from_headers_no_header(self):
        """Returns None when header key is absent."""
        result = get_session_from_headers({"s1": MagicMock()}, {}, "X-Session")
        assert result is None

    def test_create_session_headers(self):
        """create_session_headers returns correct header dict."""
        headers = create_session_headers("s1", "Mcp-Session-Id")
        assert headers == {"Mcp-Session-Id": "s1"}


class TestBuildSessionStats:
    """Test session statistics building."""

    def test_includes_all_stat_fields(self):
        """Stats dict contains expected keys with correct values."""
        sessions = {"a1": SessionInfo(session_id="a1")}
        stats = build_session_stats(
            sessions=sessions,
            max_sessions=100,
            sessions_created=5,
            sessions_expired=2,
            sessions_terminated=1,
            default_max_idle_time=timedelta(hours=1),
            cleanup_interval=timedelta(minutes=15),
            last_cleanup=datetime.now(),
            session_id_header="Mcp-Session-Id",
        )
        assert stats["total_sessions"] == 1
        assert stats["max_sessions"] == 100
        assert stats["sessions_created"] == 5
        assert stats["sessions_expired"] == 2
        assert stats["sessions_terminated"] == 1
        assert stats["session_id_header"] == "Mcp-Session-Id"
