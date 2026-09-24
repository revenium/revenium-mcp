"""Unit tests for tool_configuration/schema_slimming.py (BACK-3170).

Two halves are covered here:

* the pure schema transforms, exercised on hand-written schemas so a change in
  the rules is visible without booting a server;
* the ``params`` convention at runtime — the same call expressed with
  top-level arguments and with a ``params`` bag must reach
  ``standardized_tool_execution`` as the same arguments dict.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.registry import ToolConfigurationRegistry
from src.revenium_mcp_server.tool_configuration.schema_slimming import (
    COMMON_PARAMETERS,
    DESCRIPTION_SUFFIX,
    PARAMS_PROPERTY,
    THIN_SCHEMA_TOOLS,
    apply_schema_slimming,
    merge_params_argument,
    slim_property,
    slim_schema,
    slim_tool_description,
    slim_tool_schema,
    thin_schema,
)


# ---------------------------------------------------------------------------
# slim_property
# ---------------------------------------------------------------------------


class TestSlimProperty:
    def test_optional_string_collapses_to_string(self):
        assert slim_property(
            {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None}
        ) == {"type": "string"}

    def test_lenient_bool_union_advertises_bool(self):
        assert slim_property(
            {
                "anyOf": [{"type": "boolean"}, {"type": "string"}, {"type": "null"}],
                "default": None,
            }
        ) == {"type": "boolean"}

    def test_lenient_int_union_keeps_its_default(self):
        assert slim_property(
            {"anyOf": [{"type": "integer"}, {"type": "string"}], "default": 0}
        ) == {"type": "integer", "default": 0}

    def test_object_union_keeps_additional_properties(self):
        assert slim_property(
            {
                "anyOf": [
                    {"additionalProperties": True, "type": "object"},
                    {"type": "string"},
                    {"type": "null"},
                ],
                "default": None,
            }
        ) == {"additionalProperties": True, "type": "object"}

    def test_array_union_keeps_item_type(self):
        assert slim_property(
            {
                "anyOf": [
                    {"items": {"type": "string"}, "type": "array"},
                    {"type": "string"},
                    {"type": "null"},
                ],
                "default": None,
            }
        ) == {"items": {"type": "string"}, "type": "array"}

    def test_json_scalar_union_advertises_string(self):
        """_JSONScalar widens a *string* parameter, so string is the honest type."""
        assert slim_property(
            {
                "anyOf": [
                    {"type": "string"},
                    {"type": "integer"},
                    {"type": "number"},
                    {"type": "boolean"},
                    {"type": "null"},
                ],
                "default": None,
            }
        ) == {"type": "string"}

    def test_json_scalar_union_keeps_a_real_default(self):
        assert slim_property(
            {
                "anyOf": [
                    {"type": "string"},
                    {"type": "integer"},
                    {"type": "number"},
                    {"type": "boolean"},
                ],
                "default": "get_capabilities",
            }
        ) == {"type": "string", "default": "get_capabilities"}

    def test_numeric_union_without_a_string_branch_is_not_a_scalar_idiom(self):
        """Union[int, float] is real choice: the scalar idiom needs the str branch."""
        slimmed = slim_property(
            {"anyOf": [{"type": "integer"}, {"type": "number"}, {"type": "null"}], "default": None}
        )
        assert slimmed == {"anyOf": [{"type": "integer"}, {"type": "number"}]}

    def test_a_union_carrying_real_choice_survives(self):
        """manage_metering's search_page_range takes an int OR a list of ints.

        Collapsing that would tell a caller half of what the tool accepts is
        invalid, so only the null branch and the null default come off.
        """
        assert slim_property(
            {
                "anyOf": [
                    {"type": "integer"},
                    {"items": {"type": "integer"}, "type": "array"},
                    {"type": "null"},
                ],
                "default": None,
            }
        ) == {
            "anyOf": [{"type": "integer"}, {"items": {"type": "integer"}, "type": "array"}]
        }

    def test_a_union_of_two_structures_survives(self):
        """Neither branch is the lenient string, so neither can be dropped."""
        assert slim_property(
            {
                "anyOf": [
                    {"additionalProperties": True, "type": "object"},
                    {"items": {}, "type": "array"},
                    {"type": "null"},
                ]
            }
        ) == {
            "anyOf": [
                {"additionalProperties": True, "type": "object"},
                {"items": {}, "type": "array"},
            ]
        }

    def test_a_subset_of_the_json_scalar_set_is_still_the_idiom(self):
        """Union[str, float, int] is _JSONScalar minus bool - a widened string."""
        assert slim_property(
            {
                "anyOf": [
                    {"type": "string"},
                    {"type": "number"},
                    {"type": "integer"},
                    {"type": "null"},
                ],
                "default": None,
            }
        ) == {"type": "string"}

    def test_description_survives_the_collapse(self):
        assert slim_property(
            {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "a note",
            }
        ) == {"type": "string", "description": "a note"}

    def test_plain_property_is_untouched(self):
        assert slim_property({"type": "string", "default": "x"}) == {
            "type": "string",
            "default": "x",
        }

    def test_null_only_union_is_left_alone(self):
        """Nothing sensible to advertise, so do not invent a type."""
        assert slim_property({"anyOf": [{"type": "null"}]}) == {"anyOf": [{"type": "null"}]}

    def test_is_idempotent(self):
        once = slim_property(
            {"anyOf": [{"type": "boolean"}, {"type": "string"}, {"type": "null"}], "default": None}
        )
        assert slim_property(once) == once

    def test_does_not_mutate_its_input(self):
        original = {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None}
        slim_property(original)
        assert original == {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None}


# ---------------------------------------------------------------------------
# slim_schema
# ---------------------------------------------------------------------------


def _sample_schema():
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "alert_id": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
            "action": {"type": "string", "default": "get_capabilities"},
            "page": {"anyOf": [{"type": "integer"}, {"type": "string"}], "default": 0},
        },
    }


class TestSlimSchema:
    def test_action_is_listed_first(self):
        assert list(slim_schema(_sample_schema())["properties"]) == ["action", "alert_id", "page"]

    def test_action_keeps_its_default(self):
        action = slim_schema(_sample_schema())["properties"]["action"]
        assert action == {"type": "string", "default": "get_capabilities"}

    def test_every_property_is_slimmed(self):
        properties = slim_schema(_sample_schema())["properties"]
        assert properties["alert_id"] == {"type": "string"}
        assert properties["page"] == {"type": "integer", "default": 0}

    def test_schema_level_keys_are_preserved(self):
        slimmed = slim_schema(_sample_schema())
        assert slimmed["type"] == "object"
        assert slimmed["additionalProperties"] is False

    def test_schema_without_properties_is_returned_unchanged(self):
        assert slim_schema({"type": "object"}) == {"type": "object"}

    def test_is_idempotent(self):
        once = slim_schema(_sample_schema())
        assert slim_schema(once) == once


# ---------------------------------------------------------------------------
# thin_schema
# ---------------------------------------------------------------------------


def _wide_slim_schema():
    """A slimmed schema shaped like manage_alerts after the params rework.

    page and resource_type carry no default: the closure now applies those
    after the params merge, so thin_schema writes them back on.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["action", "alert_id"],
        "properties": {
            "action": {"type": "string"},
            "alert_id": {"type": "string"},
            "threshold": {"type": "number"},
            "filters": {"type": "object", "additionalProperties": True},
            "page": {"type": "integer"},
            "resource_type": {"type": "string"},
        },
    }


