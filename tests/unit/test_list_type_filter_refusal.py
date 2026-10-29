"""BACK-5129: the agent and customer lists refuse filters.type.

AgentController.list and the four customer controllers (users, subscribers,
organizations, teams) bind a hidden ``type`` parameter and never read it, so
a type-filtered list came back with every row and the unfiltered total under
an answer that read as filtered.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tools_decomposed.agent_management import (
    AgentManagement,
    AgentManager,
)
from src.revenium_mcp_server.tools_decomposed.customer_management import (
    CustomerAnalytics,
    CustomerManagement,
    OrganizationManager,
    SubscriberManager,
    TeamManager,
    UserManager,
)
from tests.unit._registered_tool_harness import call_domain_tool

_CUSTOMER_LISTS = [
    ("users", UserManager, "list_users", "get_users"),
    ("subscribers", SubscriberManager, "list_subscribers", "get_subscribers"),
    ("organizations", OrganizationManager, "list_organizations", "get_organizations"),
    ("teams", TeamManager, "list_teams", "get_teams"),
]


def _paged_client() -> MagicMock:
    client = MagicMock()
    client._extract_embedded_data = MagicMock(return_value=[])
    client._extract_pagination_info = MagicMock(return_value={})
    for read in (
        "get_agents",
        "get_users",
        "get_subscribers",
        "get_organizations",
        "get_teams",
    ):
        setattr(client, read, AsyncMock(return_value={}))
    return client


async def _text(tool, action: str) -> str:
    result = await tool.handle_action(action, {})
    return "\n".join(getattr(part, "text", "") for part in result)


class TestAgentListRefusesType:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("agent_type", ["API", "TELEMETRY", "BOGUS"])
    async def test_a_type_filter_is_refused_before_any_read(self, agent_type):
        client = _paged_client()

        with pytest.raises(ToolError) as refused:
            await AgentManager(client).list_agents({"filters": {"type": agent_type}})

        assert refused.value.field == "filters.type"
        assert "cannot be filtered by type" in refused.value.message
        client.get_agents.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_refusal_points_at_the_source_field(self):
        with pytest.raises(ToolError) as refused:
            await AgentManager(_paged_client()).list_agents(
                {"filters": {"type": "API"}}
            )

        assert "`source` field" in refused.value.message
        assert "(API or TELEMETRY)" not in refused.value.message

    @pytest.mark.asyncio
    async def test_the_filter_keys_hint_no_longer_lists_type(self):
        with pytest.raises(ToolError) as refused:
            await AgentManager(_paged_client()).list_agents({"filters": {"label": "x"}})

        assert "Valid filter keys for 'list_agents': query, sort" in str(refused.value)
        assert "query, sort, type" not in str(refused.value)

    @pytest.mark.asyncio
    async def test_query_and_sort_still_reach_the_platform(self):
        client = _paged_client()

        await AgentManager(client).list_agents(
            {"filters": {"query": "copilot", "sort": "created,desc"}}
        )

        sent = client.get_agents.call_args.kwargs
        assert sent["query"] == "copilot"
        assert sent["sort"] == "created,desc"
        assert "type" not in sent

    @pytest.mark.asyncio
    async def test_the_registered_tool_flags_the_refusal(self, monkeypatch, tmp_path):
        result, text = await call_domain_tool(
            monkeypatch,
            tmp_path,
            "get_agents",
            {"action": "list", "filters": {"type": "TELEMETRY"}},
        )

        assert result.is_error is True, text
        assert "cannot be filtered by type" in text


class TestCustomerListsRefuseType:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "resource_type,manager,method,read",
        _CUSTOMER_LISTS,
        ids=[c[0] for c in _CUSTOMER_LISTS],
    )
    async def test_a_type_filter_is_refused_before_any_read(
        self, resource_type, manager, method, read
    ):
        client = _paged_client()

        with pytest.raises(ToolError) as refused:
            await getattr(manager(client), method)({"filters": {"type": "CONSUMER"}})

        assert refused.value.field == "filters.type"
        assert "cannot be filtered by type" in refused.value.message
        getattr(client, read).assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "resource_type,manager,method,read",
        _CUSTOMER_LISTS,
        ids=[c[0] for c in _CUSTOMER_LISTS],
    )
    async def test_the_filter_keys_hint_no_longer_lists_type(
        self, resource_type, manager, method, read
    ):
        with pytest.raises(ToolError) as refused:
            await getattr(manager(_paged_client()), method)({"filters": {"label": "x"}})

        valid_keys = "sort" if resource_type == "teams" else "query, sort"
        assert refused.value.message.endswith(
            f"Valid filter keys for '{method}': {valid_keys}"
        )

    @pytest.mark.asyncio
    async def test_a_teams_query_is_refused_before_any_read(self):
        client = _paged_client()

        with pytest.raises(ToolError) as refused:
            await TeamManager(client).list_teams(
                {"filters": {"query": "zzzz-no-match"}}
            )

        assert refused.value.field == "filters.query"
        assert "cannot be filtered by query" in refused.value.message
        client.get_teams.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_organizations_refusal_points_at_the_types_field(self):
        with pytest.raises(ToolError) as refused:
            await OrganizationManager(_paged_client()).list_organizations(
                {"filters": {"type": "BOGUS_TYPE"}}
            )

        assert "`types` field" in refused.value.message

    @pytest.mark.asyncio
    async def test_analyze_refuses_a_type_filter_before_any_read(self):
        client = _paged_client()

        with pytest.raises(ToolError) as refused:
            await CustomerAnalytics(client).analyze_customers(
                {"resource_type": "organizations", "filters": {"type": "CONSUMER"}}
            )

        assert "cannot be filtered by type" in refused.value.message
        client.get_organizations.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_registered_tool_flags_the_refusal(self, monkeypatch, tmp_path):
        result, text = await call_domain_tool(
            monkeypatch,
            tmp_path,
            "get_customers",
            {
                "action": "list",
                "resource_type": "organizations",
                "filters": {"type": "CONSUMER"},
            },
        )

        assert result.is_error is True, text
        assert "cannot be filtered by type" in text


class TestAdvertisedFiltersMatchTheRefusal:
    @pytest.mark.asyncio
    async def test_the_agent_schema_does_not_offer_type(self):
        schema = await AgentManagement(ucm_helper=None)._get_input_schema()

        description = schema["properties"]["filters"]["description"]
        assert "Valid keys: query, sort." in description
        assert "query, sort, type" not in description

    @pytest.mark.asyncio
    async def test_agent_capabilities_say_type_is_refused(self):
        text = await _text(AgentManagement(ucm_helper=None), "get_capabilities")

        assert "query, sort, type" not in text
        assert "type is refused" in text

    @pytest.mark.asyncio
    async def test_customer_capabilities_name_the_filter_keys_and_the_refusal(self):
        text = await _text(CustomerManagement(ucm_helper=None), "get_capabilities")

        assert "`filters`" in text
        assert "type is refused" in text

    def test_the_customer_validation_schema_does_not_offer_type(self):
        from src.revenium_mcp_server.json_schema_validator import json_schema_validator

        description = json_schema_validator.schemas["manage_customers"]["properties"][
            "filters"
        ]["description"]
        assert "query, sort, type" not in description
        assert "type is refused" in description
