"""BACK-3942: manage_alerts search_provider_api_keys and the API_KEY filter it feeds.

The search returns ids and masked hints so an agent can name a key in an
API_KEY filter row; that row only works on a provider alert, so create has to
keep ``dataSource``.
"""

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from src.revenium_mcp_server.alerts.anomaly_manager import AnomalyManager
from src.revenium_mcp_server.auth import AuthConfig
from src.revenium_mcp_server.client import ReveniumClient
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement

SEARCH_PATH = "/profitstream/v2/api/sources/ai/anomaly/provider-dimensions/api-keys"

# Live shape of an ApiKeyFilterOptionPage item, plus a field the option does not declare.
LIVE_KEY = {
    "id": "apikey_011K4gLy",
    "name": "production-key",
    "provider": "anthropic",
    "partialKeyHint": "sk-ant-...yQAA",
    "active": True,
}
RAW_SECRET = "sk-ant-api03-RAWSECRETVALUE-never-print-me"


def _client() -> ReveniumClient:
    client = ReveniumClient(
        auth_config=AuthConfig(
            api_key="test_key_12345",
            team_id="team_abc",
            base_url="https://api.test.revenium.ai",
            timeout=10.0,
        )
    )
    client.get = AsyncMock(return_value={"items": [], "total": 0})
    return client


class TestSearchProviderApiKeysClient:
    @pytest.mark.asyncio
    async def test_sends_query_provider_paging_and_the_resolved_team(self):
        client = _client()
        await client.search_provider_api_keys(query="prod", provider="anthropic", page=2, size=25)
        assert client.get.call_args[0][0] == SEARCH_PATH
        assert client.get.call_args.kwargs["params"] == {
            "query": "prod",
            "provider": "anthropic",
            "page": 2,
            "size": 25,
            "teamId": "team_abc",
        }

    @pytest.mark.asyncio
    async def test_omits_query_and_provider_when_unset(self):
        client = _client()
        await client.search_provider_api_keys()
        assert client.get.call_args.kwargs["params"] == {
            "page": 0,
            "size": 50,
            "teamId": "team_abc",
        }

    @pytest.mark.asyncio
    async def test_sends_no_team_when_none_resolved(self):
        client = _client()
        with patch.object(ReveniumClient, "team_id", new_callable=PropertyMock, return_value=None):
            await client.search_provider_api_keys(query="prod")
        assert "teamId" not in client.get.call_args.kwargs["params"]


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.search_provider_api_keys = AsyncMock(return_value={"items": [], "total": 0})
    return client


@pytest.fixture
def alert_mgmt(mock_client):
    tools = AlertManagement()
    tools.get_client = AsyncMock(return_value=mock_client)
    tools.anomaly_manager = MagicMock()
    tools.alert_manager = MagicMock()
    return tools


async def _search(alert_mgmt, **arguments):
    result = await alert_mgmt.handle_action("search_provider_api_keys", arguments)
    return result[0].text


