"""Unit tests for transaction analytics data processing methods.

Focuses on data processing logic in lines 689-1235 of
transaction_level_analytics_processor.py:
- _process_summary_data: 5-endpoint fetch parsing, averages/totals/performance
- _process_customer_profitability: top N ranking, profit margin, revenue %
- _process_product_profitability: similar to customer but for products

Also covers public entry points that call these:
- analyze_summary_metrics (orchestration + error handling)
- analyze_customer_profitability
- analyze_product_profitability
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.analytics.transaction_level_analytics_processor import (
    TransactionLevelAnalyticsProcessor,
    TransactionLevelData,
    CustomerTransactionData,
    ProductTransactionData,
)
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — API response builders
# ─────────────────────────────────────────────────────────────────────────────


def _api_entry(group_name, metric_result, start_timestamp="2024-01-01T00:00:00Z"):
    """Single time-period API response entry."""
    return {
        "startTimestamp": start_timestamp,
        "groups": [
            {
                "groupName": group_name,
                "metrics": [{"metricResult": metric_result}],
            }
        ],
    }


def _multi_group_entry(groups_data, start_timestamp="2024-01-01T00:00:00Z"):
    """Time-period entry with multiple groups."""
    return {
        "startTimestamp": start_timestamp,
        "groups": [
            {
                "groupName": name,
                "metrics": [{"metricResult": value}],
            }
            for name, value in groups_data
        ],
    }


def _summary_data(
    provider_costs=None,
    avg_costs=None,
    model_costs=None,
    subscriber_costs=None,
    token_rates=None,
):
    """Build a 5-endpoint summary data dict. Pass None for empty/missing."""
    return {
        "total_cost_by_provider_over_time": provider_costs if provider_costs is not None else {},
        "cost_metric_by_provider_over_time": avg_costs if avg_costs is not None else {},
        "total_cost_by_model": model_costs if model_costs is not None else {},
        "cost_metrics_by_subscriber_credential": subscriber_costs if subscriber_costs is not None else {},
        "tokens_per_minute_by_provider": token_rates if token_rates is not None else {},
    }


def _customer_data_multi(org_entries):
    """Build customer data for multiple orgs.

    org_entries: list of (name, cost, revenue, pct_revenue) tuples.
    """
    cost_groups = []
    rev_groups = []
    pct_groups = []
    for name, cost, revenue, pct in org_entries:
        cost_groups.append({"groupName": name, "metrics": [{"metricResult": cost}]})
        rev_groups.append({"groupName": name, "metrics": [{"metricResult": revenue}]})
        pct_groups.append({"groupName": name, "metrics": [{"metricResult": pct}]})
    return {
        "cost_metric_by_organization": [{"startTimestamp": "2024-01-01", "groups": cost_groups}],
        "revenue_metric_by_organization": [{"startTimestamp": "2024-01-01", "groups": rev_groups}],
        "percentage_revenue_metric_by_organization": [{"startTimestamp": "2024-01-01", "groups": pct_groups}],
    }


def _product_data_multi(product_entries):
    """Build product data for multiple products.

    product_entries: list of (name, cost, revenue, pct_revenue) tuples.
    """
    cost_groups = []
    rev_groups = []
    pct_groups = []
    for name, cost, revenue, pct in product_entries:
        cost_groups.append({"groupName": name, "metrics": [{"metricResult": cost}]})
        rev_groups.append({"groupName": name, "metrics": [{"metricResult": revenue}]})
        pct_groups.append({"groupName": name, "metrics": [{"metricResult": pct}]})
    return {
        "cost_metric_by_product": [{"startTimestamp": "2024-01-01", "groups": cost_groups}],
        "revenue_metric_by_product": [{"startTimestamp": "2024-01-01", "groups": rev_groups}],
        "percentage_revenue_metric_by_product": [{"startTimestamp": "2024-01-01", "groups": pct_groups}],
    }


# ─────────────────────────────────────────────────────────────────────────────
# _process_summary_data — provider cost processing
# ─────────────────────────────────────────────────────────────────────────────


class TestSummaryProviderCosts:
    """Provider cost extraction from total_cost_by_provider_over_time."""

    def setup_method(self):
        self.p = TransactionLevelAnalyticsProcessor()

    def test_single_provider_single_period(self):
        data = _summary_data(provider_costs=[_api_entry("OpenAI", 100.0)])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_provider == {"OpenAI": 100.0}
        assert result.total_cost == 100.0

    def test_single_provider_multi_period_aggregation(self):
        data = _summary_data(provider_costs=[
            _api_entry("OpenAI", 100.0, "2024-01-01"),
            _api_entry("OpenAI", 200.0, "2024-01-02"),
            _api_entry("OpenAI", 50.0, "2024-01-03"),
        ])
        result = self.p._process_summary_data(data, "THIRTY_DAYS")
        assert result.cost_by_provider["OpenAI"] == 350.0
        assert result.total_cost == 350.0

    def test_multiple_providers_same_period(self):
        data = _summary_data(provider_costs=[
            _multi_group_entry([("OpenAI", 100.0), ("Anthropic", 200.0), ("Google", 50.0)])
        ])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_provider == {"OpenAI": 100.0, "Anthropic": 200.0, "Google": 50.0}
        assert result.total_cost == 350.0

    def test_multiple_providers_multi_period(self):
        data = _summary_data(provider_costs=[
            _multi_group_entry([("OpenAI", 100.0), ("Anthropic", 50.0)], "2024-01-01"),
            _multi_group_entry([("OpenAI", 200.0), ("Anthropic", 75.0)], "2024-01-02"),
        ])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_provider["OpenAI"] == 300.0
        assert result.cost_by_provider["Anthropic"] == 125.0
        assert result.total_cost == 425.0

    def test_zero_cost_provider_excluded(self):
        """Providers with zero cost are not included in cost_by_provider."""
        data = _summary_data(provider_costs=[_api_entry("FreeTier", 0.0)])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert "FreeTier" not in result.cost_by_provider
        assert result.total_cost == 0.0

    def test_empty_provider_list(self):
        data = _summary_data(provider_costs=[])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_provider == {}
        assert result.total_cost == 0.0

    def test_provider_data_is_dict_not_list(self):
        """Non-list provider data (e.g. error dict) is handled gracefully."""
        data = _summary_data(provider_costs={"error": "something broke"})
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_provider == {}
        assert result.total_cost == 0.0

    def test_provider_data_is_string(self):
        data = _summary_data(provider_costs="invalid")
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.total_cost == 0.0

    def test_non_dict_time_period_entries_skipped(self):
        data = _summary_data(provider_costs=[None, 42, "bad", _api_entry("OpenAI", 100.0)])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_provider == {"OpenAI": 100.0}

    def test_non_dict_group_entries_skipped(self):
        data = _summary_data(provider_costs=[{
            "startTimestamp": "2024-01-01",
            "groups": [None, "bad", {"groupName": "OpenAI", "metrics": [{"metricResult": 50.0}]}],
        }])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_provider == {"OpenAI": 50.0}

    def test_non_dict_metric_entries_skipped(self):
        data = _summary_data(provider_costs=[{
            "startTimestamp": "2024-01-01",
            "groups": [{
                "groupName": "OpenAI",
                "metrics": [None, 42, {"metricResult": 75.0}],
            }],
        }])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_provider == {"OpenAI": 75.0}

    def test_non_numeric_metric_result_skipped(self):
        data = _summary_data(provider_costs=[{
            "startTimestamp": "2024-01-01",
            "groups": [{
                "groupName": "OpenAI",
                "metrics": [{"metricResult": "NaN"}, {"metricResult": "bad"}],
            }],
        }])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_provider == {}

    def test_groups_key_not_list(self):
        data = _summary_data(provider_costs=[{
            "startTimestamp": "2024-01-01",
            "groups": "not-a-list",
        }])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_provider == {}

    def test_metrics_key_not_list(self):
        data = _summary_data(provider_costs=[{
            "startTimestamp": "2024-01-01",
            "groups": [{"groupName": "OpenAI", "metrics": "not-a-list"}],
        }])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_provider == {}

    def test_missing_group_name_defaults_to_unknown(self):
        data = _summary_data(provider_costs=[{
            "startTimestamp": "2024-01-01",
            "groups": [{"metrics": [{"metricResult": 100.0}]}],
        }])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert "Unknown" in result.cost_by_provider


# ─────────────────────────────────────────────────────────────────────────────
# _process_summary_data — model costs
# ─────────────────────────────────────────────────────────────────────────────


class TestSummaryModelCosts:
    """Model cost extraction from total_cost_by_model."""

    def setup_method(self):
        self.p = TransactionLevelAnalyticsProcessor()

    def test_single_model(self):
        data = _summary_data(model_costs=[_api_entry("gpt-4o", 75.0)])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_model == {"gpt-4o": 75.0}

    def test_multiple_models(self):
        data = _summary_data(model_costs=[
            _multi_group_entry([("gpt-4o", 75.0), ("claude-3-opus", 120.0), ("gemini-pro", 30.0)])
        ])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_model == {"gpt-4o": 75.0, "claude-3-opus": 120.0, "gemini-pro": 30.0}

    def test_model_aggregation_across_periods(self):
        data = _summary_data(model_costs=[
            _api_entry("gpt-4o", 50.0, "2024-01-01"),
            _api_entry("gpt-4o", 30.0, "2024-01-02"),
        ])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_model["gpt-4o"] == 80.0

    def test_empty_model_data(self):
        data = _summary_data(model_costs={})
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_model == {}

    def test_zero_cost_model_excluded(self):
        data = _summary_data(model_costs=[_api_entry("free-model", 0.0)])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert "free-model" not in result.cost_by_model

    def test_non_dict_model_data_entries_skipped(self):
        data = _summary_data(model_costs=[None, "bad", _api_entry("gpt-4o", 50.0)])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_model == {"gpt-4o": 50.0}

    def test_non_numeric_model_metric_skipped(self):
        data = _summary_data(model_costs=[{
            "startTimestamp": "2024-01-01",
            "groups": [{"groupName": "gpt-4o", "metrics": [{"metricResult": "invalid"}]}],
        }])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_model == {}


# ─────────────────────────────────────────────────────────────────────────────
# _process_summary_data — subscriber credential costs
# ─────────────────────────────────────────────────────────────────────────────


class TestSummarySubscriberCosts:
    """Subscriber credential cost extraction into cost_by_agent."""

    def setup_method(self):
        self.p = TransactionLevelAnalyticsProcessor()

    def test_single_subscriber(self):
        data = _summary_data(subscriber_costs=[_api_entry("api-key-1", 25.0)])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_agent == {"api-key-1": 25.0}

    def test_multiple_subscribers(self):
        data = _summary_data(subscriber_costs=[
            _multi_group_entry([("key-A", 10.0), ("key-B", 20.0)])
        ])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_agent == {"key-A": 10.0, "key-B": 20.0}

    def test_subscriber_aggregation(self):
        data = _summary_data(subscriber_costs=[
            _api_entry("key-A", 10.0, "2024-01-01"),
            _api_entry("key-A", 15.0, "2024-01-02"),
        ])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_agent["key-A"] == 25.0

    def test_empty_subscriber_data(self):
        data = _summary_data(subscriber_costs={})
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_agent == {}

    def test_zero_cost_subscriber_excluded(self):
        data = _summary_data(subscriber_costs=[_api_entry("free-key", 0.0)])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert "free-key" not in result.cost_by_agent


# ─────────────────────────────────────────────────────────────────────────────
# _process_summary_data — performance metrics (avg cost + tokens/min)
# ─────────────────────────────────────────────────────────────────────────────


class TestSummaryPerformanceMetrics:
    """Performance metrics from avg-cost and tokens-per-minute endpoints."""

    def setup_method(self):
        self.p = TransactionLevelAnalyticsProcessor()

    def test_avg_cost_per_transaction(self):
        data = _summary_data(avg_costs=[_api_entry("OpenAI", 0.05)])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.performance_metrics["OpenAI"]["avg_cost_per_transaction"] == 0.05

    def test_tokens_per_minute(self):
        data = _summary_data(token_rates=[_api_entry("OpenAI", 1500.0)])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.performance_metrics["OpenAI"]["tokens_per_minute"] == 1500.0

    def test_both_metrics_same_provider(self):
        data = _summary_data(
            avg_costs=[_api_entry("OpenAI", 0.03)],
            token_rates=[_api_entry("OpenAI", 2000.0)],
        )
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.performance_metrics["OpenAI"]["avg_cost_per_transaction"] == 0.03
        assert result.performance_metrics["OpenAI"]["tokens_per_minute"] == 2000.0

    def test_different_providers_separate_metrics(self):
        data = _summary_data(
            avg_costs=[_api_entry("OpenAI", 0.05)],
            token_rates=[_api_entry("Anthropic", 1200.0)],
        )
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert "OpenAI" in result.performance_metrics
        assert "Anthropic" in result.performance_metrics

    def test_zero_avg_cost_excluded(self):
        data = _summary_data(avg_costs=[_api_entry("OpenAI", 0.0)])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert "OpenAI" not in result.performance_metrics

    def test_zero_token_rate_excluded(self):
        data = _summary_data(token_rates=[_api_entry("OpenAI", 0.0)])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert "OpenAI" not in result.performance_metrics

    def test_empty_avg_cost_data(self):
        data = _summary_data(avg_costs={})
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.performance_metrics == {}

    def test_empty_token_data(self):
        data = _summary_data(token_rates={})
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.performance_metrics == {}


# ─────────────────────────────────────────────────────────────────────────────
# _process_summary_data — transaction trends
# ─────────────────────────────────────────────────────────────────────────────


class TestSummaryTransactionTrends:
    """Trend data extracted from provider costs with timestamps."""

    def setup_method(self):
        self.p = TransactionLevelAnalyticsProcessor()

    def test_trend_entry_structure(self):
        data = _summary_data(provider_costs=[_api_entry("OpenAI", 100.0, "2024-01-15T00:00:00Z")])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert len(result.transaction_trends) == 1
        trend = result.transaction_trends[0]
        assert trend["date"] == "2024-01-15T00:00:00Z"
        assert trend["cost"] == 100.0
        assert trend["provider"] == "OpenAI"
        assert trend["type"] == "provider_cost"

    def test_multiple_trends_from_multi_period(self):
        data = _summary_data(provider_costs=[
            _api_entry("OpenAI", 100.0, "2024-01-01"),
            _api_entry("OpenAI", 150.0, "2024-01-02"),
            _api_entry("Anthropic", 75.0, "2024-01-03"),
        ])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert len(result.transaction_trends) == 3

    def test_no_trends_without_timestamp(self):
        """Entries without startTimestamp produce no trends."""
        data = _summary_data(provider_costs=[{
            "groups": [{"groupName": "OpenAI", "metrics": [{"metricResult": 100.0}]}],
        }])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        # Cost is still captured, but no trend entry (no startTimestamp)
        assert result.cost_by_provider == {"OpenAI": 100.0}
        assert len(result.transaction_trends) == 0

    def test_zero_cost_no_trend(self):
        """Zero-cost entries don't generate trend entries."""
        data = _summary_data(provider_costs=[_api_entry("OpenAI", 0.0, "2024-01-01")])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert len(result.transaction_trends) == 0


