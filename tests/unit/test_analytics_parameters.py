"""Unit tests for analytics_parameters module."""

import pytest

from src.revenium_mcp_server.analytics_parameters import (
    TimePeriod,
    AggregationType,
    ChartType,
    SortOrder,
    BaseAnalyticsParams,
    CostAnalysisParams,
    VisualizationParams,
    PaginationParams,
    AdvancedAnalyticsParams,
    AnalyticsParameterValidator,
    AnalyticsParameterBuilder,
)


class TestEnums:
    """Tests for analytics enum types."""

    def test_time_period_values(self):
        assert TimePeriod.HOUR.value == "HOUR"
        assert TimePeriod.THIRTY_DAYS.value == "THIRTY_DAYS"
        assert TimePeriod.TWELVE_MONTHS.value == "TWELVE_MONTHS"

    def test_aggregation_type_values(self):
        assert AggregationType.TOTAL.value == "TOTAL"
        assert AggregationType.MEAN.value == "MEAN"
        assert AggregationType.MEDIAN.value == "MEDIAN"

    def test_chart_type_values(self):
        assert ChartType.BAR.value == "bar"
        assert ChartType.LINE.value == "line"
        assert ChartType.PIE.value == "pie"
        assert ChartType.AREA.value == "area"

    def test_sort_order_values(self):
        assert SortOrder.ASC.value == "asc"
        assert SortOrder.DESC.value == "desc"


class TestDataclasses:
    """Tests for analytics parameter dataclasses."""

    def test_base_analytics_params(self):
        p = BaseAnalyticsParams(action="get_costs", period=TimePeriod.THIRTY_DAYS)
        assert p.action == "get_costs"
        assert p.aggregation is None

    def test_cost_analysis_params(self):
        p = CostAnalysisParams(
            action="analyze", threshold=100.0, provider_filter="OPENAI"
        )
        assert p.threshold == 100.0
        assert p.include_details is False

    def test_visualization_params_defaults(self):
        p = VisualizationParams()
        assert p.chart_type is None
        assert p.include_chart is False
        assert p.width == 800
        assert p.height == 600

    def test_pagination_params_defaults(self):
        p = PaginationParams()
        assert p.limit is None
        assert p.offset == 0
        assert p.sort_order is None

    def test_advanced_analytics_params_defaults(self):
        p = AdvancedAnalyticsParams()
        assert p.output_format == "text"
        assert p.precision == 2
        assert p.strict_validation is True
        assert p.allow_partial_data is False
        assert p.include_summary is True


class TestAnalyticsParameterValidator:
    """Tests for AnalyticsParameterValidator."""

    def test_validate_period_valid(self):
        result = AnalyticsParameterValidator.validate_period("THIRTY_DAYS")
        assert result == TimePeriod.THIRTY_DAYS

    def test_validate_period_invalid(self):
        with pytest.raises(ValueError, match="Invalid period"):
            AnalyticsParameterValidator.validate_period("INVALID")

    def test_validate_aggregation_valid(self):
        result = AnalyticsParameterValidator.validate_aggregation("MEAN")
        assert result == AggregationType.MEAN

    def test_validate_aggregation_invalid(self):
        with pytest.raises(ValueError, match="Invalid aggregation"):
            AnalyticsParameterValidator.validate_aggregation("AVERAGE")

    def test_validate_chart_type_valid(self):
        result = AnalyticsParameterValidator.validate_chart_type("bar")
        assert result == ChartType.BAR

    def test_validate_chart_type_invalid(self):
        with pytest.raises(ValueError, match="Invalid chart type"):
            AnalyticsParameterValidator.validate_chart_type("scatter")

    def test_validate_threshold_valid(self):
        assert AnalyticsParameterValidator.validate_threshold(50.0) == 50.0

    def test_validate_threshold_zero(self):
        with pytest.raises(ValueError, match="positive"):
            AnalyticsParameterValidator.validate_threshold(0)

    def test_validate_threshold_negative(self):
        with pytest.raises(ValueError, match="positive"):
            AnalyticsParameterValidator.validate_threshold(-10.0)

    def test_validate_confidence_level_valid(self):
        assert AnalyticsParameterValidator.validate_confidence_level(0.95) == 0.95

    def test_validate_confidence_level_out_of_range(self):
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            AnalyticsParameterValidator.validate_confidence_level(1.5)

    def test_validate_anomaly_sensitivity_valid(self):
        assert AnalyticsParameterValidator.validate_anomaly_sensitivity(0.8) == 0.8

    def test_validate_anomaly_sensitivity_out_of_range(self):
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            AnalyticsParameterValidator.validate_anomaly_sensitivity(-0.1)

    def test_validate_email_list_valid(self):
        emails = ["test@example.com", "admin@corp.io"]
        assert AnalyticsParameterValidator.validate_email_list(emails) == emails

    def test_validate_email_list_invalid(self):
        with pytest.raises(ValueError, match="Invalid email"):
            AnalyticsParameterValidator.validate_email_list(["not_an_email"])

    def test_validate_currency_code_valid(self):
        assert AnalyticsParameterValidator.validate_currency_code("USD") == "USD"

    def test_validate_currency_code_invalid_length(self):
        with pytest.raises(ValueError, match="3-letter"):
            AnalyticsParameterValidator.validate_currency_code("US")

    def test_validate_currency_code_lowercase(self):
        with pytest.raises(ValueError, match="uppercase"):
            AnalyticsParameterValidator.validate_currency_code("usd")

    def test_validate_timezone_valid(self):
        assert AnalyticsParameterValidator.validate_timezone("UTC") == "UTC"

    def test_validate_timezone_too_short(self):
        with pytest.raises(ValueError, match="Invalid timezone"):
            AnalyticsParameterValidator.validate_timezone("UT")

    def test_validate_timezone_empty(self):
        with pytest.raises(ValueError, match="Invalid timezone"):
            AnalyticsParameterValidator.validate_timezone("")


class TestAnalyticsParameterBuilder:
    """Tests for AnalyticsParameterBuilder base class."""

    def test_initial_state_no_errors(self):
        builder = AnalyticsParameterBuilder()
        assert builder.has_errors() is False
        assert builder.get_validation_errors() == []

    def test_add_error(self):
        builder = AnalyticsParameterBuilder()
        builder._add_error("Test error")
        assert builder.has_errors() is True
        assert "Test error" in builder.get_validation_errors()

    def test_validate_and_raise_with_errors(self):
        builder = AnalyticsParameterBuilder()
        builder._add_error("Error 1")
        builder._add_error("Error 2")
        with pytest.raises(ValueError, match="Error 1"):
            builder._validate_and_raise()

    def test_validate_and_raise_no_errors(self):
        builder = AnalyticsParameterBuilder()
        # Should not raise
        builder._validate_and_raise()

    def test_get_validation_errors_returns_copy(self):
        builder = AnalyticsParameterBuilder()
        builder._add_error("err")
        errors = builder.get_validation_errors()
        errors.clear()
        assert builder.has_errors() is True
