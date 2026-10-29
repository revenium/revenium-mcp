"""Unit tests for Tool Registry Management tools.

Tests the ToolManager and ToolManagement classes from the decomposed tools module.
Covers CRUD (list, get, get_by_tool_id, create, update, replace, delete, search),
event-metering (meter_event, list_events, record_event, get_events), and analytics actions
including per-tool, aggregated, agent, provider, and filter options.
"""

import ast
import json
import pathlib
from datetime import datetime, timedelta

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.analytics.envelope_reads import ENVELOPE_MAX_PAGES
from src.revenium_mcp_server.analytics_window import CALENDAR_RANGE_MAX_DAYS

from src.revenium_mcp_server.tools_decomposed.tool_management import (
    ToolManager,
    ToolManagement,
)
from src.revenium_mcp_server.auth import AuthConfig
from src.revenium_mcp_server.client import ReveniumAPIError, ReveniumClient
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from mcp.types import TextContent
from tests.unit._helpers_list_heading import LIST_HEADING_CASES, heading_and_body, rows
from tests.unit._registered_tool_harness import call_domain_tool


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


# The tool record as the Tool Registry GET returns it (BACK-4696). The real
# GET never carries teamId, and this tool is disabled so an update that let
# the platform default enabled back to true would show.
STORED_TOOL = {
    "id": "l39KLb",
    "name": "tool-registry-tool-x",
    "toolId": "tool-registry-tool-x",
    "toolType": "MCP_SERVER",
    "description": "Tool: tool-registry-tool-x",
    "enabled": False,
    "toolProvider": "",
    "label": "tool-registry-tool-x",
    "resourceType": "tool",
    "configSource": "DATABASE",
    "created": "2026-10-15T00:00:00Z",
    "updated": "2026-10-15T00:00:00Z",
    "_links": {"self": {"href": "x"}},
    "team": {"id": "test_team_id_456", "label": "t"},
    "pricing": {
        "currency": "USD",
        "elements": [{"name": "requests", "unitPrice": "0.005", "aggregationType": "COUNT", "tiers": None}],
    },
}
_STORED_IDENTITY = {k: STORED_TOOL[k] for k in ("name", "toolId", "toolType", "enabled")}


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
        tool_data = {"name": "New Tool", "toolType": "REST_API"}
        mock_client.create_tool.return_value = {"id": "t3", **tool_data}
        result = await tool_manager.create_tool({"tool_data": tool_data})
        assert result["name"] == "New Tool"
        # teamId is auto-injected from the client's auth context (see BACK-1095)
        mock_client.create_tool.assert_called_once_with(
            {"name": "New Tool", "toolType": "REST_API", "teamId": "test_team_id_456"}
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
        mock_client.get_tool.return_value = dict(STORED_TOOL)
        mock_client.update_tool.return_value = {"id": "t1", "name": "Updated"}
        result = await tool_manager.update_tool({"tool_id": "t1", "tool_data": {"name": "Updated"}})
        assert result["name"] == "Updated"
        mock_client.update_tool.assert_called_once_with(
            "t1", {**_STORED_IDENTITY, "name": "Updated", "teamId": "test_team_id_456"},
        )

    @pytest.mark.asyncio
    async def test_update_tool_preserves_explicit_team_id(self, tool_manager, mock_client):
        mock_client.get_tool.return_value = dict(STORED_TOOL)
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

    # BACK-4696: the platform PUT requires name, toolId and toolType, and
    # defaults a missing enabled to true. An update reads the stored tool and
    # sends those four back under the caller's change, and nothing else.

    @pytest.mark.asyncio
    async def test_a_rename_sends_the_stored_tool_with_the_new_name(self, tool_manager, mock_client):
        mock_client.get_tool.return_value = dict(STORED_TOOL)

        await tool_manager.update_tool({"tool_id": "l39KLb", "tool_data": {"name": "renamed"}})

        mock_client.get_tool.assert_awaited_once_with("l39KLb")
        mock_client.update_tool.assert_awaited_once_with(
            "l39KLb", {**_STORED_IDENTITY, "name": "renamed", "teamId": "test_team_id_456"}
        )

    @pytest.mark.asyncio
    async def test_a_description_change_alone_keeps_the_stored_name(self, tool_manager, mock_client):
        mock_client.get_tool.return_value = dict(STORED_TOOL)

        await tool_manager.update_tool({"tool_id": "l39KLb", "tool_data": {"description": "new text"}})

        body = mock_client.update_tool.await_args.args[1]
        assert body == {**_STORED_IDENTITY, "description": "new text", "teamId": "test_team_id_456"}

    @pytest.mark.asyncio
    async def test_a_disabled_tool_stays_disabled_after_a_rename(self, tool_manager, mock_client):
        mock_client.get_tool.return_value = dict(STORED_TOOL)

        await tool_manager.update_tool({"tool_id": "l39KLb", "tool_data": {"name": "renamed"}})

        body = mock_client.update_tool.await_args.args[1]
        assert body["enabled"] is False

    @pytest.mark.asyncio
    async def test_pricing_is_sent_only_when_the_caller_sends_it(self, tool_manager, mock_client):
        mock_client.get_tool.return_value = dict(STORED_TOOL)

        await tool_manager.update_tool({"tool_id": "l39KLb", "tool_data": {"name": "renamed"}})

        body = mock_client.update_tool.await_args.args[1]
        assert not {"pricing", "description", "toolProvider"} & set(body)

        pricing = {
            "currency": "USD",
            "elements": [{"name": "requests", "unitPrice": 0.01, "aggregationType": "COUNT"}],
        }
        await tool_manager.update_tool({"tool_id": "l39KLb", "tool_data": {"pricing": pricing}})

        body = mock_client.update_tool.await_args.args[1]
        assert body["pricing"] == pricing

    @pytest.mark.asyncio
    async def test_the_callers_value_wins_over_the_stored_one(self, tool_manager, mock_client):
        mock_client.get_tool.return_value = dict(STORED_TOOL)
        tool_data = {"toolType": "REST_API", "enabled": True}

        await tool_manager.update_tool({"tool_id": "l39KLb", "tool_data": tool_data})

        body = mock_client.update_tool.await_args.args[1]
        assert body["toolType"] == "REST_API"
        assert body["enabled"] is True
        assert tool_data == {"toolType": "REST_API", "enabled": True}

    @pytest.mark.asyncio
    async def test_an_unreadable_tool_is_not_found_and_nothing_is_sent(self, tool_manager, mock_client):
        mock_client.get_tool.side_effect = ReveniumAPIError("missing", status_code=404)

        with pytest.raises(ToolError) as exc:
            await tool_manager.update_tool({"tool_id": "l39KLb", "tool_data": {"name": "renamed"}})

        assert exc.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND
        mock_client.update_tool.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_empty_stored_record_sends_nothing(self, tool_manager, mock_client):
        mock_client.get_tool.return_value = {}

        with pytest.raises(ToolError):
            await tool_manager.update_tool({"tool_id": "l39KLb", "tool_data": {"name": "renamed"}})

        mock_client.update_tool.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_input_is_refused_before_the_tool_is_read(self, tool_manager, mock_client):
        mock_client.get_tool.return_value = dict(STORED_TOOL)

        with pytest.raises(ToolError):
            await tool_manager.update_tool({
                "tool_id": "l39KLb",
                "tool_data": {"name": "X", "pricing": {"elements": [{"unitPrice": -1}]}},
            })

        mock_client.get_tool.assert_not_awaited()


class TestToolManagerReplace:
    """replace is an alias for update_tool (BACK-1316/F.2)."""

    @pytest.mark.asyncio
    async def test_replace_routes_through_update_tool(self, tool_manager, mock_client):
        mock_client.get_tool.return_value = dict(STORED_TOOL)
        mock_client.update_tool.return_value = {"id": "t1", "name": "Replaced"}
        result = await tool_manager.update_tool({"tool_id": "t1", "tool_data": {"name": "Replaced"}})
        assert result["name"] == "Replaced"
        mock_client.update_tool.assert_called_once_with(
            "t1", {**_STORED_IDENTITY, "name": "Replaced", "teamId": "test_team_id_456"},
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


class TestRestoreIsRetired:
    """BACK-2935: restore never worked and is no longer advertised.

    The Tool Registry API publishes no restore path, so the action promised a
    recovery the platform cannot perform and every call came back as a raw
    HTTP 404. The action is retired: it is absent from the advertised list and
    invoking it explains that deletion is permanent.
    """

    @pytest.mark.asyncio
    async def test_restore_absent_from_supported_actions(self, tool_mgmt):
        assert "restore" not in await tool_mgmt._get_supported_actions()

    @pytest.mark.asyncio
    async def test_restore_absent_from_advertised_action_enum(self, tool_mgmt):
        schema = await tool_mgmt._get_input_schema()
        assert "restore" not in schema["properties"]["action"]["enum"]

    @pytest.mark.asyncio
    async def test_restore_returns_structured_not_supported_error(self, tool_mgmt):
        """No client is built for a retired action, so this needs no auth."""
        with pytest.raises(ToolError) as excinfo:
            await tool_mgmt.handle_action("restore", {"tool_id": "t1"})
        error = excinfo.value
        assert error.error_code == ErrorCodes.ACTION_NOT_SUPPORTED
        assert "restore is not supported" in error.message
        assert "permanent" in error.message
        assert "404" not in error.message

    def test_no_client_method_posts_a_tools_restore_path(self):
        """The dead upstream call is gone, not merely unreachable."""
        from src.revenium_mcp_server import client as client_module

        source = pathlib.Path(client_module.__file__).read_text()
        assert "/restore" not in source
        assert not hasattr(client_module.ReveniumClient, "restore_tool")

    @pytest.mark.asyncio
    async def test_capabilities_do_not_promise_restore(self, tool_mgmt):
        capabilities = await tool_mgmt._get_tool_capabilities()
        crud = next(c for c in capabilities if c.name == "Tool CRUD Operations")
        assert "restore" not in crud.parameters
        assert not any("restore(" in example for example in crud.examples)
        assert any("no restore endpoint" in limit for limit in crud.limitations)

    @pytest.mark.asyncio
    async def test_delete_result_warns_the_deletion_cannot_be_undone(
        self, tool_mgmt, monkeypatch, mock_client
    ):
        mock_client.delete_tool.return_value = {"status": "deleted"}
        monkeypatch.setattr(tool_mgmt, "get_client", AsyncMock(return_value=mock_client))
        result = await tool_mgmt.handle_action("delete", {"tool_id": "t1"})
        assert "permanent" in result[0].text
        assert "no restore" in result[0].text


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
        mock_client.get_tool.return_value = STORED_TOOL
        mock_client.record_tool_event.return_value = {"id": "e1", **event_data}
        result = await tool_manager.record_event({"tool_id": STORED_TOOL["id"], "event_data": event_data})
        assert result["id"] == "e1"
        mock_client.record_tool_event.assert_called_once_with(STORED_TOOL["toolId"], event_data)

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
        mock_client.get_tool.return_value = STORED_TOOL
        mock_client.get_tool_events.return_value = {"events": [{"id": "e1"}]}
        result = await tool_manager.get_events({"tool_id": STORED_TOOL["id"], "page": 1, "size": 10})
        assert "events" in result
        mock_client.get_tool_events.assert_called_once_with(STORED_TOOL["toolId"], page=1, size=10)

    @pytest.mark.asyncio
    async def test_get_events_uses_defaults(self, tool_manager, mock_client):
        mock_client.get_tool.return_value = STORED_TOOL
        mock_client.get_tool_events.return_value = {"events": []}
        await tool_manager.get_events({"tool_id": STORED_TOOL["id"]})
        mock_client.get_tool_events.assert_called_once_with(STORED_TOOL["toolId"], page=0, size=20)

    @pytest.mark.asyncio
    async def test_get_events_missing_tool_id_raises(self, tool_manager):
        with pytest.raises(ToolError):
            await tool_manager.get_events({})


# BACK-5127: the metering ingest registers any toolId it has not seen as a new
# CUSTOM tool, so the registry id returned by create (5jpoM7 in the audit) was
# forwarded as a toolId, a phantom tool named 5jpoM7 was registered and the
# event was metered against it at charge 0.0.
AUDIT_REGISTRY_ID = "5jpoM7"
AUDIT_TOOL = {**STORED_TOOL, "id": AUDIT_REGISTRY_ID, "toolId": "mcp-test-simple-41b309ea"}
AUDIT_EVENT = {"durationMs": 150, "success": True, "timestamp": "2026-10-28T15:46:59Z"}


def _undecodable_id() -> ReveniumAPIError:
    return ReveniumAPIError("Invalid Tool ID", status_code=400)


def _unknown_tool_id() -> ReveniumAPIError:
    return ReveniumAPIError("Tool not found with toolId", status_code=404)


class TestEventActionsResolveTheRegistryId:
    """record_event and get_events take the registry id or the toolId and send the toolId."""

    @pytest.mark.asyncio
    async def test_record_event_sends_the_toolid_of_the_registry_id(self, tool_manager, mock_client):
        mock_client.get_tool.return_value = AUDIT_TOOL
        await tool_manager.record_event({"tool_id": AUDIT_REGISTRY_ID, "event_data": AUDIT_EVENT})
        mock_client.get_tool.assert_called_once_with(AUDIT_REGISTRY_ID)
        mock_client.get_tool_by_tool_id.assert_not_called()
        mock_client.record_tool_event.assert_called_once_with(AUDIT_TOOL["toolId"], AUDIT_EVENT)

    @pytest.mark.asyncio
    async def test_record_event_still_takes_a_registered_toolid(self, tool_manager, mock_client):
        mock_client.get_tool.side_effect = _undecodable_id()
        mock_client.get_tool_by_tool_id.return_value = AUDIT_TOOL
        await tool_manager.record_event({"tool_id": AUDIT_TOOL["toolId"], "event_data": AUDIT_EVENT})
        mock_client.get_tool_by_tool_id.assert_called_once_with(AUDIT_TOOL["toolId"])
        mock_client.record_tool_event.assert_called_once_with(AUDIT_TOOL["toolId"], AUDIT_EVENT)

    @pytest.mark.parametrize("registry_status", [400, 403, 404])
    @pytest.mark.asyncio
    async def test_record_event_refuses_an_unregistered_value_before_metering(
        self, tool_manager, mock_client, registry_status
    ):
        mock_client.get_tool.side_effect = ReveniumAPIError("no such id", status_code=registry_status)
        mock_client.get_tool_by_tool_id.side_effect = _unknown_tool_id()
        with pytest.raises(ToolError) as exc:
            await tool_manager.record_event({"tool_id": "no-such-tool", "event_data": AUDIT_EVENT})
        mock_client.record_tool_event.assert_not_called()
        assert exc.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND
        assert exc.value.field == "tool_id"
        assert "no-such-tool" in exc.value.message
        assert "Nothing was recorded" in exc.value.message

    @pytest.mark.parametrize("status", [429, 500, 503])
    @pytest.mark.asyncio
    async def test_record_event_lookup_failure_propagates_without_metering(
        self, tool_manager, mock_client, status
    ):
        """A platform failure is not read as "no such tool", which would say to register it again."""
        original = ReveniumAPIError("platform failure", status_code=status)
        mock_client.get_tool.side_effect = original
        with pytest.raises(ReveniumAPIError) as exc:
            await tool_manager.record_event({"tool_id": AUDIT_REGISTRY_ID, "event_data": AUDIT_EVENT})
        assert exc.value is original
        mock_client.get_tool_by_tool_id.assert_not_called()
        mock_client.record_tool_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_record_event_toolid_lookup_failure_propagates(self, tool_manager, mock_client):
        original = ReveniumAPIError("platform failure", status_code=500)
        mock_client.get_tool.side_effect = _undecodable_id()
        mock_client.get_tool_by_tool_id.side_effect = original
        with pytest.raises(ReveniumAPIError) as exc:
            await tool_manager.record_event({"tool_id": AUDIT_TOOL["toolId"], "event_data": AUDIT_EVENT})
        assert exc.value is original
        mock_client.record_tool_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_record_event_checks_event_data_before_any_lookup(self, tool_manager, mock_client):
        with pytest.raises(ToolError):
            await tool_manager.record_event({"tool_id": AUDIT_REGISTRY_ID})
        mock_client.get_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_events_reads_the_toolid_of_the_registry_id(self, tool_manager, mock_client):
        mock_client.get_tool.return_value = AUDIT_TOOL
        await tool_manager.get_events({"tool_id": AUDIT_REGISTRY_ID})
        mock_client.get_tool_events.assert_called_once_with(AUDIT_TOOL["toolId"], page=0, size=20)

    @pytest.mark.asyncio
    async def test_get_events_refuses_an_unregistered_value_and_names_list_events(
        self, tool_manager, mock_client
    ):
        mock_client.get_tool.side_effect = _undecodable_id()
        mock_client.get_tool_by_tool_id.side_effect = _unknown_tool_id()
        with pytest.raises(ToolError) as exc:
            await tool_manager.get_events({"tool_id": "retired-tool"})
        mock_client.get_tool_events.assert_not_called()
        assert exc.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND
        assert any("list_events" in suggestion for suggestion in exc.value.suggestions)

    @pytest.mark.parametrize(
        "action, arguments, as_given",
        [
            ("record_event", {"event_data": AUDIT_EVENT}, "meter_event"),
            ("get_events", {}, "list_events"),
        ],
    )
    @pytest.mark.asyncio
    async def test_a_toolid_with_a_slash_is_refused_with_the_call_that_takes_it_as_given(
        self, tool_manager, mock_client, action, arguments, as_given
    ):
        """The registry has no by-toolId lookup for a '/' (encoded it answers 400, raw it answers 404)."""
        mock_client.get_tool.side_effect = _undecodable_id()
        with pytest.raises(ToolError) as exc:
            await getattr(tool_manager, action)({"tool_id": "github/search", **arguments})
        mock_client.get_tool_by_tool_id.assert_not_called()
        mock_client.record_tool_event.assert_not_called()
        mock_client.get_tool_events.assert_not_called()
        assert exc.value.error_code == ErrorCodes.VALIDATION_ERROR
        assert "github/search" in exc.value.message
        assert any(as_given in suggestion for suggestion in exc.value.suggestions)

    @pytest.mark.asyncio
    async def test_a_registry_id_lookup_is_tried_before_the_slash_refusal(self, tool_manager, mock_client):
        mock_client.get_tool.return_value = AUDIT_TOOL
        await tool_manager.record_event({"tool_id": "odd/value", "event_data": AUDIT_EVENT})
        mock_client.record_tool_event.assert_called_once_with(AUDIT_TOOL["toolId"], AUDIT_EVENT)

    @pytest.mark.parametrize(
        "method_name, expected",
        [
            ("get_tool", "/profitstream/v2/api/tools/a%3Fb%23c"),
            ("get_tool_by_tool_id", "/profitstream/v2/api/tools/by-tool-id/a%3Fb%23c"),
        ],
    )
    @pytest.mark.asyncio
    async def test_the_tool_lookups_percent_encode_the_segment(self, method_name, expected):
        client = ReveniumClient(
            auth_config=AuthConfig(
                api_key="test-key-xyz",
                team_id="team_abc",
                base_url="https://api.test.revenium.ai",
                timeout=5.0,
                max_retries=0,
            )
        )
        client.get = AsyncMock(return_value={})
        await getattr(client, method_name)("a?b#c")
        assert client.get.call_args[0][0] == expected

    @pytest.mark.asyncio
    async def test_the_registered_tool_flags_the_refusal(self, monkeypatch, tmp_path):
        record = AsyncMock()
        monkeypatch.setattr(ReveniumClient, "get_tool", AsyncMock(side_effect=_undecodable_id()))
        monkeypatch.setattr(
            ReveniumClient, "get_tool_by_tool_id", AsyncMock(side_effect=_unknown_tool_id())
        )
        monkeypatch.setattr(ReveniumClient, "record_tool_event", record)
        result, text = await call_domain_tool(
            monkeypatch,
            tmp_path,
            "manage_tools",
            {"action": "record_event", "tool_id": "no-such-tool", "event_data": AUDIT_EVENT},
        )
        assert result.is_error is True, text
        assert "No registered tool has the registry id or toolId 'no-such-tool'" in text
        record.assert_not_called()


class TestEventToolIdIsDocumented:
    """The schema and the examples say which identifier tool_id is for the event actions."""

    @pytest.mark.asyncio
    async def test_tool_id_description_names_both_identifiers_for_events(self, tool_mgmt):
        schema = await tool_mgmt._get_input_schema()
        description = schema["properties"]["tool_id"]["description"]
        assert "record_event" in description
        assert "registry id" in description
        assert "toolId" in description

    @pytest.mark.asyncio
    async def test_record_event_capability_names_the_identifier(self, tool_mgmt):
        capabilities = await tool_mgmt._get_tool_capabilities()
        metering = next(c for c in capabilities if c.name == "Event Metering")
        assert "registry id" in metering.parameters["record_event"]["tool_id"]
        assert not any("tool_id='tool_123'" in example for example in metering.examples)


# ===========================================================================
# ToolManager Analytics Tests
# ===========================================================================


SEPTEMBER_START = "2026-09-01T00:00:00.000Z"
SEPTEMBER_END = "2026-09-30T23:59:59.999Z"
SEPTEMBER = {"start_date": SEPTEMBER_START, "end_date": SEPTEMBER_END}

# action -> (client method, the filters it takes, as caller name -> platform name)
TOOL_REPORT_ACTIONS = {
    "get_cost_breakdown": ("get_cost_by_tool", {"tool_id": "toolIds"}),
    "get_top_tools": ("get_top_tools_by_call_count", {}),
    "get_success_rate": ("get_tool_success_rate", {}),
    "get_latency": ("get_tool_latency", {}),
    "get_cost_aggregated": ("get_cost_by_tool_aggregated", {}),
    "get_cost_by_agent": ("get_cost_by_tool_agent", {}),
    "get_agent_breakdown": ("get_agent_tool_breakdown", {}),
    "get_cost_by_provider": ("get_cost_by_tool_provider", {"provider": "providers"}),
    "get_cost_by_provider_aggregated": ("get_cost_by_tool_provider_aggregated", {}),
}

ONE_PAGE = {"_embedded": {"items": []}, "page": {"number": 0, "size": 100, "totalPages": 1}}


def _bucket(hour):
    return {
        "startTimestamp": f"2026-09-30T{hour:02d}:00:00.000Z",
        "endTimestamp": f"2026-09-30T{hour:02d}:59:59.999Z",
        "groups": [{"groupName": "isotope", "metrics": [{"metricResult": 0.2}]}],
    }


def _pages(hours_per_page):
    total = len(hours_per_page)
    return {
        number: {
            "period": {"start": SEPTEMBER_START, "end": SEPTEMBER_END},
            "_embedded": {"items": [_bucket(hour) for hour in hours]},
            "page": {"number": number, "size": 100, "totalPages": total, "totalElements": 24},
        }
        for number, hours in enumerate(hours_per_page)
    }


def _answer_by_page(pages):
    async def answer(**params):
        return pages[params.get("page", 0)]

    return answer


class TestToolReportsSendThePlatformNames:
    """BACK-4625: every tool analytics action sends the names the isotope operation declares."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", sorted(TOOL_REPORT_ACTIONS))
    async def test_outgoing_parameter_names(self, tool_manager, mock_client, action):
        method, filters = TOOL_REPORT_ACTIONS[action]
        getattr(mock_client, method).return_value = ONE_PAGE
        arguments = {**SEPTEMBER, **dict.fromkeys(filters, "x")}

        await getattr(tool_manager, action)(arguments)

        sent = getattr(mock_client, method).await_args.kwargs
        assert set(sent) == {"startDate", "endDate", "size", *filters.values()}
        assert (sent["startDate"], sent["endDate"]) == (SEPTEMBER_START, SEPTEMBER_END)
        for platform_name in filters.values():
            assert sent[platform_name] == ["x"]

    @pytest.mark.asyncio
    async def test_filter_options_send_no_window_or_filter(self, tool_manager, mock_client):
        mock_client.get_tool_filter_options.return_value = {"tools": []}

        await tool_manager.get_filter_options({"action": "get_filter_options"})

        mock_client.get_tool_filter_options.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_filter_options_refuse_a_window(self, tool_manager, mock_client):
        with pytest.raises(ToolError, match="start_date is not accepted by get_filter_options"):
            await tool_manager.get_filter_options(dict(SEPTEMBER))

        mock_client.get_tool_filter_options.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_calendar_day_covers_the_whole_utc_day(self, tool_manager, mock_client):
        mock_client.get_cost_by_tool_aggregated.return_value = ONE_PAGE

        await tool_manager.get_cost_aggregated({"start_date": "2026-09-01", "end_date": "2026-09-30"})

        sent = mock_client.get_cost_by_tool_aggregated.await_args.kwargs
        assert (sent["startDate"], sent["endDate"]) == (SEPTEMBER_START, SEPTEMBER_END)

    @pytest.mark.asyncio
    async def test_a_period_becomes_the_dates_it_covers(self, tool_manager, mock_client):
        mock_client.get_top_tools_by_call_count.return_value = ONE_PAGE

        await tool_manager.get_top_tools({"period": "SEVEN_DAYS"})

        sent = mock_client.get_top_tools_by_call_count.await_args.kwargs
        assert "period" not in sent
        start = datetime.fromisoformat(sent["startDate"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(sent["endDate"].replace("Z", "+00:00"))
        assert end - start == timedelta(days=7)

    @pytest.mark.asyncio
    async def test_without_a_window_the_platform_default_is_sent(self, tool_manager, mock_client):
        mock_client.get_cost_by_tool_agent.return_value = ONE_PAGE

        read = await tool_manager.get_cost_by_agent({})

        sent = mock_client.get_cost_by_tool_agent.await_args.kwargs
        assert set(sent) == {"startDate", "endDate", "size"}
        assert (sent["startDate"], sent["endDate"]) == (read.window.start, read.window.end)
        start = datetime.fromisoformat(sent["startDate"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(sent["endDate"].replace("Z", "+00:00"))
        assert end - start == timedelta(hours=24)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "action,arguments,refused",
        [
            ("get_cost_aggregated", {"group": "TOTAL"}, "group"),
            ("get_cost_breakdown", {"granularity": "day"}, "granularity"),
            ("get_cost_by_agent", {"agent": "claude-code"}, "agent"),
            ("get_cost_aggregated", {"tool_name": "search"}, "tool_name"),
            ("get_cost_aggregated", {"tool_id": "t1"}, "tool_id"),
            ("get_cost_breakdown", {"provider": "anthropic"}, "provider"),
        ],
    )
    async def test_a_filter_the_report_does_not_take_is_refused(
        self, tool_manager, mock_client, action, arguments, refused
    ):
        method, _ = TOOL_REPORT_ACTIONS[action]

        with pytest.raises(ToolError, match=f"{refused} is not accepted by {action}"):
            await getattr(tool_manager, action)(arguments)

        getattr(mock_client, method).assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "arguments,message",
        [
            ({"period": "SEVEN_DAYS", **SEPTEMBER}, "Pass either period or start_date/end_date"),
            ({"start_date": SEPTEMBER_START}, "start_date and end_date go together"),
            ({"period": "FORTNIGHT"}, "Unsupported period"),
            ({"start_date": "2026-09-30", "end_date": "2026-09-01"}, "is after end_date"),
            (
                {"start_date": "2025-09-01", "end_date": "2026-09-02"},
                f"covers 367 days; at most {CALENDAR_RANGE_MAX_DAYS} are allowed",
            ),
            (
                {"start_date": "2025-09-01T00:00:00Z", "end_date": "2026-09-02T00:00:01Z"},
                f"covers 367 days; at most {CALENDAR_RANGE_MAX_DAYS} are allowed",
            ),
        ],
    )
    async def test_an_unusable_window_is_refused(self, tool_manager, mock_client, arguments, message):
        with pytest.raises(ToolError, match=message):
            await tool_manager.get_cost_aggregated(arguments)

        mock_client.get_cost_by_tool_aggregated.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_answer_names_the_window_asked_for(self, tool_mgmt, mock_client):
        mock_client.get_cost_by_tool_aggregated.return_value = ONE_PAGE
        tool_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await tool_mgmt.handle_action("get_cost_aggregated", dict(SEPTEMBER))

        assert f"Aggregated cost per tool ({SEPTEMBER_START} to {SEPTEMBER_END}):" in result[0].text

    @pytest.mark.asyncio
    async def test_the_longest_calendar_range_is_read(self, tool_manager, mock_client):
        mock_client.get_cost_by_tool_aggregated.return_value = ONE_PAGE

        await tool_manager.get_cost_aggregated({"start_date": "2025-09-01", "end_date": "2026-09-01"})

        sent = mock_client.get_cost_by_tool_aggregated.await_args.kwargs
        assert (sent["startDate"], sent["endDate"]) == (
            "2025-09-01T00:00:00.000Z",
            "2026-09-01T23:59:59.999Z",
        )

    @pytest.mark.asyncio
    async def test_the_answer_names_the_period_asked_for(self, tool_mgmt, mock_client):
        mock_client.get_top_tools_by_call_count.return_value = ONE_PAGE
        tool_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await tool_mgmt.handle_action("get_top_tools", {"period": "SEVEN_DAYS"})

        sent = mock_client.get_top_tools_by_call_count.await_args.kwargs
        assert f"Top tools (SEVEN_DAYS: {sent['startDate']} to {sent['endDate']}):" in result[0].text


class TestToolReportsReadEveryPage:
    """BACK-4640: a tool report's time buckets are read to the last page."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["get_cost_by_provider", "get_cost_breakdown"])
    async def test_three_pages_become_one_complete_series(self, tool_manager, mock_client, action):
        method, _ = TOOL_REPORT_ACTIONS[action]
        getattr(mock_client, method).side_effect = _answer_by_page(
            _pages([range(0, 10), range(10, 20), range(20, 24)])
        )

        read = await getattr(tool_manager, action)(dict(SEPTEMBER))

        calls = getattr(mock_client, method).await_args_list
        assert [call.kwargs.get("page") for call in calls] == [None, 1, 2]
        assert len(read.items) == 24
        assert read.items[-1]["endTimestamp"] == SEPTEMBER_END
        assert read.unread is None
        assert "page" not in read.envelope

    @pytest.mark.asyncio
    async def test_without_a_window_every_page_reads_the_same_default_window(self, tool_mgmt, mock_client):
        mock_client.get_cost_by_tool_provider.side_effect = _answer_by_page(
            _pages([range(0, 10), range(10, 20), range(20, 24)])
        )
        tool_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await tool_mgmt.handle_action("get_cost_by_provider", {})

        calls = mock_client.get_cost_by_tool_provider.await_args_list
        windows = {(call.kwargs["startDate"], call.kwargs["endDate"]) for call in calls}
        assert len(calls) == 3
        assert len(windows) == 1
        (start, end), = windows
        assert (
            f"Cost by provider (TWENTY_FOUR_HOURS, the platform default: {start} to {end}):"
            in result[0].text
        )

    @pytest.mark.asyncio
    async def test_a_read_that_stops_at_the_page_cap_says_so(self, tool_mgmt, mock_client):
        total_pages = ENVELOPE_MAX_PAGES + 1
        mock_client.get_cost_by_tool_provider.side_effect = _answer_by_page(
            _pages([[0]] * total_pages)
        )
        tool_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await tool_mgmt.handle_action("get_cost_by_provider", dict(SEPTEMBER))

        assert mock_client.get_cost_by_tool_provider.await_count == ENVELOPE_MAX_PAGES
        assert f"the platform holds {total_pages} pages" in result[0].text


class TestToolManagerFilterOptions:
    """Test ToolManager.get_filter_options behavior."""

    @pytest.mark.asyncio
    async def test_get_filter_options(self, tool_manager, mock_client):
        mock_client.get_tool_filter_options.return_value = {"tools": ["t1", "t2"]}
        result = await tool_manager.get_filter_options({})
        assert result["tools"] == ["t1", "t2"]
        mock_client.get_tool_filter_options.assert_called_once()


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


_SIMPLE_PRICING_MODELS = ("per_request", "tiered", "flat")

_REFUSED_UNIT_PRICES = [
    pytest.param(-1, "pricing.elements[0].unitPrice must be >= 0", id="negative"),
    pytest.param("-0.5", "pricing.elements[0].unitPrice must be >= 0", id="negative_string"),
    pytest.param("abc", "pricing.elements[0].unitPrice must be a number", id="non_numeric"),
    pytest.param(True, "pricing.elements[0].unitPrice must be a number", id="boolean"),
]


async def _create_refusal(tool_manager, unit_price) -> str:
    pricing = {"elements": [{"name": "requests", "unitPrice": unit_price, "aggregationType": "COUNT"}]}
    with pytest.raises(ToolError) as refused:
        await tool_manager.create_tool({"tool_data": {"name": "T", "pricing": pricing}})
    return refused.value.message


class TestCreateSimpleValidatesPricing:
    """BACK-5148: create_simple refuses the prices create refuses, before any request."""

    @pytest.mark.parametrize("pricing_model", _SIMPLE_PRICING_MODELS)
    @pytest.mark.parametrize("unit_price, reason", _REFUSED_UNIT_PRICES)
    @pytest.mark.asyncio
    async def test_refuses_with_the_create_wording(
        self, tool_manager, mock_client, pricing_model, unit_price, reason
    ):
        with pytest.raises(ToolError) as refused:
            await tool_manager.create_simple(
                {"tool_name": "T", "pricing_model": pricing_model, "per_unit_price": unit_price}
            )

        assert refused.value.message == f"Tool pricing validation failed: {reason}"
        assert refused.value.message == await _create_refusal(tool_manager, unit_price)
        mock_client.create_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_refusal_names_the_argument_the_caller_sent(self, tool_manager):
        with pytest.raises(ToolError) as refused:
            await tool_manager.create_simple({"tool_name": "T", "per_unit_price": "abc"})

        assert refused.value.field == "per_unit_price"
        assert refused.value.value == "abc"

    @pytest.mark.asyncio
    async def test_refusal_does_not_recommend_create_simple_itself(self, tool_manager):
        with pytest.raises(ToolError) as refused:
            await tool_manager.create_simple({"tool_name": "T", "per_unit_price": -1})

        assert not any("create_simple" in s for s in refused.value.suggestions or [])

    @pytest.mark.parametrize("pricing_model", _SIMPLE_PRICING_MODELS)
    @pytest.mark.asyncio
    async def test_numeric_string_price_is_stored_as_a_number(
        self, tool_manager, mock_client, pricing_model
    ):
        mock_client.create_tool.return_value = {"id": "t1"}

        await tool_manager.create_simple(
            {"tool_name": "T", "pricing_model": pricing_model, "per_unit_price": "0.02"}
        )

        element = mock_client.create_tool.call_args[0][0]["pricing"]["elements"][0]
        assert element["unitPrice"] == 0.02

    @pytest.mark.parametrize("pricing_model", _SIMPLE_PRICING_MODELS)
    @pytest.mark.asyncio
    async def test_zero_price_is_accepted(self, tool_manager, mock_client, pricing_model):
        mock_client.create_tool.return_value = {"id": "t1"}

        await tool_manager.create_simple(
            {"tool_name": "T", "pricing_model": pricing_model, "per_unit_price": 0}
        )

        mock_client.create_tool.assert_awaited_once()

    @pytest.mark.parametrize(
        "unit_price, reason",
        [
            pytest.param(-1, "unitPrice must be >= 0", id="negative"),
            pytest.param("abc", "unitPrice must be a number", id="non_numeric"),
        ],
    )
    @pytest.mark.parametrize("dry_run", [False, True], ids=["live", "dry_run"])
    @pytest.mark.asyncio
    async def test_registered_tool_refuses_before_any_request(
        self, monkeypatch, tmp_path, unit_price, reason, dry_run
    ):
        create = AsyncMock()
        monkeypatch.setattr(ReveniumClient, "create_tool", create)
        arguments = {
            "action": "create_simple",
            "tool_name": "mcp-test-neg",
            "pricing_model": "per_request",
            "per_unit_price": unit_price,
        }
        if dry_run:
            arguments["dry_run"] = True

        result, text = await call_domain_tool(monkeypatch, tmp_path, "manage_tools", arguments)

        assert result.is_error is True, text
        if not dry_run:
            assert f"Tool pricing validation failed: pricing.elements[0].{reason}" in text
        create.assert_not_called()


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
        mock_client.get_tool.return_value = dict(STORED_TOOL)
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
        # BACK-3170: a second block carries the per-action parameter reference,
        # which the advertised MCP schema no longer lists.
        assert len(result) == 2
        assert isinstance(result[0], TextContent)
        assert "## Parameters" in result[1].text
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
        """BACK-2937: an unknown action raises so the envelope carries isError."""
        with pytest.raises(ToolError) as exc_info:
            await tool_mgmt.handle_action("nonexistent_action", {})
        assert "Unknown action" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_get_pricing_help_dispatch(self, tool_mgmt):
        """get_pricing_help action is dispatched and returns guide."""
        result = await tool_mgmt.handle_action("get_pricing_help", {})
        assert len(result) == 1
        assert "Tool Pricing Guide" in result[0].text
        assert "pricing_structure" in result[0].text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("page_info, row_count, page, heading, total", LIST_HEADING_CASES)
    async def test_list_heading_counts_the_page_against_the_platform_total(
        self, tool_mgmt, mock_client, page_info, row_count, page, heading, total
    ):
        """The heading counts the page against the platform total, not the rows alone."""
        mock_client._extract_embedded_data.return_value = rows(row_count)
        mock_client._extract_pagination_info.return_value = page_info
        mock_client.list_tools.return_value = {}
        tool_mgmt.client = mock_client

        result = await tool_mgmt.handle_action("list", {"page": page, "size": 20})

        shown_heading, body = heading_and_body(result[0].text)
        assert shown_heading == heading.format(noun="tools")
        assert body["total_records"] == total
        assert body["page"] == page
        assert body["total_found"] == row_count

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
        assert result[0].text.startswith("Found 1 of 21 tools (page 3 of 3):\n\n")
        mock_client.list_tools.assert_called_once_with(page=2, size=10)

    @pytest.mark.asyncio
    async def test_replace_dispatches_to_update_tool(self, tool_mgmt, mock_client):
        mock_client.get_tool.return_value = dict(STORED_TOOL)
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
        assert call_data == {
            **_STORED_IDENTITY,
            "name": "replaced",
            "toolType": "MCP_SERVER",
            "teamId": "test_team_id_456",
        }

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


# ===========================================================================
# Tool Usage Events read-only scope
# ===========================================================================


class TestToolUsageEventsReadOnlyScope:
    """The usage event log is exposed read-only, and the capabilities say so.

    The upstream tool-event controller offers exactly one callable operation --
    the list read behind list_events / get_events. It also declares a per-event
    read-by-id that is hidden from the published API documents, gated by
    denyAll() and returns 501, and inherits create/update/delete that carry no
    request mapping. None of those are adopted, so the tool must not imply a
    write or a by-event-id read exists.
    """

    @staticmethod
    def _capability(capabilities, name):
        return next(c for c in capabilities if c.name == name)

    @pytest.mark.asyncio
    async def test_usage_events_capability_covers_exactly_the_two_reads(self, tool_mgmt):
        capabilities = await tool_mgmt._get_tool_capabilities()
        usage_events = self._capability(capabilities, "Tool Usage Events")
        assert set(usage_events.parameters) == {"list_events", "get_events"}

    @pytest.mark.asyncio
    async def test_usage_events_capability_states_read_only_scope(self, tool_mgmt):
        """Read-only is stated, and the excluded verbs are named explicitly."""
        capabilities = await tool_mgmt._get_tool_capabilities()
        usage_events = self._capability(capabilities, "Tool Usage Events")
        joined = " ".join(usage_events.limitations).lower()
        assert "read-only" in joined
        for verb in ("creating", "updating", "deleting"):
            assert verb in joined, f"read-only scope does not name {verb}"

    @pytest.mark.asyncio
    async def test_usage_events_capability_denies_a_by_event_id_read(self, tool_mgmt):
        """No per-event read exists upstream, so callers are steered to the filters."""
        capabilities = await tool_mgmt._get_tool_capabilities()
        usage_events = self._capability(capabilities, "Tool Usage Events")
        joined = " ".join(usage_events.limitations)
        assert "event ID" in joined
        assert "list_events" in joined
        assert "get_events" in joined

    @pytest.mark.asyncio
    async def test_usage_events_capability_points_writes_at_the_ingest_actions(self, tool_mgmt):
        capabilities = await tool_mgmt._get_tool_capabilities()
        usage_events = self._capability(capabilities, "Tool Usage Events")
        joined = " ".join(usage_events.limitations)
        assert "meter_event" in joined
        assert "record_event" in joined

    @pytest.mark.asyncio
    async def test_event_metering_capability_keeps_only_the_recording_actions(self, tool_mgmt):
        """Recording and reading are separate capabilities so the split is legible."""
        capabilities = await tool_mgmt._get_tool_capabilities()
        metering = self._capability(capabilities, "Event Metering")
        assert set(metering.parameters) == {"meter_event", "record_event"}

    def test_tool_description_states_the_read_only_scope(self, tool_mgmt):
        """tools/list is the only text some agents read before planning a call."""
        assert "read-only once logged" in tool_mgmt.tool_description

    @pytest.mark.asyncio
    async def test_troubleshooting_tips_state_the_read_only_scope(self, tool_mgmt):
        tips = " ".join(await tool_mgmt._get_troubleshooting_tips())
        assert "read-only" in tips
        assert "list_events" in tips

    @pytest.mark.asyncio
    async def test_read_only_scope_reaches_get_tool_metadata_output(self, tool_mgmt):
        """An agent that asks for metadata sees the scope, not only a human reader."""
        result = await tool_mgmt.handle_action("get_tool_metadata", {})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Tool Usage Events" in result[0].text
        assert "Read-only by design" in result[0].text

    @pytest.mark.asyncio
    async def test_no_write_action_targets_the_usage_event_log(self, tool_mgmt):
        """Guard against a later 'complete the CRUD set' change on this surface."""
        actions = await tool_mgmt._get_supported_actions()
        for forbidden in ("create_event", "update_event", "delete_event", "get_event"):
            assert forbidden not in actions


# ===========================================================================
# BACK-2759: agenticJobId discoverability on the metering ingest actions
# ===========================================================================


AGENTIC_JOB_ID_PATTERN = r"^(?!types$|conversion-funnel$)[a-zA-Z0-9][a-zA-Z0-9._-]{0,254}$"
AGENTIC_JOB_ID_MESSAGE = (
    "agenticJobId must start with an alphanumeric character and contain only "
    "alphanumeric, dot, underscore and dash characters; reserved words "
    "(types, conversion-funnel) are not allowed"
)


class TestAgenticJobIdIsDiscoverable:
    """The job link must be visible on the tool surface, not only in the API doc.

    POST /meter/v2/tool/events accepts agenticJobId, which is what ties a tool
    cost back to the agentic job that incurred it. The payload has always been
    forwarded verbatim, so the gap was discoverability: an agent reading the
    schema or get_capabilities had no way to learn the field exists.
    """

    @pytest.mark.asyncio
    async def test_event_data_schema_declares_agentic_job_id(self, tool_mgmt):
        schema = await tool_mgmt._get_input_schema()
        properties = schema["properties"]["event_data"]["properties"]
        assert "agenticJobId" in properties
        assert properties["agenticJobId"]["type"] == "string"

    @pytest.mark.asyncio
    async def test_schema_states_the_exact_server_contract(self, tool_mgmt):
        """The first character must be alphanumeric — a leading dash 400s."""
        schema = await tool_mgmt._get_input_schema()
        description = schema["properties"]["event_data"]["properties"]["agenticJobId"]["description"]
        assert AGENTIC_JOB_ID_PATTERN in description
        assert AGENTIC_JOB_ID_MESSAGE in description

    @pytest.mark.asyncio
    async def test_schema_points_at_the_job_side_of_the_same_identifier(self, tool_mgmt):
        """Same value as the job's AI completion events, readable via manage_jobs."""
        schema = await tool_mgmt._get_input_schema()
        description = schema["properties"]["event_data"]["properties"]["agenticJobId"]["description"]
        assert "AI completion events" in description
        assert "manage_jobs" in description

    @pytest.mark.asyncio
    async def test_event_metering_capability_names_the_field_on_both_actions(self, tool_mgmt):
        capabilities = await tool_mgmt._get_tool_capabilities()
        metering = next(c for c in capabilities if c.name == "Event Metering")
        assert "agenticJobId" in metering.parameters["meter_event"]["event_data"]
        assert "agenticJobId" in metering.parameters["record_event"]["event_data"]

    @pytest.mark.asyncio
    async def test_event_metering_examples_show_the_job_link(self, tool_mgmt):
        capabilities = await tool_mgmt._get_tool_capabilities()
        metering = next(c for c in capabilities if c.name == "Event Metering")
        assert any("agenticJobId" in example for example in metering.examples)

    @pytest.mark.asyncio
    async def test_get_capabilities_example_payload_carries_the_field(self, tool_mgmt):
        """get_capabilities output is what an agent copies into its first call."""
        result = await tool_mgmt.handle_action("get_capabilities", {})
        assert "agenticJobId" in result[0].text

    @pytest.mark.asyncio
    async def test_rollup_caveat_is_stated_so_agents_do_not_over_promise(self, tool_mgmt):
        """Ingest carries the field, but the ROI rollup is still open backend work."""
        capabilities = await tool_mgmt._get_tool_capabilities()
        metering = next(c for c in capabilities if c.name == "Event Metering")
        joined = " ".join(metering.limitations)
        assert "agenticJobId" in joined
        assert "rollup" in joined.lower()


class TestAgenticJobIdIsNotGatedClientSide:
    """The MCP deliberately adds no client-side validation of agenticJobId.

    Unlike the fire-and-forget SDK dispatch, this path is synchronous: a server
    400 comes back to the agent as a structured error response, which is the
    correct surface. Guards against a later "improvement" that adds a regex,
    reserved-word or length check and starts rejecting values the server accepts.
    """

    @pytest.mark.asyncio
    async def test_meter_event_forwards_the_payload_verbatim(self, tool_manager, mock_client):
        event_data = {"toolId": "tool_123", "durationMs": 10, "agenticJobId": "job-abc.1"}
        await tool_manager.meter_event({"event_data": event_data})
        mock_client.meter_tool_event.assert_called_once_with(event_data)

    @pytest.mark.asyncio
    async def test_meter_event_does_not_reject_a_server_invalid_value(self, tool_manager, mock_client):
        """A leading dash and a reserved word both 400 upstream — not here."""
        for value in ("-leading-dash", "types", "conversion-funnel"):
            mock_client.meter_tool_event.reset_mock()
            event_data = {"toolId": "tool_123", "agenticJobId": value}
            await tool_manager.meter_event({"event_data": event_data})
            mock_client.meter_tool_event.assert_called_once_with(event_data)

    @pytest.mark.asyncio
    async def test_record_event_preserves_the_job_link(self, tool_manager, mock_client):
        event_data = {"durationMs": 150, "agenticJobId": "job_123"}
        mock_client.get_tool.return_value = STORED_TOOL
        await tool_manager.record_event({"tool_id": STORED_TOOL["id"], "event_data": event_data})
        mock_client.record_tool_event.assert_called_once_with(STORED_TOOL["toolId"], event_data)

    @pytest.mark.asyncio
    async def test_server_rejection_reaches_the_agent(self, tool_manager, mock_client):
        """The 400 is the validation surface, so it must not be swallowed."""
        mock_client.meter_tool_event.side_effect = ReveniumAPIError(
            message="agenticJobId must start with an alphanumeric character",
            status_code=400,
        )
        with pytest.raises(ReveniumAPIError):
            await tool_manager.meter_event({"event_data": {"agenticJobId": "-bad"}})


class TestAgenticJobIdRejectionThroughTheRegisteredPath:
    """PR #327 review: pin what the AGENT actually sees on a server rejection.

    The registered execution path (standardized_tool_execution) catches the
    ReveniumAPIError and formats it via _format_api_validation_error — the
    agent receives a structured validation error carrying the server's
    message, not the raw exception. This test goes through the formatter the
    execution path uses, so the documented contract and the real surface
    cannot drift apart silently.
    """

    def test_server_rejection_formats_with_the_validation_message(self):
        from src.revenium_mcp_server.client import ReveniumAPIError
        from src.revenium_mcp_server.common.error_handling import format_error_response

        server_message = (
            "agenticJobId must start with an alphanumeric character and contain "
            "only alphanumeric, dot, underscore and dash characters; reserved "
            "words (types, conversion-funnel) are not allowed"
        )
        error = ReveniumAPIError(server_message, status_code=400)

        result = format_error_response(error, "manage_tools.meter_event")

        assert len(result) == 1
        text = result[0].text
        assert "alphanumeric" in text
        assert "reserved" in text
        # The agent-facing surface is a formatted error, not a raised exception.
        assert "ReveniumAPIError" not in text or "400" in text


# ===========================================================================
# BACK-2936: advertised tool categories and the version field that was discarded
# ===========================================================================


class TestToolTypeEnumIsDerived:
    """The advertised categories come from the contract, not from a typed copy."""

    @pytest.mark.asyncio
    async def test_advertised_categories_include_human(self, tool_mgmt):
        """The platform persists HUMAN; the hand-typed list used to omit it."""
        schema = await tool_mgmt._get_input_schema()
        assert "HUMAN" in schema["properties"]["tool_data"]["properties"]["toolType"]["enum"]

    @pytest.mark.asyncio
    async def test_create_simple_tool_type_advertises_the_same_categories(self, tool_mgmt):
        schema = await tool_mgmt._get_input_schema()
        assert (
            schema["properties"]["tool_type"]["enum"]
            == schema["properties"]["tool_data"]["properties"]["toolType"]["enum"]
        )

    @pytest.mark.asyncio
    async def test_no_hand_typed_category_list_remains_in_the_module(self, tool_mgmt):
        """A copied literal is how this drifted; keep it from coming back."""
        from src.revenium_mcp_server.tools_decomposed import tool_management

        source = pathlib.Path(tool_management.__file__).read_text()
        assert "LOCAL_FUNCTION" not in source


class TestToolVersionIsRefusedNotDiscarded:
    """BACK-2936: the tool record has no version, so a version must not look accepted."""

    @pytest.mark.asyncio
    async def test_create_rejects_version_in_tool_data(self, tool_manager, mock_client):
        with pytest.raises(ToolError) as excinfo:
            await tool_manager.create_tool(
                {"tool_data": {"name": "T", "toolType": "HUMAN", "version": "1.0.0"}}
            )
        assert "version" in excinfo.value.message
        mock_client.create_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_rejects_version_in_tool_data(self, tool_manager, mock_client):
        with pytest.raises(ToolError) as excinfo:
            await tool_manager.update_tool({"tool_id": "t1", "tool_data": {"version": "2.0.0"}})
        assert "version" in excinfo.value.message
        mock_client.update_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_simple_rejects_tool_version(self, tool_manager, mock_client):
        with pytest.raises(ToolError) as excinfo:
            await tool_manager.create_simple({"tool_name": "T", "tool_version": "1.0.0"})
        assert "tool_version" in excinfo.value.message
        mock_client.create_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_simple_rejects_empty_string_tool_version(self, tool_manager, mock_client):
        # BACK-2936: presence, not truthiness. An empty string is still a caller
        # asking for a field the platform does not store.
        with pytest.raises(ToolError) as excinfo:
            await tool_manager.create_simple({"tool_name": "T", "tool_version": ""})
        assert "tool_version" in excinfo.value.message
        mock_client.create_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_without_version_still_works(self, tool_manager, mock_client):
        mock_client.create_tool.return_value = {"id": "t1"}
        await tool_manager.create_tool({"tool_data": {"name": "T", "toolType": "HUMAN"}})
        mock_client.create_tool.assert_called_once()
        assert "version" not in mock_client.create_tool.call_args[0][0]


class TestAgentBreakdownOverTheWire:
    """BACK-4696: the agent-tool breakdown answer carries the rows the analytics service sends.

    The service answers this report with its rows under ``data`` and no
    ``_embedded``, so a client that unwraps HAL ``_embedded`` turns it into an
    empty list. Runs a real ReveniumClient against a mocked HTTP response.
    """

    BODY = {
        "id": "x",
        "resourceType": "agent-tool-breakdown",
        "label": "x",
        "period": {"start": "2026-09-15T00:00:00.000Z", "end": "2026-10-15T00:00:00.000Z"},
        "data": [
            {
                "agentName": "revvie",
                "toolName": "engineering-time",
                "toolType": "HUMAN",
                "totalCost": 1143.75,
                "totalCalls": 16,
            }
        ],
        "_links": {"self": {"href": "x"}},
    }

    @pytest.mark.asyncio
    async def test_rows_under_data_reach_the_answer_for_the_dates_asked(self):
        client = ReveniumClient(
            auth_config=AuthConfig(
                api_key="test-key-xyz",
                team_id="team_abc",
                base_url="https://api.test.revenium.ai",
                timeout=5.0,
                max_retries=0,
            )
        )
        response = MagicMock()
        response.status_code = 200
        response.headers = {}
        response.content = b"non-empty"
        response.json.return_value = self.BODY

        def config_value(name, default=None):
            return "https://ai.test.example" if name == "REVENIUM_APP_BASE_URL" else default

        tool_mgmt = ToolManagement()
        tool_mgmt.get_client = AsyncMock(return_value=client)
        with patch("src.revenium_mcp_server.client.get_config_value", side_effect=config_value), \
                patch.object(client.client, "request", new_callable=AsyncMock, return_value=response) as request:
            result = await tool_mgmt.handle_action(
                "get_agent_breakdown",
                {"start_date": "2026-09-15T00:00:00Z", "end_date": "2026-10-15T00:00:00Z"},
            )

        text = result[0].text
        assert '"agentName": "revvie"' in text
        assert '"toolName": "engineering-time"' in text
        assert '"totalCalls": 16' in text
        request.assert_awaited_once()
        sent = request.await_args.kwargs
        params = sent["params"]
        assert params["startDate"] == "2026-09-15T00:00:00.000Z"
        assert params["endDate"] == "2026-10-15T00:00:00.000Z"
        assert "start_date" not in params and "end_date" not in params
        assert sent["url"] == "https://ai.test.example/api/v2/analytics/agent-tool-breakdown"


# ===========================================================================
# BACK-5083: tool_data keys the Tool Registry does not store are refused
# ===========================================================================

# Every field a create or update can write, as the vendored platform spec's
# ToolResource lists them (plan follows pricing; team follows teamId).
_STORED_TOOL_DATA = {
    "name": "Vector DB Query",
    "toolId": "vector-db-query",
    "toolType": "CUSTOM",
    "toolProvider": "internal",
    "description": "Vector database query tool",
    "enabled": True,
    "pricing": {
        "currency": "USD",
        "elements": [{"name": "requests", "unitPrice": 0.01, "aggregationType": "COUNT"}],
    },
    "teamId": "test_team_id_456",
}


def _tool_data_keys_in(call_text: str) -> set:
    """The tool_data keys of a rendered example call such as create(tool_data={...})."""
    call = ast.parse(call_text.replace("{...}", "{}"), mode="eval").body
    tool_data = next(keyword.value for keyword in call.keywords if keyword.arg == "tool_data")
    return {key.value for key in tool_data.keys}


class TestToolDataKeysTheRegistryDoesNotStore:
    """BACK-5083: an unstored tool_data key was answered "Tool updated" and dropped."""

    @pytest.mark.asyncio
    async def test_update_refuses_the_snake_case_spelling_and_names_the_stored_one(
        self, tool_manager, mock_client
    ):
        mock_client.get_tool.return_value = dict(STORED_TOOL)

        with pytest.raises(ToolError) as excinfo:
            await tool_manager.update_tool({"tool_id": "5o2NBn", "tool_data": {"tool_provider": "mcp-test-snake"}})

        assert excinfo.value.error_code == ErrorCodes.VALIDATION_ERROR
        assert "tool_provider" in excinfo.value.message
        assert "toolProvider" in excinfo.value.message
        mock_client.get_tool.assert_not_awaited()
        mock_client.update_tool.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_refuses_an_arbitrary_key_and_sends_nothing(self, tool_manager, mock_client):
        mock_client.get_tool.return_value = dict(STORED_TOOL)

        with pytest.raises(ToolError) as excinfo:
            await tool_manager.update_tool({"tool_id": "5o2NBn", "tool_data": {"colour": "blue"}})

        assert excinfo.value.error_code == ErrorCodes.VALIDATION_ERROR
        assert "colour" in excinfo.value.message
        assert "Nothing was sent" in excinfo.value.message
        mock_client.update_tool.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_stored_field_beside_an_unstored_one_is_not_applied_either(self, tool_manager, mock_client):
        mock_client.get_tool.return_value = dict(STORED_TOOL)

        with pytest.raises(ToolError) as excinfo:
            await tool_manager.update_tool(
                {"tool_id": "5o2NBn", "tool_data": {"description": "new", "colour": "blue", "tool_type": "HUMAN"}}
            )

        assert "colour" in excinfo.value.message
        assert "tool_type" in excinfo.value.message
        assert "toolType" in excinfo.value.message
        mock_client.update_tool.assert_not_awaited()

    @pytest.mark.parametrize(
        ("key", "stored_spelling"),
        [("tool_provider", "toolProvider"), ("type", "toolType"), ("tool_id", "toolId"), ("colour", None)],
    )
    @pytest.mark.asyncio
    async def test_create_refuses_an_unstored_key_before_any_request(
        self, tool_manager, mock_client, key, stored_spelling
    ):
        with pytest.raises(ToolError) as excinfo:
            await tool_manager.create_tool({"tool_data": {"name": "T", "toolType": "CUSTOM", key: "x"}})

        assert excinfo.value.error_code == ErrorCodes.VALIDATION_ERROR
        assert key in excinfo.value.message
        if stored_spelling:
            assert stored_spelling in excinfo.value.message
        mock_client.create_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_accepts_every_stored_field(self, tool_manager, mock_client):
        mock_client.create_tool.return_value = {"id": "t1"}

        await tool_manager.create_tool({"tool_data": dict(_STORED_TOOL_DATA)})

        mock_client.create_tool.assert_awaited_once_with(_STORED_TOOL_DATA)

    @pytest.mark.asyncio
    async def test_update_accepts_every_stored_field(self, tool_manager, mock_client):
        mock_client.get_tool.return_value = dict(STORED_TOOL)

        await tool_manager.update_tool({"tool_id": "5o2NBn", "tool_data": dict(_STORED_TOOL_DATA)})

        mock_client.update_tool.assert_awaited_once_with("5o2NBn", _STORED_TOOL_DATA)

    def test_every_platform_tool_property_is_either_written_or_set_by_the_platform(self):
        from src.revenium_mcp_server.tools_decomposed.tool_management import (
            _PLATFORM_SET_TOOL_FIELDS,
            _TOOL_WRITE_FIELDS,
        )

        spec_path = pathlib.Path(__file__).resolve().parents[2] / "specs" / "openapi" / "hypercurrent.json"
        properties = json.loads(spec_path.read_text())["components"]["schemas"]["ToolResource"]["properties"]
        read_only = {name for name, schema in properties.items() if schema.get("readOnly")}

        assert set(_TOOL_WRITE_FIELDS) == set(_STORED_TOOL_DATA)
        assert not set(_TOOL_WRITE_FIELDS) & set(_PLATFORM_SET_TOOL_FIELDS)
        assert set(_TOOL_WRITE_FIELDS) | set(_PLATFORM_SET_TOOL_FIELDS) == set(properties)
        assert read_only <= set(_PLATFORM_SET_TOOL_FIELDS)

    @pytest.mark.asyncio
    async def test_a_get_record_sent_back_with_one_edit_applies_the_edit(self, tool_manager, mock_client):
        mock_client.get_tool.return_value = dict(STORED_TOOL)
        echoed = {**STORED_TOOL, "description": "edited"}

        await tool_manager.update_tool({"tool_id": "l39KLb", "tool_data": echoed})

        body = mock_client.update_tool.await_args.args[1]
        assert body["description"] == "edited"
        assert not {"id", "created", "updated", "label", "_links", "team", "configSource"} & set(body)

    @pytest.mark.parametrize(
        ("field", "value", "hint"),
        [("id", "other", None), ("team", {"id": "other_team"}, "teamId"), ("plan", {"id": "p2"}, "pricing")],
    )
    @pytest.mark.asyncio
    async def test_a_changed_platform_set_field_is_refused_and_nothing_is_written(
        self, tool_manager, mock_client, field, value, hint
    ):
        mock_client.get_tool.return_value = dict(STORED_TOOL)

        with pytest.raises(ToolError) as excinfo:
            await tool_manager.update_tool({"tool_id": "l39KLb", "tool_data": {"name": "x", field: value}})

        assert excinfo.value.error_code == ErrorCodes.VALIDATION_ERROR
        assert f"{field} (set by the platform" in excinfo.value.message
        if hint:
            assert hint in excinfo.value.message
        assert "did you mean" not in excinfo.value.message
        mock_client.update_tool.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_refuses_a_platform_set_field_without_a_rename_hint(self, tool_manager, mock_client):
        with pytest.raises(ToolError) as excinfo:
            await tool_manager.create_tool({"tool_data": {"name": "T", "toolType": "CUSTOM", "team": {"id": "t"}}})

        assert "team (set by the platform; send teamId" in excinfo.value.message
        assert "did you mean" not in excinfo.value.message
        mock_client.create_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_advertised_tool_data_schema_lists_only_accepted_fields(self, tool_mgmt):
        schema = (await tool_mgmt._get_input_schema())["properties"]["tool_data"]

        assert set(schema["properties"]) == set(_STORED_TOOL_DATA)
        assert schema["additionalProperties"] is False

    @pytest.mark.parametrize(("method", "arguments"), [("create_tool", {}), ("update_tool", {"tool_id": "t1"})])
    @pytest.mark.asyncio
    async def test_missing_parameter_examples_use_only_accepted_fields(self, tool_manager, method, arguments):
        with pytest.raises(ToolError) as excinfo:
            await getattr(tool_manager, method)(arguments)

        assert _tool_data_keys_in(excinfo.value.examples["usage"]) <= set(_STORED_TOOL_DATA)

    @pytest.mark.asyncio
    async def test_capability_examples_use_only_accepted_fields(self, tool_mgmt):
        crud = next(c for c in await tool_mgmt._get_tool_capabilities() if c.name == "Tool CRUD Operations")
        tool_data_examples = [example for example in crud.examples if "tool_data=" in example]

        assert any(example.startswith("update(") for example in tool_data_examples)
        for example in tool_data_examples:
            assert _tool_data_keys_in(example) <= set(_STORED_TOOL_DATA)

    @pytest.mark.asyncio
    async def test_get_examples_create_and_update_use_only_accepted_fields(self, tool_mgmt):
        result = await tool_mgmt.handle_action("get_examples", {})
        examples = json.loads(result[0].text.split("\n", 1)[1])["examples"]

        for action in ("create", "update"):
            assert set(examples[action]["tool_data"]) <= set(_STORED_TOOL_DATA)
