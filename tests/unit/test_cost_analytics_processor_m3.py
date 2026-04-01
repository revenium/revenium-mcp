"""Extended unit tests for CostAnalyticsProcessor — M3 coverage pass.

Targets missed lines in:
  src/revenium_mcp_server/analytics/cost_analytics_processor.py

Focused areas:
- analyze_cost_trends: success path, ReveniumAPIError → ToolError, generic Exception → ToolError
- analyze_cost_spike: success path, spike_cost_data present/absent, generic Exception → ToolError
- get_cost_breakdown: valid breakdown types (provider, model, customer, product, agent, agents),
  invalid breakdown_type → ToolError, product adds group param,
  ReveniumAPIError → ToolError
- _fetch_cost_data: group != TOTAL adds group param; exception results handled gracefully
- _process_cost_trend_data: dict/list/empty provider data; model/customer/product data;
  period_totals accumulated; metrics processing
- _calculate_average_cost_per_request: always returns 0.0
- _calculate_period_change: <2 items → 0.0; spike_investigation intent; small/large datasets
- _calculate_trend_change: small dataset (<=3), large dataset median computation
- _calculate_spike_change: <3 items fallback; baseline/recent comparison
- _determine_trend_direction: <2 items stable; increasing; decreasing; <5% stable
- _analyze_spike_period: duration-based period selection (<=1 day, <=7 days, <=30 days, >30 days);
  fallback on parse error; no start/end uses time_range.period
- _get_baseline_costs: baseline_period extracted from time_range
- _calculate_total_cost_from_spike_data: provider list; model fallback; customer fallback;
  exception → 1000.0; threshold enforcement
- _identify_spike_contributors: provider list analysis; model dict; customer dict; product dict;
  baseline comparison; sorting
- _process_breakdown_data: dict with groups; list of time periods; unexpected type warning;
  exception in processing
- _calculate_spike_trends: empty analysis; time-based grouping; trend direction; peak time
- _generate_baseline_comparison_summary: empty contributors; total_increase;
  significant_changes (>100% and <-50%)
"""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.analytics.cost_analytics_processor import (
    CostAnalyticsProcessor,
    CostTrendData,
)
from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_processor() -> CostAnalyticsProcessor:
    return CostAnalyticsProcessor()


def make_mock_client():
    client = MagicMock()
    client._request_with_retry = AsyncMock(return_value={})
    client.get = AsyncMock(return_value={})
    return client


def make_provider_time_series(provider_name: str, cost: float, timestamp: str = "2024-01-01T00:00:00"):
    return [
        {
            "startTimestamp": timestamp,
            "groups": [
                {
                    "groupName": provider_name,
                    "metrics": [{"metricResult": cost}],
                }
            ],
        }
    ]


def make_groups_dict(group_name: str, cost: float):
    return {
        "groups": [
            {
                "groupName": group_name,
                "metrics": [{"metricResult": cost}],
            }
        ]
    }


# ---------------------------------------------------------------------------
# _calculate_period_change and _calculate_trend_change / _calculate_spike_change
# ---------------------------------------------------------------------------


class TestCalculatePeriodChangeM3:
    def setup_method(self):
        self.p = make_processor()

    def test_empty_list_returns_zero(self):
        assert self.p._calculate_period_change([], "SEVEN_DAYS") == 0.0

    def test_single_item_returns_zero(self):
        data = [{"date": "2024-01-01", "cost": 100.0}]
        assert self.p._calculate_period_change(data, "SEVEN_DAYS") == 0.0

    def test_spike_investigation_intent_uses_spike_change(self):
        data = [
            {"date": "2024-01-01", "cost": 100.0},
            {"date": "2024-01-02", "cost": 200.0},
        ]
        result = self.p._calculate_period_change(data, "SEVEN_DAYS", "spike_investigation")
        # Falls back to first vs last for small dataset
        assert result == pytest.approx(100.0)

    def test_cost_analysis_intent_uses_trend_change(self):
        data = [
            {"date": "2024-01-01", "cost": 100.0},
            {"date": "2024-01-02", "cost": 200.0},
        ]
        result = self.p._calculate_period_change(data, "SEVEN_DAYS", "cost_analysis")
        # Small dataset: first vs last = (200 - 100) / 100 * 100 = 100%
        assert result == pytest.approx(100.0)


class TestCalculateTrendChangeM3:
    def setup_method(self):
        self.p = make_processor()

    def test_empty_returns_zero(self):
        assert self.p._calculate_trend_change([]) == 0.0

    def test_single_item_returns_zero(self):
        assert self.p._calculate_trend_change([{"date": "2024-01-01", "cost": 100.0}]) == 0.0

    def test_two_items_uses_first_vs_last(self):
        data = [
            {"date": "2024-01-01", "cost": 100.0},
            {"date": "2024-01-02", "cost": 150.0},
        ]
        result = self.p._calculate_trend_change(data)
        assert result == pytest.approx(50.0)

    def test_three_items_uses_first_vs_last(self):
        data = [
            {"date": "2024-01-01", "cost": 100.0},
            {"date": "2024-01-02", "cost": 120.0},
            {"date": "2024-01-03", "cost": 200.0},
        ]
        result = self.p._calculate_trend_change(data)
        assert result == pytest.approx(100.0)

    def test_zero_first_cost_with_positive_last_returns_100(self):
        data = [
            {"date": "2024-01-01", "cost": 0.0},
            {"date": "2024-01-02", "cost": 100.0},
        ]
        result = self.p._calculate_trend_change(data)
        assert result == 100.0

    def test_both_zero_returns_zero(self):
        data = [
            {"date": "2024-01-01", "cost": 0.0},
            {"date": "2024-01-02", "cost": 0.0},
        ]
        result = self.p._calculate_trend_change(data)
        assert result == 0.0

    def test_large_dataset_uses_median_comparison(self):
        # 6 items: first half [10, 20, 30] -> median 20; second half [40, 50, 60] -> median 50
        data = [{"date": f"2024-01-0{i}", "cost": float(i * 10)} for i in range(1, 7)]
        result = self.p._calculate_trend_change(data)
        # (50 - 20) / 20 * 100 = 150%
        assert result == pytest.approx(150.0)

    def test_large_dataset_zero_baseline_returns_100(self):
        data = [{"date": f"2024-01-0{i}", "cost": 0.0 if i <= 3 else 100.0} for i in range(1, 7)]
        result = self.p._calculate_trend_change(data)
        assert result == 100.0

    def test_large_dataset_both_medians_zero_returns_zero(self):
        # All costs are 0, so both median halves are 0
        data = [{"date": f"2024-01-{i:02d}", "cost": 0.0} for i in range(1, 7)]
        result = self.p._calculate_trend_change(data)
        assert result == 0.0

    def test_large_dataset_median_odd_each_half(self):
        # Odd-count halves: first [10, 20, 30] median=20; second [40, 50, 60] median=50
        data = [{"date": f"2024-01-{i:02d}", "cost": float(i * 10)} for i in range(1, 7)]
        result = self.p._calculate_trend_change(data)
        # (50 - 20) / 20 * 100 = 150%
        assert result == pytest.approx(150.0)


