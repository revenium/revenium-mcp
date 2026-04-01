"""Unit tests for ComparativeAnalyticsProcessor comparison logic (lines 160-962).

Covers:
- compare_periods: full async flow, error paths, metadata
- compare_models: full async flow, error paths
- compare_providers: full async flow, error paths
- benchmark_customers: full async flow, error paths
- _calculate_percentage_changes: edge cases beyond existing tests
- _generate_comparison_insights: branch coverage
- _generate_comparison_recommendations: heavily branched paths
- Provider comparison helpers
- _process_api_response: dict/list/edge formats
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.analytics.comparative_analytics_processor import (
    BenchmarkData,
    ComparisonResult,
    ComparativeAnalyticsProcessor,
    PercentageChange,
)
from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.common.error_handling import ToolError


@pytest.fixture
def proc():
    return ComparativeAnalyticsProcessor()


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get = AsyncMock()
    return client


# ─────────────────────────────────────────────────────────────────────────────
# compare_periods (lines 160-299)
# ─────────────────────────────────────────────────────────────────────────────


class TestComparePeriods:
    """Full async tests for period-over-period comparison."""

    @pytest.mark.asyncio
    async def test_successful_comparison_returns_result(self, proc, mock_client):
        """Happy path: two periods return a ComparisonResult with correct fields."""
        api_response = {
            "groups": [
                {
                    "groupName": "OpenAI",
                    "metrics": [{"metricResult": 100.0}],
                }
            ]
        }
        mock_client.get = AsyncMock(return_value=api_response)

        result = await proc.compare_periods(
            mock_client, "team1", "SEVEN_DAYS", "THIRTY_DAYS", "cost", "provider"
        )

        assert isinstance(result, ComparisonResult)
        assert result.comparison_type == "period"
        assert result.metadata["current_period"] == "SEVEN_DAYS"
        assert result.metadata["previous_period"] == "THIRTY_DAYS"
        assert result.metadata["metric_type"] == "cost"
        assert result.metadata["api_calls_made"] == 2
        assert "processed_at" in result.metadata

    @pytest.mark.asyncio
    async def test_comparison_calculates_percentage_changes(self, proc, mock_client):
        """Percentage changes are computed from fetched data."""
        current_resp = {
            "groups": [
                {"groupName": "OpenAI", "metrics": [{"metricResult": 200.0}]}
            ]
        }
        prev_resp = {
            "groups": [
                {"groupName": "OpenAI", "metrics": [{"metricResult": 100.0}]}
            ]
        }
        mock_client.get = AsyncMock(side_effect=[current_resp, prev_resp])

        result = await proc.compare_periods(
            mock_client, "team1", "SEVEN_DAYS", "THIRTY_DAYS", "cost", "provider"
        )

        assert len(result.percentage_changes) == 1
        assert result.percentage_changes[0].percentage_change == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_api_error_raises_tool_error(self, proc, mock_client):
        """ReveniumAPIError is wrapped in ToolError with suggestions."""
        mock_client.get = AsyncMock(
            side_effect=ReveniumAPIError("API down", status_code=500)
        )

        with pytest.raises(ToolError) as exc_info:
            await proc.compare_periods(
                mock_client, "team1", "SEVEN_DAYS", "THIRTY_DAYS"
            )
        assert "Period comparison failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_unexpected_exception_raises_tool_error(self, proc, mock_client):
        """Generic exceptions are wrapped as PROCESSING_ERROR."""
        mock_client.get = AsyncMock(side_effect=RuntimeError("unexpected"))

        with pytest.raises(ToolError) as exc_info:
            await proc.compare_periods(
                mock_client, "team1", "SEVEN_DAYS", "THIRTY_DAYS"
            )
        assert "Period comparison failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validation_error_is_propagated(self, proc, mock_client):
        """ToolError from validation is re-raised unchanged."""
        with pytest.raises(ToolError):
            await proc.compare_periods(
                mock_client, "team1", "BAD_PERIOD", "THIRTY_DAYS"
            )

    @pytest.mark.asyncio
    async def test_current_period_exception_is_raised(self, proc, mock_client):
        """When current period fetch raises, it propagates."""
        mock_client.get = AsyncMock(
            side_effect=ReveniumAPIError("fail", status_code=500)
        )

        with pytest.raises(ToolError):
            await proc.compare_periods(
                mock_client, "team1", "SEVEN_DAYS", "THIRTY_DAYS"
            )

    @pytest.mark.asyncio
    async def test_metadata_includes_data_points(self, proc, mock_client):
        """Metadata tracks data_points_current and data_points_comparison."""
        resp = {
            "groups": [
                {"groupName": "A", "metrics": [{"metricResult": 50.0}]},
                {"groupName": "B", "metrics": [{"metricResult": 75.0}]},
            ]
        }
        mock_client.get = AsyncMock(return_value=resp)

        result = await proc.compare_periods(
            mock_client, "team1", "SEVEN_DAYS", "THIRTY_DAYS", "cost", "provider"
        )
        assert result.metadata["data_points_current"] == 2
        assert result.metadata["data_points_comparison"] == 2

    @pytest.mark.asyncio
    async def test_custom_group_parameter(self, proc, mock_client):
        """Non-default group parameter passes through."""
        resp = {"groups": []}
        mock_client.get = AsyncMock(return_value=resp)

        result = await proc.compare_periods(
            mock_client, "team1", "SEVEN_DAYS", "THIRTY_DAYS",
            "cost", "provider", "MEAN"
        )
        assert isinstance(result, ComparisonResult)
        assert result.comparison_type == "period"

    @pytest.mark.asyncio
    async def test_insights_and_recommendations_populated(self, proc, mock_client):
        """Result includes insights and recommendations lists."""
        resp = {
            "groups": [
                {"groupName": "OpenAI", "metrics": [{"metricResult": 200.0}]}
            ]
        }
        mock_client.get = AsyncMock(return_value=resp)

        result = await proc.compare_periods(
            mock_client, "team1", "SEVEN_DAYS", "THIRTY_DAYS", "cost", "provider"
        )
        assert isinstance(result.key_insights, list)
        assert isinstance(result.recommendations, list)
        assert all(isinstance(i, str) for i in result.key_insights)


# ─────────────────────────────────────────────────────────────────────────────
# compare_models (lines 301-403)
# ─────────────────────────────────────────────────────────────────────────────


class TestCompareModels:
    """Full async tests for model-vs-model comparison."""

    @pytest.mark.asyncio
    async def test_successful_model_comparison(self, proc, mock_client):
        """Happy path returns ComparisonResult with model metadata."""
        api_response = {
            "groups": [
                {"groupName": "gpt-4", "metrics": [{"metricResult": 150.0}]},
                {"groupName": "claude-3", "metrics": [{"metricResult": 100.0}]},
            ]
        }
        mock_client.get = AsyncMock(return_value=api_response)

        result = await proc.compare_models(
            mock_client, "team1", "gpt-4", "claude-3", "TWELVE_MONTHS", "cost"
        )

        assert isinstance(result, ComparisonResult)
        assert result.comparison_type == "model"
        assert result.metadata["model_a"] == "gpt-4"
        assert result.metadata["model_b"] == "claude-3"
        assert result.metadata["api_calls_made"] == 1

    @pytest.mark.asyncio
    async def test_model_comparison_with_performance(self, proc, mock_client):
        """Performance metric type uses performance field."""
        api_response = {
            "groups": [
                {"groupName": "gpt-4", "metrics": [{"metricResult": 95.0}]},
                {"groupName": "claude-3", "metrics": [{"metricResult": 90.0}]},
            ]
        }
        mock_client.get = AsyncMock(return_value=api_response)

        result = await proc.compare_models(
            mock_client, "team1", "gpt-4", "claude-3", "TWELVE_MONTHS", "performance"
        )
        assert result.comparison_type == "model"

    @pytest.mark.asyncio
    async def test_model_not_found_returns_defaults(self, proc, mock_client):
        """When a model isn't in the response, defaults are used."""
        api_response = {
            "groups": [
                {"groupName": "gpt-4", "metrics": [{"metricResult": 150.0}]},
            ]
        }
        mock_client.get = AsyncMock(return_value=api_response)

        result = await proc.compare_models(
            mock_client, "team1", "gpt-4", "missing-model", "TWELVE_MONTHS", "cost"
        )
        assert result.comparison_data["model"] == "missing-model"

    @pytest.mark.asyncio
    async def test_model_comparison_exception_raises_tool_error(self, proc, mock_client):
        """Generic exception wrapped in ToolError with model names."""
        mock_client.get = AsyncMock(side_effect=RuntimeError("boom"))

        with pytest.raises(ToolError) as exc_info:
            await proc.compare_models(
                mock_client, "team1", "gpt-4", "claude-3"
            )
        assert "Model comparison failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_model_comparison_tool_error_passthrough(self, proc, mock_client):
        """ToolError from internal methods is re-raised."""
        mock_client.get = AsyncMock(
            side_effect=ToolError(message="internal error")
        )

        with pytest.raises(ToolError):
            await proc.compare_models(
                mock_client, "team1", "gpt-4", "claude-3"
            )


