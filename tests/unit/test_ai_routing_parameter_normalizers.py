"""Unit tests for ai_routing.parameter_normalizers module.

Tests ParameterNormalizers: normalization of names, emails, IDs, amounts,
dates, time periods, statuses, priorities, product types, and workflow types.
"""

import pytest

from src.revenium_mcp_server.ai_routing.parameter_normalizers import ParameterNormalizers


@pytest.fixture
def normalizers():
    return ParameterNormalizers()


class TestNameNormalization:
    """Tests for _normalize_name."""

    def test_strips_whitespace_and_quotes(self, normalizers):
        assert normalizers.normalizers["name"]('"API Gateway"') == "API Gateway"

    def test_returns_none_for_empty(self, normalizers):
        assert normalizers.normalizers["name"]("") is None

    def test_returns_none_for_too_long(self, normalizers):
        assert normalizers.normalizers["name"]("x" * 101) is None

    def test_returns_none_for_non_string(self, normalizers):
        assert normalizers.normalizers["name"](None) is None


class TestEmailNormalization:
    """Tests for _normalize_email."""

    def test_lowercases_email(self, normalizers):
        assert normalizers.normalizers["email"]("John@Example.COM") == "john@example.com"

    def test_returns_none_for_invalid_email(self, normalizers):
        assert normalizers.normalizers["email"]("not-email") is None

    def test_returns_none_for_empty(self, normalizers):
        assert normalizers.normalizers["email"]("") is None


class TestIdNormalization:
    """Tests for _normalize_id."""

    def test_strips_whitespace(self, normalizers):
        assert normalizers.normalizers["id"]("  abc-123  ") == "abc-123"

    def test_returns_none_for_invalid_chars(self, normalizers):
        assert normalizers.normalizers["id"]("has spaces") is None

    def test_returns_none_for_empty(self, normalizers):
        assert normalizers.normalizers["id"]("") is None


class TestAmountNormalization:
    """Tests for _normalize_amount."""

    def test_strips_currency_symbol(self, normalizers):
        assert normalizers.normalizers["amount"]("$29.99") == 29.99

    def test_rounds_to_two_decimals(self, normalizers):
        assert normalizers.normalizers["amount"]("19.999") == 20.0

    def test_negative_sign_stripped_and_treated_as_positive(self, normalizers):
        """The normalizer strips non-digit chars, so '-5.00' becomes 5.0."""
        assert normalizers.normalizers["amount"]("-5.00") == 5.0

    def test_returns_none_for_excessive(self, normalizers):
        assert normalizers.normalizers["amount"]("2000000") is None

    def test_returns_none_for_empty(self, normalizers):
        assert normalizers.normalizers["amount"]("") is None

    def test_returns_none_for_non_numeric(self, normalizers):
        assert normalizers.normalizers["amount"]("abc") is None


class TestDateNormalization:
    """Tests for _normalize_date."""

    def test_iso_format_passthrough(self, normalizers):
        assert normalizers.normalizers["date"]("2024-01-15") == "2024-01-15"

    def test_slash_format_converted(self, normalizers):
        result = normalizers.normalizers["date"]("01/15/2024")
        assert result == "2024-01-15"

    def test_returns_none_for_invalid_date(self, normalizers):
        assert normalizers.normalizers["date"]("not-a-date") is None

    def test_returns_none_for_empty(self, normalizers):
        assert normalizers.normalizers["date"]("") is None


class TestTimePeriodNormalization:
    """Tests for _normalize_time_period."""

    def test_yesterday_mapped(self, normalizers):
        assert normalizers.normalizers["time_period"]("yesterday") == "TWENTY_FOUR_HOURS"

    def test_today_mapped(self, normalizers):
        assert normalizers.normalizers["time_period"]("today") == "TODAY"

    def test_last_week_mapped(self, normalizers):
        assert normalizers.normalizers["time_period"]("last week") == "SEVEN_DAYS"

    def test_last_month_mapped(self, normalizers):
        assert normalizers.normalizers["time_period"]("last month") == "THIRTY_DAYS"

    def test_unknown_period_uppercased(self, normalizers):
        assert normalizers.normalizers["time_period"]("custom") == "CUSTOM"

    def test_returns_none_for_empty(self, normalizers):
        assert normalizers.normalizers["time_period"]("") is None


