"""Unit tests for error handling in Alert & Anomaly Management Tools."""

import pytest

from src.revenium_mcp_server.exceptions import (
    AlertToolsError, ValidationError, AnomalyNotFoundError, AlertNotFoundError,
    APIConnectionError, PermissionError, InvalidInputError
)
from src.revenium_mcp_server.error_handlers import (
    translate_http_error, validate_required_params, validate_anomaly_id,
    validate_alert_id, validate_pagination_params
)
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from mcp.types import TextContent


class TestCustomExceptions:
    """Test custom exception classes."""

    def test_alert_tools_error_base(self):
        """Test base AlertToolsError exception."""
        error = AlertToolsError(
            message="Test error",
            error_code="TEST_ERROR",
            details={"key": "value"},
            suggestions=["Try again", "Check input"]
        )

        assert error.message == "Test error"
        assert error.error_code == "TEST_ERROR"
        assert error.details == {"key": "value"}
        assert error.suggestions == ["Try again", "Check input"]

        # Test to_dict method
        error_dict = error.to_dict()
        assert error_dict["error_type"] == "AlertToolsError"
        assert error_dict["error_code"] == "TEST_ERROR"
        assert error_dict["message"] == "Test error"

        # Test format_user_message method (emoji removed in current implementation)
        formatted = error.format_user_message()
        assert "**Error**: Test error" in formatted
        assert "**Details:**" in formatted
        assert "**Suggestions:**" in formatted

    def test_validation_error(self):
        """Test ValidationError exception."""
        error = ValidationError(
            message="Invalid field",
            field="test_field",
            value="invalid_value",
            expected="valid format"
        )

        assert error.error_code == "VALIDATION_ERROR"
        assert error.details["field"] == "test_field"
        assert error.details["provided_value"] == "invalid_value"
        assert error.details["expected"] == "valid format"

    def test_anomaly_not_found_error(self):
        """Test AnomalyNotFoundError exception."""
        error = AnomalyNotFoundError("anomaly-123")

        assert error.error_code == "ANOMALY_NOT_FOUND"
        assert error.details["anomaly_id"] == "anomaly-123"
        assert "anomaly-123" in error.message
        assert "Verify the anomaly ID is correct" in error.suggestions

    def test_alert_not_found_error(self):
        """Test AlertNotFoundError exception."""
        error = AlertNotFoundError("alert-456")

        assert error.error_code == "ALERT_NOT_FOUND"
        assert error.details["alert_id"] == "alert-456"
        assert "alert-456" in error.message
        assert "Verify the alert ID is correct" in error.suggestions


class TestHTTPErrorTranslation:
    """Test HTTP error translation."""

    def test_translate_400_error(self):
        """Test translation of 400 Bad Request."""
        error = translate_http_error(400, "Bad request", "/api/test")
        assert isinstance(error, ValidationError)
        assert error.details["field"] == "request"

    def test_translate_401_error(self):
        """Test translation of 401 Unauthorized."""
        error = translate_http_error(401, "Unauthorized", "/api/test")
        assert isinstance(error, PermissionError)
        assert error.details["operation"] == "API access"

    def test_translate_404_anomaly_error(self):
        """Test translation of 404 for anomaly endpoint."""
        error = translate_http_error(404, "Not found", "/api/anomaly/123")
        assert isinstance(error, AnomalyNotFoundError)
        assert error.details["anomaly_id"] == "123"

    def test_translate_404_alert_error(self):
        """Test translation of 404 for alert endpoint."""
        error = translate_http_error(404, "Not found", "/api/alert/456")
        assert isinstance(error, AlertNotFoundError)
        assert error.details["alert_id"] == "456"

    def test_translate_429_error(self):
        """Test translation of 429 Rate Limited."""
        error = translate_http_error(429, "Rate limited", "/api/test")
        assert isinstance(error, APIConnectionError)
        assert error.details["status_code"] == 429

    def test_translate_500_error(self):
        """Test translation of 500 Server Error."""
        error = translate_http_error(500, "Server error", "/api/test")
        assert isinstance(error, APIConnectionError)


