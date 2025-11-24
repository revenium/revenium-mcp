"""Common error handling utilities.

This module provides standardized error handling patterns used across the MCP server,
following FastMCP patterns for structured, agent-friendly error responses.
"""

from typing import Any, Dict, List, Optional, Union

from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..client import ReveniumAPIError
from ..error_handlers import handle_alert_tool_errors
from ..exceptions import InvalidInputError, ValidationError

# Import existing error handling functionality
from ..standard_errors import (
    StandardErrorBuilder,
    StandardErrorFormatter,
    create_api_error,
    create_invalid_value_error,
    create_missing_parameter_error,
    create_unknown_action_error,
    create_validation_error,
)


# Error code constants for structured error responses
class ErrorCodes:
    """Standardized error codes for consistent error handling across all tools."""

    # Validation errors
    VALIDATION_ERROR = "VALIDATION_ERROR"
    MISSING_PARAMETER = "MISSING_PARAMETER"
    INVALID_VALUE = "INVALID_VALUE"
    INVALID_FORMAT = "INVALID_FORMAT"
    INVALID_PARAMETER = "INVALID_PARAMETER"
    BUSINESS_RULE_VIOLATION = "BUSINESS_RULE_VIOLATION"

    # API errors
    API_ERROR = "API_ERROR"
    API_TIMEOUT = "API_TIMEOUT"
    API_RATE_LIMIT = "API_RATE_LIMIT"
    API_AUTHENTICATION = "API_AUTHENTICATION"
    API_AUTHORIZATION = "API_AUTHORIZATION"

    # UCM errors
    UCM_ERROR = "UCM_ERROR"
    UCM_UNAVAILABLE = "UCM_UNAVAILABLE"
    UCM_INTEGRATION_FAILED = "UCM_INTEGRATION_FAILED"
    UCM_CAPABILITY_MISSING = "UCM_CAPABILITY_MISSING"

    # Tool errors
    TOOL_ERROR = "TOOL_ERROR"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    ACTION_NOT_SUPPORTED = "ACTION_NOT_SUPPORTED"
    INTROSPECTION_ERROR = "INTROSPECTION_ERROR"
    PROCESSING_ERROR = "PROCESSING_ERROR"

    # Resource errors
    RESOURCE_ERROR = "RESOURCE_ERROR"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RESOURCE_CONFLICT = "RESOURCE_CONFLICT"
    RESOURCE_UNAVAILABLE = "RESOURCE_UNAVAILABLE"


