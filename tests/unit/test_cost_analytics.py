"""Unit tests for CostAnalyticsProcessor.

Tests behavioral correctness of:
- Entity name normalization (provider, model, customer, product)
- Cost trend data processing from API response structures
- Period-over-period change calculation (trend and spike modes)
- Trend direction determination
- Breakdown data processing
- Spike contributor identification
- Cost breakdown validation (unsupported breakdown types)
- Error handling in analyze_cost_trends and analyze_cost_spike
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.analytics.cost_analytics_processor import (
    CostAnalyticsProcessor,
    CostTrendData,
)
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError


# ─────────────────────────────────────────────────────────────────────────────
# _normalize_entity_name
# ─────────────────────────────────────────────────────────────────────────────


class TestNormalizeEntityName:
    """Tests for entity name normalization across provider, model, and other types."""

    def setup_method(self):
        self.processor = CostAnalyticsProcessor()

    # Provider normalization
    def test_provider_openai_lowercase(self):
        assert self.processor._normalize_entity_name("openai", "provider") == "OpenAI"

    def test_provider_openai_uppercase(self):
        assert self.processor._normalize_entity_name("OPENAI", "provider") == "OpenAI"

    def test_provider_anthropic(self):
        assert self.processor._normalize_entity_name("anthropic", "provider") == "Anthropic"

    def test_provider_foundry_case_variants(self):
        assert self.processor._normalize_entity_name("foundry", "provider") == "Foundry"
        assert self.processor._normalize_entity_name("FOUNDRY", "provider") == "Foundry"

    def test_provider_already_normalized(self):
        assert self.processor._normalize_entity_name("OpenAI", "provider") == "OpenAI"

    def test_provider_unknown_passes_through(self):
        assert self.processor._normalize_entity_name("CustomProvider", "provider") == "CustomProvider"

    def test_provider_empty_returns_empty(self):
        assert self.processor._normalize_entity_name("", "provider") == ""

    def test_provider_unknown_literal_returns_unknown(self):
        assert self.processor._normalize_entity_name("Unknown", "provider") == "Unknown"

    # Model normalization
    def test_model_gpt4o_uppercase(self):
        assert self.processor._normalize_entity_name("GPT-4O", "model") == "gpt-4o"

    def test_model_claude_uppercase(self):
        assert self.processor._normalize_entity_name("CLAUDE-3-5-SONNET", "model") == "claude-3-5-sonnet"

    def test_model_already_normalized(self):
        assert self.processor._normalize_entity_name("gpt-4o", "model") == "gpt-4o"

    def test_model_unknown_passes_through(self):
        assert self.processor._normalize_entity_name("custom-model-v2", "model") == "custom-model-v2"

    # Other entity types
    def test_customer_name_strips_whitespace(self):
        assert self.processor._normalize_entity_name("  AcmeCorp  ", "customer") == "AcmeCorp"

    def test_product_name_strips_whitespace(self):
        assert self.processor._normalize_entity_name("  MyProduct  ", "product") == "MyProduct"


# ─────────────────────────────────────────────────────────────────────────────
# _determine_trend_direction
# ─────────────────────────────────────────────────────────────────────────────


class TestDetermineTrendDirection:
    """Tests for trend direction classification from period cost data."""

    def setup_method(self):
        self.processor = CostAnalyticsProcessor()

    def test_empty_data_returns_stable(self):
        assert self.processor._determine_trend_direction([]) == "stable"

    def test_single_point_returns_stable(self):
        assert self.processor._determine_trend_direction([{"date": "2024-01", "cost": 100}]) == "stable"

    def test_increasing_trend(self):
        """Costs going up by >5% → increasing."""
        data = [
            {"date": "2024-01", "cost": 100.0},
            {"date": "2024-02", "cost": 120.0},
        ]
        assert self.processor._determine_trend_direction(data) == "increasing"

    def test_decreasing_trend(self):
        """Costs going down by >5% → decreasing."""
        data = [
            {"date": "2024-01", "cost": 120.0},
            {"date": "2024-02", "cost": 100.0},
        ]
        assert self.processor._determine_trend_direction(data) == "decreasing"

    def test_stable_trend_within_5_percent(self):
        """Change <5% → stable."""
        data = [
            {"date": "2024-01", "cost": 100.0},
            {"date": "2024-02", "cost": 103.0},
        ]
        assert self.processor._determine_trend_direction(data) == "stable"

    def test_first_cost_zero_returns_stable(self):
        """Zero first cost can't compute percentage → stable."""
        data = [
            {"date": "2024-01", "cost": 0.0},
            {"date": "2024-02", "cost": 100.0},
        ]
        assert self.processor._determine_trend_direction(data) == "stable"

    def test_unsorted_data_is_sorted_by_date(self):
        """Data is sorted by date before comparison."""
        data = [
            {"date": "2024-02", "cost": 200.0},
            {"date": "2024-01", "cost": 100.0},
        ]
        assert self.processor._determine_trend_direction(data) == "increasing"


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_trend_change
# ─────────────────────────────────────────────────────────────────────────────


