"""Unit tests for analytics validation module.

Tests the behavioral correctness of:
- SupportedPeriod and SupportedAggregation enums
- ValidationError, DataProcessingError, ConfigurationError exceptions
- AnalyticsParams dataclass
- AnalyticsValidator — all validate_* methods
"""

import pytest

from src.revenium_mcp_server.analytics.validation import (
    AnalyticsValidator,
    ConfigurationError,
    DataProcessingError,
    ValidationError,
)


# ─────────────────────────────────────────────────────────────────────────────
# Exception hierarchy
# ─────────────────────────────────────────────────────────────────────────────


class TestExceptionHierarchy:
    """Ensure exceptions carry the expected payload and hierarchy."""

    def test_validation_error_carries_message_and_field(self):
        """ValidationError exposes message, field, and suggestions."""
        err = ValidationError("bad period", field="period", suggestions=["SEVEN_DAYS"])
        assert err.message == "bad period"
        assert err.field == "period"
        assert "SEVEN_DAYS" in err.suggestions

    def test_validation_error_defaults_empty_suggestions(self):
        """ValidationError with no suggestions defaults to empty list."""
        err = ValidationError("bad value")
        assert err.suggestions == []
        assert err.field is None

    def test_data_processing_error_is_analytics_error(self):
        """DataProcessingError inherits from AnalyticsError and carries message."""
        from src.revenium_mcp_server.analytics.validation import AnalyticsError

        err = DataProcessingError("processing failed")
        assert isinstance(err, AnalyticsError)
        assert "processing failed" in str(err)

    def test_configuration_error_is_analytics_error(self):
        """ConfigurationError inherits from AnalyticsError and carries message."""
        from src.revenium_mcp_server.analytics.validation import AnalyticsError

        err = ConfigurationError("config broken")
        assert isinstance(err, AnalyticsError)
        assert "config broken" in str(err)


# ─────────────────────────────────────────────────────────────────────────────
# AnalyticsValidator.validate_period
# ─────────────────────────────────────────────────────────────────────────────


class TestValidatePeriod:
    """Tests for AnalyticsValidator.validate_period."""

    @pytest.fixture
    def validator(self):
        return AnalyticsValidator()

    @pytest.mark.parametrize("period", ["HOUR", "EIGHT_HOURS", "TWENTY_FOUR_HOURS", "SEVEN_DAYS", "THIRTY_DAYS", "TWELVE_MONTHS"])
    def test_valid_periods_accepted(self, validator, period):
        """All documented period values are accepted and returned uppercase."""
        result = validator.validate_period(period)
        assert result == period

    def test_period_case_insensitive(self, validator):
        """Period validation is case-insensitive."""
        assert validator.validate_period("seven_days") == "SEVEN_DAYS"
        assert validator.validate_period("Hour") == "HOUR"

    def test_invalid_period_raises_validation_error(self, validator):
        """Unsupported period raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_period("NINETY_DAYS")
        assert exc_info.value.field == "period"
        assert "NINETY_DAYS" in exc_info.value.message

    def test_empty_period_raises_validation_error(self, validator):
        """Empty string period raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_period("")
        assert exc_info.value.field == "period"

    def test_none_period_raises_validation_error(self, validator):
        """None period raises ValidationError."""
        with pytest.raises(ValidationError):
            validator.validate_period(None)

    def test_error_suggestions_list_valid_periods(self, validator):
        """Error suggestions include valid period names."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_period("BAD_PERIOD")
        assert len(exc_info.value.suggestions) > 0


# ─────────────────────────────────────────────────────────────────────────────
# AnalyticsValidator.validate_threshold
# ─────────────────────────────────────────────────────────────────────────────


class TestValidateThreshold:
    """Tests for AnalyticsValidator.validate_threshold."""

    @pytest.fixture
    def validator(self):
        return AnalyticsValidator()

    def test_valid_float_threshold_accepted(self, validator):
        """Positive float is accepted and returned."""
        assert validator.validate_threshold(100.0) == 100.0

    def test_valid_int_threshold_accepted(self, validator):
        """Positive int is coerced to float and accepted."""
        result = validator.validate_threshold(50)
        assert result == 50.0
        assert isinstance(result, float)

    def test_valid_string_number_accepted(self, validator):
        """String representation of a positive number is accepted."""
        assert validator.validate_threshold("75.5") == 75.5

    def test_zero_threshold_raises_validation_error(self, validator):
        """Zero threshold raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_threshold(0)
        assert exc_info.value.field == "threshold"

    def test_negative_threshold_raises_validation_error(self, validator):
        """Negative threshold raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_threshold(-10.0)
        assert "positive" in exc_info.value.message.lower()

    def test_none_threshold_raises_validation_error(self, validator):
        """None threshold raises ValidationError."""
        with pytest.raises(ValidationError):
            validator.validate_threshold(None)

    def test_non_numeric_string_raises_validation_error(self, validator):
        """Non-numeric string raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_threshold("not-a-number")
        assert "number" in exc_info.value.message.lower()


