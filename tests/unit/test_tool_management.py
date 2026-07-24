"""Unit tests for Tool Registry Management tools.

Tests the ToolManager and ToolManagement classes from the decomposed tools module.
Covers CRUD (list, get, get_by_tool_id, create, update, replace, delete, restore, search),
event-metering (meter_event, list_events, record_event, get_events), and analytics actions
including per-tool, aggregated, agent, provider, and filter options.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.tools_decomposed.tool_management import (
    ToolManager,
    ToolManagement,
)
from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from mcp.types import TextContent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_client():
    """Create a mock ReveniumClient for ToolManager."""
    client = MagicMock()
    client.team_id = "test_team_id_456"
    client.list_tools = AsyncMock()
    client.get_tool = AsyncMock()
    client.get_tool_by_tool_id = AsyncMock()
    client.create_tool = AsyncMock()
    client.update_tool = AsyncMock()
    client.delete_tool = AsyncMock()
    client.restore_tool = AsyncMock()
    client.search_tools = AsyncMock()
    client.meter_tool_event = AsyncMock()
    client.list_tool_events = AsyncMock()
    client.get_cost_by_tool = AsyncMock()
    client.get_top_tools_by_call_count = AsyncMock()
    client.get_tool_success_rate = AsyncMock()
    client.get_tool_latency = AsyncMock()
    client.record_tool_event = AsyncMock()
    client.get_tool_events = AsyncMock()
    client.get_cost_by_tool_aggregated = AsyncMock()
    client.get_cost_by_tool_agent = AsyncMock()
    client.get_agent_tool_breakdown = AsyncMock()
    client.get_cost_by_tool_provider = AsyncMock()
    client.get_cost_by_tool_provider_aggregated = AsyncMock()
    client.get_tool_filter_options = AsyncMock()
    client._extract_embedded_data = MagicMock()
    client._extract_pagination_info = MagicMock()
    return client


@pytest.fixture
def tool_manager(mock_client):
    """Create ToolManager with mocked client."""
    return ToolManager(mock_client)


@pytest.fixture
def tool_mgmt():
    """Create ToolManagement instance (top-level tool)."""
    return ToolManagement()


# ===========================================================================
# ToolManager CRUD Tests
# ===========================================================================


class TestToolManagerList:
    """Test ToolManager.list_tools behavior."""

    @pytest.mark.asyncio
    async def test_list_tools_returns_paginated_result(self, tool_manager, mock_client):
        """Listing tools returns data with pagination."""
        mock_client._extract_embedded_data.return_value = [
            {"id": "t1", "name": "Equifax"},
            {"id": "t2", "name": "Plaid"},
        ]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 2}

        result = await tool_manager.list_tools({"page": 0, "size": 20})

        assert result["action"] == "list"
        assert result["total_found"] == 2
        assert len(result["tools"]) == 2
        mock_client.list_tools.assert_called_once_with(page=0, size=20)

    @pytest.mark.asyncio
    async def test_list_tools_uses_defaults(self, tool_manager, mock_client):
        """List without explicit args uses default page=0, size=20."""
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalPages": 0, "totalElements": 0}

        await tool_manager.list_tools({})

        mock_client.list_tools.assert_called_once_with(page=0, size=20)

    @pytest.mark.asyncio
    async def test_list_tools_rejects_non_numeric_page(self, tool_manager, mock_client):
        """Wrong-type page raises a structured ToolError, not a raw TypeError (BACK-1097)."""
        with pytest.raises(ToolError) as exc:
            await tool_manager.list_tools({"page": "not_a_number"})
        assert exc.value.field == "page"
        mock_client.list_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_tools_coerces_string_page(self, tool_manager, mock_client):
        """A digit-only string for page is coerced rather than rejected."""
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {}
        await tool_manager.list_tools({"page": "2", "size": "5"})
        mock_client.list_tools.assert_called_once_with(page=2, size=5)


class TestToolManagerGet:
    """Test ToolManager.get_tool behavior."""

    @pytest.mark.asyncio
    async def test_get_tool_returns_data(self, tool_manager, mock_client):
        mock_client.get_tool.return_value = {"id": "t1", "name": "Equifax"}
        result = await tool_manager.get_tool({"tool_id": "t1"})
        assert result["id"] == "t1"
        mock_client.get_tool.assert_called_once_with("t1")

    @pytest.mark.asyncio
    async def test_get_tool_missing_id_raises(self, tool_manager):
        with pytest.raises(ToolError):
            await tool_manager.get_tool({})

    @pytest.mark.asyncio
    async def test_get_tool_500_translates_to_not_found(self, tool_manager, mock_client):
        """HTTP 500 from the registry on a bogus tool_id surfaces as a structured
        RESOURCE_NOT_FOUND ToolError mentioning Tool (BACK-1098)."""
        mock_client.get_tool.side_effect = ReveniumAPIError("boom", status_code=500)
        with pytest.raises(ToolError) as exc:
            await tool_manager.get_tool({"tool_id": "NONEXISTENT"})
        assert exc.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND
        assert exc.value.field == "tool_id"
        assert "Tool" in exc.value.message
        assert "NONEXISTENT" in exc.value.message

    @pytest.mark.asyncio
    async def test_get_tool_404_translates_to_not_found(self, tool_manager, mock_client):
        """HTTP 404 also maps to the same structured error envelope."""
        mock_client.get_tool.side_effect = ReveniumAPIError("missing", status_code=404)
        with pytest.raises(ToolError) as exc:
            await tool_manager.get_tool({"tool_id": "X"})
        assert exc.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_get_tool_403_translates_to_not_found(self, tool_manager, mock_client):
        """HTTP 403 from the Tool Registry surfaces as 'Tool not found'.

        The server returns 403 (not 404) when a caller GETs a previously-
        deleted tool_id; from the client's POV this is semantically
        equivalent to "not found" (no cross-tenant ID leak).
        """
        mock_client.get_tool.side_effect = ReveniumAPIError("forbidden", status_code=403)
        with pytest.raises(ToolError) as exc:
            await tool_manager.get_tool({"tool_id": "DELETED"})
        assert exc.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND
        assert exc.value.field == "tool_id"
        assert "DELETED" in exc.value.message

    @pytest.mark.asyncio
    async def test_get_tool_other_api_errors_propagate(self, tool_manager, mock_client):
        """API errors outside the {403, 404, 500} not-found set still
        propagate unchanged so callers can distinguish genuine failures."""
        original = ReveniumAPIError("rate limited", status_code=429)
        mock_client.get_tool.side_effect = original
        with pytest.raises(ReveniumAPIError) as exc:
            await tool_manager.get_tool({"tool_id": "X"})
        assert exc.value is original


class TestToolManagerGetByToolId:
    """Test ToolManager.get_by_tool_id behavior."""

    @pytest.mark.asyncio
    async def test_get_by_tool_id_returns_data(self, tool_manager, mock_client):
        mock_client.get_tool_by_tool_id.return_value = {"id": "t1", "toolId": "my-tool"}
        result = await tool_manager.get_by_tool_id({"tool_id": "my-tool"})
        assert result["toolId"] == "my-tool"
        mock_client.get_tool_by_tool_id.assert_called_once_with("my-tool")

    @pytest.mark.asyncio
    async def test_get_by_tool_id_missing_raises(self, tool_manager):
        with pytest.raises(ToolError):
            await tool_manager.get_by_tool_id({})

    @pytest.mark.asyncio
    async def test_get_by_tool_id_500_translates_to_not_found(self, tool_manager, mock_client):
        """get_by_tool_id gets the same translation contract as get_tool."""
        mock_client.get_tool_by_tool_id.side_effect = ReveniumAPIError("boom", status_code=500)
        with pytest.raises(ToolError) as exc:
            await tool_manager.get_by_tool_id({"tool_id": "missing-team-scoped-id"})
        assert exc.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND
        assert "toolId" in exc.value.message

    @pytest.mark.asyncio
    async def test_get_by_tool_id_403_translates_to_not_found(self, tool_manager, mock_client):
        """get_by_tool_id mirrors get_tool's 403 handling."""
        mock_client.get_tool_by_tool_id.side_effect = ReveniumAPIError("forbidden", status_code=403)
        with pytest.raises(ToolError) as exc:
            await tool_manager.get_by_tool_id({"tool_id": "deleted-team-scoped"})
        assert exc.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND
        assert "toolId" in exc.value.message


