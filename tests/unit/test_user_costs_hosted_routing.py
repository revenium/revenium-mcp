"""get_user_costs on a hosted-shaped deployment (BACK-3912, BACK-3959).

Hosted MCP servers never set REVENIUM_USE_NEW_ANALYTICS_API, so every test here
runs with the flag unset. The per-user report must route to the analytics plane
anyway, be advertised by get_capabilities, and, if a deployment ever does refuse
it, say the gap is the server's configuration rather than the caller's tenant.
"""

import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server import endpoint_registry
from src.revenium_mcp_server.endpoint_registry import (
    get_endpoint_path,
    requires_new_api_flag,
    resolve_analytics_request,
)
from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    BusinessAnalyticsManagement,
)

USER_COSTS_KEY = "cost_metric_by_user_aggregated"
USER_COSTS_PATH = "/api/v2/analytics/cost-by-user-aggregated"
OLD_REFUSAL_TEXT = "requires the new analytics API"

USER_COSTS_PAYLOAD = {
    "_embedded": {
        "items": [
            {
                "groupName": "dev@example.com",
                "metrics": [
                    {"metricType": "COST_METRIC_BY_USER", "metricResult": 12.5},
                    {"metricType": "REQUEST_METRIC_BY_USER", "metricResult": 40},
                    {"metricType": "TOKEN_METRIC_BY_USER", "metricResult": 9000},
                ],
            }
        ]
    }
}


@pytest.fixture(autouse=True)
def hosted_config(monkeypatch):
    monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)
    monkeypatch.delenv("REVENIUM_APP_BASE_URL", raising=False)


@pytest.fixture
def analytics_tool():
    with patch(
        "src.revenium_mcp_server.tools_decomposed.business_analytics_management.CHART_RENDERING_AVAILABLE",
        False,
    ):
        return BusinessAnalyticsManagement()


@pytest.fixture
def refused_user_costs(monkeypatch):
    """Recreate the pre-BACK-3912 registry entry: NEW_API_ONLY without force_new."""
    entry = endpoint_registry._ENDPOINT_REGISTRY[USER_COSTS_KEY]
    monkeypatch.setitem(
        endpoint_registry._ENDPOINT_REGISTRY,
        USER_COSTS_KEY,
        dataclasses.replace(entry, force_new=False),
    )


def _client(payload):
    client = MagicMock()
    client.team_id = "team-1"
    client.get = AsyncMock(return_value=payload)
    return client


async def _run_user_costs(analytics_tool, payload=USER_COSTS_PAYLOAD, filters=None):
    client = _client(payload)
    analytics_tool.get_client = AsyncMock(return_value=client)
    arguments = {"period": "THIRTY_DAYS"}
    if filters is not None:
        arguments["filters"] = filters
    result = await analytics_tool.handle_action("get_user_costs", arguments)
    return client, result[0].text


def _sent_cost_sources(client):
    return client.get.await_args.kwargs["params"].get("costSources")


class TestRegistryRouting:
    def test_entry_is_forced_onto_the_analytics_api(self):
        assert endpoint_registry._ENDPOINT_REGISTRY[USER_COSTS_KEY].force_new is True

    def test_resolves_to_the_new_path_with_the_flag_unset(self):
        assert get_endpoint_path(USER_COSTS_KEY) == USER_COSTS_PATH

    def test_request_uses_bearer_and_a_date_window(self):
        path, params, call_kwargs = resolve_analytics_request(
            USER_COSTS_KEY, team_id="team-1", period="THIRTY_DAYS"
        )
        assert path == USER_COSTS_PATH
        assert call_kwargs.get("use_bearer") is True
        assert "startDate" in params and "endDate" in params

    def test_not_reported_as_needing_the_flag(self):
        assert requires_new_api_flag(USER_COSTS_KEY) is False

    def test_reported_as_needing_the_flag_when_the_resolver_would_refuse(
        self, refused_user_costs
    ):
        assert requires_new_api_flag(USER_COSTS_KEY) is True


