"""Unit tests for Cost Controls Management tools.

Tests the CostControlsManager and CostControlsManagement classes from the
decomposed tools module. Covers CRUD (list, get, create, update, delete),
the enforcement-visibility actions (list_enforcement_events,
get_enforcement_rules), and the introspection actions.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.tools_decomposed.cost_controls_management import (
    CostControlsManager,
    CostControlsManagement,
)
from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from mcp.types import TextContent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_client():
    """Create a mock ReveniumClient for CostControlsManager."""
    client = MagicMock()
    client.team_id = "test_team_id_456"
    client.get_cost_controls = AsyncMock()
    client.get_cost_control_by_id = AsyncMock()
    client.create_cost_control = AsyncMock()
    client.update_cost_control = AsyncMock()
    client.delete_cost_control = AsyncMock()
    client.get_enforcement_events = AsyncMock()
    client.get_enforcement_rules = AsyncMock()
    client._extract_embedded_data = MagicMock()
    client._extract_pagination_info = MagicMock()
    return client


@pytest.fixture
def cc_manager(mock_client):
    """Create CostControlsManager with mocked client."""
    return CostControlsManager(mock_client)


@pytest.fixture
def cc_mgmt():
    """Create CostControlsManagement instance (top-level tool)."""
    return CostControlsManagement()


def _valid_control_data():
    """A create payload that satisfies boundary validation."""
    return {
        "name": "Monthly Guardrail",
        "metricType": "TOTAL_COST",
        "hardLimit": 1000,
        "windowType": "CALENDAR_MONTH",
        "action": "BLOCK",
    }


# ===========================================================================
# CostControlsManager CRUD Tests
# ===========================================================================


class TestCostControlsManagerList:
    """Test CostControlsManager.list_cost_controls behavior."""

    @pytest.mark.asyncio
    async def test_list_returns_paginated_result(self, cc_manager, mock_client):
        mock_client._extract_embedded_data.return_value = [
            {"id": "cc_1", "name": "budget-a"},
            {"id": "cc_2", "name": "budget-b"},
        ]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 2}
        mock_client.get_cost_controls.return_value = {"_embedded": {}}

        result = await cc_manager.list_cost_controls({"page": 0, "size": 20})

        assert result["total_found"] == 2
        assert result["pagination"]["totalElements"] == 2
        mock_client.get_cost_controls.assert_called_once_with(page=0, size=20)

    @pytest.mark.asyncio
    async def test_list_forwards_query_search_filter(self, cc_manager, mock_client):
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalPages": 0, "totalElements": 0}
        mock_client.get_cost_controls.return_value = {}

        await cc_manager.list_cost_controls({"filters": {"query": "budget"}})

        mock_client.get_cost_controls.assert_called_once_with(page=0, size=20, query="budget")

    @pytest.mark.asyncio
    async def test_list_strips_reserved_filter_keys(self, cc_manager, mock_client):
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalPages": 0, "totalElements": 0}
        mock_client.get_cost_controls.return_value = {}

        await cc_manager.list_cost_controls({"filters": {"page": 3, "size": 5, "query": "x"}})

        mock_client.get_cost_controls.assert_called_once_with(page=0, size=20, query="x")


class TestCostControlsManagerGet:
    """Test CostControlsManager.get_cost_control behavior."""

    @pytest.mark.asyncio
    async def test_get_returns_data(self, cc_manager, mock_client):
        mock_client.get_cost_control_by_id.return_value = {"id": "cc_1", "name": "budget-a"}
        result = await cc_manager.get_cost_control({"control_id": "cc_1"})
        assert result["id"] == "cc_1"

    @pytest.mark.asyncio
    async def test_get_missing_id_raises(self, cc_manager):
        with pytest.raises(ToolError):
            await cc_manager.get_cost_control({})

    @pytest.mark.asyncio


    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [400, 403, 404])
    async def test_get_not_found_is_structured(self, cc_manager, mock_client, status):
        """Upstream 400/403/404 for missing IDs folds into RESOURCE_NOT_FOUND.

        Unknown ids can 400 and deleted/foreign ids 403; GET-by-id has no input
        other than the id, so all three mean "no accessible control for this id".
        """
        mock_client.get_cost_control_by_id.side_effect = ReveniumAPIError(
            "boom", status_code=status
        )
        with pytest.raises(ToolError) as exc_info:
            await cc_manager.get_cost_control({"control_id": "cc_missing"})
        assert exc_info.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_get_500_propagates_as_api_error(self, cc_manager, mock_client):
        """A 500 is a server failure, not evidence the control is missing."""
        mock_client.get_cost_control_by_id.side_effect = ReveniumAPIError(
            "server down", status_code=500
        )
        with pytest.raises(ReveniumAPIError):
            await cc_manager.get_cost_control({"control_id": "cc_1"})


class TestCostControlsManagerCreate:
    """Test CostControlsManager.create_cost_control behavior."""

    @pytest.mark.asyncio
    async def test_create_missing_data_raises(self, cc_manager):
        with pytest.raises(ToolError):
            await cc_manager.create_cost_control({})

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "missing", ["name", "metricType", "hardLimit", "windowType", "action"]
    )
    async def test_create_missing_required_write_field_raises(self, cc_manager, missing):
        """Each boundary-required write field is validated for presence."""
        data = _valid_control_data()
        del data[missing]
        with pytest.raises(ToolError):
            await cc_manager.create_cost_control({"control_data": data})

    @pytest.mark.asyncio
    async def test_create_injects_team_id(self, cc_manager, mock_client):
        mock_client.create_cost_control.return_value = {"id": "cc_new"}
        await cc_manager.create_cost_control({"control_data": _valid_control_data()})
        sent = mock_client.create_cost_control.call_args[0][0]
        assert sent["teamId"] == "test_team_id_456"
        assert sent["name"] == "Monthly Guardrail"

    @pytest.mark.asyncio
    async def test_create_preserves_explicit_team_id(self, cc_manager, mock_client):
        mock_client.create_cost_control.return_value = {"id": "cc_new"}
        data = {**_valid_control_data(), "teamId": "other_team"}
        await cc_manager.create_cost_control({"control_data": data})
        sent = mock_client.create_cost_control.call_args[0][0]
        assert sent["teamId"] == "other_team"

    @pytest.mark.asyncio
    async def test_create_passes_action_through_without_client_side_enum(self, cc_manager, mock_client):
        """action is not validated against a client-side enum; the server decides."""
        mock_client.create_cost_control.return_value = {"id": "cc_new"}
        data = {**_valid_control_data(), "action": "THROTTLE"}
        await cc_manager.create_cost_control({"control_data": data})
        sent = mock_client.create_cost_control.call_args[0][0]
        assert sent["action"] == "THROTTLE"


class TestCostControlsManagerUpdate:
    """Test CostControlsManager.update_cost_control behavior."""

    @pytest.mark.asyncio
    async def test_update_missing_id_raises(self, cc_manager):
        with pytest.raises(ToolError):
            await cc_manager.update_cost_control({"control_data": {"hardLimit": 5}})

    @pytest.mark.asyncio
    async def test_update_missing_data_raises(self, cc_manager):
        with pytest.raises(ToolError):
            await cc_manager.update_cost_control({"control_id": "cc_1"})

    @pytest.mark.asyncio
    async def test_update_passes_partial_body_through(self, cc_manager, mock_client):
        """PATCH is partial server-side: the caller's fields are sent as-is,
        with no fetch-and-merge."""
        mock_client.update_cost_control.return_value = {"id": "cc_1"}

        await cc_manager.update_cost_control(
            {"control_id": "cc_1", "control_data": {"hardLimit": 2000}}
        )

        mock_client.get_cost_control_by_id.assert_not_called()
        sent = mock_client.update_cost_control.call_args[0][1]
        assert sent == {"hardLimit": 2000}


    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [403, 404])
    async def test_update_not_found_is_structured(self, cc_manager, mock_client, status):
        """PATCH on a missing/foreign id folds into RESOURCE_NOT_FOUND.

        400 is deliberately NOT folded here: on PATCH it can describe a body
        validation problem, which must reach the caller as the API error."""
        mock_client.update_cost_control.side_effect = ReveniumAPIError(
            "boom", status_code=status
        )
        with pytest.raises(ToolError) as exc_info:
            await cc_manager.update_cost_control(
                {"control_id": "cc_missing", "control_data": {"hardLimit": 1}}
            )
        assert exc_info.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_update_400_propagates_as_api_error(self, cc_manager, mock_client):
        mock_client.update_cost_control.side_effect = ReveniumAPIError(
            "bad body", status_code=400
        )
        with pytest.raises(ReveniumAPIError):
            await cc_manager.update_cost_control(
                {"control_id": "cc_1", "control_data": {"hardLimit": -1}}
            )

class TestCostControlsManagerDelete:
    """Test CostControlsManager.delete_cost_control behavior."""

    @pytest.mark.asyncio
    async def test_delete_missing_id_raises(self, cc_manager):
        with pytest.raises(ToolError):
            await cc_manager.delete_cost_control({})

    @pytest.mark.asyncio
    async def test_delete_calls_client(self, cc_manager, mock_client):
        mock_client.delete_cost_control.return_value = {}
        await cc_manager.delete_cost_control({"control_id": "cc_9"})
        mock_client.delete_cost_control.assert_called_once_with("cc_9")


    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [400, 403, 404])
    async def test_delete_not_found_is_structured(self, cc_manager, mock_client, status):
        """DELETE has no input other than the id, so 400/403/404 all fold."""
        mock_client.delete_cost_control.side_effect = ReveniumAPIError(
            "boom", status_code=status
        )
        with pytest.raises(ToolError) as exc_info:
            await cc_manager.delete_cost_control({"control_id": "cc_missing"})
        assert exc_info.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND

class TestCostControlsManagerEnforcementEvents:
    """Test CostControlsManager.list_enforcement_events behavior."""

    @pytest.mark.asyncio
    async def test_events_default_pagination(self, cc_manager, mock_client):
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalPages": 0, "totalElements": 0}
        mock_client.get_enforcement_events.return_value = {}

        await cc_manager.list_enforcement_events({})

        mock_client.get_enforcement_events.assert_called_once_with(page=0, size=20)

    @pytest.mark.asyncio
    async def test_events_maps_since_and_rule_id(self, cc_manager, mock_client):
        """since/rule_id args map to the API's since/ruleId query params."""
        mock_client._extract_embedded_data.return_value = [{"id": "ev_1"}]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 1}
        mock_client.get_enforcement_events.return_value = {"_embedded": {}}

        result = await cc_manager.list_enforcement_events(
            {"since": "2026-01-01", "rule_id": "cc_1"}
        )

        mock_client.get_enforcement_events.assert_called_once_with(
            page=0, size=20, since="2026-01-01", ruleId="cc_1"
        )
        assert result["total_found"] == 1