class TestCalculateTrendChange:
    """Tests for robust trend change percentage calculation."""

    def setup_method(self):
        self.processor = CostAnalyticsProcessor()

    def test_single_point_returns_zero(self):
        assert self.processor._calculate_trend_change([{"cost": 100}]) == 0.0

    def test_two_points_first_vs_last(self):
        """With 2 points, uses simple first vs last."""
        periods = [{"cost": 100.0, "date": "a"}, {"cost": 150.0, "date": "b"}]
        result = self.processor._calculate_trend_change(periods)
        assert result == pytest.approx(50.0, abs=0.1)

    def test_three_points_first_vs_last(self):
        """With 3 points (<=3), uses first vs last."""
        periods = [
            {"cost": 100.0, "date": "a"},
            {"cost": 120.0, "date": "b"},
            {"cost": 200.0, "date": "c"},
        ]
        result = self.processor._calculate_trend_change(periods)
        assert result == pytest.approx(100.0, abs=0.1)

    def test_large_dataset_uses_median_approach(self):
        """With >3 points, uses median-based first-half vs second-half."""
        periods = [
            {"cost": 100.0, "date": "01"},
            {"cost": 110.0, "date": "02"},
            {"cost": 200.0, "date": "03"},
            {"cost": 210.0, "date": "04"},
        ]
        result = self.processor._calculate_trend_change(periods)
        # First half median: (100+110)/2 = 105
        # Second half median: (200+210)/2 = 205
        # Change: (205-105)/105 * 100 ≈ 95.24%
        assert result == pytest.approx(95.24, abs=1.0)

    def test_zero_first_cost_with_positive_last(self):
        """Zero first cost with positive last → 100%."""
        periods = [{"cost": 0.0, "date": "a"}, {"cost": 50.0, "date": "b"}]
        assert self.processor._calculate_trend_change(periods) == 100.0

    def test_zero_baseline_zero_recent(self):
        """Both zero → 0%."""
        periods = [{"cost": 0.0, "date": "a"}, {"cost": 0.0, "date": "b"}]
        assert self.processor._calculate_trend_change(periods) == 0.0

    def test_large_dataset_zero_baseline_median(self):
        """Large dataset where first-half median is 0 but second-half is positive → 100%."""
        periods = [
            {"cost": 0.0, "date": "01"},
            {"cost": 0.0, "date": "02"},
            {"cost": 100.0, "date": "03"},
            {"cost": 200.0, "date": "04"},
        ]
        assert self.processor._calculate_trend_change(periods) == 100.0


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_spike_change
# ─────────────────────────────────────────────────────────────────────────────


