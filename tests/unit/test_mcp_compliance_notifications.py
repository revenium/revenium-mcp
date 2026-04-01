"""Unit tests for mcp_compliance notifications module.

Tests MCPNotificationManager including notification sending, handler
registration, queue management, and delivery control.
"""

import pytest

from src.revenium_mcp_server.mcp_compliance.notifications import (
    MCPNotificationManager,
    NotificationMessage,
    NotificationType,
)


@pytest.fixture
def mgr():
    """Create a fresh MCPNotificationManager."""
    return MCPNotificationManager()


class TestNotificationMessage:
    """Test NotificationMessage formatting."""

    def test_to_mcp_format_with_params(self):
        """MCP format includes method and params."""
        msg = NotificationMessage(method="notifications/test", params={"key": "val"})
        fmt = msg.to_mcp_format()
        assert fmt["jsonrpc"] == "2.0"
        assert fmt["method"] == "notifications/test"
        assert fmt["params"] == {"key": "val"}

    def test_to_mcp_format_without_params(self):
        """MCP format omits params when None."""
        msg = NotificationMessage(method="notifications/test")
        fmt = msg.to_mcp_format()
        assert "params" not in fmt


class TestHandlerRegistration:
    """Test notification handler registration and unregistration."""

    def test_register_handler(self, mgr):
        """Registered handler appears in handlers list."""
        handler = lambda n: None
        mgr.register_notification_handler("test", handler)
        assert handler in mgr.notification_handlers["test"]

    def test_unregister_handler(self, mgr):
        """Unregistered handler is removed."""
        handler = lambda n: None
        mgr.register_notification_handler("test", handler)
        mgr.unregister_notification_handler("test", handler)
        assert handler not in mgr.notification_handlers.get("test", [])

    def test_unregister_nonexistent_handler(self, mgr):
        """Unregistering a handler that was never registered is harmless."""
        mgr.unregister_notification_handler("test", lambda n: None)

    def test_unregister_from_nonexistent_type(self, mgr):
        """Unregistering from a type that has no handlers is harmless."""
        mgr.unregister_notification_handler("missing_type", lambda n: None)


