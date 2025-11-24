"""Session information class for MCP compliance.

This module contains the SessionInfo class extracted from the main session manager
to maintain compliance with the 300-line limit per module.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Optional


@dataclass
class SessionInfo:
    """Information about an MCP session."""

    session_id: str
    client_info: Optional[Dict[str, Any]] = None
    protocol_version: Optional[str] = None
    max_idle_time: timedelta = field(default_factory=lambda: timedelta(hours=1))

    # Automatically set fields
    created_at: datetime = field(default_factory=datetime.now)
    last_accessed: datetime = field(default_factory=datetime.now)
    is_active: bool = field(default=True)
    request_count: int = field(default=0)

    # Session data storage
    data: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        """Check if session is expired.

        Returns:
            True if session is expired
        """
        if not self.is_active:
            return True

        idle_time = datetime.now() - self.last_accessed
        return idle_time > self.max_idle_time

    def touch(self) -> None:
        """Update last accessed time and increment request count."""
        self.last_accessed = datetime.now()
        self.request_count += 1

    def set_data(self, key: str, value: Any) -> None:
        """Set session data.

        Args:
            key: Data key
            value: Data value
        """
        self.data[key] = value

    def get_data(self, key: str, default: Any = None) -> Any:
        """Get session data.

        Args:
            key: Data key
            default: Default value if key not found

        Returns:
            Data value or default
        """
        return self.data.get(key, default)

    def remove_data(self, key: str) -> Any:
        """Remove session data.

        Args:
            key: Data key to remove

        Returns:
            Removed value or None
        """
        return self.data.pop(key, None)

    def to_dict(self) -> Dict[str, Any]:
        """Convert session info to dictionary.

        Returns:
            Session info dictionary
        """
        return {
            "session_id": self.session_id,
            "client_info": self.client_info,
            "protocol_version": self.protocol_version,
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat(),
            "is_active": self.is_active,
            "is_expired": self.is_expired(),
            "request_count": self.request_count,
            "max_idle_time_seconds": self.max_idle_time.total_seconds(),
            "data_keys": list(self.data.keys()),
        }