class TestCalculateSpikeChangeM3:
    def setup_method(self):
        self.p = make_processor()

    def test_single_item_returns_zero(self):
        # The method requires < 3 items to fall back to first vs last
        # With 1 item, first==last so change = 0
        data = [{"date": "2024-01-01", "cost": 100.0}]
        result = self.p._calculate_spike_change(data)
        assert result == 0.0

    def test_two_items_uses_first_vs_last(self):
        data = [
            {"date": "2024-01-01", "cost": 100.0},
            {"date": "2024-01-02", "cost": 200.0},
        ]
        result = self.p._calculate_spike_change(data)
        assert result == pytest.approx(100.0)

    def test_small_dataset_zero_first_returns_zero(self):
        data = [
            {"date": "2024-01-01", "cost": 0.0},
            {"date": "2024-01-02", "cost": 100.0},
        ]
        result = self.p._calculate_spike_change(data)
        assert result == 0.0

    def test_large_dataset_baseline_vs_recent(self):
        # 9 items, baseline (first 3): 10, 10, 10 -> avg 10
        # recent (last 3): 100, 100, 100 -> avg 100
        data = (
            [{"date": f"2024-01-{i:02d}", "cost": 10.0} for i in range(1, 7)]
            + [{"date": f"2024-01-{i:02d}", "cost": 100.0} for i in range(7, 10)]
        )
        result = self.p._calculate_spike_change(data)
        # (100 - 10) / 10 * 100 = 900%
        assert result == pytest.approx(900.0)

    def test_zero_baseline_avg_returns_zero(self):
        data = [{"date": f"2024-01-{i:02d}", "cost": 0.0} for i in range(1, 10)]
        result = self.p._calculate_spike_change(data)
        assert result == 0.0


# ---------------------------------------------------------------------------
# _determine_trend_direction
# ---------------------------------------------------------------------------


class TestDetermineTrendDirectionM3:
    def setup_method(self):
        self.p = make_processor()

    def test_empty_list_returns_stable(self):
        assert self.p._determine_trend_direction([]) == "stable"

    def test_single_item_returns_stable(self):
        assert self.p._determine_trend_direction([{"date": "2024-01-01", "cost": 100.0}]) == "stable"

    def test_increasing_trend(self):
        data = [
            {"date": "2024-01-01", "cost": 100.0},
            {"date": "2024-01-02", "cost": 200.0},
        ]
        assert self.p._determine_trend_direction(data) == "increasing"

    def test_decreasing_trend(self):
        data = [
            {"date": "2024-01-01", "cost": 200.0},
            {"date": "2024-01-02", "cost": 100.0},
        ]
        assert self.p._determine_trend_direction(data) == "decreasing"

    def test_small_change_is_stable(self):
        # 4% change is less than 5%, should be stable
        data = [
            {"date": "2024-01-01", "cost": 100.0},
            {"date": "2024-01-02", "cost": 104.0},
        ]
        assert self.p._determine_trend_direction(data) == "stable"

    def test_zero_first_cost_treated_as_stable(self):
        data = [
            {"date": "2024-01-01", "cost": 0.0},
            {"date": "2024-01-02", "cost": 100.0},
        ]
        # change_percentage = 0 when first_cost == 0
        assert self.p._determine_trend_direction(data) == "stable"


# ---------------------------------------------------------------------------
# _calculate_average_cost_per_request
# ---------------------------------------------------------------------------


class TestCalculateAverageCostPerRequestM3:
    def setup_method(self):
        self.p = make_processor()

    def test_always_returns_zero(self):
        result = self.p._calculate_average_cost_per_request({"key": "value"})
        assert result == 0.0

    def test_works_with_empty_dict(self):
        result = self.p._calculate_average_cost_per_request({})
        assert result == 0.0


# ---------------------------------------------------------------------------
# _process_cost_trend_data
# ---------------------------------------------------------------------------