_WIDE_DEFAULTS = {"page": 0, "resource_type": "anomalies"}


class TestThinSchema:
    def test_per_action_parameters_disappear(self):
        thinned = thin_schema(_wide_slim_schema(), _WIDE_DEFAULTS)
        assert "threshold" not in thinned["properties"]

    def test_action_common_and_defaulted_parameters_survive(self):
        properties = thin_schema(_wide_slim_schema(), _WIDE_DEFAULTS)["properties"]
        assert set(properties) == {"action", "filters", "page", "resource_type", "params"}

    def test_defaults_are_written_back_onto_the_advertised_property(self):
        """The closure applies them after the merge, so the schema must state them."""
        properties = thin_schema(_wide_slim_schema(), _WIDE_DEFAULTS)["properties"]
        assert properties["page"] == {"type": "integer", "default": 0}
        assert properties["resource_type"] == {"type": "string", "default": "anomalies"}

    def test_a_tool_without_defaults_advertises_only_action_and_the_bag(self):
        schema = {
            "type": "object",
            "properties": {"action": {"type": "string"}, "run_id": {"type": "string"}},
        }
        assert set(thin_schema(schema)["properties"]) == {"action", "params"}

    def test_action_is_listed_first(self):
        thinned = thin_schema(_wide_slim_schema(), _WIDE_DEFAULTS)
        assert list(thinned["properties"])[0] == "action"

    def test_params_property_points_at_get_capabilities(self):
        params = thin_schema(_wide_slim_schema(), _WIDE_DEFAULTS)["properties"][PARAMS_PROPERTY]
        assert params["type"] == "object"
        assert "get_capabilities" in params["description"]

    def test_params_description_states_the_precedence_rule(self):
        params = thin_schema(_wide_slim_schema(), _WIDE_DEFAULTS)["properties"][PARAMS_PROPERTY]
        assert "top-level value wins" in params["description"]

    def test_additional_properties_stays_open(self):
        """The tool still accepts every name its closure declares."""
        assert thin_schema(_wide_slim_schema(), _WIDE_DEFAULTS)["additionalProperties"] is True

    def test_required_drops_names_no_longer_advertised(self):
        assert thin_schema(_wide_slim_schema(), _WIDE_DEFAULTS)["required"] == ["action"]

    def test_required_disappears_when_nothing_is_left(self):
        schema = _wide_slim_schema()
        schema["required"] = ["alert_id"]
        assert "required" not in thin_schema(schema, _WIDE_DEFAULTS)

    def test_is_idempotent(self):
        once = thin_schema(_wide_slim_schema(), _WIDE_DEFAULTS)
        assert thin_schema(once, _WIDE_DEFAULTS) == once


