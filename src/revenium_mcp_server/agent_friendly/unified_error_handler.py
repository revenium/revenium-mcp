"""Unified Error Handling Framework for MCP Tools.

This module provides a comprehensive, standardized error handling framework
that ensures consistent, actionable error messages across all MCP tools.
"""

import time
from typing import Any, Dict, List, Optional, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from .standard_formatter import UnifiedResponseFormatter


class ErrorSeverity:
    """Error severity levels."""

    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ErrorCategory:
    """Error categories for better organization."""

    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    RATE_LIMIT = "rate_limit"
    API_ERROR = "api_error"
    CONFIGURATION = "configuration"
    BUSINESS_RULE = "business_rule"
    SYSTEM = "system"


class StandardizedError:
    """Standardized error object with comprehensive information."""

    def __init__(
        self,
        message: str,
        error_code: str,
        category: str = ErrorCategory.SYSTEM,
        severity: str = ErrorSeverity.ERROR,
        field_errors: Optional[Dict[str, str]] = None,
        suggestions: Optional[List[str]] = None,
        examples: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        documentation_url: Optional[str] = None,
        recovery_actions: Optional[List[str]] = None,
    ):
        """Initialize standardized error.

        Args:
            message: Human-readable error message
            error_code: Machine-readable error code
            category: Error category for classification
            severity: Error severity level
            field_errors: Field-specific error messages
            suggestions: Actionable suggestions to fix the error
            examples: Working examples to help resolve the error
            context: Additional context information
            documentation_url: Link to relevant documentation
            recovery_actions: Specific recovery actions to try
        """
        self.message = message
        self.error_code = error_code
        self.category = category
        self.severity = severity
        self.field_errors = field_errors or {}
        self.suggestions = suggestions or []
        self.examples = examples or {}
        self.context = context or {}
        self.documentation_url = documentation_url
        self.recovery_actions = recovery_actions or []
        self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary format."""
        return {
            "error": True,
            "error_code": self.error_code,
            "category": self.category,
            "severity": self.severity,
            "message": self.message,
            "field_errors": self.field_errors,
            "suggestions": self.suggestions,
            "examples": self.examples,
            "context": self.context,
            "documentation_url": self.documentation_url,
            "recovery_actions": self.recovery_actions,
            "timestamp": self.timestamp,
        }


class UnifiedErrorHandler:
    """Unified error handler for all MCP tools."""

    def __init__(self, tool_name: str):
        """Initialize error handler for a specific tool.

        Args:
            tool_name: Name of the tool using this error handler
        """
        self.tool_name = tool_name
        self.formatter = UnifiedResponseFormatter(tool_name)

    def create_validation_error(
        self,
        message: str,
        field_errors: Optional[Dict[str, str]] = None,
        suggestions: Optional[List[str]] = None,
        examples: Optional[Dict[str, Any]] = None,
    ) -> StandardizedError:
        """Create a validation error with field-specific guidance.

        Args:
            message: Main validation error message
            field_errors: Field-specific error messages
            suggestions: Actionable suggestions
            examples: Working examples

        Returns:
            Standardized validation error
        """
        default_suggestions = [
            "Check the field values against the expected format",
            "Use get_capabilities() to see valid options",
            "Use get_examples() to see working configurations",
            "Use validate() with dry_run=True to test your configuration",
        ]

        return StandardizedError(
            message=message,
            error_code="VALIDATION_ERROR",
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.ERROR,
            field_errors=field_errors,
            suggestions=suggestions or default_suggestions,
            examples=examples,
            recovery_actions=[
                "Fix the validation errors listed above",
                "Retry the operation with corrected data",
            ],
        )

    def create_missing_parameter_error(
        self,
        parameter_name: str,
        valid_values: Optional[List[str]] = None,
        examples: Optional[Dict[str, Any]] = None,
    ) -> StandardizedError:
        """Create error for missing required parameter.

        Args:
            parameter_name: Name of the missing parameter
            valid_values: List of valid values for the parameter
            examples: Working examples

        Returns:
            Standardized missing parameter error
        """
        suggestions = [
            f"Provide the '{parameter_name}' parameter in your request",
            "Check the API documentation for required parameters",
            "Use get_capabilities() to see all required parameters",
        ]

        if valid_values:
            suggestions.append(f"Valid values for {parameter_name}: {', '.join(valid_values)}")

        field_errors = {parameter_name: "This parameter is required"}

        if not examples and valid_values:
            examples = {
                "valid_request": {
                    parameter_name: valid_values[0] if valid_values else "example_value"
                }
            }

        return StandardizedError(
            message=f"Missing required parameter: {parameter_name}",
            error_code="MISSING_PARAMETER",
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.ERROR,
            field_errors=field_errors,
            suggestions=suggestions,
            examples=examples,
            recovery_actions=[
                f"Add the '{parameter_name}' parameter to your request",
                "Retry the operation with the required parameter",
            ],
        )

    def create_invalid_value_error(
        self,
        parameter_name: str,
        provided_value: Any,
        valid_values: Optional[List[str]] = None,
        expected_format: Optional[str] = None,
        examples: Optional[Dict[str, Any]] = None,
    ) -> StandardizedError:
        """Create error for invalid parameter value.

        Args:
            parameter_name: Name of the parameter
            provided_value: Invalid value that was provided
            valid_values: List of valid values
            expected_format: Expected format description
            examples: Working examples

        Returns:
            Standardized invalid value error
        """
        if valid_values:
            message = f"Invalid value '{provided_value}' for parameter '{parameter_name}'. Valid values: {', '.join(valid_values)}"
        elif expected_format:
            message = f"Invalid value '{provided_value}' for parameter '{parameter_name}'. Expected format: {expected_format}"
        else:
            message = f"Invalid value '{provided_value}' for parameter '{parameter_name}'"

        suggestions = [
            f"Use a valid value for '{parameter_name}'",
            "Check the parameter documentation for valid options",
            "Use get_capabilities() to see valid values",
        ]

        if valid_values:
            suggestions.append(f"Try one of: {', '.join(valid_values)}")

        field_errors = {
            parameter_name: f"Invalid value '{provided_value}'. "
            + (
                f"Valid values: {', '.join(valid_values)}"
                if valid_values
                else f"Expected format: {expected_format}" if expected_format else "Invalid value"
            )
        }

        if not examples and valid_values:
            examples = {"valid_request": {parameter_name: valid_values[0]}}

        return StandardizedError(
            message=message,
            error_code="INVALID_VALUE",
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.ERROR,
            field_errors=field_errors,
            suggestions=suggestions,
            examples=examples,
            recovery_actions=[
                f"Change '{parameter_name}' to a valid value",
                "Retry the operation with the corrected parameter",
            ],
        )

    def create_api_error(
        self,
        status_code: int,
        message: str,
        endpoint: Optional[str] = None,
        response_data: Optional[Dict[str, Any]] = None,
    ) -> StandardizedError:
        """Create error for API-related issues.

        Args:
            status_code: HTTP status code
            message: Error message from API
            endpoint: API endpoint that failed
            response_data: Additional response data

        Returns:
            Standardized API error
        """
        error_message = f"API Error ({status_code}): {message}"
        if endpoint:
            error_message += f" [Endpoint: {endpoint}]"

        suggestions = []
        recovery_actions = []

        if status_code == 400:
            suggestions.extend(
                [
                    "Check your request parameters for validity",
                    "Ensure all required fields are provided",
                    "Use validate() to test your configuration before submitting",
                ]
            )
            recovery_actions.extend(["Fix the request parameters", "Retry with valid data"])
        elif status_code == 401:
            suggestions.extend(
                [
                    "Check your API credentials",
                    "Verify your authentication token is valid",
                    "Ensure you have the correct permissions",
                ]
            )
            recovery_actions.extend(["Update your API credentials", "Re-authenticate and retry"])
        elif status_code == 403:
            suggestions.extend(
                [
                    "Verify you have permission for this operation",
                    "Check your team membership and role",
                    "Contact your administrator for access",
                ]
            )
        elif status_code == 404:
            suggestions.extend(
                [
                    "Verify the resource ID exists",
                    "Check if the resource was deleted",
                    "Use list() to see available resources",
                ]
            )
        elif status_code == 429:
            suggestions.extend(
                [
                    "Wait before retrying the request",
                    "Reduce the frequency of your requests",
                    "Consider implementing exponential backoff",
                ]
            )
            recovery_actions.extend(
                ["Wait 60 seconds and retry", "Implement rate limiting in your application"]
            )
        elif status_code >= 500:
            suggestions.extend(
                [
                    "This is a server error - try again in a few moments",
                    "Check the service status page",
                    "Contact support if the issue persists",
                ]
            )
            recovery_actions.extend(
                [
                    "Retry the operation after a short delay",
                    "Contact support if the error continues",
                ]
            )

        context = {"status_code": status_code}
        if endpoint:
            context["endpoint"] = endpoint
        if response_data:
            context["response_data"] = response_data

        return StandardizedError(
            message=error_message,
            error_code=f"API_ERROR_{status_code}",
            category=ErrorCategory.API_ERROR,
            severity=ErrorSeverity.ERROR if status_code < 500 else ErrorSeverity.CRITICAL,
            suggestions=suggestions,
            context=context,
            recovery_actions=recovery_actions,
        )

    def format_error_response(
        self, error: StandardizedError
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format error as standardized MCP response.

        Args:
            error: Standardized error to format

        Returns:
            Formatted error response
        """
        return self.formatter.format_error_response(
            message=error.message,
            error_code=error.error_code,
            field_errors=error.field_errors,
            suggestions=error.suggestions,
            examples=error.examples,
            context=error.context,
        )

    def handle_exception(
        self, exception: Exception, operation: str, context: Optional[Dict[str, Any]] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle any exception and convert to standardized error response.

        Args:
            exception: Exception that occurred
            operation: Operation that was being performed
            context: Additional context information

        Returns:
            Formatted error response
        """
        logger.error(f"Exception in {self.tool_name}.{operation}: {exception}")

        # Handle known exception types
        if hasattr(exception, "error_code") and hasattr(exception, "message"):
            # Already a standardized error
            if isinstance(exception, StandardizedError):
                return self.format_error_response(exception)

            # Convert from other error types
            error = StandardizedError(
                message=getattr(exception, "message", str(exception)),
                error_code=getattr(exception, "error_code", "UNKNOWN_ERROR"),
                category=getattr(exception, "category", ErrorCategory.SYSTEM),
                suggestions=getattr(exception, "suggestions", []),
                context=context or {},
            )
        else:
            # Generic exception handling
            error = StandardizedError(
                message=f"Unexpected error in {operation}: {str(exception)}",
                error_code="UNEXPECTED_ERROR",
                category=ErrorCategory.SYSTEM,
                severity=ErrorSeverity.CRITICAL,
                suggestions=[
                    "Try the operation again",
                    "Check your input parameters",
                    "Contact support if the issue persists",
                ],
                context=context or {},
                recovery_actions=[
                    "Retry the operation",
                    "Check system status",
                    "Contact technical support",
                ],
            )

        return self.format_error_response(error)


def with_error_handling(tool_name: str):
    """Decorator to add standardized error handling to tool methods.

    Args:
        tool_name: Name of the tool for error context

    Returns:
        Decorator function
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            error_handler = UnifiedErrorHandler(tool_name)
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                operation = func.__name__
                context = {
                    "function": operation,
                    "args_count": len(args),
                    "kwargs_keys": list(kwargs.keys()),
                }
                return error_handler.handle_exception(e, operation, context)

        return wrapper

    return decorator
