"""JSON-RPC 2.0 Compliant Error Handling for MCP Server.

This module implements the Model Context Protocol (MCP) compliant error handling
system with standard JSON-RPC error codes and enhanced error messaging for
better developer experience.

Based on MCP specification and JSON-RPC 2.0 standard:
- Standard JSON-RPC error codes (-32700 to -32603)
- MCP-specific error codes (-32002, -32001)
- Enhanced error messages with recovery guidance
- Structured error data for debugging
"""

import json
from dataclasses import asdict, dataclass
from dataclasses import field as dataclass_field
from enum import IntEnum
from typing import Any, Dict, List, Optional, Union

from mcp.types import EmbeddedResource, ImageContent, TextContent

from .error_formatting_helpers import format_error_content, get_method_suggestions


class JSONRPCErrorCode(IntEnum):
    """Standard JSON-RPC 2.0 error codes as defined in the specification."""

    # Standard JSON-RPC error codes
    PARSE_ERROR = -32700  # Invalid JSON was received by the server
    INVALID_REQUEST = -32600  # The JSON sent is not a valid Request object
    METHOD_NOT_FOUND = -32601  # The method does not exist / is not available
    INVALID_PARAMS = -32602  # Invalid method parameter(s)
    INTERNAL_ERROR = -32603  # Internal JSON-RPC error

    # MCP-specific error codes (as per MCP specification)
    RESOURCE_NOT_FOUND = -32002  # Resource not found
    TOOL_EXECUTION_FAILED = -32001  # Tool execution failed

    # Server-defined error codes (range: -32000 to -32099)
    AUTHENTICATION_ERROR = -32010  # Authentication failed
    AUTHORIZATION_ERROR = -32011  # Authorization failed
    RATE_LIMIT_ERROR = -32012  # Rate limit exceeded
    VALIDATION_ERROR = -32013  # Data validation failed
    CONFIGURATION_ERROR = -32014  # Configuration error
    DEPENDENCY_ERROR = -32015  # External dependency error
    TIMEOUT_ERROR = -32016  # Operation timeout
    CAPACITY_ERROR = -32017  # Server capacity exceeded


@dataclass
class MCPErrorData:
    """Structured error data for enhanced debugging and recovery guidance."""

    # Core error information
    field: Optional[str] = None  # Field that caused the error
    value: Optional[Any] = None  # Invalid value that caused the error
    expected: Optional[str] = None  # What was expected

    # Recovery guidance
    suggestions: List[str] = dataclass_field(default_factory=list)  # Actionable suggestions
    examples: Dict[str, Any] = dataclass_field(default_factory=dict)  # Working examples
    recovery_actions: List[str] = dataclass_field(default_factory=list)  # Step-by-step recovery

    # Additional context
    context: Dict[str, Any] = dataclass_field(default_factory=dict)  # Additional context
    documentation_url: Optional[str] = None  # Link to relevant documentation

    # Technical details (for debugging)
    trace_id: Optional[str] = None  # Request trace ID
    timestamp: Optional[str] = None  # Error timestamp
    server_info: Dict[str, Any] = dataclass_field(default_factory=dict)  # Server context


