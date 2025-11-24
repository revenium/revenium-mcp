"""Unit tests for StandardError system."""

import pytest
import json
from mcp.types import TextContent

from src.revenium_mcp_server.standard_errors import (
    StandardError, StandardErrorBuilder, StandardErrorFormatter, CommonErrors,
    create_missing_parameter_error, create_invalid_value_error,
    create_validation_error, create_api_error, create_unknown_action_error
)


class TestStandardError:
    """Test StandardError dataclass."""
    
    def test_standard_error_creation(self):
        """Test basic StandardError creation."""
        error = StandardError(
            error="Test error message",
            field="test_field",
            expected="Valid value",
            provided="invalid_value",
            suggestions=["Fix the value", "Check documentation"],
            examples={"valid": "example"},
            documentation_url="https://docs.example.com"
        )
        
        assert error.error == "Test error message"
        assert error.field == "test_field"
        assert error.expected == "Valid value"
        assert error.provided == "invalid_value"
        assert error.suggestions == ["Fix the value", "Check documentation"]
        assert error.examples == {"valid": "example"}
        assert error.documentation_url == "https://docs.example.com"
    
    def test_standard_error_defaults(self):
        """Test StandardError with default values."""
        error = StandardError(error="Test error")
        
        assert error.error == "Test error"
        assert error.field is None
        assert error.expected == "Valid input"
        assert error.provided is None
        assert error.suggestions == []
        assert error.examples is None
        assert error.documentation_url is None
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        error = StandardError(
            error="Test error",
            field="test_field",
            suggestions=["suggestion1", "suggestion2"]
        )
        
        result = error.to_dict()
        expected = {
            "error": "Test error",
            "field": "test_field",
            "expected": "Valid input",
            "provided": None,
            "suggestions": ["suggestion1", "suggestion2"],
            "examples": None,
            "documentation_url": None
        }
        
        assert result == expected
    
    def test_to_json(self):
        """Test conversion to JSON."""
        error = StandardError(error="Test error", field="test_field")
        result = error.to_json()
        
        # Should be valid JSON
        parsed = json.loads(result)
        assert parsed["error"] == "Test error"
        assert parsed["field"] == "test_field"


class TestStandardErrorBuilder:
    """Test StandardErrorBuilder class."""
    
    def test_builder_basic(self):
        """Test basic builder functionality."""
        error = StandardErrorBuilder("Test error").build()
        
        assert error.error == "Test error"
        assert error.expected == "Valid input"
        assert error.suggestions == []
    
    def test_builder_chaining(self):
        """Test builder method chaining."""
        error = (StandardErrorBuilder("Test error")
                .field("test_field")
                .expected("Valid format")
                .provided("invalid")
                .suggestions(["Fix it", "Try again"])
                .examples({"example": "value"})
                .documentation_url("https://docs.example.com")
                .build())
        
        assert error.error == "Test error"
        assert error.field == "test_field"
        assert error.expected == "Valid format"
        assert error.provided == "invalid"
        assert error.suggestions == ["Fix it", "Try again"]
        assert error.examples == {"example": "value"}
        assert error.documentation_url == "https://docs.example.com"
    
    def test_add_suggestion(self):
        """Test adding individual suggestions."""
        error = (StandardErrorBuilder("Test error")
                .add_suggestion("First suggestion")
                .add_suggestion("Second suggestion")
                .build())
        
        assert error.suggestions == ["First suggestion", "Second suggestion"]


