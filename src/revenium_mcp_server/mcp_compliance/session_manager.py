"""MCP Session Management System.

This module implements HTTP session management for MCP servers according
to the MCP specification, including session ID generation, validation,
state management, and cleanup.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from loguru import logger

from .error_handling import (
    MCPError,
    create_internal_error,
)
from .session_info import SessionInfo
from .session_operations_helpers import (
    check_session_limit,
    cleanup_expired_sessions,
    create_session_info,
    generate_unique_session_id,
    should_perform_cleanup,
    terminate_session_by_id,
    validate_session_exists,
)

# SessionInfo class moved to session_info.py


class MCPSessionManager:
    """Manages HTTP sessions for MCP servers."""

    def __init__(self):
        """Initialize the session manager."""
        self.sessions: Dict[str, SessionInfo] = {}
        self.session_id_header = "Mcp-Session-Id"
        self.default_max_idle_time = timedelta(hours=1)
        self.max_sessions = 1000
        self.cleanup_interval = timedelta(minutes=15)
        self.last_cleanup = datetime.now()

        # Statistics
        self.sessions_created = 0
        self.sessions_expired = 0
        self.sessions_terminated = 0

    def generate_session_id(self) -> str:
        """Generate a unique session ID."""
        return generate_unique_session_id()

    def create_session(
        self,
        client_info: Optional[Dict[str, Any]] = None,
        protocol_version: Optional[str] = None,
        max_idle_time: Optional[timedelta] = None,
    ) -> SessionInfo:
        """Create a new session.

        Args:
            client_info: Optional client information
            protocol_version: MCP protocol version
            max_idle_time: Maximum idle time before expiration

        Returns:
            Created session info

        Raises:
            MCPError: If session creation fails
        """
        try:
            # Check session limit
            check_session_limit(self.sessions, self.max_sessions, self._cleanup_expired_sessions)

            # Generate unique session ID
            session_id = self.generate_session_id()
            while session_id in self.sessions:
                session_id = self.generate_session_id()

            # Create and store session
            session = create_session_info(
                session_id,
                client_info,
                protocol_version,
                max_idle_time or self.default_max_idle_time,
            )
            self.sessions[session_id] = session
            self.sessions_created += 1
            logger.info(f"Created session: {session_id}")
            return session

        except MCPError:
            raise
        except Exception as e:
            logger.error(f"Error creating session: {e}")
            raise create_internal_error(message=f"Session creation failed: {str(e)}")

    def get_session(self, session_id: str) -> Optional[SessionInfo]:
        """Get session by ID.

        Args:
            session_id: Session ID

        Returns:
            Session info or None if not found/expired
        """
        if session_id not in self.sessions:
            return None

        session = self.sessions[session_id]

        # Check if session is expired
        if session.is_expired():
            self._expire_session(session_id)
            return None

        # Touch session to update last accessed time
        session.touch()
        return session

    def validate_session(self, session_id: str) -> bool:
        """Validate that a session exists and is active."""
        return validate_session_exists(self.sessions, session_id)

    def terminate_session(self, session_id: str) -> bool:
        """Terminate a session."""
        stats_counters = {"sessions_terminated": self.sessions_terminated}
        result = terminate_session_by_id(self.sessions, session_id, stats_counters)
        self.sessions_terminated = stats_counters["sessions_terminated"]
        return result

    def _expire_session(self, session_id: str) -> bool:
        """Mark a session as expired and remove it.

        Args:
            session_id: Session ID to expire

        Returns:
            True if session was expired
        """
        if session_id not in self.sessions:
            return False

        del self.sessions[session_id]
        self.sessions_expired += 1

        logger.debug(f"Expired session: {session_id}")
        return True

    def get_session_from_headers(self, headers: Dict[str, str]) -> Optional[SessionInfo]:
        """Get session from HTTP headers.

        Args:
            headers: HTTP headers dictionary

        Returns:
            Session info or None if not found
        """
        session_id = headers.get(self.session_id_header)
        if not session_id:
            return None

        return self.get_session(session_id)

    def create_session_headers(self, session_id: str) -> Dict[str, str]:
        """Create HTTP headers for session.

        Args:
            session_id: Session ID

        Returns:
            Dictionary of HTTP headers
        """
        return {self.session_id_header: session_id}

    def list_active_sessions(self) -> List[SessionInfo]:
        """List all active sessions.

        Returns:
            List of active session info objects
        """
        active_sessions = []

        for session in list(self.sessions.values()):
            if not session.is_expired() and session.is_active:
                active_sessions.append(session)
            elif session.is_expired():
                # Clean up expired session
                self._expire_session(session.session_id)

        return active_sessions

    def cleanup_expired_sessions(self) -> int:
        """Clean up expired sessions.

        Returns:
            Number of sessions cleaned up
        """
        return self._cleanup_expired_sessions()

    def _cleanup_expired_sessions(self) -> int:
        """Internal method to clean up expired sessions."""
        stats_counters = {"sessions_expired": self.sessions_expired}
        cleaned_count = cleanup_expired_sessions(self.sessions, stats_counters)
        self.sessions_expired = stats_counters["sessions_expired"]
        self.last_cleanup = datetime.now()
        return cleaned_count

    def should_cleanup(self) -> bool:
        """Check if cleanup should be performed."""
        return should_perform_cleanup(self.last_cleanup, self.cleanup_interval)

    def get_session_stats(self) -> Dict[str, Any]:
        """Get session statistics.

        Returns:
            Dictionary with session statistics
        """
        # Perform cleanup if needed
        if self.should_cleanup():
            self._cleanup_expired_sessions()

        active_sessions = self.list_active_sessions()

        return {
            "total_sessions": len(self.sessions),
            "active_sessions": len(active_sessions),
            "max_sessions": self.max_sessions,
            "sessions_created": self.sessions_created,
            "sessions_expired": self.sessions_expired,
            "sessions_terminated": self.sessions_terminated,
            "default_max_idle_time_seconds": self.default_max_idle_time.total_seconds(),
            "cleanup_interval_seconds": self.cleanup_interval.total_seconds(),
            "last_cleanup": self.last_cleanup.isoformat(),
            "session_id_header": self.session_id_header,
        }

    def get_session_details(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a session.

        Args:
            session_id: Session ID

        Returns:
            Session details dictionary or None if not found
        """
        session = self.get_session(session_id)
        if not session:
            return None

        return session.to_dict()

    def set_session_data(self, session_id: str, key: str, value: Any) -> bool:
        """Set data in a session.

        Args:
            session_id: Session ID
            key: Data key
            value: Data value

        Returns:
            True if data was set successfully
        """
        session = self.get_session(session_id)
        if not session:
            return False

        session.set_data(key, value)
        return True

    def get_session_data(self, session_id: str, key: str, default: Any = None) -> Any:
        """Get data from a session.

        Args:
            session_id: Session ID
            key: Data key
            default: Default value if key not found

        Returns:
            Data value or default
        """
        session = self.get_session(session_id)
        if not session:
            return default

        return session.get_data(key, default)


# Helper methods removed to reduce file size


# Global session manager instance
session_manager = MCPSessionManager()
