"""Tool execution engine for MCP tools with enhanced error handling and compatibility.

This module provides a unified interface for executing MCP tools, handling both
modern tools with handle_action methods and legacy tools with direct method calls.
"""

# Standard library imports
import json
from typing import Any, Dict, List, Union

# Third-party imports
from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from .parameter_mapper import ParameterMapper, ParameterMappingError

# Local imports
from .tool_registry import tool_registry


class ToolExecutionError(Exception):
    """Exception raised when tool execution fails."""

    pass


class ToolExecutor:
    """Executes MCP tools with unified interface and error handling."""

    def __init__(self):
        """Initialize tool executor with parameter mapper."""
        self.parameter_mapper = ParameterMapper()

    async def execute_tool(
        self, tool_name: str, action: str, parameters: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Execute a tool with the specified action and parameters.

        Args:
            tool_name: Name of the tool to execute
            action: Action to perform
            parameters: Parameters for the action

        Returns:
            List of MCP content objects

        Raises:
            ToolExecutionError: If execution fails
        """
        try:
            # Get tool instance
            tool_instance = self._get_tool_instance(tool_name)

            # Prepare arguments for execution
            execution_args = self._prepare_execution_arguments(parameters, action)

            # Execute based on tool type
            if self._is_modern_tool(tool_instance):
                result = await self._execute_modern_tool(tool_instance, execution_args)
            else:
                result = await self._execute_legacy_tool(tool_instance, action, execution_args)

            logger.info(f"Successfully executed {tool_name}.{action}")
            return result

        except Exception as e:
            error_msg = f"Failed to execute {tool_name}.{action}: {str(e)}"
            logger.error(error_msg)
            raise ToolExecutionError(error_msg) from e

    def _get_tool_instance(self, tool_name: str) -> Any:
        """Get tool instance from registry."""
        tool_instance = tool_registry.get_tool(tool_name)
        if tool_instance is None:
            raise ToolExecutionError(f"Tool '{tool_name}' not found in registry")

        return tool_instance

    def _prepare_execution_arguments(
        self, parameters: Dict[str, Any], action: str
    ) -> Dict[str, Any]:
        """Prepare arguments for tool execution."""
        # Ensure action is included
        execution_args = parameters.copy()
        execution_args["action"] = action

        return execution_args

    def _is_modern_tool(self, tool_instance: Any) -> bool:
        """Check if tool uses modern handle_action interface."""
        return hasattr(tool_instance, "handle_action")

    async def _execute_modern_tool(
        self, tool_instance: Any, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Execute modern tool with handle_action method."""
        try:
            result = await tool_instance.handle_action(arguments)

            # Ensure result is in correct format
            if isinstance(result, list):
                return result
            else:
                # Convert single result to list
                return [result] if result else []

        except Exception as e:
            logger.error(f"Modern tool execution failed: {e}")
            raise ToolExecutionError(f"Modern tool execution failed: {e}") from e

    async def _execute_legacy_tool(
        self, tool_instance: Any, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Execute legacy tool with direct method calls."""
        try:
            # Try to find a method that matches the action
            method_name = f"handle_{action}"

            if hasattr(tool_instance, method_name):
                method = getattr(tool_instance, method_name)
                result = await method(arguments)
            else:
                # Fallback to generic handling
                result = await self._handle_legacy_fallback(tool_instance, action, arguments)

            # Ensure result is in correct format
            if isinstance(result, list):
                return result
            else:
                return [result] if result else []

        except Exception as e:
            logger.error(f"Legacy tool execution failed: {e}")
            raise ToolExecutionError(f"Legacy tool execution failed: {e}") from e

    async def _handle_legacy_fallback(
        self, tool_instance: Any, action: str, arguments: Dict[str, Any]
    ) -> Union[TextContent, ImageContent, EmbeddedResource]:
        """Handle legacy tools that don't have specific action methods."""
        # Create a response indicating the tool needs to be updated
        response_data = {
            "status": "legacy_tool_fallback",
            "message": f"Tool {tool_instance.__class__.__name__} executed with legacy fallback",
            "action": action,
            "arguments": arguments,
            "note": "This tool should be updated to use the modern handle_action interface",
        }

        return TextContent(type="text", text=json.dumps(response_data, indent=2))

    def validate_tool_action(self, tool_name: str, action: str) -> bool:
        """Validate that a tool supports a specific action."""
        return tool_registry.validate_tool_action(tool_name, action)

    def get_tool_capabilities(self, tool_name: str) -> Dict[str, Any]:
        """Get capabilities information for a tool."""
        metadata = tool_registry.get_tool_metadata(tool_name)
        if not metadata:
            return {}

        return {
            "name": metadata.get("name", tool_name),
            "description": metadata.get("description", "No description available"),
            "supported_actions": metadata.get("supported_actions", []),
            "is_modern": not metadata.get("is_legacy", True),
            "version": metadata.get("version", "1.0.0"),
        }

    def list_available_tools(self) -> List[Dict[str, Any]]:
        """List all available tools with their capabilities."""
        tools = []

        for tool_name in tool_registry.list_tools():
            capabilities = self.get_tool_capabilities(tool_name)
            tools.append(capabilities)

        return tools
