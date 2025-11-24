"""MCP Notification System.

This module implements the MCP notification system for sending change
notifications to clients according to the MCP specification.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from .error_handling import create_internal_error


class NotificationType(Enum):
    """Types of MCP notifications."""

    TOOLS_LIST_CHANGED = "notifications/tools/list_changed"
    RESOURCES_LIST_CHANGED = "notifications/resources/list_changed"
    PROMPTS_LIST_CHANGED = "notifications/prompts/list_changed"
    RESOURCE_UPDATED = "notifications/resources/updated"
    LOG_MESSAGE = "notifications/message"


@dataclass
class NotificationMessage:
    """Represents an MCP notification message."""

    method: str
    params: Optional[Dict[str, Any]] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_mcp_format(self) -> Dict[str, Any]:
        """Convert to MCP notification format.

        Returns:
            MCP-compatible notification dictionary
        """
        notification = {"jsonrpc": "2.0", "method": self.method}

        if self.params:
            notification["params"] = self.params

        return notification


class MCPNotificationManager:
    """Manages MCP notifications and delivery."""

    def __init__(self):
        """Initialize the notification manager."""
        self.notification_handlers: Dict[str, List[Callable]] = {}
        self.notification_queue: List[NotificationMessage] = []
        self.max_queue_size = 1000
        self.delivery_enabled = True

        # Statistics
        self.notifications_sent = 0
        self.notifications_failed = 0
        self.last_notification_time: Optional[datetime] = None

    def register_notification_handler(self, notification_type: str, handler: Callable) -> None:
        """Register a handler for a specific notification type.

        Args:
            notification_type: Type of notification to handle
            handler: Function to handle the notification
        """
        if notification_type not in self.notification_handlers:
            self.notification_handlers[notification_type] = []

        self.notification_handlers[notification_type].append(handler)
        logger.debug(f"Registered notification handler for: {notification_type}")

    def unregister_notification_handler(self, notification_type: str, handler: Callable) -> None:
        """Unregister a notification handler.

        Args:
            notification_type: Type of notification
            handler: Handler to remove
        """
        if notification_type in self.notification_handlers:
            if handler in self.notification_handlers[notification_type]:
                self.notification_handlers[notification_type].remove(handler)
                logger.debug(f"Unregistered notification handler for: {notification_type}")

    async def send_notification(self, notification: NotificationMessage) -> bool:
        """Send a notification.

        Args:
            notification: Notification to send

        Returns:
            True if notification was sent successfully
        """
        if not self.delivery_enabled:
            logger.debug("Notification delivery is disabled")
            return False

        try:
            # Add to queue if not at capacity
            if len(self.notification_queue) < self.max_queue_size:
                self.notification_queue.append(notification)
            else:
                # Remove oldest notification to make room
                self.notification_queue.pop(0)
                self.notification_queue.append(notification)
                logger.warning("Notification queue full, removed oldest notification")

            # Process notification
            success = await self._process_notification(notification)

            if success:
                self.notifications_sent += 1
                self.last_notification_time = datetime.now()
                logger.debug(f"Sent notification: {notification.method}")
            else:
                self.notifications_failed += 1
                logger.warning(f"Failed to send notification: {notification.method}")

            return success

        except Exception as e:
            self.notifications_failed += 1
            logger.error(f"Error sending notification {notification.method}: {e}")
            return False

    async def _process_notification(self, notification: NotificationMessage) -> bool:
        """Process a notification by calling registered handlers.

        Args:
            notification: Notification to process

        Returns:
            True if processing was successful
        """
        handlers = self.notification_handlers.get(notification.method, [])

        if not handlers:
            # No handlers registered, but this is not necessarily an error
            logger.debug(f"No handlers registered for notification: {notification.method}")
            return True

        success_count = 0

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(notification)
                else:
                    handler(notification)
                success_count += 1
            except Exception as e:
                logger.error(f"Error in notification handler for {notification.method}: {e}")

        # Consider successful if at least one handler succeeded
        return success_count > 0

    async def send_tools_list_changed(self) -> bool:
        """Send tools/list_changed notification.

        Returns:
            True if notification was sent successfully
        """
        notification = NotificationMessage(method=NotificationType.TOOLS_LIST_CHANGED.value)

        return await self.send_notification(notification)

    async def send_resources_list_changed(self) -> bool:
        """Send resources/list_changed notification.

        Returns:
            True if notification was sent successfully
        """
        notification = NotificationMessage(method=NotificationType.RESOURCES_LIST_CHANGED.value)

        return await self.send_notification(notification)

    async def send_prompts_list_changed(self) -> bool:
        """Send prompts/list_changed notification.

        Returns:
            True if notification was sent successfully
        """
        notification = NotificationMessage(method=NotificationType.PROMPTS_LIST_CHANGED.value)

        return await self.send_notification(notification)

    async def send_resource_updated(
        self, uri: str, changes: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Send resource updated notification.

        Args:
            uri: Resource URI that was updated
            changes: Optional details about what changed

        Returns:
            True if notification was sent successfully
        """
        params = {"uri": uri}
        if changes:
            params["changes"] = changes

        notification = NotificationMessage(
            method=NotificationType.RESOURCE_UPDATED.value, params=params
        )

        return await self.send_notification(notification)

    async def send_log_message(
        self, level: str, message: str, logger_name: Optional[str] = None
    ) -> bool:
        """Send log message notification.

        Args:
            level: Log level (DEBUG, INFO, WARNING, ERROR)
            message: Log message
            logger_name: Optional logger name

        Returns:
            True if notification was sent successfully
        """
        params = {"level": level, "message": message, "timestamp": datetime.now().isoformat()}

        if logger_name:
            params["logger"] = logger_name

        notification = NotificationMessage(method=NotificationType.LOG_MESSAGE.value, params=params)

        return await self.send_notification(notification)

    def enable_delivery(self) -> None:
        """Enable notification delivery."""
        self.delivery_enabled = True
        logger.info("Notification delivery enabled")

    def disable_delivery(self) -> None:
        """Disable notification delivery."""
        self.delivery_enabled = False
        logger.info("Notification delivery disabled")

    def clear_queue(self) -> int:
        """Clear the notification queue.

        Returns:
            Number of notifications that were cleared
        """
        count = len(self.notification_queue)
        self.notification_queue.clear()
        logger.info(f"Cleared {count} notifications from queue")
        return count

    def get_queue_status(self) -> Dict[str, Any]:
        """Get notification queue status.

        Returns:
            Dictionary with queue status information
        """
        return {
            "queue_size": len(self.notification_queue),
            "max_queue_size": self.max_queue_size,
            "delivery_enabled": self.delivery_enabled,
            "notifications_sent": self.notifications_sent,
            "notifications_failed": self.notifications_failed,
            "last_notification_time": (
                self.last_notification_time.isoformat() if self.last_notification_time else None
            ),
            "registered_handlers": {
                notification_type: len(handlers)
                for notification_type, handlers in self.notification_handlers.items()
            },
        }

    def get_recent_notifications(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent notifications from the queue.

        Args:
            limit: Maximum number of notifications to return

        Returns:
            List of recent notification dictionaries
        """
        recent = self.notification_queue[-limit:] if self.notification_queue else []

        return [
            {
                "method": notification.method,
                "params": notification.params,
                "timestamp": notification.timestamp.isoformat(),
            }
            for notification in recent
        ]


# Global notification manager instance
notification_manager = MCPNotificationManager()