class TestProcessCostTrendDataM3:
    def setup_method(self):
        self.p = make_processor()

    def test_empty_cost_data_returns_zeros(self):
        result = self.p._process_cost_trend_data({}, "SEVEN_DAYS")
        assert isinstance(result, CostTrendData)
        assert result.total_cost == 0.0
        assert result.cost_by_provider == {}
        assert result.cost_by_model == {}

    def test_provider_list_data_processed(self):
        cost_data = {
            "cost_by_provider_over_time": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": [
                        {"groupName": "openai", "metrics": [{"metricResult": 100.0}]}
                    ],
                }
            ]
        }
        result = self.p._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert result.cost_by_provider.get("OpenAI", 0.0) == pytest.approx(100.0)
        assert result.total_cost == pytest.approx(100.0)

    def test_provider_dict_data_processed(self):
        # Single dict (not list) case
        cost_data = {
            "cost_by_provider_over_time": {
                "startTimestamp": "2024-01-01",
                "groups": [
                    {"groupName": "anthropic", "metrics": [{"metricResult": 50.0}]}
                ],
            }
        }
        result = self.p._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert result.cost_by_provider.get("Anthropic", 0.0) == pytest.approx(50.0)

    def test_provider_invalid_type_skipped(self):
        # Non-dict/list provider data is ignored gracefully
        cost_data = {"cost_by_provider_over_time": "bad_data"}
        result = self.p._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert result.total_cost == 0.0

    def test_model_data_processed(self):
        cost_data = {
            "total_cost_by_model": [
                {
                    "groups": [
                        {"groupName": "GPT-4O", "metrics": [{"metricResult": 75.0}]}
                    ]
                }
            ]
        }
        result = self.p._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert result.cost_by_model.get("gpt-4o", 0.0) == pytest.approx(75.0)

    def test_customer_data_processed(self):
        cost_data = {
            "cost_by_customer": [
                {
                    "groups": [
                        {"groupName": "AcmeCorp", "metrics": [{"metricResult": 200.0}]}
                    ]
                }
            ]
        }
        result = self.p._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert result.cost_by_customer.get("AcmeCorp", 0.0) == pytest.approx(200.0)

    def test_product_data_processed(self):
        cost_data = {
            "cost_by_product": [
                {
                    "groups": [
                        {"groupName": "Analytics", "metrics": [{"metricResult": 120.0}]}
                    ]
                }
            ]
        }
        result = self.p._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert result.cost_by_product.get("Analytics", 0.0) == pytest.approx(120.0)

    def test_period_totals_accumulated(self):
        cost_data = {
            "cost_by_provider_over_time": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": [
                        {"groupName": "openai", "metrics": [{"metricResult": 100.0}]},
                        {"groupName": "anthropic", "metrics": [{"metricResult": 50.0}]},
                    ],
                }
            ]
        }
        result = self.p._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert len(result.cost_by_period) == 1
        assert result.cost_by_period[0]["cost"] == pytest.approx(150.0)

    def test_non_dict_group_skipped(self):
        cost_data = {
            "cost_by_provider_over_time": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": ["not-a-dict"],
                }
            ]
        }
        result = self.p._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert result.total_cost == 0.0

    def test_non_list_groups_skipped(self):
        cost_data = {
            "cost_by_provider_over_time": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": "not-a-list",
                }
            ]
        }
        result = self.p._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert result.total_cost == 0.0

    def test_non_numeric_metric_result_skipped(self):
        cost_data = {
            "cost_by_provider_over_time": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": [
                        {"groupName": "openai", "metrics": [{"metricResult": "bad"}]}
                    ],
                }
            ]
        }
        result = self.p._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert result.total_cost == 0.0

    def test_non_dict_metric_skipped(self):
        cost_data = {
            "cost_by_provider_over_time": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": [
                        {"groupName": "openai", "metrics": ["not-a-dict"]}
                    ],
                }
            ]
        }
        result = self.p._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert result.total_cost == 0.0

    def test_trend_direction_computed(self):
        # Two periods: increasing cost
        cost_data = {
            "cost_by_provider_over_time": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": [{"groupName": "openai", "metrics": [{"metricResult": 100.0}]}],
                },
                {
                    "startTimestamp": "2024-01-02",
                    "groups": [{"groupName": "openai", "metrics": [{"metricResult": 200.0}]}],
                },
            ]
        }
        result = self.p._process_cost_trend_data(cost_data, "SEVEN_DAYS")
        assert result.trend_direction == "increasing"


# ---------------------------------------------------------------------------
# _process_breakdown_data (CostAnalyticsProcessor version)
# ---------------------------------------------------------------------------


class TestProcessBreakdownDataCAP_M3:
    """Tests for CostAnalyticsProcessor._process_breakdown_data (different from ChartDataFormatter's)."""

    def setup_method(self):
        self.p = make_processor()

    def test_dict_with_groups_processed(self):
        response = make_groups_dict("OpenAI", 100.0)
        result = self.p._process_breakdown_data(response, "provider")
        assert result["breakdown_type"] == "provider"
        assert result["total_cost"] == pytest.approx(100.0)
        assert len(result["data"]) == 1
        assert result["data"][0]["name"] == "OpenAI"

    def test_list_of_time_periods_processed(self):
        response = [
            {
                "groups": [
                    {"groupName": "Anthropic", "metrics": [{"metricResult": 75.0}]}
                ]
            }
        ]
        result = self.p._process_breakdown_data(response, "provider")
        assert result["total_cost"] == pytest.approx(75.0)
        assert result["data"][0]["name"] == "Anthropic"

    def test_unexpected_response_type_returns_empty(self):
        result = self.p._process_breakdown_data("unexpected", "provider")
        assert result["data"] == []
        assert result["total_cost"] == 0.0

    def test_empty_list_returns_empty_data(self):
        result = self.p._process_breakdown_data([], "provider")
        assert result["data"] == []

    def test_non_positive_cost_excluded(self):
        response = make_groups_dict("OpenAI", 0.0)
        result = self.p._process_breakdown_data(response, "provider")
        assert result["data"] == []

    def test_non_dict_group_in_dict_response_skipped(self):
        response = {"groups": ["not-a-dict"]}
        result = self.p._process_breakdown_data(response, "provider")
        assert result["data"] == []

    def test_non_list_groups_in_dict_response_skipped(self):
        response = {"groups": "not-a-list"}
        result = self.p._process_breakdown_data(response, "provider")
        assert result["data"] == []

    def test_total_items_count_set(self):
        response = {
            "groups": [
                {"groupName": "A", "metrics": [{"metricResult": 100.0}]},
                {"groupName": "B", "metrics": [{"metricResult": 200.0}]},
            ]
        }
        result = self.p._process_breakdown_data(response, "provider")
        assert result["total_items"] == 2

    def test_processed_at_set(self):
        response = make_groups_dict("OpenAI", 50.0)
        result = self.p._process_breakdown_data(response, "provider")
        assert "processed_at" in result

    def test_non_dict_group_in_list_response_skipped(self):
        response = [{"groups": ["not-a-dict"]}]
        result = self.p._process_breakdown_data(response, "provider")
        assert result["data"] == []


