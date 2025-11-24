"""Common validation utilities.

This module provides shared validation functions used across the MCP server.
"""

from typing import Any, Dict, List, Union, Type
from ..validators import InputValidator
from ..exceptions import ValidationError

# Re-export common validation functions
__all__ = [
    "InputValidator",
    "ValidationError",
    "validate_required_params",
    "validate_id_format",
    "preprocess_numeric_parameters",
    "preprocess_boolean_parameters",
]


def validate_required_params(params: Dict[str, Any], required_fields: List[str]) -> None:
    """Validate that required parameters are present.

    Args:
        params: Dictionary of parameters to validate
        required_fields: List of required field names

    Raises:
        ValidationError: If any required field is missing
    """
    missing_fields = [field for field in required_fields if field not in params or params[field] is None]

    if missing_fields:
        raise ValidationError(
            message=f"Missing required parameters: {', '.join(missing_fields)}",
            field="parameters",
            expected=f"Required fields: {', '.join(required_fields)}"
        )


def validate_id_format(id_value: Any, field_name: str = "id") -> str:
    """Validate ID format and convert to string.

    Args:
        id_value: ID value to validate
        field_name: Name of the field for error messages

    Returns:
        Validated ID as string

    Raises:
        ValidationError: If ID format is invalid
    """
    if not id_value:
        raise ValidationError(
            message=f"{field_name} cannot be empty",
            field=field_name,
            expected="Non-empty string or number"
        )

    # Convert to string and validate
    id_str = str(id_value).strip()
    if not id_str:
        raise ValidationError(
            message=f"{field_name} cannot be empty after conversion",
            field=field_name,
            expected="Non-empty string or number"
        )

    return id_str


def preprocess_numeric_parameters(
    arguments: Dict[str, Any],
    numeric_params: Dict[str, Type[Union[int, float]]]
) -> Dict[str, Any]:
    """Convert string numeric parameters to appropriate types.

    Handles string-to-numeric conversion for MCP tool parameters, gracefully
    handling conversion errors by keeping invalid strings as-is for downstream
    error handling.

    Args:
        arguments: Dictionary of tool arguments to process
        numeric_params: Mapping of parameter names to target types (int or float)

    Returns:
        Processed arguments dictionary with converted numeric parameters

    Example:
        >>> args = {"page": "1", "size": "10", "threshold": "99.5", "name": "test"}
        >>> numeric_map = {"page": int, "size": int, "threshold": float}
        >>> result = preprocess_numeric_parameters(args, numeric_map)
        >>> result
        {"page": 1, "size": 10, "threshold": 99.5, "name": "test"}
    """
    processed_args = arguments.copy()

    for param_name, param_type in numeric_params.items():
        if param_name in processed_args and processed_args[param_name] is not None:
            value = processed_args[param_name]
            if isinstance(value, str):
                try:
                    processed_args[param_name] = param_type(value)
                except (ValueError, TypeError):
                    # Keep as string if conversion fails - let tool handle the error
                    pass

    return processed_args


def preprocess_boolean_parameters(
    arguments: Dict[str, Any],
    boolean_params: List[str]
) -> Dict[str, Any]:
    """Convert string boolean parameters to actual boolean values.

    Handles string-to-boolean conversion for MCP tool parameters, supporting
    common string representations of boolean values.

    Args:
        arguments: Dictionary of tool arguments to process
        boolean_params: List of parameter names that should be converted to booleans

    Returns:
        Processed arguments dictionary with converted boolean parameters

    Example:
        >>> args = {"enabled": "true", "debug": "false", "count": "5", "name": "test"}
        >>> boolean_list = ["enabled", "debug"]
        >>> result = preprocess_boolean_parameters(args, boolean_list)
        >>> result
        {"enabled": True, "debug": False, "count": "5", "name": "test"}
    """
    processed_args = arguments.copy()

    for param_name in boolean_params:
        if param_name in processed_args and processed_args[param_name] is not None:
            value = processed_args[param_name]
            if isinstance(value, str):
                # Convert string to boolean using common representations
                lower_value = value.lower().strip()
                if lower_value in ('true', '1', 'yes', 'on', 'enabled'):
                    processed_args[param_name] = True
                elif lower_value in ('false', '0', 'no', 'off', 'disabled'):
                    processed_args[param_name] = False
                # Keep as string if not a recognized boolean value - let tool handle the error

    return processed_args


def preprocess_array_parameters(
    arguments: Dict[str, Any],
    array_params: List[str]
) -> Dict[str, Any]:
    """Convert string array parameters to actual Python lists.

    Handles string-to-array conversion for MCP tool parameters, supporting
    JSON string representations of arrays that need to be converted to Python lists.

    Args:
        arguments: Dictionary of tool arguments to process
        array_params: List of parameter names that should be converted to arrays

    Returns:
        Processed arguments dictionary with converted array parameters

    Example:
        >>> args = {"include_dimensions": '["providers", "models"]', "transaction_ids": '["tx_123"]', "name": "test"}
        >>> array_list = ["include_dimensions", "transaction_ids"]
        >>> result = preprocess_array_parameters(args, array_list)
        >>> result
        {"include_dimensions": ["providers", "models"], "transaction_ids": ["tx_123"], "name": "test"}
    """
    import json

    processed_args = arguments.copy()

    for param_name in array_params:
        if param_name in processed_args and processed_args[param_name] is not None:
            value = processed_args[param_name]
            if isinstance(value, str):
                try:
                    # Try to parse as JSON array
                    parsed_value = json.loads(value)
                    if isinstance(parsed_value, list):
                        processed_args[param_name] = parsed_value
                    # Keep as string if not a list - let tool handle the error
                except (json.JSONDecodeError, ValueError):
                    # Keep as string if JSON parsing fails - let tool handle the error
                    pass
            # If it's already a list, keep it as-is

    return processed_args