# ─────────────────────────────────────────────────────────────────────────────
# _process_summary_data — derived metrics and period analysis
# ─────────────────────────────────────────────────────────────────────────────


class TestSummaryDerivedMetrics:
    """Derived calculations: total_transactions, average_cost, period_analysis."""

    def setup_method(self):
        self.p = TransactionLevelAnalyticsProcessor()

    def test_total_transactions_equals_trend_count(self):
        data = _summary_data(provider_costs=[
            _api_entry("OpenAI", 100.0, "2024-01-01"),
            _api_entry("OpenAI", 200.0, "2024-01-02"),
        ])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.total_transactions == 2

    def test_average_cost_calculated(self):
        data = _summary_data(provider_costs=[
            _api_entry("OpenAI", 100.0, "2024-01-01"),
            _api_entry("OpenAI", 200.0, "2024-01-02"),
        ])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        # total_cost=300, total_transactions=2, avg=150
        assert result.average_cost_per_transaction == 150.0

    def test_zero_transactions_zero_average(self):
        data = _summary_data()
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.total_transactions == 0
        assert result.average_cost_per_transaction == 0.0

    def test_period_analysis_period_field(self):
        data = _summary_data()
        result = self.p._process_summary_data(data, "THIRTY_DAYS")
        assert result.period_analysis["period"] == "THIRTY_DAYS"

    def test_period_analysis_counts(self):
        data = _summary_data(
            provider_costs=[_multi_group_entry([("OpenAI", 10.0), ("Anthropic", 20.0)])],
            model_costs=[_multi_group_entry([("gpt-4o", 5.0), ("claude-3", 8.0), ("gemini", 3.0)])],
            subscriber_costs=[_api_entry("key-1", 7.0)],
            avg_costs=[_api_entry("OpenAI", 0.01)],
        )
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.period_analysis["provider_count"] == 2
        assert result.period_analysis["model_count"] == 3
        assert result.period_analysis["subscriber_count"] == 1
        assert result.period_analysis["performance_providers"] == 1

    def test_period_analysis_has_processed_at(self):
        data = _summary_data()
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert "processed_at" in result.period_analysis

    def test_period_analysis_total_cost(self):
        data = _summary_data(provider_costs=[_api_entry("OpenAI", 123.45)])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.period_analysis["total_cost"] == 123.45


