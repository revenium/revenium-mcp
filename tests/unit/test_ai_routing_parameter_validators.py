"""Unit tests for ai_routing.parameter_validators module.

Tests ParameterValidators: missing required params, type-specific validation
(email, amount, name, id, product_type, workflow_type), and operation-context
validation.
"""

import pytest

from src.revenium_mcp_server.ai_routing.parameter_validators import ParameterValidators


@pytest.fixture
def validator():
    return ParameterValidators()


class TestMissingRequiredParameters:
    """Tests for missing required parameter detection."""

    def test_all_present_no_errors(self, validator):
        errors = validator.validate_parameters(
            {"name": "test", "email": "a@b.com"}, ["name", "email"]
        )
        assert not any("Missing" in e for e in errors)

    def test_missing_param_produces_error(self, validator):
        errors = validator.validate_parameters({"name": "test"}, ["name", "email"])
        assert any("email" in e for e in errors)

    def test_none_value_treated_as_missing(self, validator):
        errors = validator.validate_parameters(
            {"name": None}, ["name"]
        )
        assert any("name" in e for e in errors)


class TestEmailValidation:
    """Tests for email format validation."""

    def test_valid_email_accepted(self, validator):
        errors = validator.validate_parameters({"email": "user@example.com"}, [])
        assert not any("email" in e.lower() for e in errors)

    def test_invalid_email_rejected(self, validator):
        errors = validator.validate_parameters({"email": "not-an-email"}, [])
        assert any("Invalid email" in e for e in errors)

    def test_email_none_skipped(self, validator):
        errors = validator.validate_parameters({"email": None}, [])
        assert not any("email" in e.lower() for e in errors)


class TestAmountValidation:
    """Tests for amount validation."""

    def test_valid_amount_accepted(self, validator):
        errors = validator.validate_parameters({"amount": 29.99}, [])
        assert not any("amount" in e.lower() for e in errors)

    def test_negative_amount_rejected(self, validator):
        errors = validator.validate_parameters({"amount": -5.0}, [])
        assert any("amount" in e.lower() for e in errors)

    def test_excessive_amount_rejected(self, validator):
        errors = validator.validate_parameters({"amount": 2000000}, [])
        assert any("amount" in e.lower() for e in errors)

    def test_non_numeric_amount_rejected(self, validator):
        errors = validator.validate_parameters({"amount": "abc"}, [])
        assert any("amount" in e.lower() for e in errors)

    def test_amount_none_skipped(self, validator):
        errors = validator.validate_parameters({"amount": None}, [])
        assert not any("amount" in e.lower() for e in errors)


class TestNameValidation:
    """Tests for name validation."""

    def test_valid_name_accepted(self, validator):
        errors = validator.validate_parameters({"name": "API Gateway"}, [])
        assert not any("name" in e.lower() for e in errors)

    def test_empty_name_rejected(self, validator):
        errors = validator.validate_parameters({"name": "   "}, [])
        assert any("name" in e.lower() for e in errors)

    def test_very_long_name_rejected(self, validator):
        errors = validator.validate_parameters({"name": "x" * 101}, [])
        assert any("name" in e.lower() for e in errors)


class TestIdValidation:
    """Tests for ID validation."""

    def test_valid_id_accepted(self, validator):
        errors = validator.validate_parameters({"id": "abc-123_xyz"}, [])
        assert not any("ID" in e for e in errors)

    def test_invalid_id_with_spaces_rejected(self, validator):
        errors = validator.validate_parameters({"id": "has spaces"}, [])
        assert any("ID" in e for e in errors)


class TestProductTypeValidation:
    """Tests for product type validation."""

    def test_valid_product_type_accepted(self, validator):
        for pt in ["api", "usage", "subscription", "metering"]:
            errors = validator.validate_parameters({"product_type": pt}, [])
            assert not any("product type" in e.lower() for e in errors), f"Failed for {pt}"

    def test_invalid_product_type_rejected(self, validator):
        errors = validator.validate_parameters({"product_type": "bogus"}, [])
        assert any("product type" in e.lower() for e in errors)


class TestWorkflowTypeValidation:
    """Tests for workflow type validation."""

    def test_valid_workflow_type_accepted(self, validator):
        for wt in ["subscription_setup", "customer_onboarding", "product_creation"]:
            errors = validator.validate_parameters({"workflow_type": wt}, [])
            assert not any("workflow type" in e.lower() for e in errors), f"Failed for {wt}"

    def test_invalid_workflow_type_rejected(self, validator):
        errors = validator.validate_parameters({"workflow_type": "bogus"}, [])
        assert any("workflow type" in e.lower() for e in errors)


class TestOperationContextValidation:
    """Tests for operation-context-specific validation."""

    def test_products_create_requires_name(self, validator):
        errors = validator.validate_parameters({}, [], "products.create")
        assert any("name" in e.lower() for e in errors)

    def test_customers_create_requires_email(self, validator):
        errors = validator.validate_parameters({}, [], "customers.create")
        assert any("email" in e.lower() for e in errors)

    def test_workflows_start_requires_workflow_type(self, validator):
        errors = validator.validate_parameters({}, [], "workflows.start")
        assert any("workflow_type" in e.lower() for e in errors)

    def test_unknown_context_no_extra_errors(self, validator):
        errors = validator.validate_parameters({"name": "ok"}, [], "unknown.action")
        assert not any("requires" in e.lower() for e in errors)
