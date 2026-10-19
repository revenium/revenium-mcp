"""Budget test for the advertised tool list (BACK-3170).

Every agent that connects to this server pays for the whole tool list before
it does any work, so the list has a budget like any other cost.

Calibration. The budgets below are in characters, not tokens, so the test does
not need a tokenizer dependency. The unit of measure is what a client actually
receives for one tool, rendered the way the BACK-3168 audit measured it:
``json.dumps({"name", "description", "inputSchema"}, indent=2)``. On that
rendering the audit's baseline was 18,685 cl100k_base tokens over 82,755
characters (4.42 chars/token); the slimmed list measured 6,043 tokens over
25,384 characters (4.17 chars/token). Divide a budget here by roughly 4.2 to
read it back as tokens.

The budgets carry deliberate headroom over the measured figures. They are here
to catch a regression — a parameter list creeping back into the advertised
schema — not to forbid an honest new parameter.
"""

import importlib
import json
import re

import pytest
from fastmcp import FastMCP
from fastmcp.tools.function_parsing import ParsedFunction

from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.profiles import PROFILE_DEFINITIONS
from src.revenium_mcp_server.tool_configuration.registry import ToolConfigurationRegistry
from src.revenium_mcp_server.tool_configuration.schema_slimming import (
    THIN_SCHEMA_TOOLS,
    slim_schema,
)

#: The class behind each thin tool, so the test can ask it for its own
#: get_capabilities text without going through the network.
THIN_TOOL_CLASSES = {
    "manage_metering": ("metering_management", "MeteringManagement"),
    "business_analytics_management": (
        "business_analytics_management",
        "BusinessAnalyticsManagement",
    ),
    "manage_alerts": ("alert_management", "AlertManagement"),
    "manage_ai_insights": ("ai_insights_management", "AIInsightsManagement"),
    "manage_tools": ("tool_management", "ToolManagement"),
}

#: Whole business profile (20 tools). Measured 25,384 chars / 6,043 tokens.
TOTAL_CHARACTER_BUDGET = 30_000

#: The tools BACK-3168 found heaviest, which now advertise the thin shape.
#: Measured, in characters: see the values each budget sits above.
PER_TOOL_CHARACTER_BUDGETS = {
    "business_analytics_management": 2_400,  # measured 2,037
    "manage_tools": 1_800,  # measured 1,534
    "manage_alerts": 1_800,  # measured 1,518
    "manage_metering": 1_600,  # measured 1,313
    "manage_ai_insights": 1_300,  # measured 1,017
}

_NULL_BRANCH = {"type": "null"}


#: Names a thin tool lists that another open pull request removes or declares.
#: manage_tools: BACK-4624 (PR 444) declares ``provider`` and drops ``agent``
#: from the help. The exemption lapses once ``provider`` is on the closure.
_AWAITING_OTHER_PRS = {"manage_tools": {"agent", "provider"}}


_REGISTERED_TOOLS = {}


@pytest.fixture
async def registered_tools():
    """Register the business profile once and return the live FastMCP tools.

    Registration is cached across the module: it boots every tool class, and
    these tests only read from the result.
    """
    if not _REGISTERED_TOOLS:
        mcp = FastMCP("budget-test")
        registry = ToolConfigurationRegistry(
            tool_config=ToolConfig.create_for_testing(profile="business")
        )
        await registry.register_tools_conditionally(mcp)
        for tool in await mcp.list_tools(run_middleware=False):
            _REGISTERED_TOOLS[tool.name] = tool
    return _REGISTERED_TOOLS


@pytest.fixture
async def advertised_tools(registered_tools):
    """What a client is actually sent for each tool."""
    return {
        name: {
            "name": name,
            "description": tool.description,
            "inputSchema": tool.parameters,
        }
        for name, tool in registered_tools.items()
    }


def _rendered(tool):
    return json.dumps(tool, indent=2)


def _properties(tool):
    return tool["inputSchema"].get("properties", {})


@pytest.mark.asyncio
class TestAdvertisedToolBudget:
    async def test_the_whole_business_profile_is_registered(self, advertised_tools):
        assert set(advertised_tools) == PROFILE_DEFINITIONS["business"]

    async def test_total_footprint_is_within_budget(self, advertised_tools):
        total = sum(len(_rendered(tool)) for tool in advertised_tools.values())
        assert total <= TOTAL_CHARACTER_BUDGET, (
            f"advertised tool list grew to {total} characters "
            f"(~{total // 4} tokens), budget is {TOTAL_CHARACTER_BUDGET}"
        )

    @pytest.mark.parametrize("tool_name", sorted(PER_TOOL_CHARACTER_BUDGETS))
    async def test_heavy_tool_is_within_budget(self, advertised_tools, tool_name):
        size = len(_rendered(advertised_tools[tool_name]))
        budget = PER_TOOL_CHARACTER_BUDGETS[tool_name]
        assert size <= budget, (
            f"{tool_name} grew to {size} characters (~{size // 4} tokens), budget is {budget}"
        )


