"""Dynamic MCP tool decorators for single source of truth architecture.

This module provides decorator factories that create @mcp.tool decorators
with descriptions dynamically loaded from tool classes, eliminating the
need for manual synchronization across multiple locations.
"""

import logging
from typing import Any, Callable

from fastmcp import FastMCP

from .tool_registry import get_tool_description

logger = logging.getLogger(__name__)


def dynamic_mcp_tool(tool_name: str):
    """Decorator factory that creates @mcp.tool with dynamic description.

    This decorator factory creates an @mcp.tool decorator that automatically
    retrieves the tool description from the tool class registry, ensuring
    consistency across the codebase.

    Args:
        tool_name: Name of the tool to get description for

    Returns:
        Decorator function that applies @mcp.tool with dynamic description

    Example:
        @dynamic_mcp_tool("manage_alerts")
        async def manage_alerts(action: str, **kwargs):
            # Description automatically loaded from AlertManagement.tool_description
            return await standardized_tool_execution("manage_alerts", action, **kwargs)
    """

    def decorator(func: Callable) -> Callable:
        """Apply @mcp.tool with dynamic description to function.

        Args:
            func: Function to decorate

        Returns:
            Decorated function with @mcp.tool applied
        """
        try:
            # Get description from tool class registry
            description = get_tool_description(tool_name)

            # Set function docstring for MCP protocol compliance
            func.__doc__ = description

            # Apply FastMCP @mcp.tool decorator
            # Note: This assumes 'mcp' is available in the calling scope
            # The actual decorator will be applied when this is used in enhanced_server.py
            func._dynamic_mcp_description = description
            func._dynamic_mcp_tool_name = tool_name

            logger.debug(f"Dynamic description set for {tool_name}: {description}")
            return func

        except Exception as e:
            # Graceful fallback - don't break tool registration
            fallback_description = f"Tool: {tool_name} (description unavailable)"
            func.__doc__ = fallback_description
            func._dynamic_mcp_description = fallback_description
            func._dynamic_mcp_tool_name = tool_name

            logger.warning(f"Could not get dynamic description for {tool_name}: {e}")
            logger.warning(f"Using fallback description: {fallback_description}")
            return func

    return decorator


def apply_mcp_tool_decorator(mcp_instance: FastMCP, func: Callable) -> Any:
    """Apply the actual @mcp.tool decorator to a dynamically decorated function.

    This function is used to apply the FastMCP @mcp.tool decorator to functions
    that have been prepared with dynamic descriptions.

    Args:
        mcp_instance: FastMCP instance to use for decoration
        func: Function with dynamic description already set

    Returns:
        FunctionTool object decorated with @mcp.tool
    """
    try:
        # Apply the actual @mcp.tool decorator
        return mcp_instance.tool()(func)
    except Exception as e:
        logger.error(
            f"Failed to apply @mcp.tool decorator to {getattr(func, '_dynamic_mcp_tool_name', 'unknown')}: {e}"
        )
        # Return undecorated function as fallback
        return func


def create_standardized_tool_execution():
    """Create standardized tool execution function for reduced code duplication.

    Returns:
        Async function that handles standardized tool execution pattern
    """

    async def standardized_tool_execution(tool_name: str, action: str, **kwargs) -> Any:
        """Execute tool action using standardized pattern.

        This function provides a consistent execution pattern for all tools,
        reducing code duplication in the enhanced_server.py decorators.

        Args:
            tool_name: Name of the tool to execute
            action: Action to perform
            **kwargs: Tool action arguments

        Returns:
            Tool execution result
        """
        from ..tools_decomposed.tool_registry import _get_tool_class

        try:
            # Get tool class from registry
            tool_class = _get_tool_class(tool_name)
            if not tool_class:
                raise ValueError(f"Tool class not found for {tool_name}")

            # Create tool instance
            # Note: UCM helper would be passed here in actual implementation
            tool_instance = tool_class()

            # Execute tool action
            result = await tool_instance.handle_action(action, kwargs)

            return result

        except Exception as e:
            logger.error(f"Error in standardized execution for {tool_name}.{action}: {e}")
            # Return formatted error response
            from ..common.error_handling import format_error_response

            return format_error_response(e, f"{tool_name}.{action}")

    return standardized_tool_execution