# ─────────────────────────────────────────────────────────────────────────────
# compare_providers (lines 405-491)
# ─────────────────────────────────────────────────────────────────────────────


class TestCompareProviders:
    """Full async tests for provider comparison."""

    @pytest.mark.asyncio
    async def test_successful_provider_comparison(self, proc, mock_client):
        """Happy path returns ComparisonResult with provider metadata."""
        api_response = {
            "groups": [
                {"groupName": "OpenAI", "metrics": [{"metricResult": 200.0}]},
                {"groupName": "Anthropic", "metrics": [{"metricResult": 150.0}]},
            ]
        }
        mock_client.get = AsyncMock(return_value=api_response)

        result = await proc.compare_providers(
            mock_client, "team1", "OpenAI", "Anthropic", "TWELVE_MONTHS", "cost"
        )

        assert isinstance(result, ComparisonResult)
        assert result.comparison_type == "provider"
        assert result.metadata["provider_a"] == "OpenAI"
        assert result.metadata["provider_b"] == "Anthropic"

    @pytest.mark.asyncio
    async def test_provider_comparison_performance_metric(self, proc, mock_client):
        """Performance metric uses correct endpoint."""
        api_response = {
            "groups": [
                {"groupName": "OpenAI", "metrics": [{"metricResult": 92.0}]},
                {"groupName": "Anthropic", "metrics": [{"metricResult": 88.0}]},
            ]
        }
        mock_client.get = AsyncMock(return_value=api_response)

        result = await proc.compare_providers(
            mock_client, "team1", "OpenAI", "Anthropic",
            "TWELVE_MONTHS", "performance"
        )
        assert result.comparison_type == "provider"

    @pytest.mark.asyncio
    async def test_provider_comparison_exception_raises_tool_error(self, proc, mock_client):
        """Generic exception wrapped in ToolError."""
        mock_client.get = AsyncMock(side_effect=RuntimeError("fail"))

        with pytest.raises(ToolError) as exc_info:
            await proc.compare_providers(
                mock_client, "team1", "OpenAI", "Anthropic"
            )
        assert "Provider comparison failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_provider_tool_error_passthrough(self, proc, mock_client):
        """ToolError from fetch is re-raised."""
        mock_client.get = AsyncMock(side_effect=ToolError(message="upstream"))

        with pytest.raises(ToolError):
            await proc.compare_providers(
                mock_client, "team1", "OpenAI", "Anthropic"
            )

    @pytest.mark.asyncio
    async def test_provider_not_found_returns_defaults(self, proc, mock_client):
        """Missing provider in response uses default zero values."""
        api_response = {
            "groups": [
                {"groupName": "OpenAI", "metrics": [{"metricResult": 100.0}]}
            ]
        }
        mock_client.get = AsyncMock(return_value=api_response)

        result = await proc.compare_providers(
            mock_client, "team1", "OpenAI", "MissingProvider", "TWELVE_MONTHS", "cost"
        )
        assert result.comparison_data["provider"] == "MissingProvider"


