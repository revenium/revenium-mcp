"""BACK-5679/BACK-5681: the change reason rules both guardrail tools share, counted as the platform counts."""

import ast
from pathlib import Path

import pytest

from src.revenium_mcp_server import change_reason_contract
from src.revenium_mcp_server import client as client_module
from src.revenium_mcp_server.alerts import anomaly_manager
from src.revenium_mcp_server.common import change_reason
from src.revenium_mcp_server.common.change_reason import (
    ALERT_CHANGE_REASON,
    CHANGE_REASON_FIELD_NOTE,
    COST_CONTROL_CHANGE_REASON,
    checked_change_reason,
)
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from src.revenium_mcp_server.json_schema_validator import JSONSchemaValidator
from src.revenium_mcp_server.tools_decomposed import cost_controls_management
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from src.revenium_mcp_server.tools_decomposed.cost_controls_management import (
    CostControlsManagement,
)

ASTRAL_CHARACTER = "\U0001F600"


class TestTheLengthRule:
    """ChangeReason.normalize on the platform: trimmed, then at most 500 code points."""

    def test_500_characters_pass(self):
        assert checked_change_reason("a" * 500) == "a" * 500

    def test_501_characters_are_refused_naming_the_argument_and_the_limit(self):
        with pytest.raises(ToolError) as refusal:
            checked_change_reason("a" * 501)

        assert refusal.value.field == "change_reason"
        assert refusal.value.error_code == ErrorCodes.VALIDATION_ERROR
        assert "500" in refusal.value.message
        assert "501" in refusal.value.message

    def test_the_refusal_never_quotes_the_reason(self):
        reason = "secret-" + "x" * 500

        with pytest.raises(ToolError) as refusal:
            checked_change_reason(reason)

        assert "secret-" not in str(refusal.value.__dict__)
        assert refusal.value.value is None

    def test_a_character_outside_the_basic_plane_counts_once(self):
        assert checked_change_reason(ASTRAL_CHARACTER * 500) == ASTRAL_CHARACTER * 500
        with pytest.raises(ToolError):
            checked_change_reason(ASTRAL_CHARACTER * 501)

    def test_whitespace_around_the_reason_does_not_count(self):
        assert checked_change_reason("   " + "b" * 500 + "\n\n") == "b" * 500

    @pytest.mark.parametrize("blank", [None, "", "   ", "\n\t"])
    def test_a_blank_reason_is_none(self, blank):
        assert checked_change_reason(blank) is None

    def test_the_refusal_names_the_field_it_is_given(self):
        with pytest.raises(ToolError) as refusal:
            checked_change_reason("a" * 501, field="changeReason")

        assert refusal.value.field == "changeReason"
        assert "changeReason" in refusal.value.message


def test_the_field_note_says_a_reason_on_a_save_that_changes_nothing_can_be_dropped():
    assert "changes nothing" in CHANGE_REASON_FIELD_NOTE
    assert "dropped" in CHANGE_REASON_FIELD_NOTE


def test_the_client_takes_the_change_reason_from_the_contract_module_at_load():
    tree = ast.parse(Path(client_module.__file__).read_text())
    module_level = {node.module for node in tree.body if isinstance(node, ast.ImportFrom)}
    anywhere = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert "change_reason_contract" in module_level
    assert "common.change_reason" not in anywhere


def test_the_tool_layer_shares_the_contracts_definitions():
    assert change_reason.normalized_change_reason is change_reason_contract.normalized_change_reason
    assert change_reason.CHANGE_REASON_FIELD == change_reason_contract.CHANGE_REASON_FIELD
    assert change_reason.CHANGE_REASON_MAX_LENGTH == change_reason_contract.CHANGE_REASON_MAX_LENGTH


class TestTheArgumentContractIsDefinedOnce:
    """The change_reason argument advertises one type, bound and wording on every surface."""

    @pytest.mark.parametrize("argument", [ALERT_CHANGE_REASON, COST_CONTROL_CHANGE_REASON])
    def test_the_schema_is_a_string_bounded_by_the_platforms_limit(self, argument):
        assert argument.schema() == {
            "type": "string",
            "maxLength": change_reason_contract.CHANGE_REASON_MAX_LENGTH,
            "description": argument.description(),
        }

    @pytest.mark.parametrize("argument", [ALERT_CHANGE_REASON, COST_CONTROL_CHANGE_REASON])
    def test_the_capability_text_marks_it_optional(self, argument):
        assert argument.capability_text() == "str (optional) - " + argument.description()

    @pytest.mark.asyncio
    async def test_every_advertised_schema_is_the_arguments_own(self):
        alert_input = (await AlertManagement()._get_input_schema())["properties"]
        validator = JSONSchemaValidator().schemas["manage_alerts"]["properties"]
        cost_input = (await CostControlsManagement()._get_input_schema())["properties"]

        assert alert_input["change_reason"] == ALERT_CHANGE_REASON.schema()
        assert validator["change_reason"] == ALERT_CHANGE_REASON.schema()
        assert cost_input["change_reason"] == COST_CONTROL_CHANGE_REASON.schema()

    @pytest.mark.asyncio
    async def test_every_capability_entry_is_the_arguments_own_text(self):
        alert_caps = await AlertManagement(ucm_helper=None)._get_tool_capabilities()
        alert_crud = next(cap for cap in alert_caps if cap.name == "AI Anomaly Detection")
        cost_caps = await CostControlsManagement()._get_tool_capabilities()
        cost_crud = next(cap for cap in cost_caps if cap.name == "Cost Control CRUD")

        for action in ALERT_CHANGE_REASON.readers:
            assert alert_crud.parameters[action]["change_reason"] == (
                ALERT_CHANGE_REASON.capability_text()
            )
        assert cost_crud.parameters["delete"]["change_reason"] == (
            COST_CONTROL_CHANGE_REASON.capability_text()
        )


class TestTheAmbiguousDeleteRefusalIsDefinedOnce:
    """A 400 on a delete that carried a reason cannot tell a bad id from a refused reason."""

    @pytest.mark.parametrize(
        ("status", "reason", "ambiguous"),
        [
            (400, "cleanup", True),
            (400, None, False),
            (403, "cleanup", False),
            (404, "cleanup", False),
            (500, "cleanup", False),
        ],
    )
    def test_only_a_400_on_a_delete_with_a_reason_is_ambiguous(self, status, reason, ambiguous):
        error = client_module.ReveniumAPIError("refused", status_code=status)

        assert change_reason.delete_refusal_is_id_or_change_reason(error, reason) is ambiguous

    def test_an_error_that_is_not_the_platforms_answer_is_not_ambiguous(self):
        assert change_reason.delete_refusal_is_id_or_change_reason(ValueError("x"), "r") is False

    @pytest.mark.parametrize("module", [anomaly_manager, cost_controls_management])
    def test_each_delete_asks_the_shared_rule_and_keeps_no_copy(self, module):
        tree = ast.parse(Path(module.__file__).read_text())
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        local_copies = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.BoolOp)
            and any(
                isinstance(part, ast.Compare)
                and isinstance(part.left, ast.Attribute)
                and part.left.attr == "status_code"
                for part in node.values
            )
            and any(
                isinstance(name, ast.Name) and name.id == "change_reason"
                for part in node.values
                for name in ast.walk(part)
            )
        ]

        assert "delete_refusal_is_id_or_change_reason" in called
        assert local_copies == []