@pytest.mark.asyncio
class TestAdvertisedSchemaShape:
    async def test_no_property_advertises_a_null_branch(self, advertised_tools):
        offenders = [
            f"{name}.{prop}"
            for name, tool in advertised_tools.items()
            for prop, schema in _properties(tool).items()
            if _NULL_BRANCH in schema.get("anyOf", [])
        ]
        assert offenders == []

    async def test_no_property_advertises_a_null_default(self, advertised_tools):
        offenders = [
            f"{name}.{prop}"
            for name, tool in advertised_tools.items()
            for prop, schema in _properties(tool).items()
            if "default" in schema and schema["default"] is None
        ]
        assert offenders == []

    async def test_action_is_advertised_first(self, advertised_tools):
        for name, tool in advertised_tools.items():
            properties = list(_properties(tool))
            if "action" in properties:
                assert properties[0] == "action", name

    async def test_heavy_tools_advertise_the_params_bag(self, advertised_tools):
        for tool_name in THIN_SCHEMA_TOOLS:
            properties = _properties(advertised_tools[tool_name])
            assert "params" in properties, tool_name
            assert "get_capabilities" in properties["params"]["description"], tool_name

    async def test_heavy_tools_still_accept_their_named_arguments(self, advertised_tools):
        """A thin schema must not tell a client that an existing call is invalid."""
        for tool_name in THIN_SCHEMA_TOOLS:
            assert advertised_tools[tool_name]["inputSchema"]["additionalProperties"] is True


@pytest.mark.asyncio
class TestThinToolsDocumentWhatTheyHide:
    """The thin contract: what the schema stops advertising, get_capabilities must name.

    A thin tool tells agents to call get_capabilities for its per-action
    parameters. If a parameter is missing from both the schema and that text,
    it is undiscoverable - which is the failure mode this suite exists to
    prevent, not a cosmetic one.
    """

    @staticmethod
    async def _dropped_parameters(tool):
        """Names in the closure's own schema that the advertised one no longer shows."""
        full = slim_schema(ParsedFunction.from_function(tool.fn).input_schema)
        advertised = set(tool.parameters.get("properties", {}))
        return sorted(set(full.get("properties", {})) - advertised - {"params"})

    @staticmethod
    async def _capabilities_text(tool_name):
        module_name, class_name = THIN_TOOL_CLASSES[tool_name]
        module = importlib.import_module(
            f"src.revenium_mcp_server.tools_decomposed.{module_name}"
        )
        instance = getattr(module, class_name)(ucm_helper=None)
        result = await instance.handle_action("get_capabilities", {})
        return "\n".join(getattr(part, "text", "") for part in result)

    @pytest.mark.parametrize("tool_name", sorted(THIN_SCHEMA_TOOLS))
    async def test_every_hidden_parameter_is_named_by_get_capabilities(
        self, registered_tools, tool_name
    ):
        dropped = await self._dropped_parameters(registered_tools[tool_name])
        assert dropped, f"{tool_name} hides nothing - is it still a thin tool?"

        text = await self._capabilities_text(tool_name)
        missing = [name for name in dropped if name not in text]

        assert missing == [], (
            f"{tool_name} stops advertising these but get_capabilities never names them: "
            f"{missing}. Add them to that tool class's _get_input_schema()."
        )

    @pytest.mark.parametrize("tool_name", sorted(THIN_SCHEMA_TOOLS))
    async def test_get_capabilities_says_where_parameters_may_go(self, tool_name):
        text = await self._capabilities_text(tool_name)
        assert "params" in text, tool_name

    @pytest.mark.parametrize("tool_name", sorted(THIN_SCHEMA_TOOLS))
    async def test_no_hidden_parameter_is_documented_as_any(self, tool_name):
        """A reference line reading ``(any)`` means the tool declared an empty schema.

        For a thin tool the reference block is the only place a caller can
        learn a hidden parameter's type, so an untyped entry is the same as an
        undocumented one.
        """
        text = await self._capabilities_text(tool_name)
        untyped = [line for line in text.splitlines() if line.startswith("- `") and "(any)" in line]
        assert untyped == [], (
            f"{tool_name} documents these parameters without a type: {untyped}. "
            "Give them a type in that tool class's _get_input_schema()."
        )

    @staticmethod
    async def _listed_parameters(tool_name):
        """The names under get_capabilities' "Pass any of these as a top-level argument"."""
        text = await TestThinToolsDocumentWhatTheyHide._capabilities_text(tool_name)
        reference = text.split("## Parameters", 1)[-1]
        return re.findall(r"^- `([^`]+)`", reference, re.MULTILINE)

    @pytest.mark.parametrize("tool_name", sorted(THIN_SCHEMA_TOOLS))
    async def test_every_listed_parameter_is_accepted_at_the_top_level(
        self, registered_tools, tool_name
    ):
        """The reference promises top-level use, and FastMCP refuses any name the
        closure signature does not declare, so every listed name must be declared."""
        declared = set(
            ParsedFunction.from_function(registered_tools[tool_name].fn).input_schema[
                "properties"
            ]
        )
        listed = await self._listed_parameters(tool_name)
        awaiting = _AWAITING_OTHER_PRS.get(tool_name, set())
        if "provider" in declared:
            awaiting = set()

        refused = sorted(set(listed) - declared - awaiting)

        assert refused == [], (
            f"{tool_name}'s get_capabilities lists these as top-level arguments, but "
            f"its registered closure refuses them: {refused}. Declare them in "
            "tool_configuration/registry.py or drop them from _get_input_schema()."
        )
        if tool_name == "manage_metering":
            from src.revenium_mcp_server.tools_decomposed.metering_management import (
                _COMPLETIONS_FILTER_PARAM_MAP,
            )

            filters = set(_COMPLETIONS_FILTER_PARAM_MAP)
            assert sorted(filters - set(listed)) == []
            assert sorted(filters - declared) == []



