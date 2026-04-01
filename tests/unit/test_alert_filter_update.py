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
        """Test creating a valid filter serializes to expected API shape."""
        filter_obj = AlertFilter(
            field="status",
            operator="equals",
            value="active"
        )
        dumped = filter_obj.model_dump()
        assert dumped["field"] == "status"
        assert dumped["operator"] == "equals"
        assert dumped["value"] == "active"
        assert set(dumped.keys()) == {"field", "operator", "value"}

    def test_filter_with_string_value(self):
        """Test filter with string value serializes value as string."""
        filter_obj = AlertFilter(
            field="name",
            operator="contains",
            value="test"
        )
        dumped = filter_obj.model_dump()
        assert dumped["value"] == "test"
        assert isinstance(dumped["value"], str)

    def test_filter_with_integer_value(self):
        """Test filter with integer value serializes value as integer."""
        filter_obj = AlertFilter(
            field="count",
            operator="greater_than",
            value=100
        )
        dumped = filter_obj.model_dump()
        assert dumped["value"] == 100
        assert isinstance(dumped["value"], int)

    def test_filter_with_float_value(self):
        """Test filter with float value serializes value as float."""
        filter_obj = AlertFilter(
            field="threshold",
            operator="less_than",
            value=99.5
        )
        dumped = filter_obj.model_dump()
        assert dumped["value"] == 99.5
        assert isinstance(dumped["value"], float)

    def test_filter_with_boolean_value(self):
        """Test filter with boolean value serializes value as bool."""
        filter_obj = AlertFilter(
            field="enabled",
            operator="equals",
            value=True
        )
        dumped = filter_obj.model_dump()
        assert dumped["value"] is True
        assert isinstance(dumped["value"], bool)


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
    """Test FilterOperator enum values are usable as AlertFilter operator strings."""

    def test_equals_operator(self):
        """Test EQUALS operator value is accepted by AlertFilter."""
        assert FilterOperator.EQUALS.value == "eq"
        f = AlertFilter(field="status", operator=FilterOperator.EQUALS.value, value="active")
        assert f.model_dump()["operator"] == "eq"

    def test_not_equals_operator(self):
        """Test NOT_EQUALS operator value is accepted by AlertFilter."""
        assert FilterOperator.NOT_EQUALS.value == "ne"
        f = AlertFilter(field="status", operator=FilterOperator.NOT_EQUALS.value, value="inactive")
        assert f.model_dump()["operator"] == "ne"

    def test_comparison_operators(self):
        """Test comparison operator values are accepted by AlertFilter."""
        assert FilterOperator.GREATER_THAN.value == "gt"
        assert FilterOperator.GREATER_THAN_OR_EQUAL.value == "gte"
        assert FilterOperator.LESS_THAN.value == "lt"
        assert FilterOperator.LESS_THAN_OR_EQUAL.value == "lte"
        for op in (FilterOperator.GREATER_THAN, FilterOperator.GREATER_THAN_OR_EQUAL,
                   FilterOperator.LESS_THAN, FilterOperator.LESS_THAN_OR_EQUAL):
            f = AlertFilter(field="count", operator=op.value, value=50)
            assert f.model_dump()["operator"] == op.value

    def test_string_operators(self):
        """Test string operator values are accepted by AlertFilter."""
        assert FilterOperator.CONTAINS.value == "contains"
        assert FilterOperator.NOT_CONTAINS.value == "not_contains"
        for op in (FilterOperator.CONTAINS, FilterOperator.NOT_CONTAINS):
            f = AlertFilter(field="name", operator=op.value, value="foo")
            assert f.model_dump()["operator"] == op.value

    def test_collection_operators(self):
        """Test collection operator values are accepted by AlertFilter."""
        assert FilterOperator.IN.value == "in"
        assert FilterOperator.NOT_IN.value == "not_in"
        for op in (FilterOperator.IN, FilterOperator.NOT_IN):
            f = AlertFilter(field="tag", operator=op.value, value="x")
            assert f.model_dump()["operator"] == op.value
