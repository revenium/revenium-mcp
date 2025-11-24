"""Helper functions for session operations.

This module contains helper functions extracted from the main session manager
to maintain compliance with the 300-line limit per module.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from loguru import logger


def generate_unique_session_id() -> str:
    """Generate a unique session ID.

    Returns:
        Unique session ID string
    """
    return str(uuid.uuid4())


def create_session_info(
    session_id: str,
    client_info: Optional[Dict[str, Any]],
    protocol_version: Optional[str],
    max_idle_time: timedelta,
):
    """Create a new session info object."""
    # Import here to avoid circular imports
    from .session_manager import SessionInfo

    return SessionInfo(
        session_id=session_id,
        client_info=client_info,
        protocol_version=protocol_version,
        max_idle_time=max_idle_time,
    )


def check_session_limit(sessions: Dict, max_sessions: int, cleanup_func) -> None:
    """Check if session limit is reached and clean up if needed."""
    if len(sessions) >= max_sessions:
        cleanup_func()

        if len(sessions) >= max_sessions:
            # Import here to avoid circular imports
            from .error_handling import create_internal_error

            raise create_internal_error(
                message="Maximum number of sessions reached", context={"max_sessions": max_sessions}
            )


def get_active_sessions(sessions: Dict) -> List:
    """Get list of active (non-expired) sessions."""
    active_sessions = []
    for session in sessions.values():
        if not session.is_expired():
            active_sessions.append(session)
    return active_sessions


def cleanup_expired_sessions(sessions: Dict, stats_counters: Dict) -> int:
    """Clean up expired sessions and update statistics."""
    expired_session_ids = []

    for session_id, session in sessions.items():
        if session.is_expired():
            expired_session_ids.append(session_id)

    # Remove expired sessions
    for session_id in expired_session_ids:
        del sessions[session_id]
        stats_counters["sessions_expired"] += 1
        logger.debug(f"Cleaned up expired session: {session_id}")

    if expired_session_ids:
        logger.info(f"Cleaned up {len(expired_session_ids)} expired sessions")

    return len(expired_session_ids)


def should_perform_cleanup(last_cleanup: datetime, cleanup_interval: timedelta) -> bool:
    """Check if cleanup should be performed based on interval."""
    return datetime.now() - last_cleanup >= cleanup_interval


def build_session_stats(
    sessions: Dict,
    max_sessions: int,
    sessions_created: int,
    sessions_expired: int,
    sessions_terminated: int,
    default_max_idle_time: timedelta,
    cleanup_interval: timedelta,
    last_cleanup: datetime,
    session_id_header: str,
) -> Dict[str, Any]:
    """Build session statistics dictionary."""
    active_sessions = get_active_sessions(sessions)

    return {
        "total_sessions": len(sessions),
        "active_sessions": len(active_sessions),
        "max_sessions": max_sessions,
        "sessions_created": sessions_created,
        "sessions_expired": sessions_expired,
        "sessions_terminated": sessions_terminated,
        "default_max_idle_time_seconds": default_max_idle_time.total_seconds(),
        "cleanup_interval_seconds": cleanup_interval.total_seconds(),
        "last_cleanup": last_cleanup.isoformat(),
        "session_id_header": session_id_header,
    }


def get_session_from_headers(sessions: Dict, headers: Dict[str, str], session_id_header: str):
    """Get session from HTTP headers."""
    session_id = headers.get(session_id_header)
    if session_id and session_id in sessions:
        return sessions[session_id]
    return None


def create_session_headers(session_id: str, session_id_header: str) -> Dict[str, str]:
    """Create HTTP headers for session."""
    return {session_id_header: session_id}


def validate_session_exists(sessions: Dict, session_id: str) -> bool:
    """Validate that a session exists and is active."""
    if session_id not in sessions:
        return False

    session = sessions[session_id]
    if session.is_expired():
        return False

    # Touch session to update last accessed time
    session.touch()
    return True


def terminate_session_by_id(sessions: Dict, session_id: str, stats_counters: Dict) -> bool:
    """Terminate a session by ID."""
    if session_id not in sessions:
        return False

    del sessions[session_id]
    stats_counters["sessions_terminated"] += 1
    logger.info(f"Terminated session: {session_id}")
    return True


def expire_session_by_id(sessions: Dict, session_id: str, stats_counters: Dict) -> bool:
    """Mark a session as expired and remove it."""
    if session_id not in sessions:
        return False

    del sessions[session_id]
    stats_counters["sessions_expired"] += 1
    logger.debug(f"Expired session: {session_id}")
    return True