class TestSlimToolSchema:
    def test_heavy_tools_get_the_thin_shape(self):
        for tool_name in THIN_SCHEMA_TOOLS:
            properties = slim_tool_schema(tool_name, _wide_slim_schema())["properties"]
            assert PARAMS_PROPERTY in properties
            assert "threshold" not in properties

    def test_each_thin_tool_carries_its_own_defaults(self):
        properties = slim_tool_schema("manage_alerts", _wide_slim_schema())["properties"]
        assert properties["resource_type"]["default"] == "anomalies"
        assert properties["page"]["default"] == 0

    def test_other_tools_keep_every_parameter(self):
        properties = slim_tool_schema("manage_products", _wide_slim_schema())["properties"]
        assert "threshold" in properties
        assert PARAMS_PROPERTY not in properties

    def test_common_parameters_are_the_documented_four(self):
        assert tuple(COMMON_PARAMETERS) == ("page", "size", "filters", "dry_run")


class TestSlimToolDescription:
    def test_heavy_tool_descriptions_point_at_get_capabilities(self):
        assert DESCRIPTION_SUFFIX in slim_tool_description("manage_metering", "Meter things.")

    def test_other_tool_descriptions_are_untouched(self):
        assert slim_tool_description("manage_products", "Products.") == "Products."

    def test_is_idempotent(self):
        once = slim_tool_description("manage_metering", "Meter things.")
        assert slim_tool_description("manage_metering", once) == once

    def test_empty_description_is_left_alone(self):
        assert slim_tool_description("manage_metering", None) is None


# ---------------------------------------------------------------------------
# merge_params_argument
# ---------------------------------------------------------------------------


