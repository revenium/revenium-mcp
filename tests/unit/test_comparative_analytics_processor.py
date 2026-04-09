"""Unit tests for ComparativeAnalyticsProcessor.

Tests the behavioral correctness of:
- Entity name normalization (provider, model, customer)
- Percentage change calculation with trend direction and significance
- Comparison insight generation from percentage changes
- Comparison recommendation generation (cost increases, decreases, revenue)
- Model comparison changes, insights, and recommendations
- Model and provider data extraction
- Validation of comparison inputs
"""

import pytest

from src.revenium_mcp_server.analytics.comparative_analytics_processor import (
    ComparativeAnalyticsProcessor,
    PercentageChange,
)
from src.revenium_mcp_server.common.error_handling import ToolError


# ─────────────────────────────────────────────────────────────────────────────
# Initialization
# ─────────────────────────────────────────────────────────────────────────────


class TestComparativeAnalyticsProcessorInit:
    """Verify processor initializes with expected endpoints."""

    def test_has_cost_endpoints(self):
        proc = ComparativeAnalyticsProcessor()
        assert "cost_metric_by_provider_over_time" in proc.analytics_endpoints
        assert "total_cost_by_model" in proc.analytics_endpoints

    def test_has_revenue_endpoints(self):
        proc = ComparativeAnalyticsProcessor()
        assert "revenue_metric_by_organization" in proc.analytics_endpoints
        assert "revenue_metric_by_product" in proc.analytics_endpoints


# ─────────────────────────────────────────────────────────────────────────────
# _normalize_entity_name
# ─────────────────────────────────────────────────────────────────────────────


class TestNormalizeEntityName:
    """Tests for entity name normalization across different entity types."""

    def setup_method(self):
        self.proc = ComparativeAnalyticsProcessor()

    def test_provider_normalization_case_variants(self):
        assert self.proc._normalize_entity_name("openai", "provider") == "OpenAI"
        assert self.proc._normalize_entity_name("OPENAI", "provider") == "OpenAI"
        assert self.proc._normalize_entity_name("anthropic", "provider") == "Anthropic"
        assert self.proc._normalize_entity_name("ANTHROPIC", "provider") == "Anthropic"

    def test_provider_unknown_preserved(self):
        assert self.proc._normalize_entity_name("CustomProvider", "provider") == "CustomProvider"

    def test_empty_provider_returned_as_is(self):
        assert self.proc._normalize_entity_name("", "provider") == ""

    def test_unknown_returned_as_is(self):
        assert self.proc._normalize_entity_name("Unknown", "provider") == "Unknown"

    def test_model_normalization(self):
        assert self.proc._normalize_entity_name("GPT-4O", "model") == "gpt-4o"
        assert self.proc._normalize_entity_name("GPT-3.5-TURBO", "model") == "gpt-3.5-turbo"

    def test_model_unknown_preserved(self):
        assert self.proc._normalize_entity_name("custom-model-v1", "model") == "custom-model-v1"

    def test_customer_strips_whitespace(self):
        assert self.proc._normalize_entity_name("  AcmeCorp  ", "customer") == "AcmeCorp"


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_percentage_changes
# ─────────────────────────────────────────────────────────────────────────────


