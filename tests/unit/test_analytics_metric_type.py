"""BACK-4641: the aggregation reaches the analytics API as metricType.

The analytics cost endpoints read metricType (sum, avg, max, min per
specs/openapi/isotope.json); the legacy route's group parameter is dropped
there, so MEAN and MAXIMUM used to come back as totals labelled MEAN.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    BusinessAnalyticsManagement,
)

SEPTEMBER = {"start_date": "2026-09-01", "end_date": "2026-09-30"}
METRIC_TYPES = {"TOTAL": "sum", "MEAN": "avg", "MAXIMUM": "max", "MINIMUM": "min"}

#: Every analytics path each ranked action reads.
RANKED_ACTIONS = {
    "get_provider_costs": ["/api/v2/analytics/cost-by-provider"],
    "get_model_costs": ["/api/v2/analytics/cost-by-model-aggregated"],
    "get_customer_costs": ["/api/v2/analytics/cost-by-organization"],
    "get_api_key_costs": ["/api/v2/analytics/cost-by-api-key"],
    "get_agent_costs": ["/api/v2/analytics/cost-by-agent"],
    "get_cost_summary": [
        "/api/v2/analytics/cost-by-provider",
        "/api/v2/analytics/cost-by-model-aggregated",
        "/api/v2/analytics/cost-by-organization",
        "/api/v2/analytics/cost-by-api-key",
        "/api/v2/analytics/cost-by-agent",
    ],
}


@pytest.fixture(autouse=True)
def deployment_without_the_flag(monkeypatch):
    monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)
    monkeypatch.setenv("REVENIUM_APP_BASE_URL", "https://app.example.test")


@pytest.fixture
def analytics_tool():
    with patch(
        "src.revenium_mcp_server.tools_decomposed.business_analytics_management.CHART_RENDERING_AVAILABLE",
        False,
    ):
        yield BusinessAnalyticsManagement()


def _client(analytics_tool):
    client = MagicMock()
    client.team_id = "team-1"
    client.get = AsyncMock(return_value={"_embedded": {"items": []}})
    analytics_tool.get_client = AsyncMock(return_value=client)
    return client


def _sent(client):
    return [(call.args[0], call.kwargs["params"]) for call in client.get.await_args_list]


async def _requests(analytics_tool, action, arguments):
    client = _client(analytics_tool)
    result = await analytics_tool.handle_action(action, arguments)
    return _sent(client), result[0].text


@pytest.mark.asyncio
@pytest.mark.parametrize("aggregation", sorted(METRIC_TYPES))
@pytest.mark.parametrize("action", sorted(RANKED_ACTIONS))
async def test_ranked_reads_send_the_aggregation_as_metric_type(analytics_tool, action, aggregation):
    requests, _ = await _requests(analytics_tool, action, {**SEPTEMBER, "group": aggregation})

    assert sorted(path for path, _ in requests) == sorted(RANKED_ACTIONS[action])
    for path, params in requests:
        assert params["metricType"] == METRIC_TYPES[aggregation], path
        assert "group" not in params and "aggregation" not in params, path


@pytest.mark.asyncio
async def test_a_named_period_on_the_legacy_route_still_sends_group(analytics_tool):
    requests, _ = await _requests(
        analytics_tool, "get_provider_costs", {"period": "SEVEN_DAYS", "group": "MEAN"}
    )
    [(path, params)] = requests
    assert path.startswith("/profitstream/")
    assert params["group"] == "MEAN"
    assert "metricType" not in params


@pytest.mark.asyncio
async def test_user_costs_send_metric_type_not_an_undeclared_aggregation(analytics_tool):
    requests, _ = await _requests(analytics_tool, "get_user_costs", {"period": "SEVEN_DAYS"})
    [(path, params)] = requests
    assert path == "/api/v2/analytics/cost-by-user-aggregated"
    assert params["metricType"] == "sum"
    assert "aggregation" not in params


@pytest.mark.asyncio
@pytest.mark.parametrize("aggregation", ["MEAN", "MAXIMUM", "MINIMUM"])
async def test_user_costs_refuse_an_aggregation_the_report_cannot_give(analytics_tool, aggregation):
    client = _client(analytics_tool)
    with pytest.raises(ToolError) as refusal:
        await analytics_tool.handle_action(
            "get_user_costs", {"period": "SEVEN_DAYS", "aggregation": aggregation}
        )
    assert _sent(client) == []
    assert f"total only, not {aggregation}" in refusal.value.message
