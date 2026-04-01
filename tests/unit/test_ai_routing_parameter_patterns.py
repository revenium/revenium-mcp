"""Unit tests for ai_routing.parameter_patterns module.

Tests that ParameterPatterns correctly extracts parameter values
from natural language queries using regex patterns.
"""

import pytest

from src.revenium_mcp_server.ai_routing.parameter_patterns import ParameterPatterns


@pytest.fixture
def patterns():
    return ParameterPatterns()


class TestNamePatterns:
    """Tests for name extraction patterns."""

    def test_extracts_quoted_name_with_called(self, patterns):
        for p in patterns.patterns["name"]:
            m = p.findall('create product called "API Gateway"')
            if m:
                assert "API Gateway" in m[0] if isinstance(m[0], tuple) else m
                return
        pytest.fail("No name pattern matched quoted 'called' form")

    def test_extracts_product_name(self, patterns):
        for p in patterns.patterns["name"]:
            m = p.findall('product "Billing Service"')
            if m:
                assert "Billing Service" in (m[0] if isinstance(m[0], str) else m[0])
                return
        pytest.fail("No name pattern matched product name")


class TestEmailPatterns:
    """Tests for email extraction patterns."""

    def test_extracts_email(self, patterns):
        for p in patterns.patterns["email"]:
            m = p.findall("add customer john@company.com")
            if m:
                assert "john@company.com" in m
                return
        pytest.fail("No email pattern matched")

    def test_no_match_for_invalid_email(self, patterns):
        for p in patterns.patterns["email"]:
            m = p.findall("add customer john@")
            assert len(m) == 0


class TestIdPatterns:
    """Tests for ID extraction patterns."""

    def test_extracts_id_with_prefix(self, patterns):
        for p in patterns.patterns["id"]:
            m = p.findall("get product id: abc12345")
            if m and "abc12345" in m:
                return
        # ID patterns also have a generic 8+ char pattern
        for p in patterns.patterns["id"]:
            m = p.findall("get product abc12345")
            if m and "abc12345" in m:
                return
        pytest.fail("No ID pattern matched")


class TestAmountPatterns:
    """Tests for amount extraction patterns."""

    def test_extracts_dollar_amount(self, patterns):
        for p in patterns.patterns["amount"]:
            m = p.findall("set price to $29.99")
            if m and "29.99" in m:
                return
        pytest.fail("No amount pattern matched dollar format")


class TestDatePatterns:
    """Tests for date extraction patterns."""

    def test_extracts_iso_date(self, patterns):
        for p in patterns.patterns["date"]:
            m = p.findall("created on 2024-01-15")
            if m and "2024-01-15" in m:
                return
        pytest.fail("No date pattern matched ISO format")

    def test_extracts_slash_date(self, patterns):
        for p in patterns.patterns["date"]:
            m = p.findall("from 1/15/2024")
            if m and "1/15/2024" in m:
                return
        pytest.fail("No date pattern matched slash format")


class TestTimePeriodPatterns:
    """Tests for time period extraction patterns."""

    def test_extracts_yesterday(self, patterns):
        for p in patterns.patterns["time_period"]:
            m = p.findall("show alerts from yesterday")
            if m and any("yesterday" in str(x).lower() for x in m):
                return
        pytest.fail("No time_period pattern matched 'yesterday'")

    def test_extracts_last_week(self, patterns):
        for p in patterns.patterns["time_period"]:
            m = p.findall("alerts from last week")
            if m:
                return
        pytest.fail("No time_period pattern matched 'last week'")


class TestStatusPatterns:
    """Tests for status extraction patterns."""

    def test_extracts_status_value(self, patterns):
        for p in patterns.patterns["status"]:
            m = p.findall("show status: active products")
            if m and "active" in [x.lower() for x in m]:
                return
        pytest.fail("No status pattern matched")


class TestPriorityPatterns:
    """Tests for priority extraction patterns."""

    def test_extracts_priority_value(self, patterns):
        for p in patterns.patterns["priority"]:
            m = p.findall("set priority: high")
            if m and "high" in [x.lower() for x in m]:
                return
        pytest.fail("No priority pattern matched")

    def test_extracts_priority_prefix(self, patterns):
        for p in patterns.patterns["priority"]:
            m = p.findall("high priority alert")
            if m and "high" in [x.lower() for x in m]:
                return
        pytest.fail("No priority pattern matched prefix form")


class TestProductTypePatterns:
    """Tests for product type extraction patterns."""

    def test_extracts_type_value(self, patterns):
        for p in patterns.patterns["product_type"]:
            m = p.findall("type: api")
            if m and "api" in [x.lower() for x in m]:
                return
        pytest.fail("No product_type pattern matched")


class TestWorkflowTypePatterns:
    """Tests for workflow type extraction patterns."""

    def test_extracts_workflow_type(self, patterns):
        for p in patterns.patterns["workflow_type"]:
            m = p.findall("start subscription_setup workflow")
            if m and "subscription_setup" in [x.lower() for x in m]:
                return
        pytest.fail("No workflow_type pattern matched")


class TestAllPatternCategoriesPresent:
    """Verify all expected pattern categories are registered."""

    def test_all_categories_exist(self, patterns):
        expected = {
            "name", "email", "id", "product_type", "workflow_type",
            "amount", "date", "time_period", "status", "priority",
        }
        assert expected == set(patterns.patterns.keys())
