"""Unit tests for relationships.validation module.

Tests ValidationRule, DependencyValidationRule, IntegrityValidationRule,
BusinessRuleValidationRule, and CrossResourceValidator.
"""

import pytest

from src.revenium_mcp_server.relationships.validation import (
    BusinessRuleValidationRule,
    CrossResourceValidator,
    DependencyValidationRule,
    IntegrityValidationRule,
    ValidationRule,
)


class TestValidationRule:
    """Test base ValidationRule behavior."""

    def test_base_rule_always_passes(self):
        """Base rule validation always returns passed=True."""
        rule = ValidationRule("test", "desc", "base")
        result = rule.validate({}, {})
        assert result["passed"] is True

    def test_base_rule_attributes(self):
        """Base rule stores name, description, type, severity."""
        rule = ValidationRule("r1", "A rule", "dependency", severity="warning")
        assert rule.name == "r1"
        assert rule.severity == "warning"


class TestDependencyValidationRule:
    """Test dependency validation for cross-resource operations."""

    @pytest.fixture
    def rule(self):
        return DependencyValidationRule()

    def test_passes_when_no_dependencies_required(self, rule):
        """Resource types with no required dependencies pass."""
        op = {"resource_type": "products", "resource_data": {"name": "Widget"}}
        result = rule.validate(op, {})
        assert result["passed"] is True

    def test_fails_when_required_dep_is_empty(self, rule):
        """Missing or empty required dependency field causes failure."""
        op = {
            "resource_type": "subscriptions",
            "resource_data": {"product_id": ""},
        }
        result = rule.validate(op, {})
        assert result["passed"] is False
        assert len(result["missing_dependencies"]) > 0

    def test_fails_when_required_dep_is_empty_list(self, rule):
        """Empty list for a required dependency field causes failure."""
        op = {
            "resource_type": "subscriptions",
            "resource_data": {"product_id": []},
        }
        result = rule.validate(op, {})
        assert result["passed"] is False

    def test_passes_when_required_dep_present(self, rule):
        """Valid dependency value passes validation."""
        op = {
            "resource_type": "subscriptions",
            "resource_data": {"product_id": "prod123"},
        }
        result = rule.validate(op, {})
        assert result["passed"] is True

    def test_unknown_resource_type_passes(self, rule):
        """Unknown resource types have no required deps, so they pass."""
        op = {"resource_type": "unknown_type", "resource_data": {}}
        result = rule.validate(op, {})
        assert result["passed"] is True


class TestIntegrityValidationRule:
    """Test data integrity validation."""

    @pytest.fixture
    def rule(self):
        return IntegrityValidationRule()

    def test_products_too_many_sources_warns(self, rule):
        """Products with >10 source_ids trigger integrity warning."""
        op = {
            "resource_type": "products",
            "resource_data": {"source_ids": list(range(11))},
        }
        result = rule.validate(op, {})
        assert result["passed"] is False
        assert result["severity"] == "warning"

    def test_products_normal_sources_passes(self, rule):
        """Products with <=10 source_ids pass."""
        op = {
            "resource_type": "products",
            "resource_data": {"source_ids": ["s1", "s2"]},
        }
        result = rule.validate(op, {})
        assert result["passed"] is True

    def test_subscription_end_before_start_fails(self, rule):
        """Subscription with end_date before start_date fails."""
        op = {
            "resource_type": "subscriptions",
            "resource_data": {
                "start_date": "2025-06-15T00:00:00Z",
                "end_date": "2025-06-01T00:00:00Z",
            },
        }
        result = rule.validate(op, {})
        assert result["passed"] is False
        assert any("date" in issue["field"].lower() for issue in result["integrity_issues"])

    def test_subscription_valid_dates_passes(self, rule):
        """Subscription with valid date range passes."""
        op = {
            "resource_type": "subscriptions",
            "resource_data": {
                "start_date": "2025-06-01T00:00:00Z",
                "end_date": "2025-12-31T00:00:00Z",
            },
        }
        result = rule.validate(op, {})
        assert result["passed"] is True

    def test_subscription_invalid_date_format(self, rule):
        """Invalid date format triggers integrity issue."""
        op = {
            "resource_type": "subscriptions",
            "resource_data": {
                "start_date": "not-a-date",
                "end_date": "also-not-a-date",
            },
        }
        result = rule.validate(op, {})
        assert result["passed"] is False

    def test_unknown_type_passes(self, rule):
        """Unknown resource types pass integrity validation."""
        op = {"resource_type": "widgets", "resource_data": {}}
        result = rule.validate(op, {})
        assert result["passed"] is True