class TestMergeParamsArgument:
    def test_params_fills_in_unset_arguments(self):
        assert merge_params_argument({"action": "x", "page_size": None}, {"page_size": 2}) == {
            "action": "x",
            "page_size": 2,
        }

    def test_named_arguments_win(self):
        assert merge_params_argument({"page_size": 5}, {"page_size": 2})["page_size"] == 5

    def test_action_never_comes_from_params(self):
        assert merge_params_argument({"action": "list"}, {"action": "delete"})["action"] == "list"

    def test_nested_params_key_is_ignored(self):
        assert PARAMS_PROPERTY not in merge_params_argument({}, {PARAMS_PROPERTY: {"a": 1}})

    def test_unknown_names_are_passed_through_for_the_tool_to_reject(self):
        assert merge_params_argument({}, {"nonsense": 1}) == {"nonsense": 1}

    def test_missing_params_is_a_no_op(self):
        assert merge_params_argument({"a": 1}, None) == {"a": 1}

    def test_non_object_params_is_ignored(self):
        assert merge_params_argument({"a": 1}, "not-an-object") == {"a": 1}  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# apply_schema_slimming
# ---------------------------------------------------------------------------


class _FakeTool:
    def __init__(self, parameters, description=""):
        self.parameters = parameters
        self.description = description


@pytest.mark.asyncio
class TestApplySchemaSlimming:
    async def test_replaces_the_advertised_schema(self):
        tool = _FakeTool(_sample_schema(), "Products.")
        mcp = MagicMock()
        mcp.get_tool = AsyncMock(return_value=tool)

        await apply_schema_slimming(mcp, ["manage_products"])

        assert tool.parameters["properties"]["alert_id"] == {"type": "string"}

    async def test_heavy_tool_gets_thin_schema_and_pointer(self):
        tool = _FakeTool(_sample_schema(), "Meter things.")
        mcp = MagicMock()
        mcp.get_tool = AsyncMock(return_value=tool)

        await apply_schema_slimming(mcp, ["manage_metering"])

        assert PARAMS_PROPERTY in tool.parameters["properties"]
        assert DESCRIPTION_SUFFIX in tool.description

    async def test_a_missing_tool_does_not_abort_the_pass(self):
        tool = _FakeTool(_sample_schema(), "Products.")
        mcp = MagicMock()
        mcp.get_tool = AsyncMock(side_effect=[KeyError("gone"), tool])

        await apply_schema_slimming(mcp, ["not_registered", "manage_products"])

        assert tool.parameters["properties"]["alert_id"] == {"type": "string"}


# ---------------------------------------------------------------------------
# Equivalence: top-level arguments vs the params bag
# ---------------------------------------------------------------------------


async def _closure_for(method_name: str):
    """Register one tool against a mock FastMCP and return the handler closure."""
    registry = ToolConfigurationRegistry(tool_config=ToolConfig.create_for_testing())
    mcp = MagicMock()
    await getattr(registry, method_name)(mcp)
    return mcp.tool.return_value.call_args[0][0]


async def _arguments_from(closure, **kwargs):
    """Call a handler closure and return the arguments dict it forwarded."""
    with patch(
        "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
        new=AsyncMock(return_value=[]),
    ) as execution:
        await closure(**kwargs)
    return execution.await_args.kwargs["arguments"]


