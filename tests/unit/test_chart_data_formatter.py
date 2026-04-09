"""Unit tests for ChartDataFormatter.

Tests the behavioral correctness of:
- Chart formatting for cost trends, breakdowns, profitability, comparison, multi-series
- Agent-specific chart formatting (cost trends, performance metrics, task completion)
- Transaction cost distribution and provider performance charts
- Private data processing helpers (_process_time_series_data, _process_breakdown_data, etc.)
- Input validation and error handling across all format methods
- Group parameter aggregation (TOTAL, MEAN, MAXIMUM, MINIMUM, MEDIAN)
- Date formatting and range extraction
"""

import pytest
from datetime import datetime

from src.revenium_mcp_server.analytics.chart_data_formatter import (
    ChartDataFormatter,
    ChartType,
    ChartData,
    ColorScheme,
)
from src.revenium_mcp_server.common.error_handling import ToolError


# ─────────────────────────────────────────────────────────────────────────────
# ChartDataFormatter initialization
# ─────────────────────────────────────────────────────────────────────────────


class TestChartDataFormatterInit:
    """Verify formatter is usable after construction."""

    def test_formatter_has_all_color_schemes(self):
        formatter = ChartDataFormatter()
        for scheme in ColorScheme:
            assert scheme in formatter.color_schemes
            assert len(formatter.color_schemes[scheme]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# _process_time_series_data
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessTimeSeriesData:
    """Tests for time-series data processing helper."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def test_extracts_date_and_cost_from_items(self):
        data = [
            {"date": "2024-01-02", "cost": 200},
            {"date": "2024-01-01", "cost": 100},
        ]
        result = self.formatter._process_time_series_data(data)
        assert len(result) == 2
        # Should be sorted by date
        assert result[0]["cost"] == 100.0
        assert result[1]["cost"] == 200.0

    def test_uses_timestamp_field_as_fallback(self):
        data = [{"timestamp": "2024-06-15T10:00:00Z", "cost": 50}]
        result = self.formatter._process_time_series_data(data)
        assert len(result) == 1
        assert result[0]["cost"] == 50.0

    def test_missing_date_uses_index_label(self):
        data = [{"cost": 42}]
        result = self.formatter._process_time_series_data(data)
        assert result[0]["date"] == "Point 0"

    def test_invalid_cost_defaults_to_zero(self):
        data = [{"date": "2024-01-01", "cost": "not-a-number"}]
        result = self.formatter._process_time_series_data(data)
        assert result[0]["cost"] == 0.0

    def test_non_dict_item_raises(self):
        with pytest.raises(ToolError):
            self.formatter._process_time_series_data(["not-a-dict"])


# ─────────────────────────────────────────────────────────────────────────────
# _process_breakdown_data
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessBreakdownData:
    """Tests for breakdown data processing helper."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def test_extracts_category_and_value_by_type(self):
        data = [
            {"provider": "OpenAI", "cost": 500},
            {"provider": "Anthropic", "cost": 300},
        ]
        result = self.formatter._process_breakdown_data(data, "provider")
        assert len(result) == 2
        # Should be sorted by value descending
        assert result[0]["name"] == "OpenAI"
        assert result[0]["value"] == 500.0

    def test_model_breakdown_type(self):
        data = [{"model": "gpt-4", "cost": 100}]
        result = self.formatter._process_breakdown_data(data, "model")
        assert result[0]["name"] == "gpt-4"

    def test_customer_breakdown_uses_organization_field(self):
        data = [{"organization": "AcmeCorp", "cost": 750}]
        result = self.formatter._process_breakdown_data(data, "customer")
        assert result[0]["name"] == "AcmeCorp"

    def test_falls_back_to_name_field(self):
        data = [{"name": "Fallback", "value": 10}]
        result = self.formatter._process_breakdown_data(data, "provider")
        assert result[0]["name"] == "Fallback"
        assert result[0]["value"] == 10.0

    def test_invalid_value_defaults_to_zero(self):
        data = [{"provider": "X", "cost": "bad"}]
        result = self.formatter._process_breakdown_data(data, "provider")
        assert result[0]["value"] == 0.0

    def test_non_dict_item_raises(self):
        with pytest.raises(ToolError):
            self.formatter._process_breakdown_data([42], "provider")


# ─────────────────────────────────────────────────────────────────────────────
# _process_profitability_data
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessProfitabilityData:
    """Tests for profitability data processing."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def test_calculates_profit_and_margin(self):
        data = [{"customer": "A", "revenue": 1000, "cost": 400}]
        result = self.formatter._process_profitability_data(data, "customer")
        assert result[0]["profit"] == 600.0
        assert result[0]["profit_margin"] == pytest.approx(60.0)

    def test_zero_revenue_gives_zero_margin(self):
        data = [{"customer": "B", "revenue": 0, "cost": 100}]
        result = self.formatter._process_profitability_data(data, "customer")
        assert result[0]["profit_margin"] == 0.0

    def test_sorted_by_revenue_descending(self):
        data = [
            {"customer": "Low", "revenue": 100, "cost": 50},
            {"customer": "High", "revenue": 500, "cost": 100},
        ]
        result = self.formatter._process_profitability_data(data, "customer")
        assert result[0]["entity"] == "High"


# ─────────────────────────────────────────────────────────────────────────────
# _process_comparison_data
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessComparisonData:
    """Tests for comparison data processing."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def test_labels_current_and_previous_periods(self):
        current = [{"category": "OpenAI", "value": 100}]
        previous = [{"category": "OpenAI", "value": 80}]
        result = self.formatter._process_comparison_data(current, previous)
        periods = {item["period"] for item in result}
        assert periods == {"Current", "Previous"}
        assert len(result) == 2

    def test_empty_previous_data(self):
        current = [{"category": "X", "value": 50}]
        result = self.formatter._process_comparison_data(current, [])
        assert len(result) == 1
        assert result[0]["period"] == "Current"


# ─────────────────────────────────────────────────────────────────────────────
# _process_multi_series_data
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessMultiSeriesData:
    """Tests for multi-series data processing."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def test_flattens_series_with_labels(self):
        data = {
            "Series A": [{"x": 1, "y": 10}, {"x": 2, "y": 20}],
            "Series B": [{"x": 1, "y": 5}],
        }
        result = self.formatter._process_multi_series_data(data)
        assert len(result) == 3
        series_names = {item["series"] for item in result}
        assert series_names == {"Series A", "Series B"}


# ─────────────────────────────────────────────────────────────────────────────
# _format_date
# ─────────────────────────────────────────────────────────────────────────────


class TestFormatDate:
    """Tests for date formatting helper."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def test_iso_datetime_extracts_date(self):
        result = self.formatter._format_date("2024-01-15T12:30:00Z")
        assert result == "2024-01-15"

    def test_date_string_preserved(self):
        result = self.formatter._format_date("2024-03-20")
        assert result == "2024-03-20"

    def test_datetime_object_formatted(self):
        dt = datetime(2024, 7, 4, 10, 0, 0)
        result = self.formatter._format_date(dt)
        assert result == "2024-07-04"

    def test_non_date_string_returned_as_is(self):
        result = self.formatter._format_date("Q1 2024")
        assert result == "Q1 2024"

    def test_numeric_value_converted_to_string(self):
        result = self.formatter._format_date(12345)
        assert result == "12345"


# ─────────────────────────────────────────────────────────────────────────────
# _get_date_range
# ─────────────────────────────────────────────────────────────────────────────


class TestGetDateRange:
    """Tests for date range extraction."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def test_returns_start_and_end(self):
        data = [{"date": "2024-01-01"}, {"date": "2024-01-31"}, {"date": "2024-01-15"}]
        result = self.formatter._get_date_range(data)
        assert result == {"start": "2024-01-01", "end": "2024-01-31"}

    def test_empty_data_returns_na(self):
        result = self.formatter._get_date_range([])
        assert result == {"start": "N/A", "end": "N/A"}

    def test_no_date_fields_returns_na(self):
        result = self.formatter._get_date_range([{"cost": 100}])
        assert result == {"start": "N/A", "end": "N/A"}


# ─────────────────────────────────────────────────────────────────────────────
# format_cost_trend_chart (public API)
# ─────────────────────────────────────────────────────────────────────────────


class TestFormatCostTrendChart:
    """Tests for cost trend chart formatting."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def test_valid_data_produces_line_chart(self):
        data = [
            {"date": "2024-01-01", "cost": 100},
            {"date": "2024-01-02", "cost": 200},
        ]
        result = self.formatter.format_cost_trend_chart(data)
        assert isinstance(result, ChartData)
        assert result.config.chart_type == ChartType.LINE
        assert result.metadata["data_points"] == 2
        assert result.metadata["total_cost"] == 300.0

    def test_empty_data_returns_no_data_chart(self):
        result = self.formatter.format_cost_trend_chart([])
        assert isinstance(result, ChartData)
        assert result.metadata["status"] == "no_data_available"
        assert result.data == []

    def test_non_list_data_raises_validation_error(self):
        with pytest.raises(ToolError):
            self.formatter.format_cost_trend_chart("not a list")

    def test_non_string_title_raises_validation_error(self):
        data = [{"date": "2024-01-01", "cost": 100}]
        with pytest.raises(ToolError):
            self.formatter.format_cost_trend_chart(data, title=12345)


# ─────────────────────────────────────────────────────────────────────────────
# format_cost_breakdown_chart
# ─────────────────────────────────────────────────────────────────────────────


class TestFormatCostBreakdownChart:
    """Tests for cost breakdown chart formatting."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def test_small_dataset_uses_pie_chart(self):
        data = [
            {"provider": "OpenAI", "cost": 500},
            {"provider": "Anthropic", "cost": 300},
        ]
        result = self.formatter.format_cost_breakdown_chart(data, "provider")
        assert result.config.chart_type == ChartType.PIE

    def test_large_dataset_uses_bar_chart(self):
        data = [{"provider": f"Provider{i}", "cost": i * 10} for i in range(10)]
        result = self.formatter.format_cost_breakdown_chart(data, "provider")
        assert result.config.chart_type == ChartType.BAR

    def test_empty_data_returns_no_data_chart(self):
        result = self.formatter.format_cost_breakdown_chart([], "provider")
        assert result.metadata["status"] == "no_data_available"

    def test_auto_generated_title(self):
        data = [{"provider": "X", "cost": 10}]
        result = self.formatter.format_cost_breakdown_chart(data, "provider")
        assert "Provider" in result.config.title

    def test_non_list_data_raises(self):
        with pytest.raises(ToolError):
            self.formatter.format_cost_breakdown_chart({"bad": "data"}, "provider")

    def test_empty_breakdown_type_raises(self):
        with pytest.raises(ToolError):
            self.formatter.format_cost_breakdown_chart([{"cost": 10}], "")


# ─────────────────────────────────────────────────────────────────────────────
# format_profitability_chart
# ─────────────────────────────────────────────────────────────────────────────


class TestFormatProfitabilityChart:
    """Tests for profitability chart formatting."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def test_produces_dual_axis_chart(self):
        data = [{"customer": "A", "revenue": 1000, "cost": 400}]
        result = self.formatter.format_profitability_chart(data, "customer")
        assert result.config.chart_type == ChartType.DUAL_AXIS
        assert result.metadata["entity_type"] == "customer"

    def test_auto_title_uses_entity_type(self):
        data = [{"product": "X", "revenue": 500, "cost": 200}]
        result = self.formatter.format_profitability_chart(data, "product")
        assert "Product" in result.config.title


# ─────────────────────────────────────────────────────────────────────────────
# format_comparison_chart
# ─────────────────────────────────────────────────────────────────────────────


class TestFormatComparisonChart:
    """Tests for comparison chart formatting."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def test_produces_stacked_bar_chart(self):
        current = [{"category": "A", "value": 100}]
        previous = [{"category": "A", "value": 80}]
        result = self.formatter.format_comparison_chart(current, previous, "monthly")
        assert result.config.chart_type == ChartType.STACKED_BAR
        assert result.metadata["periods"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# format_multi_series_chart
# ─────────────────────────────────────────────────────────────────────────────


class TestFormatMultiSeriesChart:
    """Tests for multi-series chart formatting."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def test_produces_chart_with_series_metadata(self):
        data = {"Revenue": [{"x": 1, "y": 100}], "Cost": [{"x": 1, "y": 50}]}
        result = self.formatter.format_multi_series_chart(data, "Metrics")
        assert result.metadata["series_count"] == 2
        assert set(result.metadata["series_names"]) == {"Revenue", "Cost"}


# ─────────────────────────────────────────────────────────────────────────────
# Agent chart methods
# ─────────────────────────────────────────────────────────────────────────────


class TestAgentChartMethods:
    """Tests for agent-specific chart formatting methods."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def test_agent_cost_trends_with_data(self):
        data = [
            {"date": "2024-01-01", "agent": "agent-1", "cost": 50},
            {"date": "2024-01-02", "agent": "agent-2", "cost": 75},
        ]
        result = self.formatter.format_agent_cost_trends_chart(data)
        assert result.config.chart_type == ChartType.LINE
        assert result.metadata["chart_type"] == "agent_cost_trends"
        assert result.metadata["data_points"] == 2

    def test_agent_cost_trends_empty_data(self):
        result = self.formatter.format_agent_cost_trends_chart([])
        assert result.metadata["status"] == "no_data_available"
        assert result.data == []

    def test_agent_cost_trends_non_list_raises(self):
        with pytest.raises(ToolError):
            self.formatter.format_agent_cost_trends_chart("bad")

    def test_agent_performance_metrics_chart(self):
        data = [{"agent": "a1", "response_time": 100, "throughput": 50}]
        result = self.formatter.format_agent_performance_metrics_chart(data)
        assert result.config.chart_type == ChartType.SCATTER
        assert result.metadata["agents"] == 1

    def test_agent_performance_empty_raises(self):
        with pytest.raises(ToolError):
            self.formatter.format_agent_performance_metrics_chart([])

    def test_agent_performance_non_list_raises(self):
        with pytest.raises(ToolError):
            self.formatter.format_agent_performance_metrics_chart("bad")

    def test_task_completion_chart(self):
        data = [{"date": "2024-01-01", "completed_tasks": 100, "success_rate": 95.5}]
        result = self.formatter.format_task_completion_analysis_chart(data)
        assert result.config.chart_type == ChartType.AREA
        assert result.metadata["total_completed_tasks"] == 100

    def test_task_completion_empty_raises(self):
        with pytest.raises(ToolError):
            self.formatter.format_task_completion_analysis_chart([])

    def test_task_completion_non_list_raises(self):
        with pytest.raises(ToolError):
            self.formatter.format_task_completion_analysis_chart("bad")


# ─────────────────────────────────────────────────────────────────────────────
# _process_agent_time_series_data
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessAgentTimeSeriesData:
    """Tests for agent time series data processing."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def test_extracts_agent_and_cost(self):
        data = [{"date": "2024-01-01", "agent": "bot-1", "cost": 25}]
        result = self.formatter._process_agent_time_series_data(data)
        assert result[0]["agent"] == "bot-1"
        assert result[0]["cost"] == 25.0

    def test_missing_agent_uses_fallback(self):
        data = [{"date": "2024-01-01", "cost": 10}]
        result = self.formatter._process_agent_time_series_data(data)
        assert result[0]["agent"] == "Agent 0"

    def test_invalid_cost_defaults_to_zero(self):
        data = [{"date": "2024-01-01", "agent": "x", "cost": "bad"}]
        result = self.formatter._process_agent_time_series_data(data)
        assert result[0]["cost"] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# _process_agent_performance_data
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessAgentPerformanceData:
    """Tests for agent performance data processing."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def test_calculates_efficiency_score(self):
        data = [{"agent": "a1", "response_time": 100, "throughput": 500}]
        result = self.formatter._process_agent_performance_data(data)
        assert result[0]["efficiency_score"] == 5.0

    def test_zero_response_time_uses_throughput(self):
        data = [{"agent": "a1", "response_time": 0, "throughput": 10}]
        result = self.formatter._process_agent_performance_data(data)
        assert result[0]["efficiency_score"] == 10.0

    def test_fallback_field_names(self):
        data = [{"agent_id": "x", "duration": 50, "requests_per_minute": 100}]
        result = self.formatter._process_agent_performance_data(data)
        assert result[0]["agent"] == "x"
        assert result[0]["response_time"] == 50.0
        assert result[0]["throughput"] == 100.0


# ─────────────────────────────────────────────────────────────────────────────
# _process_task_completion_data
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessTaskCompletionData:
    """Tests for task completion data processing."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def test_extracts_tasks_and_rate(self):
        data = [{"date": "2024-01-01", "completed_tasks": 50, "success_rate": 90.0}]
        result = self.formatter._process_task_completion_data(data)
        assert result[0]["completed_tasks"] == 50
        assert result[0]["success_rate"] == 90.0

    def test_fallback_field_names(self):
        data = [{"timestamp": "2024-01-01", "tasks_completed": 10, "completion_rate": 80}]
        result = self.formatter._process_task_completion_data(data)
        assert result[0]["completed_tasks"] == 10
        assert result[0]["success_rate"] == 80.0


# ─────────────────────────────────────────────────────────────────────────────
# _process_cost_distribution_data
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessCostDistributionData:
    """Tests for cost distribution data processing."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def test_extracts_range_and_frequency(self):
        data = [{"cost_range": "$0-$10", "frequency": 42, "percentage": 15.5}]
        result = self.formatter._process_cost_distribution_data(data)
        assert result[0]["cost_range"] == "$0-$10"
        assert result[0]["frequency"] == 42
        assert result[0]["percentage"] == 15.5

    def test_fallback_field_names(self):
        data = [{"range": "Low", "count": 5}]
        result = self.formatter._process_cost_distribution_data(data)
        assert result[0]["cost_range"] == "Low"
        assert result[0]["frequency"] == 5


# ─────────────────────────────────────────────────────────────────────────────
# _process_provider_performance_data
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessProviderPerformanceData:
    """Tests for provider performance data processing."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def test_calculates_efficiency_ratio(self):
        data = [{"provider": "OpenAI", "avg_duration": 100, "task_count": 500}]
        result = self.formatter._process_provider_performance_data(data)
        assert result[0]["efficiency_ratio"] == 5.0

    def test_zero_duration_uses_task_count(self):
        data = [{"provider": "X", "avg_duration": 0, "task_count": 10}]
        result = self.formatter._process_provider_performance_data(data)
        assert result[0]["efficiency_ratio"] == 10


# ─────────────────────────────────────────────────────────────────────────────
# _process_model_efficiency_data
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessModelEfficiencyData:
    """Tests for model efficiency data processing."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def test_categorizes_high_efficiency(self):
        data = [{"model": "gpt-4", "efficiency_score": 85, "cost_per_task": 0.05}]
        result = self.formatter._process_model_efficiency_data(data)
        assert result[0]["efficiency_category"] == "High Efficiency"

    def test_categorizes_medium_efficiency(self):
        data = [{"model": "x", "efficiency_score": 70, "cost_per_task": 0.1}]
        result = self.formatter._process_model_efficiency_data(data)
        assert result[0]["efficiency_category"] == "Medium Efficiency"

    def test_categorizes_low_efficiency(self):
        data = [{"model": "x", "efficiency_score": 40, "cost_per_task": 0.5}]
        result = self.formatter._process_model_efficiency_data(data)
        assert result[0]["efficiency_category"] == "Low Efficiency"


# ─────────────────────────────────────────────────────────────────────────────
# _process_group_parameter_data
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessGroupParameterData:
    """Tests for group parameter aggregation logic."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def _make_data(self):
        return [
            {"category": "A", "value": 10},
            {"category": "A", "value": 20},
            {"category": "A", "value": 30},
            {"category": "B", "value": 5},
        ]

    def test_total_aggregation(self):
        result = self.formatter._process_group_parameter_data(self._make_data(), "TOTAL", "cost")
        a_item = next(r for r in result if r["category"] == "A")
        assert a_item["value"] == 60.0

    def test_mean_aggregation(self):
        result = self.formatter._process_group_parameter_data(self._make_data(), "MEAN", "cost")
        a_item = next(r for r in result if r["category"] == "A")
        assert a_item["value"] == pytest.approx(20.0)

    def test_maximum_aggregation(self):
        result = self.formatter._process_group_parameter_data(self._make_data(), "MAXIMUM", "cost")
        a_item = next(r for r in result if r["category"] == "A")
        assert a_item["value"] == 30.0

    def test_minimum_aggregation(self):
        result = self.formatter._process_group_parameter_data(self._make_data(), "MINIMUM", "cost")
        a_item = next(r for r in result if r["category"] == "A")
        assert a_item["value"] == 10.0

    def test_median_aggregation_odd(self):
        result = self.formatter._process_group_parameter_data(self._make_data(), "MEDIAN", "cost")
        a_item = next(r for r in result if r["category"] == "A")
        assert a_item["value"] == 20.0  # Median of [10, 20, 30]

    def test_median_aggregation_even(self):
        data = [
            {"category": "A", "value": 10},
            {"category": "A", "value": 20},
        ]
        result = self.formatter._process_group_parameter_data(data, "MEDIAN", "cost")
        a_item = next(r for r in result if r["category"] == "A")
        assert a_item["value"] == 15.0  # Median of [10, 20]

    def test_unknown_group_defaults_to_total(self):
        result = self.formatter._process_group_parameter_data(self._make_data(), "UNKNOWN", "cost")
        a_item = next(r for r in result if r["category"] == "A")
        assert a_item["value"] == 60.0


# ─────────────────────────────────────────────────────────────────────────────
# format_group_parameter_chart (public API)
# ─────────────────────────────────────────────────────────────────────────────


class TestFormatGroupParameterChart:
    """Tests for group parameter chart formatting."""

    def setup_method(self):
        self.formatter = ChartDataFormatter()

    def test_maximum_uses_bar_chart(self):
        data = [{"category": "A", "value": 10}]
        result = self.formatter.format_group_parameter_chart(data, "MAXIMUM")
        assert result.config.chart_type == ChartType.BAR

    def test_total_uses_line_chart(self):
        data = [{"category": "A", "value": 10}]
        result = self.formatter.format_group_parameter_chart(data, "TOTAL")
        assert result.config.chart_type == ChartType.LINE

    def test_auto_title_includes_group(self):
        data = [{"category": "A", "value": 10}]
        result = self.formatter.format_group_parameter_chart(data, "MEAN", metric_type="cost")
        assert "MEAN" in result.config.title