# ─────────────────────────────────────────────────────────────────────────────
# AnalyticsValidator.validate_filters
# ─────────────────────────────────────────────────────────────────────────────


class TestValidateFilters:
    """Tests for AnalyticsValidator.validate_filters."""

    @pytest.fixture
    def validator(self):
        return AnalyticsValidator()

    def test_valid_provider_filter_accepted(self, validator):
        """provider filter key is accepted."""
        result = validator.validate_filters({"provider": "openai"})
        assert result == {"provider": "openai"}

    def test_valid_model_filter_accepted(self, validator):
        """model filter key is accepted."""
        result = validator.validate_filters({"model": "gpt-4"})
        assert result == {"model": "gpt-4"}

    def test_valid_customer_filter_accepted(self, validator):
        """customer filter key is accepted."""
        result = validator.validate_filters({"customer": "Acme Corp"})
        assert result == {"customer": "Acme Corp"}

    def test_valid_team_id_filter_accepted(self, validator):
        """team_id filter key is accepted."""
        result = validator.validate_filters({"team_id": "team-123"})
        assert result == {"team_id": "team-123"}

    def test_empty_filters_accepted(self, validator):
        """Empty dict is valid and returns empty dict."""
        result = validator.validate_filters({})
        assert result == {}

    def test_invalid_filter_key_raises_validation_error(self, validator):
        """Unknown filter key raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_filters({"unknown_key": "value"})
        assert exc_info.value.field == "filters"
        assert "unknown_key" in exc_info.value.message

    def test_non_dict_filters_raises_validation_error(self, validator):
        """Non-dict filters raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_filters("not-a-dict")
        assert exc_info.value.field == "filters"

    def test_filter_values_coerced_to_str(self, validator):
        """Filter values are coerced to strings."""
        result = validator.validate_filters({"team_id": 42})
        assert result["team_id"] == "42"


# ─────────────────────────────────────────────────────────────────────────────
# AnalyticsValidator.validate_date_range
# ─────────────────────────────────────────────────────────────────────────────


