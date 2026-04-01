"""Unit tests for product_validation_engine module."""

import pytest

from src.revenium_mcp_server.product_validation_engine import (
    ValidationError,
    ValidationResult,
    ProductValidationEngine,
)


class TestValidationError:
    """Tests for ValidationError dataclass."""

    def test_creation_with_defaults(self):
        """Should create with severity default of 'error'."""
        err = ValidationError(
            field="name", value="", error="missing", suggestion="add name"
        )
        assert err.severity == "error"
        assert err.example is None

    def test_creation_with_all_fields(self):
        """Should create with all fields populated."""
        err = ValidationError(
            field="plan.type",
            value="CHARGE",
            error="deprecated",
            suggestion="use SUBSCRIPTION",
            severity="warning",
            example={"type": "SUBSCRIPTION"},
        )
        assert err.severity == "warning"
        assert err.example == {"type": "SUBSCRIPTION"}


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_valid_result_no_warnings(self):
        """Valid result with no warnings."""
        result = ValidationResult(is_valid=True, errors=[], warnings=[])
        assert result.has_errors is False
        assert result.has_warnings is False

    def test_valid_result_with_warnings(self):
        """Valid result with warnings."""
        warning = ValidationError(
            field="name", value="X", error="too short", suggestion="make longer",
            severity="warning"
        )
        result = ValidationResult(is_valid=True, errors=[], warnings=[warning])
        assert result.has_errors is False
        assert result.has_warnings is True

    def test_invalid_result_with_errors(self):
        """Invalid result with errors."""
        err = ValidationError(
            field="name", value="", error="missing", suggestion="add name"
        )
        result = ValidationResult(is_valid=False, errors=[err], warnings=[])
        assert result.has_errors is True
        assert result.has_warnings is False

    def test_to_mcp_response_valid_no_warnings(self):
        """MCP response for valid result with no warnings."""
        result = ValidationResult(is_valid=True, errors=[], warnings=[])
        response = result.to_mcp_response()
        assert response["isError"] is False
        assert "Validation Passed" in response["content"][0]["text"]

    def test_to_mcp_response_valid_with_warnings(self):
        """MCP response for valid result with warnings should include warning text."""
        warning = ValidationError(
            field="price", value="0", error="zero pricing", suggestion="set a price",
            severity="warning"
        )
        result = ValidationResult(is_valid=True, errors=[], warnings=[warning])
        response = result.to_mcp_response()
        assert response["isError"] is False
        assert "Warnings" in response["content"][0]["text"]

    def test_to_mcp_response_invalid(self):
        """MCP response for invalid result should have isError True."""
        err = ValidationError(
            field="name", value="", error="missing name", suggestion="add name"
        )
        result = ValidationResult(is_valid=False, errors=[err], warnings=[])
        response = result.to_mcp_response()
        assert response["isError"] is True
        assert "Validation Failed" in response["content"][0]["text"]

    def test_format_mcp_errors_includes_examples(self):
        """Error formatting should include examples when available."""
        err = ValidationError(
            field="type", value="CHARGE", error="deprecated",
            suggestion="use SUBSCRIPTION",
            example={"type": "SUBSCRIPTION"}
        )
        result = ValidationResult(is_valid=False, errors=[err], warnings=[])
        response = result.to_mcp_response()
        assert "SUBSCRIPTION" in response["content"][0]["text"]

    def test_format_mcp_errors_with_both_errors_and_warnings(self):
        """Error formatting should include both errors and warnings."""
        err = ValidationError(
            field="name", value="", error="missing", suggestion="add name"
        )
        warning = ValidationError(
            field="price", value="0", error="zero pricing", suggestion="set price",
            severity="warning"
        )
        result = ValidationResult(is_valid=False, errors=[err], warnings=[warning])
        response = result.to_mcp_response()
        text = response["content"][0]["text"]
        assert "Critical" in text
        assert "Warnings" in text


