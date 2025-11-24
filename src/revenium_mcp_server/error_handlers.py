"""Error handling decorators and utilities for Alert & Anomaly Management Tools.

This module provides decorators and utilities for standardizing error handling
across all alert and anomaly management operations.
"""

import functools
import traceback
from typing import Any, Callable, Dict, List, Optional, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from .exceptions import (
    AlertNotFoundError,
    AlertToolsError,
    AnomalyNotFoundError,
    APIConnectionError,
    InvalidInputError,
    OperationTimeoutError,
    PermissionError,
    ValidationError,
)


def handle_alert_tool_errors(operation_name: str):
    """Decorator to handle errors in alert tool operations.

    Args:
        operation_name: Name of the operation for logging and error context

    Returns:
        Decorator function
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(
            *args, **kwargs
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            try:
                return await func(*args, **kwargs)

            except AlertToolsError as e:
                # Handle our custom exceptions with rich formatting
                logger.error(f"Alert tools error in {operation_name}: {e.to_dict()}")
                return [TextContent(type="text", text=e.format_user_message())]

            except ValidationError as e:
                # Handle ValidationError using its built-in formatting to avoid duplication
                logger.error(f"Validation error in {operation_name}: {e}")
                return [
                    TextContent(
                        type="text",
                        text=e.format_user_message(),
                    )
                ]

            except PermissionError as e:
                # Handle permission errors
                logger.error(f"Permission error in {operation_name}: {e}")
                return [
                    TextContent(
                        type="text",
                        text=(
                            "🔒 **Permission Denied**\n\n"
                            "You don't have permission to perform this operation.\n\n"
                            "**Suggestions:**\n"
                            "• Check your API key and team permissions\n"
                            "• Verify you're using the correct team ID\n"
                            "• Contact your administrator for access"
                        ),
                    )
                ]

            except ConnectionError as e:
                # Handle network connection errors
                logger.error(f"Connection error in {operation_name}: {e}")
                return [
                    TextContent(
                        type="text",
                        text=(
                            "🌐 **Connection Error**\n\n"
                            "Unable to connect to the API service.\n\n"
                            "**Suggestions:**\n"
                            "• Check your internet connection\n"
                            "• Verify the API endpoint is accessible\n"
                            "• Try again in a few moments\n"
                            "• Check if there are any service outages"
                        ),
                    )
                ]

            except TimeoutError as e:
                # Handle timeout errors
                logger.error(f"Timeout error in {operation_name}: {e}")
                return [
                    TextContent(
                        type="text",
                        text=(
                            "⏱️ **Operation Timeout**\n\n"
                            "The operation took too long to complete.\n\n"
                            "**Suggestions:**\n"
                            "• Try the operation again\n"
                            "• Check your network connection\n"
                            "• Consider breaking large operations into smaller chunks\n"
                            "• Contact support if the issue persists"
                        ),
                    )
                ]

            except ValueError as e:
                # Handle value errors (invalid parameters, etc.)
                logger.error(f"Value error in {operation_name}: {e}")
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"❌ **Invalid Value**\n\n"
                            f"{str(e)}\n\n"
                            f"**Suggestions:**\n"
                            f"• Check the parameter values and types\n"
                            f"• Ensure all values are within valid ranges\n"
                            f"• Refer to the API documentation for valid formats"
                        ),
                    )
                ]

            except KeyError as e:
                # Handle missing required keys
                logger.error(f"Key error in {operation_name}: {e}")
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"❌ **Missing Required Field**\n\n"
                            f"Required field {str(e)} is missing.\n\n"
                            f"**Suggestions:**\n"
                            f"• Check that all required parameters are provided\n"
                            f"• Verify the parameter names are correct\n"
                            f"• Refer to the API documentation for required fields"
                        ),
                    )
                ]

            except Exception as e:
                # Handle unexpected errors with full traceback logging
                error_id = f"{operation_name}_{hash(str(e)) % 10000:04d}"
                logger.error(
                    f"Unexpected error in {operation_name} (ID: {error_id}): {e}\n"
                    f"Traceback: {traceback.format_exc()}"
                )

                return [
                    TextContent(
                        type="text",
                        text=(
                            f"**Unexpected Error**\n\n"
                            f"An unexpected error occurred during the operation.\n\n"
                            f"**Error ID:** `{error_id}`\n"
                            f"**Error:** {str(e)}\n\n"
                            f"**Suggestions:**\n"
                            f"• Try the operation again\n"
                            f"• Check your input parameters\n"
                            f"• Contact support with the Error ID if the issue persists\n"
                            f"• Check the system logs for more details"
                        ),
                    )
                ]

        return wrapper

    return decorator


def translate_http_error(
    status_code: int, response_text: str, endpoint: str, error_data: Optional[Dict[str, Any]] = None
) -> AlertToolsError:
    """Translate HTTP errors into custom exceptions.

    Args:
        status_code: HTTP status code
        response_text: Response body text
        endpoint: API endpoint that failed
        error_data: Parsed error response data (optional)

    Returns:
        Appropriate custom exception
    """
    # Extract more specific error information if available
    error_message = response_text
    if error_data and isinstance(error_data, dict):
        if "message" in error_data:
            error_message = error_data["message"]
        elif "error" in error_data:
            error_info = error_data["error"]
            if isinstance(error_info, dict) and "message" in error_info:
                error_message = error_info["message"]
            else:
                error_message = str(error_info)

    if status_code == 400:
        # Use user-friendly error translation
        friendly_error = UserFriendlyErrorTranslator.format_user_friendly_error(
            error_message, error_data
        )

        return ValidationError(
            message=friendly_error,
            field="request",
            value=response_text[:100] if response_text else "unknown",
            expected="Valid request parameters",
        )

    elif status_code == 401:
        return PermissionError(operation="API access", resource=endpoint)

    elif status_code == 403:
        return PermissionError(operation="resource access", resource=endpoint)

    elif status_code == 404:
        # Try to determine if it's an anomaly or alert based on endpoint
        if "/anomaly/" in endpoint:
            # Extract anomaly ID from endpoint
            anomaly_id = endpoint.split("/anomaly/")[-1].split("/")[0]
            return AnomalyNotFoundError(anomaly_id)
        elif "/alert/" in endpoint:
            # Extract alert ID from endpoint
            alert_id = endpoint.split("/alert/")[-1].split("/")[0]
            return AlertNotFoundError(alert_id)
        else:
            return APIConnectionError(endpoint, status_code, response_text)

    elif status_code == 408:
        return OperationTimeoutError(
            operation=f"API call to {endpoint}", timeout_seconds=30  # Default timeout
        )

    elif status_code == 422:
        # Use user-friendly error translation for validation errors
        friendly_error = UserFriendlyErrorTranslator.format_user_friendly_error(
            error_message, error_data
        )

        return ValidationError(
            message=friendly_error,
            field="request_data",
            value=response_text[:100] if response_text else "unknown",
            expected="Valid request data format",
        )

    elif status_code == 429:
        return APIConnectionError(
            endpoint=endpoint, status_code=status_code, response_text="Rate limit exceeded"
        )

    elif status_code >= 500:
        return APIConnectionError(
            endpoint=endpoint, status_code=status_code, response_text="Server error"
        )

    else:
        return APIConnectionError(
            endpoint=endpoint, status_code=status_code, response_text=response_text
        )


def validate_required_params(params: dict, required: list) -> None:
    """Validate that required parameters are present.

    Args:
        params: Dictionary of parameters
        required: List of required parameter names

    Raises:
        ValidationError: If any required parameters are missing
    """
    missing = [param for param in required if param not in params or params[param] is None]

    if missing:
        raise ValidationError(
            message=f"Missing required parameters: {', '.join(missing)}",
            field="parameters",
            value=str(list(params.keys())),
            expected=f"Required parameters: {', '.join(missing)}",
        )


def validate_anomaly_id(anomaly_id: Any) -> str:
    """Validate and normalize anomaly ID.

    Args:
        anomaly_id: Anomaly ID to validate

    Returns:
        Validated anomaly ID as string

    Raises:
        InvalidInputError: If anomaly ID is invalid
    """
    if not anomaly_id:
        raise InvalidInputError(
            parameter="anomaly_id", value=anomaly_id, reason="Anomaly ID cannot be empty"
        )

    anomaly_id_str = str(anomaly_id).strip()

    if not anomaly_id_str:
        raise InvalidInputError(
            parameter="anomaly_id",
            value=anomaly_id,
            reason="Anomaly ID cannot be empty or whitespace",
        )

    if len(anomaly_id_str) > 100:
        raise InvalidInputError(
            parameter="anomaly_id",
            value=anomaly_id,
            reason="Anomaly ID is too long (max 100 characters)",
        )

    return anomaly_id_str


def validate_alert_id(alert_id: Any) -> str:
    """Validate and normalize alert ID.

    Args:
        alert_id: Alert ID to validate

    Returns:
        Validated alert ID as string

    Raises:
        InvalidInputError: If alert ID is invalid
    """
    if not alert_id:
        raise InvalidInputError(
            parameter="alert_id", value=alert_id, reason="Alert ID cannot be empty"
        )

    alert_id_str = str(alert_id).strip()

    if not alert_id_str:
        raise InvalidInputError(
            parameter="alert_id", value=alert_id, reason="Alert ID cannot be empty or whitespace"
        )

    if len(alert_id_str) > 100:
        raise InvalidInputError(
            parameter="alert_id", value=alert_id, reason="Alert ID is too long (max 100 characters)"
        )

    return alert_id_str


def validate_pagination_params(page: Any, size: Any) -> tuple[int, int]:
    """Validate pagination parameters.

    Args:
        page: Page number
        size: Page size

    Returns:
        Tuple of (validated_page, validated_size)

    Raises:
        InvalidInputError: If pagination parameters are invalid
    """
    try:
        page_int = int(page) if page is not None else 0
        size_int = int(size) if size is not None else 20
    except (ValueError, TypeError):
        raise InvalidInputError(
            parameter="pagination",
            value=f"page={page}, size={size}",
            reason="Page and size must be integers",
        )

    if page_int < 0:
        raise InvalidInputError(
            parameter="page", value=page_int, reason="Page number cannot be negative"
        )

    if size_int <= 0:
        raise InvalidInputError(
            parameter="size", value=size_int, reason="Page size must be positive"
        )

    if size_int > 1000:
        raise InvalidInputError(
            parameter="size", value=size_int, reason="Page size cannot exceed 1000"
        )

    return page_int, size_int


class UserFriendlyErrorTranslator:
    """Translates API errors into user-friendly messages with contextual help."""

    # Mapping of API error patterns to user-friendly messages
    ERROR_TRANSLATIONS = {
        # JSON format errors
        "invalid json format": {
            "message": "Invalid JSON data format",
            "help": "The alert data could not be processed due to formatting issues. This often happens when required fields are missing or have invalid values.",
            "example": "Use convenience methods: create_threshold_alert(name='Alert', threshold=100) or create_cumulative_usage_alert(name='Budget', threshold=1000, period='monthly')",
        },
        "json.*format": {
            "message": "JSON formatting error",
            "help": "The request data has formatting issues. Check that all required fields are provided with valid values.",
            "example": "Required fields: name, alertType, metricType, operatorType, threshold",
        },
        # Invalid ID errors
        "failed to decode hashed id": {
            "message": "Invalid anomaly ID",
            "help": "The provided anomaly ID is not valid or does not exist. Anomaly IDs are short alphanumeric codes like 'X5oon5' or 'mvMYRv'.",
            "example": "Use list(resource_type='anomalies') to get valid anomaly IDs, then use the ID from the results",
        },
        "decode.*hashed.*id": {
            "message": "Invalid anomaly ID format",
            "help": "The anomaly ID format is incorrect. Valid IDs are short alphanumeric codes generated by the system.",
            "example": "Valid ID examples: 'X5oon5', 'mvMYRv', 'GlkRbv' - get these from list operations",
        },
        # Field validation errors
        "name.*required": {
            "message": "Alert name is required",
            "help": "Please provide a descriptive name for your alert (e.g., 'High Cost Alert')",
            "example": "name: 'Cost Threshold Alert'",
        },
        "teamId.*required": {
            "message": "Team ID is required",
            "help": "The team ID identifies which team this alert belongs to",
            "example": "This is automatically set from your authentication",
        },
        "alertType.*required": {
            "message": "Alert type is required",
            "help": "Specify the type of alert you want to create",
            "example": "alertType: 'THRESHOLD' (for threshold-based alerts)",
        },
        "metricType.*required": {
            "message": "Metric type is required",
            "help": "Choose which metric to monitor for this alert",
            "example": "metricType: 'COST_PER_TRANSACTION' or 'TOTAL_COST'",
        },
        "operator.*required": {
            "message": "Comparison operator is required",
            "help": "Specify how to compare the metric value against your threshold",
            "example": "operator: 'GREATER_THAN' (alert when metric exceeds threshold)",
        },
        "threshold.*required": {
            "message": "Threshold value is required",
            "help": "Set the threshold value that triggers the alert",
            "example": "threshold: 0.05 (alert when cost exceeds $0.05)",
        },
        "notificationAddresses.*required": {
            "message": "At least one notification email is required",
            "help": "Provide email addresses to receive alert notifications",
            "example": "notificationAddresses: ['admin@company.com']",
        },
        "periodDuration.*required": {
            "message": "Evaluation period is required",
            "help": "Specify how often to check for alert conditions",
            "example": "periodDuration: 'FIVE_MINUTES'",
        },
        # Value validation errors
        "threshold.*negative": {
            "message": "Threshold value cannot be negative",
            "help": "Please provide a positive number for the threshold",
            "example": "threshold: 0.05 (not -0.05)",
        },
        "email.*invalid": {
            "message": "Invalid email address format",
            "help": "Please provide valid email addresses for notifications",
            "example": "notificationAddresses: ['user@domain.com']",
        },
        "webhook.*invalid": {
            "message": "Invalid webhook URL format",
            "help": "Webhook URLs must start with http:// or https://",
            "example": "webhook_enabled: ['https://your-webhook.com/alerts']",
        },
        # Authentication errors
        "unauthorized": {
            "message": "Authentication failed",
            "help": "Please check your API key and team ID configuration",
            "example": "Ensure your API credentials are correctly set",
        },
        "forbidden": {
            "message": "Access denied",
            "help": "You don't have permission to perform this action",
            "example": "Contact your administrator for access to alert management",
        },
        # Resource errors
        "not.*found": {
            "message": "Resource not found",
            "help": "The requested alert or anomaly doesn't exist",
            "example": "Check the alert ID and try again",
        },
        "already.*exists": {
            "message": "Resource already exists",
            "help": "An alert with this name or configuration already exists",
            "example": "Try using a different name or modify the existing alert",
        },
        # Rate limiting
        "rate.*limit": {
            "message": "Too many requests",
            "help": "Please wait a moment before trying again",
            "example": "Rate limits help ensure system stability",
        },
        # Server errors
        "internal.*server.*error": {
            "message": "Server error occurred",
            "help": "This is a temporary issue on our end",
            "example": "Please try again in a few minutes",
        },
        "service.*unavailable": {
            "message": "Service temporarily unavailable",
            "help": "The alert service is currently down for maintenance",
            "example": "Please try again later",
        },
    }

    # Common field requirements and examples
    FIELD_HELP = {
        "name": {
            "description": "A descriptive name for your alert",
            "requirements": "1-255 characters, no special characters",
            "examples": ["High Cost Alert", "Transaction Volume Monitor", "Error Rate Threshold"],
        },
        "alertType": {
            "description": "The type of alert monitoring to perform",
            "requirements": "Must be a valid alert type",
            "examples": ["THRESHOLD", "STATISTICAL", "ANOMALY"],
        },
        "metricType": {
            "description": "The metric to monitor for this alert",
            "requirements": "Must be a supported metric type",
            "examples": [
                "COST_PER_TRANSACTION",
                "TOTAL_COST",
                "TRANSACTION_COUNT",
                "LATENCY",
                "ERROR_RATE",
            ],
        },
        "operator": {
            "description": "How to compare the metric value against the threshold",
            "requirements": "Must be a valid comparison operator",
            "examples": [
                "GREATER_THAN",
                "LESS_THAN",
                "GREATER_THAN_OR_EQUAL",
                "LESS_THAN_OR_EQUAL",
                "EQUAL",
            ],
        },
        "threshold": {
            "description": "The value that triggers the alert when crossed",
            "requirements": "Must be a positive number",
            "examples": ["0.05 (for $0.05)", "100 (for 100 transactions)", "0.95 (for 95%)"],
        },
        "periodDuration": {
            "description": "How often to evaluate the alert condition",
            "requirements": "Must be a valid time period",
            "examples": ["FIVE_MINUTES", "FIFTEEN_MINUTES", "ONE_HOUR", "DAILY"],
        },
    }

    @classmethod
    def translate_error(
        cls, error_message: str, error_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Translate an API error into a user-friendly message.

        Args:
            error_message: Raw error message from API
            error_data: Additional error data from API response

        Returns:
            Dictionary with user-friendly error information
        """
        import re

        # Normalize error message for pattern matching
        normalized_error = error_message.lower()

        # Find matching error pattern
        for pattern, translation in cls.ERROR_TRANSLATIONS.items():
            if re.search(pattern, normalized_error):
                return {
                    "user_message": translation["message"],
                    "help": translation["help"],
                    "example": translation["example"],
                    "original_error": error_message,
                }

        # Extract field name if it's a validation error
        field_match = re.search(r"field['\"]?\s*:\s*['\"]?(\w+)", normalized_error)
        if field_match:
            field_name = field_match.group(1)
            if field_name in cls.FIELD_HELP:
                field_info = cls.FIELD_HELP[field_name]
                return {
                    "user_message": f"Invalid value for {field_name}",
                    "help": f"{field_info['description']}. {field_info['requirements']}",
                    "example": f"Examples: {', '.join(field_info['examples'][:2])}",
                    "original_error": error_message,
                }

        # Default fallback
        return {
            "user_message": "An error occurred while processing your request",
            "help": "Please check your input data and try again",
            "example": "Ensure all required fields are provided with valid values",
            "original_error": error_message,
        }

    @classmethod
    def format_user_friendly_error(
        cls, error_message: str, error_data: Optional[Dict[str, Any]] = None
    ) -> str:
        """Format a complete user-friendly error message.

        Args:
            error_message: Raw error message from API
            error_data: Additional error data from API response

        Returns:
            Formatted user-friendly error message
        """
        translation = cls.translate_error(error_message, error_data)

        formatted_message = f"**{translation['user_message']}**\n\n"
        formatted_message += f"**Help**: {translation['help']}\n\n"
        formatted_message += f"**Example**: {translation['example']}"

        # Add original error for debugging (in a collapsed section)
        if translation["original_error"] != translation["user_message"]:
            formatted_message += f"\n\n<details><summary>Technical Details</summary>\n{translation['original_error']}</details>"

        return formatted_message
