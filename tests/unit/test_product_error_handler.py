"""Unit tests for product_error_handler module."""

import pytest

from src.revenium_mcp_server.product_error_handler import (
    ErrorSeverity,
    ProductError,
    ProductErrorHandler,
)


class TestErrorSeverity:
    """Tests for ErrorSeverity enum."""

    def test_severity_values(self):
        """Should have all expected severity levels."""
        assert ErrorSeverity.CRITICAL == "critical"
        assert ErrorSeverity.ERROR == "error"
        assert ErrorSeverity.WARNING == "warning"
        assert ErrorSeverity.INFO == "info"


class TestProductErrorHandler:
    """Tests for ProductErrorHandler."""

    def setup_method(self):
        """Set up a fresh handler for each test."""
        self.handler = ProductErrorHandler()

    def test_enhance_api_error_matching_pattern(self):
        """Known error patterns should produce enhanced errors with context."""
        error = self.handler.enhance_api_error(
            "required field name is missing", {"plan": {"type": "SUBSCRIPTION"}}
        )
        assert isinstance(error, ProductError)
        assert error.severity == ErrorSeverity.CRITICAL
        assert error.code == "MISSING_REQUIRED_NAME"
        assert len(error.fix_steps) > 0

    def test_enhance_api_error_currency_pattern(self):
        """Currency error pattern should match and produce helpful guidance."""
        error = self.handler.enhance_api_error(
            "invalid currency code", {"plan": {"currency": "US"}}
        )
        assert error.code == "INVALID_CURRENCY"
        assert error.severity == ErrorSeverity.ERROR

    def test_enhance_api_error_unrecognized(self):
        """Unrecognized errors should get a generic enhanced error."""
        error = self.handler.enhance_api_error(
            "some totally unknown error xyz", {"name": "Test"}
        )
        assert error.code == "UNKNOWN_API_ERROR"
        assert error.severity == ErrorSeverity.ERROR
        assert len(error.fix_steps) > 0

    def test_validate_product_business_logic_missing_name(self):
        """Missing product name should produce a critical error."""
        errors = self.handler.validate_product_business_logic({})
        name_errors = [e for e in errors if e.field == "name"]
        assert len(name_errors) >= 1
        assert name_errors[0].severity == ErrorSeverity.CRITICAL

    def test_validate_product_business_logic_short_name(self):
        """Product name under 2 characters should produce an error."""
        errors = self.handler.validate_product_business_logic({"name": "A"})
        name_errors = [e for e in errors if e.field == "name"]
        assert len(name_errors) >= 1
        assert name_errors[0].code == "PRODUCT_NAME_TOO_SHORT"

    def test_validate_product_business_logic_valid_name(self):
        """Valid product name should not produce name errors."""
        errors = self.handler.validate_product_business_logic({"name": "Good Product"})
        name_errors = [e for e in errors if e.field == "name"]
        assert len(name_errors) == 0

    def test_validate_subscription_missing_period(self):
        """Subscription plan without period should produce a critical error."""
        product = {"name": "Test Product", "plan": {"type": "SUBSCRIPTION"}}
        errors = self.handler.validate_product_business_logic(product)
        period_errors = [e for e in errors if e.field == "plan.period"]
        assert len(period_errors) >= 1
        assert period_errors[0].severity == ErrorSeverity.CRITICAL

    def test_validate_subscription_with_period(self):
        """Subscription plan with period should not produce period errors."""
        product = {
            "name": "Test Product",
            "plan": {"type": "SUBSCRIPTION", "period": "MONTH"},
        }
        errors = self.handler.validate_product_business_logic(product)
        period_errors = [e for e in errors if e.field == "plan.period"]
        assert len(period_errors) == 0

    def test_validate_zero_pricing_non_free_product(self):
        """Zero pricing on a non-free product should produce a warning."""
        product = {
            "name": "Paid Service",
            "plan": {
                "type": "SUBSCRIPTION",
                "period": "MONTH",
                "tiers": [{"unit_amount": "0"}],
            },
        }
        errors = self.handler.validate_product_business_logic(product)
        pricing_warnings = [e for e in errors if e.code == "UNEXPECTED_ZERO_PRICING"]
        assert len(pricing_warnings) >= 1
        assert pricing_warnings[0].severity == ErrorSeverity.WARNING

    def test_validate_zero_pricing_free_product_ok(self):
        """Zero pricing on a product named 'Free ...' should not warn."""
        product = {
            "name": "Free Trial Plan",
            "plan": {
                "type": "SUBSCRIPTION",
                "period": "MONTH",
                "tiers": [{"unit_amount": "0"}],
            },
        }
        errors = self.handler.validate_product_business_logic(product)
        pricing_warnings = [e for e in errors if e.code == "UNEXPECTED_ZERO_PRICING"]
        assert len(pricing_warnings) == 0

    def test_get_field_guidance_known_field(self):
        """Known fields should return detailed guidance."""
        guidance = self.handler.get_field_guidance("name")
        assert "description" in guidance
        assert "best_practices" in guidance
        assert "examples" in guidance

    def test_get_field_guidance_unknown_field(self):
        """Unknown fields should return a fallback guidance."""
        guidance = self.handler.get_field_guidance("unknown_field_xyz")
        assert "description" in guidance

    def test_suggest_fixes_no_errors(self):
        """No errors should return a positive status."""
        result = self.handler.suggest_fixes([])
        assert result["status"] == "no_errors"

    def test_suggest_fixes_with_critical_errors(self):
        """Critical errors should produce high priority fix plan."""
        error = ProductError(
            code="MISSING_NAME",
            severity=ErrorSeverity.CRITICAL,
            field="name",
            message="Name is required",
            business_context="Customers need a name",
            fix_steps=["Add a name field"],
            examples=[],
            related_concepts=[],
            common_causes=[],
        )
        result = self.handler.suggest_fixes([error])
        assert result["priority"] == "high"
        assert len(result["immediate_actions"]) >= 1

    def test_suggest_fixes_with_warnings_only(self):
        """Warnings only should produce low priority fix plan."""
        warning = ProductError(
            code="ZERO_PRICE",
            severity=ErrorSeverity.WARNING,
            field="plan.tiers",
            message="Zero pricing",
            business_context="May be unintentional",
            fix_steps=["Check if pricing is intentional"],
            examples=[],
            related_concepts=[],
            common_causes=[],
        )
        result = self.handler.suggest_fixes([warning])
        assert result["priority"] == "low"
        assert len(result["recommended_improvements"]) >= 1

    def test_suggest_fixes_adds_learning_resources_for_tier_errors(self):
        """Errors on plan.tiers should trigger learning resources."""
        error = ProductError(
            code="TIER_ERROR",
            severity=ErrorSeverity.ERROR,
            field="plan.tiers",
            message="Tier issue",
            business_context="Tier config",
            fix_steps=["Fix tiers"],
            examples=[],
            related_concepts=[],
            common_causes=[],
        )
        result = self.handler.suggest_fixes([error])
        assert len(result["learning_resources"]) >= 1
