"""Enhanced error handling for agent-friendly MCP tools.

This module provides standardized error classes and formatting utilities
that generate helpful, actionable error messages with suggestions and examples.
"""

import json
from typing import Any, Dict, List, Optional


class AgentFriendlyError(Exception):
    """Base class for agent-friendly errors with enhanced messaging."""

    def __init__(
        self,
        message: str,
        error_code: str,
        suggestions: Optional[List[str]] = None,
        examples: Optional[Dict[str, Any]] = None,
        field_errors: Optional[Dict[str, str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        """Initialize agent-friendly error.

        Args:
            message: Human-readable error message
            error_code: Machine-readable error code
            suggestions: List of actionable suggestions
            examples: Working examples to help resolve the error
            field_errors: Field-specific error messages
            context: Additional context information
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.suggestions = suggestions or []
        self.examples = examples or {}
        self.field_errors = field_errors or {}
        self.context = context or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary format."""
        return {
            "error": True,
            "error_code": self.error_code,
            "message": self.message,
            "suggestions": self.suggestions,
            "examples": self.examples,
            "field_errors": self.field_errors,
            "context": self.context,
        }

    def to_formatted_message(self) -> str:
        """Generate formatted error message for display."""
        return ErrorFormatter.format_error(self)


class ValidationError(AgentFriendlyError):
    """Error for validation failures with specific field guidance."""

    def __init__(
        self,
        message: str,
        field_errors: Dict[str, str],
        suggestions: Optional[List[str]] = None,
        examples: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            suggestions=suggestions,
            examples=examples,
            field_errors=field_errors,
        )


class SchemaError(AgentFriendlyError):
    """Error for schema-related issues with discovery guidance."""

    def __init__(
        self,
        message: str,
        missing_fields: Optional[List[str]] = None,
        invalid_fields: Optional[List[str]] = None,
        suggestions: Optional[List[str]] = None,
    ):
        context = {}
        if missing_fields:
            context["missing_fields"] = missing_fields
        if invalid_fields:
            context["invalid_fields"] = invalid_fields

        super().__init__(
            message=message, error_code="SCHEMA_ERROR", suggestions=suggestions, context=context
        )


class BusinessRuleError(AgentFriendlyError):
    """Error for business rule violations with guidance."""

    def __init__(
        self,
        message: str,
        rule_name: str,
        suggestions: Optional[List[str]] = None,
        examples: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code="BUSINESS_RULE_ERROR",
            suggestions=suggestions,
            examples=examples,
            context={"rule_name": rule_name},
        )


class ErrorFormatter:
    """Utility class for formatting errors in agent-friendly ways."""

    @staticmethod
    def format_error(error: AgentFriendlyError) -> str:
        """Format error for human-readable display.

        Args:
            error: Error to format

        Returns:
            Formatted error message
        """
        lines = [f"Error: {error.message}", f"Code: {error.error_code}"]

        if error.field_errors:
            lines.append("\nField Errors:")
            for field, field_error in error.field_errors.items():
                lines.append(f"  • {field}: {field_error}")

        if error.suggestions:
            lines.append("\nSuggestions:")
            for suggestion in error.suggestions:
                lines.append(f"  • {suggestion}")

        if error.examples:
            lines.append("\n📝 Working Examples:")
            for example_name, example_data in error.examples.items():
                lines.append(f"  {example_name}:")
                if isinstance(example_data, dict):
                    lines.append(f"    {json.dumps(example_data, indent=4)}")
                else:
                    lines.append(f"    {example_data}")

        if error.context:
            lines.append("\n🔍 Additional Context:")
            for key, value in error.context.items():
                lines.append(f"  • {key}: {value}")

        return "\n".join(lines)

    @staticmethod
    def format_validation_result(
        is_valid: bool, errors: List[AgentFriendlyError], warnings: Optional[List[str]] = None
    ) -> str:
        """Format validation result.

        Args:
            is_valid: Whether validation passed
            errors: List of validation errors
            warnings: Optional list of warnings

        Returns:
            Formatted validation result
        """
        if is_valid and not warnings:
            return "✅ Validation passed successfully!"

        lines = []

        if not is_valid:
            lines.append("❌ Validation failed:")
            for error in errors:
                lines.append(f"\n{ErrorFormatter.format_error(error)}")

        if warnings:
            lines.append("\n⚠️ Warnings:")
            for warning in warnings:
                lines.append(f"  • {warning}")

        return "\n".join(lines)

    @staticmethod
    def create_field_error(
        field_name: str,
        field_value: Any,
        expected_type: str,
        valid_values: Optional[List[Any]] = None,
        example_value: Optional[Any] = None,
    ) -> str:
        """Create standardized field error message.

        Args:
            field_name: Name of the field
            field_value: Invalid value provided
            expected_type: Expected type or format
            valid_values: List of valid values (if applicable)
            example_value: Example of a valid value

        Returns:
            Formatted field error message
        """
        message = (
            f"Invalid value '{field_value}' for field '{field_name}'. Expected {expected_type}."
        )

        if valid_values:
            message += f" Valid values: {', '.join(map(str, valid_values))}"

        if example_value:
            message += f" Example: {example_value}"

        return message