class TestValidateDateRange:
    """Tests for AnalyticsValidator.validate_date_range."""

    @pytest.fixture
    def validator(self):
        return AnalyticsValidator()

    def test_valid_date_range_returns_datetimes(self, validator):
        """Valid ISO date strings return datetime tuple."""
        start, end = validator.validate_date_range(
            "2024-01-01T00:00:00Z", "2024-01-31T23:59:59Z"
        )
        assert start < end

    def test_start_equals_end_raises_validation_error(self, validator):
        """start_date == end_date raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_date_range("2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z")
        assert exc_info.value.field == "date_range"

    def test_start_after_end_raises_validation_error(self, validator):
        """start_date after end_date raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_date_range("2024-01-31T00:00:00Z", "2024-01-01T00:00:00Z")
        assert "before" in exc_info.value.message.lower()

    def test_invalid_date_format_raises_validation_error(self, validator):
        """Malformed date string raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_date_range("not-a-date", "2024-01-31T00:00:00Z")
        assert exc_info.value.field == "date_range"


# ─────────────────────────────────────────────────────────────────────────────
# AnalyticsValidator.validate_analytics_params
# ─────────────────────────────────────────────────────────────────────────────


class TestValidateAnalyticsParams:
    """Tests for AnalyticsValidator.validate_analytics_params."""

    @pytest.fixture
    def validator(self):
        return AnalyticsValidator()

    def test_minimal_valid_params(self, validator):
        """period + aggregation produces a valid AnalyticsParams."""
        params = validator.validate_analytics_params({"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert params.period == "SEVEN_DAYS"
        assert params.aggregation == "TOTAL"
        assert params.threshold is None

    def test_group_param_maps_to_aggregation(self, validator):
        """'group' key is accepted as an alias for 'aggregation'."""
        params = validator.validate_analytics_params({"period": "SEVEN_DAYS", "group": "MEAN"})
        assert params.aggregation == "MEAN"

    def test_default_aggregation_when_omitted(self, validator):
        """Missing aggregation defaults to TOTAL."""
        params = validator.validate_analytics_params({"period": "HOUR"})
        assert params.aggregation == "TOTAL"

    def test_aggregation_defaults_when_both_group_and_aggregation_empty(self, validator):
        """When both group='' and aggregation='' are supplied, defaults to TOTAL."""
        params = validator.validate_analytics_params({"period": "HOUR", "group": "", "aggregation": ""})
        assert params.aggregation == "TOTAL"

    def test_threshold_included_when_provided(self, validator):
        """Threshold is validated and included in AnalyticsParams."""
        params = validator.validate_analytics_params(
            {"period": "SEVEN_DAYS", "aggregation": "TOTAL", "threshold": 100.0}
        )
        assert params.threshold == 100.0

    def test_filters_included_when_provided(self, validator):
        """Valid filters are included in AnalyticsParams."""
        params = validator.validate_analytics_params(
            {"period": "SEVEN_DAYS", "aggregation": "TOTAL", "filters": {"provider": "openai"}}
        )
        assert params.filters == {"provider": "openai"}

    def test_invalid_period_raises_validation_error(self, validator):
        """Invalid period propagates as ValidationError."""
        with pytest.raises(ValidationError):
            validator.validate_analytics_params({"period": "INVALID", "aggregation": "TOTAL"})

    def test_invalid_aggregation_raises_validation_error(self, validator):
        """Invalid aggregation raises ValidationError."""
        with pytest.raises(ValidationError):
            validator.validate_analytics_params({"period": "SEVEN_DAYS", "aggregation": "WRONG"})


# ─────────────────────────────────────────────────────────────────────────────
# Domain-specific validators
# ─────────────────────────────────────────────────────────────────────────────


class TestDomainValidators:
    """Tests for domain-specific validate_*_params methods."""

    @pytest.fixture
    def validator(self):
        return AnalyticsValidator()

    @pytest.mark.parametrize("method", [
        "validate_provider_costs_params",
        "validate_model_costs_params",
        "validate_customer_costs_params",
        "validate_api_key_costs_params",
        "validate_agent_costs_params",
        "validate_cost_summary_params",
    ])
    def test_standard_methods_return_period_and_aggregation(self, validator, method):
        """Standard cost validators return period and aggregation keys."""
        params = {"period": "SEVEN_DAYS", "aggregation": "TOTAL"}
        result = getattr(validator, method)(params)
        assert result["period"] == "SEVEN_DAYS"
        assert result["aggregation"] == "TOTAL"

    def test_validate_cost_spike_params_requires_threshold(self, validator):
        """validate_cost_spike_params raises ValidationError when threshold is missing."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_cost_spike_params({"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
        assert exc_info.value.field == "threshold"

    def test_validate_cost_spike_params_returns_threshold_and_period(self, validator):
        """validate_cost_spike_params returns threshold and period when valid."""
        result = validator.validate_cost_spike_params(
            {"period": "SEVEN_DAYS", "aggregation": "TOTAL", "threshold": 100.0}
        )
        assert result["threshold"] == 100.0
        assert result["period"] == "SEVEN_DAYS"

    @pytest.mark.parametrize("method", [
        "validate_provider_costs_params",
        "validate_model_costs_params",
    ])
    def test_standard_methods_reject_invalid_period(self, validator, method):
        """Standard cost validators propagate period validation errors."""
        with pytest.raises(ValidationError):
            getattr(validator, method)({"period": "BAD_PERIOD", "aggregation": "TOTAL"})


