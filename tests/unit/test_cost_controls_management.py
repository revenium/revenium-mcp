"""Unit tests for Cost Controls Management tools.

Tests the CostControlsManager and CostControlsManagement classes from the
decomposed tools module. Covers CRUD (list, get, create, update, delete),
the enforcement-visibility actions (list_enforcement_events,
get_enforcement_rules), and the introspection actions.
"""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.tools_decomposed.cost_controls_management import (
    CostControlsManager,
    CostControlsManagement,
    _coerce_parent_org_unit_id,
    _summarize_org_unit_blocks,
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
    client.preview_org_unit_group = AsyncMock()
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


def _grouped_compiled_rule():
    """A compiled rule as the API returns it for a subscriber-grouped control."""
    return {
        "ruleId": 42,
        "teamId": 7,
        "name": "Per-subscriber monthly cap",
        "metricType": "TOTAL_COST",
        "threshold": 100.0,
        "currentValue": 130.0,
        "percentUsed": 1.3,
        "breached": True,
        "groupBy": "SUBSCRIBER",
        "groupBreakdown": [
            {
                "groupValue": "sub_1",
                "displayName": "sub_1",
                "currentValue": 120.5,
                "usagePercent": 1.205,
                "breached": True,
            },
            {
                "groupValue": "unattributed",
                "displayName": "Unattributed",
                "currentValue": 9.5,
                "usagePercent": 0.095,
                "breached": False,
            },
        ],
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

    @pytest.mark.asyncio
    async def test_rules_pass_group_breakdown_through_untouched(self, cc_manager, mock_client):
        """Per-group balances on a subscriber-grouped rule survive verbatim.

        Guards against a future formatter or field allowlist silently dropping
        the array or reshaping its entries."""
        expected = _grouped_compiled_rule()["groupBreakdown"]
        mock_client.get_enforcement_rules.return_value = {
            "rules": [_grouped_compiled_rule()],
            "compiledAt": "2026-08-11T00:00:00Z",
        }

        result = await cc_manager.get_enforcement_rules({})

        assert result["rules"][0]["groupBreakdown"] == expected

    @pytest.mark.asyncio
    async def test_rules_keep_null_group_breakdown_for_pooled_rules(self, cc_manager, mock_client):
        """A null groupBreakdown means the rule is pooled, which is semantically
        different from a grouped rule with zero groups, so it is never
        normalised into an empty list."""
        mock_client.get_enforcement_rules.return_value = {
            "rules": [{"ruleId": 7, "groupBy": None, "groupBreakdown": None}],
            "compiledAt": "2026-08-11T00:00:00Z",
        }

        result = await cc_manager.get_enforcement_rules({})

        assert result["rules"][0]["groupBreakdown"] is None


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

    @pytest.mark.asyncio
    async def test_capabilities_document_group_breakdown(self, cc_mgmt):
        """The per-group balances are additive and read-only, so the capability
        description is the only thing that tells an agent they exist."""
        caps = await cc_mgmt._get_tool_capabilities()
        enforcement = next(c for c in caps if "get_enforcement_rules" in c.parameters)

        assert "groupBreakdown" in enforcement.description
        for entry_field in (
            "groupValue",
            "displayName",
            "currentValue",
            "usagePercent",
            "breached",
        ):
            assert entry_field in enforcement.description
        assert "pooled" in enforcement.description

    @pytest.mark.asyncio
    async def test_group_breakdown_stays_out_of_the_input_parameters(self, cc_mgmt):
        """parameters is an input map everywhere else in this tool, so a response
        field listed there would read to an agent as an argument to send."""
        caps = await cc_mgmt._get_tool_capabilities()
        enforcement = next(c for c in caps if "get_enforcement_rules" in c.parameters)

        assert enforcement.parameters["get_enforcement_rules"] == {}
        assert "groupBreakdown" not in json.dumps(enforcement.parameters)

    @pytest.mark.asyncio
    async def test_group_breakdown_entry_fields_spelled_once(self, cc_mgmt):
        """One authoritative spelling of the entry shape: duplicates in the
        examples or limitations are what drift from the API contract."""
        caps = await cc_mgmt._get_tool_capabilities()
        enforcement = next(c for c in caps if "get_enforcement_rules" in c.parameters)
        rendered = json.dumps(
            {
                "description": enforcement.description,
                "parameters": enforcement.parameters,
                "examples": enforcement.examples,
                "limitations": enforcement.limitations,
            }
        )

        assert rendered.count("usagePercent") == 1
        assert rendered.count("groupValue") == 1


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
    async def test_get_enforcement_rules_action_preserves_group_breakdown(
        self, cc_mgmt, mock_client
    ):
        """The rendered action result carries the per-group balances unmodified."""
        expected = _grouped_compiled_rule()["groupBreakdown"]
        mock_client.get_enforcement_rules.return_value = {
            "rules": [_grouped_compiled_rule()],
            "compiledAt": "2026-08-11T00:00:00Z",
        }
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action("get_enforcement_rules", {})

        payload = json.loads(result[0].text.split("\n\n", 1)[1])
        assert payload["rules"][0]["groupBreakdown"] == expected

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


# ===========================================================================
# BACK-2764: ORG_UNIT (department) scoping
# ===========================================================================


class TestCoerceParentOrgUnitId:
    """The raw numeric org-unit id arrives as an int or as a digit string."""

    @pytest.mark.parametrize(
        "raw,expected",
        [(173, 173), ("173", 173), ("  173 ", 173), (173.0, 173), (0, 0)],
    )
    def test_numeric_forms_are_accepted(self, raw, expected):
        assert _coerce_parent_org_unit_id(raw) == expected

    @pytest.mark.parametrize("raw", [True, False, "abc", "17.5", "", "-1", -1, None, [], {}])
    def test_non_ids_are_rejected_before_the_call(self, raw):
        """Rejecting here means the caller reads "not a numeric org-unit id"
        instead of an upstream 400 about a field they cannot see."""
        with pytest.raises(ToolError) as exc:
            _coerce_parent_org_unit_id(raw)
        assert exc.value.error_code == ErrorCodes.INVALID_PARAMETER

    def test_rejection_points_at_the_org_unit_listing(self):
        with pytest.raises(ToolError) as exc:
            _coerce_parent_org_unit_id("engineering")
        assert "list_org_units" in json.dumps(exc.value.suggestions)


class TestSummarizeOrgUnitBlocks:
    """orgUnitBudgetBlocks is subscriber email -> the id of the blocking rule."""

    def test_absent_key_produces_no_line(self):
        """An older tenant never sends the map; reporting "0 blocked" from its
        absence would be an invented fact."""
        assert _summarize_org_unit_blocks({"rules": [], "compiledAt": None}) is None

    def test_explicit_null_produces_no_line(self):
        assert _summarize_org_unit_blocks({"orgUnitBudgetBlocks": None}) is None

    def test_non_dict_payload_produces_no_line(self):
        assert _summarize_org_unit_blocks("not a payload") is None

    def test_empty_map_says_nobody_is_blocked(self):
        summary = _summarize_org_unit_blocks({"orgUnitBudgetBlocks": {}, "rules": []})
        assert summary == "No subscribers are currently blocked by a department budget."

    def test_rule_id_is_resolved_to_the_rule_name(self):
        summary = _summarize_org_unit_blocks(
            {
                "orgUnitBudgetBlocks": {"ada@example.com": 42, "grace@example.com": 42},
                "rules": [{"ruleId": 42, "name": "Engineering monthly cap"}],
            }
        )
        assert "2 subscribers are currently blocked" in summary
        assert "ada@example.com (Engineering monthly cap)" in summary
        assert "grace@example.com (Engineering monthly cap)" in summary

    def test_single_block_reads_as_singular(self):
        summary = _summarize_org_unit_blocks(
            {
                "orgUnitBudgetBlocks": {"ada@example.com": 42},
                "rules": [{"ruleId": 42, "name": "Engineering monthly cap"}],
            }
        )
        assert "1 subscriber is currently blocked" in summary

    def test_string_rule_ids_still_resolve_to_names(self):
        """The map's values and rules[].ruleId are not guaranteed to share a
        JSON type, so the lookup compares them as strings."""
        summary = _summarize_org_unit_blocks(
            {
                "orgUnitBudgetBlocks": {"ada@example.com": "42"},
                "rules": [{"ruleId": 42, "name": "Engineering monthly cap"}],
            }
        )
        assert "ada@example.com (Engineering monthly cap)" in summary

    def test_unresolvable_rule_id_falls_back_to_the_id(self):
        """A block whose rule is not in the compiled set still names someone
        blocked — dropping the entry would hide a real block."""
        summary = _summarize_org_unit_blocks(
            {"orgUnitBudgetBlocks": {"ada@example.com": 99}, "rules": []}
        )
        assert "ada@example.com (rule 99)" in summary

    def test_long_block_lists_are_bounded_and_point_at_the_payload(self):
        blocks = {f"user{i}@example.com": 42 for i in range(15)}
        summary = _summarize_org_unit_blocks(
            {"orgUnitBudgetBlocks": blocks, "rules": [{"ruleId": 42, "name": "Cap"}]}
        )
        assert "15 subscribers are currently blocked" in summary
        assert "and 5 more" in summary
        assert "user14@example.com" not in summary

    def test_unexpected_shape_is_reported_not_silently_dropped(self):
        summary = _summarize_org_unit_blocks({"orgUnitBudgetBlocks": ["ada@example.com"]})
        assert "not the expected" in summary

    def test_summary_warns_that_it_names_people(self):
        summary = _summarize_org_unit_blocks(
            {"orgUnitBudgetBlocks": {"ada@example.com": 42}, "rules": []}
        )
        assert "subscriber email addresses" in summary


class TestCostControlsManagerPreviewOrgUnitGroup:
    """preview_org_unit_group counts the per-department fan-out, read-only."""

    @pytest.mark.asyncio
    async def test_missing_parent_id_raises(self, cc_manager):
        with pytest.raises(ToolError) as exc:
            await cc_manager.preview_org_unit_group({})
        assert exc.value.error_code == ErrorCodes.MISSING_PARAMETER

    @pytest.mark.asyncio
    async def test_blank_parent_id_raises_missing_not_invalid(self, cc_manager):
        with pytest.raises(ToolError) as exc:
            await cc_manager.preview_org_unit_group({"parent_org_unit_id": "   "})
        assert exc.value.error_code == ErrorCodes.MISSING_PARAMETER

    @pytest.mark.asyncio
    async def test_digit_string_is_sent_as_a_number(self, cc_manager, mock_client):
        mock_client.preview_org_unit_group.return_value = {"targetCount": 3, "targets": []}

        await cc_manager.preview_org_unit_group({"parent_org_unit_id": "173"})

        mock_client.preview_org_unit_group.assert_awaited_once_with(173)

    @pytest.mark.asyncio
    async def test_returns_target_count_and_targets(self, cc_manager, mock_client):
        targets = [{"id": "ou_1", "name": "Engineering"}]
        mock_client.preview_org_unit_group.return_value = {"targetCount": 1, "targets": targets}

        result = await cc_manager.preview_org_unit_group({"parent_org_unit_id": 173})

        assert result["action"] == "preview_org_unit_group"
        assert result["parent_org_unit_id"] == "173"
        assert result["target_count"] == 1
        assert result["targets"] == targets

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [403, 422])
    async def test_feature_flag_refusal_is_explained(self, cc_manager, mock_client, status):
        """403 (feature gate) and 422 (org-unit attribution check beneath it)
        both mean "not enabled for this tenant", not "your key is wrong"."""
        mock_client.preview_org_unit_group.side_effect = ReveniumAPIError(
            "Feature not available", status_code=status
        )

        with pytest.raises(ToolError) as exc:
            await cc_manager.preview_org_unit_group({"parent_org_unit_id": 173})

        assert "not enabled for this team" in exc.value.message
        assert "feature flag" in json.dumps(exc.value.suggestions)

    @pytest.mark.asyncio
    async def test_other_api_errors_propagate(self, cc_manager, mock_client):
        """A 500 is a server failure, not evidence the feature is off."""
        mock_client.preview_org_unit_group.side_effect = ReveniumAPIError(
            "boom", status_code=500
        )
        with pytest.raises(ReveniumAPIError):
            await cc_manager.preview_org_unit_group({"parent_org_unit_id": 173})

    @pytest.mark.asyncio
    async def test_unexpected_response_shape_is_reported(self, cc_manager, mock_client):
        """Reporting the shape beats rendering a fabricated count of zero."""
        mock_client.preview_org_unit_group.return_value = [1, 2, 3]

        result = await cc_manager.preview_org_unit_group({"parent_org_unit_id": 173})

        assert "unexpected shape" in result["warning"]
        assert "target_count" not in result


class TestOrgUnitDocumentationSurface:
    """An agent must be able to discover ORG_UNIT without reading the wire format."""

    @pytest.mark.asyncio
    async def test_preview_action_is_supported(self, cc_mgmt):
        assert "preview_org_unit_group" in await cc_mgmt._get_supported_actions()

    @pytest.mark.asyncio
    async def test_capabilities_document_the_preview_action(self, cc_mgmt):
        caps = await cc_mgmt._get_tool_capabilities()
        documented = set()
        for cap in caps:
            documented.update(cap.parameters.keys())
        assert "preview_org_unit_group" in documented

    @pytest.mark.asyncio
    async def test_group_by_names_org_unit(self, cc_mgmt):
        schema = await cc_mgmt._get_input_schema()
        group_by = schema["properties"]["control_data"]["properties"]["groupBy"]
        assert "ORG_UNIT" in group_by["description"]

    @pytest.mark.asyncio
    async def test_include_descendants_is_documented_on_the_filter_item(self, cc_mgmt):
        """The flag lives on each filter entry and only means something for
        ORG_UNIT, so documenting it as a top-level field would mislead."""
        schema = await cc_mgmt._get_input_schema()
        control_data = schema["properties"]["control_data"]["properties"]
        assert "includeDescendants" not in control_data
        item = control_data["filters"]["items"]["properties"]["includeDescendants"]
        assert "ORG_UNIT" in item["description"]

    @pytest.mark.asyncio
    async def test_parent_org_unit_id_is_declared(self, cc_mgmt):
        schema = await cc_mgmt._get_input_schema()
        assert "parent_org_unit_id" in schema["properties"]

    @pytest.mark.asyncio
    async def test_org_unit_is_documented_as_cost_control_only(self, cc_mgmt):
        """BACK-2760 closed with the alert/anomaly API throwing on ORG_UNIT, so
        the tool that teaches the dimension must also fence it off."""
        caps = await cc_mgmt._get_tool_capabilities()
        rendered = json.dumps([c.description for c in caps])
        assert "manage_alerts" in rendered
        assert "cost-control-only" in rendered

    @pytest.mark.asyncio
    async def test_examples_teach_the_org_unit_notes(self, cc_mgmt):
        result = await cc_mgmt.handle_action("get_examples", {})
        assert "preview_org_unit_group" in result[0].text
        assert "manage_alerts" in result[0].text


class TestEnforcementRulesBlockSummaryRendering:
    """The rendered get_enforcement_rules output must say who is blocked."""

    @pytest.mark.asyncio
    async def test_blocked_subscribers_are_named_with_their_rule(self, cc_mgmt, mock_client):
        mock_client.get_enforcement_rules.return_value = {
            "rules": [{"ruleId": 42, "name": "Engineering monthly cap"}],
            "compiledAt": "2026-08-26T00:00:00Z",
            "orgUnitBudgetBlocks": {"ada@example.com": 42},
        }
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action("get_enforcement_rules", {})

        assert "ada@example.com (Engineering monthly cap)" in result[0].text

    @pytest.mark.asyncio
    async def test_payload_is_still_recoverable_after_the_summary_line(
        self, cc_mgmt, mock_client
    ):
        """The summary is one extra line, never a blank one, so the first blank
        line still separates prose from the JSON payload."""
        payload = {
            "rules": [{"ruleId": 42, "name": "Engineering monthly cap"}],
            "compiledAt": "2026-08-26T00:00:00Z",
            "orgUnitBudgetBlocks": {"ada@example.com": 42},
        }
        mock_client.get_enforcement_rules.return_value = payload
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action("get_enforcement_rules", {})

        assert json.loads(result[0].text.split("\n\n", 1)[1]) == payload

    @pytest.mark.asyncio
    async def test_tenant_without_the_key_gets_no_block_line(self, cc_mgmt, mock_client):
        mock_client.get_enforcement_rules.return_value = {"rules": [], "compiledAt": None}
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action("get_enforcement_rules", {})

        assert "blocked" not in result[0].text

    @pytest.mark.asyncio
    async def test_preview_action_reports_the_fan_out(self, cc_mgmt, mock_client):
        mock_client.preview_org_unit_group.return_value = {
            "targetCount": 4,
            "targets": [],
        }
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action(
            "preview_org_unit_group", {"parent_org_unit_id": 173}
        )

        text = result[0].text
        assert "4 direct child org unit(s)" in text
        assert "organization-wide" in text


class TestPreviewResponseShapeGuards:
    """PR #331 review: malformed responses must warn, never render None counts."""

    @pytest.mark.asyncio
    async def test_unicode_digit_string_gets_the_structured_error(self, cc_manager):
        with pytest.raises(ToolError) as excinfo:
            await cc_manager.preview_org_unit_group({"parent_org_unit_id": "\u00b2"})
        assert "numeric org-unit id" in str(excinfo.value.message)

    @pytest.mark.asyncio
    async def test_dict_without_expected_fields_takes_the_warning_path(self, cc_manager):
        cc_manager.client.preview_org_unit_group = AsyncMock(return_value={"ok": True})
        result = await cc_manager.preview_org_unit_group({"parent_org_unit_id": 42})
        assert "warning" in result and "target_count" not in result

    @pytest.mark.asyncio
    async def test_wrong_typed_fields_take_the_warning_path(self, cc_manager):
        cc_manager.client.preview_org_unit_group = AsyncMock(
            return_value={"targetCount": "3", "targets": "nope"}
        )
        result = await cc_manager.preview_org_unit_group({"parent_org_unit_id": 42})
        assert "warning" in result

    @pytest.mark.asyncio
    async def test_handler_renders_warning_not_none_count(self, cc_mgmt):
        from unittest.mock import patch

        with patch.object(
            CostControlsManager, "preview_org_unit_group",
            new=AsyncMock(return_value={
                "action": "preview_org_unit_group",
                "parent_org_unit_id": "42",
                "warning": "The preview endpoint answered with an unexpected shape",
                "raw_response": {},
            }),
        ):
            out = await cc_mgmt.handle_action("preview_org_unit_group", {"parent_org_unit_id": 42})
        text = out[0].text
        assert text.startswith("WARNING:")
        assert "None per-department" not in text and "would create None" not in text

    @pytest.mark.asyncio
    async def test_happy_render_states_direct_children_not_created_budgets(self, cc_mgmt):
        from unittest.mock import patch

        with patch.object(
            CostControlsManager, "preview_org_unit_group",
            new=AsyncMock(return_value={
                "action": "preview_org_unit_group",
                "parent_org_unit_id": "42",
                "target_count": 6,
                "targets": [],
            }),
        ):
            out = await cc_mgmt.handle_action("preview_org_unit_group", {"parent_org_unit_id": 42})
        text = out[0].text
        assert "direct child org unit" in text
        assert "organization-wide" in text
        assert "would create" not in text


class TestOrgUnitDocsMatchUpstreamContract:
    """PR #331 cross-repo review: examples agents copy must not 400, and the
    preview semantics must not invite under-sizing a BLOCK rule's fan-out."""

    @pytest.mark.asyncio
    async def test_no_surface_documents_the_rejected_equals_operator(self, cc_mgmt):
        caps = await cc_mgmt.handle_action("get_capabilities", {})
        examples = await cc_mgmt.handle_action("get_examples", {})
        combined = caps[0].text + examples[0].text
        assert "EQUALS" not in combined
        assert "'operator': 'IS'" in combined or '"operator": "IS"' in combined

    @pytest.mark.asyncio
    async def test_preview_docs_state_direct_children_not_rule_fanout(self, cc_mgmt):
        caps = await cc_mgmt.handle_action("get_capabilities", {})
        text = caps[0].text
        assert "DIRECT CHILDREN" in text
        assert "organization-wide" in text