class TestCalculateSpikeChange:
    """Tests for spike-specific percentage change calculation."""

    def setup_method(self):
        self.processor = CostAnalyticsProcessor()

    def test_two_points_uses_first_vs_last(self):
        """With <3 points, uses simple first vs last."""
        periods = [{"cost": 100.0}, {"cost": 200.0}]
        result = self.processor._calculate_spike_change(periods)
        assert result == pytest.approx(100.0, abs=0.1)

    def test_baseline_vs_recent_comparison(self):
        """With 3+ points, compares first 33% average to last 33% average."""
        periods = [
            {"cost": 100.0, "date": "01"},
            {"cost": 110.0, "date": "02"},
            {"cost": 120.0, "date": "03"},
            {"cost": 200.0, "date": "04"},
            {"cost": 210.0, "date": "05"},
            {"cost": 220.0, "date": "06"},
        ]
        result = self.processor._calculate_spike_change(periods)
        # Baseline (first 2): avg(100, 110) = 105
        # Recent (last 2): avg(210, 220) = 215
        # Change: (215-105)/105 * 100 ≈ 104.76%
        assert result == pytest.approx(104.76, abs=1.0)

    def test_zero_baseline_returns_zero(self):
        """Zero baseline average → 0%."""
        periods = [
            {"cost": 0.0, "date": "01"},
            {"cost": 0.0, "date": "02"},
            {"cost": 100.0, "date": "03"},
        ]
        assert self.processor._calculate_spike_change(periods) == 0.0

    def test_two_points_zero_first(self):
        """Two points with zero first cost → 0%."""
        periods = [{"cost": 0.0}, {"cost": 100.0}]
        assert self.processor._calculate_spike_change(periods) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_period_change — routing between trend and spike modes
# ─────────────────────────────────────────────────────────────────────────────


class TestCalculatePeriodChange:
    """Tests for period change calculation mode routing."""

    def setup_method(self):
        self.processor = CostAnalyticsProcessor()

    def test_fewer_than_two_points_returns_zero(self):
        assert self.processor._calculate_period_change([], "SEVEN_DAYS") == 0.0
        assert self.processor._calculate_period_change(
            [{"cost": 100, "date": "a"}], "SEVEN_DAYS"
        ) == 0.0

    def test_spike_investigation_uses_spike_mode(self):
        """spike_investigation intent routes to _calculate_spike_change."""
        periods = [
            {"cost": 100.0, "date": "01"},
            {"cost": 200.0, "date": "02"},
        ]
        result = self.processor._calculate_period_change(
            periods, "SEVEN_DAYS", "spike_investigation"
        )
        assert result == pytest.approx(100.0, abs=0.1)

    def test_cost_analysis_uses_trend_mode(self):
        """cost_analysis intent routes to _calculate_trend_change."""
        periods = [
            {"cost": 100.0, "date": "01"},
            {"cost": 150.0, "date": "02"},
        ]
        result = self.processor._calculate_period_change(
            periods, "SEVEN_DAYS", "cost_analysis"
        )
        assert result == pytest.approx(50.0, abs=0.1)


