"""Unit tests for MeteringTransactionManager async validation pipeline.

Covers _validate_fast_checks, _validate_required_fields, _validate_numeric_fields,
_validate_string_fields, _validate_optional_fields, _validate_boolean_fields,
_validate_float_fields, _validate_timestamp_fields, _validate_special_fields,
_validate_transaction_inputs_async, and _validate_transaction_inputs_with_details.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed.metering_management import (
    MeteringTransactionManager,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

VALID_TX = {
    "model": "gpt-4",
    "provider": "OPENAI",
    "input_tokens": 1500,
    "output_tokens": 800,
    "duration_ms": 2500,
}


def _mgr() -> MeteringTransactionManager:
    return MeteringTransactionManager()


# ===========================================================================
# _validate_fast_checks
# ===========================================================================


class TestValidateFastChecks:
    """Fast-fail guard: old subscriber format, task_id, missing fields, type checks."""

    @pytest.mark.asyncio
    async def test_valid_args_returns_none(self):
        mgr = _mgr()
        result = await mgr._validate_fast_checks(VALID_TX.copy())
        assert result is None

    @pytest.mark.asyncio
    async def test_old_subscriber_email_fails(self):
        mgr = _mgr()
        args = {**VALID_TX, "subscriber_email": "old@example.com"}
        result = await mgr._validate_fast_checks(args)
        assert result is not None
        assert "subscriber" in result.lower() or "SUBSCRIBER" in result

    @pytest.mark.asyncio
    async def test_old_subscriber_id_fails(self):
        mgr = _mgr()
        args = {**VALID_TX, "subscriber_id": "u123"}
        result = await mgr._validate_fast_checks(args)
        assert result is not None
        assert "subscriber" in result.lower() or "SUBSCRIBER" in result

    @pytest.mark.asyncio
    async def test_task_id_field_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "task_id": "t1"}
        result = await mgr._validate_fast_checks(args)
        assert result is not None
        assert "task_id" in result

    @pytest.mark.asyncio
    async def test_missing_model_fails(self):
        mgr = _mgr()
        args = VALID_TX.copy()
        del args["model"]
        result = await mgr._validate_fast_checks(args)
        assert result is not None
        assert "MISSING" in result or "missing" in result.lower()

    @pytest.mark.asyncio
    async def test_none_model_fails(self):
        mgr = _mgr()
        args = {**VALID_TX, "model": None}
        result = await mgr._validate_fast_checks(args)
        assert result is not None
        assert "model" in result.lower() or "MISSING" in result

    @pytest.mark.asyncio
    async def test_missing_multiple_fields_lists_all(self):
        mgr = _mgr()
        result = await mgr._validate_fast_checks({})
        assert result is not None
        assert "model" in result
        assert "provider" in result

    @pytest.mark.asyncio
    async def test_non_string_model_fails(self):
        mgr = _mgr()
        args = {**VALID_TX, "model": 42}
        result = await mgr._validate_fast_checks(args)
        assert result is not None
        assert "model" in result.lower()
        assert "string" in result.lower()

    @pytest.mark.asyncio
    async def test_non_string_provider_fails(self):
        mgr = _mgr()
        args = {**VALID_TX, "provider": 99}
        result = await mgr._validate_fast_checks(args)
        assert result is not None
        assert "provider" in result.lower()


# ===========================================================================
# _validate_required_fields
# ===========================================================================


class TestValidateRequiredFields:
    """Required field presence and empty-string detection."""

    @pytest.mark.asyncio
    async def test_all_present_no_errors(self):
        mgr = _mgr()
        errors = await mgr._validate_required_fields(VALID_TX.copy())
        assert errors == []

    @pytest.mark.asyncio
    async def test_missing_field_reported(self):
        mgr = _mgr()
        args = VALID_TX.copy()
        del args["model"]
        errors = await mgr._validate_required_fields(args)
        assert any("model" in e for e in errors)

    @pytest.mark.asyncio
    async def test_none_field_reported(self):
        mgr = _mgr()
        args = {**VALID_TX, "provider": None}
        errors = await mgr._validate_required_fields(args)
        assert any("provider" in e for e in errors)

    @pytest.mark.asyncio
    async def test_empty_string_reported(self):
        mgr = _mgr()
        args = {**VALID_TX, "model": "   "}
        errors = await mgr._validate_required_fields(args)
        assert any("empty" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_all_missing_gives_five_errors(self):
        mgr = _mgr()
        errors = await mgr._validate_required_fields({})
        assert len(errors) == 5


# ===========================================================================
# _validate_numeric_fields
# ===========================================================================


class TestValidateNumericFields:

    @pytest.mark.asyncio
    async def test_valid_ints_no_errors(self):
        mgr = _mgr()
        errors = await mgr._validate_numeric_fields(VALID_TX.copy())
        assert errors == []

    @pytest.mark.asyncio
    async def test_string_convertible_to_int(self):
        mgr = _mgr()
        args = {**VALID_TX, "input_tokens": "500"}
        errors = await mgr._validate_numeric_fields(args)
        assert errors == []
        assert args["input_tokens"] == 500

    @pytest.mark.asyncio
    async def test_non_convertible_string(self):
        mgr = _mgr()
        args = {**VALID_TX, "output_tokens": "abc"}
        errors = await mgr._validate_numeric_fields(args)
        assert any("Cannot convert" in e for e in errors)

    @pytest.mark.asyncio
    async def test_non_int_type_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "duration_ms": [100]}
        errors = await mgr._validate_numeric_fields(args)
        assert any("Expected integer" in e for e in errors)

    @pytest.mark.asyncio
    async def test_negative_value_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "input_tokens": -5}
        errors = await mgr._validate_numeric_fields(args)
        assert any("positive" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_value_over_10m_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "output_tokens": 10_000_001}
        errors = await mgr._validate_numeric_fields(args)
        assert any("too large" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_exactly_10m_passes(self):
        mgr = _mgr()
        args = {**VALID_TX, "input_tokens": 10_000_000}
        errors = await mgr._validate_numeric_fields(args)
        assert not any("input_tokens" in e for e in errors)

    @pytest.mark.asyncio
    async def test_zero_value_passes(self):
        mgr = _mgr()
        args = {**VALID_TX, "input_tokens": 0}
        errors = await mgr._validate_numeric_fields(args)
        assert not any("input_tokens" in e for e in errors)

    @pytest.mark.asyncio
    async def test_float_type_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "duration_ms": 2.5}
        errors = await mgr._validate_numeric_fields(args)
        assert any("Expected integer" in e for e in errors)


# ===========================================================================
# _validate_string_fields
# ===========================================================================


class TestValidateStringFields:

    @pytest.mark.asyncio
    async def test_valid_strings_no_errors(self):
        mgr = _mgr()
        errors = await mgr._validate_string_fields(VALID_TX.copy())
        assert errors == []

    @pytest.mark.asyncio
    async def test_non_string_model(self):
        mgr = _mgr()
        args = {**VALID_TX, "model": 123}
        errors = await mgr._validate_string_fields(args)
        assert any("Expected string" in e for e in errors)

    @pytest.mark.asyncio
    async def test_empty_string_provider(self):
        mgr = _mgr()
        args = {**VALID_TX, "provider": "  "}
        errors = await mgr._validate_string_fields(args)
        assert any("empty" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_too_long_string(self):
        mgr = _mgr()
        args = {**VALID_TX, "model": "x" * 201}
        errors = await mgr._validate_string_fields(args)
        assert any("Too long" in e for e in errors)

    @pytest.mark.asyncio
    async def test_injection_chars_rejected(self):
        mgr = _mgr()
        for char in ["<", ">", '"', "'", "&"]:
            args = {**VALID_TX, "model": f"gpt{char}4"}
            errors = await mgr._validate_string_fields(args)
            assert any("invalid characters" in e.lower() for e in errors), f"Failed for char: {char}"

    @pytest.mark.asyncio
    async def test_exactly_200_chars_passes(self):
        mgr = _mgr()
        args = {**VALID_TX, "model": "a" * 200}
        errors = await mgr._validate_string_fields(args)
        assert not any("Too long" in e for e in errors)


# ===========================================================================
# _validate_optional_fields
# ===========================================================================


class TestValidateOptionalFields:

    @pytest.mark.asyncio
    async def test_no_optional_fields_no_errors(self):
        mgr = _mgr()
        errors = await mgr._validate_optional_fields(VALID_TX.copy())
        assert errors == []

    @pytest.mark.asyncio
    async def test_valid_optional_string(self):
        mgr = _mgr()
        args = {**VALID_TX, "organization_id": "org_123"}
        errors = await mgr._validate_optional_fields(args)
        assert errors == []

    @pytest.mark.asyncio
    async def test_optional_string_non_string_type(self):
        mgr = _mgr()
        args = {**VALID_TX, "task_type": 42}
        errors = await mgr._validate_optional_fields(args)
        assert any("task_type" in e and "Expected string" in e for e in errors)

    @pytest.mark.asyncio
    async def test_optional_string_empty(self):
        mgr = _mgr()
        args = {**VALID_TX, "agent": "  "}
        errors = await mgr._validate_optional_fields(args)
        assert any("agent" in e and "empty" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_optional_string_too_long(self):
        mgr = _mgr()
        args = {**VALID_TX, "trace_id": "x" * 501}
        errors = await mgr._validate_optional_fields(args)
        assert any("trace_id" in e and "Too long" in e for e in errors)

    @pytest.mark.asyncio
    async def test_optional_string_injection_chars(self):
        mgr = _mgr()
        args = {**VALID_TX, "stop_reason": "reason<script>"}
        errors = await mgr._validate_optional_fields(args)
        assert any("stop_reason" in e and "invalid characters" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_none_optional_field_ignored(self):
        mgr = _mgr()
        args = {**VALID_TX, "organization_id": None}
        errors = await mgr._validate_optional_fields(args)
        assert errors == []

    # -- trace string fields from usage_metadata --

    @pytest.mark.asyncio
    async def test_trace_field_from_top_level(self):
        mgr = _mgr()
        args = {**VALID_TX, "environment": "production"}
        errors = await mgr._validate_optional_fields(args)
        assert errors == []

    @pytest.mark.asyncio
    async def test_trace_field_from_usage_metadata(self):
        mgr = _mgr()
        args = {**VALID_TX, "usage_metadata": {"environment": "staging"}}
        errors = await mgr._validate_optional_fields(args)
        assert errors == []

    @pytest.mark.asyncio
    async def test_trace_field_non_string_in_usage_metadata(self):
        mgr = _mgr()
        args = {**VALID_TX, "usage_metadata": {"region": 42}}
        errors = await mgr._validate_optional_fields(args)
        assert any("usage_metadata.region" in e for e in errors)

    @pytest.mark.asyncio
    async def test_trace_field_empty_string(self):
        mgr = _mgr()
        args = {**VALID_TX, "environment": "  "}
        errors = await mgr._validate_optional_fields(args)
        assert any("environment" in e and "empty" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_trace_field_too_long(self):
        mgr = _mgr()
        args = {**VALID_TX, "region": "r" * 501}
        errors = await mgr._validate_optional_fields(args)
        assert any("region" in e and "Too long" in e for e in errors)

    @pytest.mark.asyncio
    async def test_trace_field_injection_chars(self):
        mgr = _mgr()
        args = {**VALID_TX, "credential_alias": "key&val"}
        errors = await mgr._validate_optional_fields(args)
        assert any("credential_alias" in e and "invalid characters" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_camel_case_alias_works(self):
        mgr = _mgr()
        args = {**VALID_TX, "credentialAlias": "my-key"}
        errors = await mgr._validate_optional_fields(args)
        assert errors == []

    @pytest.mark.asyncio
    async def test_top_level_takes_priority_over_usage_metadata(self):
        mgr = _mgr()
        # Top-level value is invalid, usage_metadata value is valid
        # Top-level should be checked first
        args = {**VALID_TX, "environment": 42, "usage_metadata": {"environment": "prod"}}
        errors = await mgr._validate_optional_fields(args)
        assert any("environment" in e and "Expected string" in e for e in errors)

    # -- operation_type --

    @pytest.mark.asyncio
    async def test_operation_type_valid(self):
        mgr = _mgr()
        args = {**VALID_TX, "operation_type": "CHAT"}
        errors = await mgr._validate_optional_fields(args)
        assert not any("operation_type" in e for e in errors)

    @pytest.mark.asyncio
    async def test_operation_type_non_string(self):
        mgr = _mgr()
        args = {**VALID_TX, "operation_type": 123}
        errors = await mgr._validate_optional_fields(args)
        assert any("operation_type" in e for e in errors)

    @pytest.mark.asyncio
    async def test_operation_type_empty(self):
        mgr = _mgr()
        args = {**VALID_TX, "operation_type": "  "}
        errors = await mgr._validate_optional_fields(args)
        assert any("operation_type" in e and "empty" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_operation_type_from_usage_metadata(self):
        mgr = _mgr()
        args = {**VALID_TX, "usage_metadata": {"operationType": "EMBEDDING"}}
        errors = await mgr._validate_optional_fields(args)
        assert not any("operation" in e.lower() for e in errors)

    # -- trace_type --

    @pytest.mark.asyncio
    async def test_trace_type_valid(self):
        mgr = _mgr()
        args = {**VALID_TX, "trace_type": "llm-call"}
        errors = await mgr._validate_optional_fields(args)
        assert errors == []

    @pytest.mark.asyncio
    async def test_trace_type_non_string(self):
        mgr = _mgr()
        args = {**VALID_TX, "trace_type": 99}
        errors = await mgr._validate_optional_fields(args)
        assert any("trace_type" in e for e in errors)

    @pytest.mark.asyncio
    async def test_trace_type_too_long(self):
        mgr = _mgr()
        args = {**VALID_TX, "trace_type": "t" * 129}
        errors = await mgr._validate_optional_fields(args)
        assert any("trace_type" in e and "Too long" in e for e in errors)

    @pytest.mark.asyncio
    async def test_trace_type_invalid_chars(self):
        mgr = _mgr()
        args = {**VALID_TX, "trace_type": "type with spaces"}
        errors = await mgr._validate_optional_fields(args)
        assert any("trace_type" in e and "alphanumeric" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_trace_type_allows_hyphens_underscores(self):
        mgr = _mgr()
        args = {**VALID_TX, "trace_type": "my-type_v2"}
        errors = await mgr._validate_optional_fields(args)
        assert not any("trace_type" in e for e in errors)

    @pytest.mark.asyncio
    async def test_trace_type_camelcase_alias(self):
        mgr = _mgr()
        args = {**VALID_TX, "traceType": "llm-call"}
        errors = await mgr._validate_optional_fields(args)
        assert errors == []

    @pytest.mark.asyncio
    async def test_trace_type_from_usage_metadata(self):
        mgr = _mgr()
        args = {**VALID_TX, "usage_metadata": {"traceType": "agent-step"}}
        errors = await mgr._validate_optional_fields(args)
        assert errors == []

    # -- retry_number --

    @pytest.mark.asyncio
    async def test_retry_number_valid_int(self):
        mgr = _mgr()
        args = {**VALID_TX, "retry_number": 3}
        errors = await mgr._validate_optional_fields(args)
        assert not any("retry_number" in e for e in errors)

    @pytest.mark.asyncio
    async def test_retry_number_valid_string(self):
        mgr = _mgr()
        args = {**VALID_TX, "retry_number": "2"}
        errors = await mgr._validate_optional_fields(args)
        assert not any("retry_number" in e for e in errors)

    @pytest.mark.asyncio
    async def test_retry_number_negative(self):
        mgr = _mgr()
        args = {**VALID_TX, "retry_number": -1}
        errors = await mgr._validate_optional_fields(args)
        assert any("retry_number" in e and "non-negative" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_retry_number_non_convertible(self):
        mgr = _mgr()
        args = {**VALID_TX, "retry_number": "abc"}
        errors = await mgr._validate_optional_fields(args)
        assert any("retry_number" in e for e in errors)

    @pytest.mark.asyncio
    async def test_retry_number_from_usage_metadata(self):
        mgr = _mgr()
        args = {**VALID_TX, "usage_metadata": {"retryNumber": 1}}
        errors = await mgr._validate_optional_fields(args)
        assert not any("retry" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_usage_metadata_non_dict_ignored(self):
        mgr = _mgr()
        args = {**VALID_TX, "usage_metadata": "not_a_dict"}
        errors = await mgr._validate_optional_fields(args)
        # Should not crash; usage_metadata is ignored when not a dict
        assert isinstance(errors, list)
        assert not any("usage_metadata" in e for e in errors)


# ===========================================================================
# _validate_boolean_fields
# ===========================================================================


class TestValidateBooleanFields:

    @pytest.mark.asyncio
    async def test_true_bool_passes(self):
        mgr = _mgr()
        args = {**VALID_TX, "is_streamed": True}
        errors = await mgr._validate_boolean_fields(args)
        assert errors == []

    @pytest.mark.asyncio
    async def test_false_bool_passes(self):
        mgr = _mgr()
        args = {**VALID_TX, "is_streamed": False}
        errors = await mgr._validate_boolean_fields(args)
        assert errors == []

    @pytest.mark.asyncio
    async def test_string_true_coerced(self):
        mgr = _mgr()
        args = {**VALID_TX, "is_streamed": "true"}
        errors = await mgr._validate_boolean_fields(args)
        assert errors == []
        assert args["is_streamed"] is True

    @pytest.mark.asyncio
    async def test_string_false_coerced(self):
        mgr = _mgr()
        args = {**VALID_TX, "is_streamed": "false"}
        errors = await mgr._validate_boolean_fields(args)
        assert errors == []
        assert args["is_streamed"] is False

    @pytest.mark.asyncio
    async def test_string_yes_coerced(self):
        mgr = _mgr()
        args = {**VALID_TX, "is_streamed": "yes"}
        errors = await mgr._validate_boolean_fields(args)
        assert errors == []
        assert args["is_streamed"] is True

    @pytest.mark.asyncio
    async def test_string_no_coerced(self):
        mgr = _mgr()
        args = {**VALID_TX, "is_streamed": "no"}
        errors = await mgr._validate_boolean_fields(args)
        assert errors == []
        assert args["is_streamed"] is False

    @pytest.mark.asyncio
    async def test_string_1_coerced(self):
        mgr = _mgr()
        args = {**VALID_TX, "is_streamed": "1"}
        errors = await mgr._validate_boolean_fields(args)
        assert errors == []
        assert args["is_streamed"] is True

    @pytest.mark.asyncio
    async def test_string_0_coerced(self):
        mgr = _mgr()
        args = {**VALID_TX, "is_streamed": "0"}
        errors = await mgr._validate_boolean_fields(args)
        assert errors == []
        assert args["is_streamed"] is False

    @pytest.mark.asyncio
    async def test_unconvertible_string_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "is_streamed": "maybe"}
        errors = await mgr._validate_boolean_fields(args)
        assert any("Cannot convert" in e for e in errors)

    @pytest.mark.asyncio
    async def test_non_bool_non_string_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "is_streamed": 42}
        errors = await mgr._validate_boolean_fields(args)
        assert any("Expected boolean" in e for e in errors)

    @pytest.mark.asyncio
    async def test_none_is_ignored(self):
        mgr = _mgr()
        args = {**VALID_TX, "is_streamed": None}
        errors = await mgr._validate_boolean_fields(args)
        assert errors == []

    @pytest.mark.asyncio
    async def test_absent_field_no_errors(self):
        mgr = _mgr()
        errors = await mgr._validate_boolean_fields(VALID_TX.copy())
        assert errors == []


# ===========================================================================
# _validate_float_fields
# ===========================================================================


class TestValidateFloatFields:

    @pytest.mark.asyncio
    async def test_valid_float_in_range(self):
        mgr = _mgr()
        args = {**VALID_TX, "response_quality_score": 0.85}
        errors = await mgr._validate_float_fields(args)
        assert errors == []

    @pytest.mark.asyncio
    async def test_zero_score_passes(self):
        mgr = _mgr()
        args = {**VALID_TX, "response_quality_score": 0.0}
        errors = await mgr._validate_float_fields(args)
        assert errors == []

    @pytest.mark.asyncio
    async def test_one_score_passes(self):
        mgr = _mgr()
        args = {**VALID_TX, "response_quality_score": 1.0}
        errors = await mgr._validate_float_fields(args)
        assert errors == []

    @pytest.mark.asyncio
    async def test_negative_score_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "response_quality_score": -0.1}
        errors = await mgr._validate_float_fields(args)
        assert any("between 0.0 and 1.0" in e for e in errors)

    @pytest.mark.asyncio
    async def test_score_above_one_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "response_quality_score": 1.5}
        errors = await mgr._validate_float_fields(args)
        assert any("between 0.0 and 1.0" in e for e in errors)

    @pytest.mark.asyncio
    async def test_string_converted_to_float(self):
        mgr = _mgr()
        args = {**VALID_TX, "response_quality_score": "0.75"}
        errors = await mgr._validate_float_fields(args)
        assert errors == []
        assert args["response_quality_score"] == 0.75

    @pytest.mark.asyncio
    async def test_non_convertible_string_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "response_quality_score": "high"}
        errors = await mgr._validate_float_fields(args)
        assert any("Cannot convert" in e for e in errors)

    @pytest.mark.asyncio
    async def test_non_numeric_type_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "response_quality_score": [0.5]}
        errors = await mgr._validate_float_fields(args)
        assert any("Expected number" in e for e in errors)

    @pytest.mark.asyncio
    async def test_int_in_range_passes(self):
        mgr = _mgr()
        args = {**VALID_TX, "response_quality_score": 1}
        errors = await mgr._validate_float_fields(args)
        assert errors == []

    @pytest.mark.asyncio
    async def test_none_value_ignored(self):
        mgr = _mgr()
        args = {**VALID_TX, "response_quality_score": None}
        errors = await mgr._validate_float_fields(args)
        assert errors == []

    @pytest.mark.asyncio
    async def test_absent_field_no_errors(self):
        mgr = _mgr()
        errors = await mgr._validate_float_fields(VALID_TX.copy())
        assert errors == []


# ===========================================================================
# _validate_timestamp_fields
# ===========================================================================


class TestValidateTimestampFields:

    @pytest.mark.asyncio
    async def test_valid_timestamp_passes(self):
        mgr = _mgr()
        args = {**VALID_TX, "request_time": "2025-06-16T15:30:45.123Z"}
        errors = await mgr._validate_timestamp_fields(args)
        assert errors == []

    @pytest.mark.asyncio
    async def test_non_string_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "request_time": 12345}
        errors = await mgr._validate_timestamp_fields(args)
        assert any("Expected ISO UTC string" in e for e in errors)

    @pytest.mark.asyncio
    async def test_missing_z_suffix_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "response_time": "2025-06-16T15:30:45.123"}
        errors = await mgr._validate_timestamp_fields(args)
        assert any("Z" in e for e in errors)

    @pytest.mark.asyncio
    async def test_malformed_iso_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "completion_start_time": "not-a-dateZ"}
        errors = await mgr._validate_timestamp_fields(args)
        assert any("Invalid ISO UTC format" in e for e in errors)

    @pytest.mark.asyncio
    async def test_multiple_timestamp_fields_validated(self):
        mgr = _mgr()
        args = {
            **VALID_TX,
            "request_time": "2025-06-16T15:30:45.123Z",
            "response_time": "bad-time",  # no Z
            "completion_start_time": "2025-06-16T15:31:00.000Z",
        }
        errors = await mgr._validate_timestamp_fields(args)
        assert any("response_time" in e for e in errors)
        assert not any("request_time" in e for e in errors)
        assert not any("completion_start_time" in e for e in errors)

    @pytest.mark.asyncio
    async def test_none_value_ignored(self):
        mgr = _mgr()
        args = {**VALID_TX, "request_time": None}
        errors = await mgr._validate_timestamp_fields(args)
        assert errors == []

    @pytest.mark.asyncio
    async def test_absent_fields_no_errors(self):
        mgr = _mgr()
        errors = await mgr._validate_timestamp_fields(VALID_TX.copy())
        assert errors == []


# ===========================================================================
# _validate_special_fields
# ===========================================================================


class TestValidateSpecialFields:

    @pytest.mark.asyncio
    async def test_valid_time_to_first_token(self):
        mgr = _mgr()
        args = {**VALID_TX, "time_to_first_token": 250}
        errors = await mgr._validate_special_fields(args)
        assert errors == []

    @pytest.mark.asyncio
    async def test_string_converted_to_int(self):
        mgr = _mgr()
        args = {**VALID_TX, "time_to_first_token": "100"}
        errors = await mgr._validate_special_fields(args)
        assert errors == []
        assert args["time_to_first_token"] == 100

    @pytest.mark.asyncio
    async def test_negative_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "time_to_first_token": -10}
        errors = await mgr._validate_special_fields(args)
        assert any("positive" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_over_60000_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "time_to_first_token": 60001}
        errors = await mgr._validate_special_fields(args)
        assert any("Too large" in e for e in errors)

    @pytest.mark.asyncio
    async def test_exactly_60000_passes(self):
        mgr = _mgr()
        args = {**VALID_TX, "time_to_first_token": 60000}
        errors = await mgr._validate_special_fields(args)
        assert errors == []

    @pytest.mark.asyncio
    async def test_non_int_type_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "time_to_first_token": [100]}
        errors = await mgr._validate_special_fields(args)
        assert any("Expected integer" in e for e in errors)

    @pytest.mark.asyncio
    async def test_non_convertible_string_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "time_to_first_token": "fast"}
        errors = await mgr._validate_special_fields(args)
        assert any("Cannot convert" in e for e in errors)

    @pytest.mark.asyncio
    async def test_none_ignored(self):
        mgr = _mgr()
        args = {**VALID_TX, "time_to_first_token": None}
        errors = await mgr._validate_special_fields(args)
        assert errors == []

    @pytest.mark.asyncio
    async def test_absent_field_no_errors(self):
        mgr = _mgr()
        errors = await mgr._validate_special_fields(VALID_TX.copy())
        assert errors == []


# ===========================================================================
# _validate_transaction_inputs_async (orchestrator)
# ===========================================================================


class TestValidateTransactionInputsAsync:

    @pytest.mark.asyncio
    async def test_valid_inputs_return_valid_true(self):
        mgr = _mgr()
        with patch(
            "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
        ) as mock_cache:
            mock_cache.get_cached_response = AsyncMock(return_value=None)
            mock_cache.set_cached_response = AsyncMock()
            result = await mgr._validate_transaction_inputs_async(VALID_TX.copy())
        assert result["valid"] is True
        assert "All inputs are valid" in result["message"]

    @pytest.mark.asyncio
    async def test_fast_check_failure_short_circuits(self):
        mgr = _mgr()
        args = {**VALID_TX, "task_id": "t1"}
        with patch(
            "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
        ) as mock_cache:
            mock_cache.get_cached_response = AsyncMock(return_value=None)
            mock_cache.set_cached_response = AsyncMock()
            result = await mgr._validate_transaction_inputs_async(args)
        assert result["valid"] is False
        assert "task_id" in result["message"]

    @pytest.mark.asyncio
    async def test_numeric_error_returns_invalid(self):
        mgr = _mgr()
        args = {**VALID_TX, "input_tokens": -1}
        with patch(
            "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
        ) as mock_cache:
            mock_cache.get_cached_response = AsyncMock(return_value=None)
            mock_cache.set_cached_response = AsyncMock()
            result = await mgr._validate_transaction_inputs_async(args)
        assert result["valid"] is False
        assert "positive" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_multiple_errors_categorized(self):
        mgr = _mgr()
        args = {
            **VALID_TX,
            "input_tokens": -1,
            "model": 42,  # won't fail fast checks because fast checks check model is str — but model=42 should fail
        }
        # model=42 will fail fast checks (type check), so let's use a different combo
        args2 = {
            **VALID_TX,
            "input_tokens": -1,
            "response_quality_score": 5.0,
        }
        with patch(
            "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
        ) as mock_cache:
            mock_cache.get_cached_response = AsyncMock(return_value=None)
            mock_cache.set_cached_response = AsyncMock()
            result = await mgr._validate_transaction_inputs_async(args2)
        assert result["valid"] is False
        assert "Validation Error" in result["message"]

    @pytest.mark.asyncio
    async def test_combination_warnings_appended_on_success(self):
        mgr = _mgr()
        args = {**VALID_TX, "response_quality_score": 0.9}
        with patch(
            "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
        ) as mock_cache:
            mock_cache.get_cached_response = AsyncMock(return_value=None)
            mock_cache.set_cached_response = AsyncMock()
            result = await mgr._validate_transaction_inputs_async(args)
        assert result["valid"] is True
        # Should include progressive enhancement suggestions
        if "is_streamed" in result["message"]:
            assert "suggestions" in result["message"].lower() or "Enhancement" in result["message"]

    @pytest.mark.asyncio
    async def test_exception_in_validation_task_captured(self):
        mgr = _mgr()
        with patch.object(
            mgr, "_validate_numeric_fields", new=AsyncMock(side_effect=RuntimeError("boom"))
        ):
            with patch(
                "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
            ) as mock_cache:
                mock_cache.get_cached_response = AsyncMock(return_value=None)
                mock_cache.set_cached_response = AsyncMock()
                result = await mgr._validate_transaction_inputs_async(VALID_TX.copy())
        assert result["valid"] is False
        assert "boom" in result["message"]

    @pytest.mark.asyncio
    async def test_format_errors_grouped(self):
        mgr = _mgr()
        args = {**VALID_TX, "is_streamed": 42}
        with patch(
            "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
        ) as mock_cache:
            mock_cache.get_cached_response = AsyncMock(return_value=None)
            mock_cache.set_cached_response = AsyncMock()
            result = await mgr._validate_transaction_inputs_async(args)
        assert result["valid"] is False
        assert "Format Issues" in result["message"]

    @pytest.mark.asyncio
    async def test_quick_fixes_include_relevant_hints(self):
        mgr = _mgr()
        args = {**VALID_TX, "response_quality_score": 5.0, "request_time": 123}
        with patch(
            "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
        ) as mock_cache:
            mock_cache.get_cached_response = AsyncMock(return_value=None)
            mock_cache.set_cached_response = AsyncMock()
            result = await mgr._validate_transaction_inputs_async(args)
        assert result["valid"] is False
        assert "response_quality_score" in result["message"]
        assert "Timestamps" in result["message"] or "timestamp" in result["message"].lower()


# ===========================================================================
# _validate_transaction_inputs_with_details
# ===========================================================================


class TestValidateTransactionInputsWithDetails:

    @pytest.mark.asyncio
    async def test_valid_inputs_returns_valid_true(self):
        mgr = _mgr()
        result = await mgr._validate_transaction_inputs_with_details(VALID_TX.copy())
        assert result["valid"] is True
        assert "All inputs are valid" in result["message"]

    @pytest.mark.asyncio
    async def test_old_subscriber_format_short_circuits(self):
        mgr = _mgr()
        args = {**VALID_TX, "subscriber_email": "old@test.com"}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "subscriber" in result["message"].lower() or "SUBSCRIBER" in result["message"]

    @pytest.mark.asyncio
    async def test_task_id_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "task_id": "t1"}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "task_id" in result["message"]

    @pytest.mark.asyncio
    async def test_negative_tokens_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "input_tokens": -5}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "positive" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_string_token_converted(self):
        mgr = _mgr()
        args = {**VALID_TX, "input_tokens": "1000"}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is True
        assert args["input_tokens"] == 1000

    @pytest.mark.asyncio
    async def test_non_convertible_string_token(self):
        mgr = _mgr()
        args = {**VALID_TX, "duration_ms": "slow"}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False

    @pytest.mark.asyncio
    async def test_model_injection_chars_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "model": "gpt<4"}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "invalid characters" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_empty_model_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "model": "  "}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False

    @pytest.mark.asyncio
    async def test_operation_type_valid_values(self):
        mgr = _mgr()
        for op_type in ["CHAT", "COMPLETION", "EMBEDDING", "FINE_TUNING", "MODERATION"]:
            args = {**VALID_TX, "operation_type": op_type}
            result = await mgr._validate_transaction_inputs_with_details(args)
            assert result["valid"] is True, f"Failed for {op_type}"

    @pytest.mark.asyncio
    async def test_operation_type_invalid_value(self):
        mgr = _mgr()
        args = {**VALID_TX, "operation_type": "INVALID_OP"}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "operation_type" in result["message"]

    @pytest.mark.asyncio
    async def test_is_streamed_string_coercion(self):
        mgr = _mgr()
        args = {**VALID_TX, "is_streamed": "true"}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is True
        assert args["is_streamed"] is True

    @pytest.mark.asyncio
    async def test_is_streamed_invalid_string(self):
        mgr = _mgr()
        args = {**VALID_TX, "is_streamed": "maybe"}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False

    @pytest.mark.asyncio
    async def test_optional_string_too_long(self):
        mgr = _mgr()
        args = {**VALID_TX, "organization_id": "x" * 501}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "Too long" in result["message"]

    @pytest.mark.asyncio
    async def test_optional_string_injection_chars(self):
        mgr = _mgr()
        args = {**VALID_TX, "agent": "bot&evil"}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "invalid characters" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_quality_score_out_of_range(self):
        mgr = _mgr()
        args = {**VALID_TX, "response_quality_score": 2.0}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "between 0.0 and 1.0" in result["message"]

    @pytest.mark.asyncio
    async def test_quality_score_string_conversion(self):
        mgr = _mgr()
        args = {**VALID_TX, "response_quality_score": "0.5"}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is True
        assert args["response_quality_score"] == 0.5

    @pytest.mark.asyncio
    async def test_timestamp_missing_z_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "request_time": "2025-06-16T15:30:45.123"}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "Z" in result["message"]

    @pytest.mark.asyncio
    async def test_timestamp_malformed_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "response_time": "not-a-dateZ"}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False

    @pytest.mark.asyncio
    async def test_time_to_first_token_negative(self):
        mgr = _mgr()
        args = {**VALID_TX, "time_to_first_token": -1}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "positive" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_time_to_first_token_too_large(self):
        mgr = _mgr()
        args = {**VALID_TX, "time_to_first_token": 60001}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "Too large" in result["message"]

    @pytest.mark.asyncio
    async def test_multiple_errors_grouped_and_categorized(self):
        mgr = _mgr()
        args = {
            **VALID_TX,
            "input_tokens": -1,
            "response_quality_score": 5.0,
            "is_streamed": "maybe",
        }
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "Validation Error" in result["message"]
        # Should include quick fixes
        assert "Quick Fixes" in result["message"]

    @pytest.mark.asyncio
    async def test_combination_warnings_on_success(self):
        mgr = _mgr()
        args = {**VALID_TX, "response_quality_score": 0.9}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is True
        # May include progressive enhancement suggestions
        if "is_streamed" in result["message"]:
            assert "suggestions" in result["message"].lower() or "Enhancement" in result["message"]

    @pytest.mark.asyncio
    async def test_exception_caught_returns_error(self):
        mgr = _mgr()
        with patch.object(
            mgr, "_check_for_old_subscriber_format", side_effect=RuntimeError("kaboom")
        ):
            result = await mgr._validate_transaction_inputs_with_details(VALID_TX.copy())
        assert result["valid"] is False
        assert "kaboom" in result["message"]

    @pytest.mark.asyncio
    async def test_over_10m_tokens_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "output_tokens": 10_000_001}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "too large" in result["message"].lower() or "Value too large" in result["message"]

    @pytest.mark.asyncio
    async def test_model_too_long_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "model": "m" * 201}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "Too long" in result["message"]

    @pytest.mark.asyncio
    async def test_non_int_token_type_rejected(self):
        mgr = _mgr()
        args = {**VALID_TX, "input_tokens": 3.14}
        result = await mgr._validate_transaction_inputs_with_details(args)
        assert result["valid"] is False
        assert "Expected integer" in result["message"]
