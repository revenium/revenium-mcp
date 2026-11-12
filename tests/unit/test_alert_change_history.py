"""BACK-5680: get_alerts reads who changed an alert, when, why and from what to what."""

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Client, FastMCP

from src.revenium_mcp_server.auth import AuthConfig
from src.revenium_mcp_server.client import ReveniumAPIError, ReveniumClient
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from src.revenium_mcp_server.common.tool_surface import domain_for
from src.revenium_mcp_server.middleware.framework_leak_guard import (
    FrameworkLeakGuardMiddleware,
)
from src.revenium_mcp_server.common.thin_tool_defaults import arguments_filled_on_every_call
from src.revenium_mcp_server.common.validation import is_blank
from src.revenium_mcp_server.tools_decomposed import alert_management
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from tests.unit.test_tool_config_registry_m4 import (
    _call_through_the_boundary,
    _get_registered_closure,
    _make_registry,
)

HISTORY_ACTIONS = ("list_changes", "get_changes_summary")

ENTRY = {
    "changeType": "EDITED",
    "changedAt": "2026-10-28T14:14:03.512Z",
    "changedBy": {
        "kind": "API_KEY",
        "display": "API key ci-bot (owner ops@acme.com)",
        "value": "ops@acme.com via API key 5jW1GD (ci-bot)",
        "apiKeyId": "5jW1GD",
        "apiKeyName": "ci-bot",
    },
    "fieldChanges": [
        {
            "field": "threshold",
            "label": "Threshold",
            "change": "CHANGED",
            "before": "100",
            "after": "150",
            "valueType": "NUMBER",
            "beforeValueType": "NUMBER",
        }
    ],
    "reason": "Threshold lowered after the October invoice",
    "relation": "SELF",
    "revision": 140223991,
    "subject": {
        "type": "ALERT",
        "id": "anom_7",
        "nameAtTheTime": "OpenAI spend alert",
        "teamId": "team_abc",
        "deleted": False,
    },
    "summary": None,
}
PAGE = {
    "_embedded": {"changes": [ENTRY, {**ENTRY, "changeType": "CREATED", "reason": None}]},
    "page": {"number": 0, "size": 20, "totalElements": 2, "totalPages": 1},
}
SUMMARY = {
    "createdAt": None,
    "createdBy": None,
    "lastChangedAt": "2026-10-28T14:14:03.512Z",
    "lastChangedBy": ENTRY["changedBy"],
    "historyStartsAt": "2026-10-22T21:03:55.120Z",
}

UNMAPPED_ROUTE = {"timestamp": "2026-11-10T12:00:00Z", "status": 404, "error": "Not Found"}


def _not_found_404(body):
    return ReveniumAPIError("HTTP 404", status_code=404, response_data={"error_data": body})


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
    async def test_an_alert_history_page_reads_the_changes_route_with_the_team(self):
        client = _client()

        await client.get_anomaly_changes("anom_7", page=1, size=5)

        client.get.assert_awaited_once_with(
            "/profitstream/v2/api/sources/ai/anomaly/anom_7/changes",
            params={"page": 1, "size": 5, "teamId": "team_abc"},
        )

    async def test_the_summary_is_unpaged(self):
        client = _client()

        await client.get_anomaly_change_summary("anom_7")

        client.get.assert_awaited_once_with(
            "/profitstream/v2/api/sources/ai/anomaly/anom_7/changes/summary",
            params={"teamId": "team_abc"},
        )

    @pytest.mark.parametrize("anomaly_id, segment", [("a/b", "a%2Fb"), (".", "%2E")])
    async def test_the_alert_id_stays_one_path_segment(self, anomaly_id, segment):
        client = _client()

        await client.get_anomaly_changes(anomaly_id)
        await client.get_anomaly_change_summary(anomaly_id)

        paths = [call.args[0] for call in client.get.await_args_list]
        assert paths == [
            f"/profitstream/v2/api/sources/ai/anomaly/{segment}/changes",
            f"/profitstream/v2/api/sources/ai/anomaly/{segment}/changes/summary",
        ]


