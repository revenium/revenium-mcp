"""Unit tests for Cost Controls Management tools.

Tests the CostControlsManager and CostControlsManagement classes from the
decomposed tools module. Covers CRUD (list, get, create, update, delete),
the enforcement-visibility actions (list_enforcement_events and its
summary/history/affected sub-reads, get_enforcement_rules and
get_enforcement_rule_roster), and the introspection actions.
"""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.tools_decomposed.cost_controls_management import (
    ENFORCEMENT_EVENT_ROW_FIELDS_NOTE,
    ENFORCEMENT_GROUP_PAIR_NOTE,
    ENFORCEMENT_ROSTER_NOTE,
    ENFORCEMENT_SUBREADS_UNPAGED_NOTE,
    DEPARTMENT_ENFORCEMENT_MAPS_NOTE,
    NOTIFICATION_EMAILS_PATCH_NOTE,
    CostControlsManager,
    CostControlsManagement,
    _build_enforcement_event_filters,
    _coerce_parent_department_id,
    _summarize_department_blocks,
    _summarize_department_warnings,
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
    client.get_enforcement_events_summary = AsyncMock()
    client.get_enforcement_events_history = AsyncMock()
    client.get_enforcement_events_affected = AsyncMock()
    client.get_enforcement_rules = AsyncMock()
    client.get_enforcement_rule_roster = AsyncMock()
    client.preview_department_group = AsyncMock()
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
    async def test_update_sends_an_empty_notification_email_list_intact(
        self, cc_manager, mock_client
    ):
        """An empty list is how a caller clears the recipients, so it must not
        be dropped as falsy or treated as "no change" on the way out."""
        mock_client.update_cost_control.return_value = {"id": "cc_1"}

        await cc_manager.update_cost_control(
            {"control_id": "cc_1", "control_data": {"notificationEmails": []}}
        )

        mock_client.update_cost_control.assert_awaited_once_with(
            "cc_1", {"notificationEmails": []}
        )


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

class TestNotificationEmailsDocumentation:
    """notificationEmails is discoverable on control_data with its PATCH rule."""

    @pytest.mark.asyncio
    async def test_control_data_declares_notification_emails(self, cc_mgmt):
        schema = await cc_mgmt._get_input_schema()
        prop = schema["properties"]["control_data"]["properties"]["notificationEmails"]
        assert "array" in prop["type"]
        assert prop["items"]["type"] == "string"
        assert prop["maxItems"] == 10

    def test_the_patch_rule_states_clear_replace_and_unchanged(self):
        for phrase in (
            "empty list clears the addresses",
            "non-empty list replaces them",
            "omitting the field or passing JSON null leaves them unchanged",
        ):
            assert phrase in NOTIFICATION_EMAILS_PATCH_NOTE, phrase

    @pytest.mark.asyncio
    async def test_the_schema_and_update_text_carry_the_patch_rule(self, cc_mgmt):
        schema = await cc_mgmt._get_input_schema()
        prop = schema["properties"]["control_data"]["properties"]["notificationEmails"]
        assert NOTIFICATION_EMAILS_PATCH_NOTE in prop["description"]

        caps = await cc_mgmt._get_tool_capabilities()
        crud = next(c for c in caps if "update" in c.parameters)
        assert NOTIFICATION_EMAILS_PATCH_NOTE in crud.parameters["update"]["control_data"]
        assert "notificationEmails" in crud.parameters["create"]["control_data"]

    @pytest.mark.asyncio
    async def test_no_top_level_notification_emails_argument(self, cc_mgmt):
        """control_data already carries the field; a second spelling would
        need merge rules the platform does not define."""
        schema = await cc_mgmt._get_input_schema()
        assert "notification_emails" not in schema["properties"]
        assert "notificationEmails" not in schema["properties"]


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

    @pytest.mark.asyncio
    async def test_events_with_a_legacy_action_pass_through_unchanged(self, cc_manager, mock_client):
        """A legacy action value the published enum no longer lists still renders.

        The platform's enforcement-event contract restricts ``action`` to the
        accepted values but says a rule saved under a since-retired action can
        still report it (hypercurrent BACK-2997; contradiction tracked in
        BACK-3107). The MCP must never validate events against that enum: it
        renders what the platform sent, so an old rule's events stay readable.
        """
        legacy_event = {"id": "ev_legacy", "action": "THROTTLE", "ruleName": "Old cap"}
        current_event = {"id": "ev_now", "action": "BLOCK", "ruleName": "New cap"}
        mock_client._extract_embedded_data.return_value = [legacy_event, current_event]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 2}
        mock_client.get_enforcement_events.return_value = {"_embedded": {}}

        result = await cc_manager.list_enforcement_events({})

        assert result["enforcement_events"] == [
            {"id": "ev_legacy", "action": "THROTTLE", "ruleName": "Old cap"},
            {"id": "ev_now", "action": "BLOCK", "ruleName": "New cap"},
        ]
        assert result["enforcement_events"][0]["action"] == "THROTTLE"
        assert result["total_found"] == 2


class TestCostControlsManagerEnforcementRules:
    """Test CostControlsManager.get_enforcement_rules behavior."""

    @pytest.mark.asyncio
    async def test_rules_returns_compiled_payload(self, cc_manager, mock_client):
        mock_client.get_enforcement_rules.return_value = {
            "rules": [{"id": "cc_1"}],
            "compiledAt": "2026-01-01T00:00:00Z",
        }
        result = await cc_manager.get_enforcement_rules({})
        mock_client.get_enforcement_rules.assert_called_once_with(rule_id=None)
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

        assert set(enforcement.parameters["get_enforcement_rules"]) == {"rule_id"}
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
        # The entry tuple, not the bare name: groupValue is also an event row
        # field and a list filter, so counting the name alone would now fail
        # for a reason that has nothing to do with groupBreakdown drifting.
        assert rendered.count("groupValue, displayName, currentValue, usagePercent, breached") == 1


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
        """BACK-2937: an unknown action raises so the envelope carries isError."""
        with pytest.raises(ToolError) as exc_info:
            await cc_mgmt.handle_action("bogus_action", {})
        assert "Unknown action" in exc_info.value.message
        assert "get_enforcement_rules" in exc_info.value.message

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
# BACK-2764: DEPARTMENT (department) scoping
# ===========================================================================


class TestCoerceParentDepartmentId:
    """The raw numeric department id arrives as an int or as a digit string."""

    @pytest.mark.parametrize(
        "raw,expected",
        [(173, 173), ("173", 173), ("  173 ", 173), (173.0, 173), (0, 0)],
    )
    def test_numeric_forms_are_accepted(self, raw, expected):
        assert _coerce_parent_department_id(raw) == expected

    @pytest.mark.parametrize("raw", [True, False, "abc", "17.5", "", "-1", -1, None, [], {}])
    def test_non_ids_are_rejected_before_the_call(self, raw):
        """Rejecting here means the caller reads "not a numeric department id"
        instead of an upstream 400 about a field they cannot see."""
        with pytest.raises(ToolError) as exc:
            _coerce_parent_department_id(raw)
        assert exc.value.error_code == ErrorCodes.INVALID_PARAMETER

    def test_rejection_points_at_the_department_listing(self):
        with pytest.raises(ToolError) as exc:
            _coerce_parent_department_id("engineering")
        assert "list_departments" in json.dumps(exc.value.suggestions)