class TestCapabilities:
    @pytest.mark.asyncio
    async def test_capabilities_list_get_user_costs(self, analytics_tool):
        result = await analytics_tool.handle_action("get_capabilities", {})
        assert "**get_user_costs**" in result[0].text

    @pytest.mark.asyncio
    async def test_supported_actions_include_get_user_costs(self, analytics_tool):
        assert "get_user_costs" in await analytics_tool._get_supported_actions()

    @pytest.mark.asyncio
    async def test_section_is_stripped_only_when_the_resolver_would_refuse(
        self, analytics_tool, refused_user_costs
    ):
        result = await analytics_tool.handle_action("get_capabilities", {})
        assert "get_user_costs" not in result[0].text
        assert "get_user_costs" not in await analytics_tool._get_supported_actions()


class TestHandler:
    @pytest.mark.asyncio
    async def test_returns_the_per_user_table(self, analytics_tool):
        client, text = await _run_user_costs(analytics_tool)

        assert OLD_REFUSAL_TEXT not in text
        assert "dev@example.com" in text
        path = client.get.await_args.args[0]
        assert path == USER_COSTS_PATH
        assert client.get.await_args.kwargs.get("use_bearer") is True

    @pytest.mark.asyncio
    async def test_empty_result_is_the_honest_empty_report(self, analytics_tool):
        _, text = await _run_user_costs(analytics_tool, payload={"_embedded": {"items": []}})

        assert OLD_REFUSAL_TEXT not in text
        assert "## **No Data Available**" in text
        assert "**Time Period**: THIRTY_DAYS" in text
        assert "returned no rows for these parameters" in text
        assert "not about whether anyone used AI in the period" in text
        assert "**Per-user attribution**" in text
        assert "subscriber email is populated" in text
        assert '`filters.costSources=["coding_assistant", "revenium_metered", "provider_billing"]`' in text

    @pytest.mark.asyncio
    async def test_refusal_names_the_server_configuration_not_the_tenant(
        self, analytics_tool, refused_user_costs
    ):
        client, text = await _run_user_costs(analytics_tool)

        client.get.assert_not_awaited()
        assert OLD_REFUSAL_TEXT not in text
        assert "server configuration gap" in text
        assert "not something your tenant lacks" in text


class TestCostSourcesDefault:
    """Coding-assistant usage is real spend or an estimate under coding_assistant depending on the team's API-rate setting, so an omitted filter asks for every source (BACK-4136)."""

    @pytest.mark.asyncio
    async def test_omitted_cost_sources_ask_for_the_answerable_sources(self, analytics_tool):
        client, _ = await _run_user_costs(analytics_tool)

        assert _sent_cost_sources(client) == ["coding_assistant", "revenium_metered", "provider_billing"]

    @pytest.mark.asyncio
    async def test_other_filters_alone_still_get_the_answerable_sources(self, analytics_tool):
        client, _ = await _run_user_costs(
            analytics_tool, filters={"providers": ["openai"]}
        )

        params = client.get.await_args.kwargs["params"]
        assert params["providers"] == ["openai"]
        assert params["costSources"] == ["coding_assistant", "revenium_metered", "provider_billing"]

    @pytest.mark.asyncio
    async def test_explicit_coding_assistant_is_sent_as_given(self, analytics_tool):
        client, _ = await _run_user_costs(
            analytics_tool, filters={"costSources": ["coding_assistant"]}
        )

        assert _sent_cost_sources(client) == ["coding_assistant"]

    @pytest.mark.asyncio
    async def test_explicit_single_source_is_not_widened(self, analytics_tool):
        client, _ = await _run_user_costs(
            analytics_tool, filters={"costSources": ["provider_billing"]}
        )

        assert _sent_cost_sources(client) == ["provider_billing"]

    @pytest.mark.asyncio
    async def test_note_names_the_default_and_the_coding_assistant_limit(self, analytics_tool):
        _, text = await _run_user_costs(analytics_tool)

        assert (
            "Unless you pass `filters.costSources`, this action asks for every cost source "
            "per user "
            '(`filters.costSources=["coding_assistant", "revenium_metered", "provider_billing"]`); pass a subset to narrow it'
        ) in text
        assert "returns no rows" not in text
        assert "under `coding_assistant` otherwise" in text
        assert "AI by Employee" in text
        assert "this action defaults to" not in text

    @pytest.mark.asyncio
    async def test_capabilities_state_the_new_default(self, analytics_tool):
        result = await analytics_tool.handle_action("get_capabilities", {})
        text = result[0].text

        assert "Without filters.costSources it asks for every cost source per user" in text
        assert 'defaults to\n     filters.costSources=["coding_assistant"]' not in text
