"""BACK-3539: the org-unit to department rename and its deprecated aliases."""

import importlib
import inspect
import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP
from mcp.types import TextContent

from src.revenium_mcp_server.common.department_aliases import (
    DEPRECATED_ACTION_ALIASES,
    DEPRECATED_ARGUMENT_ALIASES,
    deprecated_aliases_note,
    deprecated_argument_properties,
    resolve_department_aliases,
)
from src.revenium_mcp_server.common.tool_execution import standardized_tool_execution
from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.registry import ToolConfigurationRegistry

SRC = Path(__file__).resolve().parents[2] / "src" / "revenium_mcp_server"
OLD_WIRE_NAME = re.compile(r"org-unit|orgUnit|OrgUnit")
FEATURE_FLAG_NAMES = ("org-unit-attribution-enabled", "org-unit-budgets-enabled")


class TestActionAliases:
    @pytest.mark.parametrize(
        "old,new",
        [
            ("list_org_units", "list_departments"),
            ("delete_org_unit_person", "delete_department_person"),
            ("clear_org_unit_assignment", "clear_department_assignment"),
            ("preview_org_unit_group", "preview_department_group"),
        ],
    )
    def test_old_action_resolves_to_department_action(self, old, new):
        action, arguments = resolve_department_aliases("manage_customers", old, {"action": old})

        assert action == new
        assert arguments["action"] == new

    def test_current_action_is_left_alone(self):
        action, arguments = resolve_department_aliases("manage_customers", "list", {"action": "list"})

        assert (action, arguments) == ("list", {"action": "list"})


class TestArgumentAliases:
    @pytest.mark.parametrize("old,new", sorted(DEPRECATED_ARGUMENT_ALIASES.items()))
    def test_old_argument_is_renamed(self, old, new):
        _, arguments = resolve_department_aliases("any_tool", "act", {old: "173"})

        assert arguments == {new: "173"}

    def test_department_spelling_wins_over_its_alias(self):
        _, arguments = resolve_department_aliases(
            "business_analytics_management",
            "get_pr_health",
            {"department_id": 5, "org_unit_id": 9},
        )

        assert arguments == {"department_id": 5}

    def test_input_is_not_mutated(self):
        original = {"action": "list_org_units", "org_unit_id": 1}
        resolve_department_aliases("manage_customers", "list_org_units", original)

        assert original == {"action": "list_org_units", "org_unit_id": 1}


class TestDimensionAlias:
    def test_cost_control_group_by_and_filter_dimension_map_to_department(self):
        control_data = {
            "groupBy": "ORG_UNIT",
            "filters": [
                {"dimension": "ORG_UNIT", "operator": "IS", "value": "173"},
                {"dimension": "MODEL", "operator": "IS", "value": "gpt-4"},
            ],
        }

        _, arguments = resolve_department_aliases(
            "manage_cost_controls", "create", {"control_data": control_data}
        )

        assert arguments["control_data"]["groupBy"] == "DEPARTMENT"
        assert [f["dimension"] for f in arguments["control_data"]["filters"]] == [
            "DEPARTMENT",
            "MODEL",
        ]
        assert control_data["groupBy"] == "ORG_UNIT"

    @pytest.mark.parametrize("name", ["dimension", "group_by"])
    def test_cost_control_dimension_arguments_map_to_department(self, name):
        _, arguments = resolve_department_aliases(
            "manage_cost_controls", "get_enforcement_rule_roster", {name: "ORG_UNIT"}
        )

        assert arguments[name] == "DEPARTMENT"

    def test_department_is_accepted_unchanged(self):
        _, arguments = resolve_department_aliases(
            "manage_cost_controls", "create", {"control_data": {"groupBy": "DEPARTMENT"}}
        )

        assert arguments["control_data"]["groupBy"] == "DEPARTMENT"

    def test_other_tools_keep_their_dimension_values(self):
        _, arguments = resolve_department_aliases(
            "manage_alerts", "create", {"dimension": "ORG_UNIT"}
        )

        assert arguments["dimension"] == "ORG_UNIT"


class TestHelpText:
    def test_note_names_each_alias_of_the_requested_names(self):
        note = deprecated_aliases_note("list_departments", "DEPARTMENT")

        assert "list_org_units -> list_departments" in note
        assert "ORG_UNIT -> DEPARTMENT" in note
        assert "delete_org_unit_person" not in note

    def test_note_is_empty_for_a_name_without_aliases(self):
        assert deprecated_aliases_note("list") == ""

    def test_schema_properties_mark_the_alias_deprecated(self):
        properties = deprecated_argument_properties("department_id", "integer")

        assert properties == {
            "org_unit_id": {
                "type": "integer",
                "deprecated": True,
                "description": "Deprecated alias of department_id, still accepted for one release.",
            }
        }


class TestStandardizedExecutionResolvesAliases:
    @pytest.mark.asyncio
    async def test_tool_receives_the_department_names(self):
        handler = AsyncMock(return_value=[TextContent(type="text", text="ok")])

        with patch(
            "src.revenium_mcp_server.introspection.integration."
            "introspection_integration.handle_tool_execution",
            new=handler,
        ):
            await standardized_tool_execution(
                tool_name="manage_cost_controls",
                action="preview_org_unit_group",
                arguments={"action": "preview_org_unit_group", "parent_org_unit_id": 173},
                tool_class=MagicMock(),
            )

        handler.assert_awaited_once_with(
            "manage_cost_controls",
            "preview_department_group",
            {"action": "preview_department_group", "parent_department_id": 173},
        )