class TestSummarizeDepartmentBlocks:
    """departmentBudgetBlocks is subscriber email -> the id of the blocking rule."""

    def test_absent_key_produces_no_line(self):
        """An older tenant never sends the map; reporting "0 blocked" from its
        absence would be an invented fact."""
        assert _summarize_department_blocks({"rules": [], "compiledAt": None}) is None

    def test_explicit_null_produces_no_line(self):
        assert _summarize_department_blocks({"departmentBudgetBlocks": None}) is None

    def test_non_dict_payload_produces_no_line(self):
        assert _summarize_department_blocks("not a payload") is None

    def test_empty_map_says_nobody_is_blocked(self):
        summary = _summarize_department_blocks({"departmentBudgetBlocks": {}, "rules": []})
        assert summary == "No subscribers are currently blocked by a department budget."

    def test_rule_id_is_resolved_to_the_rule_name(self):
        summary = _summarize_department_blocks(
            {
                "departmentBudgetBlocks": {"ada@example.com": 42, "grace@example.com": 42},
                "rules": [{"ruleId": 42, "name": "Engineering monthly cap"}],
            }
        )
        assert "2 subscribers are currently blocked" in summary
        assert "ada@example.com (Engineering monthly cap)" in summary
        assert "grace@example.com (Engineering monthly cap)" in summary

    def test_single_block_reads_as_singular(self):
        summary = _summarize_department_blocks(
            {
                "departmentBudgetBlocks": {"ada@example.com": 42},
                "rules": [{"ruleId": 42, "name": "Engineering monthly cap"}],
            }
        )
        assert "1 subscriber is currently blocked" in summary

    def test_string_rule_ids_still_resolve_to_names(self):
        """The map's values and rules[].ruleId are not guaranteed to share a
        JSON type, so the lookup compares them as strings."""
        summary = _summarize_department_blocks(
            {
                "departmentBudgetBlocks": {"ada@example.com": "42"},
                "rules": [{"ruleId": 42, "name": "Engineering monthly cap"}],
            }
        )
        assert "ada@example.com (Engineering monthly cap)" in summary

    def test_unresolvable_rule_id_falls_back_to_the_id(self):
        """A block whose rule is not in the compiled set still names someone
        blocked — dropping the entry would hide a real block."""
        summary = _summarize_department_blocks(
            {"departmentBudgetBlocks": {"ada@example.com": 99}, "rules": []}
        )
        assert "ada@example.com (rule 99)" in summary

    def test_long_block_lists_are_bounded_and_point_at_the_payload(self):
        blocks = {f"user{i}@example.com": 42 for i in range(15)}
        summary = _summarize_department_blocks(
            {"departmentBudgetBlocks": blocks, "rules": [{"ruleId": 42, "name": "Cap"}]}
        )
        assert "15 subscribers are currently blocked" in summary
        assert "and 5 more" in summary
        assert "user14@example.com" not in summary

    def test_unexpected_shape_is_reported_not_silently_dropped(self):
        summary = _summarize_department_blocks({"departmentBudgetBlocks": ["ada@example.com"]})
        assert "not the expected" in summary

    def test_summary_warns_that_it_names_people(self):
        summary = _summarize_department_blocks(
            {"departmentBudgetBlocks": {"ada@example.com": 42}, "rules": []}
        )
        assert "subscriber email addresses" in summary


class TestCostControlsManagerPreviewDepartmentGroup:
    """preview_department_group counts the per-department fan-out, read-only."""

    @pytest.mark.asyncio
    async def test_missing_parent_id_raises(self, cc_manager):
        with pytest.raises(ToolError) as exc:
            await cc_manager.preview_department_group({})
        assert exc.value.error_code == ErrorCodes.MISSING_PARAMETER

    @pytest.mark.asyncio
    async def test_blank_parent_id_raises_missing_not_invalid(self, cc_manager):
        with pytest.raises(ToolError) as exc:
            await cc_manager.preview_department_group({"parent_department_id": "   "})
        assert exc.value.error_code == ErrorCodes.MISSING_PARAMETER

    @pytest.mark.asyncio
    async def test_digit_string_is_sent_as_a_number(self, cc_manager, mock_client):
        mock_client.preview_department_group.return_value = {"targetCount": 3, "targets": []}

        await cc_manager.preview_department_group({"parent_department_id": "173"})

        mock_client.preview_department_group.assert_awaited_once_with(173)

    @pytest.mark.asyncio
    async def test_returns_target_count_and_targets(self, cc_manager, mock_client):
        targets = [{"id": "ou_1", "name": "Engineering"}]
        mock_client.preview_department_group.return_value = {"targetCount": 1, "targets": targets}

        result = await cc_manager.preview_department_group({"parent_department_id": 173})

        assert result["action"] == "preview_department_group"
        assert result["parent_department_id"] == "173"
        assert result["target_count"] == 1
        assert result["targets"] == targets

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [403, 422])
    async def test_feature_flag_refusal_is_explained(self, cc_manager, mock_client, status):
        """403 (feature gate) and 422 (department attribution check beneath it)
        both mean "not enabled for this tenant", not "your key is wrong"."""
        mock_client.preview_department_group.side_effect = ReveniumAPIError(
            "Feature not available", status_code=status
        )

        with pytest.raises(ToolError) as exc:
            await cc_manager.preview_department_group({"parent_department_id": 173})

        assert "not enabled for this team" in exc.value.message
        assert "feature flag" in json.dumps(exc.value.suggestions)

    @pytest.mark.asyncio
    async def test_other_api_errors_propagate(self, cc_manager, mock_client):
        """A 500 is a server failure, not evidence the feature is off."""
        mock_client.preview_department_group.side_effect = ReveniumAPIError(
            "boom", status_code=500
        )
        with pytest.raises(ReveniumAPIError):
            await cc_manager.preview_department_group({"parent_department_id": 173})

    @pytest.mark.asyncio
    async def test_unexpected_response_shape_is_reported(self, cc_manager, mock_client):
        """Reporting the shape beats rendering a fabricated count of zero."""
        mock_client.preview_department_group.return_value = [1, 2, 3]

        result = await cc_manager.preview_department_group({"parent_department_id": 173})

        assert "unexpected shape" in result["warning"]
        assert "target_count" not in result