class TestToolManagerCreate:
    """Test ToolManager.create_tool behavior."""

    @pytest.mark.asyncio
    async def test_create_tool_sends_data(self, tool_manager, mock_client):
        tool_data = {"name": "New Tool", "type": "api"}
        mock_client.create_tool.return_value = {"id": "t3", **tool_data}
        result = await tool_manager.create_tool({"tool_data": tool_data})
        assert result["name"] == "New Tool"
        # teamId is auto-injected from the client's auth context (see BACK-1095)
        mock_client.create_tool.assert_called_once_with(
            {"name": "New Tool", "type": "api", "teamId": "test_team_id_456"}
        )

    @pytest.mark.asyncio
    async def test_create_tool_missing_data_raises(self, tool_manager):
        with pytest.raises(ToolError):
            await tool_manager.create_tool({})

    @pytest.mark.asyncio
    async def test_create_tool_injects_team_id(self, tool_manager, mock_client):
        """create injects teamId from the client's auth context (BACK-1095)."""
        mock_client.create_tool.return_value = {"id": "t1"}
        await tool_manager.create_tool({"tool_data": {"name": "X", "toolType": "MCP_SERVER"}})
        sent = mock_client.create_tool.call_args[0][0]
        assert sent["teamId"] == "test_team_id_456"

    @pytest.mark.asyncio
    async def test_create_tool_preserves_explicit_team_id(self, tool_manager, mock_client):
        """An explicit teamId in the payload is not overwritten by the auto-injection."""
        mock_client.create_tool.return_value = {"id": "t1"}
        await tool_manager.create_tool(
            {"tool_data": {"name": "X", "toolType": "MCP_SERVER", "teamId": "custom_team"}}
        )
        sent = mock_client.create_tool.call_args[0][0]
        assert sent["teamId"] == "custom_team"


class TestToolManagerUpdate:
    """Test ToolManager.update_tool behavior."""

    @pytest.mark.asyncio
    async def test_update_tool_sends_patch(self, tool_manager, mock_client):
        mock_client.update_tool.return_value = {"id": "t1", "name": "Updated"}
        result = await tool_manager.update_tool({"tool_id": "t1", "tool_data": {"name": "Updated"}})
        assert result["name"] == "Updated"
        mock_client.update_tool.assert_called_once_with(
            "t1", {"name": "Updated", "teamId": "test_team_id_456"},
        )

    @pytest.mark.asyncio
    async def test_update_tool_preserves_explicit_team_id(self, tool_manager, mock_client):
        mock_client.update_tool.return_value = {"id": "t1"}
        await tool_manager.update_tool({
            "tool_id": "t1",
            "tool_data": {"name": "X", "teamId": "explicit_team"},
        })
        call_data = mock_client.update_tool.call_args[0][1]
        assert call_data["teamId"] == "explicit_team"

    @pytest.mark.asyncio
    async def test_update_tool_missing_id_raises(self, tool_manager):
        with pytest.raises(ToolError):
            await tool_manager.update_tool({})

    @pytest.mark.asyncio
    async def test_update_tool_missing_data_raises(self, tool_manager):
        """update_tool with tool_id but no tool_data raises ToolError."""
        with pytest.raises(ToolError):
            await tool_manager.update_tool({"tool_id": "t1"})


class TestToolManagerReplace:
    """replace is an alias for update_tool (BACK-1316/F.2)."""

    @pytest.mark.asyncio
    async def test_replace_routes_through_update_tool(self, tool_manager, mock_client):
        mock_client.update_tool.return_value = {"id": "t1", "name": "Replaced"}
        result = await tool_manager.update_tool({"tool_id": "t1", "tool_data": {"name": "Replaced"}})
        assert result["name"] == "Replaced"
        mock_client.update_tool.assert_called_once_with(
            "t1", {"name": "Replaced", "teamId": "test_team_id_456"},
        )

    @pytest.mark.asyncio
    async def test_replace_missing_id_raises(self, tool_manager):
        with pytest.raises(ToolError):
            await tool_manager.update_tool({"tool_data": {"name": "X"}})

    @pytest.mark.asyncio
    async def test_replace_missing_data_raises(self, tool_manager):
        with pytest.raises(ToolError):
            await tool_manager.update_tool({"tool_id": "t1"})

    @pytest.mark.asyncio
    async def test_replace_with_invalid_pricing_raises(self, tool_manager):
        with pytest.raises(ToolError):
            await tool_manager.update_tool({
                "tool_id": "t1",
                "tool_data": {"name": "X", "pricing": {"elements": [{"unitPrice": -1}]}},
            })


class TestToolManagerDelete:
    """Test ToolManager.delete_tool behavior."""

    @pytest.mark.asyncio
    async def test_delete_tool_calls_client(self, tool_manager, mock_client):
        mock_client.delete_tool.return_value = {"status": "deleted"}
        result = await tool_manager.delete_tool({"tool_id": "t1"})
        assert result["status"] == "deleted"
        mock_client.delete_tool.assert_called_once_with("t1")

    @pytest.mark.asyncio
    async def test_delete_tool_missing_id_raises(self, tool_manager):
        with pytest.raises(ToolError):
            await tool_manager.delete_tool({})