# ─────────────────────────────────────────────────────────────────────────────
# benchmark_customers (lines 493-572)
# ─────────────────────────────────────────────────────────────────────────────


class TestBenchmarkCustomers:
    """Full async tests for customer benchmarking."""

    @pytest.mark.asyncio
    async def test_successful_benchmark(self, proc, mock_client):
        """Happy path returns BenchmarkData with computed metrics."""
        cost_resp = {
            "groups": [
                {"groupName": "cust1", "metrics": [{"metricResult": 500.0}]},
                {"groupName": "cust2", "metrics": [{"metricResult": 300.0}]},
            ]
        }
        revenue_resp = {
            "groups": [
                {"groupName": "cust1", "metrics": [{"metricResult": 1000.0}]},
                {"groupName": "cust2", "metrics": [{"metricResult": 600.0}]},
            ]
        }
        # compare_periods calls 4 gets: 2 for customer, 2 for benchmark
        mock_client.get = AsyncMock(side_effect=[
            cost_resp, revenue_resp, cost_resp, revenue_resp
        ])

        result = await proc.benchmark_customers(
            mock_client, "team1", "cust1", "industry_average", "TWELVE_MONTHS"
        )

        assert isinstance(result, BenchmarkData)
        assert result.entity_id == "cust1"
        assert result.entity_type == "customer"

    @pytest.mark.asyncio
    async def test_benchmark_with_api_errors_returns_empty_metrics(self, proc, mock_client):
        """When inner API calls fail, gather catches them; benchmark still returns."""
        # asyncio.gather(return_exceptions=True) inside _fetch_customer_metrics
        # catches the error, producing empty metrics rather than raising
        mock_client.get = AsyncMock(side_effect=RuntimeError("network down"))

        result = await proc.benchmark_customers(
            mock_client, "team1", "cust1"
        )
        # Should still return a BenchmarkData with empty metrics
        assert isinstance(result, BenchmarkData)
        assert result.entity_id == "cust1"

    @pytest.mark.asyncio
    async def test_benchmark_outer_exception_raises_tool_error(self, proc, mock_client):
        """Exception in benchmark_customers outer try block raises ToolError."""
        # Force an exception after gather by making _calculate_benchmark_performance fail
        mock_client.get = AsyncMock(return_value={"groups": []})

        with patch.object(
            proc, "_calculate_benchmark_performance",
            side_effect=RuntimeError("processing error")
        ):
            with pytest.raises(ToolError) as exc_info:
                await proc.benchmark_customers(
                    mock_client, "team1", "cust1"
                )
            assert "Customer benchmarking failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_benchmark_with_customer_not_in_data(self, proc, mock_client):
        """Customer not in API data returns empty metrics."""
        cost_resp = {
            "groups": [
                {"groupName": "other_cust", "metrics": [{"metricResult": 100.0}]}
            ]
        }
        revenue_resp = {
            "groups": [
                {"groupName": "other_cust", "metrics": [{"metricResult": 200.0}]}
            ]
        }
        mock_client.get = AsyncMock(side_effect=[
            cost_resp, revenue_resp, cost_resp, revenue_resp
        ])

        result = await proc.benchmark_customers(
            mock_client, "team1", "missing_cust"
        )
        assert result.entity_id == "missing_cust"


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_percentage_changes (lines 683-777) — additional edge cases
# ─────────────────────────────────────────────────────────────────────────────