def _platform() -> MagicMock:
    platform = MagicMock()
    platform.team_id = "team_abc"
    platform.get_anomaly_changes = AsyncMock(return_value=PAGE)
    platform.get_anomaly_change_summary = AsyncMock(return_value=SUMMARY)
    return platform


async def _act(action, arguments, platform):
    tools = AlertManagement()
    tools.get_client = AsyncMock(return_value=platform)
    result = await tools.handle_action(action, arguments)
    return result[0].text


@pytest.mark.asyncio
class TestOneAlertsHistory:
    async def test_the_page_is_rendered_entry_by_entry(self):
        platform = _platform()

        text = await _act("list_changes", {"anomaly_id": "anom_7"}, platform)

        assert text.startswith("Change history of alert anom_7. Found 2 of 2 changes")
        assert "edited by API key ci-bot (owner ops@acme.com)" in text
        assert "Reason: Threshold lowered after the October invoice" in text
        assert "Threshold (threshold): 100 -> 150" in text
        assert text.count("Reason:") == 1
        platform.get_anomaly_changes.assert_awaited_once_with("anom_7", page=0, size=20)

    async def test_alert_id_names_the_alert_too(self):
        platform = _platform()

        await _act("list_changes", {"alert_id": "anom_7", "page": 2, "size": 10}, platform)

        platform.get_anomaly_changes.assert_awaited_once_with("anom_7", page=2, size=10)

    async def test_an_empty_history_is_an_answer(self):
        platform = _platform()
        platform.get_anomaly_changes.return_value = {
            "page": {"number": 0, "size": 20, "totalElements": 0, "totalPages": 0}
        }

        text = await _act("list_changes", {"anomaly_id": "anom_7"}, platform)

        assert text == "Change history of alert anom_7. Found 0 changes; the platform reports none."

    async def test_the_summary_names_who_changed_it_last(self):
        platform = _platform()

        text = await _act("get_changes_summary", {"anomaly_id": "anom_7"}, platform)

        assert text.startswith("Change summary of alert anom_7:")
        assert "- Created: before change history began" in text
        assert "- Last changed: 2026-10-28T14:14:03.512Z by API key ci-bot" in text
        platform.get_anomaly_change_summary.assert_awaited_once_with("anom_7")

    @pytest.mark.parametrize("action", HISTORY_ACTIONS)
    async def test_a_missing_alert_id_is_refused(self, action):
        platform = _platform()

        with pytest.raises(ToolError) as refusal:
            await _act(action, {}, platform)

        assert refusal.value.field == "anomaly_id"
        platform.get_anomaly_changes.assert_not_awaited()

    async def test_a_page_size_over_the_platform_cap_is_refused(self):
        platform = _platform()

        with pytest.raises(ToolError):
            await _act("list_changes", {"anomaly_id": "anom_7", "size": 500}, platform)

        platform.get_anomaly_changes.assert_not_awaited()

    @pytest.mark.parametrize("action", HISTORY_ACTIONS)
    async def test_the_platforms_404_is_the_alert_not_being_found(self, action):
        platform = _platform()
        for read in (platform.get_anomaly_changes, platform.get_anomaly_change_summary):
            read.side_effect = _not_found_404(
                {**UNMAPPED_ROUTE, "message": "Alert not found for id: anom_gone"}
            )

        with pytest.raises(ToolError) as refusal:
            await _act(action, {"anomaly_id": "anom_gone"}, platform)

        assert refusal.value.error_code == "ANOMALY_NOT_FOUND"
        assert "anom_gone" in refusal.value.message

    @pytest.mark.parametrize("action", HISTORY_ACTIONS)
    async def test_a_platform_without_the_route_is_not_a_missing_alert(self, action):
        platform = _platform()
        for read in (platform.get_anomaly_changes, platform.get_anomaly_change_summary):
            read.side_effect = _not_found_404(UNMAPPED_ROUTE)

        with pytest.raises(ToolError) as refusal:
            await _act(action, {"anomaly_id": "anom_7"}, platform)

        assert refusal.value.error_code == ErrorCodes.RESOURCE_UNAVAILABLE
        assert "does not offer change history" in refusal.value.message
        assert "not found" not in refusal.value.message.lower()

    @pytest.mark.parametrize("action", HISTORY_ACTIONS)
    @pytest.mark.parametrize("status", [400, 403, 500])
    async def test_any_other_failure_keeps_the_platforms_answer(self, action, status):
        platform = _platform()
        for read in (platform.get_anomaly_changes, platform.get_anomaly_change_summary):
            read.side_effect = ReveniumAPIError("Forbidden", status_code=status)

        with pytest.raises(ReveniumAPIError) as failure:
            await _act(action, {"anomaly_id": "anom_7"}, platform)

        assert failure.value.status_code == status
        assert failure.value.message == "Forbidden"

    @pytest.mark.parametrize("action", HISTORY_ACTIONS)
    @pytest.mark.parametrize(
        "narrowing",
        [{"filters": {"start": "2026-10-01"}}, {"query": "changes last week"}],
        ids=["filters", "query"],
    )
    async def test_a_narrowing_is_refused_and_the_team_log_is_named(self, action, narrowing):
        platform = _platform()

        with pytest.raises(ToolError) as refusal:
            await _act(action, {"anomaly_id": "anom_7", **narrowing}, platform)

        assert refusal.value.field == next(iter(narrowing))
        assert "list_control_changes" in refusal.value.message
        assert "subject_type='ALERT'" in refusal.value.message
        assert "last week" not in str(refusal.value)
        platform.get_anomaly_changes.assert_not_awaited()
        platform.get_anomaly_change_summary.assert_not_awaited()