class TestToolManagerRestore:
    """Test ToolManager.restore_tool behavior."""

    @pytest.mark.asyncio
    async def test_restore_tool_calls_client(self, tool_manager, mock_client):
        mock_client.restore_tool.return_value = {"id": "t1", "status": "active"}
        result = await tool_manager.restore_tool({"tool_id": "t1"})
        assert result["status"] == "active"
        mock_client.restore_tool.assert_called_once_with("t1")

    @pytest.mark.asyncio
    async def test_restore_tool_missing_id_raises(self, tool_manager):
        with pytest.raises(ToolError):
            await tool_manager.restore_tool({})


class TestToolManagerSearch:
    """Test ToolManager.search_tools behavior."""

    @pytest.mark.asyncio
    async def test_search_tools_calls_client(self, tool_manager, mock_client):
        mock_client._extract_embedded_data.return_value = [{"id": "t1", "name": "Match"}]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 1}
        result = await tool_manager.search_tools({"query": "Match", "page": 0, "size": 10})
        assert result["action"] == "search"
        assert result["tools"] == [{"id": "t1", "name": "Match"}]
        # filter_warning must be present when there is at least one match —
        # the page-bounded scope caveat applies to non-empty results.
        assert "filter_warning" in result
        mock_client.search_tools.assert_called_once_with(query="Match", page=0, size=10)


# ===========================================================================
# ToolManager Event-Metering Tests
# ===========================================================================


class TestToolManagerMeterEvent:
    """Test ToolManager.meter_event behavior."""

    @pytest.mark.asyncio
    async def test_meter_event_sends_data(self, tool_manager, mock_client):
        event_data = {"toolId": "t1", "event_type": "usage", "tokens": 1000}
        mock_client.meter_tool_event.return_value = {"id": "e1", **event_data}
        result = await tool_manager.meter_event({"event_data": event_data})
        assert result["id"] == "e1"
        mock_client.meter_tool_event.assert_called_once_with(event_data)

    @pytest.mark.asyncio
    async def test_meter_event_missing_data_raises(self, tool_manager):
        with pytest.raises(ToolError):
            await tool_manager.meter_event({})


class TestToolManagerListEvents:
    """Test ToolManager.list_events behavior."""

    @pytest.mark.asyncio
    async def test_list_events_calls_global_endpoint(self, tool_manager, mock_client):
        mock_client.list_tool_events.return_value = {"events": []}
        await tool_manager.list_events({"page": 0, "size": 10})
        mock_client.list_tool_events.assert_called_once_with(page=0, size=10)

    @pytest.mark.asyncio
    async def test_list_events_passes_query_search_filter(self, tool_manager, mock_client):
        """The server-side query search term reaches the API call.

        The tool-events endpoint searches transaction ID by exact match for
        UUID terms, then falls back to partial match across tool name, tool ID
        and resource/operation.
        """
        mock_client.list_tool_events.return_value = {"events": []}
        await tool_manager.list_events({"filters": {"query": "vector-search"}})
        mock_client.list_tool_events.assert_called_once_with(page=0, size=20, query="vector-search")


# ===========================================================================
# ToolManager Per-Tool Event Tests (record_event, get_events)
# ===========================================================================


class TestToolManagerRecordEvent:
    """Test ToolManager.record_event behavior."""

    @pytest.mark.asyncio
    async def test_record_event_sends_data(self, tool_manager, mock_client):
        event_data = {"type": "invocation", "durationMs": 150, "success": True}
        mock_client.record_tool_event.return_value = {"id": "e1", **event_data}
        result = await tool_manager.record_event({"tool_id": "t1", "event_data": event_data})
        assert result["id"] == "e1"
        mock_client.record_tool_event.assert_called_once_with("t1", event_data)

    @pytest.mark.asyncio
    async def test_record_event_missing_tool_id_raises(self, tool_manager):
        with pytest.raises(ToolError):
            await tool_manager.record_event({"event_data": {"type": "invocation"}})

    @pytest.mark.asyncio
    async def test_record_event_missing_event_data_raises(self, tool_manager):
        with pytest.raises(ToolError):
            await tool_manager.record_event({"tool_id": "t1"})


class TestToolManagerGetEvents:
    """Test ToolManager.get_events behavior."""

    @pytest.mark.asyncio
    async def test_get_events_calls_client(self, tool_manager, mock_client):
        mock_client.get_tool_events.return_value = {"events": [{"id": "e1"}]}
        result = await tool_manager.get_events({"tool_id": "t1", "page": 1, "size": 10})
        assert "events" in result
        mock_client.get_tool_events.assert_called_once_with("t1", page=1, size=10)

    @pytest.mark.asyncio
    async def test_get_events_uses_defaults(self, tool_manager, mock_client):
        mock_client.get_tool_events.return_value = {"events": []}
        await tool_manager.get_events({"tool_id": "t1"})
        mock_client.get_tool_events.assert_called_once_with("t1", page=0, size=20)

    @pytest.mark.asyncio
    async def test_get_events_missing_tool_id_raises(self, tool_manager):
        with pytest.raises(ToolError):
            await tool_manager.get_events({})


# ===========================================================================
# ToolManager Analytics Tests
# ===========================================================================


class TestToolManagerCostBreakdown:
    """Test ToolManager.get_cost_breakdown behavior."""

    @pytest.mark.asyncio
    async def test_get_cost_breakdown(self, tool_manager, mock_client):
        mock_client.get_cost_by_tool.return_value = {"data": []}
        result = await tool_manager.get_cost_breakdown({"action": "get_cost_breakdown"})
        assert "data" in result
        mock_client.get_cost_by_tool.assert_called_once()


class TestToolManagerTopTools:
    """Test ToolManager.get_top_tools behavior."""

    @pytest.mark.asyncio
    async def test_get_top_tools(self, tool_manager, mock_client):
        mock_client.get_top_tools_by_call_count.return_value = {"tools": []}
        result = await tool_manager.get_top_tools({"action": "get_top_tools"})
        assert "tools" in result
        mock_client.get_top_tools_by_call_count.assert_called_once()


class TestToolManagerSuccessRate:
    """Test ToolManager.get_success_rate behavior."""

    @pytest.mark.asyncio
    async def test_get_success_rate(self, tool_manager, mock_client):
        mock_client.get_tool_success_rate.return_value = {"rates": []}
        result = await tool_manager.get_success_rate({"action": "get_success_rate"})
        assert "rates" in result
        mock_client.get_tool_success_rate.assert_called_once()


class TestToolManagerLatency:
    """Test ToolManager.get_latency behavior."""

    @pytest.mark.asyncio
    async def test_get_latency(self, tool_manager, mock_client):
        mock_client.get_tool_latency.return_value = {"latencies": []}
        result = await tool_manager.get_latency({"action": "get_latency"})
        assert "latencies" in result
        mock_client.get_tool_latency.assert_called_once()