# ─────────────────────────────────────────────────────────────────────────────
# _process_summary_data — full data integration
# ─────────────────────────────────────────────────────────────────────────────


class TestSummaryFullIntegration:
    """Full-data scenarios exercising all 5 endpoint sections together."""

    def setup_method(self):
        self.p = TransactionLevelAnalyticsProcessor()

    def test_all_five_endpoints_populated(self):
        data = _summary_data(
            provider_costs=[_api_entry("OpenAI", 100.0, "2024-01-01")],
            avg_costs=[_api_entry("OpenAI", 0.05)],
            model_costs=[_api_entry("gpt-4o", 80.0)],
            subscriber_costs=[_api_entry("key-1", 25.0)],
            token_rates=[_api_entry("OpenAI", 1500.0)],
        )
        result = self.p._process_summary_data(data, "SEVEN_DAYS")

        assert isinstance(result, TransactionLevelData)
        assert result.total_cost == 100.0
        assert result.cost_by_provider == {"OpenAI": 100.0}
        assert result.cost_by_model == {"gpt-4o": 80.0}
        assert result.cost_by_agent == {"key-1": 25.0}
        assert result.performance_metrics["OpenAI"]["avg_cost_per_transaction"] == 0.05
        assert result.performance_metrics["OpenAI"]["tokens_per_minute"] == 1500.0
        assert result.total_transactions == 1
        assert result.average_cost_per_transaction == 100.0

    def test_all_endpoints_empty(self):
        data = _summary_data()
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.total_cost == 0.0
        assert result.cost_by_provider == {}
        assert result.cost_by_model == {}
        assert result.cost_by_agent == {}
        assert result.performance_metrics == {}
        assert result.transaction_trends == []
        assert result.total_transactions == 0

    def test_partial_data_provider_only(self):
        data = _summary_data(provider_costs=[_api_entry("Anthropic", 200.0, "2024-01-01")])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.total_cost == 200.0
        assert result.cost_by_model == {}
        assert result.cost_by_agent == {}

    def test_partial_data_model_only(self):
        data = _summary_data(model_costs=[_api_entry("gpt-4o", 50.0)])
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.total_cost == 0.0  # total_cost comes from provider data only
        assert result.cost_by_model == {"gpt-4o": 50.0}

    def test_error_dict_in_endpoint_slot(self):
        """Error responses (dicts with error key) are handled gracefully."""
        data = _summary_data(
            provider_costs={"error": "timeout", "data": []},
            model_costs={"error": "timeout", "data": []},
        )
        result = self.p._process_summary_data(data, "SEVEN_DAYS")
        assert result.total_cost == 0.0
        assert result.cost_by_model == {}