# ---------------------------------------------------------------------------
# _calculate_spike_trends
# ---------------------------------------------------------------------------


class TestCalculateSpikeTrendsM3:
    def setup_method(self):
        self.p = make_processor()

    def test_empty_input_returns_unknown_trend(self):
        result = self.p._calculate_spike_trends([])
        assert result["trend_direction"] == "unknown"
        assert result["peak_time"] is None

    def test_single_entry_processes(self):
        data = [
            {
                "entity_type": "provider",
                "entity_name": "OpenAI",
                "timestamp": "2024-01-01T10:00:00",
                "cost": 100.0,
            }
        ]
        result = self.p._calculate_spike_trends(data)
        assert result["entity_count"] >= 1

    def test_peak_time_identified(self):
        data = [
            {"entity_type": "provider", "entity_name": "OpenAI", "timestamp": "2024-01-01T10:00:00", "cost": 100.0},
            {"entity_type": "provider", "entity_name": "OpenAI", "timestamp": "2024-01-01T11:00:00", "cost": 500.0},
            {"entity_type": "provider", "entity_name": "OpenAI", "timestamp": "2024-01-01T12:00:00", "cost": 200.0},
        ]
        result = self.p._calculate_spike_trends(data)
        assert result["peak_time"] == "2024-01-01T11:00:00"
        assert result["peak_cost"] == 500.0

    def test_hourly_pattern_extracted(self):
        data = [
            {"entity_type": "provider", "entity_name": "A", "timestamp": "2024-01-01T10:00:00", "cost": 50.0},
            {"entity_type": "provider", "entity_name": "A", "timestamp": "2024-01-01T10:30:00", "cost": 50.0},
        ]
        result = self.p._calculate_spike_trends(data)
        assert "10" in result["hourly_pattern"]
        assert result["hourly_pattern"]["10"] == pytest.approx(100.0)

    def test_increasing_trend_detected(self):
        # Create timestamps where second half avg > first half avg * 1.1
        data = [
            {"entity_type": "p", "entity_name": "A", "timestamp": f"2024-01-01T0{i}:00:00", "cost": float(i * 10)}
            for i in range(1, 6)
        ] + [
            {"entity_type": "p", "entity_name": "A", "timestamp": f"2024-01-01T{i+10}:00:00", "cost": float(i * 100)}
            for i in range(1, 6)
        ]
        result = self.p._calculate_spike_trends(data)
        assert result["trend_direction"] == "increasing"

    def test_timestamp_without_T_not_counted_in_hourly(self):
        data = [
            {"entity_type": "p", "entity_name": "A", "timestamp": "20240101", "cost": 100.0}
        ]
        result = self.p._calculate_spike_trends(data)
        # No T in timestamp, so hourly_pattern should be empty
        assert len(result["hourly_pattern"]) == 0


# ---------------------------------------------------------------------------
# _generate_baseline_comparison_summary
# ---------------------------------------------------------------------------


class TestGenerateBaselineComparisonSummaryM3:
    def setup_method(self):
        self.p = make_processor()

    def test_empty_contributors_returns_zeros(self):
        result = self.p._generate_baseline_comparison_summary([])
        assert result["total_increase"] == 0.0
        assert result["entities_with_increase"] == 0
        assert result["entities_with_decrease"] == 0
        assert result["significant_changes"] == []

    def test_total_increase_summed(self):
        contributors = [
            {"type": "provider", "name": "A", "increase": 100.0, "percentage_increase": 50.0},
            {"type": "provider", "name": "B", "increase": 200.0, "percentage_increase": 80.0},
        ]
        result = self.p._generate_baseline_comparison_summary(contributors)
        assert result["total_increase"] == pytest.approx(300.0)

    def test_entities_with_increase_counted(self):
        contributors = [
            {"type": "p", "name": "A", "increase": 100.0, "percentage_increase": 50.0},
            {"type": "p", "name": "B", "increase": -50.0, "percentage_increase": -30.0},
            {"type": "p", "name": "C", "increase": 200.0, "percentage_increase": 120.0},
        ]
        result = self.p._generate_baseline_comparison_summary(contributors)
        assert result["entities_with_increase"] == 2
        assert result["entities_with_decrease"] == 1

    def test_significant_increase_identified(self):
        contributors = [
            {"type": "provider", "name": "OpenAI", "increase": 500.0, "percentage_increase": 150.0},
        ]
        result = self.p._generate_baseline_comparison_summary(contributors)
        assert len(result["significant_changes"]) == 1
        assert result["significant_changes"][0]["significance"] == "major_increase"

    def test_significant_decrease_identified(self):
        contributors = [
            {"type": "provider", "name": "Anthropic", "increase": -300.0, "percentage_increase": -70.0},
        ]
        result = self.p._generate_baseline_comparison_summary(contributors)
        assert len(result["significant_changes"]) == 1
        assert result["significant_changes"][0]["significance"] == "major_decrease"

    def test_moderate_change_not_significant(self):
        contributors = [
            {"type": "provider", "name": "Google", "increase": 50.0, "percentage_increase": 30.0},
        ]
        result = self.p._generate_baseline_comparison_summary(contributors)
        assert len(result["significant_changes"]) == 0

    def test_baseline_comparison_available_true_when_baseline_exists(self):
        contributors = [
            {"type": "p", "name": "A", "increase": 100.0, "percentage_increase": 50.0, "baseline_cost": 200.0},
        ]
        result = self.p._generate_baseline_comparison_summary(contributors)
        assert result["baseline_comparison_available"] is True

    def test_baseline_comparison_available_false_when_no_baseline(self):
        contributors = [
            {"type": "p", "name": "A", "increase": 100.0, "percentage_increase": 100.0, "baseline_cost": 0.0},
        ]
        result = self.p._generate_baseline_comparison_summary(contributors)
        assert result["baseline_comparison_available"] is False