class TestToolManagerCostAggregated:
    """Test ToolManager.get_cost_aggregated behavior."""

    @pytest.mark.asyncio
    async def test_get_cost_aggregated(self, tool_manager, mock_client):
        mock_client.get_cost_by_tool_aggregated.return_value = {"data": []}
        result = await tool_manager.get_cost_aggregated({"action": "get_cost_aggregated"})
        assert "data" in result
        mock_client.get_cost_by_tool_aggregated.assert_called_once()


class TestToolManagerCostByAgent:
    """Test ToolManager.get_cost_by_agent behavior."""

    @pytest.mark.asyncio
    async def test_get_cost_by_agent(self, tool_manager, mock_client):
        mock_client.get_cost_by_tool_agent.return_value = {"data": []}
        result = await tool_manager.get_cost_by_agent({"agent": "my-agent", "start_date": "2025-01-01"})
        assert "data" in result
        mock_client.get_cost_by_tool_agent.assert_called_once_with(agent="my-agent", start_date="2025-01-01")


class TestToolManagerAgentBreakdown:
    """Test ToolManager.get_agent_breakdown behavior."""

    @pytest.mark.asyncio
    async def test_get_agent_breakdown(self, tool_manager, mock_client):
        mock_client.get_agent_tool_breakdown.return_value = {"data": []}
        result = await tool_manager.get_agent_breakdown({"action": "get_agent_breakdown"})
        assert "data" in result
        mock_client.get_agent_tool_breakdown.assert_called_once()


class TestToolManagerCostByProvider:
    """Test ToolManager.get_cost_by_provider behavior."""

    @pytest.mark.asyncio
    async def test_get_cost_by_provider(self, tool_manager, mock_client):
        mock_client.get_cost_by_tool_provider.return_value = {"data": []}
        result = await tool_manager.get_cost_by_provider({"provider": "anthropic", "start_date": "2025-01-01"})
        assert "data" in result
        mock_client.get_cost_by_tool_provider.assert_called_once_with(provider="anthropic", start_date="2025-01-01")


class TestToolManagerCostByProviderAggregated:
    """Test ToolManager.get_cost_by_provider_aggregated behavior."""

    @pytest.mark.asyncio
    async def test_get_cost_by_provider_aggregated(self, tool_manager, mock_client):
        mock_client.get_cost_by_tool_provider_aggregated.return_value = {"data": []}
        result = await tool_manager.get_cost_by_provider_aggregated({"action": "get_cost_by_provider_aggregated"})
        assert "data" in result
        mock_client.get_cost_by_tool_provider_aggregated.assert_called_once()


class TestToolManagerFilterOptions:
    """Test ToolManager.get_filter_options behavior."""

    @pytest.mark.asyncio
    async def test_get_filter_options(self, tool_manager, mock_client):
        mock_client.get_tool_filter_options.return_value = {"tools": ["t1", "t2"]}
        result = await tool_manager.get_filter_options({})
        assert result["tools"] == ["t1", "t2"]
        mock_client.get_tool_filter_options.assert_called_once()


class TestToolManagerAnalyticsFilterForwarding:
    """Test _extract_analytics_filters forwards agent and provider params."""

    @pytest.mark.asyncio
    async def test_agent_param_forwarded(self, tool_manager, mock_client):
        mock_client.get_cost_by_tool_agent.return_value = {}
        await tool_manager.get_cost_by_agent({"agent": "a1", "start_date": "2025-01-01", "irrelevant_key": "ignored"})
        mock_client.get_cost_by_tool_agent.assert_called_once_with(agent="a1", start_date="2025-01-01")

    @pytest.mark.asyncio
    async def test_provider_param_forwarded(self, tool_manager, mock_client):
        mock_client.get_cost_by_tool_provider.return_value = {}
        await tool_manager.get_cost_by_provider({"provider": "openai", "end_date": "2025-12-31", "extra": "dropped"})
        mock_client.get_cost_by_tool_provider.assert_called_once_with(provider="openai", end_date="2025-12-31")

    def test_extract_analytics_filters_includes_new_params(self, tool_manager):
        filters = tool_manager._extract_analytics_filters({
            "agent": "a1", "provider": "p1", "start_date": "2025-01-01",
            "tool_id": "t1", "unknown_param": "dropped",
        })
        assert filters == {"agent": "a1", "provider": "p1", "start_date": "2025-01-01", "tool_id": "t1"}

    @pytest.mark.asyncio
    async def test_period_param_forwarded(self, tool_manager, mock_client):
        """period reaches the analytics client method (BACK-1096)."""
        mock_client.get_top_tools_by_call_count.return_value = {}
        await tool_manager.get_top_tools({"period": "SEVEN_DAYS", "junk": "dropped"})
        mock_client.get_top_tools_by_call_count.assert_called_once_with(period="SEVEN_DAYS")

    @pytest.mark.asyncio
    async def test_group_param_forwarded(self, tool_manager, mock_client):
        """group reaches the analytics client method (BACK-1096)."""
        mock_client.get_cost_by_tool.return_value = {}
        await tool_manager.get_cost_breakdown({"group": "TOTAL", "period": "THIRTY_DAYS"})
        mock_client.get_cost_by_tool.assert_called_once_with(group="TOTAL", period="THIRTY_DAYS")

    def test_extract_analytics_filters_includes_period_and_group(self, tool_manager):
        """period and group are recognised analytics params (BACK-1096)."""
        filters = tool_manager._extract_analytics_filters({
            "period": "SEVEN_DAYS", "group": "TOTAL", "tool_id": "t1",
        })
        assert filters == {"period": "SEVEN_DAYS", "group": "TOTAL", "tool_id": "t1"}


# ===========================================================================
# ToolManagement (top-level) Tests
# ===========================================================================