class TestCalculatePercentageChangesExtended:
    """Extended tests for percentage change calculations covering missed branches."""

    def setup_method(self):
        self.proc = ComparativeAnalyticsProcessor()

    def test_multiple_entities_calculated(self):
        """Multiple entities produce multiple PercentageChange objects."""
        current = {"data": [
            {"provider": "OpenAI", "cost": 200},
            {"provider": "Anthropic", "cost": 150},
        ]}
        comparison = {"data": [
            {"provider": "OpenAI", "cost": 100},
            {"provider": "Anthropic", "cost": 100},
        ]}
        changes = self.proc._calculate_percentage_changes(current, comparison, "provider")
        assert len(changes) == 2

    def test_non_dict_items_skipped(self):
        """Non-dict items in data lists are skipped."""
        current = {"data": ["not a dict", {"provider": "X", "cost": 50}]}
        comparison = {"data": [{"provider": "X", "cost": 40}]}
        changes = self.proc._calculate_percentage_changes(current, comparison, "provider")
        assert len(changes) == 1

    def test_items_without_key_skipped(self):
        """Items without matching breakdown key are skipped."""
        current = {"data": [{"cost": 100}]}
        comparison = {"data": []}
        changes = self.proc._calculate_percentage_changes(current, comparison, "provider")
        assert len(changes) == 0

    def test_model_breakdown_uses_model_field(self):
        """Model breakdown matches on 'model' field."""
        current = {"data": [{"model": "gpt-4", "cost": 200}]}
        comparison = {"data": [{"model": "gpt-4", "cost": 150}]}
        changes = self.proc._calculate_percentage_changes(current, comparison, "model")
        assert len(changes) == 1

    def test_organization_breakdown_uses_organization_field(self):
        """Organization breakdown matches on 'organization' field."""
        current = {"data": [{"organization": "AcmeCorp", "cost": 300}]}
        comparison = {"data": [{"organization": "AcmeCorp", "cost": 200}]}
        changes = self.proc._calculate_percentage_changes(current, comparison, "customer")
        assert len(changes) == 1

    def test_revenue_field_used_when_cost_is_zero(self):
        """Revenue field is used as fallback when cost is 0."""
        current = {"data": [{"provider": "X", "cost": 0, "revenue": 500}]}
        comparison = {"data": [{"provider": "X", "cost": 0, "revenue": 400}]}
        changes = self.proc._calculate_percentage_changes(current, comparison, "provider")
        assert len(changes) == 1
        assert changes[0].current_value == 500.0

    def test_decreasing_trend_threshold(self):
        """Exactly -5% is still stable, below is decreasing."""
        current = {"data": [{"provider": "X", "cost": 94}]}
        comparison = {"data": [{"provider": "X", "cost": 100}]}
        changes = self.proc._calculate_percentage_changes(current, comparison, "provider")
        assert changes[0].trend_direction == "decreasing"

    def test_increasing_trend_threshold(self):
        """Exactly 5% is still stable, above is increasing."""
        current = {"data": [{"provider": "X", "cost": 106}]}
        comparison = {"data": [{"provider": "X", "cost": 100}]}
        changes = self.proc._calculate_percentage_changes(current, comparison, "provider")
        assert changes[0].trend_direction == "increasing"

    def test_boundary_stable_at_five_percent(self):
        """Exactly 5% change is stable, not increasing."""
        current = {"data": [{"provider": "X", "cost": 105}]}
        comparison = {"data": [{"provider": "X", "cost": 100}]}
        changes = self.proc._calculate_percentage_changes(current, comparison, "provider")
        assert changes[0].trend_direction == "stable"

    def test_boundary_moderate_at_ten_percent(self):
        """Exactly 10% change is moderate significance."""
        current = {"data": [{"provider": "X", "cost": 110}]}
        comparison = {"data": [{"provider": "X", "cost": 100}]}
        changes = self.proc._calculate_percentage_changes(current, comparison, "provider")
        assert changes[0].significance == "moderate"

    def test_comparison_lookup_non_dict_items_skipped(self):
        """Non-dict items in comparison data are skipped."""
        current = {"data": [{"provider": "X", "cost": 100}]}
        comparison = {"data": ["garbage", {"provider": "X", "cost": 80}]}
        changes = self.proc._calculate_percentage_changes(current, comparison, "provider")
        assert len(changes) == 1


