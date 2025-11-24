"""Standardized Error Response System for MCP Server.

This module implements the expert-validated StandardError interface to ensure
consistent error handling across all MCP tools, addressing the 40% error
consistency issue identified in the expert evaluation.
"""

import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Union

from mcp.types import TextContent


@dataclass
class StandardError:
    """Standardized error response format for all MCP tools.

    This interface ensures consistent error handling across all tools,
    addressing the expert feedback requirement for standardized error responses.
    """

    error: str  # Clear, human-readable error message
    field: Optional[str] = None  # Specific field that caused the error
    expected: str = "Valid input"  # What was expected (format, type, values)
    provided: Optional[Any] = None  # What was actually provided
    suggestions: List[str] = None  # Actionable suggestions to fix the error
    examples: Optional[Any] = None  # Working examples for the correct format
    documentation_url: Optional[str] = None  # Link to relevant documentation

    def __post_init__(self):
        """Initialize default suggestions if none provided."""
        if self.suggestions is None:
            self.suggestions = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format."""
        return asdict(self)

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)


class StandardErrorBuilder:
    """Builder class for creating standardized error responses."""

    def __init__(self, error_message: str):
        """Initialize with base error message."""
        self.error_data = StandardError(error=error_message)

    def field(self, field_name: str) -> "StandardErrorBuilder":
        """Set the field that caused the error."""
        self.error_data.field = field_name
        return self

    def expected(self, expected_value: str) -> "StandardErrorBuilder":
        """Set what was expected."""
        self.error_data.expected = expected_value
        return self

    def provided(self, provided_value: Any) -> "StandardErrorBuilder":
        """Set what was actually provided."""
        self.error_data.provided = provided_value
        return self

    def suggestions(self, suggestions: List[str]) -> "StandardErrorBuilder":
        """Set actionable suggestions."""
        self.error_data.suggestions = suggestions
        return self

    def add_suggestion(self, suggestion: str) -> "StandardErrorBuilder":
        """Add a single suggestion."""
        if self.error_data.suggestions is None:
            self.error_data.suggestions = []
        self.error_data.suggestions.append(suggestion)
        return self

    def examples(self, examples: Any) -> "StandardErrorBuilder":
        """Set working examples."""
        self.error_data.examples = examples
        return self

    def documentation_url(self, url: str) -> "StandardErrorBuilder":
        """Set documentation URL."""
        self.error_data.documentation_url = url
        return self

    def build(self) -> StandardError:
        """Build the final StandardError object."""
        return self.error_data


class StandardErrorFormatter:
    """Formatter for converting StandardError to user-friendly text."""

    @staticmethod
    def format_for_mcp(error: StandardError) -> TextContent:
        """Format StandardError as MCP TextContent.

        Args:
            error: StandardError object to format

        Returns:
            TextContent object with formatted error message
        """
        text = f"❌ **Error**: {error.error}\n\n"

        # Add field information if available
        if error.field:
            text += f"**Field**: `{error.field}`\n"

        # Add expected vs provided information
        text += f"**Expected**: {error.expected}\n"
        if error.provided is not None:
            provided_str = str(error.provided)
            if len(provided_str) > 100:
                provided_str = provided_str[:97] + "..."
            text += f"**Provided**: `{provided_str}`\n"

        text += "\n"

        # Add suggestions
        if error.suggestions:
            text += "**Suggestions**:\n"
            for suggestion in error.suggestions:
                text += f"  • {suggestion}\n"
            text += "\n"

        # Add examples if available
        if error.examples is not None:
            text += "**Working Example**:\n"
            if isinstance(error.examples, (dict, list)):
                text += f"```json\n{json.dumps(error.examples, indent=2)}\n```\n\n"
            else:
                text += f"```\n{error.examples}\n```\n\n"

        # Add documentation link if available
        if error.documentation_url:
            text += f"📚 **Documentation**: {error.documentation_url}\n"

        return TextContent(type="text", text=text)

    @staticmethod
    def format_as_text(error: StandardError) -> str:
        """Format StandardError as plain text string.

        Args:
            error: StandardError object to format

        Returns:
            Formatted error message as string
        """
        return StandardErrorFormatter.format_for_mcp(error).text


class CommonErrors:
    """Common error templates for consistent error messages."""

    @staticmethod
    def missing_required_parameter(
        parameter_name: str, valid_values: Optional[List[str]] = None
    ) -> StandardError:
        """Create error for missing required parameter."""
        suggestions = [
            f"Provide the '{parameter_name}' parameter in your request",
            "Check the API documentation for required parameters",
            "Use get_capabilities action to see all required parameters",
        ]

        if valid_values:
            suggestions.append(f"Valid values: {', '.join(valid_values)}")

        return (
            StandardErrorBuilder(f"Missing required parameter: {parameter_name}")
            .field(parameter_name)
            .expected(f"Required parameter '{parameter_name}'")
            .suggestions(suggestions)
            .build()
        )

    @staticmethod
    def invalid_parameter_value(
        parameter_name: str,
        provided_value: Any,
        valid_values: Optional[List[str]] = None,
        expected_format: Optional[str] = None,
    ) -> StandardError:
        """Create error for invalid parameter value."""
        expected = expected_format or "Valid value"
        if valid_values:
            expected = f"One of: {', '.join(valid_values)}"

        suggestions = [
            f"Check the value provided for '{parameter_name}'",
            "Refer to the API documentation for valid values",
            "Use get_examples action to see working examples",
        ]

        if valid_values:
            suggestions.append(f"Valid options: {', '.join(valid_values)}")

        return (
            StandardErrorBuilder(f"Invalid value for parameter: {parameter_name}")
            .field(parameter_name)
            .expected(expected)
            .provided(provided_value)
            .suggestions(suggestions)
            .build()
        )

    @staticmethod
    def validation_failed(
        field_name: str, reason: str, example: Optional[Any] = None
    ) -> StandardError:
        """Create error for validation failure."""
        suggestions = [
            f"Fix the validation error for '{field_name}'",
            "Check the field format and requirements",
            "Use validate action to test your configuration",
        ]

        if example:
            suggestions.append("See the working example below")

        builder = (
            StandardErrorBuilder(f"Validation failed for {field_name}: {reason}")
            .field(field_name)
            .expected("Valid field value")
            .suggestions(suggestions)
        )

        if example:
            builder.examples(example)

        return builder.build()

    @staticmethod
    def api_error(status_code: int, message: str, endpoint: str) -> StandardError:
        """Create error for API failures."""
        suggestions = [
            "Check your request parameters",
            "Verify your authentication credentials",
            "Try the request again",
        ]

        if status_code == 400:
            suggestions.extend(
                ["Validate your request data format", "Ensure all required fields are provided"]
            )
        elif status_code == 401:
            suggestions.extend(["Check your API key", "Verify your authentication is valid"])
        elif status_code == 403:
            suggestions.extend(["Check your permissions", "Verify your team access"])
        elif status_code == 404:
            suggestions.extend(["Check the resource ID", "Verify the resource exists"])
        elif status_code >= 500:
            suggestions.extend(["This is a server error", "Contact support if the issue persists"])

        return (
            StandardErrorBuilder(f"API request failed: {message}")
            .field("api_request")
            .expected(f"Successful API response from {endpoint}")
            .provided(f"HTTP {status_code}: {message}")
            .suggestions(suggestions)
            .build()
        )

    @staticmethod
    def unknown_action(action: str, valid_actions: List[str]) -> StandardError:
        """Create error for unknown action."""
        return (
            StandardErrorBuilder(f"Unknown action: {action}")
            .field("action")
            .expected(f"One of: {', '.join(valid_actions)}")
            .provided(action)
            .suggestions(
                [
                    f"Use one of the supported actions: {', '.join(valid_actions)}",
                    "Check the action name for typos",
                    "Use get_capabilities to see all available actions",
                ]
            )
            .build()
        )


# Convenience functions for quick error creation
def create_missing_parameter_error(
    parameter_name: str, valid_values: Optional[List[str]] = None
) -> TextContent:
    """Quick function to create missing parameter error."""
    error = CommonErrors.missing_required_parameter(parameter_name, valid_values)
    return StandardErrorFormatter.format_for_mcp(error)


def create_invalid_value_error(
    parameter_name: str,
    provided_value: Any,
    valid_values: Optional[List[str]] = None,
    expected_format: Optional[str] = None,
) -> TextContent:
    """Quick function to create invalid value error."""
    error = CommonErrors.invalid_parameter_value(
        parameter_name, provided_value, valid_values, expected_format
    )
    return StandardErrorFormatter.format_for_mcp(error)


def create_validation_error(
    field_name: str, reason: str, example: Optional[Any] = None
) -> TextContent:
    """Quick function to create validation error."""
    error = CommonErrors.validation_failed(field_name, reason, example)
    return StandardErrorFormatter.format_for_mcp(error)


def create_api_error(status_code: int, message: str, endpoint: str) -> TextContent:
    """Quick function to create API error."""
    error = CommonErrors.api_error(status_code, message, endpoint)
    return StandardErrorFormatter.format_for_mcp(error)


def create_unknown_action_error(action: str, valid_actions: List[str]) -> TextContent:
    """Quick function to create unknown action error."""
    error = CommonErrors.unknown_action(action, valid_actions)
    return StandardErrorFormatter.format_for_mcp(error)