def _registry() -> ToolConfigurationRegistry:
    return ToolConfigurationRegistry(tool_config=ToolConfig.create_for_testing(profile="business"))


async def _closure(method_name: str):
    mcp = MagicMock()
    await getattr(_registry(), method_name)(mcp)
    return mcp.tool.return_value.call_args[0][0]


class TestRegistryClosuresAcceptBothSpellings:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method,names",
        [
            ("_register_business_analytics_management", ("department_id", "org_unit_id")),
            ("_register_manage_ai_insights", ("filter_department_id", "filter_org_unit_id")),
            ("_register_manage_cost_controls", ("parent_department_id", "parent_org_unit_id")),
        ],
    )
    async def test_signature_declares_department_name_and_alias(self, method, names):
        parameters = inspect.signature(await _closure(method)).parameters

        assert set(names) <= set(parameters)

    @pytest.mark.asyncio
    async def test_alias_argument_reaches_the_tool_as_department_id(self):
        closure = await _closure("_register_business_analytics_management")
        handler = AsyncMock(return_value=[TextContent(type="text", text="ok")])

        with patch(
            "src.revenium_mcp_server.introspection.integration."
            "introspection_integration.handle_tool_execution",
            new=handler,
        ):
            await closure(action="get_pr_health", source="github", org_unit_id="173")

        _, _, arguments = handler.await_args.args
        assert arguments["department_id"] == "173"
        assert "org_unit_id" not in arguments


class TestNoOrgUnitWireNameIsSent:
    def test_source_outside_the_alias_table_uses_department_wire_names(self):
        offenders = []
        for path in SRC.rglob("*.py"):
            if "generated" in path.parts or path.name == "department_aliases.py":
                continue
            text = path.read_text(encoding="utf-8")
            for flag in FEATURE_FLAG_NAMES:
                text = text.replace(flag, "")
            if OLD_WIRE_NAME.search(text):
                offenders.append(str(path.relative_to(SRC)))

        assert offenders == []

    def test_every_action_alias_targets_a_routed_action(self):
        customer = (SRC / "tools_decomposed" / "customer_management.py").read_text()
        cost = (SRC / "tools_decomposed" / "cost_controls_management.py").read_text()

        for target in DEPRECATED_ACTION_ALIASES.values():
            assert f'action == "{target}"' in customer + cost, target


_TOOL_CLASSES = {
    "manage_customers": ("customer_management", "CustomerManagement"),
    "manage_cost_controls": ("cost_controls_management", "CostControlsManagement"),
    "business_analytics_management": (
        "business_analytics_management",
        "BusinessAnalyticsManagement",
    ),
    "manage_ai_insights": ("ai_insights_management", "AIInsightsManagement"),
}
_ADVERTISED: dict = {}


async def _advertised_tools() -> dict:
    if not _ADVERTISED:
        mcp = FastMCP("alias-test")
        await _registry().register_tools_conditionally(mcp)
        for tool in await mcp.list_tools(run_middleware=False):
            _ADVERTISED[tool.name] = tool.parameters
    return _ADVERTISED


async def _capabilities_text(tool_name: str) -> str:
    module_name, class_name = _TOOL_CLASSES[tool_name]
    module = importlib.import_module(f"src.revenium_mcp_server.tools_decomposed.{module_name}")
    result = await getattr(module, class_name)(ucm_helper=None).handle_action(
        "get_capabilities", {}
    )
    return "\n".join(getattr(part, "text", "") for part in result)


class TestClientsCanSeeTheDeprecatedAliases:
    """Every alias is visible as deprecated on tools/list or in get_capabilities."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "tool_name,aliases",
        [
            (
                "manage_customers",
                ("list_org_units", "delete_org_unit_person", "clear_org_unit_assignment"),
            ),
            ("manage_cost_controls", ("preview_org_unit_group", "parent_org_unit_id")),
            ("business_analytics_management", ("org_unit_id",)),
            ("manage_ai_insights", ("filter_org_unit_id",)),
        ],
    )
    async def test_each_alias_is_named_as_deprecated(self, tool_name, aliases):
        advertised = json.dumps((await _advertised_tools())[tool_name])
        capabilities = await _capabilities_text(tool_name)

        for alias in aliases:
            surfaces = [text for text in (advertised, capabilities) if alias in text]
            assert surfaces, f"{tool_name} never names {alias}"
            assert any(
                "one release" in text and "eprecated" in text for text in surfaces
            ), f"{tool_name} names {alias} without saying it is deprecated"

    @pytest.mark.asyncio
    async def test_advertised_alias_argument_is_flagged_deprecated(self):
        properties = (await _advertised_tools())["manage_cost_controls"]["properties"]

        assert properties["parent_org_unit_id"]["deprecated"] is True
        assert "parent_department_id" in properties["parent_org_unit_id"]["description"]
        assert "deprecated" not in properties["parent_department_id"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "tool_name,alias",
        [
            ("manage_customers", "list_org_units -> list_departments"),
            ("manage_cost_controls", "preview_org_unit_group -> preview_department_group"),
        ],
    )
    async def test_advertised_action_names_its_aliases(self, tool_name, alias):
        action = (await _advertised_tools())[tool_name]["properties"]["action"]

        assert alias in action["description"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "tool_name,alias",
        [
            ("business_analytics_management", "org_unit_id"),
            ("manage_ai_insights", "filter_org_unit_id"),
        ],
    )
    async def test_thin_tool_reference_block_flags_the_alias(self, tool_name, alias):
        text = await _capabilities_text(tool_name)
        lines = [line for line in text.splitlines() if line.startswith(f"- `{alias}` (")]

        assert lines and "(deprecated)" in lines[0]
