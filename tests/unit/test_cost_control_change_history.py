"""BACK-5680: get_cost_controls reads a budget's change history and the team's change log."""

import contextlib
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from fastmcp import Client, FastMCP

from src.revenium_mcp_server.auth import AuthConfig
from src.revenium_mcp_server.client import ReveniumAPIError, ReveniumClient
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from src.revenium_mcp_server.common.tool_surface import domain_for
from src.revenium_mcp_server.common.validation import is_blank
from src.revenium_mcp_server.middleware.framework_leak_guard import (
    FrameworkLeakGuardMiddleware,
)
from src.revenium_mcp_server.tools_decomposed import cost_controls_management
from src.revenium_mcp_server.tools_decomposed.cost_controls_management import (
    CostControlsManagement,
)
from tests.unit.test_tool_config_registry_m4 import (
    _call_through_the_boundary,
    _get_registered_closure,
    _make_registry,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXCLUSIONS_FILE = REPO_ROOT / ".claude" / "commands" / "mcp-api-exclusions.yaml"
EXPORT_PATH = "/v2/api/ai/control-changes/export"
HISTORY_ACTIONS = ("list_changes", "get_changes_summary", "list_control_changes")
WINDOW = {"since": "2026-10-01T00:00:00Z", "until": "2026-11-01T00:00:00Z"}
WINDOW_READERS = (
    "list_control_changes",
    "list_enforcement_events",
    "get_enforcement_events_summary",
    "get_enforcement_events_history",
    "get_enforcement_events_affected",
)
TEAM_LOG_FILTERS = ("subject_type", "subject_id", "change_type", "changed_by", "api_key_id")
ENFORCEMENT_NARROWINGS = (
    "rule_id",
    "level",
    "mode",
    "query",
    "group_by",
    "group_value",
    "transaction_id",
    "bucket",
    "zone",
    "affected_search",
)
ROSTER_NARROWINGS = ("search", "band", "sort", "dimension")
HISTORY_BASE = {
    "list_changes": {"control_id": "cc_1"},
    "get_changes_summary": {"control_id": "cc_1"},
    "list_control_changes": dict(WINDOW),
}
DECLARED_SAMPLES = {
    "control_data": {"name": "x"},
    "filters": {"query": "x"},
    "include_advisory": True,
    "parent_department_id": 173,
    "parent_org_unit_id": 173,
}
GATE_REFUSAL = "Feature not available"
UNMAPPED_ROUTE = {"timestamp": "2026-11-10T12:00:00Z", "status": 404, "error": "Not Found"}


def _platform_404(message: str) -> ReveniumAPIError:
    body = {**UNMAPPED_ROUTE, "message": message}
    return ReveniumAPIError(f"HTTP 404: {message}", status_code=404, response_data={"error_data": body})


def _unmapped_404() -> ReveniumAPIError:
    return ReveniumAPIError(
        "HTTP 404: Not Found", status_code=404, response_data={"error_data": UNMAPPED_ROUTE}
    )

ENTRY = {
    "changeType": "EDITED",
    "changedAt": "2026-10-28T14:14:03.512Z",
    "changedBy": {"kind": "PERSON", "display": "jane@acme.com", "value": "jane@acme.com"},
    "fieldChanges": [
        {
            "field": "hardLimit",
            "label": "Hard limit",
            "change": "CHANGED",
            "before": "1000",
            "after": "1500",
            "valueType": "CURRENCY_USD",
            "beforeValueType": "CURRENCY_USD",
        }
    ],
    "reason": "Raised for the Q4 launch",
    "relation": "SELF",
    "revision": 140223991,
    "subject": {
        "type": "COST_CONTROL",
        "id": "cc_1",
        "nameAtTheTime": "Monthly OpenAI Cap",
        "teamId": "team_abc",
        "deleted": False,
    },
    "summary": None,
}
PAGE = {
    "_embedded": {"changes": [ENTRY]},
    "page": {"number": 0, "size": 20, "totalElements": 1, "totalPages": 1},
}
EMPTY_PAGE = {"page": {"number": 0, "size": 20, "totalElements": 0, "totalPages": 0}}
SUMMARY = {
    "createdAt": "2026-10-24T09:00:00.000Z",
    "createdBy": {"kind": "PERSON", "display": "jane@acme.com", "value": "jane@acme.com"},
    "lastChangedAt": "2026-10-28T14:14:03.512Z",
    "lastChangedBy": {"kind": "PERSON", "display": "jane@acme.com", "value": "jane@acme.com"},
    "historyStartsAt": "2026-10-22T21:03:55.120Z",
}


def _client() -> ReveniumClient:
    client = ReveniumClient(
        auth_config=AuthConfig(
            api_key="test_key_12345",
            team_id="team_abc",
            base_url="https://api.test.revenium.ai",
            timeout=10.0,
        )
    )
    client.get = AsyncMock(return_value={})
    return client


@pytest.mark.asyncio
class TestTheClient:
    async def test_a_budget_history_page_reads_the_changes_route_with_the_team(self):
        client = _client()

        await client.get_cost_control_changes("cc_1", page=2, size=50)

        client.get.assert_awaited_once_with(
            "/profitstream/v2/api/ai/cost-controls/cc_1/changes",
            params={"page": 2, "size": 50, "teamId": "team_abc"},
        )

    @pytest.mark.parametrize(
        "control_id, segment", [("cc/1", "cc%2F1"), ("..", "%2E%2E"), ("a b", "a%20b")]
    )
    async def test_the_budget_id_stays_one_path_segment(self, control_id, segment):
        client = _client()

        await client.get_cost_control_changes(control_id)
        await client.get_cost_control_change_summary(control_id)

        paths = [call.args[0] for call in client.get.await_args_list]
        assert paths == [
            f"/profitstream/v2/api/ai/cost-controls/{segment}/changes",
            f"/profitstream/v2/api/ai/cost-controls/{segment}/changes/summary",
        ]

    async def test_the_summary_is_unpaged(self):
        client = _client()

        await client.get_cost_control_change_summary("cc_1")

        client.get.assert_awaited_once_with(
            "/profitstream/v2/api/ai/cost-controls/cc_1/changes/summary",
            params={"teamId": "team_abc"},
        )

    async def test_the_team_log_sends_the_window_the_paging_and_the_team(self):
        client = _client()

        await client.get_control_changes(
            "2026-10-01T00:00:00Z",
            "2026-11-01T00:00:00Z",
            page=1,
            size=10,
            subjectType="ALERT",
            changedBy="jane@acme.com",
        )

        client.get.assert_awaited_once_with(
            "/profitstream/v2/api/ai/control-changes",
            params={
                "since": "2026-10-01T00:00:00Z",
                "until": "2026-11-01T00:00:00Z",
                "page": 1,
                "size": 10,
                "subjectType": "ALERT",
                "changedBy": "jane@acme.com",
                "teamId": "team_abc",
            },
        )


def _platform() -> MagicMock:
    platform = MagicMock()
    platform.team_id = "team_abc"
    platform.get_cost_control_changes = AsyncMock(return_value=PAGE)
    platform.get_cost_control_change_summary = AsyncMock(return_value=SUMMARY)
    platform.get_control_changes = AsyncMock(return_value=PAGE)
    platform._extract_embedded_data = ReveniumClient._extract_embedded_data.__get__(platform)
    platform._extract_pagination_info = ReveniumClient._extract_pagination_info.__get__(platform)
    return platform


async def _act(action, arguments, platform):
    tool = CostControlsManagement()
    with patch.object(CostControlsManagement, "get_client", AsyncMock(return_value=platform)):
        result = await tool.handle_action(action, arguments)
    return result[0].text


@pytest.mark.asyncio
class TestOneBudgetsHistory:
    async def test_the_page_is_rendered_entry_by_entry(self):
        platform = _platform()

        text = await _act("list_changes", {"control_id": "cc_1"}, platform)

        assert text.startswith("Change history of budget cc_1. Found 1 of 1 changes")
        assert "edited by jane@acme.com" in text
        assert "Reason: Raised for the Q4 launch" in text
        assert "Hard limit (hardLimit): 1,000.00 USD -> 1,500.00 USD" in text
        platform.get_cost_control_changes.assert_awaited_once_with("cc_1", page=0, size=20)

    async def test_paging_is_forwarded(self):
        platform = _platform()

        await _act("list_changes", {"control_id": "cc_1", "page": "3", "size": 5}, platform)

        platform.get_cost_control_changes.assert_awaited_once_with("cc_1", page=3, size=5)

    async def test_an_empty_history_is_an_answer(self):
        platform = _platform()
        platform.get_cost_control_changes.return_value = EMPTY_PAGE

        text = await _act("list_changes", {"control_id": "cc_1"}, platform)

        assert text == "Change history of budget cc_1. Found 0 changes; the platform reports none."

    async def test_more_pages_are_announced(self):
        platform = _platform()
        platform.get_cost_control_changes.return_value = {
            **PAGE,
            "page": {"number": 0, "size": 1, "totalElements": 4, "totalPages": 4},
        }

        text = await _act("list_changes", {"control_id": "cc_1", "size": 1}, platform)

        assert text.endswith("More changes exist: pass page=1 size=1 for the next page.")

    async def test_the_summary_names_who_created_and_who_changed_it_last(self):
        platform = _platform()

        text = await _act("get_changes_summary", {"control_id": "cc_1"}, platform)

        assert text.startswith("Change summary of budget cc_1:")
        assert "- Created: 2026-10-24T09:00:00.000Z by jane@acme.com" in text
        platform.get_cost_control_change_summary.assert_awaited_once_with("cc_1")

    @pytest.mark.parametrize("action", ["list_changes", "get_changes_summary"])
    async def test_a_missing_budget_id_is_refused(self, action):
        platform = _platform()

        with pytest.raises(ToolError) as refusal:
            await _act(action, {}, platform)

        assert refusal.value.error_code == ErrorCodes.MISSING_PARAMETER
        assert refusal.value.field == "control_id"

    @pytest.mark.parametrize("size", [0, 101, "many", True])
    async def test_a_page_size_outside_the_platform_cap_is_refused(self, size):
        platform = _platform()

        with pytest.raises(ToolError):
            await _act("list_changes", {"control_id": "cc_1", "size": size}, platform)

        platform.get_cost_control_changes.assert_not_awaited()

    @pytest.mark.parametrize("action", ["list_changes", "get_changes_summary"])
    async def test_a_window_is_refused_and_the_team_log_is_named(self, action):
        platform = _platform()

        with pytest.raises(ToolError) as refusal:
            await _act(action, {"control_id": "cc_1", "since": "2026-10-01T00:00:00Z"}, platform)

        assert "since" in refusal.value.message
        assert "list_control_changes" in refusal.value.message
        platform.get_cost_control_changes.assert_not_awaited()
        platform.get_cost_control_change_summary.assert_not_awaited()

    @pytest.mark.parametrize("action", ["list_changes", "get_changes_summary"])
    async def test_the_platforms_404_is_the_budget_not_being_found(self, action):
        platform = _platform()
        for read in (platform.get_cost_control_changes, platform.get_cost_control_change_summary):
            read.side_effect = _platform_404("Cost control not found for id: cc_gone")

        with pytest.raises(ToolError) as refusal:
            await _act(action, {"control_id": "cc_gone"}, platform)

        assert refusal.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND
        assert "cc_gone" in refusal.value.message

    @pytest.mark.parametrize("action", ["list_changes", "get_changes_summary"])
    async def test_a_platform_without_the_route_is_not_a_missing_budget(self, action):
        platform = _platform()
        for read in (platform.get_cost_control_changes, platform.get_cost_control_change_summary):
            read.side_effect = _unmapped_404()

        with pytest.raises(ToolError) as refusal:
            await _act(action, {"control_id": "cc_1"}, platform)

        assert refusal.value.error_code == ErrorCodes.RESOURCE_UNAVAILABLE
        assert "does not offer change history" in refusal.value.message
        assert "not found" not in refusal.value.message.lower()

    @pytest.mark.parametrize("action", ["list_changes", "get_changes_summary"])
    @pytest.mark.parametrize("status", [400, 403, 500, 503])
    async def test_any_other_failure_keeps_the_platforms_answer(self, action, status):
        platform = _platform()
        for read in (platform.get_cost_control_changes, platform.get_cost_control_change_summary):
            read.side_effect = ReveniumAPIError(GATE_REFUSAL, status_code=status)

        with pytest.raises(ReveniumAPIError) as failure:
            await _act(action, {"control_id": "cc_1"}, platform)

        assert failure.value.status_code == status
        assert failure.value.message == GATE_REFUSAL

    @pytest.mark.parametrize("action", ["list_changes", "get_changes_summary"])
    async def test_a_filters_object_is_refused_and_the_team_log_is_named(self, action):
        platform = _platform()

        with pytest.raises(ToolError) as refusal:
            await _act(
                action, {"control_id": "cc_1", "filters": {"changed_by": "jane@acme.com"}}, platform
            )

        assert refusal.value.field == "filters"
        assert "list_control_changes" in refusal.value.message
        assert "jane@acme.com" not in str(refusal.value)
        platform.get_cost_control_changes.assert_not_awaited()
        platform.get_cost_control_change_summary.assert_not_awaited()

    @pytest.mark.parametrize("action", ["list_changes", "get_changes_summary"])
    async def test_an_empty_filters_object_is_no_narrowing(self, action):
        platform = _platform()

        text = await _act(action, {"control_id": "cc_1", "filters": {}}, platform)

        if action == "list_changes":
            platform.get_cost_control_changes.assert_awaited_once_with("cc_1", page=0, size=20)
            assert text.startswith("Change history of budget cc_1. Found 1 of 1 changes")
        else:
            platform.get_cost_control_change_summary.assert_awaited_once_with("cc_1")
            assert text.startswith("Change summary of budget cc_1:")


@pytest.mark.asyncio
class TestTheTeamLog:
    async def test_the_window_and_filters_are_sent_by_their_platform_names(self):
        platform = _platform()

        text = await _act(
            "list_control_changes",
            {
                **WINDOW,
                "subject_type": "COST_CONTROL",
                "subject_id": "cc_1",
                "change_type": "EDITED,DELETED",
                "changed_by": "jane@acme.com",
                "api_key_id": "5jW1GD",
                "page": 1,
                "size": 50,
            },
            platform,
        )

        platform.get_control_changes.assert_awaited_once_with(
            "2026-10-01T00:00:00Z",
            "2026-11-01T00:00:00Z",
            page=1,
            size=50,
            subjectType="COST_CONTROL",
            subjectId="cc_1",
            changeType="EDITED,DELETED",
            changedBy="jane@acme.com",
            apiKeyId="5jW1GD",
        )
        assert text.startswith(
            "Changes to the team's budgets and alerts from 2026-10-01T00:00:00Z "
            "until 2026-11-01T00:00:00Z."
        )
        assert 'budget "Monthly OpenAI Cap" (cc_1)' in text

    async def test_without_filters_only_the_window_and_paging_are_sent(self):
        platform = _platform()

        await _act("list_control_changes", dict(WINDOW), platform)

        platform.get_control_changes.assert_awaited_once_with(
            "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z", page=0, size=20
        )

    @pytest.mark.parametrize(
        "window, missing",
        [
            ({}, "since"),
            ({"since": "2026-10-01T00:00:00Z"}, "until"),
            ({"until": "2026-11-01T00:00:00Z"}, "since"),
            ({"since": " ", "until": "2026-11-01T00:00:00Z"}, "since"),
        ],
    )
    async def test_no_window_is_assumed(self, window, missing):
        platform = _platform()

        with pytest.raises(ToolError) as refusal:
            await _act("list_control_changes", window, platform)

        assert refusal.value.error_code == ErrorCodes.MISSING_PARAMETER
        assert refusal.value.field == missing
        assert "needs both since and until" in refusal.value.message
        assert "does not choose a window" in refusal.value.message
        platform.get_control_changes.assert_not_awaited()

    async def test_an_empty_window_is_an_answer(self):
        platform = _platform()
        platform.get_control_changes.return_value = EMPTY_PAGE

        text = await _act("list_control_changes", dict(WINDOW), platform)

        assert text.endswith("Found 0 changes; the platform reports none.")

    @pytest.mark.parametrize("status", [400, 403, 422, 500])
    async def test_the_platforms_refusal_reaches_the_caller(self, status):
        platform = _platform()
        refusal = ReveniumAPIError("until must be after since", status_code=status)
        platform.get_control_changes.side_effect = refusal

        with pytest.raises(ReveniumAPIError) as failure:
            await _act("list_control_changes", dict(WINDOW), platform)

        assert failure.value is refusal

    async def test_the_platforms_team_not_found_reaches_the_caller(self):
        platform = _platform()
        refusal = _platform_404("Team not found for id: team_abc")
        platform.get_control_changes.side_effect = refusal

        with pytest.raises(ReveniumAPIError) as failure:
            await _act("list_control_changes", dict(WINDOW), platform)

        assert failure.value is refusal

    async def test_a_platform_without_the_team_log_says_so(self):
        platform = _platform()
        platform.get_control_changes.side_effect = _unmapped_404()

        with pytest.raises(ToolError) as refusal:
            await _act("list_control_changes", dict(WINDOW), platform)

        assert refusal.value.error_code == ErrorCodes.RESOURCE_UNAVAILABLE
        assert "does not offer change history" in refusal.value.message

    @pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "whitespace"])
    @pytest.mark.parametrize("argument", TEAM_LOG_FILTERS)
    async def test_a_blank_filter_is_not_sent(self, argument, blank):
        platform = _platform()

        text = await _act("list_control_changes", {**WINDOW, argument: blank}, platform)

        platform.get_control_changes.assert_awaited_once_with(
            "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z", page=0, size=20
        )
        assert text.startswith("Changes to the team's budgets and alerts")

    async def test_a_filter_and_the_window_are_sent_without_surrounding_whitespace(self):
        platform = _platform()

        await _act(
            "list_control_changes",
            {"since": " 2026-10-01T00:00:00Z", "until": "2026-11-01T00:00:00Z ", "changed_by": " jane@acme.com "},
            platform,
        )

        platform.get_control_changes.assert_awaited_once_with(
            "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z", page=0, size=20, changedBy="jane@acme.com"
        )

    async def test_a_filters_object_is_refused_and_the_top_level_arguments_are_named(self):
        platform = _platform()

        with pytest.raises(ToolError) as refusal:
            await _act(
                "list_control_changes",
                {**WINDOW, "filters": {"subject_type": "ALERT", "changed_by": "jane@acme.com"}},
                platform,
            )

        assert refusal.value.field == "filters"
        for argument in TEAM_LOG_FILTERS:
            assert argument in refusal.value.message
        assert "jane@acme.com" not in str(refusal.value)
        platform.get_control_changes.assert_not_awaited()

    async def test_an_empty_filters_object_is_no_narrowing(self):
        platform = _platform()

        await _act("list_control_changes", {**WINDOW, "filters": {}}, platform)

        platform.get_control_changes.assert_awaited_once()

    @pytest.mark.parametrize("argument", ENFORCEMENT_NARROWINGS)
    @pytest.mark.parametrize("action", HISTORY_ACTIONS)
    async def test_an_enforcement_narrowing_on_a_history_read_is_refused(self, action, argument):
        platform = _platform()
        arguments = dict(WINDOW) if action == "list_control_changes" else {"control_id": "cc_1"}

        with pytest.raises(ToolError) as refusal:
            await _act(action, {**arguments, argument: "cc_9"}, platform)

        assert refusal.value.field == argument
        assert f"does not read {argument}" in refusal.value.message
        assert "subject_id" in refusal.value.message
        assert "cc_9" not in str(refusal.value)
        platform.get_cost_control_changes.assert_not_awaited()
        platform.get_cost_control_change_summary.assert_not_awaited()
        platform.get_control_changes.assert_not_awaited()

    async def test_a_budget_id_on_the_team_log_is_refused_and_subject_id_is_named(self):
        platform = _platform()

        with pytest.raises(ToolError) as refusal:
            await _act("list_control_changes", {**WINDOW, "control_id": "cc_1"}, platform)

        assert refusal.value.field == "control_id"
        assert "subject_type='COST_CONTROL'" in refusal.value.message
        assert "subject_id" in refusal.value.message
        platform.get_control_changes.assert_not_awaited()

    @pytest.mark.parametrize("blank", ["", "  "], ids=["empty", "whitespace"])
    @pytest.mark.parametrize("argument", ENFORCEMENT_NARROWINGS)
    async def test_a_blank_enforcement_narrowing_is_no_narrowing(self, argument, blank):
        platform = _platform()

        await _act("list_control_changes", {**WINDOW, argument: blank}, platform)

        platform.get_control_changes.assert_awaited_once()

    @pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "whitespace"])
    @pytest.mark.parametrize("argument", ("since", "until", *TEAM_LOG_FILTERS))
    @pytest.mark.parametrize("action", ["list_changes", "get_changes_summary"])
    async def test_a_blank_window_or_team_log_filter_on_one_budgets_history_narrows_nothing(
        self, action, argument, blank
    ):
        platform = _platform()

        await _act(action, {"control_id": "cc_1", argument: blank}, platform)

        read = (
            platform.get_cost_control_changes
            if action == "list_changes"
            else platform.get_cost_control_change_summary
        )
        read.assert_awaited_once()

    @pytest.mark.parametrize("argument", ["since", "changed_by"])
    async def test_a_blank_window_or_filter_stays_refused_on_an_action_with_no_history(
        self, argument
    ):
        refusal = await _refusal_before_any_read("list", {argument: ""})

        assert refusal.field == argument
        assert "read only by" in refusal.message

    @pytest.mark.parametrize("argument", ["subject_type", "changed_by"])
    async def test_a_team_log_filter_on_one_budgets_history_is_refused(self, argument):
        platform = _platform()

        with pytest.raises(ToolError) as refusal:
            await _act("list_changes", {"control_id": "cc_1", argument: "x"}, platform)

        assert argument in refusal.value.message
        assert "list_control_changes" in refusal.value.message


