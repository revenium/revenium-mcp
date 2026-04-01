"""Unit tests for mcp_compliance capability_operations_helpers.

Covers helper functions for capability registration, updates, enable/disable,
MCP format conversion, server info updates, change listeners, and stats.
"""

import pytest
from unittest.mock import MagicMock
from dataclasses import dataclass, field
from typing import Any, Dict

from src.revenium_mcp_server.mcp_compliance.capability_operations_helpers import (
    add_change_listener_to_list,
    build_capability_stats,
    disable_capability_in_dict,
    enable_capability_in_dict,
    get_capabilities_mcp_format,
    get_default_capabilities,
    notify_capability_changed,
    register_capability_in_dict,
    remove_change_listener_from_list,
    send_notification,
    update_capability_in_dict,
    update_server_info_fields,
)


@dataclass
class FakeCapability:
    """Minimal capability object for testing."""
    name: str
    enabled: bool = True
    sub_capabilities: Dict[str, bool] = field(default_factory=dict)

    def to_mcp_format(self):
        return self.sub_capabilities if self.sub_capabilities else {}


class TestGetDefaultCapabilities:
    """Test default capabilities construction."""

    def test_returns_expected_capability_names(self):
        """Default capabilities include tools, resources, prompts, logging."""
        caps = get_default_capabilities()
        assert "tools" in caps
        assert "resources" in caps
        assert "prompts" in caps
        assert "logging" in caps


class TestRegisterCapabilityInDict:
    """Test registering capabilities into a dictionary."""

    def test_register_new_capability(self):
        """New capability is added to the dictionary."""
        caps = {}
        cap = FakeCapability(name="custom")
        result = register_capability_in_dict(caps, cap)
        assert result is True
        assert "custom" in caps

    def test_register_overwrites_existing(self):
        """Registering an existing name replaces it."""
        old = FakeCapability(name="tools", enabled=False)
        new = FakeCapability(name="tools", enabled=True)
        caps = {"tools": old}
        register_capability_in_dict(caps, new)
        assert caps["tools"].enabled is True


class TestUpdateCapabilityInDict:
    """Test updating capabilities in a dictionary."""

    def test_update_existing_field(self):
        """Updating a known field returns True."""
        caps = {"tools": FakeCapability(name="tools", enabled=True)}
        result = update_capability_in_dict(caps, "tools", enabled=False)
        assert result is True
        assert caps["tools"].enabled is False

    def test_update_nonexistent_capability(self):
        """Updating a missing capability returns False."""
        result = update_capability_in_dict({}, "missing", enabled=True)
        assert result is False

    def test_update_unknown_field_ignored(self):
        """Unknown fields are silently ignored but don't prevent success."""
        caps = {"tools": FakeCapability(name="tools")}
        result = update_capability_in_dict(caps, "tools", nonexistent_field="val")
        # Returns True because the capability was found, even if field was unknown
        assert result is True


class TestEnableDisableCapability:
    """Test enabling and disabling capabilities."""

    def test_enable_existing(self):
        """Enabling an existing capability sets enabled=True."""
        caps = {"tools": FakeCapability(name="tools", enabled=False)}
        assert enable_capability_in_dict(caps, "tools") is True
        assert caps["tools"].enabled is True

    def test_enable_nonexistent(self):
        """Enabling a missing capability returns False."""
        assert enable_capability_in_dict({}, "missing") is False

    def test_disable_existing(self):
        """Disabling an existing capability sets enabled=False."""
        caps = {"tools": FakeCapability(name="tools", enabled=True)}
        assert disable_capability_in_dict(caps, "tools") is True
        assert caps["tools"].enabled is False

    def test_disable_nonexistent(self):
        """Disabling a missing capability returns False."""
        assert disable_capability_in_dict({}, "missing") is False


class TestGetCapabilitiesMCPFormat:
    """Test MCP format conversion."""

    def test_only_enabled_capabilities_included(self):
        """Disabled capabilities are excluded from MCP format."""
        caps = {
            "tools": FakeCapability(name="tools", enabled=True, sub_capabilities={"listChanged": True}),
            "prompts": FakeCapability(name="prompts", enabled=False),
        }
        mcp = get_capabilities_mcp_format(caps)
        assert "tools" in mcp
        assert "prompts" not in mcp