# ─────────────────────────────────────────────────────────────────────────────
# _process_cost_trend_data — processing raw API data into CostTrendData
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessCostTrendData:
    """Tests for raw API response → CostTrendData conversion."""

    def setup_method(self):
        self.processor = CostAnalyticsProcessor()

    def _make_api_response(self, group_name, metric_result, start_timestamp="2024-01-01"):
        """Create a realistic API response structure."""
        return {
            "startTimestamp": start_timestamp,
            "groups": [
                {
                    "groupName": group_name,
                    "metrics": [{"metricResult": metric_result}],
                }
            ],
        }

    def test_processes_provider_data(self):
        """Provider cost data is aggregated into cost_by_provider."""
        cost_data = {
            "cost_by_provider_over_time": self._make_api_response("OpenAI", 100.0),
            "total_cost_by_model": {},
            "cost_by_customer": {},
            "cost_by_product": {},
        }
        result = self.processor._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert isinstance(result, CostTrendData)
        assert result.cost_by_provider == {"OpenAI": 100.0}
        assert result.total_cost == 100.0

    def test_processes_model_data(self):
        """Model cost data is aggregated into cost_by_model."""
        cost_data = {
            "cost_by_provider_over_time": {},
            "total_cost_by_model": self._make_api_response("gpt-4o", 50.0),
            "cost_by_customer": {},
            "cost_by_product": {},
        }
        result = self.processor._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert result.cost_by_model == {"gpt-4o": 50.0}

    def test_processes_customer_data(self):
        """Customer cost data is aggregated into cost_by_customer."""
        cost_data = {
            "cost_by_provider_over_time": {},
            "total_cost_by_model": {},
            "cost_by_customer": self._make_api_response("AcmeCorp", 75.0),
            "cost_by_product": {},
        }
        result = self.processor._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert result.cost_by_customer == {"AcmeCorp": 75.0}

    def test_processes_product_data(self):
        """Product cost data is aggregated into cost_by_product."""
        cost_data = {
            "cost_by_provider_over_time": {},
            "total_cost_by_model": {},
            "cost_by_customer": {},
            "cost_by_product": self._make_api_response("API-Pro", 60.0),
        }
        result = self.processor._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert result.cost_by_product == {"API-Pro": 60.0}

    def test_handles_list_of_time_periods(self):
        """API responses as list of time periods are processed correctly."""
        cost_data = {
            "cost_by_provider_over_time": [
                self._make_api_response("OpenAI", 100.0, "2024-01-01"),
                self._make_api_response("OpenAI", 150.0, "2024-01-02"),
            ],
            "total_cost_by_model": {},
            "cost_by_customer": {},
            "cost_by_product": {},
        }
        result = self.processor._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert result.cost_by_provider == {"OpenAI": 250.0}
        assert result.total_cost == 250.0
        assert len(result.cost_by_period) == 2

    def test_handles_empty_data(self):
        """Empty API data returns zeroed CostTrendData."""
        cost_data = {
            "cost_by_provider_over_time": {},
            "total_cost_by_model": {},
            "cost_by_customer": {},
            "cost_by_product": {},
        }
        result = self.processor._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert result.total_cost == 0.0
        assert result.cost_by_provider == {}
        assert result.trend_direction == "stable"

    def test_handles_malformed_groups_gracefully(self):
        """Non-dict entries in groups are skipped without crashing."""
        cost_data = {
            "cost_by_provider_over_time": {
                "startTimestamp": "2024-01-01",
                "groups": ["not-a-dict", None, 42],
            },
            "total_cost_by_model": {},
            "cost_by_customer": {},
            "cost_by_product": {},
        }
        result = self.processor._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert result.total_cost == 0.0

    def test_handles_non_numeric_metric_result(self):
        """Non-numeric metricResult values are skipped."""
        cost_data = {
            "cost_by_provider_over_time": {
                "startTimestamp": "2024-01-01",
                "groups": [
                    {
                        "groupName": "OpenAI",
                        "metrics": [{"metricResult": "not-a-number"}],
                    }
                ],
            },
            "total_cost_by_model": {},
            "cost_by_customer": {},
            "cost_by_product": {},
        }
        result = self.processor._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert result.cost_by_provider == {}

    def test_normalizes_provider_names(self):
        """Provider names are normalized during processing."""
        cost_data = {
            "cost_by_provider_over_time": self._make_api_response("openai", 100.0),
            "total_cost_by_model": {},
            "cost_by_customer": {},
            "cost_by_product": {},
        }
        result = self.processor._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert "OpenAI" in result.cost_by_provider

    def test_multiple_providers_aggregated(self):
        """Multiple providers in the same time period are aggregated separately."""
        cost_data = {
            "cost_by_provider_over_time": {
                "startTimestamp": "2024-01-01",
                "groups": [
                    {"groupName": "OpenAI", "metrics": [{"metricResult": 100.0}]},
                    {"groupName": "Anthropic", "metrics": [{"metricResult": 50.0}]},
                ],
            },
            "total_cost_by_model": {},
            "cost_by_customer": {},
            "cost_by_product": {},
        }
        result = self.processor._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert result.cost_by_provider == {"OpenAI": 100.0, "Anthropic": 50.0}
        assert result.total_cost == 150.0


# ─────────────────────────────────────────────────────────────────────────────
# _process_breakdown_data
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessBreakdownData:
    """Tests for breakdown data processing from API responses."""

    def setup_method(self):
        self.processor = CostAnalyticsProcessor()

    def test_dict_with_groups(self):
        """Direct dict with groups array is processed correctly."""
        response = {
            "groups": [
                {"groupName": "OpenAI", "metrics": [{"metricResult": 100.0}]},
                {"groupName": "Anthropic", "metrics": [{"metricResult": 50.0}]},
            ]
        }
        result = self.processor._process_breakdown_data(response, "provider")
        assert result["total_cost"] == 150.0
        assert len(result["data"]) == 2

    def test_list_of_time_periods(self):
        """List of time periods with groups is processed correctly."""
        response = [
            {
                "startTimestamp": "2024-01-01",
                "groups": [
                    {"groupName": "OpenAI", "metrics": [{"metricResult": 100.0}]}
                ],
            }
        ]
        result = self.processor._process_breakdown_data(response, "provider")
        assert result["total_cost"] == 100.0

    def test_empty_response(self):
        """Empty response returns zero totals."""
        result = self.processor._process_breakdown_data({}, "provider")
        assert result["total_cost"] == 0.0
        assert result["data"] == []