# ─────────────────────────────────────────────────────────────────────────────
# _generate_comparison_insights (lines 780-840) — branch coverage
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateComparisonInsightsExtended:
    """Extended branch coverage for insight generation."""

    def setup_method(self):
        self.proc = ComparativeAnalyticsProcessor()

    def test_decreasing_overall_trend(self):
        """When majority are decreasing, reports decreasing trend."""
        changes = [
            PercentageChange(50, 100, -50, -50.0, "decreasing", "significant", "A"),
            PercentageChange(60, 100, -40, -40.0, "decreasing", "significant", "B"),
            PercentageChange(110, 100, 10, 10.0, "increasing", "moderate", "C"),
        ]
        insights = self.proc._generate_comparison_insights(changes, "cost", "provider")
        assert any("decreasing" in i.lower() for i in insights)

    def test_mixed_trend_when_equal(self):
        """Equal increasing/decreasing produces mixed trend."""
        changes = [
            PercentageChange(130, 100, 30, 30.0, "increasing", "significant", "A"),
            PercentageChange(70, 100, -30, -30.0, "decreasing", "significant", "B"),
        ]
        insights = self.proc._generate_comparison_insights(changes, "cost", "provider")
        assert any("mixed" in i.lower() for i in insights)

    def test_no_significant_changes_omits_detail(self):
        """When changes are minimal, no increase/decrease detail line."""
        changes = [
            PercentageChange(102, 100, 2, 2.0, "stable", "minimal", "A"),
        ]
        insights = self.proc._generate_comparison_insights(changes, "cost", "provider")
        assert not any("increases detected" in i.lower() for i in insights)

    def test_average_increase_calculation(self):
        """Average percentage increase is computed correctly."""
        changes = [
            PercentageChange(140, 100, 40, 40.0, "increasing", "significant", "A"),
            PercentageChange(160, 100, 60, 60.0, "increasing", "significant", "B"),
        ]
        insights = self.proc._generate_comparison_insights(changes, "revenue", "model")
        assert any("50.0%" in i for i in insights)

    def test_average_decrease_calculation(self):
        """Average percentage decrease is computed correctly."""
        changes = [
            PercentageChange(70, 100, -30, -30.0, "decreasing", "significant", "A"),
            PercentageChange(50, 100, -50, -50.0, "decreasing", "significant", "B"),
        ]
        insights = self.proc._generate_comparison_insights(changes, "cost", "provider")
        assert any("40.0%" in i for i in insights)


# ─────────────────────────────────────────────────────────────────────────────
# _generate_comparison_recommendations (lines 842-962) — heavily branched
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateComparisonRecommendationsExtended:
    """Extended branch coverage for comparison recommendations."""

    def setup_method(self):
        self.proc = ComparativeAnalyticsProcessor()

    def test_cost_increase_with_major_increases(self):
        """Major increase (>50%) triggers critical review recommendation."""
        changes = [
            PercentageChange(300, 100, 200, 200.0, "increasing", "significant", "BigSpender"),
        ]
        recs = self.proc._generate_comparison_recommendations(changes, "cost")
        assert any("critical" in r.lower() for r in recs)
        assert any("BigSpender" in r for r in recs)

    def test_cost_decrease_with_savings_estimate(self):
        """Cost decreases include estimated savings."""
        changes = [
            PercentageChange(50, 200, -150, -75.0, "decreasing", "significant", "Saver"),
        ]
        recs = self.proc._generate_comparison_recommendations(changes, "cost")
        assert any("savings" in r.lower() or "saving" in r.lower() for r in recs)
        assert any("150" in r for r in recs)

    def test_cost_decrease_includes_best_practice(self):
        """Cost decreases include best practice recommendation."""
        changes = [
            PercentageChange(40, 100, -60, -60.0, "decreasing", "significant", "OptimizedCo"),
        ]
        recs = self.proc._generate_comparison_recommendations(changes, "cost")
        assert any("best practice" in r.lower() or "playbook" in r.lower() for r in recs)

    def test_revenue_increase_recommendation(self):
        """Revenue increase triggers capitalize recommendation."""
        changes = [
            PercentageChange(200, 100, 100, 100.0, "increasing", "significant", "GrowCo"),
        ]
        recs = self.proc._generate_comparison_recommendations(changes, "revenue")
        assert any("revenue" in r.lower() and "growth" in r.lower() for r in recs)

    def test_revenue_decrease_recommendation(self):
        """Revenue decrease triggers recovery recommendation."""
        changes = [
            PercentageChange(50, 100, -50, -50.0, "decreasing", "significant", "ShrinkCo"),
        ]
        recs = self.proc._generate_comparison_recommendations(changes, "revenue")
        assert any("decline" in r.lower() or "recovery" in r.lower() for r in recs)

    def test_high_volatility_detected(self):
        """More than 50% significant changes triggers volatility warning."""
        changes = [
            PercentageChange(200, 100, 100, 100.0, "increasing", "significant", "A"),
            PercentageChange(40, 100, -60, -60.0, "decreasing", "significant", "B"),
        ]
        recs = self.proc._generate_comparison_recommendations(changes, "cost")
        assert any("volatility" in r.lower() for r in recs)

    def test_no_volatility_when_below_threshold(self):
        """Volatility not triggered when below 50% threshold."""
        changes = [
            PercentageChange(200, 100, 100, 100.0, "increasing", "significant", "A"),
            PercentageChange(102, 100, 2, 2.0, "stable", "minimal", "B"),
            PercentageChange(103, 100, 3, 3.0, "stable", "minimal", "C"),
        ]
        recs = self.proc._generate_comparison_recommendations(changes, "cost")
        assert not any("volatility" in r.lower() for r in recs)

    def test_cost_increase_without_major_still_action(self):
        """Significant cost increase under 50% still triggers action."""
        changes = [
            PercentageChange(135, 100, 35, 35.0, "increasing", "significant", "MedSpend"),
        ]
        recs = self.proc._generate_comparison_recommendations(changes, "cost")
        assert any("action" in r.lower() or "immediate" in r.lower() for r in recs)

    def test_performance_metric_no_cost_recommendations(self):
        """Performance metric doesn't trigger cost-specific recs."""
        changes = [
            PercentageChange(120, 100, 20, 20.0, "increasing", "significant", "X"),
        ]
        recs = self.proc._generate_comparison_recommendations(changes, "performance")
        assert not any("cost optimization" in r.lower() for r in recs)


