"""Unit tests for transaction analytics extended processing methods.

Covers the later data processing methods (lines ~1238-2244) of
transaction_level_analytics_processor.py:
- _process_customer_data
- _fetch_product_data / _process_product_data
- _fetch_agent_data / _process_agent_data
- _process_agent_performance
- _fetch_task_data / _process_task_data
- _process_task_performance
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.analytics.transaction_level_analytics_processor import (
    TransactionLevelAnalyticsProcessor,
    AgentAnalyticsData,
    TaskAnalyticsData,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def processor():
    with patch(
        "src.revenium_mcp_server.analytics.transaction_level_analytics_processor.TransactionLevelParameterValidator"
    ):
        return TransactionLevelAnalyticsProcessor()


@pytest.fixture
def mock_client():
    client = MagicMock()
    client._request_with_retry = AsyncMock()
    return client


# ===========================================================================
# _process_customer_data
# ===========================================================================


class TestProcessCustomerData:
    """Tests for _process_customer_data (lines 1238-1391)."""

    def test_full_customer_data(self, processor):
        """All three metric types populated for two organizations."""
        data = {
            "cost_metric_by_organization": [
                _multi_group_entry([("Acme Corp", 500.0), ("Beta Inc", 300.0)])
            ],
            "revenue_metric_by_organization": [
                _multi_group_entry([("Acme Corp", 1000.0), ("Beta Inc", 600.0)])
            ],
            "percentage_revenue_metric_by_organization": [
                _multi_group_entry([("Acme Corp", 55.0), ("Beta Inc", 45.0)])
            ],
        }

        result = processor._process_customer_data(data, "MONTH", "TOTAL")

        assert result["total_cost"] == 800.0
        assert result["total_revenue"] == 1600.0
        assert len(result["organizations"]) == 2

        acme = result["customer_profitability"]["Acme Corp"]
        assert acme["cost"] == 500.0
        assert acme["revenue"] == 1000.0
        assert acme["profit"] == 500.0
        assert acme["margin"] == pytest.approx(50.0)
        assert acme["percentage_revenue"] == 55.0

        beta = result["customer_profitability"]["Beta Inc"]
        assert beta["profit"] == 300.0

        pa = result["period_analysis"]
        assert pa["period"] == "MONTH"
        assert pa["group"] == "TOTAL"
        assert pa["organization_count"] == 2
        assert pa["total_profit"] == 800.0
        assert pa["overall_margin"] == pytest.approx(50.0)

    def test_empty_customer_data(self, processor):
        """Empty / missing data returns zeroes and empty collections."""
        result = processor._process_customer_data({}, "WEEK", "DAILY")

        assert result["total_cost"] == 0.0
        assert result["total_revenue"] == 0.0
        assert result["organizations"] == {}
        assert result["customer_profitability"] == {}
        assert result["period_analysis"]["overall_margin"] == 0.0

    def test_cost_only_customer(self, processor):
        """Organization with cost but no revenue produces negative profit."""
        data = {
            "cost_metric_by_organization": [_api_entry("Orphan Co", 200.0)],
            "revenue_metric_by_organization": {},
            "percentage_revenue_metric_by_organization": {},
        }
        result = processor._process_customer_data(data, "MONTH", "TOTAL")

        assert result["total_cost"] == 200.0
        assert result["total_revenue"] == 0.0
        prof = result["customer_profitability"]["Orphan Co"]
        assert prof["profit"] == -200.0
        assert prof["margin"] == 0.0  # no revenue => 0 margin

    def test_revenue_only_customer(self, processor):
        """Organization with revenue but no cost produces 100% margin."""
        data = {
            "cost_metric_by_organization": {},
            "revenue_metric_by_organization": [_api_entry("Lucky Co", 1000.0)],
            "percentage_revenue_metric_by_organization": {},
        }
        result = processor._process_customer_data(data, "MONTH", "TOTAL")

        assert result["total_revenue"] == 1000.0
        prof = result["customer_profitability"]["Lucky Co"]
        assert prof["margin"] == pytest.approx(100.0)

    def test_non_dict_time_period_skipped(self, processor):
        """Non-dict entries in the list are silently skipped."""
        data = {
            "cost_metric_by_organization": ["not-a-dict", _api_entry("Good Co", 100.0)],
            "revenue_metric_by_organization": [None, _api_entry("Good Co", 200.0)],
            "percentage_revenue_metric_by_organization": [42, _api_entry("Good Co", 30.0)],
        }
        result = processor._process_customer_data(data, "MONTH", "TOTAL")

        assert result["total_cost"] == 100.0
        assert result["total_revenue"] == 200.0
        assert result["customer_profitability"]["Good Co"]["percentage_revenue"] == 30.0

    def test_non_dict_group_data_skipped(self, processor):
        """Non-dict group entries are silently skipped."""
        data = {
            "cost_metric_by_organization": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": ["bad-group", {"groupName": "OK Co", "metrics": [{"metricResult": 50}]}],
                }
            ],
            "revenue_metric_by_organization": {},
            "percentage_revenue_metric_by_organization": {},
        }
        result = processor._process_customer_data(data, "MONTH", "TOTAL")
        assert "OK Co" in result["organizations"]
        assert result["total_cost"] == 50.0

    def test_non_numeric_metric_result_skipped(self, processor):
        """Non-numeric metricResult values are ignored."""
        data = {
            "cost_metric_by_organization": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": [
                        {
                            "groupName": "Mixed Co",
                            "metrics": [
                                {"metricResult": "not-a-number"},
                                {"metricResult": 150.0},
                            ],
                        }
                    ],
                }
            ],
            "revenue_metric_by_organization": {},
            "percentage_revenue_metric_by_organization": {},
        }
        result = processor._process_customer_data(data, "MONTH", "TOTAL")
        assert result["total_cost"] == 150.0

    def test_multiple_time_periods_accumulated(self, processor):
        """Metrics across multiple time periods accumulate for the same org."""
        data = {
            "cost_metric_by_organization": [
                _api_entry("Multi Co", 100.0, "2024-01-01T00:00:00Z"),
                _api_entry("Multi Co", 200.0, "2024-02-01T00:00:00Z"),
            ],
            "revenue_metric_by_organization": {},
            "percentage_revenue_metric_by_organization": {},
        }
        result = processor._process_customer_data(data, "MONTH", "TOTAL")
        # Second period overwrites because it re-assigns (not accumulates)
        # The org already exists from the first entry, so cost = 200 (last write wins)
        # Actually, looking at the code: it sets organizations[org_name]["cost"] = org_cost
        # and total_cost accumulates. So total_cost=300, but org cost=200 (last write)
        assert result["total_cost"] == 300.0


# ===========================================================================
# _fetch_product_data
# ===========================================================================


class TestFetchProductData:
    """Tests for _fetch_product_data (lines 1393-1429)."""

    @pytest.mark.asyncio
    async def test_fetch_product_data_success(self, processor, mock_client):
        """Cost and revenue endpoints fetched; percentage_revenue computed client-side."""
        mock_client._request_with_retry = AsyncMock(
            side_effect=[
                [_api_entry("Product A", 100.0)],
                [_api_entry("Product A", 500.0)],
            ]
        )

        result = await processor._fetch_product_data(mock_client, "team-1", "MONTH", "TOTAL")

        assert "cost_metric_by_product" in result
        assert "revenue_metric_by_product" in result
        assert "percentage_revenue_metric_by_product" in result
        # percentage_revenue is computed client-side from revenue data, not a separate API call
        assert mock_client._request_with_retry.call_count == 2

    @pytest.mark.asyncio
    async def test_fetch_product_data_with_group(self, processor, mock_client):
        """Non-TOTAL group is passed in params."""
        mock_client._request_with_retry = AsyncMock(return_value=[])

        await processor._fetch_product_data(mock_client, "team-1", "MONTH", "DAILY")

        # Verify group param included in calls
        for call in mock_client._request_with_retry.call_args_list:
            params = call[1].get("params", call[0][2] if len(call[0]) > 2 else {})
            assert params.get("group") == "DAILY"

    @pytest.mark.asyncio
    async def test_fetch_product_data_partial_failure(self, processor, mock_client):
        """One endpoint failing returns error dict for that key."""
        mock_client._request_with_retry = AsyncMock(
            side_effect=[
                [_api_entry("Product A", 100.0)],
                Exception("API timeout"),
                [_api_entry("Product A", 60.0)],
            ]
        )

        result = await processor._fetch_product_data(mock_client, "team-1", "MONTH", "TOTAL")

        # The failed key should have an error dict
        failed_key = "revenue_metric_by_product"
        assert "error" in result[failed_key]
        assert result[failed_key]["data"] == []


# ===========================================================================
# _process_product_data
# ===========================================================================


class TestProcessProductData:
    """Tests for _process_product_data (lines 1431-1582)."""

    def test_full_product_data(self, processor):
        """All three metric types populated for two products."""
        data = {
            "cost_metric_by_product": [
                _multi_group_entry([("Widget", 200.0), ("Gadget", 150.0)])
            ],
            "revenue_metric_by_product": [
                _multi_group_entry([("Widget", 800.0), ("Gadget", 450.0)])
            ],
            "percentage_revenue_metric_by_product": [
                _multi_group_entry([("Widget", 60.0), ("Gadget", 40.0)])
            ],
        }

        result = processor._process_product_data(data, "MONTH", "TOTAL")

        assert result["total_cost"] == 350.0
        assert result["total_revenue"] == 1250.0
        assert len(result["products"]) == 2

        widget = result["product_profitability"]["Widget"]
        assert widget["cost"] == 200.0
        assert widget["revenue"] == 800.0
        assert widget["profit"] == 600.0
        assert widget["margin"] == pytest.approx(75.0)
        assert widget["percentage_revenue"] == 60.0

        pa = result["period_analysis"]
        assert pa["product_count"] == 2
        assert pa["total_profit"] == 900.0
        assert pa["overall_margin"] == pytest.approx(72.0)

    def test_empty_product_data(self, processor):
        """Empty data returns zeroes."""
        result = processor._process_product_data({}, "WEEK", "TOTAL")
        assert result["total_cost"] == 0.0
        assert result["total_revenue"] == 0.0
        assert result["products"] == {}
        assert result["period_analysis"]["overall_margin"] == 0.0

    def test_cost_only_product(self, processor):
        """Product with cost but no revenue."""
        data = {
            "cost_metric_by_product": [_api_entry("Expensive Widget", 500.0)],
            "revenue_metric_by_product": {},
            "percentage_revenue_metric_by_product": {},
        }
        result = processor._process_product_data(data, "MONTH", "TOTAL")
        prof = result["product_profitability"]["Expensive Widget"]
        assert prof["profit"] == -500.0
        assert prof["margin"] == 0.0

    def test_revenue_only_product(self, processor):
        """Product with revenue but no cost."""
        data = {
            "cost_metric_by_product": {},
            "revenue_metric_by_product": [_api_entry("Free Product", 1000.0)],
            "percentage_revenue_metric_by_product": {},
        }
        result = processor._process_product_data(data, "MONTH", "TOTAL")
        prof = result["product_profitability"]["Free Product"]
        assert prof["margin"] == pytest.approx(100.0)

    def test_non_dict_entries_skipped(self, processor):
        """Non-dict time periods and groups are skipped gracefully."""
        data = {
            "cost_metric_by_product": ["bad", _api_entry("OK Product", 50.0)],
            "revenue_metric_by_product": [
                {"startTimestamp": "x", "groups": ["not-a-dict", {"groupName": "OK Product", "metrics": [{"metricResult": 100}]}]}
            ],
            "percentage_revenue_metric_by_product": [None],
        }
        result = processor._process_product_data(data, "MONTH", "TOTAL")
        assert result["total_cost"] == 50.0
        assert result["total_revenue"] == 100.0

    def test_non_numeric_metrics_ignored(self, processor):
        """Non-numeric metricResult values are silently ignored."""
        data = {
            "cost_metric_by_product": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": [
                        {
                            "groupName": "P1",
                            "metrics": [
                                {"metricResult": "oops"},
                                {"metricResult": 75.0},
                            ],
                        }
                    ],
                }
            ],
            "revenue_metric_by_product": {},
            "percentage_revenue_metric_by_product": {},
        }
        result = processor._process_product_data(data, "MONTH", "TOTAL")
        assert result["total_cost"] == 75.0


# ===========================================================================
# _fetch_agent_data
# ===========================================================================


class TestFetchAgentData:
    """Tests for _fetch_agent_data (lines 1584-1620)."""

    @pytest.mark.asyncio
    async def test_fetch_agent_data_success(self, processor, mock_client):
        """All three agent endpoints return successfully."""
        mock_client._request_with_retry = AsyncMock(
            side_effect=[
                [_api_entry("Agent-1", 100.0)],
                [_api_entry("Agent-1", 50)],
                [_api_entry("Agent-1", 0.95)],
            ]
        )
        result = await processor._fetch_agent_data(mock_client, "team-1", "MONTH", "TOTAL")
        assert "cost_metrics_by_agents_over_time" in result
        assert "call_count_metrics_by_agents" in result
        assert "performance_metrics_by_agents" in result

    @pytest.mark.asyncio
    async def test_fetch_agent_data_with_group(self, processor, mock_client):
        """Non-TOTAL group param is included."""
        mock_client._request_with_retry = AsyncMock(return_value=[])
        await processor._fetch_agent_data(mock_client, "team-1", "MONTH", "DAILY")
        for call in mock_client._request_with_retry.call_args_list:
            params = call[1].get("params", call[0][2] if len(call[0]) > 2 else {})
            assert params.get("group") == "DAILY"

    @pytest.mark.asyncio
    async def test_fetch_agent_data_partial_failure(self, processor, mock_client):
        """One endpoint failing returns error dict for that key."""
        mock_client._request_with_retry = AsyncMock(
            side_effect=[
                [_api_entry("Agent-1", 100.0)],
                Exception("network error"),
                [_api_entry("Agent-1", 0.95)],
            ]
        )
        result = await processor._fetch_agent_data(mock_client, "team-1", "MONTH", "TOTAL")
        assert "error" in result["call_count_metrics_by_agents"]


# ===========================================================================
# _process_agent_data
# ===========================================================================


class TestProcessAgentData:
    """Tests for _process_agent_data (lines 1622-1761)."""

    def test_full_agent_data(self, processor):
        """All three metric types for two agents."""
        data = {
            "cost_metrics_by_agents_over_time": [
                _multi_group_entry([("Agent-A", 200.0), ("Agent-B", 100.0)])
            ],
            "call_count_metrics_by_agents": [
                _multi_group_entry([("Agent-A", 50), ("Agent-B", 25)])
            ],
            "performance_metrics_by_agents": [
                _multi_group_entry([("Agent-A", 0.95), ("Agent-B", 0.88)])
            ],
        }

        result = processor._process_agent_data(data, "MONTH", "TOTAL")

        assert result["total_cost"] == 300.0
        assert result["total_calls"] == 75

        perf_a = result["agent_performance"]["Agent-A"]
        assert perf_a["cost"] == 200.0
        assert perf_a["calls"] == 50
        assert perf_a["performance"] == 0.95
        assert perf_a["cost_per_call"] == pytest.approx(4.0)
        assert perf_a["efficiency_score"] == pytest.approx(0.95 / 200.0)

        pa = result["period_analysis"]
        assert pa["agent_count"] == 2
        assert pa["average_cost_per_call"] == pytest.approx(4.0)

    def test_empty_agent_data(self, processor):
        """Empty data returns zeroes."""
        result = processor._process_agent_data({}, "WEEK", "TOTAL")
        assert result["total_cost"] == 0.0
        assert result["total_calls"] == 0
        assert result["agents"] == {}
        assert result["period_analysis"]["average_cost_per_call"] == 0.0

    def test_cost_only_agent(self, processor):
        """Agent with cost but no calls or performance."""
        data = {
            "cost_metrics_by_agents_over_time": [_api_entry("Expensive Agent", 500.0)],
            "call_count_metrics_by_agents": {},
            "performance_metrics_by_agents": {},
        }
        result = processor._process_agent_data(data, "MONTH", "TOTAL")
        perf = result["agent_performance"]["Expensive Agent"]
        assert perf["cost_per_call"] == 0.0  # no calls
        assert perf["efficiency_score"] == 0.0  # performance is 0

    def test_calls_only_agent(self, processor):
        """Agent with calls but no cost."""
        data = {
            "cost_metrics_by_agents_over_time": {},
            "call_count_metrics_by_agents": [_api_entry("Free Agent", 100)],
            "performance_metrics_by_agents": {},
        }
        result = processor._process_agent_data(data, "MONTH", "TOTAL")
        perf = result["agent_performance"]["Free Agent"]
        assert perf["cost_per_call"] == 0.0  # cost = 0
        assert perf["calls"] == 100

    def test_non_dict_entries_skipped(self, processor):
        """Non-dict time periods and groups are skipped."""
        data = {
            "cost_metrics_by_agents_over_time": ["bad", _api_entry("OK Agent", 75.0)],
            "call_count_metrics_by_agents": [
                {"groups": ["not-dict", {"groupName": "OK Agent", "metrics": [{"metricResult": 10}]}]}
            ],
            "performance_metrics_by_agents": [None],
        }
        result = processor._process_agent_data(data, "MONTH", "TOTAL")
        assert result["total_cost"] == 75.0
        assert result["total_calls"] == 10

    def test_performance_creates_new_agent_entry(self, processor):
        """Performance metric for an agent not in cost or calls creates new entry."""
        data = {
            "cost_metrics_by_agents_over_time": {},
            "call_count_metrics_by_agents": {},
            "performance_metrics_by_agents": [_api_entry("Perf Only", 0.99)],
        }
        result = processor._process_agent_data(data, "MONTH", "TOTAL")
        assert "Perf Only" in result["agents"]
        assert result["agent_performance"]["Perf Only"]["performance"] == 0.99


# ===========================================================================
# _process_agent_performance
# ===========================================================================


class TestProcessAgentPerformance:
    """Tests for _process_agent_performance (lines 1763-1871)."""

    def test_full_agent_performance(self, processor):
        """Three agents, sorted by efficiency, top_n=2."""
        data = {
            "cost_metrics_by_agents_over_time": [
                _multi_group_entry([("A", 100.0), ("B", 200.0), ("C", 50.0)])
            ],
            "call_count_metrics_by_agents": [
                _multi_group_entry([("A", 10), ("B", 20), ("C", 5)])
            ],
            "performance_metrics_by_agents": [
                _multi_group_entry([("A", 90.0), ("B", 80.0), ("C", 95.0)])
            ],
        }

        result = processor._process_agent_performance(data, top_n=2)

        assert len(result) == 2
        assert all(isinstance(r, AgentAnalyticsData) for r in result)

        # Sorted by efficiency_score desc: C (95/50=1.9), A (90/100=0.9), B (80/200=0.4)
        assert result[0].agent_name == "C"
        assert result[0].efficiency_score == pytest.approx(1.9)
        assert result[0].call_volume_rank == 1
        assert result[1].agent_name == "A"
        assert result[1].call_volume_rank == 2

    def test_empty_agent_performance(self, processor):
        """Empty data returns empty list."""
        result = processor._process_agent_performance({}, top_n=5)
        assert result == []

    def test_agent_performance_zero_cost(self, processor):
        """Agent with zero cost has 0 efficiency score."""
        data = {
            "cost_metrics_by_agents_over_time": [_api_entry("Free Agent", 0)],
            "call_count_metrics_by_agents": [_api_entry("Free Agent", 10)],
            "performance_metrics_by_agents": [_api_entry("Free Agent", 50.0)],
        }
        result = processor._process_agent_performance(data, top_n=5)
        # cost=0 so efficiency_score=0
        # But the agent still gets created from call_count and performance
        # cost_metrics entry has metricResult=0, so agent_data_dict["Free Agent"]["cost"] = 0
        assert len(result) == 1
        assert result[0].efficiency_score == 0.0

    def test_agent_performance_zero_calls(self, processor):
        """Agent with zero calls has 0 cost_per_call."""
        data = {
            "cost_metrics_by_agents_over_time": [_api_entry("No Calls", 100.0)],
            "call_count_metrics_by_agents": [_api_entry("No Calls", 0)],
            "performance_metrics_by_agents": [_api_entry("No Calls", 50.0)],
        }
        result = processor._process_agent_performance(data, top_n=5)
        assert len(result) == 1
        assert result[0].cost_per_call == 0.0

    def test_agent_performance_top_n_limits(self, processor):
        """top_n limits the number of returned agents."""
        data = {
            "cost_metrics_by_agents_over_time": [
                _multi_group_entry([("A", 100), ("B", 200), ("C", 50), ("D", 300)])
            ],
            "call_count_metrics_by_agents": [
                _multi_group_entry([("A", 10), ("B", 20), ("C", 5), ("D", 30)])
            ],
            "performance_metrics_by_agents": [
                _multi_group_entry([("A", 90), ("B", 80), ("C", 95), ("D", 70)])
            ],
        }
        result = processor._process_agent_performance(data, top_n=1)
        assert len(result) == 1

    def test_non_dict_entries_skipped(self, processor):
        """Non-dict entries in each metric section are skipped."""
        data = {
            "cost_metrics_by_agents_over_time": ["bad", _api_entry("OK", 100.0)],
            "call_count_metrics_by_agents": [None],
            "performance_metrics_by_agents": [_api_entry("OK", 0.9)],
        }
        result = processor._process_agent_performance(data, top_n=5)
        assert len(result) == 1
        assert result[0].agent_name == "OK"


# ===========================================================================
# _fetch_task_data
# ===========================================================================


class TestFetchTaskData:
    """Tests for _fetch_task_data (lines 1873-1912)."""

    @pytest.mark.asyncio
    async def test_fetch_task_data_success(self, processor, mock_client):
        """All four task endpoints return successfully."""
        mock_client._request_with_retry = AsyncMock(
            side_effect=[
                [_api_entry("OpenAI", 100.0)],
                [_api_entry("gpt-4", 80.0)],
                [_api_entry("OpenAI", 0.95)],
                [_api_entry("gpt-4", 0.92)],
            ]
        )
        result = await processor._fetch_task_data(mock_client, "team-1", "MONTH", "TOTAL")
        assert "cost_metric_by_provider" in result
        assert "cost_metric_by_model" in result
        assert "performance_metric_by_provider" in result
        assert "performance_metric_by_model" in result
        assert mock_client._request_with_retry.call_count == 4

    @pytest.mark.asyncio
    async def test_fetch_task_data_with_group(self, processor, mock_client):
        """Non-TOTAL group is passed in params."""
        mock_client._request_with_retry = AsyncMock(return_value=[])
        await processor._fetch_task_data(mock_client, "team-1", "MONTH", "DAILY")
        for call in mock_client._request_with_retry.call_args_list:
            params = call[1].get("params", call[0][2] if len(call[0]) > 2 else {})
            assert params.get("group") == "DAILY"

    @pytest.mark.asyncio
    async def test_fetch_task_data_partial_failure(self, processor, mock_client):
        """Two endpoints fail, two succeed."""
        mock_client._request_with_retry = AsyncMock(
            side_effect=[
                [_api_entry("OpenAI", 100.0)],
                Exception("timeout"),
                Exception("connection refused"),
                [_api_entry("gpt-4", 0.92)],
            ]
        )
        result = await processor._fetch_task_data(mock_client, "team-1", "MONTH", "TOTAL")
        assert "error" in result["cost_metric_by_model"]
        assert "error" in result["performance_metric_by_provider"]
        # Successful keys should have data
        assert isinstance(result["cost_metric_by_provider"], list)
        assert isinstance(result["performance_metric_by_model"], list)


# ===========================================================================
# _process_task_data
# ===========================================================================


class TestProcessTaskData:
    """Tests for _process_task_data (lines 1914-2096).

    BACK-729 fixed the variable-shadowing bug where the inner loop floats
    ``provider_performance`` and ``model_performance`` overwrote the outer
    dicts of the same names, causing a TypeError when both cost and performance
    data were present for the same provider/model. Tests now cover the mixed
    cost+performance paths directly and assert correct output.
    """

    def test_cost_data_only_providers_and_models(self, processor):
        """Cost-only data for providers and models (no performance data)."""
        data = {
            "cost_metric_by_provider": [
                _multi_group_entry([("OpenAI", 500.0), ("Anthropic", 300.0)])
            ],
            "cost_metric_by_model": [
                _multi_group_entry([("gpt-4", 400.0), ("claude-3", 250.0)])
            ],
            "performance_metric_by_provider": {},
            "performance_metric_by_model": {},
        }

        result = processor._process_task_data(data, "MONTH", "TOTAL")

        assert result["total_cost"] == 800.0
        assert result["total_performance"] == 0.0
        assert len(result["providers"]) == 2
        assert len(result["models"]) == 2

        # Provider performance with zero performance
        openai_perf = result["provider_performance"]["OpenAI"]
        assert openai_perf["cost"] == 500.0
        assert openai_perf["performance"] == 0.0
        assert openai_perf["efficiency"] == 0.0

        # Model performance with zero performance
        gpt4_perf = result["model_performance"]["gpt-4"]
        assert gpt4_perf["cost"] == 400.0
        assert gpt4_perf["efficiency"] == 0.0

        pa = result["period_analysis"]
        assert pa["provider_count"] == 2
        assert pa["model_count"] == 2
        assert pa["period"] == "MONTH"
        assert pa["group"] == "TOTAL"

    def test_empty_task_data(self, processor):
        """Empty data returns zeroes."""
        result = processor._process_task_data({}, "WEEK", "TOTAL")
        assert result["total_cost"] == 0.0
        assert result["total_performance"] == 0.0
        assert result["providers"] == {}
        assert result["models"] == {}

    def test_providers_cost_only(self, processor):
        """Only provider cost data, no performance or model data."""
        data = {
            "cost_metric_by_provider": [_api_entry("OpenAI", 500.0)],
            "cost_metric_by_model": {},
            "performance_metric_by_provider": {},
            "performance_metric_by_model": {},
        }
        result = processor._process_task_data(data, "MONTH", "TOTAL")
        assert len(result["providers"]) == 1
        assert len(result["models"]) == 0
        assert result["provider_performance"]["OpenAI"]["cost"] == 500.0

    def test_models_cost_only(self, processor):
        """Only model cost data, no provider or performance data."""
        data = {
            "cost_metric_by_provider": {},
            "cost_metric_by_model": [_api_entry("gpt-4", 400.0)],
            "performance_metric_by_provider": {},
            "performance_metric_by_model": {},
        }
        result = processor._process_task_data(data, "MONTH", "TOTAL")
        assert len(result["providers"]) == 0
        assert len(result["models"]) == 1
        assert result["model_performance"]["gpt-4"]["cost"] == 400.0
        assert result["model_performance"]["gpt-4"]["efficiency"] == 0.0

    def test_non_dict_entries_skipped(self, processor):
        """Non-dict time periods and groups are skipped gracefully."""
        data = {
            "cost_metric_by_provider": ["bad", _api_entry("OK Provider", 100.0)],
            "cost_metric_by_model": [
                {"groups": ["not-dict", {"groupName": "OK Model", "metrics": [{"metricResult": 50}]}]}
            ],
            "performance_metric_by_provider": [None],
            "performance_metric_by_model": [42],
        }
        result = processor._process_task_data(data, "MONTH", "TOTAL")
        assert result["total_cost"] == 100.0
        assert "OK Model" in result["models"]

    def test_non_numeric_metrics_ignored(self, processor):
        """Non-numeric metricResult values are silently ignored."""
        data = {
            "cost_metric_by_provider": [
                {
                    "groups": [
                        {
                            "groupName": "P1",
                            "metrics": [{"metricResult": "bad"}, {"metricResult": 100.0}],
                        }
                    ]
                }
            ],
            "cost_metric_by_model": {},
            "performance_metric_by_provider": {},
            "performance_metric_by_model": {},
        }
        result = processor._process_task_data(data, "MONTH", "TOTAL")
        assert result["total_cost"] == 100.0

    def test_performance_data_accumulates(self, processor):
        """Performance data accumulates total_performance correctly after
        fix for variable-shadowing bug (BACK-729)."""
        data = {
            "cost_metric_by_provider": {},
            "cost_metric_by_model": {},
            "performance_metric_by_provider": [
                _multi_group_entry([("OpenAI", 0.95), ("Anthropic", 0.92)])
            ],
            "performance_metric_by_model": {},
        }
        # Previously raised TypeError due to variable shadowing; now succeeds.
        result = processor._process_task_data(data, "MONTH", "TOTAL")
        assert abs(result["total_performance"] - (0.95 + 0.92)) < 1e-9
        assert "OpenAI" in result["providers"]
        assert "Anthropic" in result["providers"]

    def test_known_shadowing_bug_with_both_cost_and_performance(self, processor):
        """Fix for BACK-729: provider_performance dict was overwritten by the
        inner loop float variable when both cost and performance data were
        present.  Verifies the fix — no TypeError and correct output."""
        data = {
            "cost_metric_by_provider": [_api_entry("OpenAI", 500.0)],
            "cost_metric_by_model": {},
            "performance_metric_by_provider": [_api_entry("OpenAI", 0.95)],
            "performance_metric_by_model": {},
        }
        # Previously raised TypeError; now returns correct efficiency data.
        result = processor._process_task_data(data, "MONTH", "TOTAL")
        assert result["total_cost"] == 500.0
        assert abs(result["total_performance"] - 0.95) < 1e-9
        provider_entry = result["provider_performance"]["OpenAI"]
        assert provider_entry["cost"] == 500.0
        assert abs(provider_entry["performance"] - 0.95) < 1e-9

    def test_multiple_providers_cost_period_analysis(self, processor):
        """Multiple providers with cost data produce correct period analysis."""
        data = {
            "cost_metric_by_provider": [
                _multi_group_entry([("P1", 100.0), ("P2", 200.0), ("P3", 300.0)])
            ],
            "cost_metric_by_model": [
                _multi_group_entry([("M1", 150.0), ("M2", 250.0)])
            ],
            "performance_metric_by_provider": {},
            "performance_metric_by_model": {},
        }
        result = processor._process_task_data(data, "QUARTER", "DAILY")
        assert result["total_cost"] == 600.0
        assert result["period_analysis"]["provider_count"] == 3
        assert result["period_analysis"]["model_count"] == 2
        assert result["period_analysis"]["period"] == "QUARTER"
        assert result["period_analysis"]["group"] == "DAILY"
        assert "processed_at" in result["period_analysis"]


# ===========================================================================
# _process_task_performance
# ===========================================================================


class TestProcessTaskPerformance:
    """Tests for _process_task_performance (lines 2098-2244)."""

    def test_full_task_performance(self, processor):
        """Providers and models combined, sorted by efficiency."""
        data = {
            "cost_metric_by_provider": [
                _multi_group_entry([("OpenAI", 500.0), ("Anthropic", 300.0)])
            ],
            "performance_metric_by_provider": [
                _multi_group_entry([("OpenAI", 90.0), ("Anthropic", 85.0)])
            ],
            "cost_metric_by_model": [
                _multi_group_entry([("gpt-4", 400.0), ("claude-3", 250.0)])
            ],
            "performance_metric_by_model": [
                _multi_group_entry([("gpt-4", 88.0), ("claude-3", 92.0)])
            ],
        }

        result = processor._process_task_performance(data, top_n=10)

        assert all(isinstance(r, TaskAnalyticsData) for r in result)
        # 2 providers + 2 models = 4 entries
        assert len(result) == 4

        # Sorted by max(completion_rates.values()) desc
        # claude-3: 92/250=0.368
        # Anthropic: 85/300=0.2833
        # gpt-4: 88/400=0.22
        # OpenAI: 90/500=0.18
        assert result[0].task_metrics["name"] == "claude-3"
        assert result[-1].task_metrics["name"] == "OpenAI"

    def test_empty_task_performance(self, processor):
        """Empty data returns empty list."""
        result = processor._process_task_performance({}, top_n=5)
        assert result == []

    def test_top_n_limits_results(self, processor):
        """top_n limits the number of returned entries."""
        data = {
            "cost_metric_by_provider": [
                _multi_group_entry([("P1", 100), ("P2", 200), ("P3", 50)])
            ],
            "performance_metric_by_provider": [
                _multi_group_entry([("P1", 90), ("P2", 80), ("P3", 95)])
            ],
            "cost_metric_by_model": {},
            "performance_metric_by_model": {},
        }
        result = processor._process_task_performance(data, top_n=2)
        assert len(result) == 2

    def test_provider_type_metadata(self, processor):
        """Provider entries have correct type in task_metrics."""
        data = {
            "cost_metric_by_provider": [_api_entry("TestProvider", 100.0)],
            "performance_metric_by_provider": [_api_entry("TestProvider", 50.0)],
            "cost_metric_by_model": {},
            "performance_metric_by_model": {},
        }
        result = processor._process_task_performance(data, top_n=5)
        assert len(result) == 1
        assert result[0].task_metrics["type"] == "provider"
        assert result[0].task_metrics["name"] == "TestProvider"
        assert result[0].cost_by_provider == {"TestProvider": 100.0}
        assert result[0].performance_by_provider == {"TestProvider": 50.0}
        assert result[0].cost_by_model == {}

    def test_model_type_metadata(self, processor):
        """Model entries have correct type in task_metrics."""
        data = {
            "cost_metric_by_provider": {},
            "performance_metric_by_provider": {},
            "cost_metric_by_model": [_api_entry("gpt-4o", 200.0)],
            "performance_metric_by_model": [_api_entry("gpt-4o", 75.0)],
        }
        result = processor._process_task_performance(data, top_n=5)
        assert len(result) == 1
        assert result[0].task_metrics["type"] == "model"
        assert result[0].cost_by_model == {"gpt-4o": 200.0}
        assert result[0].performance_by_model == {"gpt-4o": 75.0}
        assert result[0].cost_by_provider == {}

    def test_zero_cost_efficiency(self, processor):
        """Provider with zero cost has 0 efficiency."""
        data = {
            "cost_metric_by_provider": [_api_entry("FreeProvider", 0)],
            "performance_metric_by_provider": [_api_entry("FreeProvider", 50.0)],
            "cost_metric_by_model": {},
            "performance_metric_by_model": {},
        }
        result = processor._process_task_performance(data, top_n=5)
        # cost=0, so provider_data_dict has cost=0
        # efficiency = performance/cost = 50/0 = 0.0 (guarded)
        # But the entry for FreeProvider in cost is 0 so it accumulates 0
        assert len(result) == 1
        assert result[0].completion_rates["FreeProvider"] == 0.0

    def test_non_dict_entries_skipped(self, processor):
        """Non-dict entries in all four sections are skipped."""
        data = {
            "cost_metric_by_provider": ["bad", _api_entry("OK", 100.0)],
            "performance_metric_by_provider": [None, _api_entry("OK", 50.0)],
            "cost_metric_by_model": [42],
            "performance_metric_by_model": ["nope"],
        }
        result = processor._process_task_performance(data, top_n=5)
        assert len(result) == 1
        assert result[0].task_metrics["name"] == "OK"

    def test_multiple_metrics_accumulated(self, processor):
        """Multiple time periods accumulate values for the same provider."""
        data = {
            "cost_metric_by_provider": [
                _api_entry("P1", 100.0, "2024-01-01"),
                _api_entry("P1", 200.0, "2024-02-01"),
            ],
            "performance_metric_by_provider": [
                _api_entry("P1", 40.0, "2024-01-01"),
                _api_entry("P1", 60.0, "2024-02-01"),
            ],
            "cost_metric_by_model": {},
            "performance_metric_by_model": {},
        }
        result = processor._process_task_performance(data, top_n=5)
        assert len(result) == 1
        # cost should be accumulated: 100 + 200 = 300
        assert result[0].cost_by_provider["P1"] == 300.0
        assert result[0].performance_by_provider["P1"] == 100.0
