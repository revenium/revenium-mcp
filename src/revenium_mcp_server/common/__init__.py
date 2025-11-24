"""Common Utilities Package.

This package contains shared utilities used across the MCP server.
Includes validation, pagination, error handling, and formatting utilities.
"""

from .error_handling import (
    StandardErrorBuilder,
    StandardErrorFormatter,
    create_api_error,
    create_invalid_value_error,
    create_missing_parameter_error,
    create_unknown_action_error,
    create_validation_error,
    format_error_response,
)
from .formatting import format_json_response, format_list_response, format_success_response

# Note: PaginationHelper and QueryCache are imported directly from ..pagination to avoid circular imports
from .validation import (
    InputValidator,
    ValidationError,
    validate_id_format,
    validate_required_params,
)

__all__ = [
    # Validation
    "InputValidator",
    "ValidationError",
    "validate_required_params",
    "validate_id_format",
    # Error handling
    "StandardErrorBuilder",
    "StandardErrorFormatter",
    "format_error_response",
    "create_missing_parameter_error",
    "create_invalid_value_error",
    "create_validation_error",
    "create_api_error",
    "create_unknown_action_error",
    # Formatting
    "format_json_response",
    "format_list_response",
    "format_success_response",
]
