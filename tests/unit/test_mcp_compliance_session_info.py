"""Unit tests for mcp_compliance.session_info module.

Tests the SessionInfo dataclass including expiry detection, session data
management, and serialization.
"""

from datetime import datetime, timedelta

from src.revenium_mcp_server.mcp_compliance.session_info import SessionInfo


class TestSessionInfoExpiry:
    """Test session expiry behavior."""

    def test_active_session_is_not_expired(self):
        """A freshly created session should not be expired."""
        session = SessionInfo(session_id="s1")
        assert not session.is_expired()

    def test_inactive_session_is_expired(self):
        """A deactivated session should be expired regardless of time."""
        session = SessionInfo(session_id="s1")
        session.is_active = False
        assert session.is_expired()

    def test_idle_session_past_max_idle_time_is_expired(self):
        """Session that exceeds max idle time should be expired."""
        session = SessionInfo(
            session_id="s1",
            max_idle_time=timedelta(seconds=1),
        )
        # Force last_accessed far in the past
        session.last_accessed = datetime.now() - timedelta(seconds=10)
        assert session.is_expired()

    def test_session_within_idle_time_is_not_expired(self):
        """Session within idle time should not be expired."""
        session = SessionInfo(
            session_id="s1",
            max_idle_time=timedelta(hours=2),
        )
        assert not session.is_expired()


class TestSessionInfoTouch:
    """Test the touch method that refreshes session access time."""

    def test_touch_increments_request_count(self):
        """Touching a session should increment its request count."""
        session = SessionInfo(session_id="s1")
        assert session.request_count == 0
        session.touch()
        session.touch()
        assert session.request_count == 2

    def test_touch_refreshes_last_accessed(self):
        """Touching a session should update last_accessed to recent time."""
        session = SessionInfo(session_id="s1")
        old_time = session.last_accessed
        session.last_accessed = datetime.now() - timedelta(minutes=30)
        session.touch()
        assert session.last_accessed > old_time - timedelta(seconds=1)


class TestSessionInfoDataStorage:
    """Test session data get/set/remove operations."""

    def test_set_and_get_data(self):
        """Data stored via set_data is retrievable via get_data."""
        session = SessionInfo(session_id="s1")
        session.set_data("user", "alice")
        assert session.get_data("user") == "alice"

    def test_get_data_default(self):
        """get_data returns default when key is absent."""
        session = SessionInfo(session_id="s1")
        assert session.get_data("missing", "fallback") == "fallback"

    def test_remove_data_returns_value_and_clears(self):
        """remove_data returns the removed value and key is no longer present."""
        session = SessionInfo(session_id="s1")
        session.set_data("temp", 42)
        removed = session.remove_data("temp")
        assert removed == 42
        assert session.get_data("temp") is None

    def test_remove_data_missing_key_returns_none(self):
        """remove_data on a missing key returns None."""
        session = SessionInfo(session_id="s1")
        assert session.remove_data("nope") is None


class TestSessionInfoToDict:
    """Test serialization of SessionInfo."""

    def test_to_dict_contains_expected_keys(self):
        """to_dict output contains all expected fields."""
        session = SessionInfo(
            session_id="s1",
            client_info={"name": "test-client"},
            protocol_version="2025-06-18",
        )
        session.set_data("key1", "val1")
        d = session.to_dict()

        assert d["session_id"] == "s1"
        assert d["client_info"] == {"name": "test-client"}
        assert d["protocol_version"] == "2025-06-18"
        assert d["is_active"] is True
        assert d["request_count"] == 0
        assert "key1" in d["data_keys"]
        assert isinstance(d["created_at"], str)
        assert isinstance(d["max_idle_time_seconds"], float)

    def test_to_dict_reflects_expired_status(self):
        """to_dict is_expired field reflects actual expiry state."""
        session = SessionInfo(session_id="s1")
        session.is_active = False
        d = session.to_dict()
        assert d["is_expired"] is True