class TestDepartmentDocumentationSurface:
    """An agent must be able to discover DEPARTMENT without reading the wire format."""

    @pytest.mark.asyncio
    async def test_preview_action_is_supported(self, cc_mgmt):
        assert "preview_department_group" in await cc_mgmt._get_supported_actions()

    @pytest.mark.asyncio
    async def test_capabilities_document_the_preview_action(self, cc_mgmt):
        caps = await cc_mgmt._get_tool_capabilities()
        documented = set()
        for cap in caps:
            documented.update(cap.parameters.keys())
        assert "preview_department_group" in documented

    @pytest.mark.asyncio
    async def test_group_by_names_department(self, cc_mgmt):
        schema = await cc_mgmt._get_input_schema()
        group_by = schema["properties"]["control_data"]["properties"]["groupBy"]
        assert "DEPARTMENT" in group_by["description"]

    @pytest.mark.asyncio
    async def test_include_descendants_is_documented_on_the_filter_item(self, cc_mgmt):
        """The flag lives on each filter entry and only means something for
        DEPARTMENT, so documenting it as a top-level field would mislead."""
        schema = await cc_mgmt._get_input_schema()
        control_data = schema["properties"]["control_data"]["properties"]
        assert "includeDescendants" not in control_data
        item = control_data["filters"]["items"]["properties"]["includeDescendants"]
        assert "DEPARTMENT" in item["description"]

    @pytest.mark.asyncio
    async def test_parent_department_id_is_declared(self, cc_mgmt):
        schema = await cc_mgmt._get_input_schema()
        assert "parent_department_id" in schema["properties"]

    @pytest.mark.asyncio
    async def test_department_is_documented_as_cost_control_only(self, cc_mgmt):
        """BACK-2760 closed with the alert/anomaly API throwing on DEPARTMENT, so
        the tool that teaches the dimension must also fence it off."""
        caps = await cc_mgmt._get_tool_capabilities()
        rendered = json.dumps([c.description for c in caps])
        assert "manage_alerts" in rendered
        assert "cost-control-only" in rendered

    @pytest.mark.asyncio
    async def test_examples_teach_the_department_notes(self, cc_mgmt):
        result = await cc_mgmt.handle_action("get_examples", {})
        assert "preview_department_group" in result[0].text
        assert "manage_alerts" in result[0].text