async def _declared_arguments():
    closure = await _get_registered_closure(
        _make_registry(profile="business"), "_register_manage_alerts"
    )
    # params is the bag merge_params_argument folds into the named arguments; it never
    # reaches the handler under its own name.
    return set(inspect.signature(closure).parameters) - {"params"}


async def _through_the_read_tool(call, platform):
    with patch.object(AlertManagement, "get_client", AsyncMock(return_value=platform)):
        return await _call_through_the_boundary(
            "_register_manage_alerts", "manage_alerts", call, execute=True
        )


@pytest.mark.asyncio
class TestNoHistoryReadDropsAnArgument:
    @pytest.mark.parametrize("action", HISTORY_ACTIONS)
    async def test_every_argument_the_tool_declares_is_read_or_refused_by_each_history_read(
        self, action
    ):
        declared = await _declared_arguments()
        reads = alert_management.HISTORY_READ_ARGUMENTS[action]
        sent_on_every_call = arguments_filled_on_every_call("manage_alerts", action)

        for argument in sorted(declared - set(reads) - set(sent_on_every_call)):
            platform = _platform()

            with pytest.raises(ToolError) as refusal:
                await _act(action, {"anomaly_id": "anom_7", argument: "x"}, platform)

            assert refusal.value.field == argument, (action, argument)
            assert "list_control_changes" in refusal.value.message, (action, argument)
            platform.get_anomaly_changes.assert_not_awaited()
            platform.get_anomaly_change_summary.assert_not_awaited()

    async def test_what_the_history_reads_take_is_declared_by_the_tool(self):
        declared = await _declared_arguments()

        for action, reads in alert_management.HISTORY_READ_ARGUMENTS.items():
            assert set(reads) <= declared
            assert arguments_filled_on_every_call("manage_alerts", action) <= declared

    @pytest.mark.parametrize("action", HISTORY_ACTIONS)
    async def test_the_registry_adds_nothing_a_history_read_would_refuse(self, action):
        _, _, reached = await _call_through_the_boundary(
            "_register_manage_alerts", "manage_alerts", {"action": action, "anomaly_id": "anom_7"}
        )
        added = set(reached) - {"anomaly_id"}
        sent_on_every_call = arguments_filled_on_every_call("manage_alerts", action)

        assert sent_on_every_call <= added
        assert all(is_blank(reached[name]) for name in added - sent_on_every_call)

    @pytest.mark.parametrize("action", HISTORY_ACTIONS)
    async def test_a_refused_history_read_never_gets_a_client(self, action):
        tools = AlertManagement()
        tools.get_client = AsyncMock(return_value=_platform())

        with pytest.raises(ToolError):
            await tools.handle_action(action, {"anomaly_id": "anom_7", "query": "last week"})

        tools.get_client.assert_not_awaited()

    async def test_an_action_listed_as_a_history_read_is_refused_before_routing(
        self, monkeypatch
    ):
        monkeypatch.setitem(alert_management.HISTORY_READ_ARGUMENTS, "get_status", ("anomaly_id",))
        tools = AlertManagement()
        tools.get_client = AsyncMock(return_value=_platform())

        with pytest.raises(ToolError) as refusal:
            await tools.handle_action("get_status", {"anomaly_id": "anom_7", "query": "last week"})

        assert refusal.value.field == "query"
        tools.get_client.assert_not_awaited()

    @pytest.mark.parametrize(
        "call",
        [
            {"action": "list_changes", "anomaly_id": "anom_7"},
            {"action": "list_changes", "anomaly_id": "anom_7", "page": 1, "size": 5},
            {"action": "list_changes", "params": {"alert_id": "anom_7", "page": "1"}},
            {"action": "list_changes", "anomaly_id": "anom_7", "query": "", "filters": {}},
            {"action": "get_changes_summary", "anomaly_id": "anom_7", "page": 0, "size": 20},
        ],
        ids=["plain", "paged", "params-alias", "blank-narrowings", "summary-with-paging"],
    )
    async def test_an_ordinary_history_call_through_the_read_tool_is_answered(self, call):
        is_error, text, _ = await _through_the_read_tool(call, _platform())

        assert not is_error, text
        assert "of alert anom_7" in text

    @pytest.mark.parametrize("argument", ["provider", "alert_type", "metric", "period", "now"])
    @pytest.mark.parametrize("inside_params", [False, True], ids=["top-level", "params"])
    async def test_an_alert_narrowing_through_the_read_tool_is_refused(
        self, argument, inside_params
    ):
        platform = _platform()
        sent = {"anomaly_id": "anom_7", argument: "OPENAI"}
        call = {"action": "list_changes", **({"params": sent} if inside_params else sent)}

        is_error, text, _ = await _through_the_read_tool(call, platform)

        assert is_error
        assert f"does not read {argument}" in text
        assert "OPENAI" not in text
        platform.get_anomaly_changes.assert_not_awaited()


