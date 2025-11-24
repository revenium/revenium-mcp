"""Base registry class for tool organization and standardized execution.

This module provides the BaseToolRegistry class that serves as the foundation
for all tool registries, ensuring consistent patterns and enterprise compliance.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Union

from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..common.error_handling import format_error_response
from ..tools_decomposed.unified_tool_base import ToolBase

logger = logging.getLogger(__name__)


class BaseToolRegistry(ABC):
    """Base class for tool registries with standardized execution patterns.

    This class provides the foundation for all tool registries, ensuring
    consistent patterns, enterprise compliance, and security maintenance.
    """

    def __init__(self, registry_name: str, ucm_helper=None):
        """Initialize the base registry.

        Args:
            registry_name: Name of the registry for logging and identification
            ucm_helper: UCM integration helper for capability management
        """
        self.registry_name = registry_name
        self.ucm_helper = ucm_helper
        self._tools: Dict[str, ToolBase] = {}
        self._tool_metadata: Dict[str, Dict[str, Any]] = {}

        # Initialize tools specific to this registry
        self._initialize_tools()

        logger.info(f"Initialized {registry_name} registry with {len(self._tools)} tools")

    @abstractmethod
    def _initialize_tools(self) -> None:
        """Initialize tools specific to this registry.

        This method should be implemented by subclasses to register
        their specific tools.
        """
        pass

    def _register_tool(self, tool_name: str, tool_instance: ToolBase) -> None:
        """Register a tool instance with the registry.

        Args:
            tool_name: Name of the tool
            tool_instance: Tool instance to register
        """
        self._tools[tool_name] = tool_instance
        self._tool_metadata[tool_name] = {
            "name": tool_name,
            "class_name": tool_instance.__class__.__name__,
            "tool_type": getattr(tool_instance, "tool_type", "utility"),
            "version": getattr(tool_instance, "tool_version", "1.0.0"),
            "description": getattr(tool_instance, "tool_description", "No description"),
        }

        logger.debug(f"Registered tool: {tool_name} in {self.registry_name}")

    async def _standardized_tool_execution(
        self, tool_name: str, action: str, parameters: Any
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Execute a tool with standardized patterns and error handling.

        This method provides consistent execution patterns across all tools
        in the registry, ensuring enterprise compliance and security.

        Args:
            tool_name: Name of the tool to execute
            action: Action to perform
            parameters: Parameters object (dataclass or dict)

        Returns:
            Tool execution result

        Raises:
            KeyError: If tool is not found in registry
            Exception: For tool execution errors
        """
        # Validate tool exists
        if tool_name not in self._tools:
            error_msg = f"Tool '{tool_name}' not found in {self.registry_name} registry"
            logger.error(error_msg)
            return format_error_response(KeyError(error_msg), f"{self.registry_name}.{tool_name}")

        tool_instance = self._tools[tool_name]

        # Convert parameters to dict if it's a dataclass
        if hasattr(parameters, "__dataclass_fields__"):
            arguments = asdict(parameters)
        elif isinstance(parameters, dict):
            arguments = parameters
        else:
            arguments = {}

        # Remove None values to avoid validation issues
        arguments = {k: v for k, v in arguments.items() if v is not None}

        try:
            logger.info(
                f"Executing {tool_name} action '{action}' via {self.registry_name} registry"
            )

            # Execute tool action
            result = await tool_instance.handle_action(action, arguments)

            logger.debug(f"Successfully executed {tool_name}.{action}")
            return result

        except Exception as e:
            logger.error(f"Error executing {tool_name}.{action}: {str(e)}")
            return format_error_response(e, f"{self.registry_name}.{tool_name}.{action}")

    def get_tool(self, tool_name: str) -> Optional[ToolBase]:
        """Get a tool instance by name.

        Args:
            tool_name: Name of the tool

        Returns:
            Tool instance if found, None otherwise
        """
        return self._tools.get(tool_name)

    def list_tools(self) -> List[str]:
        """Get list of all registered tool names.

        Returns:
            List of tool names
        """
        return list(self._tools.keys())

    def get_tool_metadata(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a specific tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Tool metadata if found, None otherwise
        """
        return self._tool_metadata.get(tool_name)


    def is_tool_available(self, tool_name: str) -> bool:
        """Check if a tool is available in the registry.

        Args:
            tool_name: Name of the tool

        Returns:
            True if tool is available, False otherwise
        """
        return tool_name in self._tools

    def get_registry_info(self) -> Dict[str, Any]:
        """Get information about this registry.

        Returns:
            Registry information including name, tool count, and tools
        """
        return {
            "registry_name": self.registry_name,
            "tool_count": len(self._tools),
            "tools": list(self._tools.keys()),
            "has_ucm_integration": self.ucm_helper is not None,
        }

    async def validate_tool_capabilities(self, tool_name: str) -> Dict[str, Any]:
        """Validate tool capabilities and return status.

        Args:
            tool_name: Name of the tool to validate

        Returns:
            Validation status and capabilities
        """
        if tool_name not in self._tools:
            return {"valid": False, "error": f"Tool '{tool_name}' not found in registry"}

        tool_instance = self._tools[tool_name]

        try:
            # Get tool metadata if available
            if hasattr(tool_instance, "get_tool_metadata"):
                metadata = await tool_instance.get_tool_metadata()
                return {
                    "valid": True,
                    "tool_name": tool_name,
                    "metadata": metadata,
                    "capabilities": getattr(metadata, "capabilities", []),
                    "supported_actions": getattr(metadata, "supported_actions", []),
                }
            else:
                return {
                    "valid": True,
                    "tool_name": tool_name,
                    "metadata": self._tool_metadata.get(tool_name, {}),
                    "note": "Limited metadata available",
                }

        except Exception as e:
            logger.error(f"Error validating tool {tool_name}: {str(e)}")
            return {"valid": False, "error": f"Validation error: {str(e)}"}