# ─────────────────────────────────────────────────────────────────────────────
# Agent costs costSources filter (BACK-2348)
# ─────────────────────────────────────────────────────────────────────────────


class TestValidateAgentCostsFilters:
    """Tests for the costSources filter on validate_agent_costs_params.

    The cost-by-agent endpoint only accepts the real-spend cost sources
    (revenium_metered, provider_billing) — unlike cost-by-user, which also
    accepts coding_assistant.
    """

    @pytest.fixture
    def validator(self):
        return AnalyticsValidator()

    def test_cost_sources_list_accepted(self, validator):
        """A valid costSources list is returned under filters."""
        result = validator.validate_agent_costs_params(
            {"period": "SEVEN_DAYS", "filters": {"costSources": ["provider_billing"]}}
        )
        assert result["filters"] == {"costSources": ["provider_billing"]}

    def test_cost_sources_string_normalized_to_list(self, validator):
        """A bare string value is normalized to a single-element list."""
        result = validator.validate_agent_costs_params(
            {"period": "SEVEN_DAYS", "filters": {"costSources": "revenium_metered"}}
        )
        assert result["filters"]["costSources"] == ["revenium_metered"]

    def test_both_real_spend_values_accepted(self, validator):
        """Both real-spend enum values pass together."""
        result = validator.validate_agent_costs_params(
            {
                "period": "SEVEN_DAYS",
                "filters": {"costSources": ["revenium_metered", "provider_billing"]},
            }
        )
        assert result["filters"]["costSources"] == ["revenium_metered", "provider_billing"]

    def test_coding_assistant_rejected(self, validator):
        """coding_assistant is valid for user costs but not for agent costs."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_agent_costs_params(
                {"period": "SEVEN_DAYS", "filters": {"costSources": ["coding_assistant"]}}
            )
        assert "coding_assistant" in exc_info.value.message
        assert any("provider_billing" in s for s in exc_info.value.suggestions)

    def test_unknown_filter_key_rejected(self, validator):
        """Filter keys other than costSources are rejected for agent costs."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_agent_costs_params(
                {"period": "SEVEN_DAYS", "filters": {"agents": ["support-bot"]}}
            )
        assert any("costSources" in s for s in exc_info.value.suggestions)

    def test_omitted_filters_leaves_validated_without_filters_key(self, validator):
        """No filters argument means no filters key in the validated params."""
        result = validator.validate_agent_costs_params({"period": "SEVEN_DAYS"})
        assert "filters" not in result


class TestFilterValidationHardening:
    """Shared _validate_array_filters edge cases raised in PR review."""

    @pytest.fixture
    def validator(self):
        return AnalyticsValidator()

    def test_provider_billing_accepted_for_user_costs(self, validator):
        """cost-by-user accepts all three cost sources on prod and dev."""
        result = validator.validate_user_costs_params(
            {"period": "SEVEN_DAYS", "filters": {"costSources": ["provider_billing"]}}
        )
        assert result["filters"]["costSources"] == ["provider_billing"]

    def test_empty_cost_sources_list_rejected_for_agent_costs(self, validator):
        """An empty list would silently drop the filter from the request."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_agent_costs_params(
                {"period": "SEVEN_DAYS", "filters": {"costSources": []}}
            )
        assert exc_info.value.field == "filters.costSources"

    def test_empty_filter_list_rejected_for_user_costs(self, validator):
        """Empty lists are rejected for every array filter key."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_user_costs_params(
                {"period": "SEVEN_DAYS", "filters": {"agents": []}}
            )
        assert exc_info.value.field == "filters.agents"

    def test_non_dict_filters_rejected_for_agent_costs(self, validator):
        """A JSON string instead of an object raises ValidationError, not AttributeError."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_agent_costs_params(
                {"period": "SEVEN_DAYS", "filters": "revenium_metered"}
            )
        assert exc_info.value.field == "filters"

    def test_non_dict_filters_rejected_for_user_costs(self, validator):
        """Same guard applies to the user-costs validator."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_user_costs_params(
                {"period": "SEVEN_DAYS", "filters": ["revenium_metered"]}
            )
        assert exc_info.value.field == "filters"