class TestEnforcementRulesBlockSummaryRendering:
    """The rendered get_enforcement_rules output must say who is blocked."""

    @pytest.mark.asyncio
    async def test_blocked_subscribers_are_named_with_their_rule(self, cc_mgmt, mock_client):
        mock_client.get_enforcement_rules.return_value = {
            "rules": [{"ruleId": 42, "name": "Engineering monthly cap"}],
            "compiledAt": "2026-08-26T00:00:00Z",
            "departmentBudgetBlocks": {"ada@example.com": 42},
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
            "departmentBudgetBlocks": {"ada@example.com": 42},
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
        mock_client.preview_department_group.return_value = {
            "targetCount": 4,
            "targets": [],
        }
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action(
            "preview_department_group", {"parent_department_id": 173}
        )

        text = result[0].text
        assert "4 direct child department(s)" in text
        assert "organization-wide" in text


class TestPreviewResponseShapeGuards:
    """PR #331 review: malformed responses must warn, never render None counts."""

    @pytest.mark.asyncio
    async def test_unicode_digit_string_gets_the_structured_error(self, cc_manager):
        with pytest.raises(ToolError) as excinfo:
            await cc_manager.preview_department_group({"parent_department_id": "\u00b2"})
        assert "numeric department id" in str(excinfo.value.message)

    @pytest.mark.asyncio
    async def test_dict_without_expected_fields_takes_the_warning_path(self, cc_manager):
        cc_manager.client.preview_department_group = AsyncMock(return_value={"ok": True})
        result = await cc_manager.preview_department_group({"parent_department_id": 42})
        assert "warning" in result and "target_count" not in result

    @pytest.mark.asyncio
    async def test_wrong_typed_fields_take_the_warning_path(self, cc_manager):
        cc_manager.client.preview_department_group = AsyncMock(
            return_value={"targetCount": "3", "targets": "nope"}
        )
        result = await cc_manager.preview_department_group({"parent_department_id": 42})
        assert "warning" in result

    @pytest.mark.asyncio
    async def test_handler_renders_warning_not_none_count(self, cc_mgmt):
        from unittest.mock import patch

        with patch.object(
            CostControlsManager, "preview_department_group",
            new=AsyncMock(return_value={
                "action": "preview_department_group",
                "parent_department_id": "42",
                "warning": "The preview endpoint answered with an unexpected shape",
                "raw_response": {},
            }),
        ):
            out = await cc_mgmt.handle_action("preview_department_group", {"parent_department_id": 42})
        text = out[0].text
        assert text.startswith("WARNING:")
        assert "None per-department" not in text and "would create None" not in text

    @pytest.mark.asyncio
    async def test_happy_render_states_direct_children_not_created_budgets(self, cc_mgmt):
        from unittest.mock import patch

        with patch.object(
            CostControlsManager, "preview_department_group",
            new=AsyncMock(return_value={
                "action": "preview_department_group",
                "parent_department_id": "42",
                "target_count": 6,
                "targets": [],
            }),
        ):
            out = await cc_mgmt.handle_action("preview_department_group", {"parent_department_id": 42})
        text = out[0].text
        assert "direct child department" in text
        assert "organization-wide" in text
        assert "would create" not in text


class TestDepartmentDocsMatchUpstreamContract:
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


class TestFilterValuesOnTheItemSchema:
    """BACK-3088: an IN row carries its list in `values`, and the schema has to
    say so or an operator writes one control per department instead."""

    @pytest.mark.asyncio
    async def test_values_is_declared_as_a_string_array(self, cc_mgmt):
        schema = await cc_mgmt._get_input_schema()
        item = schema["properties"]["control_data"]["properties"]["filters"]["items"]
        assert item["properties"]["values"]["type"] == "array"
        assert item["properties"]["values"]["items"] == {"type": "string"}

    @pytest.mark.asyncio
    async def test_value_and_values_are_both_optional(self, cc_mgmt):
        """The server decides which of the two a row needs, per operator; a
        client-side `required` here would refuse a legal IN row."""
        schema = await cc_mgmt._get_input_schema()
        item = schema["properties"]["control_data"]["properties"]["filters"]["items"]
        assert "required" not in item

    @pytest.mark.asyncio
    async def test_no_client_side_operator_enum_is_introduced(self, cc_mgmt):
        """A new upstream operator must not need an MCP release."""
        schema = await cc_mgmt._get_input_schema()
        item = schema["properties"]["control_data"]["properties"]["filters"]["items"]
        assert "enum" not in item["properties"]["operator"]

    @pytest.mark.asyncio
    async def test_in_semantics_are_documented_on_the_row(self, cc_mgmt):
        schema = await cc_mgmt._get_input_schema()
        item = schema["properties"]["control_data"]["properties"]["filters"]["items"]
        rendered = json.dumps(item)
        assert "IN" in rendered
        assert "values" in rendered
        # The AND/OR boundary is the part a caller gets wrong: several rows are
        # ANDed, so IN is the only way to say "any of these" in one row.
        assert "OR within one row only" in rendered

    @pytest.mark.asyncio
    async def test_department_is_fenced_off_from_in(self, cc_mgmt):
        """Upstream refuses IN for DEPARTMENT (CostControlService.toEntity), so
        the surface that teaches the dimension must not invite it."""
        schema = await cc_mgmt._get_input_schema()
        item = schema["properties"]["control_data"]["properties"]["filters"]["items"]
        operator_doc = item["properties"]["operator"]["description"]
        assert "DEPARTMENT" in operator_doc
        assert "only IS" in operator_doc

    @pytest.mark.asyncio
    async def test_examples_teach_an_in_row(self, cc_mgmt):
        result = await cc_mgmt.handle_action("get_examples", {})
        assert '"operator": "IN"' in result[0].text
        assert '"values"' in result[0].text

    @pytest.mark.asyncio
    async def test_capabilities_state_the_value_values_exclusivity(self, cc_mgmt):
        caps = await cc_mgmt._get_tool_capabilities()
        rendered = json.dumps([c.limitations for c in caps])
        assert "either value or values, never both" in rendered

    @pytest.mark.asyncio
    async def test_department_capability_carries_the_is_only_rule(self, cc_mgmt):
        caps = await cc_mgmt.handle_action("get_capabilities", {})
        assert "only the IS operator" in caps[0].text


class TestSummarizeDepartmentWarnings:
    """departmentBudgetWarnings is subscriber email -> the rule whose warn tier
    they crossed, disjoint from departmentBudgetBlocks."""

    def test_absent_key_produces_no_line(self):
        assert _summarize_department_warnings({"rules": [], "compiledAt": None}) is None

    def test_explicit_null_produces_no_line(self):
        assert _summarize_department_warnings({"departmentBudgetWarnings": None}) is None

    def test_non_dict_payload_produces_no_line(self):
        assert _summarize_department_warnings("not a payload") is None

    def test_empty_map_says_nobody_crossed_a_warn_threshold(self):
        summary = _summarize_department_warnings({"departmentBudgetWarnings": {}, "rules": []})
        assert summary == "No subscribers have crossed a department budget warn threshold."

    def test_rule_ids_are_resolved_to_names_and_counted(self):
        summary = _summarize_department_warnings(
            {
                "departmentBudgetWarnings": {
                    "ada@example.com": 42,
                    "grace@example.com": 42,
                    "alan@example.com": 43,
                },
                "rules": [
                    {"ruleId": 42, "name": "Engineering monthly cap"},
                    {"ruleId": 43, "name": "Design monthly cap"},
                ],
            }
        )
        assert "3 subscribers are approaching a department budget" in summary
        assert "- Engineering monthly cap: 2 subscribers warned" in summary
        assert "- Design monthly cap: 1 subscriber warned" in summary

    def test_people_are_counted_not_named(self):
        """The block summary names people because a block is an incident about
        one person; the warn summary is per rule, so it must not widen the PII
        footprint of the same action."""
        summary = _summarize_department_warnings(
            {
                "departmentBudgetWarnings": {"ada@example.com": 42},
                "rules": [{"ruleId": 42, "name": "Engineering monthly cap"}],
            }
        )
        assert "ada@example.com" not in summary
        assert "1 subscriber is approaching" in summary
        assert "departmentBudgetWarnings in the payload below" in summary

    def test_balances_are_shown_when_the_map_carries_them(self):
        summary = _summarize_department_warnings(
            {
                "departmentBudgetWarnings": {"ada@example.com": 42, "grace@example.com": 42},
                "departmentBudgetBlockBalances": {
                    "ada@example.com": 455.25,
                    "grace@example.com": 480.5,
                },
                "rules": [{"ruleId": 42, "name": "Engineering monthly cap"}],
            }
        )
        # Highest first: the point of the line is who is closest to the block.
        assert "balances compared: 480.5, 455.25" in summary

    def test_missing_balance_map_still_reports_the_counts(self):
        summary = _summarize_department_warnings(
            {
                "departmentBudgetWarnings": {"ada@example.com": 42},
                "rules": [{"ruleId": 42, "name": "Engineering monthly cap"}],
            }
        )
        assert "1 subscriber warned" in summary
        assert "balances compared" not in summary

    def test_malformed_balance_map_does_not_break_rendering(self):
        summary = _summarize_department_warnings(
            {
                "departmentBudgetWarnings": {"ada@example.com": 42},
                "departmentBudgetBlockBalances": ["455.25"],
                "rules": [{"ruleId": 42, "name": "Engineering monthly cap"}],
            }
        )
        assert "1 subscriber warned" in summary
        assert "balances compared" not in summary

    def test_unparseable_balance_is_kept_and_sorted_last(self):
        """A balance the caller cannot read is still evidence someone is at
        risk, so it is rendered rather than dropped."""
        summary = _summarize_department_warnings(
            {
                "departmentBudgetWarnings": {"ada@example.com": 42, "grace@example.com": 42},
                "departmentBudgetBlockBalances": {
                    "ada@example.com": "not-a-number",
                    "grace@example.com": 10,
                },
                "rules": [{"ruleId": 42, "name": "Cap"}],
            }
        )
        assert "balances compared: 10, not-a-number" in summary

    def test_string_rule_ids_still_resolve_to_names(self):
        summary = _summarize_department_warnings(
            {
                "departmentBudgetWarnings": {"ada@example.com": "42"},
                "rules": [{"ruleId": 42, "name": "Engineering monthly cap"}],
            }
        )
        assert "- Engineering monthly cap: 1 subscriber warned" in summary

    def test_unresolvable_rule_id_falls_back_to_the_id(self):
        summary = _summarize_department_warnings(
            {"departmentBudgetWarnings": {"ada@example.com": 99}, "rules": []}
        )
        assert "- rule 99: 1 subscriber warned" in summary

    def test_unexpected_shape_is_reported_not_silently_dropped(self):
        summary = _summarize_department_warnings(
            {"departmentBudgetWarnings": ["ada@example.com"]}
        )
        assert "not the expected" in summary

    def test_long_balance_lists_are_bounded(self):
        warned = {f"user{i}@example.com": 42 for i in range(15)}
        balances = {f"user{i}@example.com": float(i) for i in range(15)}
        summary = _summarize_department_warnings(
            {
                "departmentBudgetWarnings": warned,
                "departmentBudgetBlockBalances": balances,
                "rules": [{"ruleId": 42, "name": "Cap"}],
            }
        )
        assert "15 subscribers are approaching" in summary
        assert "and 5 more" in summary

    def test_summary_never_contains_a_blank_line(self):
        """get_enforcement_rules splits the first blank line to recover the
        JSON payload, so a multi-line summary must stay one block."""
        summary = _summarize_department_warnings(
            {
                "departmentBudgetWarnings": {"ada@example.com": 42, "alan@example.com": 43},
                "rules": [{"ruleId": 42, "name": "A"}, {"ruleId": 43, "name": "B"}],
            }
        )
        assert "\n\n" not in summary


class TestEnforcementRulesWarnSummaryRendering:
    """The rendered get_enforcement_rules output must answer "who is about to
    be blocked", not hand back a raw email map."""

    @pytest.mark.asyncio
    async def test_warned_rules_are_named_with_their_counts(self, cc_mgmt, mock_client):
        mock_client.get_enforcement_rules.return_value = {
            "rules": [{"ruleId": 42, "name": "Engineering monthly cap"}],
            "compiledAt": "2026-09-09T00:00:00Z",
            "departmentBudgetWarnings": {"ada@example.com": 42, "grace@example.com": 42},
            "departmentBudgetBlockBalances": {"ada@example.com": 480.5},
        }
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action("get_enforcement_rules", {})

        text = result[0].text.split("\n\n", 1)[0]
        assert "Engineering monthly cap: 2 subscribers warned" in text
        assert "balances compared: 480.5" in text
        assert "ada@example.com" not in text

    @pytest.mark.asyncio
    async def test_blocks_are_reported_before_warnings(self, cc_mgmt, mock_client):
        """The two maps are disjoint upstream; what is already enforced
        outranks what is only approaching."""
        mock_client.get_enforcement_rules.return_value = {
            "rules": [{"ruleId": 42, "name": "Engineering monthly cap"}],
            "compiledAt": None,
            "departmentBudgetBlocks": {"ada@example.com": 42},
            "departmentBudgetWarnings": {"grace@example.com": 42},
        }
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action("get_enforcement_rules", {})

        prose = result[0].text.split("\n\n", 1)[0]
        assert prose.index("currently blocked") < prose.index("approaching")

    @pytest.mark.asyncio
    async def test_payload_is_still_recoverable_after_both_summaries(
        self, cc_mgmt, mock_client
    ):
        payload = {
            "rules": [{"ruleId": 42, "name": "Engineering monthly cap"}],
            "compiledAt": "2026-09-09T00:00:00Z",
            "departmentBudgetBlocks": {"ada@example.com": 42},
            "departmentBudgetWarnings": {"grace@example.com": 42, "alan@example.com": 42},
            "departmentBudgetBlockBalances": {"grace@example.com": 12.5},
        }
        mock_client.get_enforcement_rules.return_value = payload
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action("get_enforcement_rules", {})

        assert json.loads(result[0].text.split("\n\n", 1)[1]) == payload

    @pytest.mark.asyncio
    async def test_payload_without_the_map_renders_exactly_as_before(
        self, cc_mgmt, mock_client
    ):
        payload = {"rules": [], "compiledAt": None}
        mock_client.get_enforcement_rules.return_value = payload
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action("get_enforcement_rules", {})

        assert result[0].text == (
            "Compiled enforcement rules (0 rules, compiledAt=None):\n\n"
            + json.dumps(payload, indent=2)
        )

    @pytest.mark.asyncio
    async def test_block_units_map_is_never_summarized_as_a_verdict(
        self, cc_mgmt, mock_client
    ):
        """departmentBudgetBlockUnits covers warned and blocked people alike - it
        is attribution for notification routing, not a block list."""
        mock_client.get_enforcement_rules.return_value = {
            "rules": [],
            "compiledAt": None,
            "departmentBudgetBlockUnits": {"ada@example.com": 173},
        }
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action("get_enforcement_rules", {})

        prose = result[0].text.split("\n\n", 1)[0]
        assert "blocked" not in prose
        assert "warned" not in prose

    @pytest.mark.asyncio
    async def test_capabilities_explain_the_three_maps(self, cc_mgmt):
        caps = await cc_mgmt._get_tool_capabilities()
        rendered = json.dumps([c.description for c in caps])
        assert "departmentBudgetWarnings" in rendered
        assert "departmentBudgetBlockBalances" in rendered
        assert "NOT a verdict" in rendered

    @pytest.mark.asyncio
    async def test_the_tools_own_actions_publish_the_map_meanings(self, cc_mgmt):
        """_get_tool_capabilities prose only reaches an agent through
        tool_introspection, so the note also has to ride the notes list that
        get_capabilities and get_examples render."""
        caps = await cc_mgmt.handle_action("get_capabilities", {})
        examples = await cc_mgmt.handle_action("get_examples", {})
        for text in (caps[0].text, examples[0].text):
            assert "departmentBudgetWarnings" in text
            assert "NOT a verdict" in text

    @pytest.mark.asyncio
    async def test_the_map_meanings_are_stated_once(self, cc_mgmt):
        """One definition, interpolated twice: a second copy is how the
        capability text and the notes list drift apart."""
        caps = await cc_mgmt._get_tool_capabilities()
        enforcement = [c for c in caps if c.name == "Enforcement Visibility"][0]
        assert DEPARTMENT_ENFORCEMENT_MAPS_NOTE in enforcement.description
        rendered = (await cc_mgmt.handle_action("get_capabilities", {}))[0].text
        assert json.dumps(DEPARTMENT_ENFORCEMENT_MAPS_NOTE)[1:-1] in rendered


# ===========================================================================
# BACK-3351: enforcement-event filtering and the summary/history/affected reads
# ===========================================================================


_ALL_EVENT_FILTER_ARGS = {
    "since": "2026-09-01T00:00:00Z",
    "until": "2026-09-23T00:00:00Z",
    "rule_id": "cc_123",
    "level": "ALL",
    "mode": "SHADOW",
    "query": "gpt",
    "group_by": "SUBSCRIBER",
    "group_value": "alex@example.com",
    "transaction_id": "txn_abc",
}

_ALL_EVENT_FILTER_PARAMS = {
    "since": "2026-09-01T00:00:00Z",
    "until": "2026-09-23T00:00:00Z",
    "ruleId": "cc_123",
    "level": "ALL",
    "mode": "SHADOW",
    "query": "gpt",
    "groupBy": "SUBSCRIBER",
    "groupValue": "alex@example.com",
    "transactionId": "txn_abc",
}


class TestEnforcementEventFilterBuilding:
    """Every filter name maps to the query parameter the endpoint declares."""

    @pytest.mark.parametrize(
        "tool_name,query_name",
        [
            ("since", "since"),
            ("until", "until"),
            ("rule_id", "ruleId"),
            ("level", "level"),
            ("mode", "mode"),
            ("query", "query"),
            ("transaction_id", "transactionId"),
        ],
    )
    def test_each_scalar_filter_maps_by_name(self, tool_name, query_name):
        built = _build_enforcement_event_filters({tool_name: "x"})
        assert built == {query_name: "x"}

    def test_the_group_pair_maps_together(self):
        built = _build_enforcement_event_filters(
            {"group_by": "DEPARTMENT", "group_value": "aB3xQ"}
        )
        assert built == {"groupBy": "DEPARTMENT", "groupValue": "aB3xQ"}

    def test_every_filter_at_once(self):
        assert _build_enforcement_event_filters(_ALL_EVENT_FILTER_ARGS) == _ALL_EVENT_FILTER_PARAMS

    def test_absent_filters_are_not_sent(self):
        assert _build_enforcement_event_filters({"page": 0, "size": 20, "action": "x"}) == {}

    def test_group_by_without_group_value_is_refused_before_the_request(self):
        with pytest.raises(ToolError) as exc_info:
            _build_enforcement_event_filters({"group_by": "SUBSCRIBER"})
        assert "group_value" in exc_info.value.message

    def test_group_value_without_group_by_is_refused_before_the_request(self):
        with pytest.raises(ToolError) as exc_info:
            _build_enforcement_event_filters({"group_value": "alex@example.com"})
        assert "group_by" in exc_info.value.message

    def test_history_only_filters_are_folded_in_for_history(self):
        built = _build_enforcement_event_filters(
            {"bucket": "HOUR", "zone": "America/Denver"},
            extra={"bucket": "bucket", "zone": "zone"},
        )
        assert built == {"bucket": "HOUR", "zone": "America/Denver"}

    def test_history_only_filters_never_reach_the_shared_set(self):
        """bucket/zone are not declared on the list, so the list must not send them."""
        assert _build_enforcement_event_filters({"bucket": "HOUR", "zone": "UTC"}) == {}

    def test_affected_search_never_reaches_the_shared_set(self):
        assert _build_enforcement_event_filters({"affected_search": "data"}) == {}


class TestListEnforcementEventsForwardsEveryFilter:
    """The list handler forwards the whole filter set, not only since/ruleId."""

    @pytest.mark.asyncio
    async def test_all_filters_reach_the_client(self, cc_manager, mock_client):
        mock_client.get_enforcement_events.return_value = {}
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {}

        await cc_manager.list_enforcement_events(
            {"page": 1, "size": 5, **_ALL_EVENT_FILTER_ARGS}
        )

        mock_client.get_enforcement_events.assert_awaited_once_with(
            page=1, size=5, **_ALL_EVENT_FILTER_PARAMS
        )

    @pytest.mark.asyncio
    async def test_no_filters_sends_only_paging(self, cc_manager, mock_client):
        mock_client.get_enforcement_events.return_value = {}
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {}

        await cc_manager.list_enforcement_events({})

        mock_client.get_enforcement_events.assert_awaited_once_with(page=0, size=20)

    @pytest.mark.asyncio
    async def test_half_a_group_pair_never_reaches_the_api(self, cc_manager, mock_client):
        with pytest.raises(ToolError):
            await cc_manager.list_enforcement_events({"group_by": "SUBSCRIBER"})
        mock_client.get_enforcement_events.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rows_reach_the_caller_unmodified(self, cc_manager, mock_client):
        """The retyped row fields are a passthrough, not a formatter's allowlist."""
        row = {
            "level": "HARD",
            "isShadow": True,
            "groupBy": "SUBSCRIBER",
            "groupValue": "alex@example.com",
            "groupLabel": "Alex",
            "transactionId": "txn_abc",
            "ruleId": "cc_123",
            "ruleDeleted": True,
            "outcome": "ENFORCEMENT_VIOLATION",
            "subscriberEmail": "alex@example.com",
        }
        mock_client.get_enforcement_events.return_value = {}
        mock_client._extract_embedded_data.return_value = [row]
        mock_client._extract_pagination_info.return_value = {}

        result = await cc_manager.list_enforcement_events({})

        assert result["enforcement_events"][0] == row


class TestEnforcementEventSubReads:
    """summary, history and affected: same filters, no paging, unmodified payload."""

    @pytest.mark.asyncio
    async def test_summary_forwards_the_shared_filters_and_no_paging(
        self, cc_manager, mock_client
    ):
        mock_client.get_enforcement_events_summary.return_value = {"blocked": 1}

        result = await cc_manager.get_enforcement_events_summary(
            {"page": 3, "size": 7, **_ALL_EVENT_FILTER_ARGS}
        )

        mock_client.get_enforcement_events_summary.assert_awaited_once_with(
            **_ALL_EVENT_FILTER_PARAMS
        )
        assert result == {"blocked": 1}

    @pytest.mark.asyncio
    async def test_history_forwards_bucket_and_zone(self, cc_manager, mock_client):
        mock_client.get_enforcement_events_history.return_value = {"buckets": []}

        await cc_manager.get_enforcement_events_history(
            {"since": "2026-09-22T00:00:00Z", "bucket": "HOUR", "zone": "America/Denver"}
        )

        mock_client.get_enforcement_events_history.assert_awaited_once_with(
            since="2026-09-22T00:00:00Z", bucket="HOUR", zone="America/Denver"
        )

    @pytest.mark.asyncio
    async def test_affected_forwards_affected_search(self, cc_manager, mock_client):
        mock_client.get_enforcement_events_affected.return_value = {"rows": [], "total": 0}

        await cc_manager.get_enforcement_events_affected(
            {"rule_id": "cc_123", "affected_search": "data"}
        )

        mock_client.get_enforcement_events_affected.assert_awaited_once_with(
            ruleId="cc_123", affectedSearch="data"
        )

    @pytest.mark.asyncio
    async def test_summary_never_sends_bucket_or_affected_search(
        self, cc_manager, mock_client
    ):
        """A filter only a sibling declares must not be forwarded here."""
        mock_client.get_enforcement_events_summary.return_value = {}

        await cc_manager.get_enforcement_events_summary(
            {"bucket": "HOUR", "zone": "UTC", "affected_search": "data"}
        )

        mock_client.get_enforcement_events_summary.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_affected_never_sends_bucket_or_zone(self, cc_manager, mock_client):
        mock_client.get_enforcement_events_affected.return_value = {}

        await cc_manager.get_enforcement_events_affected({"bucket": "HOUR", "zone": "UTC"})

        mock_client.get_enforcement_events_affected.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_the_group_pair_is_enforced_on_every_sub_read(
        self, cc_manager, mock_client
    ):
        for call in (
            cc_manager.get_enforcement_events_summary,
            cc_manager.get_enforcement_events_history,
            cc_manager.get_enforcement_events_affected,
        ):
            with pytest.raises(ToolError):
                await call({"group_value": "alex@example.com"})


class TestEnforcementSubReadRendering:
    """handle_action dispatch for the three sub-reads."""

    @pytest.mark.asyncio
    async def test_summary_header_states_the_counts_and_what_they_ignore(
        self, cc_mgmt, mock_client
    ):
        mock_client.get_enforcement_events_summary.return_value = {
            "blocked": 42,
            "warned": 8,
            "wouldBlock": 3,
            "wouldWarn": 4,
            "distinctAffected": 12,
            "resolvedSince": "2026-08-15T18:30:00Z",
            "resolvedUntil": "2026-09-14T18:30:00Z",
        }
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action("get_enforcement_events_summary", {})

        header = result[0].text.split("\n\n")[0]
        assert "42 blocked" in header
        assert "8 warned" in header
        assert "3 would have been blocked and 4 would have been warned in shadow mode" in header
        assert "12 distinct" in header
        assert "ignore level and mode" in header

    @pytest.mark.asyncio
    async def test_summary_header_without_would_warn_drops_the_shadow_warn_clause(
        self, cc_mgmt, mock_client
    ):
        mock_client.get_enforcement_events_summary.return_value = {
            "blocked": 42,
            "warned": 8,
            "wouldBlock": 3,
            "distinctAffected": 12,
            "resolvedSince": "2026-08-15T18:30:00Z",
            "resolvedUntil": "2026-09-14T18:30:00Z",
        }
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action("get_enforcement_events_summary", {})

        header = result[0].text.split("\n\n")[0]
        assert "None" not in header
        assert "would have been warned" not in header
        assert (
            "42 blocked, 8 warned, 3 would have been blocked in shadow mode, "
            "12 distinct people or objects affected." in header
        )

    @pytest.mark.asyncio
    async def test_summary_header_leaves_out_every_count_the_response_omits(
        self, cc_mgmt, mock_client
    ):
        mock_client.get_enforcement_events_summary.return_value = {
            "warned": 8,
            "wouldWarn": 4,
            "resolvedSince": "2026-08-15T18:30:00Z",
            "resolvedUntil": "2026-09-14T18:30:00Z",
        }
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action("get_enforcement_events_summary", {})

        header = result[0].text.split("\n\n")[0]
        assert "None" not in header
        assert "8 warned, 4 would have been warned in shadow mode." in header
        assert "blocked" not in header
        assert "distinct" not in header

    @pytest.mark.asyncio
    async def test_summary_of_an_unexpected_shape_is_reported_not_rendered(
        self, cc_mgmt, mock_client
    ):
        mock_client.get_enforcement_events_summary.return_value = []
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action("get_enforcement_events_summary", {})

        assert "unexpected shape" in result[0].text

    @pytest.mark.asyncio
    async def test_history_header_names_the_zone_actually_used(self, cc_mgmt, mock_client):
        mock_client.get_enforcement_events_history.return_value = {
            "buckets": [{"start": "2026-09-22T00:00:00Z", "count": 2}],
            "zone": "UTC",
        }
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action(
            "get_enforcement_events_history", {"zone": "America/Denver"}
        )

        header = result[0].text.split("\n\n")[0]
        assert "1 non-empty bucket(s) cut in UTC" in header
        assert "absent, not zero" in header

    @pytest.mark.asyncio
    async def test_affected_header_says_rows_are_capped_not_paged(self, cc_mgmt, mock_client):
        mock_client.get_enforcement_events_affected.return_value = {
            "rows": [{"value": "alex@example.com", "count": 9}],
            "total": 312,
        }
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action("get_enforcement_events_affected", {})

        header = result[0].text.split("\n\n")[0]
        assert "1 affected person/object row(s) shown of 312" in header
        assert "affected_search" in header

    @pytest.mark.asyncio
    async def test_affected_header_reads_as_one_set_without_a_selector(
        self, cc_mgmt, mock_client
    ):
        mock_client.get_enforcement_events_affected.return_value = {
            "rows": [{"value": "alex@example.com"}],
            "total": 312,
        }
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action("get_enforcement_events_affected", {})

        header = result[0].text.split("\n\n")[0]
        assert "shown of 312 matching" in header
        assert "before the level/mode filter" not in header

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "selectors, rendered",
        [
            ({"level": "HARD"}, "filtered by level=HARD"),
            ({"mode": "SHADOW"}, "filtered by mode=SHADOW"),
            ({"level": "WARN", "mode": "SHADOW"}, "filtered by level=WARN, mode=SHADOW"),
        ],
    )
    async def test_affected_header_separates_filtered_rows_from_unfiltered_total(
        self, cc_mgmt, mock_client, selectors, rendered
    ):
        mock_client.get_enforcement_events_affected.return_value = {
            "rows": [{"value": "alex@example.com"}],
            "total": 312,
        }
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action("get_enforcement_events_affected", selectors)

        header = result[0].text.split("\n\n")[0]
        assert f"1 affected person/object row(s) shown ({rendered})" in header
        assert "total matching before the level/mode filter: 312" in header
        assert "shown of 312" not in header
        assert "affected_search" in header

    @pytest.mark.asyncio
    async def test_sub_read_payloads_are_recoverable_after_the_header(
        self, cc_mgmt, mock_client
    ):
        payload = {"rows": [{"value": "alex@example.com"}], "total": 1}
        mock_client.get_enforcement_events_affected.return_value = payload
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action("get_enforcement_events_affected", {})

        assert json.loads(result[0].text.split("\n\n", 1)[1]) == payload