class TestCalculatePercentageChanges:
    """Tests for percentage change calculations between periods."""

    def setup_method(self):
        self.proc = ComparativeAnalyticsProcessor()

    def test_increasing_cost_detected(self):
        current = {"data": [{"provider": "OpenAI", "cost": 200}]}
        comparison = {"data": [{"provider": "OpenAI", "cost": 100}]}
        changes = self.proc._calculate_percentage_changes(current, comparison, "provider")
        assert len(changes) == 1
        assert changes[0].percentage_change == pytest.approx(100.0)
        assert changes[0].trend_direction == "increasing"
        assert changes[0].significance == "significant"

    def test_decreasing_cost_detected(self):
        current = {"data": [{"provider": "OpenAI", "cost": 50}]}
        comparison = {"data": [{"provider": "OpenAI", "cost": 100}]}
        changes = self.proc._calculate_percentage_changes(current, comparison, "provider")
        assert changes[0].percentage_change == pytest.approx(-50.0)
        assert changes[0].trend_direction == "decreasing"

    def test_stable_within_threshold(self):
        current = {"data": [{"provider": "OpenAI", "cost": 102}]}
        comparison = {"data": [{"provider": "OpenAI", "cost": 100}]}
        changes = self.proc._calculate_percentage_changes(current, comparison, "provider")
        assert changes[0].trend_direction == "stable"

    def test_moderate_significance(self):
        current = {"data": [{"provider": "OpenAI", "cost": 115}]}
        comparison = {"data": [{"provider": "OpenAI", "cost": 100}]}
        changes = self.proc._calculate_percentage_changes(current, comparison, "provider")
        assert changes[0].significance == "moderate"

    def test_minimal_significance(self):
        current = {"data": [{"provider": "OpenAI", "cost": 105}]}
        comparison = {"data": [{"provider": "OpenAI", "cost": 100}]}
        changes = self.proc._calculate_percentage_changes(current, comparison, "provider")
        assert changes[0].significance == "minimal"

    def test_zero_previous_value_returns_zero_change(self):
        current = {"data": [{"provider": "OpenAI", "cost": 100}]}
        comparison = {"data": [{"provider": "OpenAI", "cost": 0}]}
        changes = self.proc._calculate_percentage_changes(current, comparison, "provider")
        assert changes[0].percentage_change == 0

    def test_entity_not_in_comparison_still_calculated(self):
        current = {"data": [{"provider": "NewProvider", "cost": 50}]}
        comparison = {"data": []}
        changes = self.proc._calculate_percentage_changes(current, comparison, "provider")
        assert len(changes) == 1
        assert changes[0].entity_name == "NewProvider"

    def test_normalizes_entity_names_for_matching(self):
        current = {"data": [{"provider": "openai", "cost": 200}]}
        comparison = {"data": [{"provider": "OPENAI", "cost": 100}]}
        changes = self.proc._calculate_percentage_changes(current, comparison, "provider")
        assert len(changes) == 1
        assert changes[0].entity_name == "OpenAI"

    def test_handles_list_format_data(self):
        current = [{"provider": "X", "cost": 100}]
        comparison = [{"provider": "X", "cost": 80}]
        changes = self.proc._calculate_percentage_changes(current, comparison, "provider")
        assert len(changes) == 1


# ─────────────────────────────────────────────────────────────────────────────
# _generate_comparison_insights
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateComparisonInsights:
    """Tests for insight generation from percentage changes."""

    def setup_method(self):
        self.proc = ComparativeAnalyticsProcessor()

    def test_no_changes_returns_no_data_message(self):
        insights = self.proc._generate_comparison_insights([], "cost", "provider")
        assert any("No cost data" in i for i in insights)

    def test_significant_increases_reported(self):
        changes = [
            PercentageChange(
                current_value=200, previous_value=100, absolute_change=100,
                percentage_change=100.0, trend_direction="increasing",
                significance="significant", entity_name="OpenAI"
            )
        ]
        insights = self.proc._generate_comparison_insights(changes, "cost", "provider")
        assert any("increases" in i.lower() for i in insights)

    def test_significant_decreases_reported(self):
        changes = [
            PercentageChange(
                current_value=50, previous_value=100, absolute_change=-50,
                percentage_change=-50.0, trend_direction="decreasing",
                significance="significant", entity_name="OpenAI"
            )
        ]
        insights = self.proc._generate_comparison_insights(changes, "cost", "provider")
        assert any("decreases" in i.lower() for i in insights)

    def test_overall_trend_increasing(self):
        changes = [
            PercentageChange(
                current_value=120, previous_value=100, absolute_change=20,
                percentage_change=20.0, trend_direction="increasing",
                significance="significant", entity_name="A"
            ),
            PercentageChange(
                current_value=130, previous_value=100, absolute_change=30,
                percentage_change=30.0, trend_direction="increasing",
                significance="significant", entity_name="B"
            ),
        ]
        insights = self.proc._generate_comparison_insights(changes, "cost", "provider")
        assert any("increasing" in i.lower() for i in insights)