#: The registration closure, a call action and a value for each option that
#: is declared so existing callers are not refused but that nothing reads.
_IGNORED_ARGUMENT_CALLS = [
    ("_register_system_diagnostics", "system_diagnostics", "environment_variables", "include_sensitive", True),
    ("_register_system_diagnostics", "system_diagnostics", "environment_variables", "format_output", "json"),
    ("_register_system_diagnostics", "system_diagnostics", "system_health", "include_recommendations", True),
    ("_register_system_diagnostics", "system_diagnostics", "debug", "show_detailed_analysis", True),
    ("_register_system_setup", "system_setup", "show_welcome", "show_environment", True),
    ("_register_system_setup", "system_setup", "show_welcome", "include_recommendations", True),
    ("_register_system_setup", "system_setup", "show_welcome", "include_setup_guidance", True),
    ("_register_system_setup", "system_setup", "setup_checklist", "suggest_smart_defaults", True),
    ("_register_system_setup", "system_setup", "update_email", "validate_format", True),
    ("_register_slack_management", "slack_management", "guided_setup", "skip_prompts", True),
]

_IGNORED_ARGUMENT_TOOL_CLASSES = {
    "system_diagnostics": ("system_diagnostics", "SystemDiagnostics"),
    "system_setup": ("system_setup", "SystemSetup"),
    "slack_management": ("slack_management", "SlackManagement"),
}


def _ignored_arguments():
    from src.revenium_mcp_server.tool_configuration import schema_slimming

    return getattr(schema_slimming, "ACCEPTED_BUT_IGNORED_ARGUMENTS", {})


class TestIgnoredArgumentsAreNotAdvertised:
    """An option nothing reads stays accepted, so no caller is refused, but is
    not offered, so an assistant is not told that setting it changes the answer."""

    def test_every_ignored_argument_is_listed(self):
        listed = {(tool, name) for _, tool, _, name, _ in _IGNORED_ARGUMENT_CALLS}
        constant = {
            (tool, name) for tool, names in _ignored_arguments().items() for name in names
        }

        assert constant == listed

    async def test_an_ignored_argument_is_not_in_the_advertised_schema(
        self, advertised_tools
    ):
        advertised = sorted(
            f"{tool}.{name}"
            for _, tool, _, name, _ in _IGNORED_ARGUMENT_CALLS
            if name in _properties(advertised_tools[tool])
        )

        assert advertised == []
        for tool in _IGNORED_ARGUMENT_TOOL_CLASSES:
            assert advertised_tools[tool]["inputSchema"]["additionalProperties"] is True

    @pytest.mark.parametrize(
        ("register_method", "tool", "action", "name", "value"), _IGNORED_ARGUMENT_CALLS
    )
    async def test_an_ignored_argument_is_still_accepted(
        self, register_method, tool, action, name, value
    ):
        from tests.unit.test_tool_config_registry_m4 import _call_through_the_boundary

        is_error, text, captured = await _call_through_the_boundary(
            register_method, tool, {"action": action, name: value}
        )

        assert is_error is False, text
        assert name in captured

    @pytest.mark.parametrize("tool", sorted(_IGNORED_ARGUMENT_TOOL_CLASSES))
    async def test_no_help_answer_names_an_ignored_argument(self, tool):
        module_name, class_name = _IGNORED_ARGUMENT_TOOL_CLASSES[tool]
        module = importlib.import_module(
            f"src.revenium_mcp_server.tools_decomposed.{module_name}"
        )
        instance = getattr(module, class_name)(ucm_helper=None)
        ignored = {name for _, _, _, name, _ in _IGNORED_ARGUMENT_CALLS}

        answers = {}
        for action in ("help", "get_capabilities", "get_examples", "get_agent_summary"):
            try:
                result = await instance.handle_action(action, {})
            except Exception:  # an action this tool does not have
                continue
            answers[action] = "\n".join(getattr(part, "text", "") for part in result)
        capabilities = await instance._get_tool_capabilities()
        answers["_get_tool_capabilities"] = json.dumps(
            [
                [c.parameters, c.examples, c.limitations, c.description]
                for c in capabilities
            ]
        )

        assert "get_capabilities" in answers
        named = sorted(
            f"{action}: {name}"
            for action, text in answers.items()
            for name in ignored
            if name in text
        )
        assert named == []