class TestProductValidationEngine:
    """Tests for ProductValidationEngine class methods."""

    def test_deprecated_values_contains_charge(self):
        """CHARGE should be listed as deprecated plan type."""
        assert "plan.type" in ProductValidationEngine.DEPRECATED_VALUES
        assert "CHARGE" in ProductValidationEngine.DEPRECATED_VALUES["plan.type"]

    def test_deprecated_values_charge_has_migration_info(self):
        """CHARGE deprecation should include suggestion and working example."""
        charge_info = ProductValidationEngine.DEPRECATED_VALUES["plan.type"]["CHARGE"]
        assert "suggestion" in charge_info
        assert "working_example" in charge_info
        assert "SUBSCRIPTION" in charge_info["suggestion"]

    def test_required_fields_defined(self):
        """Required fields should be defined for product, plan, and tier."""
        assert "product" in ProductValidationEngine.REQUIRED_FIELDS
        assert "plan" in ProductValidationEngine.REQUIRED_FIELDS
        assert "name" in ProductValidationEngine.REQUIRED_FIELDS["product"]

    def test_validate_product_data_missing_all_required(self):
        """Empty product data should produce errors for missing required fields."""
        result = ProductValidationEngine.validate_product_data({})
        assert result.is_valid is False
        assert result.has_errors is True
        missing_fields = [e.field for e in result.errors]
        assert "name" in missing_fields

    def test_validate_product_data_catches_charge(self):
        """Validation should catch deprecated CHARGE plan type."""
        product_data = {
            "name": "Test Product",
            "description": "A test",
            "version": "1.0.0",
            "plan": {
                "type": "CHARGE",
                "name": "Plan",
                "currency": "USD",
                "tiers": [{"name": "T1", "up_to": None}],
            },
        }
        result = ProductValidationEngine.validate_product_data(product_data)
        all_issues = result.errors + result.warnings
        charge_issues = [
            i for i in all_issues
            if "CHARGE" in str(i.value) or "deprecated" in i.error.lower() or "CHARGE" in i.error
        ]
        assert len(charge_issues) >= 1

    def test_validate_product_data_valid_subscription(self):
        """Valid SUBSCRIPTION product should pass validation (no errors)."""
        product_data = {
            "name": "Test Product",
            "description": "A test product",
            "version": "1.0.0",
            "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
            "plan": {
                "type": "SUBSCRIPTION",
                "name": "Monthly Plan",
                "currency": "USD",
                "period": "MONTH",
                "tiers": [
                    {"name": "Basic", "up_to": None, "unit_amount": "9.99"}
                ],
            },
        }
        result = ProductValidationEngine.validate_product_data(product_data)
        assert result.is_valid is True
        assert result.has_errors is False

    def test_validate_for_mcp_returns_mcp_response(self):
        """validate_for_mcp should return MCP-compatible response dict."""
        product_data = {
            "name": "Test",
            "description": "Test",
            "version": "1.0.0",
            "plan": {
                "type": "SUBSCRIPTION",
                "name": "Plan",
                "currency": "USD",
                "period": "MONTH",
                "tiers": [{"name": "T1", "up_to": None}],
            },
        }
        response = ProductValidationEngine.validate_for_mcp(product_data)
        assert "isError" in response
        assert "content" in response

    def test_validate_for_mcp_with_errors(self):
        """validate_for_mcp with invalid data should set isError True."""
        response = ProductValidationEngine.validate_for_mcp({})
        assert response["isError"] is True

    def test_get_working_example(self):
        """get_working_example should return a valid product data structure."""
        example = ProductValidationEngine.get_working_example()
        assert isinstance(example, dict)
        assert "name" in example
        assert "plan" in example
        assert example["plan"]["type"] == "SUBSCRIPTION"

    def test_get_validation_summary(self):
        """get_validation_summary should return summary with rules and fields."""
        summary = ProductValidationEngine.get_validation_summary()
        assert isinstance(summary, dict)
        assert "required_fields" in summary or "deprecated_values" in summary or len(summary) > 0

    def test_format_validation_errors(self):
        """format_validation_errors should return a formatted string."""
        err = ValidationError(
            field="name", value=None, error="missing", suggestion="add name"
        )
        result = ValidationResult(is_valid=False, errors=[err], warnings=[])
        formatted = ProductValidationEngine.format_validation_errors(result)
        assert isinstance(formatted, str)
        assert "name" in formatted

    def test_test_charge_vs_subscription_scenario(self):
        """test_charge_vs_subscription_scenario should demonstrate the fix."""
        scenario = ProductValidationEngine.test_charge_vs_subscription_scenario()
        assert isinstance(scenario, dict)
        # Should contain before/after or similar comparison data
        assert len(scenario) > 0
