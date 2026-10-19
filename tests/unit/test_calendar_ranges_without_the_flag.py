"""Calendar ranges on the cost reports a deployment without the analytics flag reads from the legacy API (FRONT-3435).

Hosted deployments do not set REVENIUM_USE_NEW_ANALYTICS_API, so the provider,
model, customer, API key and agent cost reads take their legacy route for a
named period. The legacy route accepts only a period name, so a calendar range
must take the analytics route those endpoints already have.
"""

import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server import endpoint_registry
from src.revenium_mcp_server.analytics_window import CalendarRange
from src.revenium_mcp_server.endpoint_registry import (
    NewApiRequiredError,
    requires_new_api_flag,
    resolve_analytics_request,
)
from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    BusinessAnalyticsManagement,
)

APP_BASE_URL = "https://app.example.test"
SEPTEMBER = {"start_date": "2026-09-01", "end_date": "2026-09-30"}
SEPTEMBER_BOUNDS = ("2026-09-01T00:00:00.000Z", "2026-09-30T23:59:59.999Z")
SEPTEMBER_HEADER = "2026-09-01 to 2026-09-30 UTC, both days included"
NEW_PLANE_NOTE = "apply one rule before any filter"
LEGACY_PLANE_NOTE = "this number comes from the legacy analytics endpoints"

_PROVIDER = ("/api/v2/analytics/cost-by-provider", "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-provider-over-time")
_MODEL = ("/api/v2/analytics/cost-by-model-aggregated", "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-model")
_CUSTOMER = ("/api/v2/analytics/cost-by-organization", "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-organization")
_API_KEY = ("/api/v2/analytics/cost-by-api-key", "/profitstream/v2/api/sources/metrics/ai/cost-metrics-by-subscriber-credential")
_AGENT = ("/api/v2/analytics/cost-by-agent", "/profitstream/v2/api/sources/metrics/ai/cost-metrics-by-agents-over-time")

#: (analytics path, legacy path) of every read each flag-gated action makes.
FLAG_GATED_ACTIONS = {
    "get_provider_costs": [_PROVIDER],
    "get_model_costs": [_MODEL],
    "get_customer_costs": [_CUSTOMER],
    "get_api_key_costs": [_API_KEY],
    "get_agent_costs": [_AGENT],
    "get_cost_summary": [_PROVIDER, _MODEL, _CUSTOMER, _API_KEY, _AGENT],
}

BUCKETS = [
    {
        "startTimestamp": "2026-09-01T00:00:00.000Z",
        "endTimestamp": "2026-09-30T23:59:59.999Z",
        "groups": [{"groupName": "openai", "metrics": [{"metricResult": 2.5}]}],
    }
]


@pytest.fixture(autouse=True)
def deployment_without_the_flag(monkeypatch):
    monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)
    monkeypatch.setenv("REVENIUM_APP_BASE_URL", APP_BASE_URL)


@pytest.fixture
def analytics_tool():
    with patch(
        "src.revenium_mcp_server.tools_decomposed.business_analytics_management.CHART_RENDERING_AVAILABLE",
        False,
    ):
        return BusinessAnalyticsManagement()


async def _run(analytics_tool, action, arguments):
    client = MagicMock()
    client.team_id = "team-1"
    client.get = AsyncMock(return_value=BUCKETS)
    analytics_tool.get_client = AsyncMock(return_value=client)
    result = await analytics_tool.handle_action(action, arguments)
    return client.get.await_args_list, result[0].text


@pytest.mark.parametrize("action", FLAG_GATED_ACTIONS)
class TestFlagGatedCostReads:
    @pytest.mark.asyncio
    async def test_a_range_is_read_from_the_analytics_api(self, analytics_tool, action):
        calls, text = await _run(analytics_tool, action, dict(SEPTEMBER))

        assert [call.args[0] for call in calls] == [new for new, _ in FLAG_GATED_ACTIONS[action]]
        for call in calls:
            assert call.kwargs["use_bearer"] is True
            assert call.kwargs["base_url"] == APP_BASE_URL
            params = call.kwargs["params"]
            assert (params["startDate"], params["endDate"]) == SEPTEMBER_BOUNDS
            assert "period" not in params
        assert SEPTEMBER_HEADER in text
        assert NEW_PLANE_NOTE in text
        assert "need the analytics API" not in text

    @pytest.mark.asyncio
    async def test_a_named_period_keeps_the_legacy_route(self, analytics_tool, action):
        calls, text = await _run(analytics_tool, action, {"period": "THIRTY_DAYS"})

        assert [call.args[0] for call in calls] == [old for _, old in FLAG_GATED_ACTIONS[action]]
        for call in calls:
            assert "use_bearer" not in call.kwargs
            assert call.kwargs["params"]["period"] == "THIRTY_DAYS"
        assert LEGACY_PLANE_NOTE in text


class TestNewApiOnlyEndpointWithoutForceNew:
    """Refusal is per window: a NEW_API_ONLY entry that is not force_new is refused for a
    named period on a deployment without the flag, and answers a calendar range."""

    @pytest.fixture
    def flag_gated_new_api_only(self, monkeypatch):
        key = "cost_metric_by_user_aggregated"
        entry = endpoint_registry._ENDPOINT_REGISTRY[key]
        monkeypatch.setitem(
            endpoint_registry._ENDPOINT_REGISTRY, key, dataclasses.replace(entry, force_new=False)
        )
        return key

    def test_a_named_period_is_refused_and_the_gate_says_so(self, flag_gated_new_api_only):
        with pytest.raises(NewApiRequiredError):
            resolve_analytics_request(flag_gated_new_api_only, "team-1", "THIRTY_DAYS")
        assert requires_new_api_flag(flag_gated_new_api_only) is True

    def test_a_calendar_range_takes_the_new_path(self, flag_gated_new_api_only):
        path, params, call_kwargs = resolve_analytics_request(
            flag_gated_new_api_only,
            "team-1",
            CalendarRange.from_iso_dates("2026-09-01", "2026-09-30"),
        )

        assert path.startswith("/api/v2/analytics/")
        assert (params["startDate"], params["endDate"]) == SEPTEMBER_BOUNDS
        assert call_kwargs == {"base_url": APP_BASE_URL, "use_bearer": True}