# ---------------------------------------------------------------------------
# _calculate_total_cost_from_spike_data
# ---------------------------------------------------------------------------


class TestCalculateTotalCostFromSpikeDataM3:
    def setup_method(self):
        self.p = make_processor()

    def test_empty_spike_data_returns_min_threshold(self):
        # Empty data → total_cost = 0.0 → max(0, 100.0) since 0 < 50
        result = self.p._calculate_total_cost_from_spike_data({})
        assert result == pytest.approx(100.0)

    def test_provider_list_costs_summed(self):
        spike_cost_data = {
            "cost_by_provider_over_time": [
                {
                    "groups": [
                        {
                            "groupName": "openai",
                            "metrics": [{"metricResult": 500.0}],
                        }
                    ]
                }
            ]
        }
        result = self.p._calculate_total_cost_from_spike_data(spike_cost_data)
        assert result == pytest.approx(500.0)

    def test_large_cost_returned_as_is(self):
        spike_cost_data = {
            "cost_by_provider_over_time": [
                {
                    "groups": [
                        {"groupName": "openai", "metrics": [{"metricResult": 10000.0}]}
                    ]
                }
            ]
        }
        result = self.p._calculate_total_cost_from_spike_data(spike_cost_data)
        assert result == pytest.approx(10000.0)

    def test_model_fallback_used_when_provider_below_10(self):
        # Provider gives tiny amount, model gives more
        spike_cost_data = {
            "cost_by_provider_over_time": [
                {
                    "groups": [
                        {"groupName": "openai", "metrics": [{"metricResult": 5.0}]}
                    ]
                }
            ],
            "total_cost_by_model": {
                "groups": [
                    {"groupName": "gpt-4", "metrics": [{"metricResult": 500.0}]}
                ]
            }
        }
        result = self.p._calculate_total_cost_from_spike_data(spike_cost_data)
        assert result == pytest.approx(500.0)

    def test_customer_fallback_used_when_both_low(self):
        spike_cost_data = {
            "cost_by_provider_over_time": [],
            "total_cost_by_model": {"groups": []},
            "cost_by_customer": {
                "groups": [
                    {"groupName": "Acme", "metrics": [{"metricResult": 300.0}]}
                ]
            }
        }
        result = self.p._calculate_total_cost_from_spike_data(spike_cost_data)
        assert result == pytest.approx(300.0)

    def test_exception_returns_1000(self):
        # Inject data that causes an exception
        class BadData:
            def get(self, *args, **kwargs):
                raise RuntimeError("forced error")

        result = self.p._calculate_total_cost_from_spike_data(BadData())
        assert result == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# _identify_spike_contributors
# ---------------------------------------------------------------------------


