"""Tests for common/validation.py — parameter validation and preprocessing."""

import pytest

from src.revenium_mcp_server.common.validation import (
    validate_required_params,
    validate_id_format,
    preprocess_numeric_parameters,
    preprocess_boolean_parameters,
    preprocess_array_parameters,
    validate_pagination_params,
    validate_string_params,
)
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.exceptions import ValidationError


# ---------------------------------------------------------------------------
# validate_required_params
# ---------------------------------------------------------------------------

class TestValidateRequiredParams:
    def test_all_present_no_error(self):
        validate_required_params({"a": 1, "b": 2}, ["a", "b"])

    def test_missing_field_raises(self):
        with pytest.raises(ValidationError, match="Missing required"):
            validate_required_params({"a": 1}, ["a", "b"])

    def test_none_value_treated_as_missing(self):
        with pytest.raises(ValidationError, match="b"):
            validate_required_params({"a": 1, "b": None}, ["a", "b"])

    def test_empty_required_list_passes(self):
        validate_required_params({}, [])


# ---------------------------------------------------------------------------
# validate_id_format
# ---------------------------------------------------------------------------

class TestValidateIdFormat:
    def test_valid_string_id(self):
        assert validate_id_format("abc-123") == "abc-123"

    def test_numeric_id_converted_to_string(self):
        assert validate_id_format(42) == "42"

    def test_empty_string_raises(self):
        with pytest.raises(ValidationError):
            validate_id_format("")

    def test_none_raises(self):
        with pytest.raises(ValidationError):
            validate_id_format(None)

    def test_whitespace_only_raises(self):
        with pytest.raises(ValidationError):
            validate_id_format("   ")

    def test_strips_whitespace(self):
        assert validate_id_format("  abc  ") == "abc"

    def test_custom_field_name_in_error(self):
        with pytest.raises(ValidationError, match="product_id"):
            validate_id_format("", field_name="product_id")


# ---------------------------------------------------------------------------
# preprocess_numeric_parameters
# ---------------------------------------------------------------------------

class TestPreprocessNumericParameters:
    def test_string_to_int(self):
        result = preprocess_numeric_parameters(
            {"page": "3", "name": "test"},
            {"page": int},
        )
        assert result["page"] == 3
        assert result["name"] == "test"

    def test_string_to_float(self):
        result = preprocess_numeric_parameters(
            {"threshold": "99.5"},
            {"threshold": float},
        )
        assert result["threshold"] == 99.5

    def test_invalid_numeric_kept_as_string(self):
        result = preprocess_numeric_parameters(
            {"page": "not-a-number"},
            {"page": int},
        )
        assert result["page"] == "not-a-number"

    def test_none_value_skipped(self):
        result = preprocess_numeric_parameters(
            {"page": None},
            {"page": int},
        )
        assert result["page"] is None

    def test_already_numeric_untouched(self):
        result = preprocess_numeric_parameters(
            {"page": 5},
            {"page": int},
        )
        assert result["page"] == 5

    def test_missing_param_ignored(self):
        result = preprocess_numeric_parameters(
            {"name": "test"},
            {"page": int},
        )
        assert "page" not in result

    def test_original_not_modified(self):
        original = {"page": "1"}
        preprocess_numeric_parameters(original, {"page": int})
        assert original["page"] == "1"


# ---------------------------------------------------------------------------
# preprocess_boolean_parameters
# ---------------------------------------------------------------------------

class TestPreprocessBooleanParameters:
    @pytest.mark.parametrize("input_val,expected", [
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("enabled", True),
        ("false", False),
        ("False", False),
        ("0", False),
        ("no", False),
        ("off", False),
        ("disabled", False),
    ])
    def test_string_conversions(self, input_val, expected):
        result = preprocess_boolean_parameters(
            {"flag": input_val},
            ["flag"],
        )
        assert result["flag"] is expected

    def test_unrecognized_string_kept_as_is(self):
        result = preprocess_boolean_parameters(
            {"flag": "maybe"},
            ["flag"],
        )
        assert result["flag"] == "maybe"

    def test_none_value_skipped(self):
        result = preprocess_boolean_parameters({"flag": None}, ["flag"])
        assert result["flag"] is None

    def test_already_bool_untouched(self):
        result = preprocess_boolean_parameters({"flag": True}, ["flag"])
        assert result["flag"] is True

    def test_non_target_params_unchanged(self):
        result = preprocess_boolean_parameters(
            {"flag": "true", "name": "test"},
            ["flag"],
        )
        assert result["name"] == "test"


