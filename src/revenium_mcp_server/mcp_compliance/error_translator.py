"""Error Translation Layer for MCP Compliance.

This module provides translation from existing error types to JSON-RPC 2.0
compliant MCP errors, ensuring backward compatibility while achieving
full MCP protocol compliance.
"""

import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly.error_handling import AgentFriendlyError
from ..common.error_handling import ResourceError, ToolError

# Import existing error types for translation
from ..exceptions import (
    AlertNotFoundError,
    AlertToolsError,
    AnomalyNotFoundError,
    APIConnectionError,
    ConfigurationError,
    DataIntegrityError,
    InvalidInputError,
    OperationTimeoutError,
    PermissionError,
    ValidationError,
)
from .error_handling import (
    JSONRPCErrorCode,
    MCPError,
    MCPErrorData,
)
from .error_translation_helpers import (
    create_known_error_data,
    create_structured_error_data,
    get_default_recovery_actions,
)


class MCPErrorTranslator:
    """Translates existing error types to JSON-RPC 2.0 compliant MCP errors."""

    def __init__(self):
        """Initialize the error translator with mapping rules."""
        self._error_mappings = self._build_error_mappings()

    def _build_error_mappings(self) -> Dict[Type[Exception], JSONRPCErrorCode]:
        """Build mapping from exception types to JSON-RPC error codes.

        Returns:
            Dictionary mapping exception types to error codes
        """
        return {
            # Validation and parameter errors
            ValidationError: JSONRPCErrorCode.INVALID_PARAMS,
            InvalidInputError: JSONRPCErrorCode.INVALID_PARAMS,
            DataIntegrityError: JSONRPCErrorCode.VALIDATION_ERROR,
            # Not found errors
            AnomalyNotFoundError: JSONRPCErrorCode.RESOURCE_NOT_FOUND,
            AlertNotFoundError: JSONRPCErrorCode.RESOURCE_NOT_FOUND,
            # Permission and authentication errors
            PermissionError: JSONRPCErrorCode.AUTHORIZATION_ERROR,
            # Configuration and system errors
            ConfigurationError: JSONRPCErrorCode.CONFIGURATION_ERROR,
            APIConnectionError: JSONRPCErrorCode.DEPENDENCY_ERROR,
            OperationTimeoutError: JSONRPCErrorCode.TIMEOUT_ERROR,
            # Tool execution errors
            AlertToolsError: JSONRPCErrorCode.TOOL_EXECUTION_FAILED,
            # Generic errors
            Exception: JSONRPCErrorCode.INTERNAL_ERROR,
        }

    def translate_exception(
        self,
        exception: Exception,
        context: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> MCPError:
        """Translate any exception to a JSON-RPC compliant MCP error.

        Args:
            exception: Exception to translate
            context: Additional context information
            trace_id: Request trace ID for debugging

        Returns:
            MCPError instance with appropriate JSON-RPC error code
        """
        # Generate trace ID if not provided
        if trace_id is None:
            trace_id = f"mcp-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{id(exception)}"

        # Log the original exception for debugging
        logger.error(f"Translating exception to MCP error (trace: {trace_id}): {exception}")

        # Handle already translated MCP errors
        if isinstance(exception, MCPError):
            return exception

        # Handle structured errors with existing data
        if isinstance(exception, (ToolError, ResourceError, AgentFriendlyError)):
            return self._translate_structured_error(exception, context, trace_id)

        # Handle known exception types
        if isinstance(exception, tuple(self._error_mappings.keys())):
            return self._translate_known_error(exception, context, trace_id)

        # Handle unknown exceptions
        return self._translate_unknown_error(exception, context, trace_id)

    def _translate_structured_error(
        self,
        error: Union[ToolError, ResourceError, AgentFriendlyError],
        context: Optional[Dict[str, Any]],
        trace_id: str,
    ) -> MCPError:
        """Translate structured errors with existing metadata."""
        error_code = self._get_error_code_for_type(type(error))
        error_data = create_structured_error_data(error, context, trace_id)

        return MCPError(code=error_code, message=str(error), data=error_data)

    def _translate_known_error(
        self, exception: Exception, context: Optional[Dict[str, Any]], trace_id: str
    ) -> MCPError:
        """Translate known exception types to MCP errors."""
        error_code = self._get_error_code_for_type(type(exception))
        error_data = create_known_error_data(exception, context, trace_id)

        return MCPError(code=error_code, message=str(exception), data=error_data)

    def _translate_unknown_error(
        self, exception: Exception, context: Optional[Dict[str, Any]], trace_id: str
    ) -> MCPError:
        """Translate unknown exception types to internal errors.

        Args:
            exception: Unknown exception
            context: Additional context
            trace_id: Request trace ID

        Returns:
            MCPError instance
        """
        # Get stack trace for debugging
        stack_trace = traceback.format_exc()

        error_data = MCPErrorData(
            suggestions=[
                "This is an unexpected error",
                "Please try again in a few moments",
                "If the problem persists, contact support with the trace ID",
            ],
            recovery_actions=[
                "Wait a few seconds and retry the request",
                "Check if the operation parameters are correct",
                "Contact support if the error continues",
            ],
            trace_id=trace_id,
            timestamp=datetime.now().isoformat(),
            context={
                **(context or {}),
                "exception_type": type(exception).__name__,
                "stack_trace": stack_trace,
            },
        )

        return MCPError(
            code=JSONRPCErrorCode.INTERNAL_ERROR,
            message=f"Unexpected error: {str(exception)}",
            data=error_data,
        )

    def _get_error_code_for_type(self, exception_type: Type[Exception]) -> JSONRPCErrorCode:
        """Get the appropriate JSON-RPC error code for an exception type.

        Args:
            exception_type: Type of exception

        Returns:
            Appropriate JSON-RPC error code
        """
        # Check direct mapping first
        if exception_type in self._error_mappings:
            return self._error_mappings[exception_type]

        # Check inheritance hierarchy
        for mapped_type, error_code in self._error_mappings.items():
            if issubclass(exception_type, mapped_type):
                return error_code

        # Default to internal error
        return JSONRPCErrorCode.INTERNAL_ERROR

    def _get_recovery_actions_for_type(self, exception_type: Type[Exception]) -> List[str]:
        """Get recovery actions for specific exception types.

        Args:
            exception_type: Type of exception

        Returns:
            List of recovery actions
        """
        return get_default_recovery_actions(exception_type)


# Helper functions moved to error_translation_helpers.py


# Global translator instance
error_translator = MCPErrorTranslator()


def translate_to_mcp_error(
    exception: Exception, context: Optional[Dict[str, Any]] = None, trace_id: Optional[str] = None
) -> MCPError:
    """Convenience function to translate any exception to MCP error.

    Args:
        exception: Exception to translate
        context: Additional context information
        trace_id: Request trace ID for debugging

    Returns:
        MCPError instance
    """
    return error_translator.translate_exception(exception, context, trace_id)


def format_mcp_error_response(
    exception: Exception, context: Optional[Dict[str, Any]] = None, trace_id: Optional[str] = None
) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
    """Format any exception as an MCP-compliant error response.

    Args:
        exception: Exception to format
        context: Additional context information
        trace_id: Request trace ID for debugging

    Returns:
        List containing formatted error content
    """
    mcp_error = translate_to_mcp_error(exception, context, trace_id)
    return mcp_error.to_mcp_content()


def with_mcp_error_handling(tool_name: str, action: Optional[str] = None):
    """Decorator to add MCP-compliant error handling to tool methods.

    This decorator automatically catches exceptions and converts them to
    JSON-RPC 2.0 compliant MCP errors with enhanced error messaging.

    Args:
        tool_name: Name of the tool for error context
        action: Specific action being performed (optional)

    Returns:
        Decorator function
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                # Generate context information
                context = {
                    "tool_name": tool_name,
                    "action": action or func.__name__,
                    "function": func.__name__,
                    "args_count": len(args),
                    "kwargs_keys": list(kwargs.keys()),
                }

                # Add action from arguments if available and not specified
                if action is None and len(args) > 1 and hasattr(args[1], "get"):
                    context["action"] = args[1].get("action", func.__name__)

                # Log the error for debugging
                logger.error(f"Error in {tool_name}.{context['action']}: {e}")

                # Return MCP-compliant error response
                return format_mcp_error_response(e, context)

        return wrapper

    return decorator
