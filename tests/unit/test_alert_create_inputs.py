"""BACK-4707: alert windows, the persist wait, refusal wording and a zero threshold."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.alerts.alert_periods import (
    PLATFORM_REFUSED_PERIODS,
    accepted_period_durations,
)
from src.revenium_mcp_server.auth import AuthConfig
from src.revenium_mcp_server.client import ReveniumAPIError, ReveniumClient
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.generated.hypercurrent_models import PeriodDuration
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from tests.unit.anomaly_platform_fake import FakeAnomalyPlatform, answer, threshold_alert

ADDRESS = "ops@example.com"


def _tools_over(platform: FakeAnomalyPlatform) -> AlertManagement:
    tools = AlertManagement()
    tools.get_client = AsyncMock(return_value=platform)
    tools._post_alert_creation_prompting = AsyncMock(return_value="")
    return tools


def _alert_with_window(period_duration: str, alert_type: str = "THRESHOLD"):
    return {
        "anomaly_data": {
            "name": f"Spend over {period_duration}",
            "alertType": alert_type,
            "metricType": "TOTAL_COST",
            "operatorType": "GREATER_THAN",
            "threshold": 1000000,
            "periodDuration": period_duration,
            "notificationAddresses": [ADDRESS],
        }
    }


@pytest.mark.asyncio
class TestAlertWindows:
    async def test_a_thirty_day_window_is_created(self):
        platform = FakeAnomalyPlatform()

        await _tools_over(platform).handle_action("create", _alert_with_window("THIRTY_DAYS"))

        assert platform.created_bodies, "the 30-day alert was not created"
        assert platform.created_bodies[-1]["periodDuration"] == "THIRTY_DAYS"

    async def test_seven_days_is_refused_naming_weekly(self):
        platform = FakeAnomalyPlatform()

        with pytest.raises(ToolError) as refusal:
            await _tools_over(platform).handle_action("create", _alert_with_window("SEVEN_DAYS"))

        assert "WEEKLY" in refusal.value.message
        assert platform.created_bodies == []

    async def test_twenty_four_hours_is_refused_naming_daily(self):
        platform = FakeAnomalyPlatform()

        with pytest.raises(ToolError) as refusal:
            await _tools_over(platform).handle_action(
                "create", _alert_with_window("TWENTY_FOUR_HOURS")
            )

        assert "DAILY" in refusal.value.message
        assert platform.created_bodies == []


def test_accepted_periods_are_the_platform_tracking_periods():
    assert set(accepted_period_durations()) == {
        "FIFTEEN_MINUTES",
        "THIRTY_MINUTES",
        "ONE_HOUR",
        "TWELVE_HOURS",
        "DAILY",
        "WEEKLY",
        "MONTHLY",
        "QUARTERLY",
        "THIRTY_DAYS",
    }
    contract = {member.value for member in PeriodDuration}
    assert set(PLATFORM_REFUSED_PERIODS) <= contract
    assert set(PLATFORM_REFUSED_PERIODS.values()) <= contract


def _alert_waiting_fifteen_minutes() -> FakeAnomalyPlatform:
    return FakeAnomalyPlatform(
        [threshold_alert("a1", triggerAfterPersistsDuration="FIFTEEN_MINUTES")]
    )


def _sent_body(platform: FakeAnomalyPlatform):
    assert platform.updated_bodies, "nothing was sent to the platform"
    return platform.updated_bodies[-1][1]


@pytest.mark.asyncio
class TestClearingThePersistWait:
    async def _clear_with(self, platform, field_name, cleared_value):
        return await _tools_over(platform).handle_action(
            "update",
            {"anomaly_id": "a1", "anomaly_data": {field_name: cleared_value}},
        )

    async def test_clearing_the_wait_by_its_short_name_sends_null(self):
        platform = _alert_waiting_fifteen_minutes()

        result = await self._clear_with(platform, "trigger_after_persists_duration", None)

        assert _sent_body(platform)["triggerAfterPersistsDuration"] is None
        assert platform.store["a1"]["triggerAfterPersistsDuration"] is None
        assert "Updated Successfully" in result[0].text

    async def test_clearing_the_wait_with_an_empty_string_sends_null(self):
        platform = _alert_waiting_fifteen_minutes()

        await self._clear_with(platform, "trigger_after_persists_duration", "")

        assert _sent_body(platform)["triggerAfterPersistsDuration"] is None
        assert platform.store["a1"]["triggerAfterPersistsDuration"] is None

    async def test_clearing_the_wait_by_its_platform_name_sends_null(self):
        """Control: the platform field name already cleared the wait before the fix."""
        platform = _alert_waiting_fifteen_minutes()

        result = await self._clear_with(platform, "triggerAfterPersistsDuration", None)

        assert _sent_body(platform)["triggerAfterPersistsDuration"] is None
        assert "Updated Successfully" in result[0].text

    @pytest.mark.parametrize(
        "required_field", ["tracking_period", "alert_type", "metric_type", "operator_type"]
    )
    async def test_clearing_a_required_field_is_refused(self, required_field):
        platform = _alert_waiting_fifteen_minutes()

        with pytest.raises(ToolError) as refusal:
            await self._clear_with(platform, required_field, None)

        assert required_field in refusal.value.message
        assert REQUIRED_UPDATE_REFUSAL in refusal.value.message
        assert platform.updated_bodies == []



@pytest.mark.asyncio
class TestClearingTheSlackLink:
    @pytest.mark.parametrize("field_name", ["slack_config_id", "slackConfigId"])
    async def test_a_null_slack_id_clears_the_link_with_an_empty_list(self, field_name):
        platform = FakeAnomalyPlatform([threshold_alert("a1", slackConfigurations=["slack-1"])])

        result = await _tools_over(platform).handle_action(
            "update", {"anomaly_id": "a1", "anomaly_data": {field_name: None}}
        )

        sent = _sent_body(platform)["slackConfigurations"]
        assert sent == []
        assert "None" not in sent
        assert platform.store["a1"]["slackConfigurations"] == []
        assert "Updated Successfully" in result[0].text


def _platform_answer(status_code: int, message: str) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.reason_phrase = "Bad Request"
    response.headers = {}
    response.text = f'{{"message": "{message}"}}'
    response.content = response.text.encode()
    response.json.return_value = {"message": message}
    return response


@pytest.mark.asyncio
async def test_a_refused_alert_value_does_not_blame_json_or_missing_fields():
    client = ReveniumClient(
        auth_config=AuthConfig(
            api_key="test-key-xyz",
            team_id="team_abc",
            base_url="https://api.test.revenium.ai",
            timeout=5.0,
            max_retries=0,
        )
    )
    refused = _platform_answer(400, "Invalid JSON format")

    with patch.object(client.client, "request", new_callable=AsyncMock, return_value=refused):
        with pytest.raises(ReveniumAPIError) as refusal:
            await client._request(
                "PUT",
                "/profitstream/v2/api/sources/ai/anomaly/abc",
                json_data={"triggerAfterPersistsDuration": "None"},
            )

    assert "JSON Format Issue" not in refusal.value.message
    assert "Ensure all required fields" not in refusal.value.message
    assert "Required fields are missing" not in refusal.value.message
    assert "Invalid JSON format" in refusal.value.message


@pytest.mark.asyncio
async def test_relative_change_examples_do_not_promise_clamping():
    result = await _tools_over(FakeAnomalyPlatform()).handle_action(
        "get_examples", {"alert_type": "relative_change"}
    )

    examples = result[0].text
    assert "RELATIVE_CHANGE" in examples or "INCREASES_BY" in examples
    assert "clamped to DAILY" not in examples


@pytest.fixture
def no_default_slack_channel():
    with patch("src.revenium_mcp_server.config_store.get_config_value", return_value=None):
        yield


def _threshold_alert_at(threshold):
    return {"name": "Any error", "metric": "ERROR_RATE", "threshold": threshold, "email": ADDRESS}


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_default_slack_channel")
class TestZeroThreshold:
    async def test_a_zero_threshold_creates_a_threshold_alert(self):
        platform = FakeAnomalyPlatform()

        await _tools_over(platform).handle_action(
            "create_threshold_alert", _threshold_alert_at(0)
        )

        assert platform.created_bodies, "the zero-threshold alert was not created"
        assert platform.created_bodies[-1]["threshold"] == 0.0

    async def test_a_zero_string_threshold_creates_a_threshold_alert(self):
        platform = FakeAnomalyPlatform()

        await _tools_over(platform).handle_action(
            "create_threshold_alert", _threshold_alert_at("0")
        )

        assert platform.created_bodies, "the zero-threshold alert was not created"
        assert platform.created_bodies[-1]["threshold"] == 0.0

    async def test_a_negative_threshold_is_refused_as_negative(self):
        platform = FakeAnomalyPlatform()

        with pytest.raises(ToolError) as refusal:
            await _tools_over(platform).handle_action(
                "create_threshold_alert", _threshold_alert_at(-5)
            )

        assert "missing" not in refusal.value.message.lower()
        assert "zero or more" in refusal.value.message
        assert platform.created_bodies == []

    async def test_a_boolean_threshold_is_refused(self):
        platform = FakeAnomalyPlatform()

        with pytest.raises(ToolError):
            await _tools_over(platform).handle_action(
                "create_threshold_alert", _threshold_alert_at(True)
            )

        assert platform.created_bodies == []

    async def test_a_zero_threshold_creates_a_budget_alert(self):
        platform = FakeAnomalyPlatform()

        await _tools_over(platform).handle_action(
            "create_cumulative_usage_alert",
            {"name": "Zero budget", "threshold": 0, "period": "monthly", "email": ADDRESS},
        )

        assert platform.created_bodies, "the zero-threshold budget alert was not created"
        assert platform.created_bodies[-1]["threshold"] == 0.0

    async def test_a_boolean_budget_threshold_is_refused(self):
        platform = FakeAnomalyPlatform()

        with pytest.raises(ToolError):
            await _tools_over(platform).handle_action(
                "create_cumulative_usage_alert",
                {"name": "Bool budget", "threshold": True, "period": "monthly", "email": ADDRESS},
            )

        assert platform.created_bodies == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_default_slack_channel")
class TestBooleanThresholdThroughTheRegisteredTool:
    """The registered signature must not turn a boolean into 1.0 before the handler sees it."""

    @staticmethod
    async def _call_registered(platform, arguments):
        from fastmcp import Client, FastMCP

        from src.revenium_mcp_server.tool_configuration.config import ToolConfig
        from src.revenium_mcp_server.tool_configuration.registry import (
            ToolConfigurationRegistry,
        )

        mcp = FastMCP("alert-bool-threshold")
        registry = ToolConfigurationRegistry(
            tool_config=ToolConfig.create_for_testing(profile="business")
        )
        await registry._register_manage_alerts(mcp)
        with patch.object(
            AlertManagement, "get_client", new=AsyncMock(return_value=platform)
        ), patch.object(
            AlertManagement, "_post_alert_creation_prompting", new=AsyncMock(return_value="")
        ):
            async with Client(mcp) as client:
                return await client.call_tool(
                    "manage_alerts", arguments, raise_on_error=False
                )

    @pytest.mark.parametrize("flag", [True, False], ids=["true", "false"])
    async def test_a_boolean_threshold_is_refused_for_a_threshold_alert(self, flag):
        platform = FakeAnomalyPlatform()

        result = await self._call_registered(
            platform, {"action": "create_threshold_alert", **_threshold_alert_at(flag)}
        )

        assert result.is_error
        assert platform.created_bodies == []

    @pytest.mark.parametrize("flag", [True, False], ids=["true", "false"])
    async def test_a_boolean_threshold_is_refused_for_a_simple_alert(self, flag):
        platform = FakeAnomalyPlatform()

        result = await self._call_registered(
            platform, {"action": "create_simple", **_threshold_alert_at(flag)}
        )

        assert result.is_error
        assert "threshold must be a number" in result.content[0].text
        assert platform.created_bodies == []

    @pytest.mark.parametrize("flag", [True, False], ids=["true", "false"])
    async def test_a_boolean_threshold_is_refused_for_a_budget_alert(self, flag):
        platform = FakeAnomalyPlatform()

        result = await self._call_registered(
            platform,
            {
                "action": "create_cumulative_usage_alert",
                "name": "Bool budget",
                "threshold": flag,
                "period": "monthly",
                "email": ADDRESS,
            },
        )

        assert result.is_error
        assert platform.created_bodies == []


REQUIRED_UPDATE_REFUSAL ="is required; send a value, or leave it out to keep the stored one"


@pytest.mark.asyncio
class TestNullAndEmptyUpdateInputs:
    """An empty required field is refused; a null or blank webhook list or percent flag changes nothing."""

    @staticmethod
    async def _preview_and_update(platform, anomaly_data):
        tools = _tools_over(platform)
        update = {"anomaly_id": "a1", "anomaly_data": anomaly_data}
        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        live = await answer(tools.handle_action("update", update))
        return dry, live

    @pytest.mark.parametrize("blank", ["", "  "], ids=["empty", "spaces"])
    @pytest.mark.parametrize(
        "field_name",
        ["alert_type", "metric_type", "operator_type", "tracking_period", "name", "periodDuration"],
    )
    async def test_an_empty_required_field_is_refused_alike_by_preview_and_update(
        self, field_name, blank
    ):
        platform = FakeAnomalyPlatform([threshold_alert("a1")])

        dry, live = await self._preview_and_update(platform, {field_name: blank})

        assert dry == live
        assert live[0] is True
        assert f"{field_name} {REQUIRED_UPDATE_REFUSAL}" in live[1]
        assert platform.updated_bodies == []

    @pytest.mark.parametrize("cleared", [None, ""], ids=["null", "blank"])
    @pytest.mark.parametrize("spelling", ["webhook_configurations", "webhookConfigurations"])
    async def test_a_null_webhook_list_changes_nothing(self, spelling, cleared):
        platform = FakeAnomalyPlatform([threshold_alert("a1", webhookConfigurations=["wh-1"])])

        dry, live = await self._preview_and_update(platform, {spelling: cleared})

        assert dry[0] is False
        assert "webhookConfigurations" not in dry[1]
        assert live[0] is False
        assert "Updated Successfully" in live[1]
        assert _sent_body(platform)["webhookConfigurations"] == ["wh-1"]
        assert platform.store["a1"]["webhookConfigurations"] == ["wh-1"]

    @pytest.mark.parametrize("cleared", [None, ""], ids=["null", "blank"])
    @pytest.mark.parametrize("stored_flag", [True, False])
    @pytest.mark.parametrize("spelling", ["is_percentage", "isPercentage"])
    async def test_a_null_percent_flag_keeps_the_stored_flag(self, spelling, stored_flag, cleared):
        platform = FakeAnomalyPlatform([threshold_alert("a1", isPercentage=stored_flag)])

        dry, live = await self._preview_and_update(platform, {spelling: cleared})

        assert dry[0] is False
        assert "isPercentage" not in dry[1]
        assert live[0] is False
        assert _sent_body(platform)["isPercentage"] is stored_flag
        assert platform.store["a1"]["isPercentage"] is stored_flag