class TestCostControlsManagerEnforcementRules:
    """Test CostControlsManager.get_enforcement_rules behavior."""

    @pytest.mark.asyncio
    async def test_rules_returns_compiled_payload(self, cc_manager, mock_client):
        mock_client.get_enforcement_rules.return_value = {
            "rules": [{"id": "cc_1"}],
            "compiledAt": "2026-01-01T00:00:00Z",
        }
        result = await cc_manager.get_enforcement_rules({})
        mock_client.get_enforcement_rules.assert_called_once_with()
        assert result["rules"][0]["id"] == "cc_1"
        assert result["compiledAt"] == "2026-01-01T00:00:00Z"


# ===========================================================================
# CostControlsManagement (top-level tool) Tests
# ===========================================================================


class TestCostControlsManagementMetadata:
    """Tool-level attributes and introspection."""

    def test_tool_name(self, cc_mgmt):
        assert cc_mgmt.tool_name == "manage_cost_controls"

    @pytest.mark.asyncio
    async def test_supported_actions_include_crud_and_enforcement(self, cc_mgmt):
        actions = await cc_mgmt._get_supported_actions()
        for expected in (
            "list",
            "get",
            "create",
            "update",
            "delete",
            "list_enforcement_events",
            "get_enforcement_rules",
            "get_capabilities",
            "get_examples",
            "get_tool_metadata",
        ):
            assert expected in actions

    @pytest.mark.asyncio
    async def test_input_schema_documents_shadow_mode(self, cc_mgmt):
        schema = await cc_mgmt._get_input_schema()
        control_data = schema["properties"]["control_data"]
        assert "shadowMode" in control_data["properties"]
        assert "enabled" in control_data["properties"]

    @pytest.mark.asyncio
    async def test_capabilities_cover_every_action(self, cc_mgmt):
        """Structured discovery must document every non-introspection action
        (a review finding on manage_agents)."""
        caps = await cc_mgmt._get_tool_capabilities()
        documented = set()
        for cap in caps:
            documented.update(cap.parameters.keys())
        for action in (
            "list",
            "get",
            "create",
            "update",
            "delete",
            "list_enforcement_events",
            "get_enforcement_rules",
        ):
            assert action in documented