# ─────────────────────────────────────────────────────────────────────────────
# Provider comparison helpers
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractProviderData:
    """Test _extract_provider_data."""

    def setup_method(self):
        self.proc = ComparativeAnalyticsProcessor()

    def test_extracts_matching_provider(self):
        data = {"data": [
            {"provider": "OpenAI", "cost": 100},
            {"provider": "Anthropic", "cost": 200},
        ]}
        result = self.proc._extract_provider_data(data, "OpenAI")
        assert result["cost"] == 100

    def test_missing_provider_returns_defaults(self):
        data = {"data": [{"provider": "OpenAI", "cost": 100}]}
        result = self.proc._extract_provider_data(data, "MissingProvider")
        assert result["provider"] == "MissingProvider"
        assert result["cost"] == 0

    def test_handles_list_format(self):
        data = [{"provider": "OpenAI", "cost": 100}]
        result = self.proc._extract_provider_data(data, "OpenAI")
        assert result["cost"] == 100


class TestCalculateProviderComparisonChanges:
    """Test _calculate_provider_comparison_changes."""

    def setup_method(self):
        self.proc = ComparativeAnalyticsProcessor()

    def test_cost_comparison(self):
        a_data = {"cost": 300}
        b_data = {"cost": 100}
        changes = self.proc._calculate_provider_comparison_changes(
            a_data, b_data, "cost", "ProvA", "ProvB"
        )
        assert len(changes) == 1
        assert changes[0].percentage_change == pytest.approx(200.0)
        assert changes[0].entity_name == "ProvA vs ProvB"

    def test_zero_value_b_returns_empty(self):
        a_data = {"cost": 100}
        b_data = {"cost": 0}
        changes = self.proc._calculate_provider_comparison_changes(
            a_data, b_data, "cost", "A", "B"
        )
        assert len(changes) == 0

    def test_performance_comparison(self):
        a_data = {"performance": 95}
        b_data = {"performance": 80}
        changes = self.proc._calculate_provider_comparison_changes(
            a_data, b_data, "performance", "A", "B"
        )
        assert len(changes) == 1
        assert changes[0].current_value == 95.0

    def test_moderate_significance(self):
        a_data = {"cost": 115}
        b_data = {"cost": 100}
        changes = self.proc._calculate_provider_comparison_changes(
            a_data, b_data, "cost", "A", "B"
        )
        assert changes[0].significance == "moderate"

    def test_stable_trend(self):
        a_data = {"cost": 103}
        b_data = {"cost": 100}
        changes = self.proc._calculate_provider_comparison_changes(
            a_data, b_data, "cost", "A", "B"
        )
        assert changes[0].trend_direction == "stable"


class TestGenerateProviderComparisonInsights:
    """Test _generate_provider_comparison_insights."""

    def setup_method(self):
        self.proc = ComparativeAnalyticsProcessor()

    def test_no_changes_returns_no_data(self):
        insights = self.proc._generate_provider_comparison_insights(
            "A", "B", [], "cost"
        )
        assert any("No cost data" in i for i in insights)

    def test_increasing_reports_higher(self):
        changes = [
            PercentageChange(200, 100, 100, 100.0, "increasing", "significant", "A vs B")
        ]
        insights = self.proc._generate_provider_comparison_insights(
            "A", "B", changes, "cost"
        )
        assert any("higher" in i.lower() for i in insights)

    def test_decreasing_reports_lower(self):
        changes = [
            PercentageChange(50, 100, -50, -50.0, "decreasing", "significant", "A vs B")
        ]
        insights = self.proc._generate_provider_comparison_insights(
            "A", "B", changes, "cost"
        )
        assert any("lower" in i.lower() for i in insights)

    def test_stable_reports_similar(self):
        changes = [
            PercentageChange(100, 100, 0, 0.0, "stable", "minimal", "A vs B")
        ]
        insights = self.proc._generate_provider_comparison_insights(
            "A", "B", changes, "cost"
        )
        assert any("similar" in i.lower() for i in insights)

    def test_significant_warns_investigation(self):
        changes = [
            PercentageChange(200, 100, 100, 100.0, "increasing", "significant", "A vs B")
        ]
        insights = self.proc._generate_provider_comparison_insights(
            "A", "B", changes, "cost"
        )
        assert any("significant" in i.lower() for i in insights)


