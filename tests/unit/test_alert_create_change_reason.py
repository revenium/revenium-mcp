"""BACK-5679: an alert create carries the caller's changeReason, and only the caller's."""

from unittest.mock import AsyncMock, patch

import pytest

from src.revenium_mcp_server.alerts.anomaly_manager import AnomalyManager
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.exceptions import ValidationError
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from tests.unit.anomaly_platform_fake import FakeAnomalyPlatform
from tests.unit.test_tool_config_registry_m4 import _call_through_the_boundary

REASON = "Covers the October invoice spike"
OWNER = "owner@example.com"


def _direct_alert(**extra):
    return {
        "name": "Spend watch",
        "alertType": "THRESHOLD",
        "metricType": "TOTAL_COST",
        "operatorType": "GREATER_THAN",
        "threshold": 100,
        "notificationAddresses": [OWNER],
        **extra,
    }


def _detection_rules_alert(**extra):
    return {
        "name": "Spend watch",
        "detection_rules": [
            {"rule_type": "THRESHOLD", "metric": "total_cost", "operator": ">", "value": 5, "time_window": "15m"}
        ],
        "notificationAddresses": [OWNER],
        **extra,
    }


@pytest.fixture(autouse=True)
def no_default_slack_channel():
    with patch("src.revenium_mcp_server.config_store.get_config_value", return_value=None):
        yield


@pytest.fixture
def platform():
    return FakeAnomalyPlatform()


@pytest.fixture
def tools(platform):
    alert_tools = AlertManagement()
    alert_tools.get_client = AsyncMock(return_value=platform)
    alert_tools._post_alert_creation_prompting = AsyncMock(return_value="")
    return alert_tools


class TestTheCreateBody:
    @pytest.mark.parametrize("payload", [_direct_alert, _detection_rules_alert])
    def test_a_given_reason_is_in_the_body_of_either_shape(self, payload):
        body = AnomalyManager().prepare_create(payload(changeReason=REASON), "team-1")

        assert body["changeReason"] == REASON

    @pytest.mark.parametrize("payload", [_direct_alert, _detection_rules_alert])
    def test_the_reason_is_sent_trimmed(self, payload):
        body = AnomalyManager().prepare_create(payload(changeReason=f"  {REASON}\n"), "team-1")

        assert body["changeReason"] == REASON

    @pytest.mark.parametrize("payload", [_direct_alert, _detection_rules_alert])
    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_a_blank_reason_means_none_is_sent(self, payload, blank):
        body = AnomalyManager().prepare_create(payload(changeReason=blank), "team-1")

        assert "changeReason" not in body

    @pytest.mark.parametrize("payload", [_direct_alert, _detection_rules_alert])
    def test_without_a_reason_none_is_invented(self, payload):
        body = AnomalyManager().prepare_create(payload(), "team-1")

        assert "changeReason" not in body

    @pytest.mark.parametrize("not_text", [42, True, ["why"], {"why": "x"}])
    def test_a_reason_that_is_not_text_is_refused(self, not_text):
        with pytest.raises(ValidationError) as refusal:
            AnomalyManager().prepare_create(_direct_alert(changeReason=not_text), "team-1")

        assert refusal.value.details["field"] == "changeReason"

    @pytest.mark.parametrize("payload", [_direct_alert, _detection_rules_alert])
    def test_a_reason_over_the_limit_is_refused(self, payload):
        with pytest.raises(ToolError) as refusal:
            AnomalyManager().prepare_create(payload(changeReason="a" * 501), "team-1")

        assert refusal.value.field == "changeReason"
        assert "500" in refusal.value.message

    def test_the_limit_counts_characters_after_trimming(self):
        reason = "\U0001F600" * 500

        body = AnomalyManager().prepare_create(_direct_alert(changeReason=f"  {reason}\n"), "team-1")

        assert body["changeReason"] == reason