class TestSendNotification:
    """Test notification sending behavior."""

    @pytest.mark.asyncio
    async def test_send_with_handler(self, mgr):
        """Notification is delivered to registered handler."""
        received = []
        mgr.register_notification_handler("test", lambda n: received.append(n.method))

        msg = NotificationMessage(method="test")
        result = await mgr.send_notification(msg)
        assert result is True
        assert received == ["test"]
        assert mgr.notifications_sent == 1

    @pytest.mark.asyncio
    async def test_send_without_handler_succeeds(self, mgr):
        """Notification without handlers still returns True."""
        msg = NotificationMessage(method="unhandled")
        result = await mgr.send_notification(msg)
        assert result is True

    @pytest.mark.asyncio
    async def test_send_when_delivery_disabled(self, mgr):
        """Notification returns False when delivery is disabled."""
        mgr.disable_delivery()
        msg = NotificationMessage(method="test")
        result = await mgr.send_notification(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_handler_exception_counted_as_failure(self, mgr):
        """Handler that raises causes notification to be counted as failed."""
        mgr.register_notification_handler("test", lambda n: (_ for _ in ()).throw(RuntimeError))

        msg = NotificationMessage(method="test")
        result = await mgr.send_notification(msg)
        # When the only handler fails, processing returns False
        assert result is False
        assert mgr.notifications_failed == 1

    @pytest.mark.asyncio
    async def test_async_handler_called(self, mgr):
        """Async handler is awaited correctly."""
        received = []

        async def async_handler(notification):
            received.append(notification.method)

        mgr.register_notification_handler("test", async_handler)
        msg = NotificationMessage(method="test")
        await mgr.send_notification(msg)
        assert received == ["test"]

    @pytest.mark.asyncio
    async def test_queue_overflow_drops_oldest(self, mgr):
        """When queue is full, oldest notification is dropped."""
        mgr.max_queue_size = 2
        for i in range(3):
            await mgr.send_notification(NotificationMessage(method=f"m{i}"))

        assert len(mgr.notification_queue) == 2
        # First message was dropped
        assert mgr.notification_queue[0].method == "m1"
        assert mgr.notification_queue[1].method == "m2"


class TestConvenienceNotifications:
    """Test convenience notification methods."""

    @pytest.mark.asyncio
    async def test_send_tools_list_changed(self, mgr):
        """send_tools_list_changed sends correct notification type."""
        received = []
        mgr.register_notification_handler(
            NotificationType.TOOLS_LIST_CHANGED.value,
            lambda n: received.append(n.method),
        )
        result = await mgr.send_tools_list_changed()
        assert result is True
        assert received == [NotificationType.TOOLS_LIST_CHANGED.value]

    @pytest.mark.asyncio
    async def test_send_resource_updated(self, mgr):
        """send_resource_updated includes URI in params."""
        received = []
        mgr.register_notification_handler(
            NotificationType.RESOURCE_UPDATED.value,
            lambda n: received.append(n.params),
        )
        await mgr.send_resource_updated("revenium://test", changes={"field": "new"})
        assert received[0]["uri"] == "revenium://test"
        assert received[0]["changes"] == {"field": "new"}

    @pytest.mark.asyncio
    async def test_send_log_message(self, mgr):
        """send_log_message includes level, message, and optional logger."""
        received = []
        mgr.register_notification_handler(
            NotificationType.LOG_MESSAGE.value,
            lambda n: received.append(n.params),
        )
        await mgr.send_log_message("INFO", "hello", logger_name="test")
        assert received[0]["level"] == "INFO"
        assert received[0]["message"] == "hello"
        assert received[0]["logger"] == "test"


class TestDeliveryControl:
    """Test enable/disable delivery and queue management."""

    def test_enable_disable_delivery(self, mgr):
        """Delivery can be toggled on and off."""
        mgr.disable_delivery()
        assert mgr.delivery_enabled is False
        mgr.enable_delivery()
        assert mgr.delivery_enabled is True

    def test_clear_queue(self, mgr):
        """clear_queue empties the queue and returns count."""
        mgr.notification_queue = [
            NotificationMessage(method="a"),
            NotificationMessage(method="b"),
        ]
        count = mgr.clear_queue()
        assert count == 2
        assert len(mgr.notification_queue) == 0


class TestQueueStatus:
    """Test queue status reporting."""

    def test_get_queue_status(self, mgr):
        """Queue status contains expected fields."""
        status = mgr.get_queue_status()
        assert status["queue_size"] == 0
        assert status["delivery_enabled"] is True
        assert status["notifications_sent"] == 0
        assert status["last_notification_time"] is None

    @pytest.mark.asyncio
    async def test_get_queue_status_after_send(self, mgr):
        """Queue status updates after sending notifications."""
        await mgr.send_notification(NotificationMessage(method="test"))
        status = mgr.get_queue_status()
        assert status["queue_size"] == 1
        assert status["notifications_sent"] == 1
        assert status["last_notification_time"] is not None


class TestGetRecentNotifications:
    """Test recent notification retrieval."""

    def test_empty_queue(self, mgr):
        """Empty queue returns empty list."""
        assert mgr.get_recent_notifications() == []

    @pytest.mark.asyncio
    async def test_returns_recent_with_limit(self, mgr):
        """Returns at most `limit` recent notifications."""
        for i in range(5):
            await mgr.send_notification(NotificationMessage(method=f"m{i}"))

        recent = mgr.get_recent_notifications(limit=3)
        assert len(recent) == 3
        assert recent[0]["method"] == "m2"
        assert recent[2]["method"] == "m4"

    @pytest.mark.asyncio
    async def test_returns_all_when_fewer_than_limit(self, mgr):
        """Returns all notifications when queue has fewer than limit."""
        await mgr.send_notification(NotificationMessage(method="m0"))
        recent = mgr.get_recent_notifications(limit=10)
        assert len(recent) == 1