@pytest.mark.asyncio
class TestParamsBagEquivalence:
    async def test_manage_metering_params_match_top_level(self):
        closure = await _closure_for("_register_manage_metering")

        top_level = await _arguments_from(
            closure, action="lookup_recent_transactions", page_size=2, provider="Anthropic"
        )
        bagged = await _arguments_from(
            closure,
            action="lookup_recent_transactions",
            params={"page_size": 2, "provider": "Anthropic"},
        )

        assert bagged == top_level
        assert top_level["page_size"] == 2

    async def test_business_analytics_params_match_top_level(self):
        closure = await _closure_for("_register_business_analytics_management")

        top_level = await _arguments_from(
            closure, action="get_provider_costs", period="SEVEN_DAYS", group="TOTAL"
        )
        bagged = await _arguments_from(
            closure,
            action="get_provider_costs",
            params={"period": "SEVEN_DAYS", "group": "TOTAL"},
        )

        assert bagged == top_level
        assert top_level["period"] == "SEVEN_DAYS"

    async def test_bagged_values_get_the_same_preprocessing(self):
        """A string integer inside params is coerced exactly as a top-level one is."""
        closure = await _closure_for("_register_manage_metering")

        bagged = await _arguments_from(
            closure, action="lookup_recent_transactions", params={"page_size": "2"}
        )

        assert bagged["page_size"] == 2

    async def test_a_top_level_argument_beats_the_bag(self):
        closure = await _closure_for("_register_manage_metering")

        arguments = await _arguments_from(
            closure,
            action="lookup_recent_transactions",
            page_size=5,
            params={"page_size": 2},
        )

        assert arguments["page_size"] == 5

    async def test_the_bag_itself_is_never_forwarded(self):
        closure = await _closure_for("_register_manage_metering")

        arguments = await _arguments_from(
            closure, action="lookup_recent_transactions", params={"page_size": 2}
        )

        assert PARAMS_PROPERTY not in arguments

    async def test_manage_tools_filters_can_come_from_the_bag(self):
        closure = await _closure_for("_register_manage_tools")

        arguments = await _arguments_from(
            closure, action="list", params={"filters": {"toolType": "MCP"}}
        )

        assert arguments["filters"] == {"toolType": "MCP"}

    async def test_manage_tools_filters_still_default_to_an_empty_object(self):
        closure = await _closure_for("_register_manage_tools")

        arguments = await _arguments_from(closure, action="list")

        assert arguments["filters"] == {}


# ---------------------------------------------------------------------------
# Defaulted parameters: the bag must beat the default, and only the default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDefaultedParametersFromTheBag:
    """A default applied in the signature would land before the merge and win.

    That is the bug this suite pins: `{"params": {"page": 3}}` used to page
    from zero because `page: int = 0` had already filled the arguments dict.
    """

    async def test_defaults_still_reach_the_tool_when_nothing_is_sent(self):
        for method, expected in (
            ("_register_business_analytics_management", {"page": 0, "size": 20}),
            ("_register_manage_tools", {"page": 0, "size": 20}),
            ("_register_manage_alerts", {"page": 0, "size": 20, "resource_type": "anomalies"}),
        ):
            closure = await _closure_for(method)
            arguments = await _arguments_from(closure, action="list")
            for name, value in expected.items():
                assert arguments[name] == value, (method, name)

    async def test_business_analytics_paging_can_come_from_the_bag(self):
        closure = await _closure_for("_register_business_analytics_management")

        arguments = await _arguments_from(
            closure, action="list_invoices", params={"page": 3, "size": 5}
        )

        assert (arguments["page"], arguments["size"]) == (3, 5)

    async def test_manage_tools_paging_can_come_from_the_bag(self):
        closure = await _closure_for("_register_manage_tools")

        arguments = await _arguments_from(closure, action="list", params={"page": 3, "size": 5})

        assert (arguments["page"], arguments["size"]) == (3, 5)

    async def test_manage_alerts_paging_and_resource_type_can_come_from_the_bag(self):
        closure = await _closure_for("_register_manage_alerts")

        arguments = await _arguments_from(
            closure, action="list", params={"page": 3, "size": 5, "resource_type": "alerts"}
        )

        assert (arguments["page"], arguments["size"]) == (3, 5)
        assert arguments["resource_type"] == "alerts"

    async def test_a_top_level_value_still_beats_the_bag(self):
        closure = await _closure_for("_register_manage_alerts")

        arguments = await _arguments_from(
            closure,
            action="list",
            page=1,
            resource_type="anomalies",
            params={"page": 3, "resource_type": "alerts"},
        )

        assert arguments["page"] == 1
        assert arguments["resource_type"] == "anomalies"

    async def test_a_bagged_page_string_is_still_coerced(self):
        """The bag bypasses pydantic, so the closure has to do the coercion."""
        closure = await _closure_for("_register_manage_alerts")

        arguments = await _arguments_from(closure, action="list", params={"page": "3"})

        assert arguments["page"] == 3


