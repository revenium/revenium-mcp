"""BACK-5679: an alert delete records the caller's reason on the change history, and only theirs."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.auth import AuthConfig
from src.revenium_mcp_server.client import ReveniumAPIError, ReveniumClient
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from src.revenium_mcp_server.json_schema_validator import JSONSchemaValidator
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from tests.unit.anomaly_platform_fake import FakeAnomalyPlatform, threshold_alert
from tests.unit.test_tool_config_registry_m4 import _call_through_the_boundary

REASON = "Retired and replaced by a budget"
ALERT_PATH = "/profitstream/v2/api/sources/ai/anomaly/anom_5"


def _client() -> ReveniumClient:
    client = ReveniumClient(
        auth_config=AuthConfig(
            api_key="test_key_12345",
            team_id="team_abc",
            base_url="https://api.test.revenium.ai",
            timeout=10.0,
        )
    )
    client.delete = AsyncMock(return_value={})
    return client


@pytest.mark.asyncio
class TestTheClientDelete:
    async def test_a_given_reason_is_sent_as_the_change_reason_query(self):
        client = _client()

        await client.delete_anomaly("anom_5", change_reason=REASON)

        client.delete.assert_awaited_once_with(
            ALERT_PATH, params={"teamId": "team_abc", "changeReason": REASON}
        )

    @pytest.mark.parametrize("change_reason", [None, "", "   ", "\n\t"])
    async def test_no_reason_sends_only_the_team(self, change_reason):
        client = _client()

        await client.delete_anomaly("anom_5", change_reason=change_reason)

        client.delete.assert_awaited_once_with(ALERT_PATH, params={"teamId": "team_abc"})

    async def test_the_reason_is_sent_trimmed(self):
        client = _client()

        await client.delete_anomaly("anom_5", change_reason=f"  {REASON} ")

        client.delete.assert_awaited_once_with(
            ALERT_PATH, params={"teamId": "team_abc", "changeReason": REASON}
        )

    async def test_a_delete_by_id_alone_sends_only_the_team(self):
        client = _client()

        await client.delete_anomaly("anom_5")

        client.delete.assert_awaited_once_with(ALERT_PATH, params={"teamId": "team_abc"})


def _platform() -> MagicMock:
    platform = MagicMock()
    platform.team_id = "team_test"
    platform.delete_anomaly = AsyncMock(return_value={})
    return platform


def _tools_over(platform: MagicMock) -> AlertManagement:
    tools = AlertManagement()
    tools.get_client = AsyncMock(return_value=platform)
    return tools


@pytest.mark.asyncio
class TestTheDeleteAction:
    async def test_the_reason_reaches_the_client(self):
        platform = _platform()

        result = await _tools_over(platform).handle_action(
            "delete",
            {"resource_type": "anomalies", "anomaly_id": "anom_5", "change_reason": REASON},
        )

        assert "Deleted Successfully" in result[0].text
        platform.delete_anomaly.assert_awaited_once_with("anom_5", change_reason=REASON)

    async def test_without_a_reason_none_is_passed(self):
        platform = _platform()

        await _tools_over(platform).handle_action(
            "delete", {"resource_type": "anomalies", "anomaly_id": "anom_5"}
        )

        platform.delete_anomaly.assert_awaited_once_with("anom_5", change_reason=None)

    @pytest.mark.parametrize(
        "status, arguments",
        [
            (400, {}),
            (403, {}),
            (404, {}),
            (403, {"change_reason": REASON}),
            (404, {"change_reason": REASON}),
            (400, {"change_reason": "   "}),
        ],
    )
    async def test_a_refusal_that_names_one_cause_passes_the_platform_error_through(
        self, status, arguments
    ):
        platform = _platform()
        platform.delete_anomaly.side_effect = ReveniumAPIError("refused", status_code=status)

        with pytest.raises(ReveniumAPIError) as refusal:
            await _tools_over(platform).handle_action(
                "delete", {"resource_type": "anomalies", "anomaly_id": "anom_5", **arguments}
            )

        assert refusal.value.status_code == status

    async def test_a_400_with_a_reason_names_both_causes_without_the_platforms_words(self):
        platform = _platform()
        platform.delete_anomaly.side_effect = ReveniumAPIError(
            "changeReason is reserved; write a different reason", status_code=400
        )

        with pytest.raises(ToolError) as refusal:
            await _tools_over(platform).handle_action(
                "delete",
                {"resource_type": "anomalies", "anomaly_id": "anom_5", "change_reason": REASON},
            )

        message = refusal.value.message
        assert "'anom_5' was not deleted" in message
        assert "no accessible alert has this id" in message
        assert "refused the change reason" in message
        assert "reserved" not in str(refusal.value.__dict__)
        assert refusal.value.error_code == ErrorCodes.INVALID_VALUE
        assert refusal.value.field == "anomaly_id"

    async def test_a_400_for_a_malformed_id_with_a_reason_does_not_quote_the_id_error(self):
        platform = _platform()
        platform.delete_anomaly.side_effect = ReveniumAPIError(
            "Failed to decode hashed Id: [anom_5]", status_code=400
        )

        with pytest.raises(ToolError) as refusal:
            await _tools_over(platform).handle_action(
                "delete",
                {"resource_type": "anomalies", "anomaly_id": "anom_5", "change_reason": REASON},
            )

        assert "no accessible alert has this id" in refusal.value.message
        assert "decode" not in refusal.value.message

    async def test_a_reason_over_the_limit_is_refused_before_any_request(self):
        platform = _platform()

        with pytest.raises(ToolError) as refusal:
            await _tools_over(platform).handle_action(
                "delete",
                {"resource_type": "anomalies", "anomaly_id": "anom_5", "change_reason": "a" * 501},
            )

        assert refusal.value.field == "change_reason"
        assert "500" in refusal.value.message
        platform.delete_anomaly.assert_not_awaited()

    async def test_the_limit_counts_characters_after_trimming(self):
        platform = _platform()
        reason = "\U0001F600" * 500

        await _tools_over(platform).handle_action(
            "delete",
            {"resource_type": "anomalies", "anomaly_id": "anom_5", "change_reason": f"  {reason}\n"},
        )

        platform.delete_anomaly.assert_awaited_once_with("anom_5", change_reason=reason)


def _platform_with_alerts() -> FakeAnomalyPlatform:
    return FakeAnomalyPlatform([threshold_alert("a1"), threshold_alert("a2")])


@pytest.mark.asyncio
class TestClearAll:
    async def test_the_reason_is_sent_with_every_delete(self):
        platform = _platform_with_alerts()

        result = await _tools_over(platform).handle_action(
            "clear_all", {"resource_type": "anomalies", "change_reason": f" {REASON} "}
        )

        assert "Cleared Successfully" in result[0].text
        assert platform.deleted_ids == ["a1", "a2"]
        assert platform.deleted_reasons == [REASON, REASON]

    @pytest.mark.parametrize("arguments", [{}, {"change_reason": "  "}])
    async def test_without_a_reason_none_is_sent(self, arguments):
        platform = _platform_with_alerts()

        await _tools_over(platform).handle_action(
            "clear_all", {"resource_type": "anomalies", **arguments}
        )

        assert platform.deleted_reasons == [None, None]

    async def test_a_400_on_a_delete_with_a_reason_names_both_causes_without_the_platforms_words(
        self,
    ):
        platform = FakeAnomalyPlatform(
            [threshold_alert("a1"), threshold_alert("a2")],
            refused_deletes={
                "a1": ReveniumAPIError(
                    "changeReason is reserved; write a different reason", status_code=400
                )
            },
        )

        result = await _tools_over(platform).handle_action(
            "clear_all", {"resource_type": "anomalies", "change_reason": REASON}
        )

        text = result[0].text
        assert "Partly Cleared" in text
        refusal_line = next(line for line in text.splitlines() if "(a1)" in line)
        assert "no accessible alert has this id" in refusal_line
        assert "refused the change reason" in refusal_line
        assert "reserved;" not in text
        assert platform.deleted_ids == ["a2"]

    @pytest.mark.parametrize(
        "status, arguments",
        [(400, {}), (400, {"change_reason": "  "}), (403, {"change_reason": REASON})],
    )
    async def test_a_refusal_that_names_one_cause_keeps_the_platforms_reason(
        self, status, arguments
    ):
        platform = FakeAnomalyPlatform(
            [threshold_alert("a1"), threshold_alert("a2")],
            refused_deletes={"a1": ReveniumAPIError("Failed to decode hashed Id", status_code=status)},
        )

        result = await _tools_over(platform).handle_action(
            "clear_all", {"resource_type": "anomalies", **arguments}
        )

        refusal_line = next(line for line in result[0].text.splitlines() if "(a1)" in line)
        assert "Failed to decode hashed Id" in refusal_line
        assert "refused the change reason" not in refusal_line

    async def test_a_reason_over_the_limit_is_refused_before_the_alerts_are_read(self):
        platform = _platform_with_alerts()

        with pytest.raises(ToolError) as refusal:
            await _tools_over(platform).handle_action(
                "clear_all", {"resource_type": "anomalies", "change_reason": "a" * 501}
            )

        assert refusal.value.field == "change_reason"
        assert platform.list_calls == []
        assert platform.deleted_ids == []


async def _call_manage_alerts(arguments, platform):
    with patch.object(AlertManagement, "get_client", AsyncMock(return_value=platform)):
        return await _call_through_the_boundary(
            "_register_manage_alerts", "manage_alerts", arguments, execute=True
        )


@pytest.mark.asyncio
class TestTheRegisteredTool:
    async def test_change_reason_is_accepted_at_the_top_level_of_a_delete(self):
        platform = _platform()

        is_error, text, _ = await _call_manage_alerts(
            {"action": "delete", "anomaly_id": "anom_5", "change_reason": REASON}, platform
        )

        assert not is_error, text
        platform.delete_anomaly.assert_awaited_once_with("anom_5", change_reason=REASON)

    async def test_change_reason_is_accepted_inside_params(self):
        platform = _platform()

        is_error, text, _ = await _call_manage_alerts(
            {"action": "delete", "params": {"anomaly_id": "anom_5", "change_reason": REASON}},
            platform,
        )

        assert not is_error, text
        platform.delete_anomaly.assert_awaited_once_with("anom_5", change_reason=REASON)

    @pytest.mark.parametrize("not_text", [False, 42, ["why"]])
    async def test_a_change_reason_inside_params_that_is_not_text_is_refused(self, not_text):
        platform = _platform()

        is_error, text, _ = await _call_manage_alerts(
            {"action": "delete", "params": {"anomaly_id": "anom_5", "change_reason": not_text}},
            platform,
        )

        assert is_error, text
        assert "change_reason must be a string" in text
        platform.delete_anomaly.assert_not_awaited()

    async def test_change_reason_is_accepted_on_clear_all(self):
        platform = _platform_with_alerts()

        is_error, text, _ = await _call_manage_alerts(
            {"action": "clear_all", "change_reason": REASON}, platform
        )

        assert not is_error, text
        assert platform.deleted_reasons == [REASON, REASON]

    async def test_change_reason_on_an_update_is_refused_before_anything_is_sent(self):
        platform = _platform()
        platform.get_anomaly_by_id = AsyncMock()
        platform.update_anomaly = AsyncMock()

        is_error, text, _ = await _call_manage_alerts(
            {"action": "update", "anomaly_id": "anom_5", "name": "x", "change_reason": REASON},
            platform,
        )

        assert is_error, text
        assert "change_reason" in text
        assert "changeReason" in text
        platform.update_anomaly.assert_not_awaited()


class TestTheAlertSchemasDocumentChangeReason:
    @pytest.mark.asyncio
    async def test_the_input_schema_declares_change_reason_inside_anomaly_data(self):
        anomaly_data = (await AlertManagement()._get_input_schema())["properties"]["anomaly_data"]

        change_reason = anomaly_data["properties"]["changeReason"]
        assert change_reason["maxLength"] == 500
        assert "never returned" in change_reason["description"]
        assert "changes nothing" in change_reason["description"]

    def test_the_validator_schema_declares_change_reason_inside_anomaly_data(self):
        schema = JSONSchemaValidator().schemas["manage_alerts"]
        change_reason = schema["properties"]["anomaly_data"]["properties"]["changeReason"]

        assert change_reason["maxLength"] == 500
        assert "never returned" in change_reason["description"]

    @pytest.mark.asyncio
    async def test_the_capabilities_name_change_reason_on_create_and_update(self):
        capabilities = await AlertManagement(ucm_helper=None)._get_tool_capabilities()
        crud = next(cap for cap in capabilities if cap.name == "AI Anomaly Detection")

        for action in ("create", "update"):
            assert "changeReason" in crud.parameters[action]["anomaly_data"]


@pytest.mark.asyncio
async def test_get_capabilities_lists_change_reason_as_a_delete_argument():
    result = await AlertManagement(ucm_helper=None).handle_action("get_capabilities", {})

    reference = "\n".join(part.text for part in result).split("## Parameters", 1)[-1]
    assert "- `change_reason` (string) - delete and clear_all only:" in reference


@pytest.mark.asyncio
async def test_the_capabilities_list_change_reason_on_clear_all():
    capabilities = await AlertManagement(ucm_helper=None)._get_tool_capabilities()
    crud = next(cap for cap in capabilities if cap.name == "AI Anomaly Detection")

    assert "change_reason" in crud.parameters["clear_all"]
