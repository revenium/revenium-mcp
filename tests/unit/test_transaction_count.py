"""Real aggregate transaction count via /analytics/transaction-count-by-team.

The MCP used to fake transaction volume from cost (``max(1, int(cost / 0.01))``).
These tests pin the real path: a NEW_API_ONLY registry entry (force_new — there
is no legacy equivalent), an engine action that reads the single total from
``_embedded.items[0].metrics[0].metricResult``, and the removal of the
cost-as-proxy fabrication from the profitability processors.
"""

import inspect
from copy import deepcopy
from dataclasses import fields
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.analytics import transaction_level_analytics_processor
from src.revenium_mcp_server.analytics.simple_analytics_engine import SimpleAnalyticsEngine
from src.revenium_mcp_server.analytics.transaction_level_analytics_processor import (
    CustomerTransactionData,
    ProductTransactionData,
)
from src.revenium_mcp_server.analytics.validation import ValidationError
from src.revenium_mcp_server.endpoint_registry import (
    _ENDPOINT_REGISTRY,
    resolve_analytics_request,
)
from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    BusinessAnalyticsManagement,
)

# Captured from a live dev call on 2026-07-13 (144 transactions over SEVEN_DAYS).
ENVELOPE = {
    "id": "metric_aggregated_transaction_count_by_team",
    "resourceType": "metric_aggregated",
    "label": "Transaction Count by Team",
    "period": {"start": "2026-07-06T12:15:50.000Z", "end": "2026-07-13T12:15:50.000Z"},
    "_embedded": {
        "items": [
            {
                "groupName": "Transaction Count",
                "metrics": [
                    {
                        "id": "86c8dd46-21ad-43ac-b1e7-067354e488f1",
                        "resourceType": "metric",
                        "label": "Transaction Count",
                        "metricResult": 144,
                        "metricType": "TRANSACTION_COUNT_BY_TEAM",
                        "links": {},
                    }
                ],
            }
        ]
    },
    "_links": {"self": {"href": "https://ai.dev.hcapp.io/api/v2/analytics/..."}},
}


def _engine_with_response(response):
    client = MagicMock()
    client.team_id = "team-abc"
    client.get = AsyncMock(return_value=response)
    return SimpleAnalyticsEngine(client), client


class TestRegistryEntry:
    def test_entry_is_new_api_only_and_forced(self):
        config = _ENDPOINT_REGISTRY["transaction_count_by_team"]
        assert config.new_path == "/api/v2/analytics/transaction-count-by-team"
        assert config.mapping_status == "NEW_API_ONLY"
        assert config.force_new is True

    def test_resolves_to_new_path_with_flag_off(self, monkeypatch):
        monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)
        path, params, call_kwargs = resolve_analytics_request(
            "transaction_count_by_team", "team-ignored", "SEVEN_DAYS"
        )
        assert path == "/api/v2/analytics/transaction-count-by-team"
        assert "startDate" in params and "endDate" in params
        assert "teamId" not in params
        assert call_kwargs.get("use_bearer") is True


