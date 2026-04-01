"""Extended unit tests for ChartDataFormatter — M3 coverage pass.

Targets missed lines in:
  src/revenium_mcp_server/analytics/chart_data_formatter.py

Focused areas:
- format_cost_trend_chart: non-list input, non-string title, normal success path
- format_cost_breakdown_chart: non-list input, empty list, invalid breakdown_type,
  large dataset (> 8 items uses BAR), normal paths
- format_profitability_chart: normal path including profit/margin math
- format_comparison_chart: normal path, custom title
- format_multi_series_chart: normal path with multiple series
- format_agent_cost_trends_chart: non-list input, empty list, normal path
- format_agent_performance_metrics_chart: non-list, empty, normal path
- format_task_completion_analysis_chart: non-list, empty, normal path
- format_transaction_cost_distribution_chart: non-list, empty, normal path
- format_provider_task_performance_chart: non-list, empty, normal path
- format_model_task_efficiency_chart: non-list, empty, normal path
- format_comparative_analysis_chart: normal path
- format_group_parameter_chart: all group parameter types (TOTAL, MEAN, MAXIMUM, MINIMUM, MEDIAN, default)
- _process_time_series_data: non-list raises, non-dict item raises
- _process_breakdown_data: non-list raises, non-dict item raises
- _process_profitability_data: zero-revenue profit margin
- _process_comparison_data: current and previous period data
- _process_multi_series_data: multi-series formatting
- _process_agent_time_series_data: fallback for missing date/agent, invalid cost
- _process_agent_performance_data: fallback values, efficiency_score computation
- _process_task_completion_data: fallback fields, invalid value handling
- _process_cost_distribution_data: range/count fallbacks, invalid values
- _process_provider_performance_data: fallback fields, invalid values
- _process_model_efficiency_data: efficiency categories (high/medium/low), invalid values
- _format_date: ISO datetime string, date-only string, non-ISO string, datetime object, other types
- _get_date_range: empty list, list without date keys
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from src.revenium_mcp_server.analytics.chart_data_formatter import (
    ChartData,
    ChartDataFormatter,
    ChartType,
    ColorScheme,
)
from src.revenium_mcp_server.common.error_handling import ToolError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_formatter() -> ChartDataFormatter:
    return ChartDataFormatter()


# ---------------------------------------------------------------------------
# format_cost_trend_chart
# ---------------------------------------------------------------------------


class TestFormatCostTrendChartM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_non_list_raises_tool_error(self):
        with pytest.raises(ToolError) as exc_info:
            self.f.format_cost_trend_chart("not-a-list")
        assert "list" in str(exc_info.value).lower()

    def test_non_string_title_raises_tool_error(self):
        data = [{"date": "2024-01-01", "cost": 50.0}]
        with pytest.raises(ToolError):
            self.f.format_cost_trend_chart(data, title=123)

    def test_empty_data_returns_no_data_chart(self):
        result = self.f.format_cost_trend_chart([])
        assert isinstance(result, ChartData)
        assert result.metadata["status"] == "no_data_available"
        assert result.metadata["data_points"] == 0
        assert result.data == []

    def test_empty_data_export_options_not_downloadable(self):
        result = self.f.format_cost_trend_chart([])
        assert result.export_options["downloadable"] is False

    def test_valid_data_returns_chart_data(self):
        data = [
            {"date": "2024-01-01", "cost": 100.0},
            {"date": "2024-01-02", "cost": 200.0},
        ]
        result = self.f.format_cost_trend_chart(data, title="Test Cost Trend")
        assert isinstance(result, ChartData)
        assert result.config.title == "Test Cost Trend"
        assert result.config.chart_type == ChartType.LINE
        assert result.metadata["chart_type"] == "cost_trend"
        assert result.metadata["total_cost"] == 300.0
        assert len(result.data) == 2

    def test_valid_data_config_uses_cost_analysis_scheme(self):
        data = [{"date": "2024-01-01", "cost": 10.0}]
        result = self.f.format_cost_trend_chart(data)
        assert result.config.color_scheme == ColorScheme.COST_ANALYSIS
        assert result.config.smooth is True

    def test_valid_data_downloadable_export(self):
        data = [{"date": "2024-01-01", "cost": 10.0}]
        result = self.f.format_cost_trend_chart(data)
        assert result.export_options["downloadable"] is True

    def test_date_range_in_metadata(self):
        data = [
            {"date": "2024-01-01", "cost": 10.0},
            {"date": "2024-01-03", "cost": 30.0},
        ]
        result = self.f.format_cost_trend_chart(data)
        assert result.metadata["date_range"]["start"] == "2024-01-01"
        assert result.metadata["date_range"]["end"] == "2024-01-03"


# ---------------------------------------------------------------------------
# format_cost_breakdown_chart
# ---------------------------------------------------------------------------


class TestFormatCostBreakdownChartM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_non_list_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f.format_cost_breakdown_chart({"not": "a list"}, "provider")

    def test_empty_list_returns_no_data_chart(self):
        result = self.f.format_cost_breakdown_chart([], "provider")
        assert isinstance(result, ChartData)
        assert result.metadata["status"] == "no_data_available"
        assert result.data == []

    def test_empty_breakdown_type_raises(self):
        data = [{"provider": "OpenAI", "cost": 100.0}]
        with pytest.raises(ToolError):
            self.f.format_cost_breakdown_chart(data, "   ")

    def test_non_string_breakdown_type_raises(self):
        data = [{"provider": "OpenAI", "cost": 100.0}]
        with pytest.raises(ToolError):
            self.f.format_cost_breakdown_chart(data, 42)

    def test_small_dataset_uses_pie_chart(self):
        data = [{"provider": f"P{i}", "cost": float(i * 10)} for i in range(1, 5)]
        result = self.f.format_cost_breakdown_chart(data, "provider")
        assert result.config.chart_type == ChartType.PIE

    def test_large_dataset_uses_bar_chart(self):
        # More than 8 items forces BAR
        data = [{"provider": f"Provider{i}", "cost": float(i * 10)} for i in range(1, 12)]
        result = self.f.format_cost_breakdown_chart(data, "provider")
        assert result.config.chart_type == ChartType.BAR

    def test_auto_generated_title(self):
        data = [{"model": "gpt-4", "cost": 50.0}]
        result = self.f.format_cost_breakdown_chart(data, "model")
        assert "Model" in result.config.title

    def test_custom_title_used(self):
        data = [{"provider": "OpenAI", "cost": 100.0}]
        result = self.f.format_cost_breakdown_chart(data, "provider", title="My Title")
        assert result.config.title == "My Title"

    def test_metadata_breakdown_type_set(self):
        data = [{"provider": "OpenAI", "cost": 100.0}]
        result = self.f.format_cost_breakdown_chart(data, "provider")
        assert result.metadata["breakdown_type"] == "provider"

    def test_metadata_total_value_calculated(self):
        data = [
            {"provider": "OpenAI", "cost": 100.0},
            {"provider": "Anthropic", "cost": 200.0},
        ]
        result = self.f.format_cost_breakdown_chart(data, "provider")
        assert result.metadata["total_value"] == pytest.approx(300.0)


# ---------------------------------------------------------------------------
# format_profitability_chart
# ---------------------------------------------------------------------------


class TestFormatProfitabilityChartM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_returns_chart_data(self):
        data = [
            {"product": "Product A", "revenue": 1000.0, "cost": 400.0},
            {"product": "Product B", "revenue": 500.0, "cost": 300.0},
        ]
        result = self.f.format_profitability_chart(data, "product")
        assert isinstance(result, ChartData)
        assert result.config.chart_type == ChartType.DUAL_AXIS

    def test_auto_title_generation(self):
        data = [{"customer": "Acme", "revenue": 1000.0, "cost": 200.0}]
        result = self.f.format_profitability_chart(data, "customer")
        assert "Customer" in result.config.title
        assert "Profitability" in result.config.title

    def test_custom_title(self):
        data = [{"product": "A", "revenue": 100.0, "cost": 50.0}]
        result = self.f.format_profitability_chart(data, "product", title="Custom")
        assert result.config.title == "Custom"

    def test_metadata_totals(self):
        data = [
            {"product": "A", "revenue": 1000.0, "cost": 400.0},
            {"product": "B", "revenue": 500.0, "cost": 300.0},
        ]
        result = self.f.format_profitability_chart(data, "product")
        assert result.metadata["total_revenue"] == pytest.approx(1500.0)
        assert result.metadata["total_cost"] == pytest.approx(700.0)

    def test_profit_margin_computed_in_data(self):
        data = [{"product": "A", "revenue": 1000.0, "cost": 400.0}]
        result = self.f.format_profitability_chart(data, "product")
        item = result.data[0]
        assert item["profit"] == pytest.approx(600.0)
        assert item["profit_margin"] == pytest.approx(60.0)

    def test_zero_revenue_produces_zero_margin(self):
        data = [{"product": "A", "revenue": 0.0, "cost": 100.0}]
        result = self.f.format_profitability_chart(data, "product")
        item = result.data[0]
        assert item["profit_margin"] == 0.0

    def test_export_options_include_interactive_features(self):
        data = [{"product": "A", "revenue": 100.0, "cost": 50.0}]
        result = self.f.format_profitability_chart(data, "product")
        assert "zoom" in result.export_options["interactive_features"]
        assert "dual_axis_toggle" in result.export_options["interactive_features"]


# ---------------------------------------------------------------------------
# format_comparison_chart
# ---------------------------------------------------------------------------


class TestFormatComparisonChartM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_returns_chart_data(self):
        current = [{"category": "Jan", "value": 100.0}]
        previous = [{"category": "Jan", "value": 80.0}]
        result = self.f.format_comparison_chart(current, previous, "monthly")
        assert isinstance(result, ChartData)
        assert result.config.chart_type == ChartType.STACKED_BAR

    def test_auto_title_generation(self):
        current = [{"category": "Q1", "value": 200.0}]
        previous = [{"category": "Q1", "value": 150.0}]
        result = self.f.format_comparison_chart(current, previous, "quarterly")
        assert "Quarterly" in result.config.title

    def test_custom_title(self):
        result = self.f.format_comparison_chart([], [], "monthly", title="My Compare")
        assert result.config.title == "My Compare"

    def test_data_includes_both_periods(self):
        current = [{"category": "A", "value": 10.0}]
        previous = [{"category": "A", "value": 5.0}]
        result = self.f.format_comparison_chart(current, previous, "monthly")
        periods = {item["period"] for item in result.data}
        assert "Current" in periods
        assert "Previous" in periods

    def test_metadata_periods_is_two(self):
        result = self.f.format_comparison_chart(
            [{"category": "A", "value": 10.0}],
            [{"category": "A", "value": 5.0}],
            "monthly"
        )
        assert result.metadata["periods"] == 2

    def test_color_field_is_period(self):
        result = self.f.format_comparison_chart([], [], "monthly")
        assert result.config.color_field == "period"


# ---------------------------------------------------------------------------
# format_multi_series_chart
# ---------------------------------------------------------------------------


class TestFormatMultiSeriesChartM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_returns_chart_data(self):
        data = {
            "series_a": [{"x": "Jan", "y": 10.0}, {"x": "Feb", "y": 20.0}],
            "series_b": [{"x": "Jan", "y": 15.0}],
        }
        result = self.f.format_multi_series_chart(data, "Multi Series Test")
        assert isinstance(result, ChartData)
        assert result.config.title == "Multi Series Test"

    def test_series_count_in_metadata(self):
        data = {
            "a": [{"x": "Jan", "y": 1.0}],
            "b": [{"x": "Jan", "y": 2.0}],
            "c": [{"x": "Jan", "y": 3.0}],
        }
        result = self.f.format_multi_series_chart(data, "Test")
        assert result.metadata["series_count"] == 3

    def test_total_points_in_metadata(self):
        data = {
            "a": [{"x": "Jan", "y": 1.0}, {"x": "Feb", "y": 2.0}],
            "b": [{"x": "Jan", "y": 3.0}],
        }
        result = self.f.format_multi_series_chart(data, "Test")
        assert result.metadata["total_points"] == 3

    def test_series_names_in_metadata(self):
        data = {"revenue": [{"x": "Jan", "y": 100}], "cost": [{"x": "Jan", "y": 50}]}
        result = self.f.format_multi_series_chart(data, "Test")
        assert "revenue" in result.metadata["series_names"]
        assert "cost" in result.metadata["series_names"]

    def test_bar_chart_type_override(self):
        data = {"series_a": [{"x": "Jan", "y": 10}]}
        result = self.f.format_multi_series_chart(data, "Test", chart_type=ChartType.BAR)
        assert result.config.chart_type == ChartType.BAR

    def test_data_has_series_field(self):
        data = {"my_series": [{"x": "Jan", "y": 5.0}]}
        result = self.f.format_multi_series_chart(data, "Test")
        assert result.data[0]["series"] == "my_series"


# ---------------------------------------------------------------------------
# format_agent_cost_trends_chart
# ---------------------------------------------------------------------------


class TestFormatAgentCostTrendsChartM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_non_list_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f.format_agent_cost_trends_chart("not-a-list")

    def test_empty_list_returns_no_data_chart(self):
        result = self.f.format_agent_cost_trends_chart([])
        assert isinstance(result, ChartData)
        assert result.metadata["status"] == "no_data_available"
        assert result.data == []

    def test_empty_list_export_not_downloadable(self):
        result = self.f.format_agent_cost_trends_chart([])
        assert result.export_options["downloadable"] is False

    def test_valid_data_returns_chart_data(self):
        data = [
            {"date": "2024-01-01", "agent": "agent-1", "cost": 100.0},
            {"date": "2024-01-02", "agent": "agent-2", "cost": 200.0},
        ]
        result = self.f.format_agent_cost_trends_chart(data)
        assert isinstance(result, ChartData)
        assert result.config.chart_type == ChartType.LINE
        assert result.config.color_field == "agent"

    def test_metadata_agents_count(self):
        data = [
            {"date": "2024-01-01", "agent": "a1", "cost": 10.0},
            {"date": "2024-01-02", "agent": "a2", "cost": 20.0},
            {"date": "2024-01-03", "agent": "a1", "cost": 15.0},
        ]
        result = self.f.format_agent_cost_trends_chart(data)
        assert result.metadata["agents"] == 2

    def test_metadata_total_cost(self):
        data = [
            {"date": "2024-01-01", "agent": "a1", "cost": 50.0},
            {"date": "2024-01-02", "agent": "a1", "cost": 75.0},
        ]
        result = self.f.format_agent_cost_trends_chart(data)
        assert result.metadata["total_cost"] == pytest.approx(125.0)

    def test_interactive_features_present(self):
        data = [{"date": "2024-01-01", "agent": "a1", "cost": 10.0}]
        result = self.f.format_agent_cost_trends_chart(data)
        assert "agent_toggle" in result.export_options["interactive_features"]


# ---------------------------------------------------------------------------
# format_agent_performance_metrics_chart
# ---------------------------------------------------------------------------


class TestFormatAgentPerformanceMetricsChartM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_non_list_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f.format_agent_performance_metrics_chart({"agent": "a1"})

    def test_empty_list_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f.format_agent_performance_metrics_chart([])

    def test_valid_data_returns_scatter_chart(self):
        data = [
            {"agent": "a1", "response_time": 150.0, "throughput": 30.0},
            {"agent": "a2", "response_time": 200.0, "throughput": 25.0},
        ]
        result = self.f.format_agent_performance_metrics_chart(data)
        assert isinstance(result, ChartData)
        assert result.config.chart_type == ChartType.SCATTER

    def test_metadata_agent_count(self):
        data = [
            {"agent": "a1", "response_time": 100.0, "throughput": 50.0},
            {"agent": "a2", "response_time": 120.0, "throughput": 40.0},
        ]
        result = self.f.format_agent_performance_metrics_chart(data)
        assert result.metadata["agents"] == 2

    def test_metadata_avg_response_time(self):
        data = [
            {"agent": "a1", "response_time": 100.0, "throughput": 10.0},
            {"agent": "a2", "response_time": 200.0, "throughput": 20.0},
        ]
        result = self.f.format_agent_performance_metrics_chart(data)
        assert result.metadata["avg_response_time"] == pytest.approx(150.0)

    def test_metadata_avg_throughput(self):
        data = [
            {"agent": "a1", "response_time": 100.0, "throughput": 10.0},
            {"agent": "a2", "response_time": 200.0, "throughput": 30.0},
        ]
        result = self.f.format_agent_performance_metrics_chart(data)
        assert result.metadata["avg_throughput"] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# format_task_completion_analysis_chart
# ---------------------------------------------------------------------------


class TestFormatTaskCompletionAnalysisChartM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_non_list_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f.format_task_completion_analysis_chart("bad input")

    def test_empty_list_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f.format_task_completion_analysis_chart([])

    def test_valid_data_returns_area_chart(self):
        data = [
            {"date": "2024-01-01", "completed_tasks": 100, "success_rate": 95.0},
            {"date": "2024-01-02", "completed_tasks": 120, "success_rate": 97.0},
        ]
        result = self.f.format_task_completion_analysis_chart(data)
        assert isinstance(result, ChartData)
        assert result.config.chart_type == ChartType.AREA

    def test_metadata_total_completed_tasks(self):
        data = [
            {"date": "2024-01-01", "completed_tasks": 100, "success_rate": 95.0},
            {"date": "2024-01-02", "completed_tasks": 200, "success_rate": 90.0},
        ]
        result = self.f.format_task_completion_analysis_chart(data)
        assert result.metadata["total_completed_tasks"] == 300

    def test_metadata_avg_success_rate(self):
        data = [
            {"date": "2024-01-01", "completed_tasks": 100, "success_rate": 80.0},
            {"date": "2024-01-02", "completed_tasks": 120, "success_rate": 100.0},
        ]
        result = self.f.format_task_completion_analysis_chart(data)
        assert result.metadata["avg_success_rate"] == pytest.approx(90.0)

    def test_interactive_features_present(self):
        data = [{"date": "2024-01-01", "completed_tasks": 50, "success_rate": 90.0}]
        result = self.f.format_task_completion_analysis_chart(data)
        assert "area_fill_toggle" in result.export_options["interactive_features"]


# ---------------------------------------------------------------------------
# format_transaction_cost_distribution_chart
# ---------------------------------------------------------------------------


class TestFormatTransactionCostDistributionChartM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_non_list_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f.format_transaction_cost_distribution_chart(999)

    def test_empty_list_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f.format_transaction_cost_distribution_chart([])

    def test_valid_data_returns_bar_chart(self):
        data = [
            {"cost_range": "$0-$1", "frequency": 100, "percentage": 25.0},
            {"cost_range": "$1-$5", "frequency": 200, "percentage": 50.0},
        ]
        result = self.f.format_transaction_cost_distribution_chart(data)
        assert isinstance(result, ChartData)
        assert result.config.chart_type == ChartType.BAR

    def test_metadata_total_transactions(self):
        data = [
            {"cost_range": "$0-$1", "frequency": 100},
            {"cost_range": "$1-$5", "frequency": 200},
        ]
        result = self.f.format_transaction_cost_distribution_chart(data)
        assert result.metadata["total_transactions"] == 300

    def test_metadata_cost_ranges_count(self):
        data = [
            {"cost_range": "$0-$1", "frequency": 100},
            {"cost_range": "$1-$5", "frequency": 200},
            {"cost_range": "$5-$10", "frequency": 50},
        ]
        result = self.f.format_transaction_cost_distribution_chart(data)
        assert result.metadata["cost_ranges"] == 3


# ---------------------------------------------------------------------------
# format_provider_task_performance_chart
# ---------------------------------------------------------------------------


class TestFormatProviderTaskPerformanceChartM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_non_list_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f.format_provider_task_performance_chart("bad")

    def test_empty_list_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f.format_provider_task_performance_chart([])

    def test_valid_data_returns_dual_axis_chart(self):
        data = [
            {"provider": "OpenAI", "avg_duration": 150.0, "task_count": 1000},
            {"provider": "Anthropic", "avg_duration": 200.0, "task_count": 800},
        ]
        result = self.f.format_provider_task_performance_chart(data)
        assert isinstance(result, ChartData)
        assert result.config.chart_type == ChartType.DUAL_AXIS

    def test_metadata_total_tasks(self):
        data = [
            {"provider": "OpenAI", "avg_duration": 100.0, "task_count": 500},
            {"provider": "Anthropic", "avg_duration": 120.0, "task_count": 300},
        ]
        result = self.f.format_provider_task_performance_chart(data)
        assert result.metadata["total_tasks"] == 800

    def test_metadata_providers_count(self):
        data = [
            {"provider": "OpenAI", "avg_duration": 100.0, "task_count": 500},
            {"provider": "Anthropic", "avg_duration": 120.0, "task_count": 300},
            {"provider": "Google", "avg_duration": 90.0, "task_count": 200},
        ]
        result = self.f.format_provider_task_performance_chart(data)
        assert result.metadata["providers"] == 3


# ---------------------------------------------------------------------------
# format_model_task_efficiency_chart
# ---------------------------------------------------------------------------


class TestFormatModelTaskEfficiencyChartM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_non_list_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f.format_model_task_efficiency_chart(None)

    def test_empty_list_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f.format_model_task_efficiency_chart([])

    def test_valid_data_returns_stacked_bar_chart(self):
        data = [
            {"model": "gpt-4", "efficiency_score": 85.0, "cost_per_task": 0.05},
            {"model": "claude-3", "efficiency_score": 70.0, "cost_per_task": 0.03},
        ]
        result = self.f.format_model_task_efficiency_chart(data)
        assert isinstance(result, ChartData)
        assert result.config.chart_type == ChartType.STACKED_BAR

    def test_metadata_avg_efficiency(self):
        data = [
            {"model": "gpt-4", "efficiency_score": 80.0, "cost_per_task": 0.05},
            {"model": "claude-3", "efficiency_score": 60.0, "cost_per_task": 0.03},
        ]
        result = self.f.format_model_task_efficiency_chart(data)
        assert result.metadata["avg_efficiency"] == pytest.approx(70.0)

    def test_metadata_avg_cost_per_task(self):
        data = [
            {"model": "gpt-4", "efficiency_score": 80.0, "cost_per_task": 0.06},
            {"model": "claude-3", "efficiency_score": 60.0, "cost_per_task": 0.04},
        ]
        result = self.f.format_model_task_efficiency_chart(data)
        assert result.metadata["avg_cost_per_task"] == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# format_comparative_analysis_chart
# ---------------------------------------------------------------------------


class TestFormatComparativeAnalysisChartM3:
    def setup_method(self):
        self.f = make_formatter()

    def _make_comparison_result(self, current=None, comparison=None, comparison_type="monthly"):
        result = MagicMock()
        result.metadata = {"comparison_type": comparison_type, "group": "TOTAL"}
        result.current_data = current or {"OpenAI": 100.0, "Anthropic": 200.0}
        result.comparison_data = comparison or {"OpenAI": 80.0, "Anthropic": 150.0}
        result.percentage_changes = []
        return result

    def test_returns_chart_data(self):
        comparison_result = self._make_comparison_result()
        result = self.f.format_comparative_analysis_chart(comparison_result)
        assert isinstance(result, ChartData)
        assert result.config.chart_type in (ChartType.STACKED_BAR, ChartType.LINE, ChartType.BAR)
        assert len(result.data) > 0

    def test_auto_title_from_metadata(self):
        comparison_result = self._make_comparison_result(comparison_type="quarterly")
        result = self.f.format_comparative_analysis_chart(comparison_result)
        assert "quarterly" in result.config.title.lower()

    def test_custom_title(self):
        comparison_result = self._make_comparison_result()
        result = self.f.format_comparative_analysis_chart(comparison_result, title="Custom Title")
        assert result.config.title == "Custom Title"

    def test_metadata_comparison_type_set(self):
        comparison_result = self._make_comparison_result(comparison_type="monthly")
        result = self.f.format_comparative_analysis_chart(comparison_result)
        assert result.metadata["comparison_type"] == "monthly"

    def test_data_includes_current_and_previous_periods(self):
        comparison_result = self._make_comparison_result(
            current={"A": 100.0},
            comparison={"A": 80.0}
        )
        result = self.f.format_comparative_analysis_chart(comparison_result)
        periods = {item["period"] for item in result.data}
        assert "Current" in periods
        assert "Previous" in periods

    def test_line_chart_uses_series_color_field(self):
        comparison_result = self._make_comparison_result()
        result = self.f.format_comparative_analysis_chart(
            comparison_result, chart_type=ChartType.LINE
        )
        assert result.config.color_field == "series"

    def test_stacked_bar_uses_period_color_field(self):
        comparison_result = self._make_comparison_result()
        result = self.f.format_comparative_analysis_chart(
            comparison_result, chart_type=ChartType.STACKED_BAR
        )
        assert result.config.color_field == "period"


# ---------------------------------------------------------------------------
# format_group_parameter_chart
# ---------------------------------------------------------------------------


class TestFormatGroupParameterChartM3:
    def setup_method(self):
        self.f = make_formatter()

    def _data(self, n=3):
        return [{"category": f"Cat{i}", "value": float(i * 10)} for i in range(1, n + 1)]

    def test_total_aggregation(self):
        data = [{"category": "A", "value": 10.0}, {"category": "A", "value": 20.0}]
        result = self.f.format_group_parameter_chart(data, "TOTAL")
        item = next(i for i in result.data if i["category"] == "A")
        assert item["value"] == pytest.approx(30.0)

    def test_mean_aggregation(self):
        data = [{"category": "A", "value": 10.0}, {"category": "A", "value": 30.0}]
        result = self.f.format_group_parameter_chart(data, "MEAN")
        item = next(i for i in result.data if i["category"] == "A")
        assert item["value"] == pytest.approx(20.0)

    def test_maximum_aggregation(self):
        data = [{"category": "A", "value": 10.0}, {"category": "A", "value": 30.0}]
        result = self.f.format_group_parameter_chart(data, "MAXIMUM")
        item = next(i for i in result.data if i["category"] == "A")
        assert item["value"] == pytest.approx(30.0)

    def test_minimum_aggregation(self):
        data = [{"category": "A", "value": 10.0}, {"category": "A", "value": 30.0}]
        result = self.f.format_group_parameter_chart(data, "MINIMUM")
        item = next(i for i in result.data if i["category"] == "A")
        assert item["value"] == pytest.approx(10.0)

    def test_median_aggregation_odd(self):
        data = [
            {"category": "A", "value": 10.0},
            {"category": "A", "value": 20.0},
            {"category": "A", "value": 30.0},
        ]
        result = self.f.format_group_parameter_chart(data, "MEDIAN")
        item = next(i for i in result.data if i["category"] == "A")
        assert item["value"] == pytest.approx(20.0)

    def test_median_aggregation_even(self):
        data = [
            {"category": "A", "value": 10.0},
            {"category": "A", "value": 20.0},
        ]
        result = self.f.format_group_parameter_chart(data, "MEDIAN")
        item = next(i for i in result.data if i["category"] == "A")
        assert item["value"] == pytest.approx(15.0)

    def test_unknown_group_defaults_to_total(self):
        data = [{"category": "A", "value": 10.0}, {"category": "A", "value": 20.0}]
        result = self.f.format_group_parameter_chart(data, "UNKNOWN_GROUP")
        item = next(i for i in result.data if i["category"] == "A")
        assert item["value"] == pytest.approx(30.0)

    def test_maximum_uses_bar_chart(self):
        result = self.f.format_group_parameter_chart(self._data(), "MAXIMUM")
        assert result.config.chart_type == ChartType.BAR

    def test_minimum_uses_bar_chart(self):
        result = self.f.format_group_parameter_chart(self._data(), "MINIMUM")
        assert result.config.chart_type == ChartType.BAR

    def test_total_uses_line_chart(self):
        result = self.f.format_group_parameter_chart(self._data(), "TOTAL")
        assert result.config.chart_type == ChartType.LINE

    def test_auto_title_from_group_and_metric(self):
        result = self.f.format_group_parameter_chart(self._data(), "MEAN", metric_type="revenue")
        assert "Revenue" in result.config.title
        assert "MEAN" in result.config.title

    def test_custom_title(self):
        result = self.f.format_group_parameter_chart(self._data(), "TOTAL", title="My Chart")
        assert result.config.title == "My Chart"

    def test_metadata_group_parameter_set(self):
        result = self.f.format_group_parameter_chart(self._data(), "TOTAL")
        assert result.metadata["group_parameter"] == "TOTAL"

    def test_metric_type_in_metadata(self):
        result = self.f.format_group_parameter_chart(self._data(), "TOTAL", metric_type="cost")
        assert result.metadata["metric_type"] == "cost"


# ---------------------------------------------------------------------------
# _process_time_series_data
# ---------------------------------------------------------------------------


class TestProcessTimeSeriesDataM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_non_list_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f._process_time_series_data("not a list")

    def test_non_dict_item_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f._process_time_series_data(["string_item"])

    def test_preserves_original_data_in_output(self):
        data = [{"date": "2024-01-01", "cost": 100.0, "extra": "value"}]
        result = self.f._process_time_series_data(data)
        assert result[0]["original_data"]["extra"] == "value"

    def test_sorts_by_date_ascending(self):
        data = [
            {"date": "2024-01-03", "cost": 30.0},
            {"date": "2024-01-01", "cost": 10.0},
            {"date": "2024-01-02", "cost": 20.0},
        ]
        result = self.f._process_time_series_data(data)
        costs = [item["cost"] for item in result]
        assert costs == [10.0, 20.0, 30.0]


# ---------------------------------------------------------------------------
# _process_breakdown_data
# ---------------------------------------------------------------------------


class TestProcessBreakdownDataM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_non_list_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f._process_breakdown_data("not a list", "provider")

    def test_non_dict_item_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f._process_breakdown_data(["item_not_dict"], "provider")

    def test_provider_breakdown_uses_provider_field(self):
        data = [{"provider": "OpenAI", "value": 100.0}]
        result = self.f._process_breakdown_data(data, "provider")
        assert result[0]["name"] == "OpenAI"

    def test_model_breakdown_uses_model_field(self):
        data = [{"model": "gpt-4", "value": 50.0}]
        result = self.f._process_breakdown_data(data, "model")
        assert result[0]["name"] == "gpt-4"

    def test_customer_breakdown_uses_organization_field(self):
        data = [{"organization": "AcmeCorp", "value": 200.0}]
        result = self.f._process_breakdown_data(data, "customer")
        assert result[0]["name"] == "AcmeCorp"

    def test_falls_back_to_name_field(self):
        data = [{"name": "Widget", "value": 75.0}]
        result = self.f._process_breakdown_data(data, "product")
        assert result[0]["name"] == "Widget"

    def test_unknown_breakdown_type_falls_back_to_category_field(self):
        data = [{"category": "misc", "value": 10.0}]
        result = self.f._process_breakdown_data(data, "other")
        assert result[0]["name"] == "misc"

    def test_value_read_from_cost_field(self):
        data = [{"provider": "OpenAI", "cost": 300.0}]
        result = self.f._process_breakdown_data(data, "provider")
        assert result[0]["value"] == 300.0

    def test_value_read_from_totalCost_field(self):
        data = [{"provider": "OpenAI", "totalCost": 500.0}]
        result = self.f._process_breakdown_data(data, "provider")
        assert result[0]["value"] == 500.0

    def test_invalid_value_defaults_to_zero(self):
        data = [{"provider": "OpenAI", "value": "not-a-number"}]
        result = self.f._process_breakdown_data(data, "provider")
        assert result[0]["value"] == 0.0

    def test_sorted_descending_by_value(self):
        data = [
            {"provider": "A", "value": 10.0},
            {"provider": "B", "value": 100.0},
            {"provider": "C", "value": 50.0},
        ]
        result = self.f._process_breakdown_data(data, "provider")
        values = [item["value"] for item in result]
        assert values == sorted(values, reverse=True)

    def test_non_string_breakdown_type_raises_tool_error(self):
        # Line 1310: breakdown_type is not a string
        with pytest.raises(ToolError):
            self.f._process_breakdown_data([{"provider": "A", "value": 10.0}], 42)


# ---------------------------------------------------------------------------
# _process_profitability_data
# ---------------------------------------------------------------------------


class TestProcessProfitabilityDataM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_profit_calculation(self):
        data = [{"product": "A", "revenue": 1000.0, "cost": 400.0}]
        result = self.f._process_profitability_data(data, "product")
        assert result[0]["profit"] == pytest.approx(600.0)

    def test_profit_margin_calculation(self):
        data = [{"product": "A", "revenue": 1000.0, "cost": 400.0}]
        result = self.f._process_profitability_data(data, "product")
        assert result[0]["profit_margin"] == pytest.approx(60.0)

    def test_zero_revenue_produces_zero_margin(self):
        data = [{"product": "A", "revenue": 0.0, "cost": 100.0}]
        result = self.f._process_profitability_data(data, "product")
        assert result[0]["profit_margin"] == 0.0

    def test_sorted_by_revenue_descending(self):
        data = [
            {"product": "Low", "revenue": 100.0, "cost": 50.0},
            {"product": "High", "revenue": 500.0, "cost": 200.0},
        ]
        result = self.f._process_profitability_data(data, "product")
        assert result[0]["revenue"] == 500.0


# ---------------------------------------------------------------------------
# _process_comparison_data
# ---------------------------------------------------------------------------


class TestProcessComparisonDataM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_current_period_label(self):
        current = [{"category": "Jan", "value": 100.0}]
        result = self.f._process_comparison_data(current, [])
        assert result[0]["period"] == "Current"

    def test_previous_period_label(self):
        previous = [{"category": "Jan", "value": 80.0}]
        result = self.f._process_comparison_data([], previous)
        assert result[0]["period"] == "Previous"

    def test_total_items_count(self):
        current = [{"category": "A", "value": 10.0}, {"category": "B", "value": 20.0}]
        previous = [{"category": "A", "value": 8.0}]
        result = self.f._process_comparison_data(current, previous)
        assert len(result) == 3

    def test_value_floated(self):
        current = [{"category": "A", "value": 10}]
        result = self.f._process_comparison_data(current, [])
        assert isinstance(result[0]["value"], float)
        assert result[0]["value"] == 10.0


# ---------------------------------------------------------------------------
# _process_multi_series_data
# ---------------------------------------------------------------------------


class TestProcessMultiSeriesDataM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_series_name_assigned(self):
        data = {"revenue": [{"x": "Jan", "y": 100}]}
        result = self.f._process_multi_series_data(data)
        assert result[0]["series"] == "revenue"

    def test_multiple_series_combined(self):
        data = {
            "a": [{"x": "Jan", "y": 10}, {"x": "Feb", "y": 20}],
            "b": [{"x": "Jan", "y": 5}],
        }
        result = self.f._process_multi_series_data(data)
        assert len(result) == 3

    def test_y_value_floated(self):
        data = {"series": [{"x": "Jan", "y": 42}]}
        result = self.f._process_multi_series_data(data)
        assert isinstance(result[0]["y"], float)
        assert result[0]["y"] == 42.0

    def test_missing_y_defaults_to_zero(self):
        data = {"series": [{"x": "Jan"}]}
        result = self.f._process_multi_series_data(data)
        assert result[0]["y"] == 0.0


# ---------------------------------------------------------------------------
# _process_agent_time_series_data
# ---------------------------------------------------------------------------


class TestProcessAgentTimeSeriesDataM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_uses_agent_id_fallback(self):
        data = [{"date": "2024-01-01", "agent_id": "agent-99", "cost": 10.0}]
        result = self.f._process_agent_time_series_data(data)
        assert result[0]["agent"] == "agent-99"

    def test_missing_agent_uses_index(self):
        data = [{"date": "2024-01-01", "cost": 10.0}]
        result = self.f._process_agent_time_series_data(data)
        assert "Agent" in result[0]["agent"]

    def test_missing_date_uses_index_label(self):
        data = [{"agent": "a1", "cost": 10.0}]
        result = self.f._process_agent_time_series_data(data)
        assert "Point" in result[0]["date"]

    def test_invalid_cost_defaults_to_zero(self):
        data = [{"date": "2024-01-01", "agent": "a1", "cost": "bad"}]
        result = self.f._process_agent_time_series_data(data)
        assert result[0]["cost"] == 0.0

    def test_non_list_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f._process_agent_time_series_data("not-a-list")

    def test_non_dict_item_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f._process_agent_time_series_data(["string_item"])


# ---------------------------------------------------------------------------
# _process_agent_performance_data
# ---------------------------------------------------------------------------


class TestProcessAgentPerformanceDataM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_uses_duration_as_fallback_for_response_time(self):
        data = [{"agent": "a1", "duration": 200.0, "throughput": 10.0}]
        result = self.f._process_agent_performance_data(data)
        assert result[0]["response_time"] == 200.0

    def test_uses_latency_as_fallback(self):
        data = [{"agent": "a1", "latency": 150.0, "throughput": 10.0}]
        result = self.f._process_agent_performance_data(data)
        assert result[0]["response_time"] == 150.0

    def test_uses_requests_per_minute_as_throughput_fallback(self):
        data = [{"agent": "a1", "response_time": 100.0, "requests_per_minute": 50.0}]
        result = self.f._process_agent_performance_data(data)
        assert result[0]["throughput"] == 50.0

    def test_efficiency_score_computed(self):
        data = [{"agent": "a1", "response_time": 100.0, "throughput": 50.0}]
        result = self.f._process_agent_performance_data(data)
        # efficiency_score = throughput / response_time = 0.5
        assert result[0]["efficiency_score"] == pytest.approx(0.5)

    def test_invalid_response_time_defaults_to_zero(self):
        data = [{"agent": "a1", "response_time": "bad", "throughput": 10.0}]
        result = self.f._process_agent_performance_data(data)
        assert result[0]["response_time"] == 0.0

    def test_invalid_throughput_defaults_to_zero(self):
        data = [{"agent": "a1", "response_time": 100.0, "throughput": "bad"}]
        result = self.f._process_agent_performance_data(data)
        assert result[0]["throughput"] == 0.0

    def test_non_list_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f._process_agent_performance_data("not-a-list")

    def test_non_dict_item_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f._process_agent_performance_data(["not-a-dict"])


# ---------------------------------------------------------------------------
# _process_task_completion_data
# ---------------------------------------------------------------------------


class TestProcessTaskCompletionDataM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_uses_tasks_completed_fallback(self):
        data = [{"date": "2024-01-01", "tasks_completed": 50, "success_rate": 95.0}]
        result = self.f._process_task_completion_data(data)
        assert result[0]["completed_tasks"] == 50

    def test_uses_count_fallback(self):
        data = [{"date": "2024-01-01", "count": 30, "success_rate": 90.0}]
        result = self.f._process_task_completion_data(data)
        assert result[0]["completed_tasks"] == 30

    def test_uses_completion_rate_fallback(self):
        data = [{"date": "2024-01-01", "completed_tasks": 50, "completion_rate": 85.0}]
        result = self.f._process_task_completion_data(data)
        assert result[0]["success_rate"] == 85.0

    def test_invalid_completed_tasks_defaults_to_zero(self):
        data = [{"date": "2024-01-01", "completed_tasks": "bad", "success_rate": 90.0}]
        result = self.f._process_task_completion_data(data)
        assert result[0]["completed_tasks"] == 0

    def test_invalid_success_rate_defaults_to_zero(self):
        data = [{"date": "2024-01-01", "completed_tasks": 100, "success_rate": "bad"}]
        result = self.f._process_task_completion_data(data)
        assert result[0]["success_rate"] == 0.0

    def test_missing_date_uses_index_label(self):
        data = [{"completed_tasks": 10, "success_rate": 90.0}]
        result = self.f._process_task_completion_data(data)
        assert "Point" in result[0]["date"]

    def test_non_list_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f._process_task_completion_data("bad")

    def test_non_dict_item_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f._process_task_completion_data(["bad-item"])


# ---------------------------------------------------------------------------
# _process_cost_distribution_data
# ---------------------------------------------------------------------------


class TestProcessCostDistributionDataM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_uses_range_field_fallback(self):
        data = [{"range": "$0-$5", "frequency": 100}]
        result = self.f._process_cost_distribution_data(data)
        assert result[0]["cost_range"] == "$0-$5"

    def test_missing_cost_range_uses_index(self):
        data = [{"frequency": 100}]
        result = self.f._process_cost_distribution_data(data)
        assert "Range" in result[0]["cost_range"]

    def test_uses_count_as_frequency_fallback(self):
        data = [{"cost_range": "$0-$1", "count": 250}]
        result = self.f._process_cost_distribution_data(data)
        assert result[0]["frequency"] == 250

    def test_invalid_frequency_defaults_to_zero(self):
        data = [{"cost_range": "$0-$1", "frequency": "bad"}]
        result = self.f._process_cost_distribution_data(data)
        assert result[0]["frequency"] == 0

    def test_percentage_extracted(self):
        data = [{"cost_range": "$0-$1", "frequency": 100, "percentage": 33.3}]
        result = self.f._process_cost_distribution_data(data)
        assert result[0]["percentage"] == pytest.approx(33.3)

    def test_invalid_percentage_defaults_to_zero(self):
        data = [{"cost_range": "$0-$1", "frequency": 100, "percentage": "bad"}]
        result = self.f._process_cost_distribution_data(data)
        assert result[0]["percentage"] == 0.0

    def test_non_list_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f._process_cost_distribution_data("not-a-list")

    def test_non_dict_item_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f._process_cost_distribution_data(["bad-item"])


# ---------------------------------------------------------------------------
# _process_provider_performance_data
# ---------------------------------------------------------------------------


class TestProcessProviderPerformanceDataM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_uses_average_duration_fallback(self):
        data = [{"provider": "OpenAI", "average_duration": 200.0, "task_count": 100}]
        result = self.f._process_provider_performance_data(data)
        assert result[0]["avg_duration"] == 200.0

    def test_uses_duration_fallback(self):
        data = [{"provider": "OpenAI", "duration": 150.0, "task_count": 100}]
        result = self.f._process_provider_performance_data(data)
        assert result[0]["avg_duration"] == 150.0

    def test_missing_provider_uses_index(self):
        data = [{"avg_duration": 100.0, "task_count": 50}]
        result = self.f._process_provider_performance_data(data)
        assert "Provider" in result[0]["provider"]

    def test_uses_count_as_task_count_fallback(self):
        data = [{"provider": "OpenAI", "avg_duration": 100.0, "count": 500}]
        result = self.f._process_provider_performance_data(data)
        assert result[0]["task_count"] == 500

    def test_invalid_avg_duration_defaults_to_zero(self):
        data = [{"provider": "OpenAI", "avg_duration": "bad", "task_count": 100}]
        result = self.f._process_provider_performance_data(data)
        assert result[0]["avg_duration"] == 0.0

    def test_invalid_task_count_defaults_to_zero(self):
        data = [{"provider": "OpenAI", "avg_duration": 100.0, "task_count": "bad"}]
        result = self.f._process_provider_performance_data(data)
        assert result[0]["task_count"] == 0

    def test_efficiency_ratio_computed(self):
        data = [{"provider": "OpenAI", "avg_duration": 100.0, "task_count": 200}]
        result = self.f._process_provider_performance_data(data)
        # efficiency_ratio = task_count / avg_duration = 2.0
        assert result[0]["efficiency_ratio"] == pytest.approx(2.0)

    def test_non_list_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f._process_provider_performance_data("not-a-list")

    def test_non_dict_item_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f._process_provider_performance_data(["bad-item"])


# ---------------------------------------------------------------------------
# _process_model_efficiency_data
# ---------------------------------------------------------------------------


class TestProcessModelEfficiencyDataM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_high_efficiency_category(self):
        data = [{"model": "gpt-4", "efficiency_score": 85.0, "cost_per_task": 0.05}]
        result = self.f._process_model_efficiency_data(data)
        assert result[0]["efficiency_category"] == "High Efficiency"

    def test_medium_efficiency_category(self):
        data = [{"model": "claude-3", "efficiency_score": 65.0, "cost_per_task": 0.04}]
        result = self.f._process_model_efficiency_data(data)
        assert result[0]["efficiency_category"] == "Medium Efficiency"

    def test_low_efficiency_category(self):
        data = [{"model": "gpt-3", "efficiency_score": 45.0, "cost_per_task": 0.10}]
        result = self.f._process_model_efficiency_data(data)
        assert result[0]["efficiency_category"] == "Low Efficiency"

    def test_uses_efficiency_field_fallback(self):
        data = [{"model": "gpt-4", "efficiency": 90.0, "cost_per_task": 0.05}]
        result = self.f._process_model_efficiency_data(data)
        assert result[0]["efficiency_score"] == 90.0

    def test_uses_cost_field_fallback_for_cost_per_task(self):
        data = [{"model": "gpt-4", "efficiency_score": 75.0, "cost": 0.03}]
        result = self.f._process_model_efficiency_data(data)
        assert result[0]["cost_per_task"] == 0.03

    def test_missing_model_uses_index(self):
        data = [{"efficiency_score": 75.0, "cost_per_task": 0.05}]
        result = self.f._process_model_efficiency_data(data)
        assert "Model" in result[0]["model"]

    def test_invalid_efficiency_defaults_to_zero(self):
        data = [{"model": "gpt-4", "efficiency_score": "bad", "cost_per_task": 0.05}]
        result = self.f._process_model_efficiency_data(data)
        assert result[0]["efficiency_score"] == 0.0

    def test_invalid_cost_per_task_defaults_to_zero(self):
        data = [{"model": "gpt-4", "efficiency_score": 75.0, "cost_per_task": "bad"}]
        result = self.f._process_model_efficiency_data(data)
        assert result[0]["cost_per_task"] == 0.0

    def test_value_ratio_computed_with_cost(self):
        data = [{"model": "gpt-4", "efficiency_score": 80.0, "cost_per_task": 0.01}]
        result = self.f._process_model_efficiency_data(data)
        # value_ratio = efficiency_score / max(cost_per_task * 100, 1) = 80 / 1.0 = 80.0
        assert result[0]["value_ratio"] == pytest.approx(80.0)

    def test_value_ratio_when_no_cost(self):
        data = [{"model": "gpt-4", "efficiency_score": 80.0, "cost_per_task": 0.0}]
        result = self.f._process_model_efficiency_data(data)
        # When cost is 0: value_ratio = efficiency_score
        assert result[0]["value_ratio"] == pytest.approx(80.0)

    def test_non_list_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f._process_model_efficiency_data("not-a-list")

    def test_non_dict_item_raises_tool_error(self):
        with pytest.raises(ToolError):
            self.f._process_model_efficiency_data(["bad-item"])


# ---------------------------------------------------------------------------
# _format_date
# ---------------------------------------------------------------------------


class TestFormatDateM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_iso_datetime_string_extracted_to_date(self):
        result = self.f._format_date("2024-06-15T10:30:00Z")
        assert result == "2024-06-15"

    def test_date_only_string_returned_as_is(self):
        result = self.f._format_date("2024-06-15")
        assert result == "2024-06-15"

    def test_non_iso_string_returned_as_is(self):
        result = self.f._format_date("June 2024")
        assert result == "June 2024"

    def test_datetime_object_formatted(self):
        dt = datetime(2024, 6, 15, 10, 30)
        result = self.f._format_date(dt)
        assert result == "2024-06-15"

    def test_integer_converted_to_string(self):
        result = self.f._format_date(20240615)
        assert result == "20240615"

    def test_none_converted_to_string(self):
        result = self.f._format_date(None)
        assert result == "None"

    def test_invalid_iso_string_falls_back_to_str(self):
        result = self.f._format_date("not-a-valid-date-T")
        # Should not raise, returns the input string unchanged
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# _get_date_range
# ---------------------------------------------------------------------------


class TestGetDateRangeM3:
    def setup_method(self):
        self.f = make_formatter()

    def test_empty_list_returns_na(self):
        result = self.f._get_date_range([])
        assert result == {"start": "N/A", "end": "N/A"}

    def test_list_without_date_keys_returns_na(self):
        result = self.f._get_date_range([{"cost": 100.0}])
        assert result == {"start": "N/A", "end": "N/A"}

    def test_single_item_range_is_same(self):
        result = self.f._get_date_range([{"date": "2024-01-01"}])
        assert result["start"] == "2024-01-01"
        assert result["end"] == "2024-01-01"

    def test_multiple_items_returns_correct_range(self):
        data = [
            {"date": "2024-01-03"},
            {"date": "2024-01-01"},
            {"date": "2024-01-02"},
        ]
        result = self.f._get_date_range(data)
        assert result["start"] == "2024-01-01"
        assert result["end"] == "2024-01-03"