class TestStatusNormalization:
    """Tests for _normalize_status."""

    def test_standard_statuses_mapped(self, normalizers):
        assert normalizers.normalizers["status"]("active") == "active"
        assert normalizers.normalizers["status"]("inactive") == "inactive"
        assert normalizers.normalizers["status"]("pending") == "pending"

    def test_alias_done_maps_to_completed(self, normalizers):
        assert normalizers.normalizers["status"]("done") == "completed"

    def test_alias_error_maps_to_failed(self, normalizers):
        assert normalizers.normalizers["status"]("error") == "failed"

    def test_unknown_status_returns_none(self, normalizers):
        assert normalizers.normalizers["status"]("bogus") is None

    def test_returns_none_for_empty(self, normalizers):
        assert normalizers.normalizers["status"]("") is None


class TestPriorityNormalization:
    """Tests for _normalize_priority."""

    def test_standard_priorities(self, normalizers):
        assert normalizers.normalizers["priority"]("high") == "high"
        assert normalizers.normalizers["priority"]("low") == "low"
        assert normalizers.normalizers["priority"]("critical") == "critical"

    def test_alias_normal_maps_to_medium(self, normalizers):
        assert normalizers.normalizers["priority"]("normal") == "medium"

    def test_unknown_priority_returns_none(self, normalizers):
        assert normalizers.normalizers["priority"]("urgent") is None

    def test_returns_none_for_empty(self, normalizers):
        assert normalizers.normalizers["priority"]("") is None


class TestProductTypeNormalization:
    """Tests for _normalize_product_type."""

    def test_standard_types(self, normalizers):
        assert normalizers.normalizers["product_type"]("api") == "api"
        assert normalizers.normalizers["product_type"]("usage") == "usage"
        assert normalizers.normalizers["product_type"]("subscription") == "subscription"

    def test_alias_billing_maps_to_subscription(self, normalizers):
        assert normalizers.normalizers["product_type"]("billing") == "subscription"

    def test_alias_monitoring_maps_to_api(self, normalizers):
        assert normalizers.normalizers["product_type"]("monitoring") == "api"

    def test_unknown_type_returned_lowercased(self, normalizers):
        """Unknown types pass through lowercased (validation catches them later)."""
        assert normalizers.normalizers["product_type"]("Custom") == "custom"

    def test_returns_none_for_empty(self, normalizers):
        assert normalizers.normalizers["product_type"]("") is None


class TestWorkflowTypeNormalization:
    """Tests for _normalize_workflow_type."""

    def test_standard_types(self, normalizers):
        assert normalizers.normalizers["workflow_type"]("subscription_setup") == "subscription_setup"
        assert normalizers.normalizers["workflow_type"]("customer_onboarding") == "customer_onboarding"

    def test_alias_setup_maps(self, normalizers):
        assert normalizers.normalizers["workflow_type"]("setup") == "subscription_setup"

    def test_alias_onboarding_maps(self, normalizers):
        assert normalizers.normalizers["workflow_type"]("onboarding") == "customer_onboarding"

    def test_alias_creation_maps(self, normalizers):
        assert normalizers.normalizers["workflow_type"]("creation") == "product_creation"

    def test_unknown_returns_none(self, normalizers):
        assert normalizers.normalizers["workflow_type"]("bogus") is None

    def test_returns_none_for_empty(self, normalizers):
        assert normalizers.normalizers["workflow_type"]("") is None


class TestAllNormalizerCategoriesPresent:
    """Verify all expected normalizer categories are registered."""

    def test_all_categories_exist(self, normalizers):
        expected = {
            "name", "email", "id", "product_type", "workflow_type",
            "amount", "date", "time_period", "status", "priority",
        }
        assert expected == set(normalizers.normalizers.keys())