class MCPError(Exception):
    """JSON-RPC 2.0 compliant error for MCP server responses.

    This class provides structured error handling that follows both JSON-RPC 2.0
    and MCP specifications while providing enhanced error messaging for better
    developer experience.
    """

    def __init__(
        self,
        code: JSONRPCErrorCode,
        message: str,
        data: Optional[MCPErrorData] = None,
        suggestions: Optional[List[str]] = None,
        examples: Optional[Dict[str, Any]] = None,
        recovery_actions: Optional[List[str]] = None,
    ):
        """Initialize MCP error with JSON-RPC compliance.

        Args:
            code: JSON-RPC error code
            message: Human-readable error message
            data: Structured error data for debugging
            suggestions: Quick suggestions (convenience parameter)
            examples: Working examples (convenience parameter)
            recovery_actions: Recovery steps (convenience parameter)
        """
        super().__init__(message)
        self.code = code
        self.message = message

        # Initialize or update error data
        if data is None:
            data = MCPErrorData()

        # Add convenience parameters to data if provided
        if suggestions:
            data.suggestions.extend(suggestions)
        if examples:
            data.examples.update(examples)
        if recovery_actions:
            data.recovery_actions.extend(recovery_actions)

        self.data = data

    def to_json_rpc_error(self, request_id: Optional[Union[str, int]] = None) -> Dict[str, Any]:
        """Convert to JSON-RPC 2.0 error response format.

        Args:
            request_id: ID of the request that caused the error

        Returns:
            JSON-RPC 2.0 compliant error response
        """
        error_response = {
            "jsonrpc": "2.0",
            "error": {"code": self.code.value, "message": self.message},
        }

        # Add request ID if provided
        if request_id is not None:
            error_response["id"] = request_id

        # Add structured data if available
        if self.data and (
            self.data.field or self.data.suggestions or self.data.examples or self.data.context
        ):
            error_response["error"]["data"] = asdict(self.data)

        return error_response

    def to_mcp_content(self) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Convert to MCP content format for tool responses."""
        text = format_error_content(self)
        return [TextContent(type="text", text=text.strip())]


# Convenience functions for common error types
def create_invalid_params_error(
    message: str,
    field: Optional[str] = None,
    value: Optional[Any] = None,
    expected: Optional[str] = None,
    suggestions: Optional[List[str]] = None,
) -> MCPError:
    """Create an invalid parameters error (-32602).

    Args:
        message: Error message
        field: Field that caused the error
        value: Invalid value
        expected: What was expected
        suggestions: Recovery suggestions

    Returns:
        MCPError instance
    """
    data = MCPErrorData(field=field, value=value, expected=expected, suggestions=suggestions or [])

    return MCPError(code=JSONRPCErrorCode.INVALID_PARAMS, message=message, data=data)


def create_method_not_found_error(
    method: str, available_methods: Optional[List[str]] = None
) -> MCPError:
    """Create a method not found error (-32601).

    Args:
        method: Method that was not found
        available_methods: List of available methods

    Returns:
        MCPError instance
    """
    suggestions = get_method_suggestions(method, available_methods)

    data = MCPErrorData(
        field="method",
        value=method,
        expected="Valid method name",
        suggestions=suggestions,
        context={"available_methods": available_methods or []},
    )

    return MCPError(
        code=JSONRPCErrorCode.METHOD_NOT_FOUND, message=f"Method not found: {method}", data=data
    )


def create_tool_execution_error(
    tool_name: str, action: str, error_message: str, suggestions: Optional[List[str]] = None
) -> MCPError:
    """Create a tool execution error (-32001).

    Args:
        tool_name: Name of the tool
        action: Action that failed
        error_message: Detailed error message
        suggestions: Recovery suggestions

    Returns:
        MCPError instance
    """
    data = MCPErrorData(
        suggestions=suggestions
        or [
            f"Verify the {action} action is supported by {tool_name}",
            "Check the action parameters are correct",
            "Try using the tool's introspection capabilities",
        ],
        context={"tool_name": tool_name, "action": action, "original_error": error_message},
    )

    return MCPError(
        code=JSONRPCErrorCode.TOOL_EXECUTION_FAILED,
        message=f"Tool execution failed: {tool_name}.{action} - {error_message}",
        data=data,
    )


def create_resource_not_found_error(
    uri: str, available_resources: Optional[List[str]] = None
) -> MCPError:
    """Create a resource not found error (-32002).

    Args:
        uri: Resource URI that was not found
        available_resources: List of available resource URIs

    Returns:
        MCPError instance
    """
    suggestions = ["Check the resource URI is correct"]
    if available_resources:
        suggestions.append(f"Available resources: {', '.join(available_resources)}")

    data = MCPErrorData(
        field="uri",
        value=uri,
        expected="Valid resource URI",
        suggestions=suggestions,
        context={"available_resources": available_resources or []},
    )

    return MCPError(
        code=JSONRPCErrorCode.RESOURCE_NOT_FOUND, message=f"Resource not found: {uri}", data=data
    )


def create_internal_error(
    message: str, trace_id: Optional[str] = None, context: Optional[Dict[str, Any]] = None
) -> MCPError:
    """Create an internal server error (-32603).

    Args:
        message: Error message
        trace_id: Request trace ID for debugging
        context: Additional context information

    Returns:
        MCPError instance
    """
    data = MCPErrorData(
        suggestions=[
            "This is an internal server error",
            "Please try again in a few moments",
            "If the problem persists, contact support",
        ],
        recovery_actions=[
            "Wait a few seconds and retry the request",
            "Check if the server is experiencing issues",
            "Contact support with the trace ID if available",
        ],
        trace_id=trace_id,
        context=context or {},
    )

    return MCPError(
        code=JSONRPCErrorCode.INTERNAL_ERROR, message=f"Internal server error: {message}", data=data
    )


# Helper functions moved to error_formatting_helpers.py
