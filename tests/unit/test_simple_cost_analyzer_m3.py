"""Extended unit tests for SimpleCostAnalyzer (M3 coverage pass).

Covers the async methods and remaining branch paths missed by the initial
test_simple_cost_analyzer.py:
- get_provider_costs (all response formats + error paths)
- get_model_costs    (all response formats + error paths)
- get_customer_costs (all response formats + error paths)
- get_api_key_costs  (all response formats + error paths)
- get_agent_costs    (all response formats + error paths)
- get_cost_summary
- investigate_cost_spike
- _process_provider_data edge cases (invalid groups list, non-dict entries)
- _process_api_key_data edge cases
- _process_agent_data edge cases
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.analytics.simple_cost_analyzer import SimpleCostAnalyzer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_analyzer(team_id="team-test-001"):
    """Return an analyzer backed by a mock client with team_id set."""
    client = MagicMock()
    client.team_id = team_id
    client.get = AsyncMock()
    return SimpleCostAnalyzer(client)


def _make_analyzer_no_team():
    """Return an analyzer backed by a mock client without team_id."""
    client = MagicMock()
    client.team_id = None
    client.get = AsyncMock()
    return SimpleCostAnalyzer(client)


# ---------------------------------------------------------------------------
# get_provider_costs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetProviderCosts:
    """Tests for get_provider_costs async method."""

    async def test_returns_processed_list_from_list_response(self):
        """Direct list response is processed correctly."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = [
            {"groupName": "OpenAI", "metrics": [{"metricResult": 500.0}]},
            {"groupName": "Anthropic", "metrics": [{"metricResult": 300.0}]},
        ]
        result = await analyzer.get_provider_costs("LAST_30_DAYS", "TOTAL")
        assert isinstance(result, list)
        assert len(result) == 2
        # Sorted descending by cost
        assert result[0]["provider"] == "OpenAI"
        assert result[0]["cost"] == 500.0
        assert result[1]["provider"] == "Anthropic"

    async def test_returns_processed_list_from_wrapped_dict_response(self):
        """Response wrapped in {'data': [...]} is unwrapped."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = {
            "data": [
                {"groupName": "Google", "metrics": [{"metricResult": 200.0}]},
            ]
        }
        result = await analyzer.get_provider_costs("LAST_7_DAYS", "TOTAL")
        assert len(result) == 1
        assert result[0]["provider"] == "Google"

    async def test_empty_response_returns_empty_list(self):
        """Falsy response returns []."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = None
        result = await analyzer.get_provider_costs("LAST_30_DAYS", "TOTAL")
        assert result == []

    async def test_empty_list_response_returns_empty_list(self):
        """Empty list response returns []."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = []
        result = await analyzer.get_provider_costs("LAST_30_DAYS", "TOTAL")
        assert result == []

    async def test_unexpected_data_format_returns_empty_list(self):
        """Dict without 'data' key where extracted data is non-list returns []."""
        analyzer = _make_analyzer()
        # get("data", []) returns [], which is falsy → early return []
        analyzer.client.get.return_value = {"other_key": "value"}
        result = await analyzer.get_provider_costs("LAST_30_DAYS", "TOTAL")
        assert result == []

    async def test_raises_when_no_team_id_on_client_and_no_env(self, monkeypatch):
        """Raises Exception when team_id unavailable everywhere."""
        monkeypatch.delenv("REVENIUM_TEAM_ID", raising=False)
        analyzer = _make_analyzer_no_team()
        with pytest.raises(Exception, match="Team ID not available"):
            await analyzer.get_provider_costs("LAST_30_DAYS", "TOTAL")

    async def test_uses_env_team_id_when_client_has_none(self, monkeypatch):
        """Falls back to REVENIUM_TEAM_ID env var when client.team_id is None."""
        monkeypatch.setenv("REVENIUM_TEAM_ID", "env-team-xyz")
        analyzer = _make_analyzer_no_team()
        analyzer.client.get.return_value = []
        result = await analyzer.get_provider_costs("LAST_30_DAYS", "TOTAL")
        assert result == []
        # Confirm the API was called (meaning team_id was resolved)
        analyzer.client.get.assert_called_once()

    async def test_re_raises_api_exception(self):
        """Exceptions from client.get are re-raised."""
        analyzer = _make_analyzer()
        analyzer.client.get.side_effect = RuntimeError("API down")
        with pytest.raises(RuntimeError, match="API down"):
            await analyzer.get_provider_costs("LAST_30_DAYS", "TOTAL")

    async def test_percentage_calculated_correctly(self):
        """Cost percentages sum to 100 for two providers."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = [
            {"groupName": "OpenAI", "metrics": [{"metricResult": 400.0}]},
            {"groupName": "Azure", "metrics": [{"metricResult": 600.0}]},
        ]
        result = await analyzer.get_provider_costs("LAST_30_DAYS", "TOTAL")
        pct_sum = sum(r["percentage"] for r in result)
        assert pct_sum == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# get_model_costs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetModelCosts:
    """Tests for get_model_costs async method."""

    async def test_dict_with_groups_format(self):
        """Response is a dict with 'groups' key (total endpoint format)."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = {
            "groups": [
                {"groupName": "gpt-4", "metrics": [{"metricResult": 800.0}]},
                {"groupName": "claude-3", "metrics": [{"metricResult": 200.0}]},
            ]
        }
        result = await analyzer.get_model_costs("LAST_30_DAYS", "TOTAL")
        assert len(result) == 2
        assert result[0]["model"] == "gpt-4"
        assert result[0]["cost"] == 800.0
        assert result[0]["percentage"] == pytest.approx(80.0)

    async def test_list_with_nested_groups_time_series_format(self):
        """Response is list of time entries each with 'groups'."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = [
            {
                "timestamp": "2024-01-01",
                "groups": [
                    {"groupName": "gpt-4", "metrics": [{"metricResult": 100.0}]},
                    {"groupName": "gpt-3.5", "metrics": [{"metricResult": 50.0}]},
                ],
            },
            {
                "timestamp": "2024-01-02",
                "groups": [
                    {"groupName": "gpt-4", "metrics": [{"metricResult": 150.0}]},
                ],
            },
        ]
        result = await analyzer.get_model_costs("LAST_7_DAYS", "DAILY")
        # gpt-4 accumulates 250 across two entries
        gpt4 = next(r for r in result if r["model"] == "gpt-4")
        assert gpt4["cost"] == pytest.approx(250.0)
        gpt35 = next(r for r in result if r["model"] == "gpt-3.5")
        assert gpt35["cost"] == pytest.approx(50.0)

    async def test_direct_list_of_model_objects(self):
        """Response is simple list of model objects with direct cost fields."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = [
            {"model": "gemini-pro", "cost": 120.0},
            {"model": "llama3", "metricResult": 80.0},
        ]
        result = await analyzer.get_model_costs("LAST_30_DAYS", "TOTAL")
        models = {r["model"] for r in result}
        assert "gemini-pro" in models

    async def test_direct_list_with_metrics_nested(self):
        """Direct list items with nested metrics structure."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = [
            {
                "groupName": "whisper",
                "metrics": [{"metricResult": 60.0}],
            }
        ]
        result = await analyzer.get_model_costs("LAST_30_DAYS", "TOTAL")
        assert len(result) == 1
        assert result[0]["model"] == "whisper"
        assert result[0]["cost"] == pytest.approx(60.0)

    async def test_raises_when_no_team_id(self, monkeypatch):
        monkeypatch.delenv("REVENIUM_TEAM_ID", raising=False)
        analyzer = _make_analyzer_no_team()
        with pytest.raises(Exception, match="Team ID not available"):
            await analyzer.get_model_costs("LAST_30_DAYS", "TOTAL")

    async def test_re_raises_api_exception(self):
        analyzer = _make_analyzer()
        analyzer.client.get.side_effect = ValueError("bad request")
        with pytest.raises(ValueError, match="bad request"):
            await analyzer.get_model_costs("LAST_30_DAYS", "TOTAL")

    async def test_zero_cost_items_excluded_from_dict_groups(self):
        """Items with zero metricResult are not added to processed_data."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = {
            "groups": [
                {"groupName": "gpt-4", "metrics": [{"metricResult": 0.0}]},
                {"groupName": "claude-3", "metrics": [{"metricResult": 100.0}]},
            ]
        }
        result = await analyzer.get_model_costs("LAST_30_DAYS", "TOTAL")
        assert len(result) == 1
        assert result[0]["model"] == "claude-3"

    async def test_sorted_by_cost_descending(self):
        """Results are sorted highest cost first."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = [
            {"model": "cheap", "cost": 10.0},
            {"model": "expensive", "cost": 9000.0},
        ]
        result = await analyzer.get_model_costs("LAST_30_DAYS", "TOTAL")
        assert result[0]["model"] == "expensive"

    async def test_direct_list_uses_total_cost_field(self):
        """totalCost field in direct list items is used when cost absent."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = [
            {"model": "model-a", "totalCost": 250.0},
        ]
        result = await analyzer.get_model_costs("LAST_30_DAYS", "TOTAL")
        assert len(result) == 1
        assert result[0]["cost"] == pytest.approx(250.0)

    async def test_env_team_id_fallback(self, monkeypatch):
        """Falls back to env var for team_id."""
        monkeypatch.setenv("REVENIUM_TEAM_ID", "env-fallback-team")
        analyzer = _make_analyzer_no_team()
        analyzer.client.get.return_value = {"groups": []}
        result = await analyzer.get_model_costs("LAST_30_DAYS", "TOTAL")
        assert result == []


# ---------------------------------------------------------------------------
# get_customer_costs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetCustomerCosts:
    """Tests for get_customer_costs async method."""

    async def test_dict_with_groups_wrapped_in_list(self):
        """Single dict with groups is wrapped in a list and processed as time-series."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = {
            "groups": [
                {"groupName": "Acme Corp", "metrics": [{"metricResult": 1200.0}]},
                {"groupName": "BetaCo", "metrics": [{"metricResult": 400.0}]},
            ]
        }
        result = await analyzer.get_customer_costs("LAST_30_DAYS", "TOTAL")
        assert len(result) == 2
        assert result[0]["customer"] == "Acme Corp"
        assert result[0]["cost"] == pytest.approx(1200.0)
        assert result[0]["percentage"] == pytest.approx(75.0)

    async def test_list_response_direct_format(self):
        """Plain list of customer objects."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = [
            {"organization": "OrgA", "cost": 300.0},
            {"customer": "OrgB", "cost": 700.0},
        ]
        result = await analyzer.get_customer_costs("LAST_7_DAYS", "TOTAL")
        names = {r["customer"] for r in result}
        assert "OrgA" in names
        assert "OrgB" in names

    async def test_list_with_groups_time_series(self):
        """List of time-series entries with nested groups."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = [
            {
                "timestamp": "2024-01-01",
                "groups": [
                    {"groupName": "Corp X", "metrics": [{"metricResult": 500.0}]},
                ],
            },
            {
                "timestamp": "2024-01-02",
                "groups": [
                    {"groupName": "Corp X", "metrics": [{"metricResult": 300.0}]},
                ],
            },
        ]
        result = await analyzer.get_customer_costs("LAST_7_DAYS", "DAILY")
        assert len(result) == 1
        assert result[0]["customer"] == "Corp X"
        assert result[0]["cost"] == pytest.approx(800.0)

    async def test_wrapped_dict_response(self):
        """Response wrapped in {'data': [...]} is extracted."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = {
            "data": [
                {"customer": "wrapped-customer", "cost": 100.0},
            ]
        }
        result = await analyzer.get_customer_costs("LAST_30_DAYS", "TOTAL")
        # wrapped response where data has no groups → direct format processing
        assert any(r["customer"] == "wrapped-customer" for r in result)

    async def test_raises_when_no_team_id(self, monkeypatch):
        monkeypatch.delenv("REVENIUM_TEAM_ID", raising=False)
        analyzer = _make_analyzer_no_team()
        with pytest.raises(Exception, match="Team ID not available"):
            await analyzer.get_customer_costs("LAST_30_DAYS", "TOTAL")

    async def test_re_raises_api_exception(self):
        analyzer = _make_analyzer()
        analyzer.client.get.side_effect = ConnectionError("timeout")
        with pytest.raises(ConnectionError, match="timeout"):
            await analyzer.get_customer_costs("LAST_30_DAYS", "TOTAL")

    async def test_customer_name_falls_back_to_groupname(self):
        """Customer name uses groupName field when organization/customer absent."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = [
            {"groupName": "fallback-customer", "cost": 200.0},
        ]
        result = await analyzer.get_customer_costs("LAST_30_DAYS", "TOTAL")
        assert any(r["customer"] == "fallback-customer" for r in result)

    async def test_percentage_zero_when_total_cost_zero(self):
        """Percentage is 0 when all costs are zero (no items added)."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = [
            {"customer": "ghost", "cost": 0.0},
        ]
        result = await analyzer.get_customer_costs("LAST_30_DAYS", "TOTAL")
        # Zero-cost items are not added
        assert result == []


# ---------------------------------------------------------------------------
# get_api_key_costs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetApiKeyCosts:
    """Tests for get_api_key_costs async method."""

    async def test_list_response_with_groups(self):
        """Standard groups format returns processed api_key records."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = [
            {
                "groups": [
                    {"groupName": "key-prod-01", "metrics": [{"metricResult": 750.0}]},
                    {"groupName": "key-staging-02", "metrics": [{"metricResult": 250.0}]},
                ]
            }
        ]
        result = await analyzer.get_api_key_costs("LAST_30_DAYS", "TOTAL")
        assert len(result) == 2
        assert result[0]["api_key"] == "key-prod-01"
        assert result[0]["cost"] == 750.0
        assert result[0]["percentage"] == pytest.approx(75.0)

    async def test_empty_response_returns_empty_list(self):
        """Falsy response (None) returns []."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = None
        result = await analyzer.get_api_key_costs("LAST_30_DAYS", "TOTAL")
        assert result == []

    async def test_empty_list_returns_empty_list(self):
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = []
        result = await analyzer.get_api_key_costs("LAST_30_DAYS", "TOTAL")
        assert result == []

    async def test_wrapped_dict_response(self):
        """Dict without groups uses 'data' extraction."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = {
            "data": [
                {"groupName": "data-key", "metrics": [{"metricResult": 100.0}]},
            ]
        }
        result = await analyzer.get_api_key_costs("LAST_30_DAYS", "TOTAL")
        assert len(result) == 1
        assert result[0]["api_key"] == "data-key"

    async def test_raises_when_no_team_id(self, monkeypatch):
        monkeypatch.delenv("REVENIUM_TEAM_ID", raising=False)
        analyzer = _make_analyzer_no_team()
        with pytest.raises(Exception, match="Team ID not available"):
            await analyzer.get_api_key_costs("LAST_30_DAYS", "TOTAL")

    async def test_env_team_id_fallback(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_TEAM_ID", "env-team-apik")
        analyzer = _make_analyzer_no_team()
        analyzer.client.get.return_value = []
        result = await analyzer.get_api_key_costs("LAST_30_DAYS", "TOTAL")
        assert result == []
        analyzer.client.get.assert_called_once()

    async def test_re_raises_api_exception(self):
        analyzer = _make_analyzer()
        analyzer.client.get.side_effect = TimeoutError("network timeout")
        with pytest.raises(TimeoutError):
            await analyzer.get_api_key_costs("LAST_30_DAYS", "TOTAL")

    async def test_direct_format_no_groups_key(self):
        """Direct dict items without groups key are processed."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = [
            {"groupName": "direct-api-key", "metrics": [{"metricResult": 555.0}]},
        ]
        result = await analyzer.get_api_key_costs("LAST_30_DAYS", "TOTAL")
        assert len(result) == 1
        assert result[0]["api_key"] == "direct-api-key"
        assert result[0]["cost"] == pytest.approx(555.0)

    async def test_sorted_descending(self):
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = [
            {"groupName": "small-key", "metrics": [{"metricResult": 10.0}]},
            {"groupName": "big-key", "metrics": [{"metricResult": 1000.0}]},
        ]
        result = await analyzer.get_api_key_costs("LAST_30_DAYS", "TOTAL")
        assert result[0]["api_key"] == "big-key"


# ---------------------------------------------------------------------------
# get_agent_costs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetAgentCosts:
    """Tests for get_agent_costs async method."""

    async def test_list_response_with_groups(self):
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = [
            {
                "groups": [
                    {"groupName": "research-agent", "metrics": [{"metricResult": 600.0}]},
                    {"groupName": "coding-agent", "metrics": [{"metricResult": 400.0}]},
                ]
            }
        ]
        result = await analyzer.get_agent_costs("LAST_30_DAYS", "TOTAL")
        assert len(result) == 2
        assert result[0]["agent"] == "research-agent"
        assert result[0]["cost"] == 600.0
        assert result[0]["percentage"] == pytest.approx(60.0)

    async def test_empty_response_returns_empty_list(self):
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = None
        result = await analyzer.get_agent_costs("LAST_30_DAYS", "TOTAL")
        assert result == []

    async def test_empty_list_returns_empty_list(self):
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = []
        result = await analyzer.get_agent_costs("LAST_30_DAYS", "TOTAL")
        assert result == []

    async def test_wrapped_dict_response(self):
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = {
            "data": [
                {"groupName": "wrapped-agent", "metrics": [{"metricResult": 300.0}]},
            ]
        }
        result = await analyzer.get_agent_costs("LAST_30_DAYS", "TOTAL")
        assert len(result) == 1
        assert result[0]["agent"] == "wrapped-agent"

    async def test_raises_when_no_team_id(self, monkeypatch):
        monkeypatch.delenv("REVENIUM_TEAM_ID", raising=False)
        analyzer = _make_analyzer_no_team()
        with pytest.raises(Exception, match="Team ID not available"):
            await analyzer.get_agent_costs("LAST_30_DAYS", "TOTAL")

    async def test_env_team_id_fallback(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_TEAM_ID", "env-team-agent")
        analyzer = _make_analyzer_no_team()
        analyzer.client.get.return_value = []
        result = await analyzer.get_agent_costs("LAST_30_DAYS", "TOTAL")
        assert result == []
        analyzer.client.get.assert_called_once()

    async def test_re_raises_api_exception(self):
        analyzer = _make_analyzer()
        analyzer.client.get.side_effect = RuntimeError("agent api error")
        with pytest.raises(RuntimeError, match="agent api error"):
            await analyzer.get_agent_costs("LAST_30_DAYS", "TOTAL")

    async def test_direct_format_without_groups_key(self):
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = [
            {"groupName": "direct-agent", "metrics": [{"metricResult": 200.0}]},
        ]
        result = await analyzer.get_agent_costs("LAST_30_DAYS", "TOTAL")
        assert len(result) == 1
        assert result[0]["agent"] == "direct-agent"

    async def test_sorted_descending(self):
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = [
            {"groupName": "slow-agent", "metrics": [{"metricResult": 50.0}]},
            {"groupName": "fast-agent", "metrics": [{"metricResult": 900.0}]},
        ]
        result = await analyzer.get_agent_costs("LAST_30_DAYS", "TOTAL")
        assert result[0]["agent"] == "fast-agent"

    async def test_non_dict_items_skipped(self):
        """Non-dict entries in the list are skipped gracefully."""
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = [
            "not-a-dict",
            {"groupName": "real-agent", "metrics": [{"metricResult": 100.0}]},
        ]
        result = await analyzer.get_agent_costs("LAST_30_DAYS", "TOTAL")
        assert len(result) == 1
        assert result[0]["agent"] == "real-agent"


# ---------------------------------------------------------------------------
# get_cost_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetCostSummary:
    """Tests for get_cost_summary which aggregates all 5 data sources."""

    async def test_summary_structure_with_data(self):
        """Verify the summary dict has all required keys when data is present."""
        analyzer = _make_analyzer()

        provider_data = [{"provider": "OpenAI", "cost": 500.0, "percentage": 100.0}]
        model_data = [{"model": "gpt-4", "cost": 400.0, "percentage": 100.0}]
        customer_data = [{"customer": "Acme", "cost": 300.0, "percentage": 100.0}]
        api_key_data = [{"api_key": "key-1", "cost": 200.0, "percentage": 100.0}]
        agent_data = [{"agent": "bot-1", "cost": 100.0, "percentage": 100.0}]

        with patch.object(analyzer, "get_provider_costs", new=AsyncMock(return_value=provider_data)), \
             patch.object(analyzer, "get_model_costs", new=AsyncMock(return_value=model_data)), \
             patch.object(analyzer, "get_customer_costs", new=AsyncMock(return_value=customer_data)), \
             patch.object(analyzer, "get_api_key_costs", new=AsyncMock(return_value=api_key_data)), \
             patch.object(analyzer, "get_agent_costs", new=AsyncMock(return_value=agent_data)):

            result = await analyzer.get_cost_summary("LAST_30_DAYS", "TOTAL")

        required_keys = {
            "total_cost", "cost_breakdown", "top_providers", "top_models",
            "top_customers", "top_api_keys", "top_agents", "period",
            "aggregation", "timestamp",
        }
        assert required_keys.issubset(result.keys())

    async def test_total_cost_uses_provider_costs(self):
        """total_cost is derived from provider_costs sum."""
        analyzer = _make_analyzer()
        provider_data = [
            {"provider": "OpenAI", "cost": 600.0, "percentage": 60.0},
            {"provider": "Azure", "cost": 400.0, "percentage": 40.0},
        ]

        with patch.object(analyzer, "get_provider_costs", new=AsyncMock(return_value=provider_data)), \
             patch.object(analyzer, "get_model_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_customer_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_api_key_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_agent_costs", new=AsyncMock(return_value=[])):

            result = await analyzer.get_cost_summary("LAST_30_DAYS", "TOTAL")

        assert result["total_cost"] == pytest.approx(1000.0)

    async def test_top_lists_capped_at_3(self):
        """top_providers/models/etc contain at most 3 entries."""
        analyzer = _make_analyzer()
        five_providers = [
            {"provider": f"P{i}", "cost": float(500 - i * 50), "percentage": 10.0}
            for i in range(5)
        ]

        with patch.object(analyzer, "get_provider_costs", new=AsyncMock(return_value=five_providers)), \
             patch.object(analyzer, "get_model_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_customer_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_api_key_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_agent_costs", new=AsyncMock(return_value=[])):

            result = await analyzer.get_cost_summary("LAST_30_DAYS", "TOTAL")

        assert len(result["top_providers"]) == 3

    async def test_period_and_aggregation_preserved(self):
        analyzer = _make_analyzer()
        with patch.object(analyzer, "get_provider_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_model_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_customer_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_api_key_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_agent_costs", new=AsyncMock(return_value=[])):

            result = await analyzer.get_cost_summary("LAST_7_DAYS", "WEEKLY")

        assert result["period"] == "LAST_7_DAYS"
        assert result["aggregation"] == "WEEKLY"

    async def test_re_raises_when_sub_method_fails(self):
        """Exception from any sub-method is re-raised."""
        analyzer = _make_analyzer()
        with patch.object(analyzer, "get_provider_costs", new=AsyncMock(side_effect=RuntimeError("provider fail"))):
            with pytest.raises(RuntimeError, match="provider fail"):
                await analyzer.get_cost_summary("LAST_30_DAYS", "TOTAL")

    async def test_cost_breakdown_has_all_keys(self):
        analyzer = _make_analyzer()
        model_data = [{"model": "m1", "cost": 300.0, "percentage": 100.0}]
        customer_data = [{"customer": "c1", "cost": 200.0, "percentage": 100.0}]
        api_key_data = [{"api_key": "k1", "cost": 150.0, "percentage": 100.0}]
        agent_data = [{"agent": "a1", "cost": 100.0, "percentage": 100.0}]
        provider_data = [{"provider": "p1", "cost": 400.0, "percentage": 100.0}]

        with patch.object(analyzer, "get_provider_costs", new=AsyncMock(return_value=provider_data)), \
             patch.object(analyzer, "get_model_costs", new=AsyncMock(return_value=model_data)), \
             patch.object(analyzer, "get_customer_costs", new=AsyncMock(return_value=customer_data)), \
             patch.object(analyzer, "get_api_key_costs", new=AsyncMock(return_value=api_key_data)), \
             patch.object(analyzer, "get_agent_costs", new=AsyncMock(return_value=agent_data)):

            result = await analyzer.get_cost_summary("LAST_30_DAYS", "TOTAL")

        breakdown = result["cost_breakdown"]
        assert set(breakdown.keys()) == {
            "provider_costs", "model_costs", "customer_costs",
            "api_key_costs", "agent_costs",
        }
        assert breakdown["model_costs"] == pytest.approx(300.0)
        assert breakdown["customer_costs"] == pytest.approx(200.0)
        assert breakdown["api_key_costs"] == pytest.approx(150.0)
        assert breakdown["agent_costs"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# investigate_cost_spike
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestInvestigateCostSpike:
    """Tests for investigate_cost_spike method."""

    async def test_spike_detected_when_contributors_above_threshold(self):
        """spike_detected=True when at least one cost exceeds threshold."""
        analyzer = _make_analyzer()

        provider_data = [{"provider": "OpenAI", "cost": 5000.0, "percentage": 100.0}]
        model_data = []
        customer_data = []
        api_key_data = []
        agent_data = []

        with patch.object(analyzer, "get_provider_costs", new=AsyncMock(return_value=provider_data)), \
             patch.object(analyzer, "get_model_costs", new=AsyncMock(return_value=model_data)), \
             patch.object(analyzer, "get_customer_costs", new=AsyncMock(return_value=customer_data)), \
             patch.object(analyzer, "get_api_key_costs", new=AsyncMock(return_value=api_key_data)), \
             patch.object(analyzer, "get_agent_costs", new=AsyncMock(return_value=agent_data)):

            result = await analyzer.investigate_cost_spike(1000.0, "LAST_30_DAYS")

        assert result["spike_detected"] is True
        assert result["threshold"] == 1000.0
        assert result["period"] == "LAST_30_DAYS"
        assert result["contributors_count"] == 1
        assert result["total_spike_cost"] == pytest.approx(5000.0)

    async def test_no_spike_when_all_below_threshold(self):
        """spike_detected=False when no costs exceed the threshold."""
        analyzer = _make_analyzer()

        provider_data = [{"provider": "OpenAI", "cost": 50.0, "percentage": 100.0}]

        with patch.object(analyzer, "get_provider_costs", new=AsyncMock(return_value=provider_data)), \
             patch.object(analyzer, "get_model_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_customer_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_api_key_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_agent_costs", new=AsyncMock(return_value=[])):

            result = await analyzer.investigate_cost_spike(1000.0, "LAST_30_DAYS")

        assert result["spike_detected"] is False
        assert result["contributors_count"] == 0

    async def test_contributors_include_all_dimensions(self):
        """Contributors from all 5 dimensions are included."""
        analyzer = _make_analyzer()

        provider_data = [{"provider": "OpenAI", "cost": 2000.0, "percentage": 100.0}]
        model_data = [{"model": "gpt-4", "cost": 1500.0, "percentage": 100.0}]
        customer_data = [{"customer": "Acme", "cost": 1200.0, "percentage": 100.0}]
        api_key_data = [{"api_key": "k1", "cost": 1100.0, "percentage": 100.0}]
        agent_data = [{"agent": "bot-1", "cost": 1050.0, "percentage": 100.0}]

        with patch.object(analyzer, "get_provider_costs", new=AsyncMock(return_value=provider_data)), \
             patch.object(analyzer, "get_model_costs", new=AsyncMock(return_value=model_data)), \
             patch.object(analyzer, "get_customer_costs", new=AsyncMock(return_value=customer_data)), \
             patch.object(analyzer, "get_api_key_costs", new=AsyncMock(return_value=api_key_data)), \
             patch.object(analyzer, "get_agent_costs", new=AsyncMock(return_value=agent_data)):

            result = await analyzer.investigate_cost_spike(1000.0, "LAST_30_DAYS")

        assert result["contributors_count"] == 5
        types_found = {c["type"] for c in result["contributors"]}
        assert types_found == {"provider", "model", "customer", "api_key", "agent"}

    async def test_contributors_sorted_descending_by_cost(self):
        """Contributors are sorted highest cost first."""
        analyzer = _make_analyzer()

        provider_data = [{"provider": "Azure", "cost": 500.0, "percentage": 100.0}]
        model_data = [{"model": "gpt-4", "cost": 9000.0, "percentage": 100.0}]

        with patch.object(analyzer, "get_provider_costs", new=AsyncMock(return_value=provider_data)), \
             patch.object(analyzer, "get_model_costs", new=AsyncMock(return_value=model_data)), \
             patch.object(analyzer, "get_customer_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_api_key_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_agent_costs", new=AsyncMock(return_value=[])):

            result = await analyzer.investigate_cost_spike(400.0, "LAST_30_DAYS")

        assert result["contributors"][0]["cost"] >= result["contributors"][1]["cost"]
        assert result["contributors"][0]["name"] == "gpt-4"

    async def test_re_raises_when_sub_method_fails(self):
        analyzer = _make_analyzer()
        with patch.object(analyzer, "get_provider_costs", new=AsyncMock(side_effect=RuntimeError("api fail"))):
            with pytest.raises(RuntimeError, match="api fail"):
                await analyzer.investigate_cost_spike(100.0, "LAST_30_DAYS")

    async def test_result_contains_timestamp(self):
        """Result includes a timestamp field."""
        analyzer = _make_analyzer()

        with patch.object(analyzer, "get_provider_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_model_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_customer_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_api_key_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_agent_costs", new=AsyncMock(return_value=[])):

            result = await analyzer.investigate_cost_spike(500.0, "LAST_7_DAYS")

        assert "timestamp" in result
        assert result["timestamp"]  # non-empty

    async def test_debug_entries_excluded_from_contributors(self):
        """DEBUG_INFO items from customer_costs are not added as contributors."""
        analyzer = _make_analyzer()

        customer_data = [
            {"customer": "DEBUG_INFO", "cost": 9999.0, "percentage": 0},
            {"customer": "RealCorp", "cost": 2000.0, "percentage": 100.0},
        ]

        with patch.object(analyzer, "get_provider_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_model_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_customer_costs", new=AsyncMock(return_value=customer_data)), \
             patch.object(analyzer, "get_api_key_costs", new=AsyncMock(return_value=[])), \
             patch.object(analyzer, "get_agent_costs", new=AsyncMock(return_value=[])):

            result = await analyzer.investigate_cost_spike(1000.0, "LAST_30_DAYS")

        contributor_names = [c["name"] for c in result["contributors"]]
        assert "DEBUG_INFO" not in contributor_names
        assert "RealCorp" in contributor_names


# ---------------------------------------------------------------------------
# _process_provider_data edge cases not covered by initial tests
# ---------------------------------------------------------------------------


class TestProcessProviderDataEdgeCases:
    """Edge cases for _process_provider_data."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def test_non_dict_items_in_list_skipped(self):
        """Non-dict items in the data list are skipped."""
        data = [
            "not-a-dict",
            {"groupName": "OpenAI", "metrics": [{"metricResult": 100.0}]},
        ]
        result = self.analyzer._process_provider_data(data)
        assert len(result) == 1
        assert result[0]["provider"] == "OpenAI"

    def test_groups_key_with_non_list_value_skipped(self):
        """If groups value is not a list, that response entry is skipped."""
        data = [{"groups": "not-a-list"}]
        result = self.analyzer._process_provider_data(data)
        assert result == []

    def test_group_item_with_non_list_metrics_skipped(self):
        """Group item with non-list metrics is skipped."""
        data = [
            {
                "groups": [
                    {"groupName": "OpenAI", "metrics": "bad-format"},
                ]
            }
        ]
        result = self.analyzer._process_provider_data(data)
        assert result == []

    def test_metric_non_dict_skipped(self):
        """Non-dict metric entries within a group are skipped."""
        data = [
            {
                "groups": [
                    {
                        "groupName": "Azure",
                        "metrics": ["not-a-dict", {"metricResult": 200.0}],
                    }
                ]
            }
        ]
        result = self.analyzer._process_provider_data(data)
        # Only valid metric contributes
        assert result[0]["cost"] == pytest.approx(200.0)

    def test_non_numeric_metric_result_ignored(self):
        """Non-numeric metricResult is not added to cost."""
        data = [
            {
                "groups": [
                    {
                        "groupName": "AWS",
                        "metrics": [
                            {"metricResult": "not-a-number"},
                            {"metricResult": 150.0},
                        ],
                    }
                ]
            }
        ]
        result = self.analyzer._process_provider_data(data)
        assert result[0]["cost"] == pytest.approx(150.0)

    def test_direct_format_non_list_metrics_skipped(self):
        """Direct format item with non-list metrics is skipped."""
        data = [{"groupName": "Anthropic", "metrics": "bad-format"}]
        result = self.analyzer._process_provider_data(data)
        assert result == []

    def test_multiple_groups_responses_aggregated(self):
        """Multiple response dicts in data list are aggregated together."""
        data = [
            {"groupName": "OpenAI", "metrics": [{"metricResult": 300.0}]},
            {"groupName": "OpenAI", "metrics": [{"metricResult": 200.0}]},
        ]
        result = self.analyzer._process_provider_data(data)
        # Both direct-format items for OpenAI should be aggregated
        assert len(result) == 1
        assert result[0]["cost"] == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# _process_api_key_data edge cases
# ---------------------------------------------------------------------------


class TestProcessApiKeyDataEdgeCases:
    """Edge cases for _process_api_key_data."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def test_non_dict_items_skipped(self):
        data = ["not-a-dict", {"groupName": "key-1", "metrics": [{"metricResult": 100.0}]}]
        result = self.analyzer._process_api_key_data(data)
        assert len(result) == 1
        assert result[0]["api_key"] == "key-1"

    def test_groups_non_list_skipped(self):
        data = [{"groups": "not-a-list"}]
        result = self.analyzer._process_api_key_data(data)
        assert result == []

    def test_group_item_non_dict_skipped(self):
        data = [{"groups": ["not-a-dict"]}]
        result = self.analyzer._process_api_key_data(data)
        assert result == []

    def test_group_item_with_non_list_metrics_skipped(self):
        data = [{"groups": [{"groupName": "k1", "metrics": "bad"}]}]
        result = self.analyzer._process_api_key_data(data)
        assert result == []

    def test_metric_non_dict_skipped_in_groups(self):
        data = [
            {
                "groups": [
                    {"groupName": "k1", "metrics": ["bad", {"metricResult": 50.0}]}
                ]
            }
        ]
        result = self.analyzer._process_api_key_data(data)
        assert result[0]["cost"] == pytest.approx(50.0)

    def test_non_numeric_metric_result_ignored_in_groups(self):
        data = [
            {
                "groups": [
                    {"groupName": "k1", "metrics": [{"metricResult": "NaN"}, {"metricResult": 75.0}]}
                ]
            }
        ]
        result = self.analyzer._process_api_key_data(data)
        assert result[0]["cost"] == pytest.approx(75.0)

    def test_direct_format_non_list_metrics_skipped(self):
        data = [{"groupName": "k-direct", "metrics": "bad"}]
        result = self.analyzer._process_api_key_data(data)
        assert result == []

    def test_metric_non_dict_in_direct_format_skipped(self):
        data = [{"groupName": "k-direct", "metrics": ["bad", {"metricResult": 200.0}]}]
        result = self.analyzer._process_api_key_data(data)
        assert result[0]["cost"] == pytest.approx(200.0)

    def test_non_numeric_metric_in_direct_format_ignored(self):
        data = [{"groupName": "k-direct", "metrics": [{"metricResult": "bad"}, {"metricResult": 100.0}]}]
        result = self.analyzer._process_api_key_data(data)
        assert result[0]["cost"] == pytest.approx(100.0)

    def test_zero_cost_not_added(self):
        data = [{"groupName": "zero-key", "metrics": [{"metricResult": 0.0}]}]
        result = self.analyzer._process_api_key_data(data)
        assert result == []

    def test_percentage_zero_when_only_one_key(self):
        data = [{"groupName": "solo-key", "metrics": [{"metricResult": 500.0}]}]
        result = self.analyzer._process_api_key_data(data)
        assert result[0]["percentage"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# _process_agent_data edge cases
# ---------------------------------------------------------------------------


class TestProcessAgentDataEdgeCases:
    """Edge cases for _process_agent_data."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def test_non_dict_items_skipped(self):
        data = ["not-a-dict", {"groupName": "agent-1", "metrics": [{"metricResult": 100.0}]}]
        result = self.analyzer._process_agent_data(data)
        assert len(result) == 1
        assert result[0]["agent"] == "agent-1"

    def test_groups_non_list_skipped(self):
        data = [{"groups": "bad-format"}]
        result = self.analyzer._process_agent_data(data)
        assert result == []

    def test_group_item_non_dict_skipped(self):
        data = [{"groups": ["not-a-dict"]}]
        result = self.analyzer._process_agent_data(data)
        assert result == []

    def test_group_item_non_list_metrics_skipped(self):
        data = [{"groups": [{"groupName": "a1", "metrics": "bad"}]}]
        result = self.analyzer._process_agent_data(data)
        assert result == []

    def test_metric_non_dict_skipped_in_groups(self):
        data = [{"groups": [{"groupName": "a1", "metrics": ["bad", {"metricResult": 80.0}]}]}]
        result = self.analyzer._process_agent_data(data)
        assert result[0]["cost"] == pytest.approx(80.0)

    def test_non_numeric_metric_ignored_in_groups(self):
        data = [
            {
                "groups": [
                    {"groupName": "a1", "metrics": [{"metricResult": "NaN"}, {"metricResult": 60.0}]}
                ]
            }
        ]
        result = self.analyzer._process_agent_data(data)
        assert result[0]["cost"] == pytest.approx(60.0)

    def test_direct_format_non_list_metrics_skipped(self):
        data = [{"groupName": "a-direct", "metrics": "bad"}]
        result = self.analyzer._process_agent_data(data)
        assert result == []

    def test_metric_non_dict_in_direct_format_skipped(self):
        data = [{"groupName": "a-direct", "metrics": ["bad", {"metricResult": 300.0}]}]
        result = self.analyzer._process_agent_data(data)
        assert result[0]["cost"] == pytest.approx(300.0)

    def test_non_numeric_metric_in_direct_format_ignored(self):
        data = [{"groupName": "a-direct", "metrics": [{"metricResult": "bad"}, {"metricResult": 150.0}]}]
        result = self.analyzer._process_agent_data(data)
        assert result[0]["cost"] == pytest.approx(150.0)

    def test_zero_cost_not_added(self):
        data = [{"groupName": "zero-agent", "metrics": [{"metricResult": 0.0}]}]
        result = self.analyzer._process_agent_data(data)
        assert result == []

    def test_percentage_100_for_single_agent(self):
        data = [{"groupName": "solo-agent", "metrics": [{"metricResult": 700.0}]}]
        result = self.analyzer._process_agent_data(data)
        assert result[0]["percentage"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# get_agent_costs — costSources filter passthrough (BACK-2348)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetAgentCostsCostSourceFilter:
    """costSources filter maps to the new API's costSource query param."""

    async def test_filter_sent_as_cost_source_param_on_new_api(self, monkeypatch):
        """filters.costSources reaches the wire as repeated costSource values."""
        monkeypatch.setenv("REVENIUM_USE_NEW_ANALYTICS_API", "true")
        monkeypatch.setenv("REVENIUM_APP_BASE_URL", "https://app.dev.example")
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = []
        await analyzer.get_agent_costs(
            "SEVEN_DAYS", "TOTAL", filters={"costSources": ["provider_billing"]}
        )
        analyzer.client.get.assert_awaited_once()
        _, kwargs = analyzer.client.get.call_args
        assert kwargs["params"]["costSource"] == ["provider_billing"]

    async def test_no_filter_omits_cost_source_param(self, monkeypatch):
        """Omitting the filter keeps costSource off the request entirely."""
        monkeypatch.setenv("REVENIUM_USE_NEW_ANALYTICS_API", "true")
        monkeypatch.setenv("REVENIUM_APP_BASE_URL", "https://app.dev.example")
        analyzer = _make_analyzer()
        analyzer.client.get.return_value = []
        await analyzer.get_agent_costs("SEVEN_DAYS", "TOTAL")
        analyzer.client.get.assert_awaited_once()
        _, kwargs = analyzer.client.get.call_args
        assert "costSource" not in kwargs["params"]

    async def test_filter_on_legacy_api_raises_validation_error(self, monkeypatch):
        """The legacy profitstream endpoint has no costSource param; failing
        loudly beats silently returning unfiltered data labeled as filtered."""
        from src.revenium_mcp_server.analytics.validation import ValidationError

        monkeypatch.setenv("REVENIUM_USE_NEW_ANALYTICS_API", "false")
        analyzer = _make_analyzer()
        with pytest.raises(ValidationError, match="new analytics API"):
            await analyzer.get_agent_costs(
                "SEVEN_DAYS", "TOTAL", filters={"costSources": ["provider_billing"]}
            )
        analyzer.client.get.assert_not_called()
