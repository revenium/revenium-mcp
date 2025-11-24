"""Unit tests for alert filter update functionality."""

import pytest
from pydantic import ValidationError

from src.revenium_mcp_server.models_decomposed.alerts import (
    AlertFilter,
    FilterOperator,
)


class TestAlertFilterValidation:
    """Test AlertFilter validation."""

    def test_valid_filter_creation(self):
        """Test creating a valid filter."""
        filter_obj = AlertFilter(
            field="status",
            operator="equals",
            value="active"
        )
        assert filter_obj.field == "status"
        assert filter_obj.operator == "equals"
        assert filter_obj.value == "active"

    def test_filter_with_string_value(self):
        """Test filter with string value."""
        filter_obj = AlertFilter(
            field="name",
            operator="contains",
            value="test"
        )
        assert filter_obj.value == "test"

    def test_filter_with_integer_value(self):
        """Test filter with integer value."""
        filter_obj = AlertFilter(
            field="count",
            operator="greater_than",
            value=100
        )
        assert filter_obj.value == 100

    def test_filter_with_float_value(self):
        """Test filter with float value."""
        filter_obj = AlertFilter(
            field="threshold",
            operator="less_than",
            value=99.5
        )
        assert filter_obj.value == 99.5

    def test_filter_with_boolean_value(self):
        """Test filter with boolean value."""
        filter_obj = AlertFilter(
            field="enabled",
            operator="equals",
            value=True
        )
        assert filter_obj.value is True


class TestAlertFilterEdgeCases:
    """Test AlertFilter edge cases."""

    def test_filter_empty_field_fails(self):
        """Test that empty field fails validation."""
        with pytest.raises(ValidationError):
            AlertFilter(
                field="",
                operator="equals",
                value="test"
            )

    def test_filter_empty_operator_fails(self):
        """Test that empty operator fails validation."""
        with pytest.raises(ValidationError):
            AlertFilter(
                field="status",
                operator="",
                value="test"
            )

    def test_filter_whitespace_field_fails(self):
        """Test that whitespace-only field fails validation."""
        with pytest.raises(ValidationError):
            AlertFilter(
                field="   ",
                operator="equals",
                value="test"
            )


class TestFilterOperatorEnum:
    """Test FilterOperator enum values."""

    def test_equals_operator(self):
        """Test EQUALS operator value."""
        assert FilterOperator.EQUALS.value == "eq"

    def test_not_equals_operator(self):
        """Test NOT_EQUALS operator value."""
        assert FilterOperator.NOT_EQUALS.value == "ne"

    def test_comparison_operators(self):
        """Test comparison operator values."""
        assert FilterOperator.GREATER_THAN.value == "gt"
        assert FilterOperator.GREATER_THAN_OR_EQUAL.value == "gte"
        assert FilterOperator.LESS_THAN.value == "lt"
        assert FilterOperator.LESS_THAN_OR_EQUAL.value == "lte"

    def test_string_operators(self):
        """Test string operator values."""
        assert FilterOperator.CONTAINS.value == "contains"
        assert FilterOperator.NOT_CONTAINS.value == "not_contains"

    def test_collection_operators(self):
        """Test collection operator values."""
        assert FilterOperator.IN.value == "in"
        assert FilterOperator.NOT_IN.value == "not_in"