class TestEnforcementEventDocumentationSurface:
    """The new actions and filters are discoverable, and the row fields labelled."""

    @pytest.mark.asyncio
    async def test_every_new_action_is_supported(self, cc_mgmt):
        actions = await cc_mgmt._get_supported_actions()
        for name in (
            "get_enforcement_events_summary",
            "get_enforcement_events_history",
            "get_enforcement_events_affected",
            "get_enforcement_rule_roster",
        ):
            assert name in actions

    @pytest.mark.asyncio
    async def test_every_new_filter_is_declared_on_the_input_schema(self, cc_mgmt):
        schema = await cc_mgmt._get_input_schema()
        for name in (
            "until", "level", "mode", "query", "group_by", "group_value",
            "transaction_id", "bucket", "zone", "affected_search",
            "search", "band", "sort", "dimension",
        ):
            assert name in schema["properties"], name

    @pytest.mark.asyncio
    async def test_the_new_row_fields_are_labelled_in_the_capability_text(self, cc_mgmt):
        caps = await cc_mgmt._get_tool_capabilities()
        enforcement = next(c for c in caps if "get_enforcement_rules" in c.parameters)
        for field in (
            "tier", "level", "isShadow", "groupBy", "groupValue", "groupLabel",
            "transactionId", "ruleId", "ruleDeleted",
        ):
            assert field in enforcement.description, field

    def test_tier_is_named_as_the_line_the_event_crossed(self):
        assert "which tier fired" not in ENFORCEMENT_EVENT_ROW_FIELDS_NOTE
        assert (
            "tier (the line the event crossed: HARD for the cap, WARN for the "
            "warning line)"
        ) in ENFORCEMENT_EVENT_ROW_FIELDS_NOTE

    def test_level_stays_warn_when_a_non_blocking_rule_crosses_its_cap(self):
        """The case the old wording got wrong: level is not the tier that
        fired, because a non-blocking cap crossing blocks nothing."""
        assert (
            "when a non-blocking rule crosses its cap: tier is HARD, but level "
            "stays WARN because nothing was blocked"
        ) in ENFORCEMENT_EVENT_ROW_FIELDS_NOTE

    @pytest.mark.asyncio
    async def test_tier_is_listed_as_a_row_field_not_a_filter(self, cc_mgmt):
        """The list endpoint has no tier query parameter."""
        assert "except tier," in ENFORCEMENT_EVENT_ROW_FIELDS_NOTE
        schema = await cc_mgmt._get_input_schema()
        assert "tier" not in schema["properties"]

    @pytest.mark.asyncio
    async def test_get_capabilities_publishes_the_tier_wording(self, cc_mgmt):
        result = await cc_mgmt.handle_action("get_capabilities", {})
        text = result[0].text
        assert "tier (the line the event crossed" in text
        assert "level stays WARN because nothing was blocked" in text
        assert "which tier fired" not in text

    @pytest.mark.asyncio
    async def test_the_row_field_note_is_stated_once(self, cc_mgmt):
        """One authoritative spelling: a second copy is what drifts."""
        caps = await cc_mgmt._get_tool_capabilities()
        rendered = json.dumps([c.description for c in caps])
        assert rendered.count(ENFORCEMENT_EVENT_ROW_FIELDS_NOTE[:60]) == 1

    @pytest.mark.asyncio
    async def test_the_capability_publishes_the_new_conventions(self, cc_mgmt):
        caps = await cc_mgmt._get_tool_capabilities()
        enforcement = next(c for c in caps if "get_enforcement_rules" in c.parameters)
        for note in (
            ENFORCEMENT_GROUP_PAIR_NOTE,
            ENFORCEMENT_SUBREADS_UNPAGED_NOTE,
            ENFORCEMENT_ROSTER_NOTE,
        ):
            assert note in enforcement.limitations

    @pytest.mark.asyncio
    async def test_get_examples_publishes_the_enforcement_notes(self, cc_mgmt):
        result = await cc_mgmt.handle_action("get_examples", {})
        assert ENFORCEMENT_GROUP_PAIR_NOTE in result[0].text
        assert "get_enforcement_rule_roster" in result[0].text


