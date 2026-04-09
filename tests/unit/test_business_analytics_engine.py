"""Unit tests for BusinessAnalyticsEngine.

Tests behavioral correctness of:
- Query validation (query type, entity, period, aggregation checks)
- Capabilities retrieval (UCM integration with fallback)
- Insight generation (cost, spike, profitability, transaction-level)
- Chart data generation
- Query complexity calculation
- Cost recommendation generation
- Spike recommendation generation
- Query routing and error handling in process_analytics_query
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from dataclasses import dataclass

from src.revenium_mcp_server.analytics.business_analytics_engine import (
    AnalyticsQuery,
    AnalyticsResult,
    BusinessAnalyticsEngine,
)
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_query(
    query_type="cost_analysis",
    entities=None,
    period="SEVEN_DAYS",
    aggregation="TOTAL",
    filters=None,
    context=None,
):
    """Build a valid AnalyticsQuery with sensible defaults."""
    return AnalyticsQuery(
        query_type=query_type,
        entities=entities or ["providers"],
        time_range={"period": period},
        aggregation=aggregation,
        filters=filters,
        context=context,
    )


def _engine_no_ucm():
    """Engine without UCM — uses static fallback capabilities."""
    return BusinessAnalyticsEngine(ucm_integration=None)


# ─────────────────────────────────────────────────────────────────────────────
# _get_capabilities — UCM integration with fallback
# ─────────────────────────────────────────────────────────────────────────────


class TestGetCapabilities:
    """Tests for capability retrieval: UCM path and static fallback."""

    @pytest.mark.asyncio
    async def test_static_fallback_returns_all_query_types(self):
        """Without UCM, static capabilities include all 7 query types."""
        engine = _engine_no_ucm()
        caps = await engine._get_capabilities()
        expected_types = [
            "cost_analysis", "profitability", "comparison",
            "trend", "breakdown", "spike_investigation", "transaction_level",
        ]
        for qt in expected_types:
            assert qt in caps["query_types"], f"Missing query type: {qt}"

    @pytest.mark.asyncio
    async def test_static_fallback_returns_entity_types(self):
        """Static capabilities include entity types like providers, models, etc."""
        engine = _engine_no_ucm()
        caps = await engine._get_capabilities()
        assert "providers" in caps["entity_types"]
        assert "customers" in caps["entity_types"]
        assert "transactions" in caps["entity_types"]

    @pytest.mark.asyncio
    async def test_static_fallback_returns_periods_and_aggregations(self):
        """Static capabilities include the API-verified periods and aggregation types."""
        engine = _engine_no_ucm()
        caps = await engine._get_capabilities()
        assert "SEVEN_DAYS" in caps["supported_periods"]
        assert "TOTAL" in caps["supported_aggregations"]
        assert "MEAN" in caps["supported_aggregations"]

    @pytest.mark.asyncio
    async def test_ucm_success_uses_ucm_capabilities(self):
        """When UCM integration succeeds, its capabilities are used."""
        ucm = AsyncMock()
        ucm_caps = {"query_types": ["custom_type"], "entity_types": ["foo"]}
        ucm.get_analytics_capabilities = AsyncMock(return_value=ucm_caps)
        engine = BusinessAnalyticsEngine(ucm_integration=ucm)

        caps = await engine._get_capabilities()
        assert caps == ucm_caps

    @pytest.mark.asyncio
    async def test_ucm_failure_falls_back_to_static(self):
        """When UCM integration raises, engine falls back to static capabilities."""
        ucm = AsyncMock()
        ucm.get_analytics_capabilities = AsyncMock(side_effect=RuntimeError("UCM down"))
        engine = BusinessAnalyticsEngine(ucm_integration=ucm)

        caps = await engine._get_capabilities()
        # Should get static capabilities
        assert "cost_analysis" in caps["query_types"]

    @pytest.mark.asyncio
    async def test_ucm_failure_disables_ucm_for_subsequent_calls(self):
        """After UCM failure, subsequent calls skip UCM entirely."""
        ucm = AsyncMock()
        ucm.get_analytics_capabilities = AsyncMock(side_effect=RuntimeError("UCM down"))
        engine = BusinessAnalyticsEngine(ucm_integration=ucm)

        # First call — triggers failure
        await engine._get_capabilities()
        assert engine._ucm_failed is True
        assert engine.ucm_integration is None

        # Second call — should not attempt UCM
        caps = await engine._get_capabilities()
        assert "cost_analysis" in caps["query_types"]
        # UCM was only called once (during the first attempt)
        assert ucm.get_analytics_capabilities.call_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# _validate_query — validates query type, entities, period, aggregation
# ─────────────────────────────────────────────────────────────────────────────


class TestValidateQuery:
    """Tests for query validation logic."""

    @pytest.mark.asyncio
    async def test_valid_query_passes_validation(self):
        """A well-formed query does not raise."""
        engine = _engine_no_ucm()
        query = _make_query(query_type="cost_analysis", entities=["providers"], aggregation="TOTAL")
        # Should not raise
        await engine._validate_query(query)

    @pytest.mark.asyncio
    async def test_unsupported_query_type_raises_tool_error(self):
        """An unrecognized query_type raises ToolError with INVALID_PARAMETER."""
        engine = _engine_no_ucm()
        query = _make_query(query_type="nonexistent_type")

        with pytest.raises(ToolError) as exc_info:
            await engine._validate_query(query)
        assert exc_info.value.error_code == ErrorCodes.INVALID_PARAMETER

    @pytest.mark.asyncio
    async def test_unsupported_entity_raises_tool_error(self):
        """An unrecognized entity type raises ToolError."""
        engine = _engine_no_ucm()
        query = _make_query(entities=["unicorns"])

        with pytest.raises(ToolError) as exc_info:
            await engine._validate_query(query)
        assert exc_info.value.error_code == ErrorCodes.INVALID_PARAMETER

    @pytest.mark.asyncio
    async def test_unsupported_period_raises_tool_error(self):
        """An unrecognized time period raises ToolError."""
        engine = _engine_no_ucm()
        query = _make_query(period="ONE_MILLION_YEARS")

        with pytest.raises(ToolError) as exc_info:
            await engine._validate_query(query)
        assert exc_info.value.error_code == ErrorCodes.INVALID_PARAMETER

    @pytest.mark.asyncio
    async def test_unsupported_aggregation_raises_tool_error(self):
        """An unrecognized aggregation type raises ToolError."""
        engine = _engine_no_ucm()
        query = _make_query(aggregation="PERCENTILE_99")

        with pytest.raises(ToolError) as exc_info:
            await engine._validate_query(query)
        assert exc_info.value.error_code == ErrorCodes.INVALID_PARAMETER

    @pytest.mark.asyncio
    async def test_empty_entities_list_passes_validation(self):
        """Empty entities list is acceptable."""
        engine = _engine_no_ucm()
        query = _make_query(entities=[])
        # Should not raise
        await engine._validate_query(query)

    @pytest.mark.asyncio
    async def test_no_period_in_time_range_passes_validation(self):
        """Missing period in time_range skips period validation."""
        engine = _engine_no_ucm()
        query = AnalyticsQuery(
            query_type="cost_analysis",
            entities=["providers"],
            time_range={},  # No period key
            aggregation="TOTAL",
        )
        # Should not raise
        await engine._validate_query(query)


# ─────────────────────────────────────────────────────────────────────────────
# _generate_insights — insight generation for different query types
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateInsights:
    """Tests for insight generation based on query type and data shape."""

    def test_cost_analysis_with_dict_results(self):
        """Cost analysis with dict data generates data-point insight."""
        engine = _engine_no_ucm()
        query = _make_query(query_type="cost_analysis")
        data = {"results": [{"cost": 100}, {"cost": 200}]}
        insights = engine._generate_insights(query, data)
        assert any("2 data points" in i for i in insights)

    def test_cost_analysis_with_list_data(self):
        """Cost analysis with list data generates data-point insight from list length."""
        engine = _engine_no_ucm()
        query = _make_query(query_type="cost_analysis")
        data = [{"cost": 1}, {"cost": 2}, {"cost": 3}]
        insights = engine._generate_insights(query, data)
        assert any("3 data points" in i for i in insights)

    def test_profitability_generates_insight(self):
        """Profitability query type generates profitability insight."""
        engine = _engine_no_ucm()
        query = _make_query(query_type="profitability")
        insights = engine._generate_insights(query, {})
        assert any("Profitability" in i for i in insights)

    def test_transaction_level_with_results(self):
        """Transaction-level query with results generates success insight."""
        engine = _engine_no_ucm()
        query = _make_query(query_type="transaction_level")
        data = {"results": {"some": "data"}}
        insights = engine._generate_insights(query, data)
        assert any("Transaction-level" in i for i in insights)

    def test_unknown_query_type_returns_empty(self):
        """Query types not in the insight logic return empty insights list."""
        engine = _engine_no_ucm()
        query = _make_query(query_type="comparison")
        insights = engine._generate_insights(query, {})
        assert insights == []


# ─────────────────────────────────────────────────────────────────────────────
# _generate_chart_data
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateChartData:
    """Tests for chart data generation."""

    def test_cost_analysis_generates_line_chart(self):
        """Cost analysis query generates a line chart configuration."""
        engine = _engine_no_ucm()
        query = _make_query(query_type="cost_analysis")
        data = {"results": [{"date": "2024-01", "cost": 100}]}
        charts = engine._generate_chart_data(query, data)
        assert len(charts) == 1
        assert charts[0]["type"] == "line"
        assert charts[0]["title"] == "Cost Trends Over Time"

    def test_cost_analysis_with_list_data(self):
        """Cost analysis chart uses list data directly when data is a list."""
        engine = _engine_no_ucm()
        query = _make_query(query_type="cost_analysis")
        data = [{"date": "2024-01", "cost": 100}]
        charts = engine._generate_chart_data(query, data)
        assert charts[0]["data"] == data

    def test_non_cost_query_returns_empty_charts(self):
        """Non-cost_analysis queries return empty chart list."""
        engine = _engine_no_ucm()
        query = _make_query(query_type="profitability")
        charts = engine._generate_chart_data(query, {})
        assert charts == []


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_query_complexity
# ─────────────────────────────────────────────────────────────────────────────


class TestCalculateQueryComplexity:
    """Tests for query complexity scoring."""

    def test_simple_query(self):
        """Few entities, no filters, non-comparison type → simple."""
        engine = _engine_no_ucm()
        query = _make_query(entities=["providers"])
        assert engine._calculate_query_complexity(query) == "simple"

    def test_moderate_query(self):
        """Multiple entities push complexity to moderate."""
        engine = _engine_no_ucm()
        query = _make_query(entities=["providers", "models", "customers"])
        assert engine._calculate_query_complexity(query) == "moderate"

    def test_complex_query(self):
        """Many entities plus filters plus comparison type → complex."""
        engine = _engine_no_ucm()
        query = _make_query(
            query_type="comparison",
            entities=["providers", "models", "customers"],
            filters={"a": 1, "b": 2},
        )
        assert engine._calculate_query_complexity(query) == "complex"

    def test_comparison_type_adds_complexity(self):
        """Comparison and trend types add +2 to complexity score."""
        engine = _engine_no_ucm()
        # 2 entities + comparison(2) = 4 → moderate
        query = _make_query(query_type="comparison", entities=["providers", "models"])
        assert engine._calculate_query_complexity(query) == "moderate"

    def test_trend_type_adds_complexity(self):
        """Trend type also adds +2 complexity."""
        engine = _engine_no_ucm()
        query = _make_query(query_type="trend", entities=["providers", "models"])
        assert engine._calculate_query_complexity(query) == "moderate"


# ─────────────────────────────────────────────────────────────────────────────
# _generate_cost_insights — cost trend insight generation
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateCostInsights:
    """Tests for detailed cost insight generation from trend data."""

    @dataclass
    class FakeCostTrends:
        total_cost: float = 0.0
        trend_direction: str = "stable"
        period_over_period_change: float = 0.0
        cost_by_provider: dict = None
        cost_by_model: dict = None

        def __post_init__(self):
            if self.cost_by_provider is None:
                self.cost_by_provider = {}
            if self.cost_by_model is None:
                self.cost_by_model = {}

    @pytest.mark.asyncio
    async def test_total_cost_insight(self):
        """Positive total cost generates a cost insight with dollar amount."""
        engine = _engine_no_ucm()
        trends = self.FakeCostTrends(total_cost=1234.56)
        insights = await engine._generate_cost_insights(trends, "SEVEN_DAYS")
        assert any("$1234.56" in i for i in insights)

    @pytest.mark.asyncio
    async def test_zero_cost_no_total_insight(self):
        """Zero total cost does not generate the total-cost insight line."""
        engine = _engine_no_ucm()
        trends = self.FakeCostTrends(total_cost=0.0)
        insights = await engine._generate_cost_insights(trends, "SEVEN_DAYS")
        assert not any("Total cost" in i for i in insights)

    @pytest.mark.asyncio
    async def test_significant_increase_insight(self):
        """Increasing trend with >10% change generates increase insight."""
        engine = _engine_no_ucm()
        trends = self.FakeCostTrends(
            total_cost=500.0,
            trend_direction="increasing",
            period_over_period_change=25.0,
        )
        insights = await engine._generate_cost_insights(trends, "SEVEN_DAYS")
        assert any("increase" in i.lower() for i in insights)

    @pytest.mark.asyncio
    async def test_significant_decrease_insight(self):
        """Decreasing trend with <-10% change generates reduction insight."""
        engine = _engine_no_ucm()
        trends = self.FakeCostTrends(
            total_cost=500.0,
            trend_direction="decreasing",
            period_over_period_change=-15.0,
        )
        insights = await engine._generate_cost_insights(trends, "SEVEN_DAYS")
        assert any("reduction" in i.lower() for i in insights)

    @pytest.mark.asyncio
    async def test_stable_trend_insight(self):
        """Stable trend generates stability insight."""
        engine = _engine_no_ucm()
        trends = self.FakeCostTrends(
            total_cost=500.0,
            trend_direction="stable",
            period_over_period_change=2.0,
        )
        insights = await engine._generate_cost_insights(trends, "SEVEN_DAYS")
        assert any("stable" in i.lower() for i in insights)

    @pytest.mark.asyncio
    async def test_large_change_adds_clarification(self):
        """Period change >50% adds clarification note."""
        engine = _engine_no_ucm()
        trends = self.FakeCostTrends(
            total_cost=500.0,
            trend_direction="increasing",
            period_over_period_change=75.0,
        )
        insights = await engine._generate_cost_insights(trends, "SEVEN_DAYS")
        assert any("Note" in i for i in insights)

    @pytest.mark.asyncio
    async def test_top_provider_insight(self):
        """Provider cost data generates top-provider insight."""
        engine = _engine_no_ucm()
        trends = self.FakeCostTrends(
            total_cost=300.0,
            cost_by_provider={"OpenAI": 200.0, "Anthropic": 100.0},
        )
        insights = await engine._generate_cost_insights(trends, "SEVEN_DAYS")
        assert any("OpenAI" in i for i in insights)

    @pytest.mark.asyncio
    async def test_top_model_insight(self):
        """Model cost data generates most-expensive-model insight."""
        engine = _engine_no_ucm()
        trends = self.FakeCostTrends(
            total_cost=500.0,
            cost_by_model={"gpt-4o": 400.0, "gpt-3.5-turbo": 100.0},
        )
        insights = await engine._generate_cost_insights(trends, "SEVEN_DAYS")
        assert any("gpt-4o" in i for i in insights)


# ─────────────────────────────────────────────────────────────────────────────
# _generate_cost_recommendations
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateCostRecommendations:
    """Tests for cost optimization recommendation generation."""

    @dataclass
    class FakeCostTrends:
        trend_direction: str = "stable"
        period_over_period_change: float = 0.0
        cost_by_provider: dict = None
        cost_by_model: dict = None

        def __post_init__(self):
            if self.cost_by_provider is None:
                self.cost_by_provider = {}
            if self.cost_by_model is None:
                self.cost_by_model = {}

    @pytest.mark.asyncio
    async def test_large_increase_generates_cost_control_recommendations(self):
        """Increasing trend >20% generates urgent recommendations."""
        engine = _engine_no_ucm()
        trends = self.FakeCostTrends(
            trend_direction="increasing", period_over_period_change=25.0
        )
        recs = await engine._generate_cost_recommendations(trends, "SEVEN_DAYS")
        assert any("cost controls" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_provider_concentration_recommendation(self):
        """When top provider costs 2x+ the second, diversification is recommended."""
        engine = _engine_no_ucm()
        trends = self.FakeCostTrends(
            cost_by_provider={"OpenAI": 500.0, "Anthropic": 100.0}
        )
        recs = await engine._generate_cost_recommendations(trends, "SEVEN_DAYS")
        assert any("diversif" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_expensive_models_recommendation(self):
        """Models costing >$100 trigger review recommendation."""
        engine = _engine_no_ucm()
        trends = self.FakeCostTrends(
            cost_by_model={"gpt-4o": 200.0, "gpt-3.5-turbo": 50.0}
        )
        recs = await engine._generate_cost_recommendations(trends, "SEVEN_DAYS")
        assert any("high-cost models" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_short_period_recommendation(self):
        """ONE_DAY period triggers longer-period recommendation."""
        engine = _engine_no_ucm()
        trends = self.FakeCostTrends()
        recs = await engine._generate_cost_recommendations(trends, "ONE_DAY")
        assert any("longer periods" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_healthy_trends_default_recommendation(self):
        """No issues → healthy trends recommendation."""
        engine = _engine_no_ucm()
        trends = self.FakeCostTrends()
        recs = await engine._generate_cost_recommendations(trends, "SEVEN_DAYS")
        assert any("healthy" in r.lower() for r in recs)


# ─────────────────────────────────────────────────────────────────────────────
# _generate_spike_insights
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateSpikeInsights:
    """Tests for spike investigation insight generation."""

    @pytest.mark.asyncio
    async def test_spike_with_contributors(self):
        """Spike with contributors generates contributor count and driver insights."""
        engine = _engine_no_ucm()
        spike = {
            "contributors": [
                {"name": "OpenAI", "type": "provider", "spike_cost": 500.0,
                 "baseline_cost": 200.0, "increase": 300.0, "percentage_increase": 150.0}
            ],
            "analysis_threshold": 100.0,
            "baseline_comparison": {"total": 200.0},
        }
        insights = await engine._generate_spike_insights(spike, "SEVEN_DAYS")
        assert any("1 spike contributor" in i for i in insights)
        assert any("OpenAI" in i for i in insights)

    @pytest.mark.asyncio
    async def test_spike_with_unified_calculation(self):
        """When unified fix is applied, insights use UNIFIED CALCULATION label."""
        engine = _engine_no_ucm()
        spike = {
            "contributors": [
                {"name": "OpenAI", "type": "provider", "spike_cost": 500.0,
                 "baseline_cost": 200.0, "increase": 300.0}
            ],
            "analysis_threshold": 100.0,
            "unified_percentage_change": 75.0,
            "_debug_unified_fix_applied": True,
        }
        insights = await engine._generate_spike_insights(spike, "SEVEN_DAYS")
        assert any("UNIFIED CALCULATION" in i for i in insights)

    @pytest.mark.asyncio
    async def test_spike_no_contributors(self):
        """Spike with no contributors generates 'no significant' message."""
        engine = _engine_no_ucm()
        spike = {"contributors": [], "analysis_threshold": 100.0}
        insights = await engine._generate_spike_insights(spike, "SEVEN_DAYS")
        assert any("No significant" in i for i in insights)

    @pytest.mark.asyncio
    async def test_spike_contributor_types(self):
        """Multiple contributor types generate type-specific insights."""
        engine = _engine_no_ucm()
        spike = {
            "contributors": [
                {"name": "OpenAI", "type": "provider", "spike_cost": 500.0,
                 "baseline_cost": 200.0, "increase": 300.0, "percentage_increase": 150.0},
                {"name": "gpt-4o", "type": "model", "spike_cost": 400.0,
                 "baseline_cost": 100.0, "increase": 300.0, "percentage_increase": 300.0},
                {"name": "AcmeCorp", "type": "customer", "spike_cost": 300.0,
                 "baseline_cost": 100.0, "increase": 200.0, "percentage_increase": 200.0},
            ],
            "analysis_threshold": 100.0,
        }
        insights = await engine._generate_spike_insights(spike, "SEVEN_DAYS")
        assert any("provider" in i for i in insights)
        assert any("model" in i for i in insights)
        assert any("customer" in i for i in insights)

    @pytest.mark.asyncio
    async def test_spike_insights_error_resilience(self):
        """Malformed spike data does not crash — returns limited insights."""
        engine = _engine_no_ucm()
        spike = None  # Will cause attribute error on .get()
        # The method wraps errors in try/except
        insights = await engine._generate_spike_insights(spike, "SEVEN_DAYS")
        assert any("limited insights" in i.lower() for i in insights)


# ─────────────────────────────────────────────────────────────────────────────
# _generate_spike_recommendations
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateSpikeRecommendations:
    """Tests for spike recommendation generation."""

    @pytest.mark.asyncio
    async def test_significant_spike_triggers_alert_recommendations(self):
        """Increase >$100 triggers alert setup recommendations."""
        engine = _engine_no_ucm()
        spike = {
            "contributors": [
                {"name": "OpenAI", "type": "provider", "spike_cost": 500.0,
                 "baseline_cost": 200.0, "increase": 150.0}
            ],
            "analysis_threshold": 100.0,
        }
        recs = await engine._generate_spike_recommendations(spike, "SEVEN_DAYS")
        assert any("alert" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_spike_above_double_threshold_triggers_budget_alert(self):
        """Spike cost > 2x threshold triggers budget alert recommendation."""
        engine = _engine_no_ucm()
        spike = {
            "contributors": [
                {"name": "OpenAI", "type": "provider", "spike_cost": 250.0,
                 "baseline_cost": 50.0, "increase": 200.0}
            ],
            "analysis_threshold": 100.0,
        }
        recs = await engine._generate_spike_recommendations(spike, "SEVEN_DAYS")
        assert any("budget" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_no_contributors_recommendations(self):
        """No contributors → no immediate action recommendation."""
        engine = _engine_no_ucm()
        spike = {"contributors": [], "analysis_threshold": 100.0}
        recs = await engine._generate_spike_recommendations(spike, "SEVEN_DAYS")
        assert any("no immediate action" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_provider_contributor_generates_investigation_rec(self):
        """Provider contributor triggers provider-specific investigation."""
        engine = _engine_no_ucm()
        spike = {
            "contributors": [
                {"name": "OpenAI", "type": "provider", "spike_cost": 500.0,
                 "baseline_cost": 200.0, "increase": 150.0}
            ],
            "analysis_threshold": 100.0,
        }
        recs = await engine._generate_spike_recommendations(spike, "SEVEN_DAYS")
        assert any("OpenAI" in r for r in recs)


# ─────────────────────────────────────────────────────────────────────────────
# process_analytics_query — routing, error handling, result structure
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessAnalyticsQuery:
    """Tests for the main query processing entry point."""

    @pytest.mark.asyncio
    async def test_unsupported_query_type_raises(self):
        """Unsupported query type raises ToolError with suggestions."""
        engine = _engine_no_ucm()
        client = MagicMock()
        query = _make_query(query_type="invalid_type")

        with pytest.raises(ToolError) as exc_info:
            await engine.process_analytics_query(client, query)
        assert "Unsupported query type" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_trend_query_returns_result(self):
        """Trend query type returns an AnalyticsResult (placeholder implementation)."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="trend")

        result = await engine.process_analytics_query(client, query)
        assert isinstance(result, AnalyticsResult)
        assert result.query == query
        assert result.data["query_type"] == "trend"

    @pytest.mark.asyncio
    async def test_api_error_wraps_in_tool_error(self):
        """ReveniumAPIError during processing is wrapped in ToolError."""
        from src.revenium_mcp_server.client import ReveniumAPIError

        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="cost_analysis")

        with patch(
            "src.revenium_mcp_server.analytics.business_analytics_engine.BusinessAnalyticsEngine._process_cost_analysis",
            new_callable=AsyncMock,
            side_effect=ReveniumAPIError("API failure", 500),
        ):
            with pytest.raises(ToolError) as exc_info:
                await engine.process_analytics_query(client, query)
            assert exc_info.value.error_code == ErrorCodes.API_ERROR

    @pytest.mark.asyncio
    async def test_unexpected_error_wraps_in_tool_error(self):
        """Unexpected exceptions during processing are wrapped in ToolError."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="cost_analysis")

        with patch(
            "src.revenium_mcp_server.analytics.business_analytics_engine.BusinessAnalyticsEngine._process_cost_analysis",
            new_callable=AsyncMock,
            side_effect=ValueError("something broke"),
        ):
            with pytest.raises(ToolError) as exc_info:
                await engine.process_analytics_query(client, query)
            assert exc_info.value.error_code == ErrorCodes.PROCESSING_ERROR

    @pytest.mark.asyncio
    async def test_tool_error_re_raised_unchanged(self):
        """ToolError during processing is re-raised without modification."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="cost_analysis")
        original_error = ToolError(
            message="custom validation error",
            error_code=ErrorCodes.INVALID_PARAMETER,
        )

        with patch(
            "src.revenium_mcp_server.analytics.business_analytics_engine.BusinessAnalyticsEngine._process_cost_analysis",
            new_callable=AsyncMock,
            side_effect=original_error,
        ):
            with pytest.raises(ToolError) as exc_info:
                await engine.process_analytics_query(client, query)
            assert exc_info.value is original_error

    @pytest.mark.asyncio
    async def test_result_metadata_structure(self):
        """Successful result has expected metadata fields."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="trend")

        result = await engine.process_analytics_query(client, query)
        assert "processing_time" in result.metadata
        assert "data_points" in result.metadata
        assert "query_complexity" in result.metadata
        assert "api_calls_made" in result.metadata
        assert isinstance(result.timestamp, datetime)

    @pytest.mark.asyncio
    async def test_list_data_result_metadata(self):
        """When processor returns list data, metadata handles it correctly."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="cost_analysis")

        with patch(
            "src.revenium_mcp_server.analytics.business_analytics_engine.BusinessAnalyticsEngine._process_cost_analysis",
            new_callable=AsyncMock,
            return_value=[{"cost": 100}, {"cost": 200}],
        ):
            result = await engine.process_analytics_query(client, query)
            assert result.metadata["data_points"] == 2
            assert result.metadata["api_calls_made"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# _generate_profitability_insights
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateProfitabilityInsights:
    """Tests for profitability insight generation."""

    @dataclass
    class FakeProfData:
        total_revenue: float = 0.0
        total_cost: float = 0.0
        net_profit: float = 0.0
        profit_margin: float = 0.0
        profitability_by_customer: dict = None
        profitability_by_product: dict = None

        def __post_init__(self):
            if self.profitability_by_customer is None:
                self.profitability_by_customer = {}
            if self.profitability_by_product is None:
                self.profitability_by_product = {}

    @pytest.mark.asyncio
    async def test_excellent_margin_insight(self):
        """Profit margin >20% generates excellent insight."""
        engine = _engine_no_ucm()
        data = self.FakeProfData(
            total_revenue=1000.0, total_cost=700.0,
            net_profit=300.0, profit_margin=30.0,
        )
        insights = await engine._generate_profitability_insights(data, "SEVEN_DAYS")
        assert any("Excellent" in i for i in insights)

    @pytest.mark.asyncio
    async def test_good_margin_insight(self):
        """Profit margin 10-20% generates good insight."""
        engine = _engine_no_ucm()
        data = self.FakeProfData(profit_margin=15.0)
        insights = await engine._generate_profitability_insights(data, "SEVEN_DAYS")
        assert any("Good" in i for i in insights)

    @pytest.mark.asyncio
    async def test_low_margin_insight(self):
        """Profit margin 0-10% generates low-margin insight."""
        engine = _engine_no_ucm()
        data = self.FakeProfData(profit_margin=5.0)
        insights = await engine._generate_profitability_insights(data, "SEVEN_DAYS")
        assert any("Low profit margin" in i for i in insights)

    @pytest.mark.asyncio
    async def test_negative_margin_insight(self):
        """Negative profit margin generates attention-required insight."""
        engine = _engine_no_ucm()
        data = self.FakeProfData(profit_margin=-5.0)
        insights = await engine._generate_profitability_insights(data, "SEVEN_DAYS")
        assert any("Negative" in i for i in insights)

    @pytest.mark.asyncio
    async def test_customer_profitability_insights(self):
        """Customer profitability data generates customer-specific insights."""
        engine = _engine_no_ucm()
        data = self.FakeProfData(
            profit_margin=20.0,
            profitability_by_customer={
                "AcmeCorp": {"profit": 100.0},
                "BigLoss": {"profit": -50.0},
            },
        )
        insights = await engine._generate_profitability_insights(data, "SEVEN_DAYS")
        assert any("1 profitable" in i for i in insights)
        assert any("AcmeCorp" in i for i in insights)

    @pytest.mark.asyncio
    async def test_product_profitability_insights(self):
        """Product profitability data generates product-specific insights."""
        engine = _engine_no_ucm()
        data = self.FakeProfData(
            profit_margin=20.0,
            profitability_by_product={
                "Premium": {"profit": 200.0},
                "Basic": {"profit": -10.0},
            },
        )
        insights = await engine._generate_profitability_insights(data, "SEVEN_DAYS")
        assert any("1 profitable product" in i for i in insights)
        assert any("Premium" in i for i in insights)

    @pytest.mark.asyncio
    async def test_revenue_and_cost_displayed(self):
        """Revenue and cost values appear in insights."""
        engine = _engine_no_ucm()
        data = self.FakeProfData(total_revenue=1000.0, total_cost=800.0)
        insights = await engine._generate_profitability_insights(data, "SEVEN_DAYS")
        assert any("Revenue" in i for i in insights)
        assert any("Cost" in i for i in insights)


# ─────────────────────────────────────────────────────────────────────────────
# _generate_profitability_recommendations
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateProfitabilityRecommendations:
    """Tests for profitability recommendation generation."""

    @dataclass
    class FakeProfData:
        profit_margin: float = 0.0
        profitability_by_customer: dict = None
        profitability_by_product: dict = None

        def __post_init__(self):
            if self.profitability_by_customer is None:
                self.profitability_by_customer = {}
            if self.profitability_by_product is None:
                self.profitability_by_product = {}

    @pytest.mark.asyncio
    async def test_critical_margin_recommendations(self):
        """Margin <5% generates critical cost-reduction recommendations."""
        engine = _engine_no_ucm()
        data = self.FakeProfData(profit_margin=3.0)
        recs = await engine._generate_profitability_recommendations(data, "SEVEN_DAYS")
        assert any("Critical" in r for r in recs)

    @pytest.mark.asyncio
    async def test_moderate_margin_recommendations(self):
        """Margin 5-15% generates focus recommendations."""
        engine = _engine_no_ucm()
        data = self.FakeProfData(profit_margin=10.0)
        recs = await engine._generate_profitability_recommendations(data, "SEVEN_DAYS")
        assert any("Opportunity" in r for r in recs)

    @pytest.mark.asyncio
    async def test_strong_margin_recommendations(self):
        """Margin >15% generates scaling recommendations."""
        engine = _engine_no_ucm()
        data = self.FakeProfData(profit_margin=25.0)
        recs = await engine._generate_profitability_recommendations(data, "SEVEN_DAYS")
        assert any("Strong profitability" in r for r in recs)

    @pytest.mark.asyncio
    async def test_unprofitable_customers_recommendation(self):
        """Unprofitable customers trigger pricing review recommendation."""
        engine = _engine_no_ucm()
        data = self.FakeProfData(
            profit_margin=10.0,
            profitability_by_customer={"BadCorp": {"profit": -100.0}},
        )
        recs = await engine._generate_profitability_recommendations(data, "SEVEN_DAYS")
        assert any("unprofitable customer" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_unprofitable_products_recommendation(self):
        """Unprofitable products trigger evaluation recommendation."""
        engine = _engine_no_ucm()
        data = self.FakeProfData(
            profit_margin=10.0,
            profitability_by_product={"LossProduct": {"profit": -50.0}},
        )
        recs = await engine._generate_profitability_recommendations(data, "SEVEN_DAYS")
        assert any("unprofitable product" in r.lower() for r in recs)


# ─────────────────────────────────────────────────────────────────────────────
# _generate_breakdown_insights and _generate_breakdown_recommendations
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateBreakdownInsights:
    """Tests for breakdown insight generation."""

    @pytest.mark.asyncio
    async def test_model_breakdown_insights(self):
        """Model breakdown generates model-specific insights."""
        engine = _engine_no_ucm()
        data = {"cost_by_model": {"gpt-4o": 200.0, "gpt-3.5": 50.0}}
        insights = await engine._generate_breakdown_insights(data, "SEVEN_DAYS")
        assert any("2 models" in i for i in insights)
        assert any("gpt-4o" in i for i in insights)

    @pytest.mark.asyncio
    async def test_provider_breakdown_insights(self):
        """Provider breakdown generates provider-specific insights."""
        engine = _engine_no_ucm()
        data = {"cost_by_provider": {"OpenAI": 300.0, "Anthropic": 100.0}}
        insights = await engine._generate_breakdown_insights(data, "SEVEN_DAYS")
        assert any("2 providers" in i for i in insights)
        assert any("OpenAI" in i for i in insights)

    @pytest.mark.asyncio
    async def test_customer_breakdown_insights(self):
        """Customer breakdown generates customer-specific insights."""
        engine = _engine_no_ucm()
        data = {"cost_by_customer": {"AcmeCorp": 150.0}}
        insights = await engine._generate_breakdown_insights(data, "SEVEN_DAYS")
        assert any("1 customer" in i for i in insights)
        assert any("AcmeCorp" in i for i in insights)

    @pytest.mark.asyncio
    async def test_product_breakdown_insights(self):
        """Product breakdown generates product-specific insights."""
        engine = _engine_no_ucm()
        data = {"cost_by_product": {"API-Pro": 120.0}}
        insights = await engine._generate_breakdown_insights(data, "SEVEN_DAYS")
        assert any("1 product" in i for i in insights)

    @pytest.mark.asyncio
    async def test_task_breakdown_insights(self):
        """Task breakdown generates task-specific insights."""
        engine = _engine_no_ucm()
        data = {"cost_by_task": {"inference": 80.0, "training": 120.0}}
        insights = await engine._generate_breakdown_insights(data, "SEVEN_DAYS")
        assert any("2 task types" in i for i in insights)

    @pytest.mark.asyncio
    async def test_agent_breakdown_insights(self):
        """Agent breakdown (list format) generates agent-specific insights."""
        engine = _engine_no_ucm()
        data = {"cost_by_agent": [
            {"name": "Agent1", "cost": 50.0},
            {"name": "Agent2", "cost": 15.0},
        ]}
        insights = await engine._generate_breakdown_insights(data, "SEVEN_DAYS")
        assert any("2 agents" in i for i in insights)

    @pytest.mark.asyncio
    async def test_expensive_models_in_breakdown(self):
        """Models costing >$100 are called out."""
        engine = _engine_no_ucm()
        data = {"cost_by_model": {"gpt-4o": 200.0, "gpt-3.5": 50.0}}
        insights = await engine._generate_breakdown_insights(data, "SEVEN_DAYS")
        assert any("costs >$100" in i for i in insights)

    @pytest.mark.asyncio
    async def test_empty_breakdown_fallback(self):
        """Empty breakdown data generates fallback insight."""
        engine = _engine_no_ucm()
        insights = await engine._generate_breakdown_insights({}, "SEVEN_DAYS")
        assert any("completed successfully" in i.lower() for i in insights)


class TestGenerateBreakdownRecommendations:
    """Tests for breakdown recommendation generation."""

    @pytest.mark.asyncio
    async def test_model_cost_dominance_recommendation(self):
        """Model dominating >50% of cost triggers recommendation."""
        engine = _engine_no_ucm()
        data = {"cost_by_model": {"gpt-4o": 800.0, "gpt-3.5": 200.0}}
        recs = await engine._generate_breakdown_recommendations(data, "SEVEN_DAYS")
        assert any("gpt-4o" in r for r in recs)

    @pytest.mark.asyncio
    async def test_provider_concentration_recommendation(self):
        """Provider >80% concentration triggers diversification recommendation."""
        engine = _engine_no_ucm()
        data = {"cost_by_provider": {"OpenAI": 900.0, "Anthropic": 100.0}}
        recs = await engine._generate_breakdown_recommendations(data, "SEVEN_DAYS")
        assert any("diversif" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_customer_high_usage_recommendation(self):
        """Customer >$100 triggers volume discount recommendation."""
        engine = _engine_no_ucm()
        data = {"cost_by_customer": {"BigCorp": 500.0}}
        recs = await engine._generate_breakdown_recommendations(data, "SEVEN_DAYS")
        assert any("BigCorp" in r for r in recs)

    @pytest.mark.asyncio
    async def test_product_high_cost_recommendation(self):
        """Product >$200 triggers cost review recommendation."""
        engine = _engine_no_ucm()
        data = {"cost_by_product": {"ExpensiveAPI": 300.0}}
        recs = await engine._generate_breakdown_recommendations(data, "SEVEN_DAYS")
        assert any("ExpensiveAPI" in r for r in recs)

    @pytest.mark.asyncio
    async def test_task_high_cost_recommendation(self):
        """Task >$50 triggers optimization recommendation."""
        engine = _engine_no_ucm()
        data = {"cost_by_task": {"inference": 80.0}}
        recs = await engine._generate_breakdown_recommendations(data, "SEVEN_DAYS")
        assert any("inference" in r for r in recs)

    @pytest.mark.asyncio
    async def test_multiple_providers_rate_comparison(self):
        """3+ providers triggers rate comparison recommendation."""
        engine = _engine_no_ucm()
        data = {"cost_by_provider": {"A": 100.0, "B": 80.0, "C": 60.0}}
        recs = await engine._generate_breakdown_recommendations(data, "SEVEN_DAYS")
        assert any("Compare provider rates" in r for r in recs)

    @pytest.mark.asyncio
    async def test_empty_breakdown_fallback(self):
        """Empty breakdown generates balanced distribution recommendation."""
        engine = _engine_no_ucm()
        recs = await engine._generate_breakdown_recommendations({}, "SEVEN_DAYS")
        assert any("balanced distribution" in r.lower() for r in recs)


# ─────────────────────────────────────────────────────────────────────────────
# _generate_transaction_level_insights and recommendations
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateTransactionLevelInsights:
    """Tests for transaction-level insight generation."""

    @dataclass
    class FakeTransactionData:
        total_cost: float = 0.0
        average_cost_per_transaction: float = 0.0
        cost_by_provider: dict = None
        cost_by_model: dict = None
        performance_metrics: dict = None

        def __post_init__(self):
            if self.cost_by_provider is None:
                self.cost_by_provider = {}
            if self.cost_by_model is None:
                self.cost_by_model = {}
            if self.performance_metrics is None:
                self.performance_metrics = {}

    @pytest.mark.asyncio
    async def test_cost_insights_generated(self):
        """Positive total cost generates cost insights."""
        engine = _engine_no_ucm()
        data = self.FakeTransactionData(total_cost=500.0, average_cost_per_transaction=0.05)
        insights = await engine._generate_transaction_level_insights(data, "SEVEN_DAYS")
        assert any("$500.00" in i for i in insights)
        assert any("Average cost" in i for i in insights)

    @pytest.mark.asyncio
    async def test_zero_cost_no_cost_insights(self):
        """Zero cost does not generate cost-specific insights."""
        engine = _engine_no_ucm()
        data = self.FakeTransactionData(total_cost=0.0)
        insights = await engine._generate_transaction_level_insights(data, "SEVEN_DAYS")
        assert not any("Total transaction costs" in i for i in insights)

    @pytest.mark.asyncio
    async def test_provider_insights(self):
        """Provider data generates provider insight."""
        engine = _engine_no_ucm()
        data = self.FakeTransactionData(
            total_cost=300.0,
            cost_by_provider={"OpenAI": 200.0, "Anthropic": 100.0},
        )
        insights = await engine._generate_transaction_level_insights(data, "SEVEN_DAYS")
        assert any("OpenAI" in i for i in insights)

    @pytest.mark.asyncio
    async def test_model_insights(self):
        """Model data generates model insight."""
        engine = _engine_no_ucm()
        data = self.FakeTransactionData(
            total_cost=300.0,
            cost_by_model={"gpt-4o": 250.0, "gpt-3.5": 50.0},
        )
        insights = await engine._generate_transaction_level_insights(data, "SEVEN_DAYS")
        assert any("gpt-4o" in i for i in insights)

    @pytest.mark.asyncio
    async def test_performance_metrics_insights(self):
        """Performance metrics generate throughput and cost-per-transaction insights."""
        engine = _engine_no_ucm()
        data = self.FakeTransactionData(
            total_cost=100.0,
            performance_metrics={
                "OpenAI": {"tokens_per_minute": 5000.0, "avg_cost_per_transaction": 0.002},
            },
        )
        insights = await engine._generate_transaction_level_insights(data, "SEVEN_DAYS")
        assert any("tokens/min" in i for i in insights)
        assert any("avg cost" in i.lower() for i in insights)

    @pytest.mark.asyncio
    async def test_multiple_providers_distribution_insight(self):
        """Multiple providers generate distribution insight."""
        engine = _engine_no_ucm()
        data = self.FakeTransactionData(
            total_cost=300.0,
            cost_by_provider={"OpenAI": 200.0, "Anthropic": 100.0},
        )
        insights = await engine._generate_transaction_level_insights(data, "SEVEN_DAYS")
        assert any("2 providers" in i for i in insights)

    @pytest.mark.asyncio
    async def test_error_resilience(self):
        """Malformed data does not crash — returns fallback insight."""
        engine = _engine_no_ucm()
        # None will cause getattr to return defaults, no crash
        insights = await engine._generate_transaction_level_insights(None, "SEVEN_DAYS")
        # Should not raise; returns empty or minimal insights (all items must be strings)
        assert isinstance(insights, list)
        assert all(isinstance(item, str) for item in insights)


# ─────────────────────────────────────────────────────────────────────────────
# _generate_transaction_level_recommendations
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateTransactionLevelRecommendations:
    """Tests for transaction-level recommendation generation."""

    @dataclass
    class FakeTransactionData:
        total_cost: float = 0.0
        average_cost_per_transaction: float = 0.0
        cost_by_provider: dict = None
        cost_by_model: dict = None
        performance_metrics: dict = None

        def __post_init__(self):
            if self.cost_by_provider is None:
                self.cost_by_provider = {}
            if self.cost_by_model is None:
                self.cost_by_model = {}
            if self.performance_metrics is None:
                self.performance_metrics = {}

    @pytest.mark.asyncio
    async def test_provider_cost_difference_recommendation(self):
        """Significant cost difference between providers triggers recommendation."""
        engine = _engine_no_ucm()
        data = self.FakeTransactionData(
            cost_by_provider={"OpenAI": 200.0, "Anthropic": 50.0},
        )
        recs = await engine._generate_transaction_level_recommendations(data, "SEVEN_DAYS")
        assert any("OpenAI" in r for r in recs)

    @pytest.mark.asyncio
    async def test_low_throughput_recommendation(self):
        """Low throughput provider triggers optimization recommendation."""
        engine = _engine_no_ucm()
        data = self.FakeTransactionData(
            performance_metrics={"SlowProvider": {"tokens_per_minute": 50.0}},
        )
        recs = await engine._generate_transaction_level_recommendations(data, "SEVEN_DAYS")
        assert any("throughput" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_high_cost_per_transaction_recommendation(self):
        """High avg cost per transaction triggers batch processing recommendation."""
        engine = _engine_no_ucm()
        data = self.FakeTransactionData(average_cost_per_transaction=0.05)
        recs = await engine._generate_transaction_level_recommendations(data, "SEVEN_DAYS")
        assert any("batch processing" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_model_cost_recommendation(self):
        """Multiple models generate top-model cost recommendation."""
        engine = _engine_no_ucm()
        data = self.FakeTransactionData(
            cost_by_model={"gpt-4o": 300.0, "gpt-3.5": 50.0},
        )
        recs = await engine._generate_transaction_level_recommendations(data, "SEVEN_DAYS")
        assert any("gpt-4o" in r for r in recs)

    @pytest.mark.asyncio
    async def test_general_recommendations_always_present(self):
        """General monitoring recommendations are always included."""
        engine = _engine_no_ucm()
        data = self.FakeTransactionData()
        recs = await engine._generate_transaction_level_recommendations(data, "SEVEN_DAYS")
        assert any("Monitor" in r for r in recs)


# ─────────────────────────────────────────────────────────────────────────────
# _generate_customer_analytics_insights and recommendations
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateCustomerAnalyticsInsights:
    """Tests for customer analytics insight generation."""

    @pytest.mark.asyncio
    async def test_customer_count_insight(self):
        """Customer data generates organization count insight."""
        engine = _engine_no_ucm()
        data = {
            "organizations": {"Acme": {}, "BigCo": {}},
            "total_cost": 500.0,
            "total_revenue": 1000.0,
        }
        insights = await engine._generate_customer_analytics_insights(data, "SEVEN_DAYS")
        assert any("2 customer" in i for i in insights)

    @pytest.mark.asyncio
    async def test_customer_cost_and_revenue_insights(self):
        """Cost and revenue generate dollar-amount insights."""
        engine = _engine_no_ucm()
        data = {
            "organizations": {"Acme": {}},
            "total_cost": 500.0,
            "total_revenue": 1000.0,
        }
        insights = await engine._generate_customer_analytics_insights(data, "SEVEN_DAYS")
        assert any("$500.00" in i for i in insights)
        assert any("$1,000.00" in i or "$1000.00" in i for i in insights)

    @pytest.mark.asyncio
    async def test_customer_profitability_insights(self):
        """Customer profitability data generates profitable/unprofitable count."""
        engine = _engine_no_ucm()
        data = {
            "organizations": {"Acme": {}, "BadCo": {}},
            "total_cost": 0.0,
            "total_revenue": 0.0,
            "customer_profitability": {
                "Acme": {"profit": 100.0},
                "BadCo": {"profit": -50.0},
            },
        }
        insights = await engine._generate_customer_analytics_insights(data, "SEVEN_DAYS")
        assert any("1/2" in i for i in insights)
        assert any("Acme" in i for i in insights)

    @pytest.mark.asyncio
    async def test_overall_margin_insight(self):
        """Overall margin generates margin insight."""
        engine = _engine_no_ucm()
        data = {
            "organizations": {"Acme": {}},
            "total_cost": 0.0,
            "total_revenue": 0.0,
            "period_analysis": {"overall_margin": 15.5},
        }
        insights = await engine._generate_customer_analytics_insights(data, "SEVEN_DAYS")
        assert any("15.5%" in i for i in insights)

    @pytest.mark.asyncio
    async def test_empty_organizations_no_crash(self):
        """Empty organizations dict does not crash."""
        engine = _engine_no_ucm()
        data = {"organizations": {}, "total_cost": 0.0, "total_revenue": 0.0}
        insights = await engine._generate_customer_analytics_insights(data, "SEVEN_DAYS")
        # Empty organizations must not crash and must return a list of strings
        assert isinstance(insights, list)
        assert all(isinstance(item, str) for item in insights)


class TestGenerateCustomerAnalyticsRecommendations:
    """Tests for customer analytics recommendation generation."""

    @pytest.mark.asyncio
    async def test_unprofitable_customers_recommendation(self):
        """Unprofitable customers trigger pricing review recommendation."""
        engine = _engine_no_ucm()
        data = {
            "customer_profitability": {
                "BadCo": {"profit": -100.0, "margin": 5.0, "revenue": 200.0},
            },
            "period_analysis": {"overall_margin": 5.0},
        }
        recs = await engine._generate_customer_analytics_recommendations(data, "SEVEN_DAYS")
        assert any("unprofitable" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_high_margin_customers_recommendation(self):
        """High-margin customers trigger expansion recommendation."""
        engine = _engine_no_ucm()
        data = {
            "customer_profitability": {
                "GoldCo": {"profit": 500.0, "margin": 30.0, "revenue": 1000.0},
            },
            "period_analysis": {"overall_margin": 20.0},
        }
        recs = await engine._generate_customer_analytics_recommendations(data, "SEVEN_DAYS")
        assert any(">20% margins" in r for r in recs)

    @pytest.mark.asyncio
    async def test_revenue_concentration_recommendation(self):
        """Revenue concentration >50% triggers diversification recommendation."""
        engine = _engine_no_ucm()
        data = {
            "customer_profitability": {
                "BigCo": {"profit": 500.0, "margin": 20.0, "revenue": 800.0},
                "SmallCo": {"profit": 50.0, "margin": 10.0, "revenue": 100.0},
            },
            "period_analysis": {"overall_margin": 20.0},
        }
        recs = await engine._generate_customer_analytics_recommendations(data, "SEVEN_DAYS")
        assert any("diversif" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_low_overall_margin_recommendation(self):
        """Low overall margin triggers pricing review recommendation."""
        engine = _engine_no_ucm()
        data = {
            "customer_profitability": {},
            "period_analysis": {"overall_margin": 5.0},
        }
        recs = await engine._generate_customer_analytics_recommendations(data, "SEVEN_DAYS")
        assert any("margin" in r.lower() and "low" in r.lower() for r in recs)


# ─────────────────────────────────────────────────────────────────────────────
# _generate_product/agent/task analytics insights and recommendations
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateProductAnalyticsInsights:
    """Tests for product analytics insight generation."""

    @pytest.mark.asyncio
    async def test_product_count_and_cost_insights(self):
        """Product data generates count and cost insights."""
        engine = _engine_no_ucm()
        data = {
            "products": {"API-Pro": {}, "API-Basic": {}},
            "total_cost": 300.0,
            "total_revenue": 600.0,
        }
        insights = await engine._generate_product_analytics_insights(data, "SEVEN_DAYS")
        assert any("2 products" in i for i in insights)
        assert any("$300.00" in i for i in insights)

    @pytest.mark.asyncio
    async def test_product_profitability_insights(self):
        """Product profitability data generates profitable/unprofitable count."""
        engine = _engine_no_ucm()
        data = {
            "products": {"A": {}},
            "total_cost": 0.0,
            "total_revenue": 0.0,
            "product_profitability": {
                "A": {"profit": 100.0},
            },
        }
        insights = await engine._generate_product_analytics_insights(data, "SEVEN_DAYS")
        assert any("1/1" in i for i in insights)

    @pytest.mark.asyncio
    async def test_empty_products_no_crash(self):
        """Empty products dict does not crash."""
        engine = _engine_no_ucm()
        insights = await engine._generate_product_analytics_insights({}, "SEVEN_DAYS")
        assert isinstance(insights, list)
        assert all(isinstance(item, str) for item in insights)


class TestGenerateProductAnalyticsRecommendations:
    """Tests for product analytics recommendation generation."""

    @pytest.mark.asyncio
    async def test_unprofitable_products_recommendation(self):
        """Unprofitable products trigger discontinuation recommendation."""
        engine = _engine_no_ucm()
        data = {
            "product_profitability": {"LossProduct": {"profit": -100.0, "revenue": 200.0}},
            "period_analysis": {"overall_margin": 5.0},
        }
        recs = await engine._generate_product_analytics_recommendations(data, "SEVEN_DAYS")
        assert any("unprofitable" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_high_margin_products_recommendation(self):
        """High-margin products trigger promotion recommendation."""
        engine = _engine_no_ucm()
        data = {
            "product_profitability": {"GoldProduct": {"profit": 500.0, "margin": 30.0, "revenue": 1000.0}},
            "period_analysis": {"overall_margin": 20.0},
        }
        recs = await engine._generate_product_analytics_recommendations(data, "SEVEN_DAYS")
        assert any(">20% margins" in r for r in recs)

    @pytest.mark.asyncio
    async def test_low_overall_margin_recommendation(self):
        """Low overall product margin triggers pricing review."""
        engine = _engine_no_ucm()
        data = {
            "product_profitability": {},
            "period_analysis": {"overall_margin": 5.0},
        }
        recs = await engine._generate_product_analytics_recommendations(data, "SEVEN_DAYS")
        assert any("margin" in r.lower() and "low" in r.lower() for r in recs)


class TestGenerateAgentAnalyticsInsights:
    """Tests for agent analytics insight generation."""

    @pytest.mark.asyncio
    async def test_agent_count_and_cost_insights(self):
        """Agent data generates count and cost insights."""
        engine = _engine_no_ucm()
        data = {
            "agents": {"agent-1": {}, "agent-2": {}},
            "total_cost": 200.0,
            "total_calls": 5000,
        }
        insights = await engine._generate_agent_analytics_insights(data, "SEVEN_DAYS")
        assert any("2 agents" in i for i in insights)
        assert any("$200.00" in i for i in insights)
        assert any("5,000" in i for i in insights)

    @pytest.mark.asyncio
    async def test_agent_performance_insights(self):
        """Agent performance data generates top-agent and efficiency insights."""
        engine = _engine_no_ucm()
        data = {
            "agents": {"agent-1": {}},
            "total_cost": 100.0,
            "total_calls": 0,
            "agent_performance": {
                "agent-1": {"efficiency_score": 1.5},
            },
        }
        insights = await engine._generate_agent_analytics_insights(data, "SEVEN_DAYS")
        assert any("agent-1" in i for i in insights)
        assert any("highly efficient" in i.lower() for i in insights)

    @pytest.mark.asyncio
    async def test_agent_cost_per_call_insight(self):
        """Cost per call generates insight."""
        engine = _engine_no_ucm()
        data = {
            "agents": {"agent-1": {}},
            "total_cost": 100.0,
            "total_calls": 0,
            "period_analysis": {"average_cost_per_call": 0.005},
        }
        insights = await engine._generate_agent_analytics_insights(data, "SEVEN_DAYS")
        assert any("cost per call" in i.lower() for i in insights)

    @pytest.mark.asyncio
    async def test_empty_agents_no_crash(self):
        """Empty agents dict does not crash."""
        engine = _engine_no_ucm()
        insights = await engine._generate_agent_analytics_insights({}, "SEVEN_DAYS")
        assert isinstance(insights, list)
        assert all(isinstance(item, str) for item in insights)


class TestGenerateAgentAnalyticsRecommendations:
    """Tests for agent analytics recommendation generation."""

    @pytest.mark.asyncio
    async def test_low_efficiency_agents_recommendation(self):
        """Low-efficiency agents trigger optimization recommendation."""
        engine = _engine_no_ucm()
        data = {
            "agent_performance": {"slow-agent": {"efficiency_score": 0.2}},
            "period_analysis": {},
        }
        recs = await engine._generate_agent_analytics_recommendations(data, "SEVEN_DAYS")
        assert any("low efficiency" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_high_cost_agents_recommendation(self):
        """High cost-per-call agents trigger review recommendation."""
        engine = _engine_no_ucm()
        data = {
            "agent_performance": {"expensive-agent": {"cost_per_call": 0.05}},
            "period_analysis": {},
        }
        recs = await engine._generate_agent_analytics_recommendations(data, "SEVEN_DAYS")
        assert any("high cost per call" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_call_volume_concentration_recommendation(self):
        """Call volume concentration >50% triggers load balancing recommendation."""
        engine = _engine_no_ucm()
        data = {
            "agent_performance": {
                "busy-agent": {"calls": 800, "efficiency_score": 1.0},
                "idle-agent": {"calls": 200, "efficiency_score": 1.0},
            },
            "period_analysis": {},
        }
        recs = await engine._generate_agent_analytics_recommendations(data, "SEVEN_DAYS")
        assert any("load balancing" in r.lower() for r in recs)


class TestGenerateTaskAnalyticsInsights:
    """Tests for task analytics insight generation."""

    @pytest.mark.asyncio
    async def test_task_provider_and_model_insights(self):
        """Task data generates provider/model count insight."""
        engine = _engine_no_ucm()
        data = {
            "providers": {"OpenAI": {}},
            "models": {"gpt-4o": {}, "gpt-3.5": {}},
            "total_cost": 500.0,
            "total_performance": 100.0,
        }
        insights = await engine._generate_task_analytics_insights(data, "SEVEN_DAYS")
        assert any("1 providers" in i or "1 provider" in i for i in insights)
        assert any("2 models" in i for i in insights)
        assert any("$500.00" in i for i in insights)

    @pytest.mark.asyncio
    async def test_task_provider_performance_insights(self):
        """Provider performance data generates top-provider insight."""
        engine = _engine_no_ucm()
        data = {
            "providers": {"OpenAI": {}},
            "models": {},
            "total_cost": 100.0,
            "total_performance": 200.0,
            "provider_performance": {"OpenAI": {"efficiency": 2.0}},
        }
        insights = await engine._generate_task_analytics_insights(data, "SEVEN_DAYS")
        assert any("OpenAI" in i for i in insights)
        assert any("highly efficient" in i.lower() for i in insights)

    @pytest.mark.asyncio
    async def test_task_model_performance_insights(self):
        """Model performance data generates top-model insight."""
        engine = _engine_no_ucm()
        data = {
            "providers": {"OpenAI": {}},
            "models": {"gpt-4o": {}},
            "total_cost": 100.0,
            "total_performance": 50.0,
            "model_performance": {"gpt-4o": {"efficiency": 1.5}},
        }
        insights = await engine._generate_task_analytics_insights(data, "SEVEN_DAYS")
        assert any("gpt-4o" in i for i in insights)

    @pytest.mark.asyncio
    async def test_task_overall_efficiency_insight(self):
        """Total cost and performance generate efficiency insight."""
        engine = _engine_no_ucm()
        data = {
            "providers": {"OpenAI": {}},
            "models": {},
            "total_cost": 100.0,
            "total_performance": 250.0,
        }
        insights = await engine._generate_task_analytics_insights(data, "SEVEN_DAYS")
        assert any("efficiency" in i.lower() and "per dollar" in i.lower() for i in insights)

    @pytest.mark.asyncio
    async def test_empty_task_data_no_crash(self):
        """Empty task data does not crash."""
        engine = _engine_no_ucm()
        insights = await engine._generate_task_analytics_insights({}, "SEVEN_DAYS")
        assert isinstance(insights, list)
        assert all(isinstance(item, str) for item in insights)


class TestGenerateTaskAnalyticsRecommendations:
    """Tests for task analytics recommendation generation."""

    @pytest.mark.asyncio
    async def test_low_efficiency_providers_recommendation(self):
        """Low-efficiency providers trigger optimization recommendation."""
        engine = _engine_no_ucm()
        data = {
            "provider_performance": {"SlowProvider": {"efficiency": 0.3}},
            "total_cost": 100.0,
            "total_performance": 30.0,
        }
        recs = await engine._generate_task_analytics_recommendations(data, "SEVEN_DAYS")
        assert any("low task efficiency" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_high_cost_providers_recommendation(self):
        """Providers consuming >40% of total cost trigger review recommendation."""
        engine = _engine_no_ucm()
        data = {
            "provider_performance": {"ExpensiveProvider": {"cost": 60.0, "efficiency": 1.0}},
            "total_cost": 100.0,
            "total_performance": 100.0,
        }
        recs = await engine._generate_task_analytics_recommendations(data, "SEVEN_DAYS")
        assert any("significant task costs" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_low_efficiency_models_recommendation(self):
        """Low-efficiency models trigger replacement recommendation."""
        engine = _engine_no_ucm()
        data = {
            "model_performance": {"bad-model": {"efficiency": 0.2}},
            "total_cost": 100.0,
            "total_performance": 20.0,
        }
        recs = await engine._generate_task_analytics_recommendations(data, "SEVEN_DAYS")
        assert any("low task efficiency" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_low_overall_efficiency_recommendation(self):
        """Low overall efficiency triggers optimization recommendation."""
        engine = _engine_no_ucm()
        data = {
            "total_cost": 100.0,
            "total_performance": 50.0,
        }
        recs = await engine._generate_task_analytics_recommendations(data, "SEVEN_DAYS")
        assert any("task optimization" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_excellent_efficiency_recommendation(self):
        """Excellent efficiency triggers scaling recommendation."""
        engine = _engine_no_ucm()
        data = {
            "total_cost": 100.0,
            "total_performance": 300.0,
        }
        recs = await engine._generate_task_analytics_recommendations(data, "SEVEN_DAYS")
        assert any("Excellent" in r for r in recs)

    @pytest.mark.asyncio
    async def test_provider_cost_concentration_recommendation(self):
        """Provider >60% cost concentration triggers load balancing recommendation."""
        engine = _engine_no_ucm()
        data = {
            "provider_performance": {
                "BigProvider": {"cost": 70.0, "efficiency": 1.0},
                "SmallProvider": {"cost": 30.0, "efficiency": 1.0},
            },
            "total_cost": 100.0,
            "total_performance": 100.0,
        }
        recs = await engine._generate_task_analytics_recommendations(data, "SEVEN_DAYS")
        assert any("load balancing" in r.lower() for r in recs)


# ─────────────────────────────────────────────────────────────────────────────
# _process_cost_analysis — mocked sub-processor
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessCostAnalysis:
    """Tests for cost analysis processing pipeline."""

    @pytest.mark.asyncio
    async def test_cost_analysis_returns_completed(self):
        """Successful cost analysis returns completed status."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="cost_analysis", period="SEVEN_DAYS")

        fake_trends = MagicMock()
        fake_trends.total_cost = 100.0
        fake_trends.trend_direction = "stable"
        fake_trends.period_over_period_change = 0.0
        fake_trends.cost_by_provider = {}
        fake_trends.cost_by_model = {}

        with patch(
            "src.revenium_mcp_server.analytics.cost_analytics_processor.CostAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_cost_trends = AsyncMock(return_value=fake_trends)

            result = await engine._process_cost_analysis(client, query)
            assert result["status"] == "completed"
            assert result["query_type"] == "cost_analysis"
            assert "insights" in result["results"]

    @pytest.mark.asyncio
    async def test_cost_analysis_uses_context_intent(self):
        """Cost analysis extracts intent from query context."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(
            query_type="cost_analysis",
            context={"intent": "deep_analysis"},
        )

        fake_trends = MagicMock()
        fake_trends.total_cost = 0.0
        fake_trends.trend_direction = "stable"
        fake_trends.period_over_period_change = 0.0
        fake_trends.cost_by_provider = {}
        fake_trends.cost_by_model = {}

        with patch(
            "src.revenium_mcp_server.analytics.cost_analytics_processor.CostAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_cost_trends = AsyncMock(return_value=fake_trends)

            result = await engine._process_cost_analysis(client, query)
            # Verify intent was passed through
            call_args = instance.analyze_cost_trends.call_args
            assert call_args[0][4] == "deep_analysis"

    @pytest.mark.asyncio
    async def test_cost_analysis_failure_returns_failed_status(self):
        """Exception during cost analysis returns failed status."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="cost_analysis")

        with patch(
            "src.revenium_mcp_server.analytics.cost_analytics_processor.CostAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_cost_trends = AsyncMock(side_effect=RuntimeError("API down"))

            result = await engine._process_cost_analysis(client, query)
            assert "failed" in result["status"]
            assert result["api_calls_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# _process_spike_investigation — mocked sub-processor
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessSpikeInvestigation:
    """Tests for spike investigation processing pipeline."""

    @pytest.mark.asyncio
    async def test_spike_investigation_returns_completed(self):
        """Successful spike investigation returns completed status."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="spike_investigation", period="SEVEN_DAYS")

        fake_spike = {"contributors": [], "analysis_threshold": 100.0}

        with patch(
            "src.revenium_mcp_server.analytics.cost_analytics_processor.CostAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_cost_spike = AsyncMock(return_value=fake_spike)

            result = await engine._process_spike_investigation(client, query)
            assert result["status"] == "completed"
            assert result["query_type"] == "spike_investigation"
            assert result["results"]["threshold"] == 100.0

    @pytest.mark.asyncio
    async def test_spike_investigation_uses_context_threshold(self):
        """Spike investigation extracts threshold from context."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(
            query_type="spike_investigation",
            context={"threshold": 250.0},
        )

        fake_spike = {"contributors": [], "analysis_threshold": 250.0}

        with patch(
            "src.revenium_mcp_server.analytics.cost_analytics_processor.CostAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_cost_spike = AsyncMock(return_value=fake_spike)

            result = await engine._process_spike_investigation(client, query)
            assert result["results"]["threshold"] == 250.0

    @pytest.mark.asyncio
    async def test_spike_investigation_failure_returns_failed(self):
        """Exception during spike investigation returns failed status."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="spike_investigation")

        with patch(
            "src.revenium_mcp_server.analytics.cost_analytics_processor.CostAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_cost_spike = AsyncMock(side_effect=RuntimeError("timeout"))

            result = await engine._process_spike_investigation(client, query)
            assert "failed" in result["status"]


# ─────────────────────────────────────────────────────────────────────────────
# _process_profitability_analysis — mocked sub-processor
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessProfitabilityAnalysis:
    """Tests for profitability analysis processing pipeline."""

    def _fake_profitability_data(self):
        mock = MagicMock()
        mock.total_revenue = 1000.0
        mock.total_cost = 700.0
        mock.net_profit = 300.0
        mock.profit_margin = 30.0
        mock.profitability_by_customer = {}
        mock.profitability_by_product = {}
        return mock

    @pytest.mark.asyncio
    async def test_profitability_analysis_both_entities(self):
        """Default entity_type='both' fetches both customer and product profitability."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="profitability", entities=["customers", "products"])

        with patch(
            "src.revenium_mcp_server.analytics.profitability_analytics_processor.ProfitabilityAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_profitability = AsyncMock(return_value=self._fake_profitability_data())
            instance.analyze_customer_profitability = AsyncMock(return_value=[{"name": "Acme"}])
            instance.analyze_product_profitability = AsyncMock(return_value=[{"name": "API"}])

            result = await engine._process_profitability_analysis(client, query)
            assert result["status"] == "completed"
            assert result["results"]["entity_type"] == "both"
            instance.analyze_customer_profitability.assert_awaited_once()
            instance.analyze_product_profitability.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_profitability_analysis_customers_only(self):
        """Entity=['customers'] only fetches customer profitability."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="profitability", entities=["customers"])

        with patch(
            "src.revenium_mcp_server.analytics.profitability_analytics_processor.ProfitabilityAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_profitability = AsyncMock(return_value=self._fake_profitability_data())
            instance.analyze_customer_profitability = AsyncMock(return_value=[])
            instance.analyze_product_profitability = AsyncMock(return_value=[])

            result = await engine._process_profitability_analysis(client, query)
            assert result["results"]["entity_type"] == "customers"
            instance.analyze_customer_profitability.assert_awaited_once()
            instance.analyze_product_profitability.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_profitability_analysis_products_only(self):
        """Entity=['products'] only fetches product profitability."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="profitability", entities=["products"])

        with patch(
            "src.revenium_mcp_server.analytics.profitability_analytics_processor.ProfitabilityAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_profitability = AsyncMock(return_value=self._fake_profitability_data())
            instance.analyze_customer_profitability = AsyncMock(return_value=[])
            instance.analyze_product_profitability = AsyncMock(return_value=[])

            result = await engine._process_profitability_analysis(client, query)
            assert result["results"]["entity_type"] == "products"
            instance.analyze_product_profitability.assert_awaited_once()
            instance.analyze_customer_profitability.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_profitability_analysis_failure_returns_failed(self):
        """Exception during profitability analysis returns failed status."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="profitability")

        with patch(
            "src.revenium_mcp_server.analytics.profitability_analytics_processor.ProfitabilityAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_profitability = AsyncMock(side_effect=RuntimeError("DB error"))

            result = await engine._process_profitability_analysis(client, query)
            assert "failed" in result["status"]


# ─────────────────────────────────────────────────────────────────────────────
# _process_comparison_analysis — mocked sub-processor
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessComparisonAnalysis:
    """Tests for comparison analysis processing pipeline."""

    @pytest.mark.asyncio
    async def test_period_comparison_default(self):
        """Default comparison type is period comparison."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="comparison")

        with patch(
            "src.revenium_mcp_server.analytics.comparative_analytics_processor.ComparativeAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            mock_result = MagicMock()
            mock_result.metadata = {"api_calls_made": 2}
            instance.compare_periods = AsyncMock(return_value=mock_result)

            result = await engine._process_comparison_analysis(client, query)
            assert result["status"] == "completed"
            assert result["results"]["comparison_type"] == "period"

    @pytest.mark.asyncio
    async def test_model_comparison(self):
        """Model comparison with model_a and model_b."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(
            query_type="comparison",
            filters={"comparison_type": "model", "model_a": "gpt-4o", "model_b": "gpt-3.5"},
        )

        with patch(
            "src.revenium_mcp_server.analytics.comparative_analytics_processor.ComparativeAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.compare_models = AsyncMock(return_value=MagicMock())

            result = await engine._process_comparison_analysis(client, query)
            assert result["status"] == "completed"
            assert result["results"]["comparison_type"] == "model"

    @pytest.mark.asyncio
    async def test_model_comparison_missing_models_returns_error(self):
        """Model comparison without model_a/model_b returns error status."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(
            query_type="comparison",
            filters={"comparison_type": "model"},
        )

        result = await engine._process_comparison_analysis(client, query)
        assert "error" in result["status"]
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_provider_comparison(self):
        """Provider comparison with provider_a and provider_b."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(
            query_type="comparison",
            filters={"comparison_type": "provider", "provider_a": "OpenAI", "provider_b": "Anthropic"},
        )

        with patch(
            "src.revenium_mcp_server.analytics.comparative_analytics_processor.ComparativeAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.compare_providers = AsyncMock(return_value=MagicMock())

            result = await engine._process_comparison_analysis(client, query)
            assert result["status"] == "completed"
            assert result["results"]["comparison_type"] == "provider"

    @pytest.mark.asyncio
    async def test_provider_comparison_missing_providers_returns_error(self):
        """Provider comparison without provider_a/provider_b returns error status."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(
            query_type="comparison",
            filters={"comparison_type": "provider"},
        )

        result = await engine._process_comparison_analysis(client, query)
        assert "error" in result["status"]

    @pytest.mark.asyncio
    async def test_benchmark_comparison(self):
        """Benchmark comparison with customer_id."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(
            query_type="comparison",
            filters={"comparison_type": "benchmark", "customer_id": "cust-123"},
        )

        with patch(
            "src.revenium_mcp_server.analytics.comparative_analytics_processor.ComparativeAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.benchmark_customers = AsyncMock(return_value=MagicMock())

            result = await engine._process_comparison_analysis(client, query)
            assert result["status"] == "completed"
            assert result["results"]["comparison_type"] == "benchmark"

    @pytest.mark.asyncio
    async def test_benchmark_missing_customer_returns_error(self):
        """Benchmark without customer_id returns error status."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(
            query_type="comparison",
            filters={"comparison_type": "benchmark"},
        )

        result = await engine._process_comparison_analysis(client, query)
        assert "error" in result["status"]

    @pytest.mark.asyncio
    async def test_unsupported_comparison_type_returns_error(self):
        """Unsupported comparison type returns error status."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(
            query_type="comparison",
            filters={"comparison_type": "nonexistent"},
        )

        result = await engine._process_comparison_analysis(client, query)
        assert "error" in result["status"]
        assert "unsupported comparison type" in result["status"]

    @pytest.mark.asyncio
    async def test_comparison_analysis_failure_returns_failed(self):
        """Exception during comparison returns failed status."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="comparison")

        with patch(
            "src.revenium_mcp_server.analytics.comparative_analytics_processor.ComparativeAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.compare_periods = AsyncMock(side_effect=RuntimeError("timeout"))

            result = await engine._process_comparison_analysis(client, query)
            assert "failed" in result["status"]


# ─────────────────────────────────────────────────────────────────────────────
# _process_breakdown_analysis — mocked sub-processor
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessBreakdownAnalysis:
    """Tests for breakdown analysis processing pipeline."""

    @pytest.mark.asyncio
    async def test_agent_breakdown(self):
        """Agent entity routes to get_cost_breakdown for agents."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="breakdown", entities=["agents"])

        with patch(
            "src.revenium_mcp_server.analytics.cost_analytics_processor.CostAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.get_cost_breakdown = AsyncMock(
                return_value={"data": [{"name": "agent-1", "cost": 50.0}]}
            )

            result = await engine._process_breakdown_analysis(client, query)
            assert result["status"] == "completed"
            assert "cost_by_agent" in result["results"]

    @pytest.mark.asyncio
    async def test_model_breakdown(self):
        """Model entity routes to analyze_cost_trends for model breakdown."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="breakdown", entities=["models"])

        fake_trends = MagicMock()
        fake_trends.cost_by_model = {"gpt-4o": 200.0}

        with patch(
            "src.revenium_mcp_server.analytics.cost_analytics_processor.CostAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_cost_trends = AsyncMock(return_value=fake_trends)

            result = await engine._process_breakdown_analysis(client, query)
            assert result["status"] == "completed"
            assert "cost_by_model" in result["results"]

    @pytest.mark.asyncio
    async def test_provider_breakdown(self):
        """Provider entity routes to analyze_cost_trends for provider breakdown."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="breakdown", entities=["providers"])

        fake_trends = MagicMock()
        fake_trends.cost_by_provider = {"OpenAI": 300.0}

        with patch(
            "src.revenium_mcp_server.analytics.cost_analytics_processor.CostAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_cost_trends = AsyncMock(return_value=fake_trends)

            result = await engine._process_breakdown_analysis(client, query)
            assert result["status"] == "completed"
            assert "cost_by_provider" in result["results"]

    @pytest.mark.asyncio
    async def test_customer_breakdown(self):
        """Customer entity routes to analyze_cost_trends for customer breakdown."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="breakdown", entities=["customers"])

        fake_trends = MagicMock()
        fake_trends.cost_by_customer = {"AcmeCorp": 150.0}

        with patch(
            "src.revenium_mcp_server.analytics.cost_analytics_processor.CostAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_cost_trends = AsyncMock(return_value=fake_trends)

            result = await engine._process_breakdown_analysis(client, query)
            assert result["status"] == "completed"
            assert "cost_by_customer" in result["results"]

    @pytest.mark.asyncio
    async def test_product_breakdown(self):
        """Product entity routes to get_cost_breakdown for products."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="breakdown", entities=["products"])

        with patch(
            "src.revenium_mcp_server.analytics.cost_analytics_processor.CostAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.get_cost_breakdown = AsyncMock(
                return_value={"data": [{"name": "API-Pro", "cost": 120.0}]}
            )

            result = await engine._process_breakdown_analysis(client, query)
            assert result["status"] == "completed"
            assert "cost_by_product" in result["results"]
            assert result["results"]["cost_by_product"] == {"API-Pro": 120.0}

    @pytest.mark.asyncio
    async def test_task_breakdown(self):
        """Task entity routes to TransactionLevelAnalyticsProcessor."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="breakdown", entities=["tasks"])

        fake_result = MagicMock()
        fake_result.cost_by_task = {"inference": 80.0}

        with patch(
            "src.revenium_mcp_server.analytics.transaction_level_analytics_processor.TransactionLevelAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_task_metrics = AsyncMock(return_value=fake_result)

            result = await engine._process_breakdown_analysis(client, query)
            assert result["status"] == "completed"
            assert "cost_by_task" in result["results"]

    @pytest.mark.asyncio
    async def test_default_breakdown_comprehensive(self):
        """No specific entity routes to comprehensive breakdown."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        # Use an entity that doesn't match any specific breakdown
        query = _make_query(query_type="breakdown", entities=["transactions"])

        fake_trends = MagicMock()
        fake_trends.cost_by_provider = {"OpenAI": 300.0}
        fake_trends.cost_by_model = {"gpt-4o": 200.0}
        fake_trends.cost_by_customer = {"Acme": 100.0}

        with patch(
            "src.revenium_mcp_server.analytics.cost_analytics_processor.CostAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_cost_trends = AsyncMock(return_value=fake_trends)

            result = await engine._process_breakdown_analysis(client, query)
            assert result["status"] == "completed"
            assert "cost_by_provider" in result["results"]
            assert "cost_by_model" in result["results"]
            assert "cost_by_customer" in result["results"]

    @pytest.mark.asyncio
    async def test_breakdown_failure_returns_failed(self):
        """Exception during breakdown returns failed status."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="breakdown", entities=["models"])

        with patch(
            "src.revenium_mcp_server.analytics.cost_analytics_processor.CostAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_cost_trends = AsyncMock(side_effect=RuntimeError("boom"))

            result = await engine._process_breakdown_analysis(client, query)
            assert "failed" in result["status"]


# ─────────────────────────────────────────────────────────────────────────────
# _process_transaction_level_analysis — mocked sub-processor
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessTransactionLevelAnalysis:
    """Tests for transaction-level analysis processing pipeline."""

    def _fake_transaction_data(self):
        """Create a fake TransactionLevelData-like object."""
        mock = MagicMock()
        mock.total_cost = 500.0
        mock.average_cost_per_transaction = 0.05
        mock.cost_by_provider = {"OpenAI": 300.0}
        mock.cost_by_model = {"gpt-4o": 200.0}
        mock.performance_metrics = {}
        mock.transaction_trends = []
        mock.period = "SEVEN_DAYS"
        mock.aggregation = "TOTAL"
        return mock

    @pytest.mark.asyncio
    async def test_customer_intent_routes_to_customer_analysis(self):
        """Customer entity routes to analyze_customer_transactions."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="transaction_level", entities=["customers"])

        with patch(
            "src.revenium_mcp_server.analytics.transaction_level_analytics_processor.TransactionLevelAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_customer_transactions = AsyncMock(
                return_value={"organizations": {}, "total_cost": 0.0}
            )

            result = await engine._process_transaction_level_analysis(client, query)
            assert result["status"] == "completed"
            assert "customer_analytics" in result["results"]

    @pytest.mark.asyncio
    async def test_product_intent_routes_to_product_analysis(self):
        """Product entity routes to analyze_product_transactions."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="transaction_level", entities=["products"])

        with patch(
            "src.revenium_mcp_server.analytics.transaction_level_analytics_processor.TransactionLevelAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_product_transactions = AsyncMock(
                return_value={"products": {}, "total_cost": 0.0}
            )

            result = await engine._process_transaction_level_analysis(client, query)
            assert result["status"] == "completed"
            assert "product_analytics" in result["results"]

    @pytest.mark.asyncio
    async def test_agent_intent_routes_to_agent_analysis(self):
        """Agent entity routes to analyze_agent_transactions."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="transaction_level", entities=["agents"])

        with patch(
            "src.revenium_mcp_server.analytics.transaction_level_analytics_processor.TransactionLevelAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_agent_transactions = AsyncMock(
                return_value={"agents": {}, "total_cost": 0.0}
            )

            result = await engine._process_transaction_level_analysis(client, query)
            assert result["status"] == "completed"
            assert "agent_analytics" in result["results"]

    @pytest.mark.asyncio
    async def test_task_intent_routes_to_task_analysis(self):
        """Task entity routes to analyze_task_metrics."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="transaction_level", entities=["tasks"])

        with patch(
            "src.revenium_mcp_server.analytics.transaction_level_analytics_processor.TransactionLevelAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_task_metrics = AsyncMock(
                return_value={"providers": {}, "models": {}, "total_cost": 0.0}
            )

            result = await engine._process_transaction_level_analysis(client, query)
            assert result["status"] == "completed"
            assert "task_analytics" in result["results"]

    @pytest.mark.asyncio
    async def test_default_routes_to_summary_analysis(self):
        """No specific entity routes to summary metrics."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="transaction_level", entities=["transactions"])

        fake_data = self._fake_transaction_data()

        with patch(
            "src.revenium_mcp_server.analytics.transaction_level_analytics_processor.TransactionLevelAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_summary_metrics = AsyncMock(return_value=fake_data)

            result = await engine._process_transaction_level_analysis(client, query)
            assert result["status"] == "completed"
            assert "summary_analytics" in result["results"]

    @pytest.mark.asyncio
    async def test_context_intent_overrides_entity_detection(self):
        """Context intent with 'customer' keyword routes to customer analysis."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(
            query_type="transaction_level",
            entities=["transactions"],
            context={"intent": "customer_analysis"},
        )

        with patch(
            "src.revenium_mcp_server.analytics.transaction_level_analytics_processor.TransactionLevelAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_customer_transactions = AsyncMock(
                return_value={"organizations": {}, "total_cost": 0.0}
            )

            result = await engine._process_transaction_level_analysis(client, query)
            assert "customer_analytics" in result["results"]

    @pytest.mark.asyncio
    async def test_non_string_intent_handled_gracefully(self):
        """Non-string intent value does not crash."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(
            query_type="transaction_level",
            entities=["transactions"],
            context={"intent": 12345},  # Non-string intent
        )

        fake_data = self._fake_transaction_data()

        with patch(
            "src.revenium_mcp_server.analytics.transaction_level_analytics_processor.TransactionLevelAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_summary_metrics = AsyncMock(return_value=fake_data)

            result = await engine._process_transaction_level_analysis(client, query)
            assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_transaction_data_object_serialized(self):
        """TransactionLevelData objects are converted to dicts in results."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="transaction_level", entities=["transactions"])

        fake_data = self._fake_transaction_data()

        with patch(
            "src.revenium_mcp_server.analytics.transaction_level_analytics_processor.TransactionLevelAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_summary_metrics = AsyncMock(return_value=fake_data)

            result = await engine._process_transaction_level_analysis(client, query)
            summary = result["results"]["summary_analytics"]
            # Should be serialized to dict
            assert isinstance(summary, dict)
            assert summary["total_cost"] == 500.0

    @pytest.mark.asyncio
    async def test_transaction_level_failure_returns_failed(self):
        """Exception during transaction-level analysis returns failed status."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="transaction_level", entities=["customers"])

        with patch(
            "src.revenium_mcp_server.analytics.transaction_level_analytics_processor.TransactionLevelAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_customer_transactions = AsyncMock(
                side_effect=RuntimeError("connection lost")
            )

            result = await engine._process_transaction_level_analysis(client, query)
            assert "failed" in result["status"]

    @pytest.mark.asyncio
    async def test_customer_with_profitability_intent(self):
        """Customer + profitability entity triggers extra profitability analysis."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(
            query_type="transaction_level",
            entities=["customers"],
            context={"profitability": True},
        )

        with patch(
            "src.revenium_mcp_server.analytics.transaction_level_analytics_processor.TransactionLevelAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_customer_transactions = AsyncMock(
                return_value={"organizations": {}, "total_cost": 0.0}
            )
            instance.analyze_customer_profitability = AsyncMock(
                return_value={"Acme": {"profit": 100.0}}
            )

            result = await engine._process_transaction_level_analysis(client, query)
            assert "customer_analytics" in result["results"]
            assert "customer_profitability" in result["results"]

    @pytest.mark.asyncio
    async def test_agent_with_performance_intent(self):
        """Agent + performance entity triggers extra performance analysis."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(
            query_type="transaction_level",
            entities=["agents"],
            context={"performance": True},
        )

        with patch(
            "src.revenium_mcp_server.analytics.transaction_level_analytics_processor.TransactionLevelAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_agent_transactions = AsyncMock(
                return_value={"agents": {}, "total_cost": 0.0}
            )
            instance.analyze_agent_performance = AsyncMock(
                return_value={"agent-1": {"efficiency_score": 1.5}}
            )

            result = await engine._process_transaction_level_analysis(client, query)
            assert "agent_analytics" in result["results"]
            assert "agent_performance" in result["results"]

    @pytest.mark.asyncio
    async def test_task_with_performance_intent(self):
        """Task + performance entity triggers extra task performance analysis."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(
            query_type="transaction_level",
            entities=["tasks"],
            context={"performance": True},
        )

        with patch(
            "src.revenium_mcp_server.analytics.transaction_level_analytics_processor.TransactionLevelAnalyticsProcessor",
            autospec=False,
        ) as MockProcessor:
            instance = MockProcessor.return_value
            instance.analyze_task_metrics = AsyncMock(
                return_value={"providers": {}, "models": {}, "total_cost": 0.0}
            )
            instance.analyze_task_performance = AsyncMock(
                return_value={"inference": {"efficiency": 1.5}}
            )

            result = await engine._process_transaction_level_analysis(client, query)
            assert "task_analytics" in result["results"]
            assert "task_performance" in result["results"]


# ─────────────────────────────────────────────────────────────────────────────
# process_analytics_query — full routing for each query type
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessAnalyticsQueryRouting:
    """Tests for query routing through the main entry point for each query type."""

    @pytest.mark.asyncio
    async def test_cost_analysis_routing(self):
        """cost_analysis routes to _process_cost_analysis and returns AnalyticsResult."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="cost_analysis")

        mock_data = {
            "query_type": "cost_analysis",
            "results": {"cost_trends": {}},
            "api_calls_count": 4,
            "status": "completed",
        }
        with patch.object(engine, "_process_cost_analysis", new_callable=AsyncMock, return_value=mock_data):
            result = await engine.process_analytics_query(client, query)
            assert isinstance(result, AnalyticsResult)
            assert result.data["query_type"] == "cost_analysis"

    @pytest.mark.asyncio
    async def test_profitability_routing(self):
        """profitability routes to _process_profitability_analysis."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="profitability")

        mock_data = {
            "query_type": "profitability",
            "results": {},
            "api_calls_count": 6,
            "status": "completed",
        }
        with patch.object(engine, "_process_profitability_analysis", new_callable=AsyncMock, return_value=mock_data):
            result = await engine.process_analytics_query(client, query)
            assert result.data["query_type"] == "profitability"

    @pytest.mark.asyncio
    async def test_comparison_routing(self):
        """comparison routes to _process_comparison_analysis."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="comparison")

        mock_data = {
            "query_type": "comparison",
            "results": {},
            "api_calls_count": 2,
            "status": "completed",
        }
        with patch.object(engine, "_process_comparison_analysis", new_callable=AsyncMock, return_value=mock_data):
            result = await engine.process_analytics_query(client, query)
            assert result.data["query_type"] == "comparison"

    @pytest.mark.asyncio
    async def test_spike_investigation_routing(self):
        """spike_investigation routes to _process_spike_investigation."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="spike_investigation")

        mock_data = {
            "query_type": "spike_investigation",
            "results": {},
            "api_calls_count": 6,
            "status": "completed",
        }
        with patch.object(engine, "_process_spike_investigation", new_callable=AsyncMock, return_value=mock_data):
            result = await engine.process_analytics_query(client, query)
            assert result.data["query_type"] == "spike_investigation"

    @pytest.mark.asyncio
    async def test_breakdown_routing(self):
        """breakdown routes to _process_breakdown_analysis."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="breakdown")

        mock_data = {
            "query_type": "breakdown",
            "results": {},
            "api_calls_count": 1,
            "status": "completed",
        }
        with patch.object(engine, "_process_breakdown_analysis", new_callable=AsyncMock, return_value=mock_data):
            result = await engine.process_analytics_query(client, query)
            assert result.data["query_type"] == "breakdown"

    @pytest.mark.asyncio
    async def test_transaction_level_routing(self):
        """transaction_level routes to _process_transaction_level_analysis."""
        engine = _engine_no_ucm()
        client = MagicMock()
        client.team_id = "test-team"
        query = _make_query(query_type="transaction_level")

        mock_data = {
            "query_type": "transaction_level",
            "results": {},
            "api_calls_count": 5,
            "status": "completed",
        }
        with patch.object(engine, "_process_transaction_level_analysis", new_callable=AsyncMock, return_value=mock_data):
            result = await engine.process_analytics_query(client, query)
            assert result.data["query_type"] == "transaction_level"