# ---------------------------------------------------------------------------
# JSON-string decoding has to see the merged values, not the named ones
# ---------------------------------------------------------------------------


async def _text_from(closure, **kwargs):
    """Call a closure that is expected to refuse, and return its message."""
    with patch(
        "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
        new=AsyncMock(return_value=[]),
    ):
        result = await closure(**kwargs)
    return result[0].text if result else ""


@pytest.mark.asyncio
class TestBaggedJsonStringsAreDecoded:
    async def test_manage_alerts_decodes_anomaly_data_from_the_bag(self):
        closure = await _closure_for("_register_manage_alerts")

        arguments = await _arguments_from(
            closure, action="create", params={"anomaly_data": '{"name": "Alert"}'}
        )

        assert arguments["anomaly_data"] == {"name": "Alert"}

    async def test_manage_alerts_decodes_anomaly_ids_from_the_bag(self):
        closure = await _closure_for("_register_manage_alerts")

        arguments = await _arguments_from(
            closure, action="get_budget_progress", params={"anomaly_ids": '["a1", "a2"]'}
        )

        assert arguments["anomaly_ids"] == ["a1", "a2"]

    async def test_malformed_bagged_anomaly_data_is_still_refused(self):
        closure = await _closure_for("_register_manage_alerts")

        text = await _text_from(closure, action="create", params={"anomaly_data": "{not json"})

        assert "Invalid JSON String for anomaly_data" in text

    async def test_a_bagged_anomaly_ids_scalar_is_still_refused(self):
        closure = await _closure_for("_register_manage_alerts")

        text = await _text_from(
            closure, action="get_budget_progress", params={"anomaly_ids": '"a1"'}
        )

        assert "Invalid anomaly_ids" in text

    async def test_manage_tools_decodes_filters_from_the_bag(self):
        closure = await _closure_for("_register_manage_tools")

        arguments = await _arguments_from(
            closure, action="list", params={"filters": '{"toolType": "MCP"}'}
        )

        assert arguments["filters"] == {"toolType": "MCP"}

    async def test_manage_tools_refuses_an_empty_filters_string(self):
        """`filters or {}` used to swallow this before the decode could refuse it."""
        closure = await _closure_for("_register_manage_tools")

        assert "Invalid JSON for filters" in await _text_from(closure, action="list", filters="")

    async def test_manage_tools_refuses_an_empty_filters_string_from_the_bag(self):
        closure = await _closure_for("_register_manage_tools")

        text = await _text_from(closure, action="list", params={"filters": ""})

        assert "Invalid JSON for filters" in text

    async def test_manage_tools_decodes_tool_data_from_the_bag(self):
        closure = await _closure_for("_register_manage_tools")

        arguments = await _arguments_from(
            closure, action="create", params={"tool_data": '{"name": "My Tool"}'}
        )

        assert arguments["tool_data"] == {"name": "My Tool"}

    async def test_manage_tools_decodes_event_data_from_the_bag(self):
        closure = await _closure_for("_register_manage_tools")

        arguments = await _arguments_from(
            closure, action="meter_event", params={"event_data": '{"type": "invocation"}'}
        )

        assert arguments["event_data"] == {"type": "invocation"}

    async def test_malformed_bagged_tool_data_is_still_refused(self):
        closure = await _closure_for("_register_manage_tools")

        text = await _text_from(closure, action="create", params={"tool_data": "{not json"})

        assert "Invalid JSON for tool_data" in text

    async def test_malformed_bagged_event_data_is_still_refused(self):
        closure = await _closure_for("_register_manage_tools")

        text = await _text_from(closure, action="meter_event", params={"event_data": ""})

        assert "Invalid JSON for event_data" in text