class TestCostControlsManagementActions:
    """handle_action dispatch."""

    @pytest.mark.asyncio
    async def test_get_capabilities_returns_text(self, cc_mgmt):
        result = await cc_mgmt.handle_action("get_capabilities", {})
        assert isinstance(result[0], TextContent)
        assert "list_enforcement_events" in result[0].text

    @pytest.mark.asyncio
    async def test_get_examples_returns_examples(self, cc_mgmt):
        result = await cc_mgmt.handle_action("get_examples", {})
        assert "metricType" in result[0].text

    @pytest.mark.asyncio
    async def test_unknown_action_lists_supported(self, cc_mgmt):
        result = await cc_mgmt.handle_action("bogus_action", {})
        assert "Unknown action" in result[0].text
        assert "get_enforcement_rules" in result[0].text

    @pytest.mark.asyncio
    async def test_list_action_formats_result(self, cc_mgmt, mock_client):
        mock_client._extract_embedded_data.return_value = [{"id": "cc_1"}]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 1}
        mock_client.get_cost_controls.return_value = {}
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action("list", {"page": 0, "size": 20})

        assert "Found 1 cost controls" in result[0].text

    @pytest.mark.asyncio
    async def test_get_enforcement_rules_action_formats_result(self, cc_mgmt, mock_client):
        mock_client.get_enforcement_rules.return_value = {"rules": [], "compiledAt": None}
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action("get_enforcement_rules", {})

        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_tool_error_propagates(self, cc_mgmt, mock_client):
        """A ToolError from the manager must propagate out of handle_action so
        FastMCP marks the envelope isError:true, not be rendered as content text."""
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)
        with pytest.raises(ToolError):
            await cc_mgmt.handle_action("get", {})

    @pytest.mark.asyncio
    async def test_auth_failure_reraises_api_error(self, cc_mgmt, mock_client):
        """An auth failure from the client must propagate out of handle_action so
        FastMCP marks the envelope isError:true, not swallow it into content text."""
        mock_client.get_cost_controls.side_effect = ReveniumAPIError(
            "Unauthorized", status_code=401
        )
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)
        with pytest.raises(ReveniumAPIError) as exc:
            await cc_mgmt.handle_action("list", {"page": 0, "size": 20})
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_auth_failure_reraises_tool_error(self, cc_mgmt, mock_client):
        """A ToolError raised while handling an action must propagate, not be
        rendered as ``Tool error: ...`` content text without isError:true."""
        boom = ToolError(message="unauthorized", error_code=ErrorCodes.API_AUTHORIZATION)
        mock_client.get_cost_controls.side_effect = boom
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)
        with pytest.raises(ToolError) as exc:
            await cc_mgmt.handle_action("list", {"page": 0, "size": 20})
        assert exc.value is boom