# ===========================================================================
# BACK-3352: one rule's compiled entry and its roster
# ===========================================================================


class TestGetEnforcementRulesNarrowedToOneRule:
    """rule_id narrows the compiled read, and an unknown id is not an empty team."""

    @pytest.mark.asyncio
    async def test_rule_id_is_forwarded(self, cc_manager, mock_client):
        mock_client.get_enforcement_rules.return_value = {"rules": []}

        await cc_manager.get_enforcement_rules({"rule_id": "cc_123"})

        mock_client.get_enforcement_rules.assert_awaited_once_with(rule_id="cc_123")

    @pytest.mark.asyncio
    async def test_empty_rules_for_a_known_id_render_as_no_such_rule(
        self, cc_mgmt, mock_client
    ):
        mock_client.get_enforcement_rules.return_value = {"rules": [], "compiledAt": None}
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action(
            "get_enforcement_rules", {"rule_id": "cc_nope"}
        )

        assert "No compiled rule with id cc_nope" in result[0].text
        assert "0 rules" not in result[0].text

    @pytest.mark.asyncio
    async def test_an_empty_unnarrowed_read_still_reads_as_an_empty_team(
        self, cc_mgmt, mock_client
    ):
        mock_client.get_enforcement_rules.return_value = {"rules": [], "compiledAt": None}
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action("get_enforcement_rules", {})

        assert "0 rules" in result[0].text
        assert "No compiled rule with id" not in result[0].text

    @pytest.mark.asyncio
    async def test_a_narrowed_hit_names_the_rule_it_was_narrowed_to(
        self, cc_mgmt, mock_client
    ):
        mock_client.get_enforcement_rules.return_value = {
            "rules": [{"ruleId": "cc_123", "name": "Monthly cap"}],
            "compiledAt": "2026-09-23T00:00:00Z",
        }
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action(
            "get_enforcement_rules", {"rule_id": "cc_123"}
        )

        assert "for rule cc_123" in result[0].text
        assert "1 rules" in result[0].text