class TestGenerateProviderRecommendations:
    """Test _generate_provider_recommendations."""

    def setup_method(self):
        self.proc = ComparativeAnalyticsProcessor()

    def test_no_changes_recommends_data_collection(self):
        recs = self.proc._generate_provider_recommendations("A", "B", [])
        assert any("data" in r.lower() for r in recs)

    def test_large_cost_difference_triggers_strategic_review(self):
        changes = [
            PercentageChange(500, 100, 400, 400.0, "increasing", "significant", "A vs B")
        ]
        recs = self.proc._generate_provider_recommendations("A", "B", changes)
        assert any("strategic" in r.lower() or "migration" in r.lower() for r in recs)

    def test_moderate_cost_increase_triggers_optimization(self):
        changes = [
            PercentageChange(125, 100, 25, 25.0, "increasing", "significant", "A vs B")
        ]
        recs = self.proc._generate_provider_recommendations("A", "B", changes)
        assert any("optimization" in r.lower() or "cost" in r.lower() for r in recs)

    def test_decreasing_cost_confirms_efficiency(self):
        changes = [
            PercentageChange(50, 100, -50, -50.0, "decreasing", "significant", "A vs B")
        ]
        recs = self.proc._generate_provider_recommendations("A", "B", changes)
        assert any("efficien" in r.lower() for r in recs)

    def test_large_monthly_impact_triggers_risk_management(self):
        """Monthly impact > $1000 triggers risk management."""
        changes = [
            PercentageChange(200, 100, 100, 100.0, "increasing", "significant", "A vs B")
        ]
        recs = self.proc._generate_provider_recommendations("A", "B", changes)
        # monthly_impact = 100 * 30 = 3000 > 1000
        assert any("risk" in r.lower() for r in recs)


# ─────────────────────────────────────────────────────────────────────────────
# _process_api_response
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessApiResponse:
    """Test _process_api_response for dict/list/edge formats."""

    def setup_method(self):
        self.proc = ComparativeAnalyticsProcessor()

    def test_dict_format_with_groups(self):
        """Dict response with groups extracts data correctly."""
        response = {
            "groups": [
                {"groupName": "OpenAI", "metrics": [{"metricResult": 50.0}]}
            ]
        }
        result = self.proc._process_api_response(response, "provider")
        assert len(result) == 1
        assert result[0]["provider"] == "OpenAI"
        assert result[0]["cost"] == 50.0

    def test_list_format_response(self):
        """List response with time periods processes correctly."""
        response = [
            {
                "groups": [
                    {"groupName": "gpt-4", "metrics": [{"metricResult": 75.0}]}
                ]
            }
        ]
        result = self.proc._process_api_response(response, "model")
        assert len(result) == 1
        assert result[0]["model"] == "gpt-4"

    def test_zero_cost_excluded(self):
        """Groups with zero cost are excluded."""
        response = {
            "groups": [
                {"groupName": "Empty", "metrics": [{"metricResult": 0}]}
            ]
        }
        result = self.proc._process_api_response(response, "provider")
        assert len(result) == 0

    def test_non_numeric_metric_skipped(self):
        """Non-numeric metricResult is skipped."""
        response = {
            "groups": [
                {"groupName": "Bad", "metrics": [{"metricResult": "not a number"}]}
            ]
        }
        result = self.proc._process_api_response(response, "provider")
        assert len(result) == 0

    def test_empty_groups_returns_empty(self):
        response = {"groups": []}
        result = self.proc._process_api_response(response, "provider")
        assert result == []

    def test_unexpected_format_returns_empty(self):
        """Non-dict non-list response returns empty."""
        result = self.proc._process_api_response("unexpected", "provider")
        assert result == []

    def test_multiple_metrics_summed(self):
        """Multiple metrics in a group are summed."""
        response = {
            "groups": [
                {
                    "groupName": "OpenAI",
                    "metrics": [
                        {"metricResult": 30.0},
                        {"metricResult": 20.0},
                    ],
                }
            ]
        }
        result = self.proc._process_api_response(response, "provider")
        assert result[0]["cost"] == 50.0

    def test_customer_breakdown_sets_organization(self):
        """Customer breakdown sets organization field."""
        response = {
            "groups": [
                {"groupName": "AcmeCorp", "metrics": [{"metricResult": 100.0}]}
            ]
        }
        result = self.proc._process_api_response(response, "customer")
        assert result[0]["organization"] == "AcmeCorp"
        assert result[0]["provider"] is None

    def test_non_dict_group_skipped(self):
        """Non-dict items in groups list are skipped."""
        response = {"groups": ["not a dict"]}
        result = self.proc._process_api_response(response, "provider")
        assert result == []

    def test_non_list_groups_returns_empty(self):
        """Non-list groups value returns empty."""
        response = {"groups": "not a list"}
        result = self.proc._process_api_response(response, "provider")
        assert result == []

    def test_non_dict_metrics_skipped(self):
        """Non-dict items in metrics list are skipped."""
        response = {
            "groups": [
                {"groupName": "X", "metrics": ["not a dict"]}
            ]
        }
        result = self.proc._process_api_response(response, "provider")
        assert result == []

    def test_non_list_metrics_skipped(self):
        """Non-list metrics value is skipped."""
        response = {
            "groups": [
                {"groupName": "X", "metrics": "not a list"}
            ]
        }
        result = self.proc._process_api_response(response, "provider")
        assert result == []

    def test_empty_list_returns_empty(self):
        """Empty list response returns empty."""
        result = self.proc._process_api_response([], "provider")
        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_benchmark_performance and _calculate_customer_ranking
