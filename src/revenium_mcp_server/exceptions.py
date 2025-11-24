"""Custom exceptions for Alert & Anomaly Management Tools.

This module defines custom exception classes for better error handling
and more informative error messages in the alert and anomaly management system.
"""

import json
from typing import Any, Dict, Optional


class AlertToolsError(Exception):
    """Base exception class for all alert tools errors."""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        suggestions: Optional[list] = None,
    ):
        """Initialize the base alert tools error.

        Args:
            message: Human-readable error message
            error_code: Machine-readable error code
            details: Additional error details
            suggestions: List of suggested actions to resolve the error
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code or "ALERT_TOOLS_ERROR"
        self.details = details or {}
        self.suggestions = suggestions or []

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for structured logging."""
        return {
            "error_type": self.__class__.__name__,
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
            "suggestions": self.suggestions,
        }

    def format_user_message(self) -> str:
        """Format a user-friendly error message with suggestions."""
        formatted_message = f"**Error**: {self.message}"

        if self.details:
            formatted_message += f"\n\n**Details:**"
            for key, value in self.details.items():
                formatted_message += f"\n  • {key}: {value}"

        if self.suggestions:
            formatted_message += f"\n\n**Suggestions:**"
            for suggestion in self.suggestions:
                formatted_message += f"\n  • {suggestion}"

        return formatted_message


class ValidationError(AlertToolsError):
    """Exception raised when input validation fails."""

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        value: Optional[Any] = None,
        expected: Optional[str] = None,
        suggestion: Optional[str] = None,
        example: Optional[Dict[str, Any]] = None,
    ):
        details = {}
        if field:
            details["field"] = field
        if value is not None:
            details["provided_value"] = str(value)
        if expected:
            details["expected"] = expected
        # Note: suggestion is NOT added to details to avoid duplication with suggestions list
        if example:
            details["example"] = json.dumps(example, indent=2)

        suggestions = [
            "Check the input parameters and their types",
            "Refer to the API documentation for valid values",
            "Ensure all required fields are provided",
        ]

        # Add custom suggestion if provided
        if suggestion:
            suggestions.insert(0, suggestion)

        super().__init__(
            message=message, error_code="VALIDATION_ERROR", details=details, suggestions=suggestions
        )


class AnomalyNotFoundError(AlertToolsError):
    """Exception raised when an anomaly is not found."""

    def __init__(self, anomaly_id: str):
        details = {"anomaly_id": anomaly_id}
        suggestions = [
            "Verify the anomaly ID is correct",
            "Check if the anomaly was deleted",
            "List all anomalies to see available IDs",
            "Ensure you have access to this anomaly",
        ]

        super().__init__(
            message=f"Anomaly with ID '{anomaly_id}' not found",
            error_code="ANOMALY_NOT_FOUND",
            details=details,
            suggestions=suggestions,
        )


class AlertNotFoundError(AlertToolsError):
    """Exception raised when an alert is not found."""

    def __init__(self, alert_id: str):
        details = {"alert_id": alert_id}
        suggestions = [
            "Verify the alert ID is correct",
            "Check if the alert was resolved or archived",
            "List all alerts to see available IDs",
            "Ensure you have access to this alert",
        ]

        super().__init__(
            message=f"Alert with ID '{alert_id}' not found",
            error_code="ALERT_NOT_FOUND",
            details=details,
            suggestions=suggestions,
        )


class InvalidInputError(AlertToolsError):
    """Exception raised when input parameters are invalid."""

    def __init__(self, parameter: str, value: Any, reason: str):
        details = {"parameter": parameter, "value": str(value), "reason": reason}
        suggestions = [
            f"Check the '{parameter}' parameter value",
            "Refer to the API documentation for valid parameter formats",
            "Ensure the parameter meets all requirements",
        ]

        super().__init__(
            message=f"Invalid input for parameter '{parameter}': {reason}",
            error_code="INVALID_INPUT",
            details=details,
            suggestions=suggestions,
        )


class APIConnectionError(AlertToolsError):
    """Exception raised when API connection fails."""

    def __init__(
        self, endpoint: str, status_code: Optional[int] = None, response_text: Optional[str] = None
    ):
        details = {"endpoint": endpoint}
        if status_code:
            details["status_code"] = status_code
        if response_text:
            details["response"] = response_text[:500]  # Limit response text

        suggestions = [
            "Check your internet connection",
            "Verify API credentials are correct",
            "Check if the API service is available",
            "Try again in a few moments",
        ]

        if status_code == 401:
            suggestions.extend(
                [
                    "Verify your API key is valid",
                    "Check if your API key has expired",
                    "Ensure you have the correct permissions",
                ]
            )
        elif status_code == 403:
            suggestions.extend(
                [
                    "Check if you have permission to access this resource",
                    "Verify your team ID is correct",
                    "Contact your administrator for access",
                ]
            )
        elif status_code == 429:
            suggestions.extend(
                [
                    "You are being rate limited",
                    "Wait a few minutes before trying again",
                    "Consider reducing the frequency of requests",
                ]
            )

        super().__init__(
            message=f"API connection failed for endpoint '{endpoint}'"
            + (f" (HTTP {status_code})" if status_code else ""),
            error_code="API_CONNECTION_ERROR",
            details=details,
            suggestions=suggestions,
        )


class PermissionError(AlertToolsError):
    """Exception raised when user lacks permission for an operation."""

    def __init__(self, operation: str, resource: str):
        details = {"operation": operation, "resource": resource}
        suggestions = [
            "Check if you have the required permissions",
            "Verify your team membership",
            "Contact your administrator for access",
            "Ensure you're using the correct team ID",
        ]

        super().__init__(
            message=f"Permission denied for operation '{operation}' on resource '{resource}'",
            error_code="PERMISSION_DENIED",
            details=details,
            suggestions=suggestions,
        )


class ConfigurationError(AlertToolsError):
    """Exception raised when configuration is invalid or missing."""

    def __init__(self, config_item: str, issue: str):
        details = {"config_item": config_item, "issue": issue}
        suggestions = [
            "Check your configuration settings",
            "Verify all required environment variables are set",
            "Ensure configuration values are in the correct format",
            "Refer to the setup documentation",
        ]

        super().__init__(
            message=f"Configuration error for '{config_item}': {issue}",
            error_code="CONFIGURATION_ERROR",
            details=details,
            suggestions=suggestions,
        )


class OperationTimeoutError(AlertToolsError):
    """Exception raised when an operation times out."""

    def __init__(self, operation: str, timeout_seconds: int):
        details = {"operation": operation, "timeout_seconds": timeout_seconds}
        suggestions = [
            "Try the operation again",
            "Check your network connection",
            "Consider increasing the timeout if possible",
            "Break large operations into smaller chunks",
        ]

        super().__init__(
            message=f"Operation '{operation}' timed out after {timeout_seconds} seconds",
            error_code="OPERATION_TIMEOUT",
            details=details,
            suggestions=suggestions,
        )


class DataIntegrityError(AlertToolsError):
    """Exception raised when data integrity checks fail."""

    def __init__(self, data_type: str, issue: str):
        details = {"data_type": data_type, "issue": issue}
        suggestions = [
            "Verify the data format is correct",
            "Check for missing required fields",
            "Ensure data relationships are valid",
            "Try refreshing the data",
        ]

        super().__init__(
            message=f"Data integrity error for '{data_type}': {issue}",
            error_code="DATA_INTEGRITY_ERROR",
            details=details,
            suggestions=suggestions,
        )