# ---------------------------------------------------------------------------
# preprocess_array_parameters
# ---------------------------------------------------------------------------

class TestPreprocessArrayParameters:
    def test_json_array_string_parsed(self):
        result = preprocess_array_parameters(
            {"dims": '["a", "b"]'},
            ["dims"],
        )
        assert result["dims"] == ["a", "b"]

    def test_invalid_json_kept_as_string(self):
        result = preprocess_array_parameters(
            {"dims": "not-json"},
            ["dims"],
        )
        assert result["dims"] == "not-json"

    def test_json_non_array_kept_as_string(self):
        """If JSON parses to a dict, keep the original string."""
        result = preprocess_array_parameters(
            {"dims": '{"key": "val"}'},
            ["dims"],
        )
        assert result["dims"] == '{"key": "val"}'

    def test_already_list_untouched(self):
        result = preprocess_array_parameters(
            {"dims": [1, 2, 3]},
            ["dims"],
        )
        assert result["dims"] == [1, 2, 3]

    def test_none_skipped(self):
        result = preprocess_array_parameters({"dims": None}, ["dims"])
        assert result["dims"] is None

    def test_missing_param_ignored(self):
        result = preprocess_array_parameters({"x": 1}, ["dims"])
        assert "dims" not in result


# ---------------------------------------------------------------------------
# validate_pagination_params (BACK-1097)
# ---------------------------------------------------------------------------

class TestValidatePaginationParams:
    def test_int_values_pass_through(self):
        result = validate_pagination_params({"page": 0, "size": 20}, action="list")
        assert result["page"] == 0
        assert result["size"] == 20

    def test_string_digits_coerced_to_int(self):
        result = validate_pagination_params({"page": "3", "size": "10"}, action="list")
        assert result["page"] == 3
        assert result["size"] == 10

    def test_string_with_whitespace_coerced(self):
        result = validate_pagination_params({"page": " 2 "}, action="list")
        assert result["page"] == 2

    def test_missing_keys_pass_through(self):
        result = validate_pagination_params({"other": "x"}, action="list")
        assert result == {"other": "x"}

    def test_none_values_skipped(self):
        result = validate_pagination_params({"page": None, "size": None}, action="list")
        assert result["page"] is None
        assert result["size"] is None

    def test_non_numeric_string_raises_tool_error(self):
        with pytest.raises(ToolError) as exc:
            validate_pagination_params({"page": "not_a_number"}, action="list tools")
        assert exc.value.field == "page"
        assert "not_a_number" in str(exc.value.message)
        # Every suggestion should mention the action name so the user can tell
        # which call failed (BACK-1097 review follow-up).
        assert exc.value.suggestions, "expected at least one suggestion"
        for suggestion in exc.value.suggestions:
            assert "list tools" in suggestion

    def test_negative_page_raises(self):
        with pytest.raises(ToolError) as exc:
            validate_pagination_params({"page": -1}, action="list")
        assert exc.value.field == "page"

    def test_size_below_minimum_raises(self):
        with pytest.raises(ToolError) as exc:
            validate_pagination_params({"size": 0}, action="list")
        assert exc.value.field == "size"

    def test_size_above_maximum_raises(self):
        with pytest.raises(ToolError) as exc:
            validate_pagination_params({"size": 101}, action="list")
        assert exc.value.field == "size"

    def test_bool_rejected(self):
        """True/False are int subclasses in Python — should be rejected, not coerced."""
        with pytest.raises(ToolError) as exc:
            validate_pagination_params({"page": True}, action="list")
        assert exc.value.field == "page"

    def test_float_rejected(self):
        with pytest.raises(ToolError) as exc:
            validate_pagination_params({"page": 1.5}, action="list")
        assert exc.value.field == "page"

    def test_does_not_mutate_input(self):
        original = {"page": "5"}
        validate_pagination_params(original, action="list")
        assert original == {"page": "5"}

    def test_overlong_digit_string_rejected_without_int_overflow_attempt(self):
        """Very long digit strings must be rejected via the length guard, not
        passed to int(). On Python < 3.11.4, int("9" * 1_000_000) would saturate
        CPU (CVE-2020-10735); the guard short-circuits to a ToolError instead.
        """
        huge_digits = "9" * 1000
        with pytest.raises(ToolError) as exc:
            validate_pagination_params({"page": huge_digits}, action="list")
        assert exc.value.field == "page"

    def test_page_upper_bound_rejects_max_int(self):
        with pytest.raises(ToolError) as exc:
            validate_pagination_params({"page": 2147483647}, action="list")
        assert exc.value.field == "page"
        assert "[0, 10000]" in exc.value.message

    def test_page_at_upper_bound_accepted(self):
        result = validate_pagination_params({"page": 10000}, action="list")
        assert result["page"] == 10000

    def test_page_above_upper_bound_rejected(self):
        with pytest.raises(ToolError) as exc:
            validate_pagination_params({"page": 10001}, action="list")
        assert exc.value.field == "page"

    def test_safe_integer_overflow_does_not_echo_corrupted_value(self):
        over_safe = 2**53 + 1
        with pytest.raises(ToolError) as exc:
            validate_pagination_params({"page": over_safe}, action="list")
        assert "safe integer range" in exc.value.message
        assert str(over_safe) not in exc.value.message

    def test_safe_integer_overflow_on_size(self):
        over_safe = 2**53 + 1
        with pytest.raises(ToolError) as exc:
            validate_pagination_params({"size": over_safe}, action="list")
        assert "safe integer range" in exc.value.message
        assert str(over_safe) not in exc.value.message

    def test_safe_integer_value_stored_for_debug(self):
        over_safe = 2**53 + 1
        with pytest.raises(ToolError) as exc:
            validate_pagination_params({"page": over_safe}, action="list")
        assert exc.value.value == str(over_safe)


