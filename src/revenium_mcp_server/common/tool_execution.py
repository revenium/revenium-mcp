"""Standardized tool execution module.

This module provides the standardized tool execution function that is used
across the codebase to ensure consistent tool execution patterns.

Separated from enhanced_server.py to avoid circular import issues.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

if TYPE_CHECKING:
    from ..auth.tenant_context import TenantContext

from ..auth.claims_middleware import current_tenant_context
from ..client import ReveniumAPIError
from .department_aliases import resolve_department_aliases
from .dry_run_guard import normalise_dry_run, refuse_unsupported_dry_run
from ..log_context import bind_tenant_context, clear_tenant_context, sanitize_error_message


async def standardized_tool_execution(
    tool_name: str,
    action: str,
    arguments: Dict[str, Any],
    tool_class: Any,
    use_direct_execution: bool = True,
    ctx: Optional[TenantContext] = None,
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
    from ..common.error_handling import IntrospectionError, ToolError
    from ..introspection.integration import introspection_integration

    action, arguments = resolve_department_aliases(tool_name, action, arguments)
    refuse_unsupported_dry_run(tool_name, action, arguments)
    arguments = normalise_dry_run(arguments)
    if ctx is None:
        ctx = current_tenant_context()
    tokens = bind_tenant_context(ctx)
    start_time = time.time()

    try:
        # First, try introspection execution
        introspection_start = time.time()
        try:
            result = await introspection_integration.handle_tool_execution(
                tool_name, action, arguments, ctx=ctx
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

        except PermissionError:
            # Fail closed on auth failure — never retry via direct execution.
            raise
        except ToolError:
            # The action ran and answered with a user-facing error. Running it
            # again on a fresh tool instance would repeat its platform calls and
            # waits only to raise the same error; introspection-layer failures
            # (ToolExecutionError subclasses) still fall back below.
            raise
        except ReveniumAPIError as platform_error:
            # Same reason as ToolError: a rerun doubles a timeout and resends a
            # write the platform may already have committed (BACK-4841).
            raise _execution_failure(platform_error, tool_name, action) from platform_error
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

                result = await tool_instance.handle_action(action, arguments, ctx=ctx)

                # Performance monitoring for direct execution
                direct_time = (time.time() - direct_start) * 1000
                total_time = (time.time() - start_time) * 1000

                logger.info(
                    f"PERFORMANCE: {tool_name}.{action} - UCM: {ucm_time:.2f}ms, Direct: {direct_time:.2f}ms, Total: {total_time:.2f}ms"
                )

                # Performance metrics recording removed - handled by external monitoring

                return result

            except PermissionError:
                # Fail closed on auth failure from the direct path too.
                raise
            except Exception as fallback_error:
                # Performance monitoring for failure
                total_time = (time.time() - start_time) * 1000

                logger.error(f"PERFORMANCE: {tool_name}.{action} - FAILED after {total_time:.2f}ms")

                # Performance metrics recording removed - handled by external monitoring

                # Check if the direct execution error is a user-friendly ToolError
                # If so, preserve just the user message without internal system details
                if isinstance(fallback_error, ToolError):
                    # Re-raise the ToolError directly to preserve user-friendly message
                    raise fallback_error

                raise _execution_failure(fallback_error, tool_name, action)

    except PermissionError:
        # Auth failures are expected control flow in clerk/api_key mode, not a
        # system error — re-raise without the ERROR-level performance log below,
        # which would otherwise create false-positive noise and alert triggers.
        raise
    except Exception as e:
        total_time = (time.time() - start_time) * 1000

        logger.error(
            f"PERFORMANCE: {tool_name}.{action} - ERROR after {total_time:.2f}ms: {str(e)}"
        )
        from .error_handling import ToolError

        if isinstance(e, ToolError):
            await _carry_guidance_to_caller(e, tool_name, tool_class)
        raise
    finally:
        clear_tenant_context(tokens)


_SELF_EXPLAINING_ERROR_MARKERS = (
    "Invalid organization ID format",
    "Invalid subscriber",
    "Invalid user",
    "not found",
    "validation error",
    "missing parameter",
)


def _execution_failure(error: Exception, tool_name: str, action: str) -> Exception:
    """The error the caller sees for an action that raised something other than a ToolError."""
    from .error_handling import ToolExecutionError

    error_str = sanitize_error_message(str(error))
    if any(marker in error_str for marker in _SELF_EXPLAINING_ERROR_MARKERS):
        return ToolExecutionError(error_str, tool_name=tool_name, action=action)
    return ToolExecutionError(
        f"Tool execution failed: {error_str}", tool_name=tool_name, action=action
    )


async def _carry_guidance_to_caller(error: Any, tool_name: str, tool_class: Any) -> None:
    """Put the error's guidance into the one string the framework sends the caller."""
    from .error_handling import caller_message

    valid_actions = (
        await _valid_actions(tool_name, tool_class) if error.field == "action" else []
    )
    try:
        text = caller_message(error, valid_actions)
    except Exception as render_error:
        logger.debug(f"Could not render guidance for {tool_name}: {render_error}")
        return
    error.message = text
    error.args = (text,)


async def _valid_actions(tool_name: str, tool_class: Any) -> List[str]:
    """The tool's advertised actions; empty when they cannot be read."""
    from ..introspection.integration import introspection_integration

    try:
        provider = await introspection_integration.engine.registry.get_provider(tool_name)
        if provider is None or not hasattr(provider, "_get_supported_actions"):
            provider = tool_class(ucm_helper=None)
        return [str(action) for action in await provider._get_supported_actions()]
    except Exception as lookup_error:
        logger.debug(f"Could not read supported actions for {tool_name}: {lookup_error}")
        return []