# ─────────────────────────────────────────────────────────────────────────────
# get_cost_breakdown — validation
# ─────────────────────────────────────────────────────────────────────────────


class TestGetCostBreakdownValidation:
    """Tests for cost breakdown type validation."""

    @pytest.mark.asyncio
    async def test_unsupported_breakdown_type_raises(self):
        """Unsupported breakdown type raises ToolError with suggestions."""
        processor = CostAnalyticsProcessor()
        client = MagicMock()

        with pytest.raises(ToolError) as exc_info:
            await processor.get_cost_breakdown(client, "team-1", "unicorn")
        assert "Unsupported breakdown type" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_supported_breakdown_types(self):
        """All expected breakdown types are recognized."""
        processor = CostAnalyticsProcessor()
        client = MagicMock()
        client.get = AsyncMock(return_value={"groups": []})

        for bt in ["provider", "model", "customer", "product", "agent", "agents"]:
            result = await processor.get_cost_breakdown(client, "team-1", bt)
            assert "total_cost" in result


# ─────────────────────────────────────────────────────────────────────────────
# _identify_spike_contributors
# ─────────────────────────────────────────────────────────────────────────────


class TestIdentifySpikeContributors:
    """Tests for spike contributor identification logic."""

    def setup_method(self):
        self.processor = CostAnalyticsProcessor()

    def test_identifies_provider_contributors(self):
        """Providers with costs above detection threshold appear as contributors."""
        spike_data = {
            "cost_data": {
                "cost_by_provider_over_time": [
                    {
                        "startTimestamp": "2024-01-01",
                        "groups": [
                            {"groupName": "OpenAI", "metrics": [{"metricResult": 500.0}]}
                        ],
                    }
                ],
            },
        }
        baseline_data = {
            "baseline_data": {
                "cost_by_provider_over_time": [
                    {
                        "startTimestamp": "2024-01-01",
                        "groups": [
                            {"groupName": "OpenAI", "metrics": [{"metricResult": 200.0}]}
                        ],
                    }
                ],
            },
        }
        result = self.processor._identify_spike_contributors(spike_data, baseline_data, 100.0)
        assert "contributors" in result
        # The result should contain contributor data
        assert isinstance(result["contributors"], list)

    def test_empty_spike_data_returns_empty_contributors(self):
        """No cost data → empty contributors list."""
        spike_data = {"cost_data": {}}
        baseline_data = {"baseline_data": {}}
        result = self.processor._identify_spike_contributors(spike_data, baseline_data, 100.0)
        assert result["contributors"] == []


# ─────────────────────────────────────────────────────────────────────────────
# analyze_cost_trends — error handling
# ─────────────────────────────────────────────────────────────────────────────


class TestAnalyzeCostTrendsErrors:
    """Tests for error handling in analyze_cost_trends."""

    @pytest.mark.asyncio
    async def test_api_error_raises_tool_error(self):
        """ReveniumAPIError during fetch is wrapped in ToolError with API_ERROR code."""
        from src.revenium_mcp_server.client import ReveniumAPIError

        processor = CostAnalyticsProcessor()
        client = MagicMock()

        with patch.object(
            processor, "_fetch_cost_data",
            new_callable=AsyncMock,
            side_effect=ReveniumAPIError("API failure", 500),
        ):
            with pytest.raises(ToolError) as exc_info:
                await processor.analyze_cost_trends(client, "team-1", "SEVEN_DAYS")
            assert exc_info.value.error_code == ErrorCodes.API_ERROR

    @pytest.mark.asyncio
    async def test_unexpected_error_raises_tool_error(self):
        """Unexpected exception is wrapped in ToolError with PROCESSING_ERROR code."""
        processor = CostAnalyticsProcessor()
        client = MagicMock()

        with patch.object(
            processor, "_fetch_cost_data",
            new_callable=AsyncMock,
            side_effect=ValueError("something broke"),
        ):
            with pytest.raises(ToolError) as exc_info:
                await processor.analyze_cost_trends(client, "team-1", "SEVEN_DAYS")
            assert exc_info.value.error_code == ErrorCodes.PROCESSING_ERROR

    @pytest.mark.asyncio
    async def test_tool_error_re_raised(self):
        """ToolError during processing is re-raised without modification."""
        processor = CostAnalyticsProcessor()
        client = MagicMock()
        original = ToolError(message="original", error_code=ErrorCodes.INVALID_PARAMETER)

        with patch.object(
            processor, "_fetch_cost_data",
            new_callable=AsyncMock,
            side_effect=original,
        ):
            with pytest.raises(ToolError) as exc_info:
                await processor.analyze_cost_trends(client, "team-1", "SEVEN_DAYS")
            assert exc_info.value is original