class TestToolManagementMetadata:
    """Test ToolManagement class attributes."""

    def test_tool_name(self, tool_mgmt):
        assert tool_mgmt.tool_name == "manage_tools"

    def test_business_category(self, tool_mgmt):
        assert tool_mgmt.business_category == "Core Business Management Tools"

    @pytest.mark.asyncio
    async def test_supported_actions_include_all_required(self, tool_mgmt):
        actions = await tool_mgmt._get_supported_actions()
        required = [
            "list", "get", "get_by_tool_id", "create", "create_simple", "update", "delete",
            "meter_event", "list_events", "record_event", "get_events",
            "get_cost_breakdown", "get_cost_aggregated", "get_top_tools", "get_success_rate", "get_latency",
            "get_cost_by_agent", "get_agent_breakdown",
            "get_cost_by_provider", "get_cost_by_provider_aggregated",
            "get_filter_options",
            "get_pricing_help",
        ]
        for action in required:
            assert action in actions, f"Missing required action: {action}"

    @pytest.mark.asyncio
    async def test_input_schema_has_action_required(self, tool_mgmt):
        schema = await tool_mgmt._get_input_schema()
        assert "action" in schema["required"]
        assert "action" in schema["properties"]

    @pytest.mark.asyncio
    async def test_input_schema_exposes_period_and_group(self, tool_mgmt):
        """Schema declares period/group so analytics callers don't trigger Pydantic
        rejection (BACK-1096). additionalProperties stays False, so unknown params
        still fail loudly — only these two were the legitimate gap."""
        schema = await tool_mgmt._get_input_schema()
        assert "period" in schema["properties"]
        assert "group" in schema["properties"]
        assert schema["additionalProperties"] is False
        assert "SEVEN_DAYS" in schema["properties"]["period"]["enum"]

    @pytest.mark.asyncio
    async def test_event_data_redirects_subscriber_credential_attribution(self, tool_mgmt):
        """meter_event silently drops subscriberCredential — schema description and
        Event Metering capability point callers at manage_metering for attribution
        instead of advertising a field whose persistence is not verified end-to-end."""
        schema = await tool_mgmt._get_input_schema()
        event_data_desc = schema["properties"]["event_data"]["description"]
        assert "manage_metering" in event_data_desc
        assert "subscriber-credential attribution" in event_data_desc.lower()

        capabilities = await tool_mgmt._get_tool_capabilities()
        event_metering = next(c for c in capabilities if c.name == "Event Metering")
        joined_limitations = " ".join(event_metering.limitations)
        assert "manage_metering" in joined_limitations
        assert "subscriber-credential attribution" in joined_limitations.lower()


# ===========================================================================
# ToolManager Pricing Tests
# ===========================================================================


class TestToolManagerCreateSimple:
    """Test ToolManager.create_simple behavior."""

    @pytest.mark.asyncio
    async def test_create_simple_per_request(self, tool_manager, mock_client):
        """create_simple with per_request model builds correct pricing structure."""
        mock_client.create_tool.return_value = {"id": "t1", "name": "My Tool"}
        await tool_manager.create_simple({
            "tool_name": "My Tool",
            "pricing_model": "per_request",
            "per_unit_price": 0.005,
        })
        call_args = mock_client.create_tool.call_args[0][0]
        assert call_args["name"] == "My Tool"
        assert call_args["pricing"]["currency"] == "USD"
        assert len(call_args["pricing"]["elements"]) == 1
        elem = call_args["pricing"]["elements"][0]
        assert elem["name"] == "requests"
        assert elem["unitPrice"] == 0.005
        assert elem["aggregationType"] == "COUNT"
        assert "tiers" not in elem

    @pytest.mark.asyncio
    async def test_create_simple_tiered(self, tool_manager, mock_client):
        """create_simple with tiered model builds 3 graduated tiers."""
        mock_client.create_tool.return_value = {"id": "t1", "name": "Tiered Tool"}
        await tool_manager.create_simple({
            "tool_name": "Tiered Tool",
            "pricing_model": "tiered",
            "per_unit_price": 0.01,
        })
        call_args = mock_client.create_tool.call_args[0][0]
        tiers = call_args["pricing"]["elements"][0]["tiers"]
        assert len(tiers) == 3
        assert tiers[0]["upTo"] == 1000
        assert tiers[0]["unitPrice"] == 0.01
        assert tiers[1]["upTo"] == 10000
        assert tiers[1]["unitPrice"] == 0.008
        assert tiers[2]["upTo"] is None
        assert tiers[2]["unitPrice"] == 0.005

    @pytest.mark.asyncio
    async def test_create_simple_flat(self, tool_manager, mock_client):
        """create_simple with flat model uses access element."""
        mock_client.create_tool.return_value = {"id": "t1", "name": "Flat Tool"}
        await tool_manager.create_simple({
            "tool_name": "Flat Tool",
            "pricing_model": "flat",
            "per_unit_price": 9.99,
        })
        call_args = mock_client.create_tool.call_args[0][0]
        elem = call_args["pricing"]["elements"][0]
        assert elem["name"] == "access"
        assert elem["unitPrice"] == 9.99

    @pytest.mark.asyncio
    async def test_create_simple_missing_name_raises(self, tool_manager):
        """create_simple without tool_name raises ToolError."""
        with pytest.raises(ToolError):
            await tool_manager.create_simple({"pricing_model": "per_request"})

    @pytest.mark.asyncio
    async def test_create_simple_invalid_model_raises(self, tool_manager):
        """create_simple with unknown pricing_model raises ToolError."""
        with pytest.raises(ToolError):
            await tool_manager.create_simple({"tool_name": "X", "pricing_model": "invalid"})


class TestToolManagerGetPricingHelp:
    """Test ToolManager.get_pricing_help behavior."""

    @pytest.mark.asyncio
    async def test_get_pricing_help_returns_structure(self, tool_manager):
        """get_pricing_help returns complete pricing documentation."""
        result = await tool_manager.get_pricing_help({})
        assert "pricing_structure" in result
        assert "element_fields" in result
        assert "tier_rules" in result
        assert "examples" in result
        assert "convenience_actions" in result
        assert "SUM" in result["element_fields"]["aggregationType"]
        assert "COUNT" in result["element_fields"]["aggregationType"]