class TestIdentifySpikeContributorsM3:
    def setup_method(self):
        self.p = make_processor()

    def _make_spike_data(self, provider_cost: float = 1000.0):
        return {
            "cost_data": {
                "cost_by_provider_over_time": [
                    {
                        "startTimestamp": "2024-01-01T10:00:00",
                        "groups": [
                            {"groupName": "openai", "metrics": [{"metricResult": provider_cost}]}
                        ],
                    }
                ],
                "total_cost_by_model": {},
                "cost_by_customer": {},
                "cost_by_product": {},
            }
        }

    def _make_baseline_data(self):
        return {"baseline_data": {}}

    def test_provider_contributor_identified(self):
        spike_data = self._make_spike_data(1000.0)
        result = self.p._identify_spike_contributors(spike_data, self._make_baseline_data(), 100.0)
        assert result["total_contributors"] >= 1
        provider_contrib = next(
            (c for c in result["contributors"] if c["type"] == "provider"), None
        )
        assert provider_contrib is not None
        assert provider_contrib["name"] == "OpenAI"

    def test_contributors_sorted_by_cost_descending(self):
        spike_data = {
            "cost_data": {
                "cost_by_provider_over_time": [
                    {
                        "startTimestamp": "2024-01-01T10:00:00",
                        "groups": [
                            {"groupName": "openai", "metrics": [{"metricResult": 500.0}]},
                            {"groupName": "anthropic", "metrics": [{"metricResult": 1000.0}]},
                        ],
                    }
                ],
                "total_cost_by_model": {},
                "cost_by_customer": {},
                "cost_by_product": {},
            }
        }
        result = self.p._identify_spike_contributors(spike_data, self._make_baseline_data(), 100.0)
        costs = [c["spike_cost"] for c in result["contributors"]]
        assert costs == sorted(costs, reverse=True)

    def test_model_contributor_identified(self):
        spike_data = {
            "cost_data": {
                "cost_by_provider_over_time": [],
                "total_cost_by_model": make_groups_dict("gpt-4o", 800.0),
                "cost_by_customer": {},
                "cost_by_product": {},
            }
        }
        result = self.p._identify_spike_contributors(spike_data, self._make_baseline_data(), 100.0)
        model_contrib = next(
            (c for c in result["contributors"] if c["type"] == "model"), None
        )
        assert model_contrib is not None
        assert model_contrib["name"] == "gpt-4o"

    def test_customer_contributor_identified(self):
        spike_data = {
            "cost_data": {
                "cost_by_provider_over_time": [],
                "total_cost_by_model": {},
                "cost_by_customer": make_groups_dict("AcmeCorp", 600.0),
                "cost_by_product": {},
            }
        }
        result = self.p._identify_spike_contributors(spike_data, self._make_baseline_data(), 100.0)
        cust_contrib = next(
            (c for c in result["contributors"] if c["type"] == "customer"), None
        )
        assert cust_contrib is not None
        assert cust_contrib["name"] == "AcmeCorp"

    def test_product_contributor_identified(self):
        spike_data = {
            "cost_data": {
                "cost_by_provider_over_time": [],
                "total_cost_by_model": {},
                "cost_by_customer": {},
                "cost_by_product": make_groups_dict("Analytics", 700.0),
            }
        }
        result = self.p._identify_spike_contributors(spike_data, self._make_baseline_data(), 100.0)
        prod_contrib = next(
            (c for c in result["contributors"] if c["type"] == "product"), None
        )
        assert prod_contrib is not None
        assert prod_contrib["name"] == "Analytics"

    def test_analysis_threshold_included(self):
        result = self.p._identify_spike_contributors(
            {"cost_data": {}}, self._make_baseline_data(), 500.0
        )
        assert result["analysis_threshold"] == 500.0

    def test_analyzed_at_set(self):
        result = self.p._identify_spike_contributors(
            {"cost_data": {}}, self._make_baseline_data(), 100.0
        )
        assert "analyzed_at" in result

    def test_baseline_provider_comparison(self):
        """Verify percentage_increase is 100% when no baseline data for provider."""
        spike_data = self._make_spike_data(500.0)
        result = self.p._identify_spike_contributors(spike_data, self._make_baseline_data(), 100.0)
        provider_contrib = next(
            (c for c in result["contributors"] if c["type"] == "provider"), None
        )
        assert provider_contrib is not None, "Expected at least one provider contributor"
        # No baseline → percentage_increase = 100%
        assert provider_contrib["percentage_increase"] == 100.0

    def test_baseline_period_without_groups_skipped(self):
        """Line 1038: time_period in baseline data without groups key is skipped."""
        spike_data = self._make_spike_data(500.0)
        baseline = {
            "baseline_data": {
                "cost_by_provider_over_time": [
                    {"startTimestamp": "2024-01-01"},  # no "groups" key
                    "not-a-dict",  # not a dict
                ]
            }
        }
        # Should not raise, just skip those entries
        result = self.p._identify_spike_contributors(spike_data, baseline, 100.0)
        assert "contributors" in result

    def test_spike_provider_non_dict_group_skipped(self):
        """Lines 1060, 1066: non-dict time_period or group in spike data is skipped."""
        spike_data = {
            "cost_data": {
                "cost_by_provider_over_time": [
                    "not-a-dict",  # skipped at line 1060
                    {
                        "startTimestamp": "2024-01-01",
                        "groups": [
                            "not-a-dict-group",  # skipped at line 1066
                            {"groupName": "openai", "metrics": [{"metricResult": 500.0}]},
                        ],
                    },
                ],
                "total_cost_by_model": {},
                "cost_by_customer": {},
                "cost_by_product": {},
            }
        }
        result = self.p._identify_spike_contributors(spike_data, self._make_baseline_data(), 100.0)
        # Should still find the valid openai contributor
        assert "contributors" in result
        provider_contrib = next(
            (c for c in result["contributors"] if c["type"] == "provider" and c["name"] == "OpenAI"),
            None
        )
        assert provider_contrib is not None

    def test_baseline_with_provider_reduces_percentage(self):
        """Verify baseline_total > 0 path for percentage_increase calculation."""
        spike_data = self._make_spike_data(500.0)
        baseline = {
            "baseline_data": {
                "cost_by_provider_over_time": [
                    {
                        "startTimestamp": "2023-12-01",
                        "groups": [
                            {"groupName": "openai", "metrics": [{"metricResult": 250.0}]}
                        ],
                    }
                ]
            }
        }
        result = self.p._identify_spike_contributors(spike_data, baseline, 100.0)
        provider_contrib = next(
            (c for c in result["contributors"] if c["type"] == "provider"), None
        )
        assert provider_contrib is not None, "Expected at least one provider contributor"
        # spike=500, baseline=250: increase = 250, percentage = 100%
        assert provider_contrib["percentage_increase"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# get_cost_breakdown
# ---------------------------------------------------------------------------


class TestGetCostBreakdownM3:
    def setup_method(self):
        self.p = make_processor()

    @pytest.mark.asyncio
    async def test_unsupported_breakdown_type_raises_tool_error(self):
        client = make_mock_client()
        with pytest.raises(ToolError) as exc_info:
            await self.p.get_cost_breakdown(client, "team-1", "unsupported_type")
        assert "unsupported" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_provider_breakdown_calls_correct_endpoint(self):
        client = make_mock_client()
        client.get = AsyncMock(return_value={"groups": []})
        result = await self.p.get_cost_breakdown(client, "team-1", "provider")
        assert result["breakdown_type"] == "provider"
        client.get.assert_called_once()
        call_args = client.get.call_args
        assert "total-cost-by-provider-over-time" in str(call_args)

    @pytest.mark.asyncio
    async def test_model_breakdown_calls_correct_endpoint(self):
        client = make_mock_client()
        client.get = AsyncMock(return_value={"groups": []})
        result = await self.p.get_cost_breakdown(client, "team-1", "model")
        assert result["breakdown_type"] == "model"
        call_args = client.get.call_args
        assert "total-cost-by-model" in str(call_args)

    @pytest.mark.asyncio
    async def test_product_breakdown_adds_group_param(self):
        client = make_mock_client()
        client.get = AsyncMock(return_value={"groups": []})
        await self.p.get_cost_breakdown(client, "team-1", "product")
        call_kwargs = client.get.call_args
        params = call_kwargs[1].get("params", call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {})
        assert params.get("group") == "TOTAL"

    @pytest.mark.asyncio
    async def test_agent_breakdown_supported(self):
        client = make_mock_client()
        client.get = AsyncMock(return_value={"groups": []})
        result = await self.p.get_cost_breakdown(client, "team-1", "agent")
        assert result["breakdown_type"] == "agent"

    @pytest.mark.asyncio
    async def test_agents_plural_breakdown_supported(self):
        client = make_mock_client()
        client.get = AsyncMock(return_value={"groups": []})
        result = await self.p.get_cost_breakdown(client, "team-1", "agents")
        assert result["breakdown_type"] == "agents"

    @pytest.mark.asyncio
    async def test_api_error_raises_tool_error(self):
        client = make_mock_client()
        client.get = AsyncMock(side_effect=ReveniumAPIError("API failure", status_code=500))
        with pytest.raises(ToolError) as exc_info:
            await self.p.get_cost_breakdown(client, "team-1", "provider")
        assert exc_info.value.error_code == ErrorCodes.API_ERROR


# ---------------------------------------------------------------------------
# analyze_cost_trends
# ---------------------------------------------------------------------------


class TestAnalyzeCostTrendsM3:
    def setup_method(self):
        self.p = make_processor()

    @pytest.mark.asyncio
    async def test_success_path_returns_cost_trend_data(self):
        client = make_mock_client()
        # All sub-calls return empty dicts
        client._request_with_retry = AsyncMock(return_value={})

        result = await self.p.analyze_cost_trends(client, "team-1")
        assert isinstance(result, CostTrendData)
        assert result.total_cost == 0.0

    @pytest.mark.asyncio
    async def test_api_error_raises_tool_error(self):
        client = make_mock_client()
        with patch.object(
            self.p,
            "_fetch_cost_data",
            side_effect=ReveniumAPIError("API failure", status_code=500),
        ):
            with pytest.raises(ToolError) as exc_info:
                await self.p.analyze_cost_trends(client, "team-1")
            assert exc_info.value.error_code == ErrorCodes.API_ERROR

    @pytest.mark.asyncio
    async def test_generic_exception_raises_tool_error(self):
        client = make_mock_client()
        with patch.object(
            self.p, "_fetch_cost_data", side_effect=RuntimeError("unexpected")
        ):
            with pytest.raises(ToolError) as exc_info:
                await self.p.analyze_cost_trends(client, "team-1")
            assert exc_info.value.error_code == ErrorCodes.PROCESSING_ERROR

    @pytest.mark.asyncio
    async def test_tool_error_re_raised_unchanged(self):
        original_error = ToolError(
            message="original error",
            error_code=ErrorCodes.VALIDATION_ERROR,
            field="test",
            value="test",
            suggestions=["fix it"],
        )
        client = make_mock_client()
        with patch.object(self.p, "_fetch_cost_data", side_effect=original_error):
            with pytest.raises(ToolError) as exc_info:
                await self.p.analyze_cost_trends(client, "team-1")
            assert exc_info.value is original_error


# ---------------------------------------------------------------------------
# analyze_cost_spike
# ---------------------------------------------------------------------------


class TestAnalyzeCostSpikeM3:
    def setup_method(self):
        self.p = make_processor()

    def _empty_spike_data(self):
        return {
            "spike_analysis": "implemented",
            "period": "SEVEN_DAYS",
            "cost_data": {},
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _baseline_data(self):
        return {
            "baseline_costs": "implemented",
            "baseline_period": "SEVEN_DAYS",
            "baseline_data": {},
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

    @pytest.mark.asyncio
    async def test_success_path_returns_dict(self):
        client = make_mock_client()
        with patch.object(self.p, "_analyze_spike_period", return_value=self._empty_spike_data()), \
             patch.object(self.p, "_get_baseline_costs", return_value=self._baseline_data()):
            result = await self.p.analyze_cost_spike(
                client, "team-1", {"start": "2024-01-01", "end": "2024-01-07"}, 500.0
            )
        assert "contributors" in result

    @pytest.mark.asyncio
    async def test_spike_cost_data_present_triggers_unified_fix(self):
        spike_data_with_costs = {
            "period": "SEVEN_DAYS",
            "cost_data": {
                "cost_by_provider_over_time": [
                    {
                        "startTimestamp": "2024-01-01",
                        "groups": [{"groupName": "openai", "metrics": [{"metricResult": 500.0}]}],
                    }
                ],
                "total_cost_by_model": {},
                "cost_by_customer": {},
                "cost_by_product": {},
            },
        }
        client = make_mock_client()
        with patch.object(self.p, "_analyze_spike_period", return_value=spike_data_with_costs), \
             patch.object(self.p, "_get_baseline_costs", return_value=self._baseline_data()):
            result = await self.p.analyze_cost_spike(
                client, "team-1", {}, 500.0
            )
        # The unified fix should have been applied: check for the computed fields it sets
        assert "unified_percentage_change" in result
        assert "trend_direction" in result

    @pytest.mark.asyncio
    async def test_generic_exception_raises_tool_error(self):
        client = make_mock_client()
        with patch.object(self.p, "_analyze_spike_period", side_effect=RuntimeError("fail")):
            with pytest.raises(ToolError) as exc_info:
                await self.p.analyze_cost_spike(client, "team-1", {}, 100.0)
            assert exc_info.value.error_code == ErrorCodes.PROCESSING_ERROR


# ---------------------------------------------------------------------------
# _analyze_spike_period
# ---------------------------------------------------------------------------


class TestAnalyzeSpikePeriodM3:
    def setup_method(self):
        self.p = make_processor()

    @pytest.mark.asyncio
    async def test_within_1_day_uses_24h_period(self):
        client = make_mock_client()
        client._request_with_retry = AsyncMock(return_value={})
        time_range = {
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-01T12:00:00Z",
        }
        with patch.object(self.p, "_fetch_cost_data", return_value={}) as mock_fetch:
            await self.p._analyze_spike_period(client, "team-1", time_range)
            mock_fetch.assert_called_once()
            call_kwargs = mock_fetch.call_args
            period = call_kwargs[0][2]
            assert period == "TWENTY_FOUR_HOURS"

    @pytest.mark.asyncio
    async def test_within_7_days_uses_7day_period(self):
        client = make_mock_client()
        start = "2024-01-01T00:00:00Z"
        end = "2024-01-05T00:00:00Z"
        time_range = {"start": start, "end": end}
        with patch.object(self.p, "_fetch_cost_data", return_value={}) as mock_fetch:
            await self.p._analyze_spike_period(client, "team-1", time_range)
            period = mock_fetch.call_args[0][2]
            assert period == "SEVEN_DAYS"

    @pytest.mark.asyncio
    async def test_within_30_days_uses_30day_period(self):
        client = make_mock_client()
        start = "2024-01-01T00:00:00Z"
        end = "2024-01-20T00:00:00Z"
        time_range = {"start": start, "end": end}
        with patch.object(self.p, "_fetch_cost_data", return_value={}) as mock_fetch:
            await self.p._analyze_spike_period(client, "team-1", time_range)
            period = mock_fetch.call_args[0][2]
            assert period == "THIRTY_DAYS"

    @pytest.mark.asyncio
    async def test_over_30_days_uses_90day_period(self):
        client = make_mock_client()
        start = "2024-01-01T00:00:00Z"
        end = "2024-03-01T00:00:00Z"
        time_range = {"start": start, "end": end}
        with patch.object(self.p, "_fetch_cost_data", return_value={}) as mock_fetch:
            await self.p._analyze_spike_period(client, "team-1", time_range)
            period = mock_fetch.call_args[0][2]
            assert period == "NINETY_DAYS"

    @pytest.mark.asyncio
    async def test_invalid_datetime_falls_back_to_7days(self):
        client = make_mock_client()
        time_range = {"start": "not-a-date", "end": "also-not-a-date"}
        with patch.object(self.p, "_fetch_cost_data", return_value={}) as mock_fetch:
            await self.p._analyze_spike_period(client, "team-1", time_range)
            period = mock_fetch.call_args[0][2]
            assert period == "SEVEN_DAYS"

    @pytest.mark.asyncio
    async def test_no_start_end_uses_period_from_time_range(self):
        client = make_mock_client()
        time_range = {"period": "THIRTY_DAYS"}
        with patch.object(self.p, "_fetch_cost_data", return_value={}) as mock_fetch:
            await self.p._analyze_spike_period(client, "team-1", time_range)
            period = mock_fetch.call_args[0][2]
            assert period == "THIRTY_DAYS"

    @pytest.mark.asyncio
    async def test_no_start_end_default_period_is_7days(self):
        client = make_mock_client()
        time_range = {}
        with patch.object(self.p, "_fetch_cost_data", return_value={}) as mock_fetch:
            await self.p._analyze_spike_period(client, "team-1", time_range)
            period = mock_fetch.call_args[0][2]
            assert period == "SEVEN_DAYS"

    @pytest.mark.asyncio
    async def test_returns_dict_with_cost_data(self):
        client = make_mock_client()
        with patch.object(self.p, "_fetch_cost_data", return_value={"key": "val"}):
            result = await self.p._analyze_spike_period(client, "team-1", {})
        assert result["spike_analysis"] == "implemented"
        assert "cost_data" in result


# ---------------------------------------------------------------------------
# _get_baseline_costs
# ---------------------------------------------------------------------------


class TestGetBaselineCostsM3:
    def setup_method(self):
        self.p = make_processor()

    @pytest.mark.asyncio
    async def test_uses_baseline_period_from_time_range(self):
        client = make_mock_client()
        time_range = {"baseline_period": "NINETY_DAYS"}
        with patch.object(self.p, "_fetch_cost_data", return_value={}) as mock_fetch:
            result = await self.p._get_baseline_costs(client, "team-1", time_range)
        assert result["baseline_period"] == "NINETY_DAYS"

    @pytest.mark.asyncio
    async def test_defaults_to_7days_when_no_period(self):
        client = make_mock_client()
        with patch.object(self.p, "_fetch_cost_data", return_value={}) as mock_fetch:
            result = await self.p._get_baseline_costs(client, "team-1", {})
        assert result["baseline_period"] == "SEVEN_DAYS"

    @pytest.mark.asyncio
    async def test_returns_dict_with_baseline_costs_key(self):
        client = make_mock_client()
        with patch.object(self.p, "_fetch_cost_data", return_value={}):
            result = await self.p._get_baseline_costs(client, "team-1", {})
        assert "baseline_costs" in result
        assert "analyzed_at" in result


# ---------------------------------------------------------------------------
# _fetch_cost_data
# ---------------------------------------------------------------------------


class TestFetchCostDataM3:
    def setup_method(self):
        self.p = make_processor()

    @pytest.mark.asyncio
    async def test_cost_by_product_always_receives_group_total(self):
        # cost_by_product hardcodes group=TOTAL in its params regardless of the group argument.
        # The other three endpoints (provider, model, customer) receive no group param.
        client = make_mock_client()
        client._request_with_retry = AsyncMock(return_value={})

        await self.p._fetch_cost_data(client, "team-1", "SEVEN_DAYS", "MEAN")

        assert client._request_with_retry.call_count == 4

        # Find the cost_by_product call (last call, targets cost-metric-by-product)
        all_calls = client._request_with_retry.call_args_list
        product_call = next(
            (c for c in all_calls if "cost-metric-by-product" in c[0][1]),
            None,
        )
        assert product_call is not None
        product_params = product_call[1].get("params", product_call[0][2] if len(product_call[0]) > 2 else {})
        assert product_params.get("group") == "TOTAL"

        # All other endpoints do NOT receive a group param
        other_calls = [c for c in all_calls if "cost-metric-by-product" not in c[0][1]]
        for call in other_calls:
            call_params = call[1].get("params", call[0][2] if len(call[0]) > 2 else {})
            assert "group" not in call_params

    @pytest.mark.asyncio
    async def test_exception_results_handled_gracefully(self):
        client = make_mock_client()
        client._request_with_retry = AsyncMock(side_effect=Exception("network failure"))

        result = await self.p._fetch_cost_data(client, "team-1", "SEVEN_DAYS", "TOTAL")

        # All tasks failed with exceptions, so all results should be error dicts
        for key, val in result.items():
            assert "error" in val or val == {"error": str(Exception("network failure")), "data": []}

    @pytest.mark.asyncio
    async def test_successful_results_stored(self):
        client = make_mock_client()
        client._request_with_retry = AsyncMock(return_value={"groups": []})

        result = await self.p._fetch_cost_data(client, "team-1", "SEVEN_DAYS", "TOTAL")
        assert len(result) == 4
        for val in result.values():
            assert val == {"groups": []}
