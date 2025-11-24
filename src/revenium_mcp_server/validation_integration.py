"""Validation Integration Layer for MCP Tools.

This module integrates JSON Schema validation with existing MCP tools,
providing a unified validation experience across all tools.
"""

from functools import wraps
from typing import Any, Callable, Dict

from loguru import logger
from mcp.types import TextContent

from .json_schema_validator import json_schema_validator


class ValidationIntegration:
    """Integration layer for JSON Schema validation with MCP tools."""

    def __init__(self):
        """Initialize the validation integration."""
        self.validator = json_schema_validator
        self.validation_cache: Dict[str, Dict[str, Any]] = {}

    def validate_tool_call(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a complete tool call with parameters.

        Args:
            tool_name: Name of the MCP tool
            parameters: Parameters passed to the tool

        Returns:
            Validation result with detailed feedback
        """
        logger.debug(f"Validating {tool_name} with parameters: {list(parameters.keys())}")

        # Run JSON Schema validation
        schema_result = self.validator.validate_tool_parameters(tool_name, parameters)

        if schema_result["valid"]:
            logger.debug(f"✅ {tool_name} validation passed")
            return {
                "valid": True,
                "errors": [],
                "warnings": [],
                "suggestions": [],
                "validated_parameters": schema_result.get("validated_data", parameters),
            }

        logger.warning(f"❌ {tool_name} validation failed: {len(schema_result['errors'])} errors")

        # Format errors for user consumption
        formatted_errors = []
        for error in schema_result["errors"]:
            formatted_errors.append(
                {
                    "field": error.get("field", "unknown"),
                    "message": error.get("message", "Validation error"),
                    "expected": error.get("expected", "Valid value"),
                    "provided": error.get("provided", "Invalid value"),
                }
            )

        return {
            "valid": False,
            "errors": formatted_errors,
            "warnings": [],
            "suggestions": schema_result.get("suggestions", []),
            "schema_errors": schema_result.get("schema_errors", []),
        }

    def create_validation_decorator(self, tool_name: str) -> Callable:
        """Create a validation decorator for a specific tool.

        Args:
            tool_name: Name of the tool to validate

        Returns:
            Decorator function that validates parameters before tool execution
        """

        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Extract parameters from kwargs or args
                if len(args) > 1:
                    parameters = args[1] if isinstance(args[1], dict) else kwargs
                else:
                    parameters = kwargs

                # Validate parameters
                validation_result = self.validate_tool_call(tool_name, parameters)

                if not validation_result["valid"]:
                    # Return validation errors as TextContent
                    error_text = self._format_validation_errors(validation_result, tool_name)
                    return [TextContent(type="text", text=error_text)]

                # If validation passes, call the original function
                return await func(*args, **kwargs)

            return wrapper

        return decorator

    def _format_validation_errors(self, validation_result: Dict[str, Any], tool_name: str) -> str:
        """Format validation errors into user-friendly text."""
        error_text = f"❌ **Parameter Validation Failed for {tool_name}**\n\n"

        # Add errors
        if validation_result["errors"]:
            error_text += "**Errors:**\n"
            for i, error in enumerate(validation_result["errors"], 1):
                error_text += f"{i}. **{error['field']}**: {error['message']}\n"
                error_text += f"   - Expected: {error['expected']}\n"
                error_text += f"   - Provided: {error['provided']}\n\n"

        # Add suggestions
        if validation_result["suggestions"]:
            error_text += "**Suggestions:**\n"
            for suggestion in validation_result["suggestions"][:5]:  # Limit to 5 suggestions
                error_text += f"• {suggestion}\n"
            error_text += "\n"

        # Add helpful actions
        error_text += "**Next Steps:**\n"
        error_text += f"• Use `get_capabilities` to see valid parameters for {tool_name}\n"
        error_text += f"• Use `get_examples` to see working parameter examples\n"
        error_text += f"• Use `validate` action to test your parameters before submitting\n"

        return error_text

    def get_validation_summary(self, tool_name: str) -> Dict[str, Any]:
        """Get a summary of validation rules for a tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Summary of validation rules and requirements
        """
        if tool_name not in self.validator.schemas:
            return {
                "error": f"No validation schema found for {tool_name}",
                "available_tools": list(self.validator.schemas.keys()),
            }

        schema = self.validator.schemas[tool_name]
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        summary = {
            "tool_name": tool_name,
            "required_parameters": required,
            "optional_parameters": [p for p in properties.keys() if p not in required],
            "parameter_details": {},
        }

        # Extract parameter details
        for param_name, param_schema in properties.items():
            details = {
                "type": param_schema.get("type", "unknown"),
                "description": param_schema.get("description", "No description available"),
                "required": param_name in required,
            }

            # Add constraints
            if "enum" in param_schema:
                details["valid_values"] = param_schema["enum"]
            if "minLength" in param_schema:
                details["min_length"] = param_schema["minLength"]
            if "maxLength" in param_schema:
                details["max_length"] = param_schema["maxLength"]
            if "minimum" in param_schema:
                details["minimum"] = param_schema["minimum"]
            if "maximum" in param_schema:
                details["maximum"] = param_schema["maximum"]
            if "pattern" in param_schema:
                details["pattern"] = param_schema["pattern"]
            if "format" in param_schema:
                details["format"] = param_schema["format"]

            summary["parameter_details"][param_name] = details

        return summary


class ValidationReporter:
    """Generate validation reports and statistics."""

    def __init__(self, integration: ValidationIntegration):
        """Initialize the validation reporter."""
        self.integration = integration

    def generate_tool_validation_report(self, tool_name: str) -> str:
        """Generate a comprehensive validation report for a tool."""
        summary = self.integration.get_validation_summary(tool_name)

        if "error" in summary:
            return f"❌ **Error**: {summary['error']}\n\nAvailable tools: {', '.join(summary['available_tools'])}"

        report = f"# 📋 **Validation Report: {tool_name}**\n\n"

        # Required parameters
        if summary["required_parameters"]:
            report += "## ✅ **Required Parameters**\n\n"
            for param in summary["required_parameters"]:
                details = summary["parameter_details"][param]
                report += f"### `{param}`\n"
                report += f"- **Type**: {details['type']}\n"
                report += f"- **Description**: {details['description']}\n"

                if "valid_values" in details:
                    report += (
                        f"- **Valid Values**: {', '.join(map(str, details['valid_values']))}\n"
                    )
                if "min_length" in details:
                    report += f"- **Minimum Length**: {details['min_length']}\n"
                if "max_length" in details:
                    report += f"- **Maximum Length**: {details['max_length']}\n"
                if "pattern" in details:
                    report += f"- **Pattern**: `{details['pattern']}`\n"
                if "format" in details:
                    report += f"- **Format**: {details['format']}\n"

                report += "\n"

        # Optional parameters
        if summary["optional_parameters"]:
            report += "## 🔧 **Optional Parameters**\n\n"
            for param in summary["optional_parameters"]:
                details = summary["parameter_details"][param]
                report += f"### `{param}`\n"
                report += f"- **Type**: {details['type']}\n"
                report += f"- **Description**: {details['description']}\n"

                if "valid_values" in details:
                    report += (
                        f"- **Valid Values**: {', '.join(map(str, details['valid_values']))}\n"
                    )

                report += "\n"

        # Usage examples
        report += "## 💡 **Usage Tips**\n\n"
        report += f"• Use `get_examples` to see working examples for {tool_name}\n"
        report += f"• Use `validate` action to test parameters before submitting\n"
        report += f"• All parameter names must use snake_case format\n"
        report += f"• Required parameters must be provided for the tool to work\n"

        return report

    def generate_all_tools_report(self) -> str:
        """Generate a validation report for all tools."""
        tools = list(self.integration.validator.schemas.keys())

        report = "# 📊 **All Tools Validation Summary**\n\n"
        report += f"**Total Tools**: {len(tools)}\n\n"

        for tool_name in sorted(tools):
            summary = self.integration.get_validation_summary(tool_name)
            required_count = len(summary["required_parameters"])
            optional_count = len(summary["optional_parameters"])
            total_count = required_count + optional_count

            report += f"## {tool_name}\n"
            report += f"- **Total Parameters**: {total_count}\n"
            report += f"- **Required**: {required_count}\n"
            report += f"- **Optional**: {optional_count}\n"
            report += f"- **Required Params**: {', '.join(summary['required_parameters']) if summary['required_parameters'] else 'None'}\n\n"

        return report


# Global instances
validation_integration = ValidationIntegration()
validation_reporter = ValidationReporter(validation_integration)