# ─────────────────────────────────────────────────────────────────────────────


class TestBenchmarkPerformanceCalculation:
    """Test _calculate_benchmark_performance."""

    def setup_method(self):
        self.proc = ComparativeAnalyticsProcessor()

    def test_above_benchmark(self):
        customer = {"cost": 150.0, "revenue": 300.0}
        benchmark = {"cost": 100.0, "revenue": 200.0}
        result = self.proc._calculate_benchmark_performance(customer, benchmark)
        assert "cost" in result
        assert "revenue" in result
        assert result["cost"].percentage_change == pytest.approx(50.0)

    def test_below_benchmark(self):
        customer = {"cost": 50.0}
        benchmark = {"cost": 100.0}
        result = self.proc._calculate_benchmark_performance(customer, benchmark)
        assert result["cost"].percentage_change == pytest.approx(-50.0)

    def test_zero_benchmark_excluded(self):
        """Zero benchmark value skips that metric."""
        customer = {"cost": 100.0}
        benchmark = {"cost": 0.0}
        result = self.proc._calculate_benchmark_performance(customer, benchmark)
        assert "cost" not in result

    def test_missing_metric_in_benchmark_skipped(self):
        """Metric not in benchmark is skipped."""
        customer = {"cost": 100.0, "revenue": 200.0}
        benchmark = {"cost": 50.0}
        result = self.proc._calculate_benchmark_performance(customer, benchmark)
        assert "cost" in result
        assert "revenue" not in result


class TestCalculateCustomerRanking:
    """Test _calculate_customer_ranking."""

    def setup_method(self):
        self.proc = ComparativeAnalyticsProcessor()

    def test_above_average_returns_75th_percentile(self):
        customer = {"profit_margin": 60.0}
        benchmark = {"profit_margin": 40.0}
        ranking, percentile = self.proc._calculate_customer_ranking(customer, benchmark)
        assert ranking is None
        assert percentile == 75.0

    def test_average_returns_50th_percentile(self):
        customer = {"profit_margin": 35.0}
        benchmark = {"profit_margin": 40.0}
        ranking, percentile = self.proc._calculate_customer_ranking(customer, benchmark)
        assert percentile == 50.0

    def test_below_average_returns_25th_percentile(self):
        customer = {"profit_margin": 10.0}
        benchmark = {"profit_margin": 40.0}
        ranking, percentile = self.proc._calculate_customer_ranking(customer, benchmark)
        assert percentile == 25.0

    def test_no_profit_margin_returns_none(self):
        customer = {"cost": 100.0}
        benchmark = {"cost": 50.0}
        ranking, percentile = self.proc._calculate_customer_ranking(customer, benchmark)
        assert ranking is None
        assert percentile is None


# ─────────────────────────────────────────────────────────────────────────────
# _fetch_period_data endpoint mapping
# ─────────────────────────────────────────────────────────────────────────────


class TestFetchPeriodData:
    """Test _fetch_period_data endpoint selection."""

    @pytest.mark.asyncio
    async def test_cost_by_provider_uses_correct_endpoint(self, proc, mock_client):
        mock_client.get = AsyncMock(return_value={"groups": []})
        await proc._fetch_period_data(
            mock_client, "team1", "SEVEN_DAYS", "cost", "provider"
        )
        call_args = mock_client.get.call_args
        assert "cost-metric-by-provider-over-time" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_cost_by_model_uses_correct_endpoint(self, proc, mock_client):
        mock_client.get = AsyncMock(return_value={"groups": []})
        await proc._fetch_period_data(
            mock_client, "team1", "SEVEN_DAYS", "cost", "model"
        )
        call_args = mock_client.get.call_args
        assert "total-cost-by-model" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_cost_by_customer_uses_organization_endpoint(self, proc, mock_client):
        mock_client.get = AsyncMock(return_value={"groups": []})
        await proc._fetch_period_data(
            mock_client, "team1", "SEVEN_DAYS", "cost", "customer"
        )
        call_args = mock_client.get.call_args
        assert "cost-metric-by-organization" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_fallback_endpoint_for_unknown_combo(self, proc, mock_client):
        """Unknown metric/breakdown combo falls back to cost by provider."""
        mock_client.get = AsyncMock(return_value={"groups": []})
        await proc._fetch_period_data(
            mock_client, "team1", "SEVEN_DAYS", "revenue", "product"
        )
        # Should not raise

    @pytest.mark.asyncio
    async def test_api_error_propagates(self, proc, mock_client):
        mock_client.get = AsyncMock(
            side_effect=ReveniumAPIError("fail", status_code=500)
        )
        with pytest.raises(ReveniumAPIError):
            await proc._fetch_period_data(
                mock_client, "team1", "SEVEN_DAYS", "cost", "provider"
            )

    @pytest.mark.asyncio
    async def test_group_parameter_passed(self, proc, mock_client):
        """Group parameter is passed for cost-by-provider endpoint."""
        mock_client.get = AsyncMock(return_value={"groups": []})
        await proc._fetch_period_data(
            mock_client, "team1", "SEVEN_DAYS", "cost", "provider", "MEAN"
        )
        call_args = mock_client.get.call_args
        assert call_args[1]["params"]["group"] == "MEAN"
