"""BACK-5089: an alert create naming tags is refused, because the platform's alert has none."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import validate_call

from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.registry import (
    ToolConfigurationRegistry,
)
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from tests.unit.anomaly_platform_fake import FakeAnomalyPlatform, threshold_alert

TAGS = ["mcp-test"]
CREATE_REFUSAL = "Alerts have no tags field on the platform, so a create cannot set tags. Nothing was created."
UPDATE_REFUSAL = "Alerts have no tags field on the platform, so an update cannot change tags. Nothing was updated."
AUDIT_ALERT = {
    "name": "mcp-test-alert",
    "alertType": "THRESHOLD",
    "metricType": "TOTAL_COST",
    "threshold": 999999,
    "notificationAddresses": ["mcp-test@example.com"],
}
QUICK_CREATES = {
    "create_simple": {"name": "Spend", "threshold": 100, "email": "b@example.com"},
    "create_threshold_alert": {
        "name": "Spike",
        "threshold": 100,
        "email": "b@example.com",
    },
    "create_cumulative_usage_alert": {
        "name": "Budget",
        "threshold": 100,
        "email": "b@example.com",
    },
    "create_from_text": {
        "text": "alert me when total cost exceeds 100 dollars per day"
    },
}


@pytest.fixture(autouse=True)
def no_default_slack_channel():
    with patch(
        "src.revenium_mcp_server.config_store.get_config_value", return_value=None
    ):
        yield


@pytest.fixture
def platform():
    return FakeAnomalyPlatform([threshold_alert("a1")])


@pytest.fixture
def tools(platform):
    alert_tools = AlertManagement()
    alert_tools.get_client = AsyncMock(return_value=platform)
    alert_tools._post_alert_creation_prompting = AsyncMock(return_value="")
    return alert_tools


def _assert_refused_before_any_request(refusal, platform, wording=CREATE_REFUSAL):
    assert refusal.value.field == "tags"
    assert wording in str(refusal.value)
    assert platform.created_bodies == []
    assert platform.updated_bodies == []


@pytest.mark.asyncio
class TestCreateRefusesTags:
    async def test_flat_tags_on_create_are_refused_before_any_request(
        self, tools, platform
    ):
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action("create", {**AUDIT_ALERT, "tags": TAGS})

        _assert_refused_before_any_request(refusal, platform)

    async def test_tags_inside_anomaly_data_are_refused_before_any_request(
        self, tools, platform
    ):
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action(
                "create", {"anomaly_data": {**AUDIT_ALERT, "tags": TAGS}}
            )

        _assert_refused_before_any_request(refusal, platform)

    @pytest.mark.parametrize("nested", [False, True])
    async def test_a_create_dry_run_with_tags_is_refused_the_same_way(
        self, tools, platform, nested
    ):
        alert = {**AUDIT_ALERT, "tags": TAGS}
        arguments = {"anomaly_data": alert} if nested else alert
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action("create", {**arguments, "dry_run": True})

        _assert_refused_before_any_request(refusal, platform)

    async def test_validate_with_tags_is_refused_the_same_way(self, tools, platform):
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action(
                "validate", {"anomaly_data": {**AUDIT_ALERT, "tags": TAGS}}
            )

        _assert_refused_before_any_request(refusal, platform)

    @pytest.mark.parametrize("action", sorted(QUICK_CREATES))
    async def test_a_quick_create_with_tags_gives_the_platform_reason(
        self, tools, platform, action
    ):
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action(action, {**QUICK_CREATES[action], "tags": TAGS})

        _assert_refused_before_any_request(refusal, platform)

    async def test_a_create_without_tags_is_created_as_before(self, tools, platform):
        await tools.handle_action("create", dict(AUDIT_ALERT))

        assert len(platform.created_bodies) == 1
        body = platform.created_bodies[0]
        assert body["name"] == AUDIT_ALERT["name"]
        assert "tags" not in body


@pytest.mark.asyncio
class TestUpdateKeepsItsWording:
    @pytest.mark.parametrize("nested", [False, True])
    async def test_tags_on_update_get_the_platform_reason(
        self, tools, platform, nested
    ):
        arguments = (
            {"anomaly_data": {"name": "X", "tags": TAGS}} if nested else {"tags": TAGS}
        )
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action("update", {"anomaly_id": "a1", **arguments})

        _assert_refused_before_any_request(refusal, platform, UPDATE_REFUSAL)


@pytest.mark.asyncio
class TestTagsAreNotAdvertised:
    async def test_the_input_schema_does_not_list_tags(self, tools):
        assert "tags" not in (await tools._get_input_schema())["properties"]

    async def test_the_capabilities_parameter_reference_does_not_list_tags(self, tools):
        reference = await tools.parameter_reference_block()

        assert "`tags`" not in reference[0].text


async def _arguments_the_handler_receives(**call):
    registry = ToolConfigurationRegistry(tool_config=ToolConfig.create_for_testing())
    mcp = MagicMock()
    await registry._register_manage_alerts(mcp)
    closure = validate_call(mcp.tool.call_args_list[0][0][0].__wrapped__)
    with patch(
        "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
        new=AsyncMock(return_value=[]),
    ) as execution:
        await closure(action="create", **call)
    return execution.await_args.kwargs["arguments"]


@pytest.mark.asyncio
class TestTheToolPassesTagsOnToBeRefused:
    async def test_top_level_tags_reach_the_handler(self):
        assert (await _arguments_the_handler_receives(tags=TAGS))["tags"] == TAGS

    async def test_tags_in_params_reach_the_handler(self):
        arguments = await _arguments_the_handler_receives(params={"tags": TAGS})

        assert arguments["tags"] == TAGS


@pytest.mark.asyncio
async def test_get_capabilities_says_tags_are_refused(tools):
    text = "\n".join(
        part.text for part in await tools.handle_action("get_capabilities", {})
    )

    assert (
        "Alerts have no `tags` field on the platform, so create and update refuse it"
        in text
    )
