"""Error handling utilities for manage capabilities tool.

This module provides error creation and formatting functions for the
manage_capabilities tool, following enterprise Python standards.
"""

from typing import Any, Dict, List

from loguru import logger

from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_structured_missing_parameter_error,
    create_structured_validation_error,
    format_structured_error,
)


def create_missing_resource_type_error() -> str:
    """Create error for missing resource_type parameter.

    Returns:
        Formatted error message
    """
    error = create_structured_missing_parameter_error(
        parameter_name="resource_type",
        action="get UCM capabilities",
        examples={
            "usage": "manage_capabilities(action='get_capabilities', resource_type='products')",
            "valid_resource_types": [
                "products",
                "subscriptions",
                "customers",
                "alerts",
                "sources",
                "metering_elements",
            ],
            "example_calls": [
                "manage_capabilities(action='get_capabilities', resource_type='products')",
                "manage_capabilities(action='get_capabilities', resource_type='alerts')",
            ],
            "system_context": "🔧 SYSTEM: UCM capabilities provide real-time configuration and validation data",
        },
    )
    return format_structured_error(error)


def create_missing_verify_params_error(missing_params: List[str]) -> str:
    """Create error for missing verify_capability parameters.

    Args:
        missing_params: List of missing parameter names

    Returns:
        Formatted error message
    """
    examples_data = get_verify_params_examples()
    suggestions = get_verify_params_suggestions()

    error = create_structured_validation_error(
        message=f"Missing required parameters for verify_capability: {', '.join(missing_params)}",
        field="verify_capability_parameters",
        value=f"missing: {', '.join(missing_params)}",
        suggestions=suggestions,
        examples=examples_data,
    )
    return format_structured_error(error)


def get_verify_params_examples() -> Dict[str, Any]:
    """Get examples for verify_capability parameters.

    Returns:
        Examples dictionary
    """
    return {
        "usage": "manage_capabilities(action='verify_capability', resource_type='products', capability_name='currencies', value='USD')",
        "required_parameters": ["resource_type", "capability_name", "value"],
        "system_context": "🔧 SYSTEM: UCM capability verification validates configuration values against API",
    }


def get_verify_params_suggestions() -> List[str]:
    """Get suggestions for verify_capability parameters.

    Returns:
        List of suggestions
    """
    return [
        "Provide all required parameters: resource_type, capability_name, and value",
        "Use get_capabilities() first to see available capabilities",
        "Check parameter spelling and format",
        "Ensure all parameters have non-empty values",
    ]


def create_unsupported_action_error(action: str) -> str:
    """Create error for unsupported action.

    Args:
        action: The unsupported action name

    Returns:
        Formatted error message
    """
    examples_data = get_unsupported_action_examples()
    suggestions = get_unsupported_action_suggestions()

    error = ToolError(
        message=f"Unknown action '{action}' is not supported",
        error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
        field="action",
        value=action,
        suggestions=suggestions,
        examples=examples_data,
    )
    return format_structured_error(error)


def get_unsupported_action_examples() -> Dict[str, Any]:
    """Get examples for unsupported action error.

    Returns:
        Examples dictionary
    """
    return {
        "supported_actions": [
            "get_capabilities",
            "get_examples",
            "verify_capability",
            "refresh_capabilities",
            "get_health_status",
        ],
        "system_context": "🔧 SYSTEM: UCM capability management provides real-time configuration validation",
    }


def get_unsupported_action_suggestions() -> List[str]:
    """Get suggestions for unsupported action error.

    Returns:
        List of suggestions
    """
    return [
        "Use one of the supported actions: get_capabilities, get_examples, verify_capability, refresh_capabilities, get_health_status",
        "Check the action name for typos",
        "Use get_capabilities() to see available UCM capabilities",
    ]


def create_execution_error(exception: Exception) -> str:
    """Create error for execution failures.

    Args:
        exception: The caught exception

    Returns:
        Formatted error message
    """
    logger.error(f"Error in manage_capabilities: {exception}")
    examples_data = get_execution_error_examples()
    suggestions = get_execution_error_suggestions()

    error = ToolError(
        message=f"UCM capability management failed: {str(exception)}",
        error_code=ErrorCodes.UCM_ERROR,
        field="manage_capabilities",
        value=str(exception),
        suggestions=suggestions,
        examples=examples_data,
    )
    return format_structured_error(error)


def get_execution_error_examples() -> Dict[str, Any]:
    """Get examples for execution error.

    Returns:
        Examples dictionary
    """
    return {
        "troubleshooting": ["Check UCM service status", "Verify authentication"],
        "system_context": "🔧 SYSTEM: UCM capability management provides real-time configuration validation",
    }


def get_execution_error_suggestions() -> List[str]:
    """Get suggestions for execution error.

    Returns:
        List of suggestions
    """
    return [
        "Check UCM service connectivity and authentication",
        "Verify UCM integration is working properly",
        "Try again after a few moments",
    ]