class TestToolManagerPricingValidation:
    """Test ToolManager._validate_tool_pricing behavior."""

    def test_valid_pricing_passes(self, tool_manager):
        """Well-formed pricing returns no errors."""
        pricing = {
            "currency": "USD",
            "elements": [{"name": "requests", "unitPrice": 0.01, "aggregationType": "COUNT"}],
        }
        assert tool_manager._validate_tool_pricing(pricing) == []

    def test_valid_tiered_pricing_passes(self, tool_manager):
        """Tiered pricing with correct structure passes."""
        pricing = {
            "elements": [{
                "name": "requests",
                "unitPrice": 0.01,
                "aggregationType": "COUNT",
                "tiers": [
                    {"upTo": 1000, "unitPrice": 0.01},
                    {"upTo": None, "unitPrice": 0.005},
                ],
            }],
        }
        assert tool_manager._validate_tool_pricing(pricing) == []

    def test_invalid_aggregation_type(self, tool_manager):
        """Invalid aggregationType is caught."""
        pricing = {"elements": [{"name": "x", "aggregationType": "INVALID"}]}
        errors = tool_manager._validate_tool_pricing(pricing)
        assert any("aggregationType" in e for e in errors)

    def test_negative_unit_price(self, tool_manager):
        """Negative unitPrice on element is caught."""
        pricing = {"elements": [{"name": "x", "unitPrice": -1}]}
        errors = tool_manager._validate_tool_pricing(pricing)
        assert any("unitPrice must be >= 0" in e for e in errors)

    def test_negative_tier_price(self, tool_manager):
        """Negative unitPrice on tier is caught."""
        pricing = {"elements": [{"name": "x", "tiers": [{"upTo": None, "unitPrice": -0.5}]}]}
        errors = tool_manager._validate_tool_pricing(pricing)
        assert any("unitPrice must be >= 0" in e for e in errors)

    def test_final_tier_missing_null(self, tool_manager):
        """Final tier without upTo: null is caught."""
        pricing = {"elements": [{"name": "x", "tiers": [{"upTo": 1000, "unitPrice": 0.01}]}]}
        errors = tool_manager._validate_tool_pricing(pricing)
        assert any("final tier must have upTo: null" in e for e in errors)

    def test_tier_order_not_ascending(self, tool_manager):
        """Non-ascending tier upTo values are caught."""
        pricing = {"elements": [{
            "name": "x",
            "tiers": [
                {"upTo": 5000, "unitPrice": 0.01},
                {"upTo": 1000, "unitPrice": 0.005},
                {"upTo": None, "unitPrice": 0.001},
            ],
        }]}
        errors = tool_manager._validate_tool_pricing(pricing)
        assert any("ascending" in e for e in errors)

    def test_missing_element_name(self, tool_manager):
        """Element without name is caught."""
        pricing = {"elements": [{"unitPrice": 0.01}]}
        errors = tool_manager._validate_tool_pricing(pricing)
        assert any("name is required" in e for e in errors)

    def test_elements_not_array(self, tool_manager):
        """Non-array elements is caught."""
        pricing = {"elements": "not_an_array"}
        errors = tool_manager._validate_tool_pricing(pricing)
        assert any("must be an array" in e for e in errors)

    @pytest.mark.asyncio
    async def test_create_with_invalid_pricing_raises(self, tool_manager):
        """create_tool with invalid pricing raises ToolError."""
        with pytest.raises(ToolError):
            await tool_manager.create_tool({
                "tool_data": {
                    "name": "Bad Tool",
                    "pricing": {"elements": [{"unitPrice": -1}]},
                }
            })

    @pytest.mark.asyncio
    async def test_update_with_invalid_pricing_raises(self, tool_manager):
        """update_tool with invalid pricing raises ToolError."""
        with pytest.raises(ToolError):
            await tool_manager.update_tool({
                "tool_id": "t1",
                "tool_data": {"pricing": {"elements": "bad"}},
            })

    def test_string_unit_price_passes(self, tool_manager):
        """String unitPrice (as returned by GET round-trip) is accepted (BACK-2396)."""
        pricing = {
            "currency": "USD",
            "elements": [{"name": "x", "unitPrice": "0.0005", "aggregationType": "COUNT"}],
        }
        assert tool_manager._validate_tool_pricing(pricing) == []

    def test_negative_string_unit_price(self, tool_manager):
        """Negative string unitPrice is flagged, not raised as a TypeError (BACK-2396)."""
        pricing = {"elements": [{"name": "x", "unitPrice": "-1"}]}
        errors = tool_manager._validate_tool_pricing(pricing)
        assert any("unitPrice must be >= 0" in e for e in errors)

    def test_non_numeric_string_unit_price(self, tool_manager):
        """Non-numeric string unitPrice produces a structured error, not a raise (BACK-2396)."""
        pricing = {"elements": [{"name": "x", "unitPrice": "abc"}]}
        errors = tool_manager._validate_tool_pricing(pricing)
        assert any("unitPrice must be a number" in e for e in errors)

    def test_string_tier_up_to_ascending_passes(self, tool_manager):
        """Numeric-string tier upTo values in ascending order pass (BACK-2396)."""
        pricing = {"elements": [{
            "name": "x",
            "tiers": [
                {"upTo": "5000", "unitPrice": "0.01"},
                {"upTo": "10000", "unitPrice": "0.008"},
                {"upTo": None, "unitPrice": "0.005"},
            ],
        }]}
        assert tool_manager._validate_tool_pricing(pricing) == []

    def test_string_tier_up_to_not_ascending(self, tool_manager):
        """Numeric-string tier upTo values out of order are still caught (BACK-2396).

        Regression guard for the latent lexicographic-comparison bug where
        "5000" <= "10000" is True as a string comparison but should be
        evaluated numerically.
        """
        pricing = {"elements": [{
            "name": "x",
            "tiers": [
                {"upTo": "10000", "unitPrice": "0.008"},
                {"upTo": "5000", "unitPrice": "0.01"},
                {"upTo": None, "unitPrice": "0.005"},
            ],
        }]}
        errors = tool_manager._validate_tool_pricing(pricing)
        assert any("ascending" in e for e in errors)

    def test_non_numeric_middle_tier_up_to_reported_once(self, tool_manager):
        """A non-numeric middle-tier upTo produces exactly one "must be a number" error.

        Regression guard: previously each middle tier's upTo was coerced
        twice (once as "curr" then again as "prev" on the next iteration),
        so a non-numeric value produced the error message twice.
        """
        pricing = {"elements": [{
            "name": "x",
            "tiers": [
                {"upTo": 1000, "unitPrice": "0.01"},
                {"upTo": "abc", "unitPrice": "0.008"},
                {"upTo": None, "unitPrice": "0.005"},
            ],
        }]}
        errors = tool_manager._validate_tool_pricing(pricing)
        must_be_number_errors = [e for e in errors if "upTo must be a number" in e]
        assert len(must_be_number_errors) == 1

    @pytest.mark.asyncio
    async def test_update_with_string_unit_price_does_not_raise(
        self, tool_manager, mock_client
    ):
        """update_tool with a string unitPrice (GET round-trip) succeeds without TypeError (BACK-2396)."""
        mock_client.update_tool = AsyncMock(return_value={"id": "t1", "name": "x"})
        tool_manager.client = mock_client

        result = await tool_manager.update_tool({
            "tool_id": "t1",
            "tool_data": {
                "pricing": {
                    "elements": [{"name": "x", "unitPrice": "0.0005", "aggregationType": "COUNT"}]
                }
            },
        })

        assert result == {"id": "t1", "name": "x"}
        mock_client.update_tool.assert_called_once()


# ===========================================================================
# ToolManagement (top-level) Tests
# ===========================================================================


