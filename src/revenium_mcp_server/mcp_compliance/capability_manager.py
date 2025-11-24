"""MCP Enhanced Capability Management System.

This module implements enhanced MCP capability declarations and management
including dynamic capability updates, change notifications, and server
metadata management according to the MCP specification.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from ..version import get_package_version
from .capability_operations_helpers import (
    add_change_listener_to_list,
    build_capability_stats,
    get_capabilities_mcp_format,
    get_default_capabilities,
    remove_change_listener_from_list,
    send_notification,
    update_server_info_fields,
)
from .protocol_handler import protocol_handler


@dataclass
class CapabilityInfo:
    """Information about a specific capability."""

    name: str
    enabled: bool = True
    sub_capabilities: Dict[str, bool] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    last_updated: datetime = field(default_factory=datetime.now)
    version: str = "1.0.0"

    def to_mcp_format(self) -> Dict[str, Any]:
        """Convert to MCP capability format.

        Returns:
            MCP-compatible capability dictionary
        """
        if not self.enabled:
            return {}

        if self.sub_capabilities:
            return self.sub_capabilities
        else:
            return {}


@dataclass
class ServerInfo:
    """Server information for MCP initialization."""

    name: str = "revenium-mcp"
    version: str = field(default_factory=get_package_version)
    description: str = "Revenium Platform API MCP Server with AI transaction monitoring"
    vendor: str = "Revenium"
    homepage: str = "https://github.com/revenium/revenium-mcp"

    # Additional metadata
    features: List[str] = field(
        default_factory=lambda: [
            "AI transaction monitoring",
            "Business analytics",
            "Real-time alerting",
            "Cost optimization",
            "Resource management",
        ]
    )
    supported_protocols: List[str] = field(
        default_factory=lambda: ["2024-11-05", "2025-03-26", "2025-06-18"]
    )

    def to_mcp_format(self) -> Dict[str, Any]:
        """Convert to MCP server info format.

        Returns:
            MCP-compatible server info dictionary
        """
        return {"name": self.name, "version": self.version}

    def to_extended_format(self) -> Dict[str, Any]:
        """Convert to extended server info format with additional metadata.

        Returns:
            Extended server info dictionary
        """
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "vendor": self.vendor,
            "homepage": self.homepage,
            "features": self.features,
            "supported_protocols": self.supported_protocols,
            "last_updated": datetime.now().isoformat(),
        }


class MCPCapabilityManager:
    """Manages MCP server capabilities and change notifications."""

    def __init__(self):
        """Initialize the capability manager."""
        self.capabilities: Dict[str, CapabilityInfo] = {}
        self.server_info = ServerInfo()
        self.change_listeners: List[Callable] = []
        self.notification_enabled = True

        # Initialize default capabilities
        self._initialize_default_capabilities()

    def _initialize_default_capabilities(self):
        """Initialize default MCP capabilities."""
        default_capabilities = get_default_capabilities()

        for name, capability in default_capabilities.items():
            self.capabilities[name] = capability

        logger.info(f"Initialized {len(default_capabilities)} default MCP capabilities")

    def register_capability(self, capability: CapabilityInfo) -> bool:
        """Register a new capability.

        Args:
            capability: Capability to register

        Returns:
            True if capability was registered successfully
        """
        old_capability = self.capabilities.get(capability.name)
        self.capabilities[capability.name] = capability

        # Trigger change notification if capability changed
        if old_capability != capability:
            asyncio.create_task(self._notify_capability_changed(capability.name))

        logger.debug(f"Registered capability: {capability.name}")
        return True

    def update_capability(self, name: str, **updates) -> bool:
        """Update an existing capability.

        Args:
            name: Capability name
            **updates: Fields to update

        Returns:
            True if capability was updated successfully
        """
        if name not in self.capabilities:
            logger.warning(f"Cannot update non-existent capability: {name}")
            return False

        capability = self.capabilities[name]
        updated = False

        # Update fields
        for field_name, value in updates.items():
            if hasattr(capability, field_name):
                setattr(capability, field_name, value)
                updated = True

        if updated:
            capability.last_updated = datetime.now()
            asyncio.create_task(self._notify_capability_changed(name))
            logger.debug(f"Updated capability: {name}")

        return updated

    def enable_capability(self, name: str) -> bool:
        """Enable a capability.

        Args:
            name: Capability name

        Returns:
            True if capability was enabled
        """
        return self.update_capability(name, enabled=True)

    def disable_capability(self, name: str) -> bool:
        """Disable a capability.

        Args:
            name: Capability name

        Returns:
            True if capability was disabled
        """
        return self.update_capability(name, enabled=False)

    def get_capabilities(self) -> Dict[str, Any]:
        """Get current server capabilities in MCP format."""
        return get_capabilities_mcp_format(self.capabilities)

    def get_capability_info(self, name: str) -> Optional[CapabilityInfo]:
        """Get detailed information about a capability.

        Args:
            name: Capability name

        Returns:
            CapabilityInfo or None if not found
        """
        return self.capabilities.get(name)

    def get_server_info(self, extended: bool = False) -> Dict[str, Any]:
        """Get server information.

        Args:
            extended: Whether to include extended metadata

        Returns:
            Server info dictionary
        """
        if extended:
            return self.server_info.to_extended_format()
        else:
            return self.server_info.to_mcp_format()

    def update_server_info(self, **updates) -> bool:
        """Update server information."""
        return update_server_info_fields(self.server_info, **updates)

    def add_change_listener(self, listener: Callable[[str], None]) -> None:
        """Add a capability change listener."""
        add_change_listener_to_list(self.change_listeners, listener)

    def remove_change_listener(self, listener: Callable[[str], None]) -> None:
        """Remove a capability change listener."""
        remove_change_listener_from_list(self.change_listeners, listener)

    async def _notify_capability_changed(self, capability_name: str) -> None:
        """Notify listeners of capability changes.

        Args:
            capability_name: Name of capability that changed
        """
        if not self.notification_enabled:
            return

        # Notify registered listeners
        for listener in self.change_listeners:
            try:
                if asyncio.iscoroutinefunction(listener):
                    await listener(capability_name)
                else:
                    listener(capability_name)
            except Exception as e:
                logger.error(f"Error in capability change listener: {e}")

        # Send MCP notification if protocol handler supports it
        if hasattr(protocol_handler, "client_supports_capability"):
            if (
                protocol_handler.client_supports_capability("tools", "listChanged")
                and capability_name == "tools"
            ):
                await self._send_tools_list_changed_notification()
            elif (
                protocol_handler.client_supports_capability("resources", "listChanged")
                and capability_name == "resources"
            ):
                await self._send_resources_list_changed_notification()
            elif (
                protocol_handler.client_supports_capability("prompts", "listChanged")
                and capability_name == "prompts"
            ):
                await self._send_prompts_list_changed_notification()

    async def _send_tools_list_changed_notification(self) -> None:
        """Send tools/list_changed notification."""
        await send_notification("tools", protocol_handler.send_tools_list_changed_notification)

    async def _send_resources_list_changed_notification(self) -> None:
        """Send resources/list_changed notification."""
        await send_notification(
            "resources", protocol_handler.send_resources_list_changed_notification
        )

    async def _send_prompts_list_changed_notification(self) -> None:
        """Send prompts/list_changed notification."""
        await send_notification("prompts", protocol_handler.send_prompts_list_changed_notification)

    def get_capability_stats(self) -> Dict[str, Any]:
        """Get capability statistics."""
        stats = build_capability_stats(self.capabilities)
        stats.update(
            {
                "notification_enabled": self.notification_enabled,
                "change_listeners": len(self.change_listeners),
                "last_updated": max(
                    (cap.last_updated for cap in self.capabilities.values()), default=datetime.now()
                ).isoformat(),
            }
        )
        return stats


# Helper functions moved to capability_operations_helpers.py


# Global capability manager instance
capability_manager = MCPCapabilityManager()