async def _declared_arguments():
    closure = await _get_registered_closure(
        _make_registry(profile="business"), "_register_manage_cost_controls"
    )
    return set(inspect.signature(closure).parameters)


def _assert_nothing_read(platform):
    platform.get_cost_control_changes.assert_not_awaited()
    platform.get_cost_control_change_summary.assert_not_awaited()
    platform.get_control_changes.assert_not_awaited()


async def _refusal_before_any_read(action, arguments):
    tool = CostControlsManagement()
    get_client = AsyncMock(return_value=_platform())
    with patch.object(CostControlsManagement, "get_client", get_client):
        with pytest.raises(ToolError) as refusal:
            await tool.handle_action(action, arguments)
    get_client.assert_not_awaited()
    return refusal.value


@pytest.mark.asyncio
class TestNoActionDropsAHistoryArgument:
    async def test_every_action_with_no_history_refuses_the_team_log_filters(self):
        actions = await CostControlsManagement()._get_supported_actions()

        for action in actions:
            if action in HISTORY_ACTIONS:
                continue
            refusal = await _refusal_before_any_read(action, {"changed_by": "jane@acme.com"})
            assert refusal.field == "changed_by", action
            assert "read only by list_control_changes" in refusal.message, action
            assert "jane@acme.com" not in str(refusal), action

    @pytest.mark.parametrize("argument", TEAM_LOG_FILTERS)
    async def test_an_enforcement_event_read_refuses_each_team_log_filter(self, argument):
        refusal = await _refusal_before_any_read("list_enforcement_events", {argument: "x"})

        assert refusal.field == argument
        assert "list_control_changes" in refusal.message

    async def test_every_action_without_a_window_refuses_since_and_until(self):
        actions = await CostControlsManagement()._get_supported_actions()

        for action in actions:
            if action in WINDOW_READERS or action in HISTORY_ACTIONS:
                continue
            refusal = await _refusal_before_any_read(action, {"until": "2026-11-01T00:00:00Z"})
            assert refusal.field == "until", action
            assert "list_enforcement_events" in refusal.message, action

    async def test_every_action_that_builds_the_enforcement_filters_takes_a_window(self):
        reached = []

        def spy(arguments, extra=None):
            reached.append(current)
            raise RuntimeError("stop before any read")

        actions = await CostControlsManagement()._get_supported_actions()
        with patch.object(cost_controls_management, "_build_enforcement_event_filters", spy):
            with patch.object(
                CostControlsManagement, "get_client", AsyncMock(return_value=_platform())
            ):
                for current in actions:
                    with contextlib.suppress(Exception):
                        await CostControlsManagement().handle_action(
                            current, {"rule_id": "cc_1", "group_by": "SUBSCRIBER", "group_value": "x"}
                        )

        assert reached
        assert set(reached) <= set(cost_controls_management._WINDOW_READERS)

    @pytest.mark.parametrize("argument", ROSTER_NARROWINGS)
    @pytest.mark.parametrize("action", HISTORY_ACTIONS)
    async def test_a_roster_narrowing_on_a_history_read_is_refused(self, action, argument):
        platform = _platform()

        with pytest.raises(ToolError) as refusal:
            await _act(action, {**HISTORY_BASE[action], argument: "jane@acme.com"}, platform)

        assert refusal.value.field == argument
        assert f"does not read {argument}" in refusal.value.message
        assert "jane@acme.com" not in str(refusal.value)
        _assert_nothing_read(platform)

    @pytest.mark.parametrize("action", HISTORY_ACTIONS)
    async def test_every_argument_the_tool_declares_is_read_or_refused_by_each_history_read(
        self, action
    ):
        declared = await _declared_arguments()
        reads = cost_controls_management.HISTORY_READ_ARGUMENTS[action]
        sent_on_every_call = cost_controls_management.SENT_ON_EVERY_CALL

        for argument in sorted(declared - set(reads) - set(sent_on_every_call)):
            platform = _platform()
            value = DECLARED_SAMPLES.get(argument, "x")

            with pytest.raises(ToolError) as refusal:
                await _act(action, {**HISTORY_BASE[action], argument: value}, platform)

            assert refusal.value.field == argument, (action, argument)
            _assert_nothing_read(platform)

    @pytest.mark.parametrize("action", HISTORY_ACTIONS)
    async def test_the_registry_adds_nothing_a_history_read_would_refuse(self, action):
        caller = {"action": action, **HISTORY_BASE[action]}
        _, _, reached = await _call_through_the_boundary(
            "_register_manage_cost_controls", "manage_cost_controls", caller
        )
        added = set(reached) - set(caller)
        sent_on_every_call = set(cost_controls_management.SENT_ON_EVERY_CALL) - {"action"}

        assert sent_on_every_call <= added
        assert all(is_blank(reached[name]) for name in added - sent_on_every_call)

    async def test_a_blank_window_on_one_budgets_history_through_the_read_tool_is_answered(self):
        platform = _platform()
        with patch.object(CostControlsManagement, "get_client", AsyncMock(return_value=platform)):
            is_error, text, _ = await _call_through_the_boundary(
                "_register_manage_cost_controls",
                "manage_cost_controls",
                {"action": "list_changes", "control_id": "cc_1", "since": "", "changed_by": " "},
                execute=True,
            )

        assert not is_error, text
        platform.get_cost_control_changes.assert_awaited_once_with("cc_1", page=0, size=20)

    async def test_what_the_history_reads_take_is_declared_by_the_tool(self):
        declared = await _declared_arguments()

        for reads in cost_controls_management.HISTORY_READ_ARGUMENTS.values():
            assert set(reads) <= declared
        assert set(cost_controls_management.SENT_ON_EVERY_CALL) <= declared

    async def test_the_read_tool_refuses_search_on_the_team_log(self):
        platform = _platform()
        with patch.object(CostControlsManagement, "get_client", AsyncMock(return_value=platform)):
            is_error, text, _ = await _call_through_the_boundary(
                "_register_manage_cost_controls",
                "manage_cost_controls",
                {"action": "list_control_changes", **WINDOW, "search": "jane@acme.com"},
                execute=True,
            )

        assert is_error
        assert "does not read search" in text
        platform.get_control_changes.assert_not_awaited()

    @pytest.mark.parametrize("action", WINDOW_READERS)
    async def test_the_window_readers_take_since_and_until(self, action):
        get_client = AsyncMock(return_value=_platform())
        with patch.object(CostControlsManagement, "get_client", get_client):
            with contextlib.suppress(Exception):
                await CostControlsManagement().handle_action(action, dict(WINDOW))

        get_client.assert_awaited_once()

    async def test_the_read_tool_refuses_a_team_log_filter_on_enforcement_events(self):
        platform = _platform()
        with patch.object(CostControlsManagement, "get_client", AsyncMock(return_value=platform)):
            is_error, text, _ = await _call_through_the_boundary(
                "_register_manage_cost_controls",
                "manage_cost_controls",
                {"action": "list_enforcement_events", "changed_by": "jane@acme.com"},
                execute=True,
            )

        assert is_error
        assert "list_control_changes" in text

    async def test_the_read_tool_refuses_filters_on_the_team_log(self):
        platform = _platform()
        with patch.object(CostControlsManagement, "get_client", AsyncMock(return_value=platform)):
            is_error, text, _ = await _call_through_the_boundary(
                "_register_manage_cost_controls",
                "manage_cost_controls",
                {"action": "list_control_changes", **WINDOW, "filters": {"subject_type": "ALERT"}},
                execute=True,
            )

        assert is_error
        assert "subject_type" in text
        platform.get_control_changes.assert_not_awaited()


