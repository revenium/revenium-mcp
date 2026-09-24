"""Unit tests for the get_capabilities parameter reference (BACK-3170).

The thin-schema tools no longer advertise their per-action parameters, so
this rendering is the only place a caller sees a parameter's type and its
accepted values. A union carries both on its branches rather than at the top
level, which is what most of these cases pin.
"""

import pytest

from src.revenium_mcp_server.tools_decomposed.unified_tool_base import (
    _PARAMETER_DESCRIPTION_MAX,
    _format_parameter_line,
    _format_parameter_type,
)


class TestFormatParameterType:
    def test_plain_scalar(self):
        assert _format_parameter_type({"type": "string"}) == "string"

    def test_array_names_its_item_type(self):
        assert _format_parameter_type({"type": "array", "items": {"type": "string"}}) == (
            "array of string"
        )

    def test_array_without_items_is_just_an_array(self):
        assert _format_parameter_type({"type": "array"}) == "array"

    def test_one_of_branches_are_named(self):
        assert _format_parameter_type(
            {"oneOf": [{"type": "boolean"}, {"type": "string"}]}
        ) == "boolean or string"

    def test_any_of_branches_are_named(self):
        assert _format_parameter_type(
            {"anyOf": [{"type": "boolean"}, {"type": "string"}]}
        ) == "boolean or string"

    def test_the_null_branch_is_not_a_type_a_caller_sends(self):
        assert _format_parameter_type(
            {"anyOf": [{"type": "string"}, {"type": "null"}]}
        ) == "string"

    def test_an_array_branch_keeps_its_item_type(self):
        assert _format_parameter_type(
            {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}]}
        ) == "array of string or string"

    def test_repeated_branch_types_are_named_once(self):
        assert _format_parameter_type(
            {"oneOf": [{"type": "string", "enum": ["a"]}, {"type": "string", "enum": ["b"]}]}
        ) == "string"

    def test_a_type_list_is_named_the_same_way(self):
        assert _format_parameter_type({"type": ["string", "null"]}) == "string"

    def test_a_property_with_nothing_to_go_on_is_any(self):
        assert _format_parameter_type({}) == "any"


class TestFormatParameterLine:
    def test_name_type_and_description(self):
        assert _format_parameter_line("model", {"type": "string", "description": "AI model"}) == (
            "- `model` (string) - AI model"
        )

    def test_top_level_enum_is_listed(self):
        assert _format_parameter_line("group", {"type": "string", "enum": ["TOTAL", "MEAN"]}) == (
            "- `group` (string): one of TOTAL, MEAN"
        )

    def test_a_branch_nested_enum_still_surfaces(self):
        """manage_metering's return_transaction_data shape: the values are on a branch."""
        line = _format_parameter_line(
            "return_transaction_data",
            {
                "oneOf": [
                    {"type": "boolean", "description": "true=full, false=no"},
                    {"type": "string", "enum": ["no", "summary", "full"]},
                ],
                "default": "no",
                "description": "Transaction data detail level",
            },
        )
        assert line == (
            "- `return_transaction_data` (boolean or string): one of no, summary, full"
            " - Transaction data detail level"
        )

    def test_values_from_several_branches_are_merged_in_order(self):
        line = _format_parameter_line(
            "mode",
            {"anyOf": [{"type": "string", "enum": ["a", "b"]}, {"type": "string", "enum": ["b", "c"]}]},
        )
        assert line == "- `mode` (string): one of a, b, c"

    def test_a_nullable_union_reads_as_the_type_it_accepts(self):
        line = _format_parameter_line(
            "slim", {"anyOf": [{"type": "boolean"}, {"type": "null"}], "description": "Slim output"}
        )
        assert line == "- `slim` (boolean) - Slim output"

    def test_an_array_union_names_its_item_type(self):
        line = _format_parameter_line(
            "anomaly_ids",
            {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}]},
        )
        assert line == "- `anomaly_ids` (array of string or string)"

    def test_a_long_description_is_truncated_on_a_word_boundary(self):
        line = _format_parameter_line(
            "x", {"type": "string", "description": "word " * 100}
        )
        assert line.endswith("...")
        assert len(line) < _PARAMETER_DESCRIPTION_MAX + 40

    def test_whitespace_in_a_description_is_collapsed(self):
        line = _format_parameter_line("x", {"type": "string", "description": "a\n   b"})
        assert line == "- `x` (string) - a b"

    def test_a_non_object_property_still_renders(self):
        assert _format_parameter_line("x", "not-a-schema") == "- `x`"


@pytest.mark.asyncio
class TestAnalyticsValueListsHaveOneSource:
    """Both capabilities renderings quote the same lists, so they must agree."""

    async def test_the_two_renderings_agree(self):
        from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
            AGGREGATION_VALUES,
            COST_PERIOD_VALUES,
            BusinessAnalyticsManagement,
        )

        result = await BusinessAnalyticsManagement(ucm_helper=None).handle_action(
            "get_capabilities", {}
        )
        text = "\n".join(part.text for part in result)

        periods = ", ".join(COST_PERIOD_VALUES)
        aggregations = ", ".join(AGGREGATION_VALUES)
        assert f"**Time Periods**: {periods}" in text
        assert f"**Aggregations**: {aggregations}" in text
        # The generated reference quotes the same two lists.
        assert periods in text.split("## Parameters", 1)[1]
        assert f"one of {aggregations}" in text