# ─────────────────────────────────────────────────────────────────────────────
# _generate_comparison_recommendations
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateComparisonRecommendations:
    """Tests for recommendation generation from percentage changes."""

    def setup_method(self):
        self.proc = ComparativeAnalyticsProcessor()

    def test_no_changes_recommends_more_data(self):
        recs = self.proc._generate_comparison_recommendations([], "cost")
        assert any("gather" in r.lower() for r in recs)

    def test_cost_increases_trigger_action_recommendation(self):
        changes = [
            PercentageChange(
                current_value=250, previous_value=100, absolute_change=150,
                percentage_change=150.0, trend_direction="increasing",
                significance="significant", entity_name="OpenAI"
            )
        ]
        recs = self.proc._generate_comparison_recommendations(changes, "cost")
        assert any("action" in r.lower() or "immediate" in r.lower() for r in recs)

    def test_cost_decreases_trigger_success_recommendation(self):
        changes = [
            PercentageChange(
                current_value=50, previous_value=100, absolute_change=-50,
                percentage_change=-50.0, trend_direction="decreasing",
                significance="significant", entity_name="OpenAI"
            )
        ]
        recs = self.proc._generate_comparison_recommendations(changes, "cost")
        assert any("success" in r.lower() or "savings" in r.lower() for r in recs)

    def test_revenue_increase_recommendation(self):
        changes = [
            PercentageChange(
                current_value=200, previous_value=100, absolute_change=100,
                percentage_change=100.0, trend_direction="increasing",
                significance="significant", entity_name="Product A"
            )
        ]
        recs = self.proc._generate_comparison_recommendations(changes, "revenue")
        assert any("revenue" in r.lower() for r in recs)

    def test_high_volatility_recommendation(self):
        # More than 50% of changes are significant
        changes = [
            PercentageChange(
                current_value=200, previous_value=100, absolute_change=100,
                percentage_change=100.0, trend_direction="increasing",
                significance="significant", entity_name="A"
            ),
            PercentageChange(
                current_value=50, previous_value=100, absolute_change=-50,
                percentage_change=-50.0, trend_direction="decreasing",
                significance="significant", entity_name="B"
            ),
        ]
        recs = self.proc._generate_comparison_recommendations(changes, "cost")
        assert any("volatility" in r.lower() for r in recs)


# ─────────────────────────────────────────────────────────────────────────────
# _extract_model_data
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractModelData:
    """Tests for extracting specific model data from API response."""

    def setup_method(self):
        self.proc = ComparativeAnalyticsProcessor()

    def test_extracts_matching_model(self):
        model_data = {"data": [
            {"model": "gpt-4", "cost": 100},
            {"model": "claude-3", "cost": 200},
        ]}
        result = self.proc._extract_model_data(model_data, "gpt-4")
        assert result["cost"] == 100

    def test_missing_model_returns_defaults(self):
        model_data = {"data": [{"model": "gpt-4", "cost": 100}]}
        result = self.proc._extract_model_data(model_data, "missing-model")
        assert result["model"] == "missing-model"
        assert result["cost"] == 0

    def test_handles_list_format(self):
        model_data = [{"model": "gpt-4", "cost": 100}]
        result = self.proc._extract_model_data(model_data, "gpt-4")
        assert result["cost"] == 100


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_model_comparison_changes
# ─────────────────────────────────────────────────────────────────────────────


class TestCalculateModelComparisonChanges:
    """Tests for model-vs-model comparison calculations."""

    def setup_method(self):
        self.proc = ComparativeAnalyticsProcessor()

    def test_cost_comparison(self):
        model_a = {"cost": 200}
        model_b = {"cost": 100}
        changes = self.proc._calculate_model_comparison_changes(
            model_a, model_b, "cost", "gpt-4", "claude-3"
        )
        assert len(changes) == 1
        assert changes[0].percentage_change == pytest.approx(100.0)
        assert changes[0].entity_name == "gpt-4 vs claude-3"

    def test_zero_model_b_returns_empty(self):
        model_a = {"cost": 100}
        model_b = {"cost": 0}
        changes = self.proc._calculate_model_comparison_changes(
            model_a, model_b, "cost", "A", "B"
        )
        assert len(changes) == 0

    def test_performance_comparison_uses_performance_field(self):
        model_a = {"performance": 90}
        model_b = {"performance": 80}
        changes = self.proc._calculate_model_comparison_changes(
            model_a, model_b, "performance", "A", "B"
        )
        assert len(changes) == 1
        assert changes[0].current_value == 90.0

    def test_significant_difference(self):
        model_a = {"cost": 300}
        model_b = {"cost": 100}
        changes = self.proc._calculate_model_comparison_changes(
            model_a, model_b, "cost", "A", "B"
        )
        assert changes[0].significance == "significant"


