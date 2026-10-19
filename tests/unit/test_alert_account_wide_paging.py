"""BACK-4644: the account-wide alert actions and the status summary reach every alert."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.alerts.anomaly_inventory import ANOMALY_PAGE_SIZE
from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.registry import ToolConfigurationRegistry
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from tests.unit.anomaly_platform_fake import FakeAnomalyPlatform, threshold_alert

ALERT_COUNT = 1200


def _platform(enabled: bool = True, **options) -> FakeAnomalyPlatform:
    return FakeAnomalyPlatform(
        [threshold_alert(f"{index:05d}", enabled=enabled) for index in range(ALERT_COUNT)],
        **options,
    )


def _tools_over(platform: FakeAnomalyPlatform) -> AlertManagement:
    tools = AlertManagement()
    tools.get_client = AsyncMock(return_value=platform)
    return tools


def _enabled_count(platform: FakeAnomalyPlatform) -> int:
    return sum(1 for alert in platform.store.values() if alert["enabled"])


@pytest.mark.asyncio
class TestEveryAlertIsReached:
    async def test_disable_all_leaves_none_enabled(self):
        platform = _platform(enabled=True)

        result = await _tools_over(platform).handle_action("disable_all", {"confirm": True})

        assert _enabled_count(platform) == 0
        text = result[0].text
        assert "Disable All Alerts - Complete" in text
        assert "**Total Alerts:** 1200" in text
        assert "**Disabled:** 1200" in text
        assert len(platform.list_calls) == ALERT_COUNT // ANOMALY_PAGE_SIZE

    async def test_enable_all_leaves_none_disabled(self):
        platform = _platform(enabled=False)

        result = await _tools_over(platform).handle_action("enable_all", {"confirm": True})

        assert _enabled_count(platform) == ALERT_COUNT
        assert "**Enabled:** 1200" in result[0].text

    async def test_clear_all_leaves_no_alert(self):
        platform = _platform()

        result = await _tools_over(platform).handle_action("clear_all", {"confirm": True})

        assert platform.store == {}
        assert len(platform.deleted_ids) == ALERT_COUNT
        assert "**Deleted:** 1200 of 1200 anomalies" in result[0].text
        assert "Anomalies Cleared Successfully" in result[0].text

    async def test_status_counts_match_the_platform_total(self):
        platform = _platform(enabled=True)
        for alert_id in list(platform.store)[:1000]:
            platform.store[alert_id]["enabled"] = False

        result = await _tools_over(platform).handle_action("get_status", {})

        text = result[0].text
        assert "**Total Alerts:** 1200" in text
        assert "**Enabled:** 200" in text
        assert "**Disabled:** 1000" in text


@pytest.mark.asyncio
class TestAnActionThatStopsEarlySaysSo:
    async def test_disable_all_reports_how_many_of_the_total_it_covered(self):
        platform = _platform(enabled=True, failing_list_page=2)

        result = await _tools_over(platform).handle_action("disable_all", {"confirm": True})

        text = result[0].text
        assert "Complete" not in text
        assert "Disable All Alerts - Partial" in text
        assert "read 200 of 1200 alerts" in text
        assert _enabled_count(platform) == 1000

    async def test_status_reports_partial_counts(self):
        platform = _platform(failing_list_page=1)

        result = await _tools_over(platform).handle_action("get_status", {})

        assert "read 100 of 1200 alerts" in result[0].text

    async def test_clear_all_is_not_worded_as_success_when_partial(self):
        platform = _platform(failing_list_page=3)

        result = await _tools_over(platform).handle_action("clear_all", {"confirm": True})

        text = result[0].text
        assert "Cleared Successfully" not in text
        assert "read 300 of 1200 alerts" in text
        assert len(platform.store) == 900


ACCOUNT_WIDE_ACTIONS = ["clear_all", "enable_all", "disable_all"]
NOT_AN_EXPLICIT_YES = ["null", "undefined", "none", "n", "y", "", "maybe", " ", False, "false"]
EXPLICIT_YES = [True, "true", "yes", " yes ", "1"]


async def _registered_manage_alerts(platform: FakeAnomalyPlatform):
    """The manage_alerts closure as registered, with execution routed to the fake platform."""
    registry = ToolConfigurationRegistry(
        tool_config=ToolConfig.create_for_testing(
            profile="starter", custom_overrides={}, tool_enabled={}
        )
    )
    mcp = MagicMock()
    await registry._register_manage_alerts(mcp)
    closure = mcp.tool.return_value.call_args[0][0]

    async def pass_through(tool_name, action, arguments, tool_class, **_kwargs):
        tools = tool_class()
        tools.get_client = AsyncMock(return_value=platform)
        return await tools.handle_action(action, arguments)

    return closure, pass_through


def _two_alerts(action: str) -> FakeAnomalyPlatform:
    enabled = action != "enable_all"
    return FakeAnomalyPlatform(
        [threshold_alert("a1", enabled=enabled), threshold_alert("a2", enabled=enabled)]
    )


@pytest.mark.asyncio
class TestAnAccountWideActionNeedsAnExplicitYes:
    @pytest.mark.parametrize("action", ACCOUNT_WIDE_ACTIONS)
    @pytest.mark.parametrize(
        "call",
        [{"confirm": value} for value in NOT_AN_EXPLICIT_YES]
        + [{"params": {"confirm": "null"}}, {"params": {"confirm": 1}}],
        ids=[repr(value) for value in NOT_AN_EXPLICIT_YES] + ["params-null", "params-int-1"],
    )
    async def test_a_placeholder_or_unrecognised_confirm_is_held_and_sends_nothing(
        self, action, call
    ):
        platform = _two_alerts(action)
        enabled_before = {key: alert["enabled"] for key, alert in platform.store.items()}
        closure, pass_through = await _registered_manage_alerts(platform)

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            side_effect=pass_through,
        ):
            result = await closure(action=action, **call)

        assert "Confirmation Required" in result[0].text
        assert platform.list_calls == []
        assert platform.deleted_ids == []
        assert platform.updated_bodies == []
        assert platform.read_ids == []
        assert {key: alert["enabled"] for key, alert in platform.store.items()} == enabled_before

    @pytest.mark.parametrize("action", ACCOUNT_WIDE_ACTIONS)
    @pytest.mark.parametrize("confirm", EXPLICIT_YES, ids=repr)
    async def test_an_explicit_yes_runs_the_action(self, action, confirm):
        platform = _two_alerts(action)
        closure, pass_through = await _registered_manage_alerts(platform)

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            side_effect=pass_through,
        ):
            result = await closure(action=action, confirm=confirm)

        text = result[0].text
        assert "Confirmation Required" not in text
        if action == "clear_all":
            assert platform.store == {}
            assert "**Deleted:** 2 of 2 anomalies" in text
        elif action == "enable_all":
            assert all(alert["enabled"] for alert in platform.store.values())
        else:
            assert not any(alert["enabled"] for alert in platform.store.values())