class TestSearchProviderApiKeysAction:
    @pytest.mark.asyncio
    async def test_forwards_query_provider_page_and_size(self, alert_mgmt, mock_client):
        await _search(alert_mgmt, query="prod", provider="openai", page=1, size=100)
        mock_client.search_provider_api_keys.assert_awaited_once_with(
            query="prod", provider="openai", page=1, size=100
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("size", [0, 101, -5, True, "many"])
    async def test_refuses_a_size_outside_1_to_100_before_the_call(
        self, alert_mgmt, mock_client, size
    ):
        with pytest.raises(ToolError) as exc_info:
            await _search(alert_mgmt, query="prod", size=size)
        assert exc_info.value.field == "size"
        assert "1 to 100" in exc_info.value.message
        mock_client.search_provider_api_keys.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("size, sent", [(1, 1), (100, 100), ("50", 50)])
    async def test_accepts_sizes_at_the_bounds(self, alert_mgmt, mock_client, size, sent):
        await _search(alert_mgmt, size=size)
        assert mock_client.search_provider_api_keys.call_args.kwargs["size"] == sent

    @pytest.mark.asyncio
    async def test_renders_ids_names_and_masked_hints(self, alert_mgmt, mock_client):
        mock_client.search_provider_api_keys.return_value = {
            "items": [
                LIVE_KEY,
                {"id": "apikey_unnamed", "name": None, "provider": "openai",
                 "partialKeyHint": None, "active": False},
            ],
            "total": 58500,
        }
        text = await _search(alert_mgmt, query="prod", page=0, size=2)

        assert "matching `prod`" in text
        assert "- production-key · id `apikey_011K4gLy` · anthropic · hint `sk-ant-...yQAA` · live" in text
        assert "- (unnamed) · id `apikey_unnamed` · openai · no hint · inactive" in text
        assert "Page 0 · 2 shown of 58500 matching" in text
        assert "None" not in text

    @pytest.mark.asyncio
    async def test_prints_nothing_the_option_does_not_declare(self, alert_mgmt, mock_client):
        leaky = {**LIVE_KEY, "apiKey": RAW_SECRET, "secret": RAW_SECRET}
        mock_client.search_provider_api_keys.return_value = {"items": [leaky], "total": 1}
        text = await _search(alert_mgmt, query="prod")
        assert RAW_SECRET not in text
        assert "sk-ant-...yQAA" in text

    @pytest.mark.asyncio
    async def test_points_the_result_at_a_provider_api_key_filter(self, alert_mgmt, mock_client):
        mock_client.search_provider_api_keys.return_value = {"items": [LIVE_KEY], "total": 1}
        text = await _search(alert_mgmt, query="prod")
        assert '"dataSource": "PROVIDER"' in text
        assert '{"dimension": "API_KEY", "operator": "IS", "value": "<id>"}' in text

    @pytest.mark.asyncio
    async def test_empty_result_says_no_key_matched(self, alert_mgmt, mock_client):
        text = await _search(alert_mgmt, query="nothing-like-this")
        assert "No provider API keys match" in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("total", [0, None])
    async def test_only_a_zero_or_missing_total_says_nothing_matched(
        self, alert_mgmt, mock_client, total
    ):
        mock_client.search_provider_api_keys.return_value = {"items": [], "total": total}
        text = await _search(alert_mgmt, page=1, size=20)
        assert "No provider API keys match" in text

    @pytest.mark.asyncio
    async def test_a_page_past_the_last_match_points_back_to_the_matches(
        self, alert_mgmt, mock_client
    ):
        mock_client.search_provider_api_keys.return_value = {"items": [], "total": 1}
        text = await _search(alert_mgmt, page=1, size=20)
        assert "No provider API keys match" not in text
        assert "1 keys match, but page 1 starts past the last result at size 20" in text
        assert "The matches are on pages 0 to 0." in text

    @pytest.mark.asyncio
    async def test_names_the_last_page_with_results(self, alert_mgmt, mock_client):
        mock_client.search_provider_api_keys.return_value = {"items": [], "total": 45}
        text = await _search(alert_mgmt, page=5, size=20)
        assert "The matches are on pages 0 to 2." in text

    @pytest.mark.asyncio
    async def test_a_page_past_the_search_depth_says_to_narrow(self, alert_mgmt, mock_client):
        mock_client.search_provider_api_keys.return_value = {"items": [], "total": 58500}
        text = await _search(alert_mgmt, page=20, size=50)
        assert "58500 keys match" in text
        assert "the last page with results at size 50 is page 19" in text
        assert "Narrow the search" in text

    @pytest.mark.asyncio
    async def test_is_a_supported_action_with_its_parameters_documented(self, alert_mgmt):
        assert "search_provider_api_keys" in await alert_mgmt._get_supported_actions()
        properties = (await alert_mgmt._get_input_schema())["properties"]
        assert "search_provider_api_keys" in properties["provider"]["description"]
        assert "search_provider_api_keys" in properties["query"]["description"]

    @pytest.mark.asyncio
    async def test_capabilities_name_the_action_beside_the_filter_operators(self, alert_mgmt):
        text = await alert_mgmt._build_enhanced_capabilities_text(None)
        assert "search_provider_api_keys(query=" in text
        assert "**API_KEY filters**" in text


DETECTION_RULES_KEY_BUDGET = {
    "name": "Production key budget",
    "detection_rules": [
        {"rule_type": "CUMULATIVE_USAGE", "metric": "total_cost", "operator": ">",
         "value": 500, "time_window": "monthly"}
    ],
    "filters": [{"field": "api_key", "operator": "is", "value": "apikey_011K4gLy"}],
}


def _created_body(payload):
    client = MagicMock()
    client.team_id = "team_abc"
    client.create_anomaly = AsyncMock(return_value={"id": "anom_1", "name": payload["name"]})
    return client


class TestCreateKeepsDataSource:
    @pytest.mark.asyncio
    async def test_detection_rules_create_sends_the_provider_data_source(self):
        payload = {**DETECTION_RULES_KEY_BUDGET, "dataSource": "PROVIDER"}
        client = _created_body(payload)
        await AnomalyManager().create_anomaly(client, payload)
        body = client.create_anomaly.call_args[0][0]
        assert body["dataSource"] == "PROVIDER"
        assert body["filters"] == [
            {"dimension": "API_KEY", "operator": "IS", "value": "apikey_011K4gLy"}
        ]

    @pytest.mark.asyncio
    async def test_detection_rules_create_adds_no_data_source_the_caller_did_not_pass(self):
        client = _created_body(DETECTION_RULES_KEY_BUDGET)
        await AnomalyManager().create_anomaly(client, dict(DETECTION_RULES_KEY_BUDGET))
        assert "dataSource" not in client.create_anomaly.call_args[0][0]

    def test_direct_format_adds_no_data_source_the_caller_did_not_pass(self):
        validated = AnomalyManager().validate_anomaly_payload({
            "name": "Production key budget",
            "alertType": "CUMULATIVE_USAGE",
            "metricType": "TOTAL_COST",
            "operatorType": "GREATER_THAN",
            "threshold": 500,
        })
        assert "dataSource" not in validated

    def test_provider_data_source_reaches_the_create_payload(self):
        validated = AnomalyManager().validate_anomaly_payload({
            "name": "Production key budget",
            "dataSource": "PROVIDER",
            "alertType": "CUMULATIVE_USAGE",
            "metricType": "TOTAL_COST",
            "operatorType": "GREATER_THAN",
            "threshold": 500,
            "periodDuration": "MONTHLY",
            "filters": [{"dimension": "API_KEY", "operator": "IS", "value": "apikey_011K4gLy"}],
        })
        assert validated["dataSource"] == "PROVIDER"
        assert validated["filters"] == [
            {"dimension": "API_KEY", "operator": "IS", "value": "apikey_011K4gLy"}
        ]