class TestUpdateServerInfoFields:
    """Test server info field updates."""

    def test_update_known_field(self):
        """Known fields are updated and returns True."""
        info = MagicMock()
        info.name = "old"
        result = update_server_info_fields(info, name="new")
        assert result is True

    def test_update_unknown_field(self):
        """Unknown fields are skipped, returns False if no valid fields."""
        info = MagicMock(spec=[])  # no attributes
        result = update_server_info_fields(info, missing="val")
        assert result is False


class TestChangeListeners:
    """Test adding and removing change listeners."""

    def test_add_listener(self):
        """Listener is added to the list."""
        listeners = []
        fn = lambda x: x
        add_change_listener_to_list(listeners, fn)
        assert fn in listeners

    def test_add_duplicate_listener_noop(self):
        """Adding the same listener twice doesn't duplicate it."""
        listeners = []
        fn = lambda x: x
        add_change_listener_to_list(listeners, fn)
        add_change_listener_to_list(listeners, fn)
        assert len(listeners) == 1

    def test_remove_listener(self):
        """Listener is removed from the list."""
        fn = lambda x: x
        listeners = [fn]
        remove_change_listener_from_list(listeners, fn)
        assert fn not in listeners

    def test_remove_absent_listener_noop(self):
        """Removing a listener not in the list does nothing."""
        listeners = []
        remove_change_listener_from_list(listeners, lambda x: x)
        assert listeners == []


class TestNotifyCapabilityChanged:
    """Test async notification of capability changes."""

    @pytest.mark.asyncio
    async def test_listeners_called_with_capability_name(self):
        """All listeners receive the capability name."""
        called_with = []
        listeners = [lambda name: called_with.append(name)]
        await notify_capability_changed(listeners, "tools", {})
        assert called_with == ["tools"]

    @pytest.mark.asyncio
    async def test_listener_exception_does_not_stop_others(self):
        """A failing listener doesn't prevent other listeners from running."""
        results = []

        def good_listener(name):
            results.append(name)

        def bad_listener(name):
            raise RuntimeError("boom")

        await notify_capability_changed([bad_listener, good_listener], "tools", {})
        assert results == ["tools"]

    @pytest.mark.asyncio
    async def test_notification_func_called(self):
        """MCP notification function is called for matching capability."""
        called = []

        async def notify_tools():
            called.append("tools")

        await notify_capability_changed([], "tools", {"tools": notify_tools})
        assert called == ["tools"]

    @pytest.mark.asyncio
    async def test_notification_func_exception_handled(self):
        """Failing notification function doesn't raise."""
        async def bad_notify():
            raise RuntimeError("notify failed")

        # Should not raise
        await notify_capability_changed([], "tools", {"tools": bad_notify})


class TestSendNotification:
    """Test the send_notification helper."""

    @pytest.mark.asyncio
    async def test_calls_send_func(self):
        """send_notification calls the provided async function."""
        called = []

        async def func():
            called.append(True)

        await send_notification("tools", func)
        assert called == [True]

    @pytest.mark.asyncio
    async def test_handles_send_func_exception(self):
        """send_notification catches exceptions from send_func."""
        async def failing_func():
            raise RuntimeError("send failed")

        # Should not raise
        await send_notification("tools", failing_func)


class TestBuildCapabilityStats:
    """Test capability statistics building."""

    def test_counts_enabled_and_disabled(self):
        """Stats accurately count enabled and disabled capabilities."""
        caps = {
            "tools": FakeCapability(name="tools", enabled=True, sub_capabilities={"a": True}),
            "prompts": FakeCapability(name="prompts", enabled=False),
        }
        stats = build_capability_stats(caps)
        assert stats["total_capabilities"] == 2
        assert stats["enabled_capabilities"] == 1
        assert stats["disabled_capabilities"] == 1
        assert "tools" in stats["capabilities_by_status"]["enabled"]
        assert "prompts" in stats["capabilities_by_status"]["disabled"]

    def test_sub_capabilities_counted(self):
        """Sub-capabilities count is tracked per capability."""
        caps = {
            "tools": FakeCapability(name="tools", sub_capabilities={"a": True, "b": False}),
        }
        stats = build_capability_stats(caps)
        assert stats["sub_capabilities_count"]["tools"] == 2