class TestToolManagementHandleAction:
    """Test ToolManagement.handle_action dispatch."""

    @pytest.mark.asyncio
    async def test_get_capabilities_returns_actions(self, tool_mgmt):
        result = await tool_mgmt.handle_action("get_capabilities", {})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "get_cost_breakdown" in result[0].text
        assert "meter_event" in result[0].text
        assert "get_by_tool_id" in result[0].text
        assert "create_simple" in result[0].text
        assert "get_pricing_help" in result[0].text

    @pytest.mark.asyncio
    async def test_get_capabilities_includes_pricing_examples(self, tool_mgmt):
        """get_capabilities includes pricing-aware create examples."""
        result = await tool_mgmt.handle_action("get_capabilities", {})
        text = result[0].text
        assert "pricing" in text
        assert "per_unit_price" in text

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self, tool_mgmt):
        result = await tool_mgmt.handle_action("nonexistent_action", {})
        assert len(result) == 1
        assert "Unknown action" in result[0].text

    @pytest.mark.asyncio
    async def test_get_pricing_help_dispatch(self, tool_mgmt):
        """get_pricing_help action is dispatched and returns guide."""
        result = await tool_mgmt.handle_action("get_pricing_help", {})
        assert len(result) == 1
        assert "Tool Pricing Guide" in result[0].text
        assert "pricing_structure" in result[0].text

    @pytest.mark.asyncio
    async def test_list_dispatch_with_digit_string_page_no_typeerror(self, tool_mgmt, mock_client):
        """Digit-string page flows end-to-end to display text without TypeError (BACK-1097).

        Regression guard for the Greptile P1: list_tools coerces page internally,
        but the outer handle_action display text previously read the un-coerced
        arguments dict and raised `TypeError: can only concatenate str (not "int")`.
        """
        mock_client._extract_embedded_data.return_value = [{"id": "t1", "name": "Equifax"}]
        mock_client._extract_pagination_info.return_value = {"totalPages": 3, "totalElements": 21}
        tool_mgmt.client = mock_client

        result = await tool_mgmt.handle_action("list", {"page": "2", "size": "10"})

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "page 3" in result[0].text
        assert "Found 1 tools" in result[0].text
        mock_client.list_tools.assert_called_once_with(page=2, size=10)

    @pytest.mark.asyncio
    async def test_replace_dispatches_to_update_tool(self, tool_mgmt, mock_client):
        mock_client.update_tool.return_value = {"id": "t1", "name": "replaced"}
        tool_mgmt.client = mock_client

        result = await tool_mgmt.handle_action("replace", {
            "tool_id": "t1",
            "tool_data": {"name": "replaced", "toolType": "MCP_SERVER"},
        })

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Tool updated" in result[0].text
        mock_client.update_tool.assert_called_once()
        call_data = mock_client.update_tool.call_args[0][1]
        assert "teamId" in call_data

    @pytest.mark.asyncio
    async def test_auth_failure_reraises_api_error(self, tool_mgmt, mock_client):
        """An auth failure from the client must propagate out of handle_action so
        FastMCP marks the envelope isError:true, not swallow it into content text."""
        mock_client.list_tools.side_effect = ReveniumAPIError(
            "Unauthorized", status_code=401
        )
        tool_mgmt.get_client = AsyncMock(return_value=mock_client)
        with pytest.raises(ReveniumAPIError) as exc:
            await tool_mgmt.handle_action("list", {"page": 0, "size": 20})
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_auth_failure_reraises_tool_error(self, tool_mgmt, mock_client):
        """A ToolError raised while handling an action must propagate, not be
        rendered as ``Tool error: ...`` content text without isError:true."""
        boom = ToolError(message="unauthorized", error_code=ErrorCodes.API_AUTHORIZATION)
        mock_client.list_tools.side_effect = boom
        tool_mgmt.get_client = AsyncMock(return_value=mock_client)
        with pytest.raises(ToolError) as exc:
            await tool_mgmt.handle_action("list", {"page": 0, "size": 20})
        assert exc.value is boom


# ===========================================================================
# Unit Cost Enrichment (BACK-1055)
# ===========================================================================


class TestCostActionEnrichment:
    """Each of the six cost actions must emit ``currency`` and formatted fields."""

    @pytest.mark.asyncio
    async def test_get_cost_aggregated_emits_currency_and_formatted_field(
        self, tool_mgmt, mock_client
    ):
        mock_client.get_cost_by_tool_aggregated.return_value = {
            "_embedded": {"items": [{"toolId": "t1", "totalCost": 106344}]}
        }
        tool_mgmt.get_client = AsyncMock(return_value=mock_client)
        result = await tool_mgmt.handle_action(
            "get_cost_aggregated", {"period": "THIRTY_DAYS"}
        )
        text = result[0].text
        assert '"currency": "USD"' in text
        assert '"totalCost_formatted": "$106,344.00"' in text

    @pytest.mark.asyncio
    async def test_get_cost_by_agent_emits_currency_and_formatted_field(
        self, tool_mgmt, mock_client
    ):
        mock_client.get_cost_by_tool_agent.return_value = {
            "groups": [
                {
                    "groupName": "agent-x",
                    "metrics": [
                        {"metricResult": 480.369, "metricType": "COST_METRIC_BY_TOOL_AGENT"}
                    ],
                }
            ]
        }
        tool_mgmt.get_client = AsyncMock(return_value=mock_client)
        result = await tool_mgmt.handle_action(
            "get_cost_by_agent", {"period": "SEVEN_DAYS"}
        )
        text = result[0].text
        assert '"currency": "USD"' in text
        assert '"metricResult_formatted": "$480.37"' in text

    @pytest.mark.asyncio
    async def test_get_cost_breakdown_emits_currency(
        self, tool_mgmt, mock_client
    ):
        mock_client.get_cost_by_tool.return_value = {
            "groups": [{"metrics": [{"metricResult": 75774}]}]
        }
        tool_mgmt.get_client = AsyncMock(return_value=mock_client)
        result = await tool_mgmt.handle_action("get_cost_breakdown", {})
        text = result[0].text
        assert '"currency": "USD"' in text
        assert '"metricResult_formatted": "$75,774.00"' in text

    @pytest.mark.asyncio
    async def test_get_agent_breakdown_emits_currency(
        self, tool_mgmt, mock_client
    ):
        mock_client.get_agent_tool_breakdown.return_value = {
            "groups": [{"metrics": [{"metricResult": 12.5}]}]
        }
        tool_mgmt.get_client = AsyncMock(return_value=mock_client)
        result = await tool_mgmt.handle_action("get_agent_breakdown", {})
        text = result[0].text
        assert '"currency": "USD"' in text
        assert '"metricResult_formatted": "$12.50"' in text

    @pytest.mark.asyncio
    async def test_get_cost_by_provider_emits_currency(
        self, tool_mgmt, mock_client
    ):
        mock_client.get_cost_by_tool_provider.return_value = {
            "groups": [{"metrics": [{"metricResult": 1}]}]
        }
        tool_mgmt.get_client = AsyncMock(return_value=mock_client)
        result = await tool_mgmt.handle_action("get_cost_by_provider", {})
        text = result[0].text
        assert '"currency": "USD"' in text
        assert '"metricResult_formatted": "$1.00"' in text

    @pytest.mark.asyncio
    async def test_get_cost_by_provider_aggregated_emits_currency(
        self, tool_mgmt, mock_client
    ):
        mock_client.get_cost_by_tool_provider_aggregated.return_value = {
            "groups": [{"metrics": [{"metricResult": 2}]}]
        }
        tool_mgmt.get_client = AsyncMock(return_value=mock_client)
        result = await tool_mgmt.handle_action(
            "get_cost_by_provider_aggregated", {}
        )
        text = result[0].text
        assert '"currency": "USD"' in text
        assert '"metricResult_formatted": "$2.00"' in text