class TestAppHostResolution:
    """The registry's app-host resolution must pair known API hosts with their
    analytics hosts (same order as client._get_app_base_url): explicit
    REVENIUM_APP_BASE_URL > known-host map from REVENIUM_BASE_URL > prod
    default. Without the pairing step a dev key is sent to the prod host.
    """

    def test_known_dev_host_pairs_analytics_host(self, monkeypatch):
        monkeypatch.delenv("REVENIUM_APP_BASE_URL", raising=False)
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.dev.hcapp.io")
        _, _, call_kwargs = resolve_analytics_request(
            "transaction_count_by_team", "t", "SEVEN_DAYS"
        )
        assert call_kwargs["base_url"] == "https://ai.dev.hcapp.io"

    def test_known_dev_host_with_port_still_pairs(self, monkeypatch):
        monkeypatch.delenv("REVENIUM_APP_BASE_URL", raising=False)
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.dev.hcapp.io:443")
        _, _, call_kwargs = resolve_analytics_request(
            "transaction_count_by_team", "t", "SEVEN_DAYS"
        )
        assert call_kwargs["base_url"] == "https://ai.dev.hcapp.io"

    def test_explicit_app_base_url_wins(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_APP_BASE_URL", "https://app.example.test")
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.dev.hcapp.io")
        _, _, call_kwargs = resolve_analytics_request(
            "transaction_count_by_team", "t", "SEVEN_DAYS"
        )
        assert call_kwargs["base_url"] == "https://app.example.test"

    def test_unknown_host_falls_back_to_prod_default(self, monkeypatch):
        monkeypatch.delenv("REVENIUM_APP_BASE_URL", raising=False)
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.revenium.ai")
        _, _, call_kwargs = resolve_analytics_request(
            "transaction_count_by_team", "t", "SEVEN_DAYS"
        )
        assert call_kwargs["base_url"] == "https://app.revenium.ai"


class TestGetTransactionCount:
    @pytest.mark.asyncio
    async def test_happy_path_returns_real_total(self):
        engine, client = _engine_with_response(deepcopy(ENVELOPE))

        result = await engine.get_transaction_count(period="SEVEN_DAYS")

        assert "144" in result
        assert "SEVEN_DAYS" in result
        path = client.get.call_args.args[0]
        assert path == "/api/v2/analytics/transaction-count-by-team"
        params = client.get.call_args.kwargs["params"]
        assert "startDate" in params and "endDate" in params

    @pytest.mark.asyncio
    async def test_client_unwrapped_list_shape_is_parsed(self):
        # The client unwraps the HAL envelope and hands back _embedded.items
        # directly — the shape the live path actually produces.
        engine, _ = _engine_with_response(deepcopy(ENVELOPE["_embedded"]["items"]))

        result = await engine.get_transaction_count(period="SEVEN_DAYS")

        assert "144" in result

    @pytest.mark.asyncio
    async def test_zero_count_is_reported_not_floored_to_one(self):
        envelope = deepcopy(ENVELOPE)
        envelope["_embedded"]["items"][0]["metrics"][0]["metricResult"] = 0
        engine, _ = _engine_with_response(envelope)

        result = await engine.get_transaction_count(period="SEVEN_DAYS")

        assert "0" in result
        assert "144" not in result

    @pytest.mark.asyncio
    async def test_invalid_period_raises_validation_error(self):
        engine, client = _engine_with_response(deepcopy(ENVELOPE))

        with pytest.raises(ValidationError):
            await engine.get_transaction_count(period="FORTNIGHT")
        client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_response_reports_no_data(self):
        engine, _ = _engine_with_response({})

        result = await engine.get_transaction_count(period="SEVEN_DAYS")

        assert "no data" in result.lower()


class TestToolDispatch:
    @pytest.fixture
    def analytics_tool(self):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.business_analytics_management.CHART_RENDERING_AVAILABLE",
            False,
        ):
            return BusinessAnalyticsManagement()

    @pytest.mark.asyncio
    async def test_action_dispatches_to_engine(self, analytics_tool):
        with patch.object(
            SimpleAnalyticsEngine,
            "get_transaction_count",
            new=AsyncMock(return_value="**Total Transactions**: 144"),
        ) as mock_method:
            with patch.object(analytics_tool, "get_client", new=AsyncMock(return_value=MagicMock())):
                result = await analytics_tool.handle_action(
                    "get_transaction_count", {"period": "SEVEN_DAYS"}
                )

        mock_method.assert_awaited_once()
        assert "144" in result[0].text

    @pytest.mark.asyncio
    async def test_action_is_listed_as_supported(self, analytics_tool):
        actions = await analytics_tool._get_supported_actions()
        assert "get_transaction_count" in actions


class TestCostProxyRemoval:
    def test_customer_data_has_no_fabricated_count_fields(self):
        names = {f.name for f in fields(CustomerTransactionData)}
        assert "transaction_count" not in names
        assert "cost_per_transaction" not in names

    def test_product_data_has_no_fabricated_count_fields(self):
        names = {f.name for f in fields(ProductTransactionData)}
        assert "transaction_count" not in names
        assert "cost_per_transaction" not in names

    def test_cost_as_proxy_formula_is_gone_from_processor(self):
        source = inspect.getsource(transaction_level_analytics_processor)
        assert "cost / 0.01" not in source