# ─────────────────────────────────────────────────────────────────────────────
# _process_customer_profitability
# ─────────────────────────────────────────────────────────────────────────────


class TestCustomerProfitability:
    """Tests for _process_customer_profitability method."""

    def setup_method(self):
        self.p = TransactionLevelAnalyticsProcessor()

    def test_single_customer_all_fields(self):
        data = _customer_data_multi([("AcmeCorp", 100.0, 250.0, 15.0)])
        result = self.p._process_customer_profitability(data, top_n=10)
        assert len(result) == 1
        c = result[0]
        assert isinstance(c, CustomerTransactionData)
        assert c.organization_name == "AcmeCorp"
        assert c.total_cost == 100.0
        assert c.total_revenue == 250.0
        assert c.net_profit == 150.0
        assert c.profit_margin == 60.0  # (150/250)*100
        assert c.percentage_revenue == 15.0

    def test_profit_margin_calculation(self):
        data = _customer_data_multi([("X", 30.0, 100.0, 0.0)])
        result = self.p._process_customer_profitability(data, top_n=10)
        assert result[0].profit_margin == pytest.approx(70.0, abs=0.1)

    def test_negative_profit(self):
        """Cost > revenue produces negative profit."""
        data = _customer_data_multi([("Loser", 200.0, 50.0, 5.0)])
        result = self.p._process_customer_profitability(data, top_n=10)
        assert result[0].net_profit == -150.0
        assert result[0].profit_margin == pytest.approx(-300.0, abs=0.1)

    def test_zero_revenue_zero_margin(self):
        data = _customer_data_multi([("NoRev", 50.0, 0.0, 0.0)])
        result = self.p._process_customer_profitability(data, top_n=10)
        assert result[0].profit_margin == 0.0

    def test_zero_cost_full_margin(self):
        data = _customer_data_multi([("NoCost", 0.0, 100.0, 10.0)])
        result = self.p._process_customer_profitability(data, top_n=10)
        assert result[0].net_profit == 100.0
        assert result[0].profit_margin == 100.0

    def test_sorted_by_profit_descending(self):
        data = _customer_data_multi([
            ("Low", 90.0, 100.0, 5.0),    # profit=10
            ("Mid", 50.0, 100.0, 10.0),   # profit=50
            ("High", 10.0, 100.0, 15.0),  # profit=90
        ])
        result = self.p._process_customer_profitability(data, top_n=10)
        assert [c.organization_name for c in result] == ["High", "Mid", "Low"]

    def test_top_n_limits_output(self):
        entries = [(f"Org{i}", float(i), float(i * 10), float(i)) for i in range(1, 8)]
        data = _customer_data_multi(entries)
        result = self.p._process_customer_profitability(data, top_n=3)
        assert len(result) == 3

    def test_top_n_larger_than_data(self):
        data = _customer_data_multi([("A", 10.0, 20.0, 5.0)])
        result = self.p._process_customer_profitability(data, top_n=100)
        assert len(result) == 1

    def test_no_fabricated_transaction_fields(self):
        # Cost-derived transaction estimates were removed: real volume comes
        # from the transaction-count-by-team endpoint, not max(1, cost/0.01).
        data = _customer_data_multi([("X", 1.0, 10.0, 5.0)])
        result = self.p._process_customer_profitability(data, top_n=10)
        assert not hasattr(result[0], "transaction_count")
        assert not hasattr(result[0], "cost_per_transaction")

    def test_empty_cost_data(self):
        data = {
            "cost_metric_by_organization": {},
            "revenue_metric_by_organization": {},
            "percentage_revenue_metric_by_organization": {},
        }
        result = self.p._process_customer_profitability(data, top_n=10)
        assert result == []

    def test_empty_lists(self):
        data = {
            "cost_metric_by_organization": [],
            "revenue_metric_by_organization": [],
            "percentage_revenue_metric_by_organization": [],
        }
        result = self.p._process_customer_profitability(data, top_n=10)
        assert result == []

    def test_cost_only_no_revenue(self):
        """Customer with cost data but no revenue data."""
        data = {
            "cost_metric_by_organization": [_api_entry("CostOnly", 50.0)],
            "revenue_metric_by_organization": {},
            "percentage_revenue_metric_by_organization": {},
        }
        result = self.p._process_customer_profitability(data, top_n=10)
        assert len(result) == 1
        assert result[0].total_cost == 50.0
        assert result[0].total_revenue == 0.0
        assert result[0].net_profit == -50.0

    def test_revenue_only_no_cost(self):
        """Customer with revenue data but no cost data."""
        data = {
            "cost_metric_by_organization": {},
            "revenue_metric_by_organization": [_api_entry("RevOnly", 200.0)],
            "percentage_revenue_metric_by_organization": {},
        }
        result = self.p._process_customer_profitability(data, top_n=10)
        assert len(result) == 1
        assert result[0].total_cost == 0.0
        assert result[0].total_revenue == 200.0

    def test_non_dict_time_period_skipped(self):
        data = {
            "cost_metric_by_organization": [None, "bad"],
            "revenue_metric_by_organization": {},
            "percentage_revenue_metric_by_organization": {},
        }
        result = self.p._process_customer_profitability(data, top_n=10)
        assert result == []

    def test_non_dict_group_skipped(self):
        data = {
            "cost_metric_by_organization": [{
                "startTimestamp": "2024-01-01",
                "groups": [None, "bad", {"groupName": "Valid", "metrics": [{"metricResult": 10.0}]}],
            }],
            "revenue_metric_by_organization": {},
            "percentage_revenue_metric_by_organization": {},
        }
        result = self.p._process_customer_profitability(data, top_n=10)
        assert len(result) == 1
        assert result[0].organization_name == "Valid"

    def test_multi_period_aggregation(self):
        """Same org across multiple time periods aggregates costs."""
        data = {
            "cost_metric_by_organization": [
                _api_entry("Acme", 50.0, "2024-01-01"),
                _api_entry("Acme", 75.0, "2024-01-02"),
            ],
            "revenue_metric_by_organization": [
                _api_entry("Acme", 100.0, "2024-01-01"),
                _api_entry("Acme", 200.0, "2024-01-02"),
            ],
            "percentage_revenue_metric_by_organization": {},
        }
        result = self.p._process_customer_profitability(data, top_n=10)
        assert result[0].total_cost == 125.0
        assert result[0].total_revenue == 300.0
        assert result[0].net_profit == 175.0


