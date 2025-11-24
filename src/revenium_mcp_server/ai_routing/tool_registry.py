"""Tool registry for managing MCP tool instances and discovery.

This module provides centralized tool registration and discovery capabilities
for the AI routing system, enabling dynamic tool management and introspection.
"""

# Standard library imports
from typing import Any, Dict, List, Optional

# Third-party imports
from loguru import logger

# Local imports
from ..tools_decomposed import (
    AlertManagement,
    CustomerManagement,
    MeteringElementsManagement,
    MeteringManagement,
    SourceManagement,
    WorkflowManagement,
    product_management,
    subscription_management,
)


class ToolRegistry:
    """Centralized registry for MCP tools with discovery capabilities."""

    def __init__(self):
        """Initialize the tool registry with available tools."""
        self._tools: Dict[str, Any] = {}
        self._tool_metadata: Dict[str, Dict[str, Any]] = {}
        self._initialize_tools()

    def _initialize_tools(self) -> None:
        """Initialize and register all available MCP tools."""
        # Register tools with their instances
        tool_configs = [
            ("products", product_management),
            ("subscriptions", subscription_management),
            ("alerts", AlertManagement()),
            ("customers", CustomerManagement()),
            ("workflows", WorkflowManagement()),
            ("sources", SourceManagement()),
            ("metering", MeteringManagement()),
            ("metering_elements", MeteringElementsManagement()),
        ]

        for tool_name, tool_instance in tool_configs:
            self._register_tool(tool_name, tool_instance)

        logger.info(f"Tool registry initialized with {len(self._tools)} tools")

    def _register_tool(self, name: str, instance: Any) -> None:
        """Register a single tool instance."""
        self._tools[name] = instance

        # Extract tool metadata if available
        metadata = self._extract_tool_metadata(instance)
        self._tool_metadata[name] = metadata

        logger.debug(f"Registered tool: {name}")

    def _extract_tool_metadata(self, instance: Any) -> Dict[str, Any]:
        """Extract metadata from a tool instance."""
        metadata = {
            "name": getattr(instance, "tool_name", instance.__class__.__name__),
            "description": getattr(instance, "tool_description", "No description available"),
            "version": getattr(instance, "tool_version", "1.0.0"),
            "has_handle_action": hasattr(instance, "handle_action"),
            "is_legacy": not hasattr(instance, "handle_action"),
            "supported_actions": self._get_supported_actions(instance),
        }

        return metadata

    def _get_supported_actions(self, instance: Any) -> List[str]:
        """Get supported actions for a tool instance."""
        # Default CRUD actions for most tools
        default_actions = ["list", "get", "create", "update", "delete"]

        # Special cases for specific tools
        if hasattr(instance, "tool_name"):
            tool_name = instance.tool_name
            if "workflow" in tool_name.lower():
                return ["list", "get", "start", "next_step", "complete_step"]

        return default_actions

    def get_tool(self, name: str) -> Optional[Any]:
        """Get a tool instance by name."""
        return self._tools.get(name)

    def get_tool_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a specific tool."""
        return self._tool_metadata.get(name)

    def list_tools(self) -> List[str]:
        """Get list of all registered tool names."""
        return list(self._tools.keys())


    def is_tool_available(self, name: str) -> bool:
        """Check if a tool is available in the registry."""
        return name in self._tools

    def get_tools_by_capability(self, capability: str) -> List[str]:
        """Get tools that support a specific capability."""
        matching_tools = []

        for tool_name, metadata in self._tool_metadata.items():
            if capability in metadata.get("supported_actions", []):
                matching_tools.append(tool_name)

        return matching_tools

    def validate_tool_action(self, tool_name: str, action: str) -> bool:
        """Validate that a tool supports a specific action."""
        metadata = self.get_tool_metadata(tool_name)
        if not metadata:
            return False

        supported_actions = metadata.get("supported_actions", [])
        return action in supported_actions


# Global tool registry instance
tool_registry = ToolRegistry()