class TestValidateStringParams:
    """Reject non-string values on string-typed fields so callers see a
    structured ToolError instead of a raw Pydantic `string_type` leak."""

    def test_all_strings_pass_through_unchanged(self):
        args = {"tool_id": "abc123", "tool_name": "MyTool", "action": "get"}
        result = validate_string_params(args, ["tool_id", "tool_name"], action="get")
        assert result == args

    def test_missing_fields_are_ignored(self):
        result = validate_string_params({"action": "list"}, ["tool_id"], action="list")
        assert result == {"action": "list"}

    def test_none_values_are_ignored(self):
        result = validate_string_params({"tool_id": None}, ["tool_id"], action="get")
        assert result == {"tool_id": None}

    def test_int_raises_tool_error_with_field_context(self):
        with pytest.raises(ToolError) as exc:
            validate_string_params({"tool_id": 12345}, ["tool_id"], action="get")
        assert exc.value.field == "tool_id"
        assert "string" in exc.value.message.lower()
        assert "12345" in exc.value.message

    def test_float_raises(self):
        with pytest.raises(ToolError) as exc:
            validate_string_params({"tool_id": 1.5}, ["tool_id"], action="get")
        assert exc.value.field == "tool_id"

    def test_bool_raises(self):
        """Python booleans are int subclasses; must reject explicitly to avoid
        silent coercion into 'True'/'False'."""
        with pytest.raises(ToolError) as exc:
            validate_string_params({"tool_id": True}, ["tool_id"], action="get")
        assert exc.value.field == "tool_id"

    def test_error_message_mentions_action(self):
        with pytest.raises(ToolError) as exc:
            validate_string_params({"tool_id": 42}, ["tool_id"], action="get tool")
        assert "get tool" in " ".join(exc.value.suggestions or []).lower() or "get tool" in exc.value.message.lower()

    def test_original_dict_not_mutated(self):
        original = {"tool_id": "abc"}
        validate_string_params(original, ["tool_id"], action="get")
        assert original == {"tool_id": "abc"}

    def test_empty_string_still_passes(self):
        """Semantic validity (empty not allowed) is enforced downstream, not here."""
        result = validate_string_params({"tool_id": ""}, ["tool_id"], action="get")
        assert result["tool_id"] == ""