# ─────────────────────────────────────────────────────────────────────────────
# _process_product_profitability
# ─────────────────────────────────────────────────────────────────────────────


class TestProductProfitability:
    """Tests for _process_product_profitability method."""

    def setup_method(self):
        self.p = TransactionLevelAnalyticsProcessor()

    def test_single_product_all_fields(self):
        data = _product_data_multi([("API-Pro", 80.0, 200.0, 12.0)])
        result = self.p._process_product_profitability(data, top_n=10)
        assert len(result) == 1
        p = result[0]
        assert isinstance(p, ProductTransactionData)
        assert p.product_name == "API-Pro"
        assert p.total_cost == 80.0
        assert p.total_revenue == 200.0
        assert p.net_profit == 120.0
        assert p.profit_margin == 60.0
        assert p.percentage_revenue == 12.0

    def test_profit_margin_calculation(self):
        data = _product_data_multi([("X", 25.0, 100.0, 0.0)])
        result = self.p._process_product_profitability(data, top_n=10)
        assert result[0].profit_margin == 75.0

    def test_negative_profit(self):
        data = _product_data_multi([("Loser", 300.0, 100.0, 5.0)])
        result = self.p._process_product_profitability(data, top_n=10)
        assert result[0].net_profit == -200.0

    def test_zero_revenue_zero_margin(self):
        data = _product_data_multi([("NoRev", 50.0, 0.0, 0.0)])
        result = self.p._process_product_profitability(data, top_n=10)
        assert result[0].profit_margin == 0.0

    def test_zero_cost_full_margin(self):
        data = _product_data_multi([("Free", 0.0, 100.0, 10.0)])
        result = self.p._process_product_profitability(data, top_n=10)
        assert result[0].profit_margin == 100.0

    def test_sorted_by_profit_descending(self):
        data = _product_data_multi([
            ("Low", 95.0, 100.0, 5.0),    # profit=5
            ("Mid", 60.0, 100.0, 10.0),   # profit=40
            ("High", 20.0, 100.0, 15.0),  # profit=80
        ])
        result = self.p._process_product_profitability(data, top_n=10)
        assert [p.product_name for p in result] == ["High", "Mid", "Low"]

    def test_top_n_limits_output(self):
        entries = [(f"Prod{i}", float(i), float(i * 10), float(i)) for i in range(1, 8)]
        data = _product_data_multi(entries)
        result = self.p._process_product_profitability(data, top_n=3)
        assert len(result) == 3

    def test_top_n_larger_than_data(self):
        data = _product_data_multi([("A", 10.0, 20.0, 5.0)])
        result = self.p._process_product_profitability(data, top_n=100)
        assert len(result) == 1

    def test_no_fabricated_transaction_fields(self):
        # Same contract as the customer rows: no cost-derived count estimates.
        data = _product_data_multi([("X", 1.0, 10.0, 5.0)])
        result = self.p._process_product_profitability(data, top_n=10)
        assert not hasattr(result[0], "transaction_count")
        assert not hasattr(result[0], "cost_per_transaction")

    def test_empty_product_data(self):
        data = {
            "cost_metric_by_product": {},
            "revenue_metric_by_product": {},
            "percentage_revenue_metric_by_product": {},
        }
        result = self.p._process_product_profitability(data, top_n=10)
        assert result == []

    def test_empty_lists(self):
        data = {
            "cost_metric_by_product": [],
            "revenue_metric_by_product": [],
            "percentage_revenue_metric_by_product": [],
        }
        result = self.p._process_product_profitability(data, top_n=10)
        assert result == []

    def test_cost_only_no_revenue(self):
        data = {
            "cost_metric_by_product": [_api_entry("CostOnly", 50.0)],
            "revenue_metric_by_product": {},
            "percentage_revenue_metric_by_product": {},
        }
        result = self.p._process_product_profitability(data, top_n=10)
        assert len(result) == 1
        assert result[0].total_cost == 50.0
        assert result[0].total_revenue == 0.0

    def test_revenue_only_no_cost(self):
        data = {
            "cost_metric_by_product": {},
            "revenue_metric_by_product": [_api_entry("RevOnly", 200.0)],
            "percentage_revenue_metric_by_product": {},
        }
        result = self.p._process_product_profitability(data, top_n=10)
        assert len(result) == 1
        assert result[0].total_revenue == 200.0

    def test_non_dict_time_period_skipped(self):
        data = {
            "cost_metric_by_product": [None, "bad"],
            "revenue_metric_by_product": {},
            "percentage_revenue_metric_by_product": {},
        }
        result = self.p._process_product_profitability(data, top_n=10)
        assert result == []

    def test_non_dict_group_skipped(self):
        data = {
            "cost_metric_by_product": [{
                "startTimestamp": "2024-01-01",
                "groups": [None, {"groupName": "Valid", "metrics": [{"metricResult": 10.0}]}],
            }],
            "revenue_metric_by_product": {},
            "percentage_revenue_metric_by_product": {},
        }
        result = self.p._process_product_profitability(data, top_n=10)
        assert len(result) == 1

    def test_multi_period_aggregation(self):
        data = {
            "cost_metric_by_product": [
                _api_entry("Pro", 40.0, "2024-01-01"),
                _api_entry("Pro", 60.0, "2024-01-02"),
            ],
            "revenue_metric_by_product": [
                _api_entry("Pro", 100.0, "2024-01-01"),
                _api_entry("Pro", 150.0, "2024-01-02"),
            ],
            "percentage_revenue_metric_by_product": {},
        }
        result = self.p._process_product_profitability(data, top_n=10)
        assert result[0].total_cost == 100.0
        assert result[0].total_revenue == 250.0
        assert result[0].net_profit == 150.0

    def test_percentage_revenue_aggregated(self):
        data = {
            "cost_metric_by_product": [_api_entry("Pro", 10.0)],
            "revenue_metric_by_product": [_api_entry("Pro", 50.0)],
            "percentage_revenue_metric_by_product": [
                _api_entry("Pro", 5.0, "2024-01-01"),
                _api_entry("Pro", 7.0, "2024-01-02"),
            ],
        }
        result = self.p._process_product_profitability(data, top_n=10)
        assert result[0].percentage_revenue == 12.0


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point: analyze_summary_metrics
# ─────────────────────────────────────────────────────────────────────────────