class TestBusinessRuleValidationRule:
    """Test business rule validation."""

    @pytest.fixture
    def rule(self):
        return BusinessRuleValidationRule()

    def test_product_name_too_short(self, rule):
        """Product name shorter than 3 chars fails."""
        op = {
            "resource_type": "products",
            "resource_data": {"name": "ab"},
        }
        result = rule.validate(op, {})
        assert result["passed"] is False
        assert any("name" in v["rule"] for v in result["business_violations"])

    def test_product_name_valid(self, rule):
        """Product name >= 3 chars passes."""
        op = {
            "resource_type": "products",
            "resource_data": {"name": "Widget Pro"},
        }
        result = rule.validate(op, {})
        assert result["passed"] is True

    def test_product_duplicate_name(self, rule):
        """Duplicate product name fails when existing products provided."""
        op = {
            "resource_type": "products",
            "resource_data": {"name": "Existing Product"},
        }
        context = {"existing_products": [{"name": "Existing Product"}]}
        result = rule.validate(op, context)
        assert result["passed"] is False
        assert any("uniqueness" in v["rule"] for v in result["business_violations"])

    def test_subscription_missing_product_id(self, rule):
        """Subscription create without product_id fails."""
        op = {
            "resource_type": "subscriptions",
            "type": "create",
            "resource_data": {},
        }
        result = rule.validate(op, {})
        assert result["passed"] is False

    def test_alert_negative_threshold(self, rule):
        """Alert with negative threshold fails."""
        op = {
            "resource_type": "alerts",
            "resource_data": {"threshold": -5},
        }
        result = rule.validate(op, {})
        assert result["passed"] is False

    def test_alert_non_numeric_threshold(self, rule):
        """Alert with non-numeric threshold fails."""
        op = {
            "resource_type": "alerts",
            "resource_data": {"threshold": "not a number"},
        }
        result = rule.validate(op, {})
        assert result["passed"] is False

    def test_alert_valid_threshold(self, rule):
        """Alert with valid positive threshold passes."""
        op = {
            "resource_type": "alerts",
            "resource_data": {"threshold": 100},
        }
        result = rule.validate(op, {})
        assert result["passed"] is True


class TestCrossResourceValidator:
    """Test the composite CrossResourceValidator."""

    @pytest.fixture
    def validator(self):
        return CrossResourceValidator()

    @pytest.mark.asyncio
    async def test_initialize_is_idempotent(self, validator):
        """Multiple initialize calls don't cause issues."""
        await validator.initialize()
        await validator.initialize()
        assert validator._initialized is True

    @pytest.mark.asyncio
    async def test_validate_valid_operation(self, validator):
        """Valid operation passes all rules."""
        op = {
            "resource_type": "products",
            "resource_data": {"name": "Good Product"},
        }
        result = await validator.validate_operation(op)
        assert result["validation_passed"] is True
        assert result["error_count"] == 0

    @pytest.mark.asyncio
    async def test_validate_operation_with_errors(self, validator):
        """Invalid operation produces errors."""
        op = {
            "resource_type": "products",
            "resource_data": {"name": "ab"},  # too short
        }
        result = await validator.validate_operation(op)
        assert result["validation_passed"] is False
        assert result["error_count"] > 0

    @pytest.mark.asyncio
    async def test_validate_operation_with_warnings(self, validator):
        """Operation with integrity warnings reports them."""
        op = {
            "resource_type": "products",
            "resource_data": {"name": "Good Name", "source_ids": list(range(15))},
        }
        result = await validator.validate_operation(op)
        assert result["has_warnings"] is True
        assert result["warning_count"] > 0

    @pytest.mark.asyncio
    async def test_recommendations_generated(self, validator):
        """Recommendations are generated based on errors and warnings."""
        op = {
            "resource_type": "products",
            "resource_data": {"name": "ab"},
        }
        result = await validator.validate_operation(op)
        assert len(result["recommendations"]) > 0
        assert any("Fix" in r for r in result["recommendations"])

    @pytest.mark.asyncio
    async def test_recommendations_for_clean_operation(self, validator):
        """Clean operation gets "safe to proceed" recommendation."""
        op = {
            "resource_type": "products",
            "resource_data": {"name": "Valid Product Name"},
        }
        result = await validator.validate_operation(op)
        recs = result["recommendations"]
        assert any("safe to proceed" in r.lower() for r in recs)
