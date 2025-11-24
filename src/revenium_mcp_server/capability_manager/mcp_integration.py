"""MCP protocol integration for the Unified Capability Manager.

This module provides integration with the Model Context Protocol for capability
declarations and change notifications.
"""

from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from .core import UnifiedCapabilityManager


class MCPCapabilityIntegration:
    """Integrates UCM with MCP protocol for capability declarations and notifications."""

    def __init__(self, ucm: UnifiedCapabilityManager):
        """Initialize MCP integration.

        Args:
            ucm: UnifiedCapabilityManager instance
        """
        self.ucm = ucm
        self._mcp_server = None
        self._capability_change_handlers: List[Callable] = []

        # MCP capability declaration cache
        self._mcp_declarations: Dict[str, Any] = {}

    async def initialize(self, mcp_server) -> None:
        """Initialize MCP integration with server instance.

        Args:
            mcp_server: FastMCP server instance
        """
        self._mcp_server = mcp_server

        # Register as capability change listener
        await self.ucm.add_change_listener(self._handle_capability_changes)

        logger.info("Initialized MCP capability integration")

    async def generate_mcp_capabilities(self) -> Dict[str, Any]:
        """Generate MCP capability declarations from UCM.

        Returns:
            MCP-compatible capability declarations
        """
        mcp_capabilities = {
            "tools": {"listChanged": True},
            "resources": {"subscribe": True, "listChanged": True},
        }

        # Add custom capability metadata
        mcp_capabilities["experimental"] = {
            "unified_capability_manager": {
                "version": "1.0.0",
                "supported_resource_types": list(self.ucm.supported_resource_types),
                "verification_enabled": True,
                "cache_enabled": True,
            }
        }

        logger.debug("Generated MCP capability declarations")
        return mcp_capabilities

    async def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Generate tool schemas based on verified capabilities.

        Returns:
            List of MCP tool schema declarations
        """
        tool_schemas = []

        for resource_type in self.ucm.supported_resource_types:
            try:
                capabilities = await self.ucm.get_capabilities(resource_type)
                schema = await self._generate_tool_schema(resource_type, capabilities)
                tool_schemas.append(schema)
            except Exception as e:
                logger.error(f"Failed to generate tool schema for {resource_type}: {e}")

        return tool_schemas

    async def get_resource_schemas(self) -> List[Dict[str, Any]]:
        """Generate resource schemas based on verified capabilities.

        Returns:
            List of MCP resource schema declarations
        """
        resource_schemas = []

        for resource_type in self.ucm.supported_resource_types:
            try:
                capabilities = await self.ucm.get_capabilities(resource_type)
                schema = await self._generate_resource_schema(resource_type, capabilities)
                resource_schemas.append(schema)
            except Exception as e:
                logger.error(f"Failed to generate resource schema for {resource_type}: {e}")

        return resource_schemas

    async def notify_capability_changes(self, changes: Dict[str, Any]) -> None:
        """Send MCP notifications for capability changes.

        Args:
            changes: Dictionary of capability changes
        """
        if not self._mcp_server:
            logger.warning("MCP server not initialized, cannot send notifications")
            return

        # Send tools/list changed notification
        try:
            # This would integrate with FastMCP's notification system
            # Implementation depends on FastMCP's notification API
            logger.info(f"Would send MCP capability change notifications: {changes}")

            # Notify registered handlers
            for handler in self._capability_change_handlers:
                try:
                    await handler(changes)
                except Exception as e:
                    logger.error(f"Error in capability change handler: {e}")

        except Exception as e:
            logger.error(f"Failed to send MCP capability change notifications: {e}")

    async def add_capability_change_handler(self, handler: Callable) -> None:
        """Add a handler for capability changes.

        Args:
            handler: Async callable that receives capability change notifications
        """
        self._capability_change_handlers.append(handler)

    async def remove_capability_change_handler(self, handler: Callable) -> None:
        """Remove a capability change handler.

        Args:
            handler: Handler to remove
        """
        if handler in self._capability_change_handlers:
            self._capability_change_handlers.remove(handler)

    async def _handle_capability_changes(self, changes: Dict[str, Any]) -> None:
        """Handle capability changes from UCM.

        Args:
            changes: Capability changes notification
        """
        logger.info(f"Handling capability changes: {changes}")

        # Update MCP declarations cache
        await self._update_mcp_declarations(changes)

        # Send MCP notifications
        await self.notify_capability_changes(changes)

    async def _update_mcp_declarations(self, changes: Dict[str, Any]) -> None:
        """Update cached MCP declarations based on capability changes.

        Args:
            changes: Capability changes
        """
        for resource_type, change_info in changes.get("changes", {}).items():
            if change_info.get("status") == "success":
                try:
                    capabilities = await self.ucm.get_capabilities(resource_type)
                    self._mcp_declarations[resource_type] = capabilities
                    logger.debug(f"Updated MCP declarations for {resource_type}")
                except Exception as e:
                    logger.error(f"Failed to update MCP declarations for {resource_type}: {e}")

    async def _generate_tool_schema(
        self, resource_type: str, capabilities: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate MCP tool schema for a resource type.

        Args:
            resource_type: Type of resource
            capabilities: Verified capabilities

        Returns:
            MCP tool schema
        """
        # Generate schema based on capabilities
        schema = {
            "name": f"manage_{resource_type}",
            "description": f"Manage {resource_type} with verified capabilities",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "get", "create", "update", "delete", "get_capabilities"],
                        "description": "Action to perform",
                    }
                },
                "required": ["action"],
            },
        }

        # Add capability-specific properties
        if "schema" in capabilities:
            schema_info = capabilities["schema"]
            if isinstance(schema_info, dict):
                for schema_name, schema_def in schema_info.items():
                    if isinstance(schema_def, dict) and "required" in schema_def:
                        # Add schema information to tool description
                        schema[
                            "description"
                        ] += f"\n\nRequired fields for {schema_name}: {', '.join(schema_def['required'])}"

        return schema

    async def _generate_resource_schema(
        self, resource_type: str, capabilities: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate MCP resource schema for a resource type.

        Args:
            resource_type: Type of resource
            capabilities: Verified capabilities

        Returns:
            MCP resource schema
        """
        schema = {
            "uri": f"capability://{resource_type}",
            "name": f"{resource_type.title()} Capabilities",
            "description": f"Verified capabilities for {resource_type}",
            "mimeType": "application/json",
        }

        return schema