# ─────────────────────────────────────────────────────────────────────────────
# analyze_cost_spike — error handling
# ─────────────────────────────────────────────────────────────────────────────


class TestAnalyzeCostSpikeErrors:
    """Tests for error handling in analyze_cost_spike."""

    @pytest.mark.asyncio
    async def test_unexpected_error_raises_tool_error(self):
        """Unexpected exception is wrapped in ToolError."""
        processor = CostAnalyticsProcessor()
        client = MagicMock()

        with patch.object(
            processor, "_analyze_spike_period",
            new_callable=AsyncMock,
            side_effect=ValueError("something broke"),
        ):
            with pytest.raises(ToolError) as exc_info:
                await processor.analyze_cost_spike(
                    client, "team-1", {"period": "SEVEN_DAYS"}, 100.0
                )
            assert exc_info.value.error_code == ErrorCodes.PROCESSING_ERROR

    @pytest.mark.asyncio
    async def test_tool_error_re_raised(self):
        """ToolError is re-raised without modification."""
        processor = CostAnalyticsProcessor()
        client = MagicMock()
        original = ToolError(message="original", error_code=ErrorCodes.INVALID_PARAMETER)

        with patch.object(
            processor, "_analyze_spike_period",
            new_callable=AsyncMock,
            side_effect=original,
        ):
            with pytest.raises(ToolError) as exc_info:
                await processor.analyze_cost_spike(
                    client, "team-1", {"period": "SEVEN_DAYS"}, 100.0
                )
            assert exc_info.value is original

    @pytest.mark.asyncio
    async def test_successful_spike_analysis_includes_unified_calc(self):
        """Successful spike analysis includes unified percentage calculation."""
        processor = CostAnalyticsProcessor()
        client = MagicMock()

        spike_data = {
            "cost_data": {
                "cost_by_provider_over_time": [
                    {
                        "startTimestamp": "2024-01-01",
                        "groups": [
                            {"groupName": "OpenAI", "metrics": [{"metricResult": 100.0}]}
                        ],
                    },
                    {
                        "startTimestamp": "2024-01-02",
                        "groups": [
                            {"groupName": "OpenAI", "metrics": [{"metricResult": 200.0}]}
                        ],
                    },
                ],
            },
            "period": "SEVEN_DAYS",
        }
        baseline_data = {"baseline_data": {}}

        with patch.object(
            processor, "_analyze_spike_period",
            new_callable=AsyncMock,
            return_value=spike_data,
        ), patch.object(
            processor, "_get_baseline_costs",
            new_callable=AsyncMock,
            return_value=baseline_data,
        ):
            result = await processor.analyze_cost_spike(
                client, "team-1", {"period": "SEVEN_DAYS"}, 100.0
            )
            assert "_debug_unified_fix_applied" in result
            assert result["_debug_unified_fix_applied"] is True
            assert "unified_percentage_change" in result


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_average_cost_per_request
# ─────────────────────────────────────────────────────────────────────────────


class TestCalculateAverageCostPerRequest:
    """Tests for average cost per request calculation."""

    def test_returns_zero_placeholder(self):
        """Current implementation returns 0.0 as placeholder."""
        processor = CostAnalyticsProcessor()
        result = processor._calculate_average_cost_per_request({"some": "data"})
        assert result == 0.0