@pytest.mark.asyncio
class TestTheSplitSurface:
    async def test_every_history_action_is_a_read(self):
        domain = domain_for("manage_cost_controls")

        for action in HISTORY_ACTIONS:
            assert action in await CostControlsManagement()._get_supported_actions()
            assert domain.tool_for(action) == "get_cost_controls"

    async def test_the_read_tool_runs_list_changes(self):
        platform = _platform()
        with patch.object(CostControlsManagement, "get_client", AsyncMock(return_value=platform)):
            is_error, text, _ = await _call_through_the_boundary(
                "_register_manage_cost_controls",
                "manage_cost_controls",
                {"action": "list_changes", "control_id": "cc_1"},
                execute=True,
            )

        assert not is_error, text
        assert "Change history of budget cc_1" in text

    async def test_the_read_tool_takes_the_team_log_filters(self):
        platform = _platform()
        with patch.object(CostControlsManagement, "get_client", AsyncMock(return_value=platform)):
            is_error, text, _ = await _call_through_the_boundary(
                "_register_manage_cost_controls",
                "manage_cost_controls",
                {
                    "action": "list_control_changes",
                    **WINDOW,
                    "subject_type": "ALERT",
                    "subject_id": "anom_7",
                    "change_type": "EDITED",
                    "changed_by": "jane@acme.com",
                    "api_key_id": "5jW1GD",
                },
                execute=True,
            )

        assert not is_error, text
        assert platform.get_control_changes.await_args.kwargs["subjectId"] == "anom_7"

    async def test_the_write_tool_refuses_a_history_read_and_names_its_sibling(self):
        mcp = FastMCP("change-history-write-side")
        mcp.add_middleware(FrameworkLeakGuardMiddleware())
        await _make_registry(profile="business")._register_manage_cost_controls(mcp)

        async with Client(mcp) as client:
            result = await client.call_tool(
                "manage_cost_controls",
                {"action": "list_changes", "control_id": "cc_1"},
                raise_on_error=False,
            )

        text = "\n".join(getattr(part, "text", "") for part in result.content)
        assert result.is_error
        assert "get_cost_controls" in text