@pytest.mark.asyncio
class TestTheCreateActions:
    @pytest.mark.parametrize("payload", [_direct_alert, _detection_rules_alert])
    async def test_create_sends_the_reason(self, tools, platform, payload):
        await tools.handle_action("create", {"anomaly_data": payload(changeReason=REASON)})

        assert platform.created_bodies[-1]["changeReason"] == REASON

    async def test_create_with_flat_fields_beside_anomaly_data_sends_the_reason(self, tools, platform):
        await tools.handle_action(
            "create",
            {
                "anomaly_data": {"changeReason": REASON},
                "name": "Spend watch",
                "alertType": "THRESHOLD",
                "metricType": "TOTAL_COST",
                "threshold": 100,
                "email": OWNER,
            },
        )

        assert platform.created_bodies[-1]["changeReason"] == REASON

    async def test_create_with_a_reason_over_the_limit_creates_nothing(self, tools, platform):
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action(
                "create", {"anomaly_data": _direct_alert(changeReason="a" * 501)}
            )

        assert refusal.value.field == "changeReason"
        assert platform.created_bodies == []

    async def test_create_without_a_reason_sends_none(self, tools, platform):
        await tools.handle_action("create", {"anomaly_data": _direct_alert()})

        assert "changeReason" not in platform.created_bodies[-1]

    @pytest.mark.parametrize("action, extra", [("validate", {}), ("create", {"dry_run": True})])
    async def test_a_preview_refuses_a_reason_the_create_refuses_and_creates_nothing(
        self, tools, platform, action, extra
    ):
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action(action, {"anomaly_data": _direct_alert(changeReason=42), **extra})

        assert "changeReason" in refusal.value.message
        assert platform.created_bodies == []

    @pytest.mark.parametrize("action, extra", [("validate", {}), ("create", {"dry_run": True})])
    async def test_a_preview_accepts_a_reason_and_creates_nothing(self, tools, platform, action, extra):
        result = await tools.handle_action(
            action, {"anomaly_data": _direct_alert(changeReason=REASON), **extra}
        )

        assert '"valid": true' in result[0].text
        assert platform.created_bodies == []

    @pytest.mark.parametrize(
        "action, arguments",
        [
            ("create_threshold_alert", {"name": "Spike", "threshold": 100, "email": OWNER}),
            ("create_cumulative_usage_alert", {"name": "Budget", "threshold": 1000, "email": OWNER}),
            ("create_simple", {"name": "Simple", "threshold": 100, "email": OWNER}),
        ],
    )
    async def test_the_quick_creates_send_no_reason(self, tools, platform, action, arguments):
        await tools.handle_action(action, arguments)

        assert platform.created_bodies, f"{action} created nothing"
        assert "changeReason" not in platform.created_bodies[-1]


async def _call_manage_alerts(arguments, platform):
    with patch.object(AlertManagement, "get_client", AsyncMock(return_value=platform)), patch.object(
        AlertManagement, "_post_alert_creation_prompting", AsyncMock(return_value="")
    ):
        return await _call_through_the_boundary(
            "_register_manage_alerts", "manage_alerts", arguments, execute=True
        )


@pytest.mark.asyncio
class TestTheRegisteredTool:
    async def test_a_create_sends_the_reason_inside_anomaly_data(self, platform):
        is_error, text, _ = await _call_manage_alerts(
            {"action": "create", "anomaly_data": _direct_alert(changeReason=REASON)}, platform
        )

        assert not is_error, text
        assert platform.created_bodies[-1]["changeReason"] == REASON

    @pytest.mark.parametrize("action", ["create", "create_threshold_alert", "update"])
    async def test_change_reason_outside_delete_is_refused_naming_the_create_or_update_action(
        self, platform, action
    ):
        is_error, text, _ = await _call_manage_alerts(
            {"action": action, "anomaly_id": "a1", "name": "x", "change_reason": REASON}, platform
        )

        assert is_error, text
        assert "create or update action" in text
        assert "changeReason inside anomaly_data" in text
        assert platform.created_bodies == []
        assert platform.updated_bodies == []