class TestNonCostActionsNotEnriched:
    """Actions that are not cost-related must not have currency labels injected."""

    @pytest.mark.asyncio
    async def test_get_top_tools_has_no_currency(
        self, tool_mgmt, mock_client
    ):
        mock_client.get_top_tools_by_call_count.return_value = {
            "groups": [{"metrics": [{"metricResult": 42}]}]
        }
        tool_mgmt.get_client = AsyncMock(return_value=mock_client)
        result = await tool_mgmt.handle_action("get_top_tools", {})
        text = result[0].text
        assert '"currency": "USD"' not in text
        assert "metricResult_formatted" not in text

    @pytest.mark.asyncio
    async def test_get_success_rate_has_no_currency(
        self, tool_mgmt, mock_client
    ):
        mock_client.get_tool_success_rate.return_value = {
            "groups": [{"metrics": [{"metricResult": 0.95}]}]
        }
        tool_mgmt.get_client = AsyncMock(return_value=mock_client)
        result = await tool_mgmt.handle_action("get_success_rate", {})
        text = result[0].text
        assert '"currency": "USD"' not in text
        assert "metricResult_formatted" not in text

    @pytest.mark.asyncio
    async def test_get_latency_has_no_currency(
        self, tool_mgmt, mock_client
    ):
        mock_client.get_tool_latency.return_value = {
            "groups": [{"metrics": [{"metricResult": 123}]}]
        }
        tool_mgmt.get_client = AsyncMock(return_value=mock_client)
        result = await tool_mgmt.handle_action("get_latency", {})
        text = result[0].text
        assert '"currency": "USD"' not in text
        assert "metricResult_formatted" not in text


# ===========================================================================
# BACK-1138 — search applies a client-side filter and warns about page-1 scope
# ===========================================================================


class TestToolManagerSearchClientSideFilter:
    """Regression for BACK-1138 — search previously forwarded the query as
    ``name=...`` and returned the server's response verbatim. The Tool
    Registry endpoint ignores the filter today and returns every tool, so
    callers got the full list back. Follow the BACK-927 pattern: substring-
    filter the returned page client-side and surface a warning that beyond
    the requested page no other matches are evaluated."""

    @pytest.mark.asyncio
    async def test_search_requires_query(self, tool_manager):
        """An empty query is no longer silently treated as 'list everything'."""
        with pytest.raises(ToolError):
            await tool_manager.search_tools({})

    @pytest.mark.asyncio
    async def test_whitespace_only_query_raises_structured_error(self, tool_manager, mock_client):
        """A whitespace-only query must be rejected before any client call.

        Non-empty but whitespace-only strings are truthy in Python, so an
        unguarded ``if not query`` check would let them through and the
        stripped needle would match every tool (names/descriptions commonly
        contain spaces). Strip before the empty check and raise the structured
        missing-parameter error.
        """
        with pytest.raises(ToolError):
            await tool_manager.search_tools({"query": "   "})
        mock_client.search_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_filters_returned_page_by_name(self, tool_manager, mock_client):
        """Only tools whose name contains the query (case-insensitive) survive."""
        mock_client._extract_embedded_data.return_value = [
            {"id": "t1", "name": "Billing Sync", "description": ""},
            {"id": "t2", "name": "Plaid", "description": ""},
            {"id": "t3", "name": "Equifax", "description": "billing connector"},
        ]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 3}

        result = await tool_manager.search_tools({"query": "billing"})

        assert result["action"] == "search"
        assert result["query"] == "billing"
        assert {t["id"] for t in result["tools"]} == {"t1", "t3"}
        assert result["total_found"] == 2
        assert "filter_warning" in result
        mock_client.search_tools.assert_called_once_with(query="billing", page=0, size=20)

    @pytest.mark.asyncio
    async def test_search_returns_empty_without_warning_on_single_page(
        self, tool_manager, mock_client
    ):
        """Zero matches AND only one page → no warning (true dead end).

        Suppressing the warning here avoids the misleading "phantom matches
        elsewhere" hint Tessie iter-1 flagged: the server reported a single
        page, the caller scanned all of it client-side, and nothing matched.
        """
        mock_client._extract_embedded_data.return_value = [
            {"id": "t1", "name": "Plaid", "description": ""},
        ]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 1}

        result = await tool_manager.search_tools({"query": "billing"})

        assert result["tools"] == []
        assert result["total_found"] == 0
        assert "filter_warning" not in result

    @pytest.mark.asyncio
    async def test_search_returns_empty_with_warning_when_more_pages(
        self, tool_manager, mock_client
    ):
        """Zero matches BUT server reports more pages → warning is present.

        Greptile iter-1 escalated the previous "always drop on empty" change
        to P1: a caller (especially an LLM agent) seeing tools=[] with no
        warning concludes "no such tool exists anywhere" and stops paginating.
        When totalPages > 1 the call only scanned one page of the unfiltered
        list, so the warning must stay to nudge the caller to keep going.
        """
        mock_client._extract_embedded_data.return_value = [
            {"id": "t1", "name": "Plaid", "description": ""},
        ]
        mock_client._extract_pagination_info.return_value = {"totalPages": 5, "totalElements": 100}

        result = await tool_manager.search_tools({"query": "billing"})

        assert result["tools"] == []
        assert result["total_found"] == 0
        assert "filter_warning" in result

    @pytest.mark.asyncio
    async def test_search_passes_pagination_to_client(self, tool_manager, mock_client):
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {}

        await tool_manager.search_tools({"query": "x", "page": 2, "size": 50})

        mock_client.search_tools.assert_called_once_with(query="x", page=2, size=50)


class TestGetExamplesAction:
    """manage_tools was the only tool without get_examples."""

    @pytest.mark.asyncio
    async def test_get_examples_returns_examples(self):
        from src.revenium_mcp_server.tools_decomposed.tool_management import ToolManagement

        tool = ToolManagement()
        result = await tool.handle_action("get_examples", {})
        text = result[0].text
        assert "Tool Registry Examples" in text
        assert "create_simple" in text
        assert "meter_event" in text

    @pytest.mark.asyncio
    async def test_get_examples_is_advertised(self):
        from src.revenium_mcp_server.tools_decomposed.tool_management import ToolManagement

        tool = ToolManagement()
        assert "get_examples" in await tool._get_supported_actions()