@pytest.mark.asyncio
class TestTheHelpText:
    async def test_the_capabilities_describe_each_history_action(self):
        capabilities = await CostControlsManagement()._get_tool_capabilities()
        history = next(cap for cap in capabilities if cap.name == "Change History")

        assert set(history.parameters) == set(HISTORY_ACTIONS)
        assert history.parameters["list_control_changes"]["since"].startswith("str (required")
        assert history.parameters["list_control_changes"]["until"].startswith("str (required")
        for action in HISTORY_ACTIONS:
            assert any(example.startswith(f"{action}(") for example in history.examples)
        assert any("CSV export" in limitation for limitation in history.limitations)

    async def test_get_examples_shows_each_history_action(self):
        tool = CostControlsManagement()
        result = await tool.handle_action("get_examples", {})
        text = result[0].text

        for action in HISTORY_ACTIONS:
            assert f'"action": "{action}"' in text
        assert "change_history_notes" in text

    async def test_the_schema_declares_the_team_log_filters(self):
        properties = (await CostControlsManagement()._get_input_schema())["properties"]

        for name in ("subject_type", "subject_id", "change_type", "changed_by", "api_key_id"):
            assert "list_control_changes" in properties[name]["description"]
        assert "REQUIRED for list_control_changes" in properties["since"]["description"]
        assert "REQUIRED for list_control_changes" in properties["until"]["description"]

    async def test_the_read_tool_description_mentions_the_change_history(self):
        assert "change history" in domain_for("manage_cost_controls").read_description


@pytest.mark.skipif(
    not EXCLUSIONS_FILE.exists(),
    reason="mcp-api-exclusions.yaml is internal-only and absent from the public mirror",
)
class TestTheExportDecision:
    def test_the_csv_export_is_pinned_to_the_decision_block(self):
        declared = yaml.safe_load(EXCLUSIONS_FILE.read_text(encoding="utf-8"))["decision_exclusions"]
        entry = next(item for item in declared if item["path"] == EXPORT_PATH)

        assert entry["method"] == "GET"
        assert entry["ticket"] == "BACK-5680"
        assert "Decision (BACK-5680)" in entry["anchor"]
        assert entry["decided_by"] == "Jonas Oliveira"
        assert str(entry["decided_on"]) == "2026-11-10"
        assert entry["revisit"]

    def test_the_decision_block_sits_above_the_team_log_read(self):
        source = Path(cost_controls_management.__file__).read_text(encoding="utf-8")
        block = source.index("Decision (BACK-5680)")
        handler = source.index("async def list_control_changes")

        assert 0 < handler - block < 1500
