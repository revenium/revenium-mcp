"""Resource class definitions for MCP compliance.

This module contains the core resource classes extracted from the main resources module
to maintain compliance with the 300-line limit per module.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger


class ResourceType(Enum):
    """Types of resources available in the MCP server."""

    ANALYTICS = "analytics"
    TRANSACTIONS = "transactions"
    ALERTS = "alerts"
    REPORTS = "reports"
    DASHBOARDS = "dashboards"


class ResourceMimeType(Enum):
    """MIME types supported by resources."""

    JSON = "application/json"
    HTML = "text/html"
    MARKDOWN = "text/markdown"
    TEXT = "text/plain"
    CSV = "text/csv"


@dataclass
class MCPResource:
    """Represents an MCP resource with metadata and content loading capabilities."""

    uri: str
    name: str
    description: str
    mime_type: ResourceMimeType
    resource_type: ResourceType
    annotations: Dict[str, Any] = field(default_factory=dict)
    last_modified: Optional[datetime] = None
    size_bytes: Optional[int] = None
    version: Optional[str] = None

    def __post_init__(self):
        """Initialize default values after dataclass creation."""
        if self.last_modified is None:
            self.last_modified = datetime.now()
        if self.version is None:
            self.version = "1.0"

    def to_mcp_resource_dict(self) -> Dict[str, Any]:
        """Convert to MCP resource dictionary format.

        Returns:
            MCP-compatible resource dictionary
        """
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mime_type.value,
            "annotations": self.annotations,
        }

    async def load_content(self, content_provider) -> Any:
        """Load resource content using the provided content provider.

        Args:
            content_provider: Function to load content for this resource

        Returns:
            Resource content
        """
        try:
            content = await content_provider(self)

            # Update metadata after successful load
            self.last_modified = datetime.now()

            return content
        except Exception as e:
            logger.error(f"Failed to load content for resource {self.uri}: {e}")
            raise


@dataclass
class ResourceSubscription:
    """Represents a subscription to resource change notifications."""

    uri: str
    subscriber_id: str
    created_at: datetime = field(default_factory=datetime.now)
    last_notification: Optional[datetime] = None
    notification_count: int = 0

    def should_notify(self, resource: MCPResource) -> bool:
        """Check if subscriber should be notified of resource changes.

        Args:
            resource: Resource that changed

        Returns:
            True if notification should be sent
        """
        # For now, always notify on changes
        # In a real implementation, this could check:
        # - Time since last notification
        # - Resource change significance
        # - Subscriber preferences
        return True

    def mark_notified(self):
        """Mark that notification was sent."""
        self.last_notification = datetime.now()
        self.notification_count += 1