# ─────────────────────────────────────────────────────────────────────────────
# _generate_model_comparison_insights
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateModelComparisonInsights:
    """Tests for model comparison insight generation."""

    def setup_method(self):
        self.proc = ComparativeAnalyticsProcessor()

    def test_no_changes_reports_no_data(self):
        insights = self.proc._generate_model_comparison_insights("A", "B", [], "cost")
        assert any("No cost data" in i for i in insights)

    def test_increasing_reports_higher(self):
        changes = [
            PercentageChange(
                current_value=200, previous_value=100, absolute_change=100,
                percentage_change=100.0, trend_direction="increasing",
                significance="significant", entity_name="A vs B"
            )
        ]
        insights = self.proc._generate_model_comparison_insights("A", "B", changes, "cost")
        assert any("higher" in i.lower() for i in insights)

    def test_decreasing_reports_lower(self):
        changes = [
            PercentageChange(
                current_value=50, previous_value=100, absolute_change=-50,
                percentage_change=-50.0, trend_direction="decreasing",
                significance="significant", entity_name="A vs B"
            )
        ]
        insights = self.proc._generate_model_comparison_insights("A", "B", changes, "cost")
        assert any("lower" in i.lower() for i in insights)

    def test_stable_reports_similar(self):
        changes = [
            PercentageChange(
                current_value=100, previous_value=100, absolute_change=0,
                percentage_change=0.0, trend_direction="stable",
                significance="minimal", entity_name="A vs B"
            )
        ]
        insights = self.proc._generate_model_comparison_insights("A", "B", changes, "cost")
        assert any("similar" in i.lower() for i in insights)


# ─────────────────────────────────────────────────────────────────────────────
# _generate_model_recommendations
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateModelRecommendations:
    """Tests for model comparison recommendation generation."""

    def setup_method(self):
        self.proc = ComparativeAnalyticsProcessor()

    def test_no_changes_recommends_data_collection(self):
        recs = self.proc._generate_model_recommendations("A", "B", [])
        assert any("data" in r.lower() for r in recs)

    def test_large_cost_difference_triggers_critical(self):
        changes = [
            PercentageChange(
                current_value=300, previous_value=100, absolute_change=200,
                percentage_change=200.0, trend_direction="increasing",
                significance="significant", entity_name="A vs B"
            )
        ]
        recs = self.proc._generate_model_recommendations("A", "B", changes)
        assert any("critical" in r.lower() or "migrate" in r.lower() for r in recs)

    def test_cost_efficient_model_triggers_confirmation(self):
        changes = [
            PercentageChange(
                current_value=50, previous_value=100, absolute_change=-50,
                percentage_change=-50.0, trend_direction="decreasing",
                significance="significant", entity_name="A vs B"
            )
        ]
        recs = self.proc._generate_model_recommendations("A", "B", changes)
        assert any("cost" in r.lower() and "efficien" in r.lower() for r in recs)


# ─────────────────────────────────────────────────────────────────────────────
# _validate_comparison_inputs
# ─────────────────────────────────────────────────────────────────────────────


class TestValidateComparisonInputs:
    """Tests for input validation of comparison parameters."""

    def setup_method(self):
        self.proc = ComparativeAnalyticsProcessor()

    @pytest.mark.asyncio
    async def test_valid_inputs_pass(self):
        # Should not raise
        await self.proc._validate_comparison_inputs(
            "cost", "provider", "SEVEN_DAYS", "THIRTY_DAYS", "TOTAL"
        )

    @pytest.mark.asyncio
    async def test_invalid_metric_type_raises(self):
        with pytest.raises(ToolError):
            await self.proc._validate_comparison_inputs(
                "invalid", "provider", "SEVEN_DAYS", "THIRTY_DAYS"
            )

    @pytest.mark.asyncio
    async def test_invalid_breakdown_raises(self):
        with pytest.raises(ToolError):
            await self.proc._validate_comparison_inputs(
                "cost", "invalid", "SEVEN_DAYS", "THIRTY_DAYS"
            )

    @pytest.mark.asyncio
    async def test_invalid_current_period_raises(self):
        with pytest.raises(ToolError):
            await self.proc._validate_comparison_inputs(
                "cost", "provider", "BAD_PERIOD", "THIRTY_DAYS"
            )

    @pytest.mark.asyncio
    async def test_invalid_previous_period_raises(self):
        with pytest.raises(ToolError):
            await self.proc._validate_comparison_inputs(
                "cost", "provider", "SEVEN_DAYS", "BAD_PERIOD"
            )

    @pytest.mark.asyncio
    async def test_invalid_group_raises(self):
        with pytest.raises(ToolError):
            await self.proc._validate_comparison_inputs(
                "cost", "provider", "SEVEN_DAYS", "THIRTY_DAYS", "BAD_GROUP"
            )
