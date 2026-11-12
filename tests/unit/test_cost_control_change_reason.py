"""BACK-5681: a budget delete records the caller's reason, and control_data documents the history fields."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.auth import AuthConfig
from src.revenium_mcp_server.client import ReveniumAPIError, ReveniumClient
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from src.revenium_mcp_server.tools_decomposed.cost_controls_management import (
    CostControlsManagement,
    CostControlsManager,
)
from tests.unit.test_tool_config_registry_m4 import _call_through_the_boundary

REASON = "Replaced by the department budget"
CONTROL_PATH = "/profitstream/v2/api/ai/cost-controls/cc_99"


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

        await client.delete_cost_control("cc_99", change_reason=REASON)

        client.delete.assert_awaited_once_with(
            CONTROL_PATH, params={"teamId": "team_abc", "changeReason": REASON}
        )

    @pytest.mark.parametrize("change_reason", [None, "", "   ", "\n\t"])
    async def test_no_reason_sends_only_the_team(self, change_reason):
        client = _client()

        await client.delete_cost_control("cc_99", change_reason=change_reason)

        client.delete.assert_awaited_once_with(CONTROL_PATH, params={"teamId": "team_abc"})

    async def test_the_reason_is_sent_trimmed(self):
        client = _client()

        await client.delete_cost_control("cc_99", change_reason=f"  {REASON} ")

        client.delete.assert_awaited_once_with(
            CONTROL_PATH, params={"teamId": "team_abc", "changeReason": REASON}
        )

    async def test_a_delete_by_id_alone_sends_only_the_team(self):
        client = _client()

        await client.delete_cost_control("cc_99")

        client.delete.assert_awaited_once_with(CONTROL_PATH, params={"teamId": "team_abc"})


def _platform() -> MagicMock:
    platform = MagicMock()
    platform.team_id = "team_test"
    platform.delete_cost_control = AsyncMock(return_value={})
    return platform


@pytest.mark.asyncio
class TestTheDeleteAction:
    async def test_the_reason_reaches_the_client(self):
        platform = _platform()

        await CostControlsManager(platform).delete_cost_control(
            {"control_id": "cc_99", "change_reason": REASON}
        )

        platform.delete_cost_control.assert_awaited_once_with("cc_99", change_reason=REASON)

    async def test_without_a_reason_none_is_passed(self):
        platform = _platform()

        await CostControlsManager(platform).delete_cost_control({"control_id": "cc_99"})

        platform.delete_cost_control.assert_awaited_once_with("cc_99", change_reason=None)

    async def test_the_reason_reaches_the_client_trimmed(self):
        platform = _platform()

        await CostControlsManager(platform).delete_cost_control(
            {"control_id": "cc_99", "change_reason": f" {REASON}  "}
        )

        platform.delete_cost_control.assert_awaited_once_with("cc_99", change_reason=REASON)

    async def test_a_400_with_a_reason_names_both_causes_without_the_platforms_words(self):
        platform = _platform()
        platform.delete_cost_control.side_effect = ReveniumAPIError(
            "changeReason is reserved; write a different reason", status_code=400
        )

        with pytest.raises(ToolError) as refusal:
            await CostControlsManager(platform).delete_cost_control(
                {"control_id": "cc_99", "change_reason": REASON}
            )

        message = refusal.value.message
        assert "'cc_99' was not deleted" in message
        assert "no accessible cost control has this id" in message
        assert "refused the change reason" in message
        assert "500 characters" in message
        assert "write a different reason" not in str(refusal.value.__dict__)
        assert refusal.value.error_code == ErrorCodes.INVALID_VALUE
        assert refusal.value.field == "control_id"
        assert refusal.value.value is None

    async def test_a_reason_over_the_limit_is_refused_before_any_request(self):
        platform = _platform()

        with pytest.raises(ToolError) as refusal:
            await CostControlsManager(platform).delete_cost_control(
                {"control_id": "cc_99", "change_reason": "x" * 501}
            )

        assert refusal.value.field == "change_reason"
        assert "500" in refusal.value.message
        platform.delete_cost_control.assert_not_awaited()

    async def test_the_limit_counts_characters_after_trimming(self):
        platform = _platform()
        reason = "\U0001F600" * 500

        await CostControlsManager(platform).delete_cost_control(
            {"control_id": "cc_99", "change_reason": f"\n{reason}  "}
        )

        platform.delete_cost_control.assert_awaited_once_with("cc_99", change_reason=reason)

    async def test_a_400_for_an_unknown_id_with_a_reason_does_not_confirm_the_id_exists(self):
        platform = _platform()
        platform.delete_cost_control.side_effect = ReveniumAPIError(
            "Invalid id: cc_other_tenant", status_code=400
        )

        with pytest.raises(ToolError) as refusal:
            await CostControlsManager(platform).delete_cost_control(
                {"control_id": "cc_other_tenant", "change_reason": REASON}
            )

        assert "no accessible cost control has this id" in refusal.value.message
        assert "Invalid id" not in refusal.value.message

    @pytest.mark.parametrize("blank", ["", "   "])
    async def test_a_400_with_a_blank_reason_is_not_found(self, blank):
        platform = _platform()
        platform.delete_cost_control.side_effect = ReveniumAPIError("boom", status_code=400)

        with pytest.raises(ToolError) as refusal:
            await CostControlsManager(platform).delete_cost_control(
                {"control_id": "cc_missing", "change_reason": blank}
            )

        assert refusal.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND
        platform.delete_cost_control.assert_awaited_once_with("cc_missing", change_reason=None)

    async def test_a_server_failure_with_a_reason_propagates(self):
        platform = _platform()
        platform.delete_cost_control.side_effect = ReveniumAPIError("down", status_code=503)

        with pytest.raises(ReveniumAPIError):
            await CostControlsManager(platform).delete_cost_control(
                {"control_id": "cc_99", "change_reason": REASON}
            )

    @pytest.mark.parametrize("status", [403, 404])
    async def test_an_unknown_id_with_a_reason_is_still_not_found(self, status):
        platform = _platform()
        platform.delete_cost_control.side_effect = ReveniumAPIError("boom", status_code=status)

        with pytest.raises(ToolError) as refusal:
            await CostControlsManager(platform).delete_cost_control(
                {"control_id": "cc_missing", "change_reason": REASON}
            )

        assert refusal.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND


async def _call_manage_cost_controls(arguments, platform):
    with patch.object(CostControlsManagement, "get_client", AsyncMock(return_value=platform)):
        return await _call_through_the_boundary(
            "_register_manage_cost_controls", "manage_cost_controls", arguments, execute=True
        )


@pytest.mark.asyncio
class TestTheRegisteredTool:
    async def test_change_reason_is_accepted_at_the_top_level_of_a_delete(self):
        platform = _platform()

        is_error, text, _ = await _call_manage_cost_controls(
            {"action": "delete", "control_id": "cc_99", "change_reason": REASON}, platform
        )

        assert not is_error, text
        platform.delete_cost_control.assert_awaited_once_with("cc_99", change_reason=REASON)

    async def test_change_reason_on_an_update_is_refused_before_anything_is_sent(self):
        platform = _platform()
        platform.update_cost_control = AsyncMock()

        is_error, text, _ = await _call_manage_cost_controls(
            {
                "action": "update",
                "control_id": "cc_99",
                "control_data": {"hardLimit": 2000},
                "change_reason": REASON,
            },
            platform,
        )

        assert is_error, text
        assert "change_reason" in text
        assert "changeReason inside control_data" in text
        platform.update_cost_control.assert_not_awaited()

    async def test_a_change_reason_that_is_not_text_is_refused(self):
        platform = _platform()

        is_error, text, _ = await _call_manage_cost_controls(
            {"action": "delete", "control_id": "cc_99", "change_reason": 42}, platform
        )

        assert is_error, text
        assert "change_reason" in text
        platform.delete_cost_control.assert_not_awaited()


@pytest.mark.asyncio
class TestTheSchemaNamesTheHistoryFields:
    async def test_control_data_documents_change_reason_and_the_alert_link(self):
        control_data = (await CostControlsManagement()._get_input_schema())["properties"][
            "control_data"
        ]

        change_reason = control_data["properties"]["changeReason"]
        assert change_reason["maxLength"] == 500
        assert "never returned" in change_reason["description"]
        assert "changes nothing" in change_reason["description"]
        link = control_data["properties"]["aiAnomalyId"]
        assert "null clears" in link["description"]

    async def test_the_schema_lists_change_reason_for_delete(self):
        properties = (await CostControlsManagement()._get_input_schema())["properties"]

        assert properties["change_reason"]["description"].startswith("delete only:")

    async def test_the_capabilities_name_both_fields_on_create_and_update(self):
        capabilities = await CostControlsManagement()._get_tool_capabilities()
        crud = next(cap for cap in capabilities if cap.name == "Cost Control CRUD")

        for action in ("create", "update"):
            assert "changeReason" in crud.parameters[action]["control_data"]
            assert "aiAnomalyId" in crud.parameters[action]["control_data"]
        assert "change_reason" in crud.parameters["delete"]
