"""Helper functions for error translation.

This module contains helper functions extracted from the main error translator
to maintain compliance with the 300-line limit per module.
"""

from datetime import datetime
from typing import Any, Dict, List, Type

# Import exception types
from ..exceptions import (
    APIConnectionError,
    ConfigurationError,
    InvalidInputError,
    OperationTimeoutError,
    PermissionError,
    ValidationError,
)


def create_structured_error_data(error, context, trace_id):
    """Create error data for structured errors."""
    # Import here to avoid circular imports
    from .error_handling import MCPErrorData

    # Extract existing error data
    suggestions = getattr(error, "suggestions", [])
    examples = getattr(error, "examples", {})
    field = getattr(error, "field", None)
    value = getattr(error, "value", None)

    # Create error data
    error_data = MCPErrorData(
        field=field,
        value=value,
        suggestions=suggestions,
        examples=examples,
        trace_id=trace_id,
        timestamp=datetime.now().isoformat(),
        context=context or {},
    )

    # Add recovery actions based on error type
    if hasattr(error, "__class__") and "ToolError" in error.__class__.__name__:
        error_data.recovery_actions = [
            "Check the tool action and parameters",
            "Use tool introspection to verify capabilities",
            "Refer to tool documentation for correct usage",
        ]
    elif hasattr(error, "__class__") and "ResourceError" in error.__class__.__name__:
        error_data.recovery_actions = [
            "Verify the resource URI is correct",
            "Check if the resource exists",
            "Use resource discovery to find available resources",
        ]

    return error_data


def create_known_error_data(exception, context, trace_id):
    """Create error data for known exception types."""
    # Import here to avoid circular imports
    from .error_handling import MCPErrorData

    # Extract suggestions if available
    suggestions = []
    if hasattr(exception, "suggestions"):
        suggestions = getattr(exception, "suggestions", [])

    # Extract field information if available
    field = getattr(exception, "field", None)
    value = getattr(exception, "value", None)
    expected = getattr(exception, "expected", None)

    # Create error data
    error_data = MCPErrorData(
        field=field,
        value=value,
        expected=expected,
        suggestions=suggestions,
        trace_id=trace_id,
        timestamp=datetime.now().isoformat(),
        context=context or {},
    )

    # Add type-specific recovery actions
    error_data.recovery_actions = get_default_recovery_actions(type(exception))

    return error_data


def get_recovery_actions_mapping() -> Dict[Type[Exception], List[str]]:
    """Get mapping of exception types to recovery actions."""
    return {
        ValidationError: [
            "Check the input parameters are correct",
            "Verify required fields are provided",
            "Ensure data types match expected formats",
        ],
        InvalidInputError: [
            "Review the input data format",
            "Check for missing or invalid fields",
            "Refer to the API documentation for correct format",
        ],
        APIConnectionError: [
            "Check your internet connection",
            "Verify the API endpoint is accessible",
            "Try again in a few moments",
        ],
        PermissionError: [
            "Verify you have the required permissions",
            "Check your authentication credentials",
            "Contact your administrator for access",
        ],
        ConfigurationError: [
            "Check the server configuration",
            "Verify environment variables are set correctly",
            "Contact support if configuration issues persist",
        ],
        OperationTimeoutError: [
            "Try the operation again",
            "Check if the server is experiencing high load",
            "Consider breaking large operations into smaller parts",
        ],
    }


def get_default_recovery_actions(exception_type: Type[Exception]) -> List[str]:
    """Get default recovery actions for unknown exception types."""
    recovery_map = get_recovery_actions_mapping()

    # Check inheritance hierarchy
    for mapped_type, actions in recovery_map.items():
        try:
            if issubclass(exception_type, mapped_type):
                return actions
        except TypeError:
            # Handle cases where exception_type is not a class
            continue

    # Default recovery actions
    return [
        "Try the operation again",
        "Check the input parameters",
        "Contact support if the problem persists",
    ]
