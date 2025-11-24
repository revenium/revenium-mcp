"""Standardized tool execution module.

This module provides the standardized tool execution function that is used
across the codebase to ensure consistent tool execution patterns.

Separated from enhanced_server.py to avoid circular import issues.
"""

import time
from typing import Any, Dict, List, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent


async def standardized_tool_execution(
    tool_name: str,
    action: str,
    arguments: Dict[str, Any],
    tool_class: Any,
    use_direct_execution: bool = True,
) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
    """Standardized tool execution path with proper exception handling and performance monitoring.

    This function provides a consistent execution path for all tools, eliminating
    the need for string-based error detection and bypass patterns.

    Args:
        tool_name: Name of the tool for introspection
        action: Action to perform
        arguments: Action arguments
        tool_class: Tool class to instantiate for fallback
        use_direct_execution: Whether to use direct execution (for compatibility)

    Returns:
        Tool execution result

    Raises:
        ToolExecutionError: For tool execution failures
        IntrospectionError: For introspection layer failures
        UCMError: For UCM integration failures
    """
    from ..capability_manager.integration_service import ucm_integration_service
    from ..common.error_handling import IntrospectionError, ToolExecutionError
    from ..introspection.integration import introspection_integration

    # Performance monitoring removed - infrastructure monitoring handled externally
    # Performance monitoring - start timing
    start_time = time.time()

    try:
        # First, try introspection execution
        introspection_start = time.time()
        try:
            result = await introspection_integration.handle_tool_execution(
                tool_name, action, arguments
            )
            introspection_time = (time.time() - introspection_start) * 1000  # Convert to ms

            # Check if introspection succeeded - detect error responses
            if result and len(result) > 0:
                # Check if the result is an error response
                first_result = result[0]
                if isinstance(first_result, TextContent):
                    content_text = first_result.text
                    # Detect error indicators in the response
                    if any(
                        error_indicator in content_text
                        for error_indicator in [
                            "🚨 **TOOL_ERROR**",
                            "Tool execution failed",
                            "**Message**: Tool execution failed",
                            "Error executing tool",
                        ]
                    ):
                        # This is an error response, fall back to direct execution
                        raise IntrospectionError(
                            f"Introspection returned error response for {tool_name}: {content_text[:100]}...",
                            tool_name=tool_name,
                            action=action,
                        )

                # Introspection succeeded, return result
                # Log performance metrics and record for dashboard
                total_time = (time.time() - start_time) * 1000
                logger.info(
                    f"PERFORMANCE: {tool_name}.{action} - Introspection: {introspection_time:.2f}ms, Total: {total_time:.2f}ms"
                )

                # Performance metrics recording removed - handled by external monitoring

                return result
            else:
                raise IntrospectionError(
                    f"Introspection returned empty result for {tool_name}",
                    tool_name=tool_name,
                    action=action,
                )

        except (IntrospectionError, Exception) as e:
            # Introspection failed, fall back to direct execution
            introspection_time = (time.time() - introspection_start) * 1000
            logger.info(
                f"Introspection failed for {tool_name} after {introspection_time:.2f}ms, attempting direct execution: {str(e)}"
            )

            # Fallback to direct tool execution
            direct_start = time.time()
            try:
                # Get UCM helper with health check
                ucm_helper_start = time.time()
                ucm_helper = None
                try:
                    # Check if UCM integration is healthy before using it
                    health_status = await ucm_integration_service.get_health_status()
                    if health_status.get("status") == "healthy":
                        ucm_helper = ucm_integration_service.get_integration_helper()
                    else:
                        logger.debug(
                            f"UCM integration not healthy, using fallback: {health_status}"
                        )
                except Exception as e:
                    logger.debug(f"UCM health check failed, using fallback: {e}")

                ucm_time = (time.time() - ucm_helper_start) * 1000

                # Create tool instance with standardized UCM integration
                # All tools now use the unified constructor pattern: ucm_helper parameter
                tool_instance = tool_class(ucm_helper=ucm_helper)

                result = await tool_instance.handle_action(action, arguments)

                # Performance monitoring for direct execution
                direct_time = (time.time() - direct_start) * 1000
                total_time = (time.time() - start_time) * 1000

                logger.info(
                    f"PERFORMANCE: {tool_name}.{action} - UCM: {ucm_time:.2f}ms, Direct: {direct_time:.2f}ms, Total: {total_time:.2f}ms"
                )

                # Performance metrics recording removed - handled by external monitoring

                return result

            except Exception as fallback_error:
                # Performance monitoring for failure
                total_time = (time.time() - start_time) * 1000

                logger.error(f"PERFORMANCE: {tool_name}.{action} - FAILED after {total_time:.2f}ms")

                # Performance metrics recording removed - handled by external monitoring

                # Check if the direct execution error is a user-friendly ToolError
                # If so, preserve just the user message without internal system details
                from ..common.error_handling import ToolError

                if isinstance(fallback_error, ToolError):
                    # Re-raise the ToolError directly to preserve user-friendly message
                    raise fallback_error

                # For other errors, check if they contain user-friendly messages
                error_str = str(fallback_error)
                if any(indicator in error_str for indicator in [
                    "Invalid organization ID format",
                    "Invalid subscriber",
                    "Invalid user",
                    "not found",
                    "validation error",
                    "missing parameter"
                ]):
                    # This appears to be a user-friendly error, just raise it directly
                    raise ToolExecutionError(error_str, tool_name=tool_name, action=action)

                # For truly technical errors, provide minimal context
                raise ToolExecutionError(
                    f"Tool execution failed: {str(fallback_error)}",
                    tool_name=tool_name,
                    action=action,
                )

    except Exception as e:
        # Catch-all for any other exceptions
        total_time = (time.time() - start_time) * 1000

        logger.error(
            f"PERFORMANCE: {tool_name}.{action} - ERROR after {total_time:.2f}ms: {str(e)}"
        )
        raise