class TestGetEnforcementRuleRoster:
    """The per-rule roster read."""

    @pytest.mark.asyncio
    async def test_every_selector_is_forwarded(self, cc_manager, mock_client):
        mock_client.get_enforcement_rule_roster.return_value = {"rows": []}

        await cc_manager.get_enforcement_rule_roster(
            {
                "rule_id": "cc_123",
                "page": 2,
                "size": 50,
                "search": "data",
                "band": "BLOCKED",
                "sort": "PERCENT",
                "dimension": "SUBSCRIBER",
            }
        )

        mock_client.get_enforcement_rule_roster.assert_awaited_once_with(
            rule_id="cc_123",
            page=2,
            size=50,
            search="data",
            band="BLOCKED",
            sort="PERCENT",
            dimension="SUBSCRIBER",
        )

    @pytest.mark.asyncio
    async def test_defaults_when_only_a_rule_id_is_given(self, cc_manager, mock_client):
        mock_client.get_enforcement_rule_roster.return_value = {"rows": []}

        await cc_manager.get_enforcement_rule_roster({"rule_id": "cc_123"})

        mock_client.get_enforcement_rule_roster.assert_awaited_once_with(
            rule_id="cc_123", page=0, size=20, search=None, band=None, sort=None, dimension=None
        )

    @pytest.mark.asyncio
    async def test_missing_rule_id_is_refused_before_the_request(
        self, cc_manager, mock_client
    ):
        with pytest.raises(ToolError) as exc_info:
            await cc_manager.get_enforcement_rule_roster({})

        assert "rule_id" in exc_info.value.message
        mock_client.get_enforcement_rule_roster.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_pooled_rule_404_is_explained_not_passed_through(
        self, cc_manager, mock_client
    ):
        mock_client.get_enforcement_rule_roster.side_effect = ReveniumAPIError(
            "Not Found", status_code=404
        )

        with pytest.raises(ToolError) as exc_info:
            await cc_manager.get_enforcement_rule_roster({"rule_id": "cc_pooled"})

        assert exc_info.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND
        assert "pooled" in json.dumps(exc_info.value.suggestions)

    @pytest.mark.asyncio
    async def test_other_api_errors_propagate(self, cc_manager, mock_client):
        mock_client.get_enforcement_rule_roster.side_effect = ReveniumAPIError(
            "Boom", status_code=500
        )

        with pytest.raises(ReveniumAPIError):
            await cc_manager.get_enforcement_rule_roster({"rule_id": "cc_123"})

    @pytest.mark.asyncio
    async def test_roster_header_reports_the_whole_roster_counts(self, cc_mgmt, mock_client):
        mock_client.get_enforcement_rule_roster.return_value = {
            "ruleId": "cc_123",
            "dimension": "SUBSCRIBER",
            "rows": [{"key": "alex@example.com"}],
            "total": 42,
            "blockedCount": 3,
            "warnedCount": 5,
            "underCount": 34,
        }
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action(
            "get_enforcement_rule_roster", {"rule_id": "cc_123"}
        )

        header = result[0].text.split("\n\n")[0]
        assert "Roster for rule cc_123 (SUBSCRIBER)" in header
        assert "1 row(s) of 42 matching" in header
        assert "3 blocked, 5 warned, 34 under" in header
        assert "names people or departments" in header

    @pytest.mark.asyncio
    async def test_a_204_roster_renders_as_not_yet_compiled(self, cc_mgmt, mock_client):
        # ReveniumClient._request maps a 204 or any empty body to {}.
        mock_client.get_enforcement_rule_roster.return_value = {}
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action(
            "get_enforcement_rule_roster", {"rule_id": "cc_123"}
        )

        assert result[0].text == (
            "No compiled roster is available for rule cc_123 yet; "
            "the reading is produced by the next compile."
        )

    @pytest.mark.asyncio
    async def test_roster_payload_is_recoverable_after_the_header(self, cc_mgmt, mock_client):
        payload = {"ruleId": "cc_123", "rows": [{"key": "alex@example.com"}], "total": 1}
        mock_client.get_enforcement_rule_roster.return_value = payload
        cc_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await cc_mgmt.handle_action(
            "get_enforcement_rule_roster", {"rule_id": "cc_123"}
        )

        assert json.loads(result[0].text.split("\n\n", 1)[1]) == payload