@pytest.mark.asyncio
class TestTheSplitSurface:
    async def test_both_history_actions_are_reads(self):
        domain = domain_for("manage_alerts")

        for action in HISTORY_ACTIONS:
            assert action in await AlertManagement()._get_supported_actions()
            assert domain.tool_for(action) == "get_alerts"

    async def test_the_read_tool_runs_list_changes(self):
        platform = _platform()
        with patch.object(AlertManagement, "get_client", AsyncMock(return_value=platform)):
            is_error, text, _ = await _call_through_the_boundary(
                "_register_manage_alerts",
                "manage_alerts",
                {"action": "list_changes", "params": {"anomaly_id": "anom_7"}},
                execute=True,
            )

        assert not is_error, text
        assert "Change history of alert anom_7" in text

    @pytest.mark.parametrize("argument", ["since", "until", "changed_by", "change_type", "subject_id"])
    @pytest.mark.parametrize("inside_params", [False, True], ids=["top-level", "params"])
    async def test_the_read_tool_refuses_a_team_log_argument_before_any_read(
        self, argument, inside_params
    ):
        platform = _platform()
        sent = {"anomaly_id": "anom_7", argument: "x"}
        call = {"action": "list_changes", **({"params": sent} if inside_params else sent)}
        with patch.object(AlertManagement, "get_client", AsyncMock(return_value=platform)):
            is_error, text, _ = await _call_through_the_boundary(
                "_register_manage_alerts", "manage_alerts", call, execute=True
            )

        assert is_error
        assert argument in text
        platform.get_anomaly_changes.assert_not_awaited()

    async def test_the_write_tool_refuses_a_history_read_and_names_its_sibling(self):
        mcp = FastMCP("alert-change-history-write-side")
        mcp.add_middleware(FrameworkLeakGuardMiddleware())
        await _make_registry(profile="business")._register_manage_alerts(mcp)

        async with Client(mcp) as client:
            result = await client.call_tool(
                "manage_alerts",
                {"action": "get_changes_summary", "anomaly_id": "anom_7"},
                raise_on_error=False,
            )

        text = "\n".join(getattr(part, "text", "") for part in result.content)
        assert result.is_error
        assert "get_alerts" in text