# FastMCP-style structured error classes
class ToolError(Exception):
    """FastMCP-style tool error that provides structured, agent-friendly error messages.

    Error messages from ToolError are always sent to clients, regardless of
    mask_error_details setting, following FastMCP patterns.
    """

    def __init__(
        self,
        message: str,
        error_code: str = ErrorCodes.TOOL_ERROR,
        field: Optional[str] = None,
        value: Optional[Any] = None,
        suggestions: Optional[List[str]] = None,
        examples: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        """Initialize structured tool error.

        Args:
            message: Human-readable error message
            error_code: Machine-readable error code from ErrorCodes
            field: Field name that caused the error (if applicable)
            value: Invalid value that caused the error (if applicable)
            suggestions: List of actionable suggestions for fixing the error
            examples: Working examples to help resolve the error
            context: Additional context information
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.field = field
        self.value = value
        self.suggestions = suggestions or []
        self.examples = examples or {}
        self.context = context or {}


class ResourceError(ToolError):
    """FastMCP-style resource error for resource-specific operations.

    Error messages from ResourceError are always sent to clients, regardless of
    mask_error_details setting, following FastMCP patterns.
    """

    def __init__(
        self,
        message: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        error_code: str = ErrorCodes.RESOURCE_ERROR,
        **kwargs,
    ):
        """Initialize structured resource error.

        Args:
            message: Human-readable error message
            resource_type: Type of resource (e.g., 'product', 'alert', 'customer')
            resource_id: ID of the specific resource (if applicable)
            error_code: Machine-readable error code from ErrorCodes
            **kwargs: Additional arguments passed to ToolError
        """
        super().__init__(message, error_code, **kwargs)
        self.resource_type = resource_type
        self.resource_id = resource_id


# New exception hierarchy for standardized execution paths
class ToolExecutionError(Exception):
    """Base exception for tool execution errors."""

    def __init__(self, message: str, tool_name: str = "", action: str = ""):
        super().__init__(message)
        self.tool_name = tool_name
        self.action = action


class IntrospectionError(ToolExecutionError):
    """Exception for introspection layer failures."""

    def __init__(
        self,
        message: str,
        tool_name: str = "",
        action: str = "",
        original_error: Optional[Exception] = None,
    ):
        super().__init__(message, tool_name, action)
        self.original_error = original_error


class UCMError(ToolExecutionError):
    """Exception for UCM integration failures."""

    def __init__(
        self, message: str, tool_name: str = "", action: str = "", ucm_available: bool = False
    ):
        super().__init__(message, tool_name, action)
        self.ucm_available = ucm_available


class ToolNotFoundError(ToolExecutionError):
    """Exception for tool not found in registry."""

    pass


class UCMToolMixin:
    """Mixin class for standardized UCM integration across all MCP tools.

    This mixin provides a consistent interface for UCM integration that all
    tools should use to eliminate constructor pattern inconsistencies.
    """

    def __init__(self, ucm_helper=None, **kwargs):
        """Initialize UCM integration.

        Args:
            ucm_helper: UCM integration helper instance
            **kwargs: Additional arguments passed to parent classes
        """
        # Call parent constructor if it exists
        if hasattr(super(), "__init__"):
            super().__init__(**kwargs)

        # Store UCM helper with standardized name
        self.ucm_helper = ucm_helper

        # Log UCM integration status (only in verbose mode)
        import os

        startup_verbose = os.getenv("MCP_STARTUP_VERBOSE", "false").lower() == "true"

        if self.ucm_helper:
            if startup_verbose:
                from loguru import logger

                logger.info(f"🎯 {self.__class__.__name__}: UCM integration active")
        else:
            if startup_verbose:
                from loguru import logger

                logger.warning(
                    f"⚠️ {self.__class__.__name__}: No UCM integration (using static capabilities)"
                )

    def has_ucm_integration(self) -> bool:
        """Check if UCM integration is available.

        Returns:
            True if UCM helper is available, False otherwise
        """
        return self.ucm_helper is not None

    async def get_ucm_capabilities(self, resource_type: str) -> Optional[dict]:
        """Get capabilities from UCM if available.

        Args:
            resource_type: Resource type for capability lookup

        Returns:
            UCM capabilities dict or None if not available
        """
        if not self.ucm_helper:
            return None

        try:
            return await self.ucm_helper.ucm.get_capabilities(resource_type)
        except Exception as e:
            from loguru import logger

            logger.warning(f"Failed to get UCM capabilities for {resource_type}: {e}")
            return None


# Enhanced error formatting functions
def format_structured_error(
    error: Union[ToolError, ResourceError], include_debug_info: bool = False
) -> str:
    """Format a structured error into agent-friendly text.

    Args:
        error: ToolError or ResourceError instance
        include_debug_info: Whether to include debug information

    Returns:
        Formatted error text
    """
    # Start with error header
    text = f"**{error.error_code}**\n\n"
    text += f"**Message**: {error.message}\n\n"

    # Add field information if available
    if error.field:
        text += f"**Field**: `{error.field}`\n"
        if error.value is not None:
            text += f"**Invalid Value**: `{error.value}`\n"
        text += "\n"

    # Add resource information for ResourceError
    if isinstance(error, ResourceError):
        text += f"**Resource Type**: {error.resource_type}\n"
        if error.resource_id:
            text += f"**Resource ID**: {error.resource_id}\n"
        text += "\n"

    # Add suggestions if available
    if error.suggestions:
        text += "**Suggestions**:\n"
        for i, suggestion in enumerate(error.suggestions, 1):
            text += f"{i}. {suggestion}\n"
        text += "\n"

    # Add examples if available
    if error.examples:
        text += "**Examples**:\n"
        for example_type, example_value in error.examples.items():
            if isinstance(example_value, str):
                text += f"- **{example_type}**: `{example_value}`\n"
            elif isinstance(example_value, dict):
                text += f"- **{example_type}**:\n```json\n{example_value}\n```\n"
        text += "\n"

    # Add context information if available
    if error.context and include_debug_info:
        text += "**🔍 Debug Context**:\n"
        for key, value in error.context.items():
            text += f"- **{key}**: {value}\n"
        text += "\n"

    return text.strip()


def create_structured_validation_error(
    message: str,
    field: Optional[str] = None,
    value: Optional[Any] = None,
    suggestions: Optional[List[str]] = None,
    examples: Optional[Dict[str, Any]] = None,
) -> ToolError:
    """Create a structured validation error with helpful guidance.

    Args:
        message: Human-readable error message
        field: Field name that failed validation
        value: Invalid value that caused the error
        suggestions: List of actionable suggestions
        examples: Working examples to help fix the error

    Returns:
        ToolError instance with validation error details
    """
    return ToolError(
        message=message,
        error_code=ErrorCodes.VALIDATION_ERROR,
        field=field,
        value=value,
        suggestions=suggestions or [],
        examples=examples or {},
    )


def create_structured_missing_parameter_error(
    parameter_name: str, action: str, examples: Optional[Dict[str, Any]] = None
) -> ToolError:
    """Create a structured missing parameter error.

    Args:
        parameter_name: Name of the missing parameter
        action: Action that requires the parameter
        examples: Working examples showing correct usage

    Returns:
        ToolError instance with missing parameter details
    """
    return ToolError(
        message=f"Required parameter '{parameter_name}' is missing",
        error_code=ErrorCodes.MISSING_PARAMETER,
        field=parameter_name,
        suggestions=[
            f"Add the '{parameter_name}' parameter to your {action} request",
            f"Check the action documentation for required parameters",
            "Use get_examples() to see working examples",
        ],
        examples=examples or {},
    )


def create_resource_not_found_error(
    resource_type: str, resource_id: str, suggestions: Optional[List[str]] = None
) -> ResourceError:
    """Create a structured resource not found error.

    Args:
        resource_type: Type of resource that was not found
        resource_id: ID of the resource that was not found
        suggestions: List of actionable suggestions

    Returns:
        ResourceError instance with resource not found details
    """
    return ResourceError(
        message=f"{resource_type.title()} with ID '{resource_id}' not found",
        resource_type=resource_type,
        resource_id=resource_id,
        error_code=ErrorCodes.RESOURCE_NOT_FOUND,
        suggestions=suggestions
        or [
            f"Verify the {resource_type} ID is correct",
            f"Use list action to see available {resource_type}s",
            f"Check if the {resource_type} was deleted or moved",
        ],
    )


# Re-export for common use
__all__ = [
    "StandardErrorBuilder",
    "StandardErrorFormatter",
    "create_missing_parameter_error",
    "create_invalid_value_error",
    "create_validation_error",
    "create_api_error",
    "create_unknown_action_error",
    "handle_alert_tool_errors",
    "ValidationError",
    "InvalidInputError",
    "format_error_response",
    "ToolExecutionError",
    "IntrospectionError",
    "UCMError",
    "ToolNotFoundError",
    "UCMToolMixin",
    # New structured error classes and functions
    "ErrorCodes",
    "ToolError",
    "ResourceError",
    "format_structured_error",
    "create_structured_validation_error",
    "create_structured_missing_parameter_error",
    "create_resource_not_found_error",
]


def format_error_response(
    error: Exception, context: str = ""
) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
    """Format an exception as a standardized MCP error response.

    This function now supports both legacy ValidationError and new structured errors.

    Args:
        error: Exception to format
        context: Additional context for the error

    Returns:
        List containing formatted error response
    """
    # Handle new structured errors
    if isinstance(error, (ToolError, ResourceError)):
        formatted_text = format_structured_error(error, include_debug_info=False)
        return [TextContent(type="text", text=formatted_text)]

    # Handle legacy ValidationError
    if isinstance(error, ValidationError):
        error_builder = StandardErrorBuilder(error.message)
        # Access values from the details dictionary
        if hasattr(error, "details") and error.details.get("field"):
            error_builder.field(error.details["field"])
        if hasattr(error, "details") and error.details.get("expected"):
            error_builder.expected(error.details["expected"])
        if hasattr(error, "suggestions") and error.suggestions:
            error_builder.suggestions(error.suggestions)

        return [StandardErrorFormatter.format_for_mcp(error_builder.build())]

    # Enhanced API error handling - preserve validation details
    from ..client import ReveniumAPIError

    if isinstance(error, ReveniumAPIError):
        return _format_api_validation_error(error, context)

    # Check for wrapped ReveniumAPIError in ToolExecutionError
    if isinstance(error, ToolExecutionError):
        # Extract the original ReveniumAPIError from the wrapped error message
        error_message = str(error)
        # Check for various API validation error patterns
        api_error_patterns = [
            "Failed to decode hashed Id",
            "Unknown resource type",
            "HTTP 400:",
            "HTTP 401:",
            "HTTP 403:",
            "HTTP 404:",
            "HTTP 422:",
        ]

        if "Direct error:" in error_message and any(
            pattern in error_message for pattern in api_error_patterns
        ):
            # Extract the direct error part
            direct_error_match = error_message.split("Direct error: ", 1)
            if len(direct_error_match) > 1:
                direct_error_text = direct_error_match[1]
                # Determine status code from the error message
                status_code = 400  # Default to 400 for validation errors
                if "HTTP 401:" in direct_error_text:
                    status_code = 401
                elif "HTTP 403:" in direct_error_text:
                    status_code = 403
                elif "HTTP 404:" in direct_error_text:
                    status_code = 404
                elif "HTTP 422:" in direct_error_text:
                    status_code = 422

                # Create a synthetic ReveniumAPIError for enhanced processing
                synthetic_api_error = ReveniumAPIError(
                    message=direct_error_text,
                    status_code=status_code,
                    response_data={"wrapped_in": "ToolExecutionError"},
                )
                return _format_api_validation_error(synthetic_api_error, context)

    # Generic error formatting for other exceptions
    error_text = f"**TOOL_ERROR**\n\n"
    error_text += f"**Message**: {str(error)}\n\n"

    if context:
        error_text += f"**Context**: {context}\n\n"

    error_text += "**Suggestions**:\n"
    error_text += "1. Check the action parameters and try again\n"
    error_text += "2. Use get_capabilities() to see available actions\n"
    error_text += "3. Use get_examples() to see working examples\n"

    return [TextContent(type="text", text=error_text)]


def _format_api_validation_error(
    api_error: "ReveniumAPIError", context: str = ""
) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
    """Format ReveniumAPIError with enhanced validation context preservation.

    Args:
        api_error: ReveniumAPIError instance
        context: Additional context for the error

    Returns:
        List containing formatted error response with preserved validation details
    """
    error_message = api_error.message
    status_code = getattr(api_error, "status_code", None)
    response_data = getattr(api_error, "response_data", None)

    # Extract specific validation details from the error message
    validation_context = _extract_validation_context(error_message, status_code)

    # Build enhanced error response
    error_text = f"🚨 **API_VALIDATION_ERROR**\n\n"

    # Add user-friendly error message
    if validation_context["user_friendly_message"]:
        error_text += f"**Issue**: {validation_context['user_friendly_message']}\n\n"
    else:
        error_text += f"**Issue**: {error_message}\n\n"

    # Add specific field information if available
    if validation_context["field"]:
        error_text += f"**Field**: `{validation_context['field']}`\n"
        if validation_context["invalid_value"]:
            error_text += f"**Invalid Value**: `{validation_context['invalid_value']}`\n"
        error_text += "\n"

    # Add context if provided
    if context:
        error_text += f"**Context**: {context}\n\n"

    # Add specific suggestions based on error type
    error_text += "**💡 Specific Guidance**:\n"
    for suggestion in validation_context["suggestions"]:
        error_text += f"• {suggestion}\n"

    # Add examples if available
    if validation_context["examples"]:
        error_text += "\n**📝 Examples**:\n"
        for example in validation_context["examples"]:
            error_text += f"• {example}\n"

    # Add technical details in collapsible section
    error_text += f"\n<details><summary>Technical Details</summary>\n"
    error_text += f"**Status Code**: {status_code}\n"
    error_text += f"**Original Message**: {error_message}\n"
    if response_data:
        error_text += f"**Response Data**: {response_data}\n"
    error_text += "</details>"

    return [TextContent(type="text", text=error_text)]


def _extract_validation_context(error_message: str, status_code: int) -> dict:
    """Extract validation context from API error message.

    Args:
        error_message: Raw API error message
        status_code: HTTP status code

    Returns:
        Dictionary with validation context details
    """
    import re

    context = {
        "user_friendly_message": "",
        "field": "",
        "invalid_value": "",
        "suggestions": [],
        "examples": [],
    }

    # Handle specific validation error patterns
    if "Failed to decode hashed Id" in error_message:
        # Extract the invalid ID from the message
        id_match = re.search(r"Failed to decode hashed Id: \[([^\]]+)\]", error_message)
        invalid_id = id_match.group(1) if id_match else "unknown"

        context.update(
            {
                "user_friendly_message": f"Invalid ID format: '{invalid_id}' is not a valid resource identifier",
                "field": "resource_id",
                "invalid_value": invalid_id,
                "suggestions": [
                    "Use a valid resource ID from a previous list() or get() operation",
                    "Resource IDs are typically in format 'prefix_randomstring' (e.g., 'prod_abc123')",
                    "Use list() action to see all available resources and their valid IDs",
                    "Check that you're using the correct ID parameter name for this action",
                ],
                "examples": [
                    "Valid product ID: 'prod_abc123def456'",
                    "Valid subscription ID: 'sub_xyz789ghi012'",
                    "Use list() first: manage_products(action='list') to get valid IDs",
                ],
            }
        )

    elif "Unknown resource type" in error_message:
        # Extract the invalid resource type
        type_match = re.search(r"Unknown resource type: ([^\s]+)", error_message)
        invalid_type = type_match.group(1) if type_match else "unknown"

        context.update(
            {
                "user_friendly_message": f"Invalid resource type: '{invalid_type}' is not supported",
                "field": "resource_type",
                "invalid_value": invalid_type,
                "suggestions": [
                    "Use get_capabilities() to see all supported resource types",
                    "Common resource types: 'users', 'subscribers', 'organizations', 'teams'",
                    "Check the spelling and case of the resource type parameter",
                    "Resource types are case-sensitive and must match exactly",
                ],
                "examples": [
                    "Valid: resource_type='users'",
                    "Valid: resource_type='organizations'",
                    "Invalid: resource_type='user' (missing 's')",
                    "Use get_capabilities() to see the complete list",
                ],
            }
        )

    elif status_code == 400 and (
        "required" in error_message.lower() or "missing" in error_message.lower()
    ):
        context.update(
            {
                "user_friendly_message": "Required parameter is missing or invalid",
                "suggestions": [
                    "Check that all required parameters are provided",
                    "Use get_capabilities() to see required vs optional parameters",
                    "Verify parameter names are spelled correctly and use the right case",
                    "Use get_examples() to see working parameter combinations",
                ],
                "examples": [
                    "Use get_capabilities() to see required fields",
                    "Use get_examples() to see working templates",
                ],
            }
        )

    elif status_code == 401:
        context.update(
            {
                "user_friendly_message": "Authentication failed - invalid or missing API credentials",
                "suggestions": [
                    "Check that your API key is correctly configured",
                    "Verify that your team ID and owner ID are set properly",
                    "Ensure your API key has the necessary permissions",
                    "Contact your administrator if you need access",
                ],
            }
        )

    elif status_code == 403:
        context.update(
            {
                "user_friendly_message": "Access denied - insufficient permissions for this operation",
                "suggestions": [
                    "Contact your administrator to request the necessary permissions",
                    "Verify you're accessing resources within your organization",
                    "Check if your API key has the required scope for this action",
                ],
            }
        )

    elif status_code == 404:
        context.update(
            {
                "user_friendly_message": "Resource not found - the requested item doesn't exist",
                "suggestions": [
                    "Verify the resource ID is correct and exists",
                    "Use list() action to see all available resources",
                    "Check if the resource was deleted or moved",
                    "Ensure you have access to the resource",
                ],
            }
        )

    else:
        # Generic API error handling
        context.update(
            {
                "user_friendly_message": f"API request failed with status {status_code}",
                "suggestions": [
                    "Check your request parameters and try again",
                    "Use get_capabilities() to understand the expected format",
                    "Use get_examples() to see working examples",
                    "If the problem persists, contact support",
                ],
            }
        )

    return context
