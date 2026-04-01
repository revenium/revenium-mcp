"""Tests for common/validation.py — parameter validation and preprocessing."""

import json
import pytest

from src.revenium_mcp_server.common.validation import (
    validate_required_params,
    validate_id_format,
    preprocess_numeric_parameters,
    preprocess_boolean_parameters,
    preprocess_array_parameters,
)
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