@pytest.mark.asyncio
class TestTheHelpText:
    async def test_the_capabilities_describe_each_history_action(self):
        capabilities = await AlertManagement()._get_tool_capabilities()
        history = next(cap for cap in capabilities if cap.name == "Change History")

        assert set(history.parameters) == set(HISTORY_ACTIONS)
        for action in HISTORY_ACTIONS:
            assert any(example.startswith(f"{action}(") for example in history.examples)
        assert any("list_control_changes" in limitation for limitation in history.limitations)

    async def test_get_capabilities_and_get_examples_show_the_history_reads(self):
        tools = AlertManagement(ucm_helper=None)

        capabilities = "\n".join(part.text for part in await tools.handle_action("get_capabilities", {}))
        examples = (await tools.handle_action("get_examples", {}))[0].text

        for text in (capabilities, examples):
            assert 'list_changes(anomaly_id="anom_123")' in text
            assert 'get_changes_summary(anomaly_id="anom_123")' in text

    async def test_the_unknown_action_answer_lists_the_history_reads(self):
        with pytest.raises(ToolError) as refusal:
            await _act("no_such_action", {}, _platform())

        assert refusal.value.examples["change_history"] == list(HISTORY_ACTIONS)

    async def test_the_read_tool_description_mentions_who_changed_an_alert(self):
        assert "who changed" in domain_for("manage_alerts").read_description

    async def test_the_schema_names_the_history_reads_on_anomaly_id(self):
        properties = (await AlertManagement()._get_input_schema())["properties"]

        assert "list_changes" in properties["anomaly_id"]["description"]
        assert "get_changes_summary" in properties["anomaly_id"]["description"]


class TestTheTeamLogPointerNamesTheRightProfile:
    def test_get_cost_controls_is_in_the_business_profile_and_not_the_starter_one(self):
        from src.revenium_mcp_server.tool_configuration.profiles import PROFILE_DEFINITIONS
        from src.revenium_mcp_server.tools_decomposed.alert_management import (
            ONE_ALERT_IN_A_WINDOW,
            TEAM_CHANGE_LOG_POINTER,
            TEAM_LOG_TOOL_PROFILE_NOTE,
        )

        assert "get_cost_controls" in PROFILE_DEFINITIONS["business"]
        assert "get_cost_controls" not in PROFILE_DEFINITIONS["starter"]
        assert TEAM_LOG_TOOL_PROFILE_NOTE in TEAM_CHANGE_LOG_POINTER
        assert TEAM_LOG_TOOL_PROFILE_NOTE in ONE_ALERT_IN_A_WINDOW