class TestStandardErrorFormatter:
    """Test StandardErrorFormatter class."""
    
    def test_format_for_mcp_basic(self):
        """Test basic MCP formatting."""
        error = StandardError(
            error="Test error message",
            expected="Valid value",
            suggestions=["Fix the issue", "Try again"]
        )
        
        result = StandardErrorFormatter.format_for_mcp(error)
        
        assert isinstance(result, TextContent)
        assert "❌ **Error**: Test error message" in result.text
        assert "**Expected**: Valid value" in result.text
        assert "**Suggestions**:" in result.text
        assert "• Fix the issue" in result.text
        assert "• Try again" in result.text
    
    def test_format_for_mcp_with_field(self):
        """Test MCP formatting with field information."""
        error = StandardError(
            error="Invalid field value",
            field="username",
            expected="String with 3-20 characters",
            provided="ab"
        )
        
        result = StandardErrorFormatter.format_for_mcp(error)
        
        assert "**Field**: `username`" in result.text
        assert "**Expected**: String with 3-20 characters" in result.text
        assert "**Provided**: `ab`" in result.text
    
    def test_format_for_mcp_with_examples(self):
        """Test MCP formatting with examples."""
        error = StandardError(
            error="Invalid format",
            examples={"name": "John Doe", "age": 30}
        )
        
        result = StandardErrorFormatter.format_for_mcp(error)
        
        assert "**Working Example**:" in result.text
        assert "```json" in result.text
        assert '"name": "John Doe"' in result.text
    
    def test_format_for_mcp_with_documentation(self):
        """Test MCP formatting with documentation URL."""
        error = StandardError(
            error="Configuration error",
            documentation_url="https://docs.example.com/config"
        )
        
        result = StandardErrorFormatter.format_for_mcp(error)
        
        assert "📚 **Documentation**: https://docs.example.com/config" in result.text
    
    def test_format_as_text(self):
        """Test text formatting."""
        error = StandardError(error="Test error")
        result = StandardErrorFormatter.format_as_text(error)
        
        assert isinstance(result, str)
        assert "❌ **Error**: Test error" in result


class TestCommonErrors:
    """Test CommonErrors utility class."""
    
    def test_missing_required_parameter(self):
        """Test missing required parameter error."""
        error = CommonErrors.missing_required_parameter("action")
        
        assert error.error == "Missing required parameter: action"
        assert error.field == "action"
        assert error.expected == "Required parameter 'action'"
        assert "Provide the 'action' parameter" in error.suggestions[0]
    
    def test_missing_required_parameter_with_valid_values(self):
        """Test missing required parameter with valid values."""
        error = CommonErrors.missing_required_parameter("action", ["list", "get", "create"])
        
        assert "Valid values: list, get, create" in error.suggestions
    
    def test_invalid_parameter_value(self):
        """Test invalid parameter value error."""
        error = CommonErrors.invalid_parameter_value("status", "invalid", ["active", "inactive"])
        
        assert error.error == "Invalid value for parameter: status"
        assert error.field == "status"
        assert error.provided == "invalid"
        assert error.expected == "One of: active, inactive"
        assert "Valid options: active, inactive" in error.suggestions
    
    def test_validation_failed(self):
        """Test validation failed error."""
        example = {"name": "Valid Name", "length": 10}
        error = CommonErrors.validation_failed("name", "too short", example)
        
        assert error.error == "Validation failed for name: too short"
        assert error.field == "name"
        assert error.examples == example
        assert "See the working example below" in error.suggestions
    
    def test_api_error(self):
        """Test API error creation."""
        error = CommonErrors.api_error(400, "Bad Request", "/api/test")
        
        assert error.error == "API request failed: Bad Request"
        assert error.field == "api_request"
        assert error.provided == "HTTP 400: Bad Request"
        assert "Validate your request data format" in error.suggestions
    
    def test_unknown_action(self):
        """Test unknown action error."""
        error = CommonErrors.unknown_action("invalid", ["list", "get", "create"])
        
        assert error.error == "Unknown action: invalid"
        assert error.field == "action"
        assert error.provided == "invalid"
        assert error.expected == "One of: list, get, create"


class TestConvenienceFunctions:
    """Test convenience functions."""
    
    def test_create_missing_parameter_error(self):
        """Test create_missing_parameter_error function."""
        result = create_missing_parameter_error("action")
        
        assert isinstance(result, TextContent)
        assert "Missing required parameter: action" in result.text
    
    def test_create_invalid_value_error(self):
        """Test create_invalid_value_error function."""
        result = create_invalid_value_error("status", "invalid", ["active", "inactive"])
        
        assert isinstance(result, TextContent)
        assert "Invalid value for parameter: status" in result.text
    
    def test_create_validation_error(self):
        """Test create_validation_error function."""
        result = create_validation_error("name", "too short", {"name": "Valid Name"})
        
        assert isinstance(result, TextContent)
        assert "Validation failed for name: too short" in result.text
    
    def test_create_api_error(self):
        """Test create_api_error function."""
        result = create_api_error(404, "Not Found", "/api/test")
        
        assert isinstance(result, TextContent)
        assert "API request failed: Not Found" in result.text
    
    def test_create_unknown_action_error(self):
        """Test create_unknown_action_error function."""
        result = create_unknown_action_error("invalid", ["list", "get"])
        
        assert isinstance(result, TextContent)
        assert "Unknown action: invalid" in result.text
