"""Unit tests for ai_routing.parameter_mapper module.

Tests ParameterMapper: parameter mapping for different operation types,
nested value handling, default application, and validation.
"""

import pytest

from src.revenium_mcp_server.ai_routing.models import ExtractedParameters
from src.revenium_mcp_server.ai_routing.parameter_mapper import (
    ParameterMapper,
    ParameterMappingError,
)


@pytest.fixture
def mapper():
    return ParameterMapper()


class TestMapParametersProducts:
    """Tests for product operation parameter mapping."""

    def test_maps_product_create_name(self, mapper):
        params = ExtractedParameters(parameters={"name": "API Gateway"})
        result = mapper.map_parameters("products.create", params)
        assert result["action"] == "create"
        assert result["product_data"]["name"] == "API Gateway"

    def test_applies_default_product_type(self, mapper):
        params = ExtractedParameters(parameters={"name": "Test"})
        result = mapper.map_parameters("products.create", params)
        assert result["product_data"]["type"] == "api"

    def test_explicit_product_type_overrides_default(self, mapper):
        params = ExtractedParameters(
            parameters={"name": "Test", "product_type": "usage"}
        )
        result = mapper.map_parameters("products.create", params)
        assert result["product_data"]["type"] == "usage"

    def test_applies_description_default_with_name(self, mapper):
        params = ExtractedParameters(parameters={"name": "Billing"})
        result = mapper.map_parameters("products.create", params)
        assert "Billing" in result["product_data"]["description"]


class TestMapParametersCustomers:
    """Tests for customer operation parameter mapping."""

    def test_maps_customer_create_email(self, mapper):
        params = ExtractedParameters(parameters={"email": "john@test.com"})
        result = mapper.map_parameters("customers.create", params)
        assert result["action"] == "create"
        assert result["subscriber_data"]["email"] == "john@test.com"

    def test_applies_default_role(self, mapper):
        params = ExtractedParameters(parameters={"email": "john@test.com"})
        result = mapper.map_parameters("customers.create", params)
        assert result["subscriber_data"]["role"] == "ROLE_API_CONSUMER"

    def test_applies_default_name_from_email(self, mapper):
        params = ExtractedParameters(parameters={"email": "john@test.com"})
        result = mapper.map_parameters("customers.create", params)
        assert result["subscriber_data"]["name"] == "john"


class TestMapParametersWorkflows:
    """Tests for workflow operation parameter mapping."""

    def test_maps_workflow_start(self, mapper):
        params = ExtractedParameters(parameters={"workflow_type": "subscription_setup"})
        result = mapper.map_parameters("workflows.start", params)
        assert result["action"] == "start"
        assert result["workflow_type"] == "subscription_setup"

    def test_applies_default_context(self, mapper):
        params = ExtractedParameters(parameters={"workflow_type": "subscription_setup"})
        result = mapper.map_parameters("workflows.start", params)
        assert result["context"] == {}


class TestMapParametersAlerts:
    """Tests for alert operation parameter mapping."""

    def test_maps_alerts_list_with_defaults(self, mapper):
        params = ExtractedParameters(parameters={})
        result = mapper.map_parameters("alerts.list", params)
        assert result["action"] == "list"
        assert result["page"] == 0
        assert result["size"] == 20

    def test_maps_alerts_with_time_period(self, mapper):
        params = ExtractedParameters(parameters={"time_period": "SEVEN_DAYS"})
        result = mapper.map_parameters("alerts.list", params)
        assert result["filters"]["time_period"] == "SEVEN_DAYS"


class TestMapParametersSubscriptions:
    """Tests for subscription operation parameter mapping."""

    def test_maps_subscriptions_list_defaults(self, mapper):
        params = ExtractedParameters(parameters={})
        result = mapper.map_parameters("subscriptions.list", params)
        assert result["action"] == "list"
        assert result["page"] == 0
        assert result["size"] == 20


class TestGenericMapping:
    """Tests for generic (unknown operation) parameter mapping."""

    def test_unknown_operation_copies_params_directly(self, mapper):
        params = ExtractedParameters(parameters={"foo": "bar", "baz": 42})
        result = mapper.map_parameters("unknown.operation", params)
        assert result["foo"] == "bar"
        assert result["baz"] == 42

    def test_unknown_operation_skips_none_values(self, mapper):
        params = ExtractedParameters(parameters={"foo": "bar", "empty": None})
        result = mapper.map_parameters("unknown.operation", params)
        assert "empty" not in result


class TestNestedValueHelpers:
    """Tests for _set_nested_value and _has_nested_value."""

    def test_set_nested_value_creates_hierarchy(self, mapper):
        data = {}
        mapper._set_nested_value(data, "a.b.c", "value")
        assert data["a"]["b"]["c"] == "value"

    def test_set_nested_value_single_key(self, mapper):
        data = {}
        mapper._set_nested_value(data, "key", "val")
        assert data["key"] == "val"

    def test_has_nested_value_true(self, mapper):
        data = {"a": {"b": "c"}}
        assert mapper._has_nested_value(data, "a.b") is True

    def test_has_nested_value_false(self, mapper):
        data = {"a": {"b": "c"}}
        assert mapper._has_nested_value(data, "a.x") is False

    def test_has_nested_value_single_key(self, mapper):
        data = {"key": "val"}
        assert mapper._has_nested_value(data, "key") is True


class TestGetRequiredOptionalParameters:
    """Tests for get_required_parameters and get_optional_parameters."""

    def test_products_create_required(self, mapper):
        assert "name" in mapper.get_required_parameters("products.create")

    def test_alerts_list_no_required(self, mapper):
        assert mapper.get_required_parameters("alerts.list") == []

    def test_products_create_optional(self, mapper):
        optional = mapper.get_optional_parameters("products.create")
        assert "product_type" in optional

    def test_unknown_operation_returns_empty(self, mapper):
        assert mapper.get_required_parameters("unknown.op") == []
        assert mapper.get_optional_parameters("unknown.op") == []


class TestValidateParameters:
    """Tests for validate_parameters method."""

    def test_returns_missing_required_params(self, mapper):
        params = ExtractedParameters(parameters={})
        missing = mapper.validate_parameters("products.create", params)
        assert "name" in missing

    def test_returns_empty_when_all_present(self, mapper):
        params = ExtractedParameters(parameters={"name": "Test"})
        missing = mapper.validate_parameters("products.create", params)
        assert missing == []

    def test_none_value_treated_as_missing(self, mapper):
        params = ExtractedParameters(parameters={"name": None})
        missing = mapper.validate_parameters("products.create", params)
        assert "name" in missing