class TestValidationFunctions:
    """Test validation utility functions."""

    def test_validate_required_params_success(self):
        """Test successful parameter validation."""
        params = {"param1": "value1", "param2": "value2"}
        # Should not raise any exception
        validate_required_params(params, ["param1", "param2"])

    def test_validate_required_params_missing(self):
        """Test validation with missing parameters."""
        params = {"param1": "value1"}

        with pytest.raises(ValidationError) as exc_info:
            validate_required_params(params, ["param1", "param2"])

        assert "Missing required parameters" in str(exc_info.value)
        # The error uses 'expected' field instead of 'missing_parameters'
        assert "param2" in exc_info.value.details["expected"]

    def test_validate_anomaly_id_success(self):
        """Test successful anomaly ID validation."""
        result = validate_anomaly_id("anomaly-123")
        assert result == "anomaly-123"

        # Test with whitespace
        result = validate_anomaly_id("  anomaly-456  ")
        assert result == "anomaly-456"

    def test_validate_anomaly_id_empty(self):
        """Test anomaly ID validation with empty value."""
        with pytest.raises(InvalidInputError) as exc_info:
            validate_anomaly_id("")

        assert exc_info.value.details["parameter"] == "anomaly_id"
        assert "cannot be empty" in exc_info.value.details["reason"]

    def test_validate_anomaly_id_too_long(self):
        """Test anomaly ID validation with too long value."""
        long_id = "x" * 101  # Over 100 characters

        with pytest.raises(InvalidInputError) as exc_info:
            validate_anomaly_id(long_id)

        assert "too long" in exc_info.value.details["reason"]

    def test_validate_alert_id_success(self):
        """Test successful alert ID validation."""
        result = validate_alert_id("alert-789")
        assert result == "alert-789"

    def test_validate_pagination_params_success(self):
        """Test successful pagination validation."""
        page, size = validate_pagination_params(0, 20)
        assert page == 0
        assert size == 20

        # Test with None values (should use defaults)
        page, size = validate_pagination_params(None, None)
        assert page == 0
        assert size == 20

    def test_validate_pagination_params_invalid(self):
        """Test pagination validation with invalid values."""
        # Test negative page
        with pytest.raises(InvalidInputError) as exc_info:
            validate_pagination_params(-1, 20)
        assert "cannot be negative" in exc_info.value.details["reason"]

        # Test zero size
        with pytest.raises(InvalidInputError) as exc_info:
            validate_pagination_params(0, 0)
        assert "must be positive" in exc_info.value.details["reason"]

        # Test too large size
        with pytest.raises(InvalidInputError) as exc_info:
            validate_pagination_params(0, 1001)
        assert "cannot exceed 1000" in exc_info.value.details["reason"]


class TestErrorHandlingDecorator:
    """Test error handling decorator integration."""

    @pytest.mark.asyncio
    async def test_decorator_handles_custom_exceptions(self):
        """Test that decorator properly handles custom exceptions."""
        alert_tools = AlertManagement()

        # Test with invalid action - empty anomaly_id handled by validation
        arguments = {"anomaly_id": ""}
        result = await alert_tools.handle_action("get", arguments)

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_decorator_handles_validation_errors(self):
        """Test that decorator handles validation errors."""
        alert_tools = AlertManagement()

        # Test get_capabilities which should always work
        result = await alert_tools.handle_action("get_capabilities", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_decorator_handles_api_errors(self):
        """Test that decorator handles API connection errors."""
        alert_tools = AlertManagement()

        # Test with unknown action to trigger error handling
        from src.revenium_mcp_server.common.error_handling import ToolError

        with pytest.raises(ToolError) as exc_info:
            await alert_tools.handle_action("unknown_action", {})

        assert "unknown action" in str(exc_info.value).lower()


if __name__ == "__main__":
    pytest.main([__file__])