class TestAnalyzeSummaryMetrics:
    """Tests for the async orchestration of analyze_summary_metrics."""

    @pytest.mark.asyncio
    async def test_success_returns_transaction_level_data(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        fetch_data = _summary_data(
            provider_costs=[_api_entry("OpenAI", 250.0, "2024-01-01")],
            model_costs=[_api_entry("gpt-4o", 200.0)],
        )
        with patch.object(processor, "_fetch_summary_data", new_callable=AsyncMock, return_value=fetch_data):
            result = await processor.analyze_summary_metrics(client, "team-1", "SEVEN_DAYS", "TOTAL")
        assert isinstance(result, TransactionLevelData)
        assert result.total_cost == 250.0
        assert result.cost_by_model == {"gpt-4o": 200.0}

    @pytest.mark.asyncio
    async def test_default_parameters(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        fetch_data = _summary_data(provider_costs=[_api_entry("OpenAI", 10.0, "2024-01-01")])
        with patch.object(processor, "_fetch_summary_data", new_callable=AsyncMock, return_value=fetch_data) as mock_fetch:
            await processor.analyze_summary_metrics(client, "team-1")
            mock_fetch.assert_called_once_with(client, "team-1", "SEVEN_DAYS", "TOTAL")

    @pytest.mark.asyncio
    async def test_tool_error_reraise(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        original = ToolError(message="auth failed", error_code=ErrorCodes.API_ERROR)
        with patch.object(processor, "_fetch_summary_data", new_callable=AsyncMock, side_effect=original):
            with pytest.raises(ToolError) as exc:
                await processor.analyze_summary_metrics(client, "team-1")
            assert exc.value is original

    @pytest.mark.asyncio
    async def test_unexpected_error_wrapped(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        with patch.object(processor, "_fetch_summary_data", new_callable=AsyncMock, side_effect=ValueError("boom")):
            with pytest.raises(ToolError) as exc:
                await processor.analyze_summary_metrics(client, "team-1")
            assert exc.value.error_code == ErrorCodes.PROCESSING_ERROR
            assert "boom" in str(exc.value.message)

    @pytest.mark.asyncio
    async def test_passes_period_and_group_to_fetch(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        fetch_data = _summary_data()
        with patch.object(processor, "_fetch_summary_data", new_callable=AsyncMock, return_value=fetch_data) as mock_fetch:
            await processor.analyze_summary_metrics(client, "team-1", "THIRTY_DAYS", "TOTAL")
            mock_fetch.assert_called_once_with(client, "team-1", "THIRTY_DAYS", "TOTAL")


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point: analyze_customer_profitability
# ─────────────────────────────────────────────────────────────────────────────


class TestAnalyzeCustomerProfitability:
    """Tests for the async orchestration of analyze_customer_profitability."""

    @pytest.mark.asyncio
    async def test_success_returns_customer_list(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        fetch_data = _customer_data_multi([("Acme", 100.0, 300.0, 20.0)])
        with patch.object(processor, "_fetch_customer_data", new_callable=AsyncMock, return_value=fetch_data):
            result = await processor.analyze_customer_profitability(client, "team-1", "SEVEN_DAYS", 10)
        assert len(result) == 1
        assert isinstance(result[0], CustomerTransactionData)
        assert result[0].organization_name == "Acme"

    @pytest.mark.asyncio
    async def test_default_parameters(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        fetch_data = _customer_data_multi([("X", 1.0, 2.0, 1.0)])
        with patch.object(processor, "_fetch_customer_data", new_callable=AsyncMock, return_value=fetch_data) as mock_fetch:
            await processor.analyze_customer_profitability(client, "team-1")
            mock_fetch.assert_called_once_with(client, "team-1", "SEVEN_DAYS", "MEAN")

    @pytest.mark.asyncio
    async def test_tool_error_reraise(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        original = ToolError(message="forbidden", error_code=ErrorCodes.API_ERROR)
        with patch.object(processor, "_fetch_customer_data", new_callable=AsyncMock, side_effect=original):
            with pytest.raises(ToolError) as exc:
                await processor.analyze_customer_profitability(client, "team-1")
            assert exc.value is original

    @pytest.mark.asyncio
    async def test_unexpected_error_wrapped(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        with patch.object(processor, "_fetch_customer_data", new_callable=AsyncMock, side_effect=RuntimeError("network")):
            with pytest.raises(ToolError) as exc:
                await processor.analyze_customer_profitability(client, "team-1")
            assert exc.value.error_code == ErrorCodes.PROCESSING_ERROR

    @pytest.mark.asyncio
    async def test_top_n_passed_to_processing(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        entries = [(f"Org{i}", float(i), float(i * 10), float(i)) for i in range(1, 8)]
        fetch_data = _customer_data_multi(entries)
        with patch.object(processor, "_fetch_customer_data", new_callable=AsyncMock, return_value=fetch_data):
            result = await processor.analyze_customer_profitability(client, "team-1", "SEVEN_DAYS", 2)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_empty_data_returns_empty_list(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        fetch_data = {
            "cost_metric_by_organization": {},
            "revenue_metric_by_organization": {},
            "percentage_revenue_metric_by_organization": {},
        }
        with patch.object(processor, "_fetch_customer_data", new_callable=AsyncMock, return_value=fetch_data):
            result = await processor.analyze_customer_profitability(client, "team-1")
        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point: analyze_product_profitability
# ─────────────────────────────────────────────────────────────────────────────


class TestAnalyzeProductProfitability:
    """Tests for the async orchestration of analyze_product_profitability."""

    @pytest.mark.asyncio
    async def test_success_returns_product_list(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        fetch_data = _product_data_multi([("API-Pro", 80.0, 200.0, 12.0)])
        with patch.object(processor, "_fetch_product_data", new_callable=AsyncMock, return_value=fetch_data):
            result = await processor.analyze_product_profitability(client, "team-1", "SEVEN_DAYS", 10)
        assert len(result) == 1
        assert isinstance(result[0], ProductTransactionData)
        assert result[0].product_name == "API-Pro"

    @pytest.mark.asyncio
    async def test_default_parameters(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        fetch_data = _product_data_multi([("X", 1.0, 2.0, 1.0)])
        with patch.object(processor, "_fetch_product_data", new_callable=AsyncMock, return_value=fetch_data) as mock_fetch:
            await processor.analyze_product_profitability(client, "team-1")
            mock_fetch.assert_called_once_with(client, "team-1", "SEVEN_DAYS", "TOTAL")

    @pytest.mark.asyncio
    async def test_tool_error_reraise(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        original = ToolError(message="forbidden", error_code=ErrorCodes.API_ERROR)
        with patch.object(processor, "_fetch_product_data", new_callable=AsyncMock, side_effect=original):
            with pytest.raises(ToolError) as exc:
                await processor.analyze_product_profitability(client, "team-1")
            assert exc.value is original

    @pytest.mark.asyncio
    async def test_unexpected_error_wrapped(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        with patch.object(processor, "_fetch_product_data", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            with pytest.raises(ToolError) as exc:
                await processor.analyze_product_profitability(client, "team-1")
            assert exc.value.error_code == ErrorCodes.PROCESSING_ERROR

    @pytest.mark.asyncio
    async def test_top_n_passed_to_processing(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        entries = [(f"Prod{i}", float(i), float(i * 10), float(i)) for i in range(1, 8)]
        fetch_data = _product_data_multi(entries)
        with patch.object(processor, "_fetch_product_data", new_callable=AsyncMock, return_value=fetch_data):
            result = await processor.analyze_product_profitability(client, "team-1", "SEVEN_DAYS", 2)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_empty_data_returns_empty_list(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        fetch_data = {
            "cost_metric_by_product": {},
            "revenue_metric_by_product": {},
            "percentage_revenue_metric_by_product": {},
        }
        with patch.object(processor, "_fetch_product_data", new_callable=AsyncMock, return_value=fetch_data):
            result = await processor.analyze_product_profitability(client, "team-1")
        assert result == []
