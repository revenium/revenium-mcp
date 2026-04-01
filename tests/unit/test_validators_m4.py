"""Extended unit tests for src/revenium_mcp_server/validators.py.

Targets missed lines to improve coverage from ~17% to >70%.
"""

import pytest
from datetime import datetime, timezone

from src.revenium_mcp_server.validators import (
    AdvancedConfigurationBuilder,
    InputValidator,
    ALERT_VALIDATION_RULES,
    ANOMALY_VALIDATION_RULES,
    PAGINATION_VALIDATION_RULES,
    validate_input,
)
from src.revenium_mcp_server.exceptions import InvalidInputError, ValidationError


# ---------------------------------------------------------------------------
# sanitize_string
# ---------------------------------------------------------------------------

class TestSanitizeString:
    def test_none_returns_empty_string(self):
        result = InputValidator.sanitize_string(None)
        assert result == ""

    def test_strips_leading_trailing_whitespace(self):
        result = InputValidator.sanitize_string("  hello  ")
        assert result == "hello"

    def test_removes_null_bytes(self):
        result = InputValidator.sanitize_string("hel\x00lo")
        assert "\x00" not in result
        assert result == "hello"

    def test_removes_low_control_characters(self):
        result = InputValidator.sanitize_string("abc\x01\x1fdef")
        assert "\x01" not in result
        assert "\x1f" not in result

    def test_preserves_tab_newline_cr(self):
        # Tabs, newlines, and CR are kept but then normalised to single spaces
        result = InputValidator.sanitize_string("a\tb\nc\r")
        assert result == "a b c"

    def test_html_escape_applied_by_default(self):
        result = InputValidator.sanitize_string("<b>bold</b>")
        assert "<b>" not in result
        assert "&lt;b&gt;" in result

    def test_allow_html_skips_escape(self):
        result = InputValidator.sanitize_string("<b>bold</b>", allow_html=True)
        assert "<b>bold</b>" in result

    def test_max_length_exceeded_raises(self):
        with pytest.raises(InvalidInputError) as exc_info:
            InputValidator.sanitize_string("a" * 20, max_length=10)
        assert exc_info.value.error_code == "INVALID_INPUT"

    def test_max_length_exact_ok(self):
        result = InputValidator.sanitize_string("hello", max_length=5)
        assert result == "hello"

    def test_normalises_multiple_spaces(self):
        result = InputValidator.sanitize_string("a   b   c")
        assert result == "a b c"

    def test_non_string_input_converted(self):
        result = InputValidator.sanitize_string(42)
        assert result == "42"


# ---------------------------------------------------------------------------
# validate_anomaly_name
# ---------------------------------------------------------------------------

class TestValidateAnomalyName:
    def test_valid_name_returned(self):
        result = InputValidator.validate_anomaly_name("My Alert")
        assert result == "My Alert"

    def test_empty_string_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_anomaly_name("")
        assert exc_info.value.details["field"] == "name"

    def test_none_raises(self):
        with pytest.raises(ValidationError):
            InputValidator.validate_anomaly_name(None)

    def test_single_char_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_anomaly_name("a")
        assert "2 characters" in exc_info.value.message

    def test_name_too_long_raises(self):
        long_name = "a" * 256
        with pytest.raises(InvalidInputError):
            InputValidator.validate_anomaly_name(long_name)

    def test_name_exactly_two_chars_ok(self):
        result = InputValidator.validate_anomaly_name("ab")
        assert result == "ab"


# ---------------------------------------------------------------------------
# validate_description
# ---------------------------------------------------------------------------

class TestValidateDescription:
    def test_none_returns_none(self):
        assert InputValidator.validate_description(None) is None

    def test_empty_returns_none(self):
        assert InputValidator.validate_description("") is None

    def test_valid_description_returned(self):
        result = InputValidator.validate_description("A valid description.")
        assert result == "A valid description."

    def test_description_too_long_raises(self):
        long_desc = "x" * 2001
        with pytest.raises(InvalidInputError):
            InputValidator.validate_description(long_desc)


# ---------------------------------------------------------------------------
# validate_uuid
# ---------------------------------------------------------------------------

class TestValidateUuid:
    def test_valid_uuid_accepted(self):
        uid = "123e4567-e89b-12d3-a456-426614174000"
        result = InputValidator.validate_uuid(uid)
        assert result == uid

    def test_uppercase_uuid_normalised_to_lowercase(self):
        uid = "123E4567-E89B-12D3-A456-426614174000"
        result = InputValidator.validate_uuid(uid)
        assert result == uid.lower()

    def test_empty_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_uuid("")
        assert exc_info.value.details["field"] == "id"

    def test_none_raises(self):
        with pytest.raises(ValidationError):
            InputValidator.validate_uuid(None)

    def test_invalid_format_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_uuid("not-a-uuid")
        assert "Invalid" in exc_info.value.message

    def test_custom_field_name_in_error(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_uuid("", field_name="alert_id")
        assert exc_info.value.details["field"] == "alert_id"


# ---------------------------------------------------------------------------
# validate_email
# ---------------------------------------------------------------------------

class TestValidateEmail:
    def test_valid_email_accepted(self):
        result = InputValidator.validate_email("user@example.com")
        assert result == "user@example.com"

    def test_email_normalised_to_lowercase(self):
        result = InputValidator.validate_email("User@EXAMPLE.COM")
        assert result == "user@example.com"

    def test_empty_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_email("")
        assert exc_info.value.details["field"] == "email"

    def test_none_raises(self):
        with pytest.raises(ValidationError):
            InputValidator.validate_email(None)

    def test_invalid_format_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_email("not-an-email")
        assert "Invalid email" in exc_info.value.message


# ---------------------------------------------------------------------------
# validate_tags
# ---------------------------------------------------------------------------

class TestValidateTags:
    def test_empty_list_returns_empty(self):
        assert InputValidator.validate_tags([]) == []

    def test_none_returns_empty(self):
        assert InputValidator.validate_tags(None) == []

    def test_valid_tags_returned(self):
        result = InputValidator.validate_tags(["api", "test", "v2"])
        assert result == ["api", "test", "v2"]

    def test_non_list_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_tags("api,test")
        assert exc_info.value.details["field"] == "tags"

    def test_too_many_tags_raises(self):
        tags = [f"tag{i}" for i in range(21)]
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_tags(tags)
        assert "Too many tags" in exc_info.value.message

    def test_duplicate_tags_deduplicated(self):
        result = InputValidator.validate_tags(["api", "api", "test"])
        assert result.count("api") == 1

    def test_empty_tag_in_list_skipped(self):
        result = InputValidator.validate_tags(["api", "", "test"])
        assert "" not in result
        assert "api" in result
        assert "test" in result

    def test_invalid_tag_characters_raise(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_tags(["<script>"])
        assert exc_info.value.details["field"] == "tags"

    def test_tag_too_long_raises(self):
        long_tag = "a" * 51
        with pytest.raises(InvalidInputError):
            InputValidator.validate_tags([long_tag])

    def test_tuple_accepted_as_tags(self):
        result = InputValidator.validate_tags(("api", "test"))
        assert "api" in result


# ---------------------------------------------------------------------------
# validate_numeric_range
# ---------------------------------------------------------------------------

class TestValidateNumericRange:
    def test_valid_int_accepted(self):
        result = InputValidator.validate_numeric_range(42, "count")
        assert result == 42

    def test_valid_float_accepted(self):
        result = InputValidator.validate_numeric_range(3.14, "rate")
        assert abs(result - 3.14) < 0.001

    def test_string_int_parsed(self):
        result = InputValidator.validate_numeric_range("100", "count")
        assert result == 100

    def test_string_float_parsed(self):
        result = InputValidator.validate_numeric_range("3.14", "rate")
        assert abs(result - 3.14) < 0.001

    def test_none_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_numeric_range(None, "count")
        assert exc_info.value.details["field"] == "count"

    def test_non_numeric_string_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_numeric_range("abc", "count")
        assert "Invalid" in exc_info.value.message

    def test_below_min_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_numeric_range(5, "count", min_value=10)
        assert "below minimum" in exc_info.value.message

    def test_above_max_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_numeric_range(200, "count", max_value=100)
        assert "exceeds maximum" in exc_info.value.message

    def test_allow_zero_false_rejects_zero(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_numeric_range(0, "count", allow_zero=False)
        assert "cannot be zero" in exc_info.value.message

    def test_allow_zero_true_accepts_zero(self):
        result = InputValidator.validate_numeric_range(0, "count", allow_zero=True)
        assert result == 0

    def test_exact_min_boundary_accepted(self):
        result = InputValidator.validate_numeric_range(10, "count", min_value=10)
        assert result == 10

    def test_exact_max_boundary_accepted(self):
        result = InputValidator.validate_numeric_range(100, "count", max_value=100)
        assert result == 100


# ---------------------------------------------------------------------------
# validate_datetime_string
# ---------------------------------------------------------------------------

class TestValidateDatetimeString:
    def test_iso_z_format_accepted(self):
        result = InputValidator.validate_datetime_string("2024-01-15T10:30:00Z")
        assert isinstance(result, datetime)
        assert result.tzinfo is not None
        assert result.year == 2024 and result.month == 1 and result.day == 15

    def test_iso_with_microseconds_z(self):
        result = InputValidator.validate_datetime_string("2024-01-15T10:30:00.123456Z")
        assert result.tzinfo is not None
        assert result.microsecond == 123456

    def test_iso_basic_format(self):
        result = InputValidator.validate_datetime_string("2024-01-15T10:30:00")
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc

    def test_date_only_format(self):
        result = InputValidator.validate_datetime_string("2024-01-15")
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_space_separated_format(self):
        result = InputValidator.validate_datetime_string("2024-01-15 10:30:00")
        assert result.hour == 10

    def test_empty_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_datetime_string("")
        assert exc_info.value.details["field"] == "datetime"

    def test_none_raises(self):
        with pytest.raises(ValidationError):
            InputValidator.validate_datetime_string(None)

    def test_invalid_format_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_datetime_string("not-a-date")
        assert "Invalid" in exc_info.value.message

    def test_custom_field_name_in_error(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_datetime_string("", field_name="start_date")
        assert exc_info.value.details["field"] == "start_date"

    def test_iso_microseconds_no_z(self):
        result = InputValidator.validate_datetime_string("2024-06-01T12:00:00.999999")
        assert result.microsecond == 999999


# ---------------------------------------------------------------------------
# validate_url
# ---------------------------------------------------------------------------

class TestValidateUrl:
    def test_valid_https_url(self):
        result = InputValidator.validate_url("https://example.com/api")
        assert result == "https://example.com/api"

    def test_valid_http_url(self):
        result = InputValidator.validate_url("http://example.com")
        assert result == "http://example.com"

    def test_empty_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_url("")
        assert exc_info.value.details["field"] == "url"

    def test_none_raises(self):
        with pytest.raises(ValidationError):
            InputValidator.validate_url(None)

    def test_ftp_scheme_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_url("ftp://files.example.com")
        assert "Invalid" in exc_info.value.message

    def test_missing_netloc_raises(self):
        with pytest.raises(ValidationError):
            InputValidator.validate_url("https://")

    def test_custom_field_name_in_error(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_url("", field_name="webhook_url")
        assert exc_info.value.details["field"] == "webhook_url"


# ---------------------------------------------------------------------------
# validate_detection_rule
# ---------------------------------------------------------------------------

class TestValidateDetectionRule:
    def _base_rule(self):
        return {"rule_type": "THRESHOLD", "metric": "error_rate", "operator": ">", "value": 5}

    def test_valid_rule_accepted(self):
        result = InputValidator.validate_detection_rule(self._base_rule())
        assert result["rule_type"] == "THRESHOLD"
        assert result["operator"] == ">"
        assert result["value"] == 5

    def test_non_dict_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_detection_rule("not a dict")
        assert "dictionary" in exc_info.value.message

    def test_missing_required_field_raises(self):
        rule = {"rule_type": "THRESHOLD", "metric": "error_rate", "operator": ">"}
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_detection_rule(rule)
        assert "value" in exc_info.value.message

    def test_invalid_rule_type_raises(self):
        rule = {**self._base_rule(), "rule_type": "UNKNOWN"}
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_detection_rule(rule)
        assert "rule_type" in exc_info.value.details["field"]

    def test_rule_type_normalised_to_uppercase(self):
        rule = {**self._base_rule(), "rule_type": "threshold"}
        result = InputValidator.validate_detection_rule(rule)
        assert result["rule_type"] == "THRESHOLD"

    def test_invalid_operator_raises(self):
        rule = {**self._base_rule(), "operator": "LIKE"}
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_detection_rule(rule)
        assert "operator" in exc_info.value.details["field"]

    def test_valid_string_operator(self):
        rule = {**self._base_rule(), "operator": "contains", "value": "error"}
        result = InputValidator.validate_detection_rule(rule)
        assert result["operator"] == "contains"
        assert result["value"] == "error"

    def test_time_window_threshold_format(self):
        rule = {**self._base_rule(), "time_window": "5m"}
        result = InputValidator.validate_detection_rule(rule)
        assert result["time_window"] == "5m"

    def test_time_window_invalid_format_raises(self):
        rule = {**self._base_rule(), "time_window": "5minutes"}
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_detection_rule(rule)
        assert "time_window" in exc_info.value.details["field"]

    def test_cumulative_usage_calendar_period_accepted(self):
        rule = {
            "rule_type": "CUMULATIVE_USAGE",
            "metric": "total_cost",
            "operator": ">",
            "value": 100,
            "time_window": "monthly",
        }
        result = InputValidator.validate_detection_rule(rule)
        assert result["time_window"] == "monthly"

    def test_cumulative_usage_invalid_period_raises(self):
        rule = {
            "rule_type": "CUMULATIVE_USAGE",
            "metric": "total_cost",
            "operator": ">",
            "value": 100,
            "time_window": "5m",
        }
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_detection_rule(rule)
        assert "CUMULATIVE_USAGE" in exc_info.value.message

    def test_aggregation_valid_accepted(self):
        rule = {**self._base_rule(), "aggregation": "avg"}
        result = InputValidator.validate_detection_rule(rule)
        assert result["aggregation"] == "avg"

    def test_aggregation_invalid_raises(self):
        rule = {**self._base_rule(), "aggregation": "geometric_mean"}
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_detection_rule(rule)
        assert "aggregation" in exc_info.value.details["field"]

    def test_conditions_list_accepted(self):
        rule = {**self._base_rule(), "conditions": ["cond1", "cond2"]}
        result = InputValidator.validate_detection_rule(rule)
        assert len(result["conditions"]) == 2

    def test_conditions_non_list_raises(self):
        rule = {**self._base_rule(), "conditions": "single condition"}
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_detection_rule(rule)
        assert "conditions" in exc_info.value.details["field"]

    def test_empty_metric_raises(self):
        rule = {**self._base_rule(), "metric": ""}
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_detection_rule(rule)
        assert "metric" in exc_info.value.details["field"]

    def test_all_valid_rule_types_accepted(self):
        for rt in ["THRESHOLD", "STATISTICAL", "PATTERN", "ANOMALY", "TREND", "CUMULATIVE_USAGE"]:
            rule = {**self._base_rule(), "rule_type": rt}
            result = InputValidator.validate_detection_rule(rule)
            assert result["rule_type"] == rt


# ---------------------------------------------------------------------------
# validate_thresholds
# ---------------------------------------------------------------------------

class TestValidateThresholds:
    def test_valid_thresholds_accepted(self):
        result = InputValidator.validate_thresholds({"error_rate": 0.05, "latency": 500})
        assert result["error_rate"] == 0.05
        assert result["latency"] == 500

    def test_non_dict_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_thresholds([1, 2])
        assert "dictionary" in exc_info.value.message

    def test_empty_dict_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_thresholds({})
        assert "At least one threshold" in exc_info.value.message

    def test_invalid_threshold_value_raises(self):
        with pytest.raises(ValidationError):
            InputValidator.validate_thresholds({"error_rate": "not-a-number"})

    def test_zero_threshold_accepted(self):
        result = InputValidator.validate_thresholds({"error_rate": 0})
        assert result["error_rate"] == 0


# ---------------------------------------------------------------------------
# _convert_filters_to_api_format
# ---------------------------------------------------------------------------

class TestConvertFiltersToApiFormat:
    def test_empty_list_returns_empty(self):
        result = InputValidator._convert_filters_to_api_format([])
        assert result == []

    def test_none_returns_empty(self):
        result = InputValidator._convert_filters_to_api_format(None)
        assert result == []

    def test_known_field_mapped_to_dimension(self):
        filters = [{"field": "organization", "operator": "contains", "value": "acme"}]
        result = InputValidator._convert_filters_to_api_format(filters)
        assert result[0]["dimension"] == "ORGANIZATION"

    def test_known_operator_mapped(self):
        filters = [{"field": "model", "operator": "equals", "value": "gpt-4"}]
        result = InputValidator._convert_filters_to_api_format(filters)
        assert result[0]["operator"] == "IS"

    def test_unknown_field_upcased(self):
        filters = [{"field": "custom_field", "operator": "is", "value": "x"}]
        result = InputValidator._convert_filters_to_api_format(filters)
        assert result[0]["dimension"] == "CUSTOM_FIELD"

    def test_non_dict_filter_skipped(self):
        result = InputValidator._convert_filters_to_api_format(["bad_filter"])
        assert result == []

    def test_value_converted_to_string(self):
        filters = [{"field": "model", "operator": "equals", "value": 42}]
        result = InputValidator._convert_filters_to_api_format(filters)
        assert result[0]["value"] == "42"

    def test_multiple_filters_all_converted(self):
        filters = [
            {"field": "organization", "operator": "contains", "value": "acme"},
            {"field": "product", "operator": "starts_with", "value": "pro"},
        ]
        result = InputValidator._convert_filters_to_api_format(filters)
        assert len(result) == 2
        assert result[1]["operator"] == "STARTS_WITH"


# ---------------------------------------------------------------------------
# convert_to_api_format
# ---------------------------------------------------------------------------

class TestConvertToApiFormat:
    def _user_data(self, **overrides):
        base = {
            "name": "High Error Rate",
            "detection_rules": [
                {
                    "rule_type": "THRESHOLD",
                    "metric": "error_rate",
                    "operator": ">",
                    "value": 0.05,
                    "time_window": "5m",
                }
            ],
        }
        base.update(overrides)
        return base

    def test_basic_threshold_conversion(self):
        result = InputValidator.convert_to_api_format(self._user_data())
        assert result["name"] == "High Error Rate"
        assert result["label"] == "High Error Rate"
        assert result["alertType"] == "THRESHOLD"
        assert result["operatorType"] == "GREATER_THAN"
        assert result["metricType"] == "ERROR_RATE"
        assert result["periodDuration"] == "FIVE_MINUTES"

    def test_no_detection_rules_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.convert_to_api_format({"name": "test", "detection_rules": []})
        assert "detection_rules" in exc_info.value.details["field"]

    def test_missing_detection_rules_raises(self):
        with pytest.raises(ValidationError):
            InputValidator.convert_to_api_format({"name": "test"})

    def test_invalid_operator_raises(self):
        data = self._user_data()
        data["detection_rules"][0]["operator"] = "contains"
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.convert_to_api_format(data)
        assert exc_info.value.details["field"] == "operator"

    def test_invalid_metric_raises(self):
        data = self._user_data()
        data["detection_rules"][0]["metric"] = "nonexistent_metric"
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.convert_to_api_format(data)
        assert exc_info.value.details["field"] == "metric"

    def test_invalid_metric_cost_suggestion(self):
        # When the metric contains "cost", the error suggestions must mention total_cost.
        data = self._user_data()
        data["detection_rules"][0]["metric"] = "cost_something"
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.convert_to_api_format(data)
        assert any("total_cost" in s for s in exc_info.value.suggestions)

    def test_invalid_metric_token_suggestion(self):
        # When the metric contains "token", the error suggestions must mention token_count.
        data = self._user_data()
        data["detection_rules"][0]["metric"] = "token_usage"
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.convert_to_api_format(data)
        assert any("token_count" in s for s in exc_info.value.suggestions)

    def test_invalid_metric_time_suggestion(self):
        # When the metric contains "time", the error suggestions must mention tokens_per_second.
        data = self._user_data()
        data["detection_rules"][0]["metric"] = "response_time"
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.convert_to_api_format(data)
        assert any("tokens_per_second" in s for s in exc_info.value.suggestions)

    def test_cumulative_usage_with_monthly_period(self):
        data = self._user_data()
        data["detection_rules"][0]["rule_type"] = "CUMULATIVE_USAGE"
        data["detection_rules"][0]["time_window"] = "monthly"
        result = InputValidator.convert_to_api_format(data)
        assert result["alertType"] == "CUMULATIVE_USAGE"
        assert result["periodDuration"] == "MONTHLY"

    def test_cumulative_usage_default_period_daily(self):
        # When time_window is absent and no period keys exist in user_data,
        # the code falls back to "daily" → "DAILY".
        data = {
            "name": "Monthly Cost",
            "detection_rules": [
                {
                    "rule_type": "CUMULATIVE_USAGE",
                    "metric": "total_cost",
                    "operator": ">",
                    "value": 1000,
                    # no time_window key
                }
            ],
        }
        result = InputValidator.convert_to_api_format(data)
        assert result["periodDuration"] == "DAILY"

    def test_all_period_durations_mapped(self):
        period_map = {
            "1m": "ONE_MINUTE",
            "5m": "FIVE_MINUTES",
            "1h": "ONE_HOUR",
            "1d": "ONE_DAY",
        }
        for short, expected in period_map.items():
            data = self._user_data()
            data["detection_rules"][0]["time_window"] = short
            result = InputValidator.convert_to_api_format(data)
            assert result["periodDuration"] == expected, f"Failed for {short}"

    def test_optional_description_included_when_present(self):
        data = self._user_data(description="Alert for high error rate")
        result = InputValidator.convert_to_api_format(data)
        assert result["description"] == "Alert for high error rate"

    def test_optional_description_absent_when_not_provided(self):
        result = InputValidator.convert_to_api_format(self._user_data())
        assert "description" not in result

    def test_group_by_included_when_present(self):
        data = self._user_data(group_by="organization")
        result = InputValidator.convert_to_api_format(data)
        assert result["groupBy"] == "organization"

    def test_notification_addresses_passed_through(self):
        data = self._user_data(notificationAddresses=["admin@example.com"])
        result = InputValidator.convert_to_api_format(data)
        assert "admin@example.com" in result["notificationAddresses"]

    def test_filters_converted(self):
        data = self._user_data(
            filters=[{"field": "organization", "operator": "contains", "value": "acme"}]
        )
        result = InputValidator.convert_to_api_format(data)
        assert len(result["filters"]) == 1
        assert result["filters"][0]["dimension"] == "ORGANIZATION"

    def test_is_percentage_defaulted_to_false(self):
        result = InputValidator.convert_to_api_format(self._user_data())
        assert result["isPercentage"] is False

    def test_all_threshold_operators(self):
        for op, expected in [
            ("<", "LESS_THAN"),
            (">=", "GREATER_THAN_OR_EQUAL_TO"),
            ("<=", "LESS_THAN_OR_EQUAL_TO"),
        ]:
            data = self._user_data()
            data["detection_rules"][0]["operator"] = op
            result = InputValidator.convert_to_api_format(data)
            assert result["operatorType"] == expected

    def test_all_threshold_metrics_mapped(self):
        metrics_map = {
            "total_cost": "TOTAL_COST",
            "token_count": "TOKEN_COUNT",
            "error_count": "ERROR_COUNT",
            "requests_per_second": "REQUESTS_PER_SECOND",
        }
        for metric, expected in metrics_map.items():
            data = self._user_data()
            data["detection_rules"][0]["metric"] = metric
            result = InputValidator.convert_to_api_format(data)
            assert result["metricType"] == expected


# ---------------------------------------------------------------------------
# AdvancedConfigurationBuilder
# ---------------------------------------------------------------------------

class TestAdvancedConfigurationBuilder:
    def test_create_filter_returns_dict_with_correct_fields(self):
        result = AdvancedConfigurationBuilder.create_filter("organization", "contains", "acme")
        assert result["field"] == "organization"
        assert result["operator"] == "contains"
        assert result["value"] == "acme"

    def test_create_slack_config_returns_url(self):
        url = "https://hooks.slack.com/services/T00/B00/XYZ"
        result = AdvancedConfigurationBuilder.create_slack_config(url, channel="#alerts")
        assert result == url

    def test_create_webhook_config_returns_url(self):
        url = "https://example.com/webhook"
        result = AdvancedConfigurationBuilder.create_webhook_config(url)
        assert result == url

    def test_build_advanced_config_with_filters(self):
        filters = [{"dimension": "ORGANIZATION", "operator": "CONTAINS", "value": "acme"}]
        result = AdvancedConfigurationBuilder.build_advanced_config(filters=filters)
        assert result["filters"] == filters

    def test_build_advanced_config_no_filters_returns_empty_list(self):
        result = AdvancedConfigurationBuilder.build_advanced_config()
        assert result["filters"] == []

    def test_build_advanced_config_group_by(self):
        result = AdvancedConfigurationBuilder.build_advanced_config(group_by="model")
        assert result["groupBy"] == "model"

    def test_build_advanced_config_no_group_by_absent(self):
        result = AdvancedConfigurationBuilder.build_advanced_config()
        assert "groupBy" not in result

    def test_build_advanced_config_slack_configs(self):
        result = AdvancedConfigurationBuilder.build_advanced_config(
            slack_configs=["https://hooks.slack.com/T1/B1/K1"]
        )
        assert len(result["slackConfigurations"]) == 1

    def test_build_advanced_config_no_slack_returns_empty_list(self):
        result = AdvancedConfigurationBuilder.build_advanced_config()
        assert result["slackConfigurations"] == []

    def test_build_advanced_config_webhook_configs(self):
        result = AdvancedConfigurationBuilder.build_advanced_config(
            webhook_configs=["https://example.com/wh"]
        )
        assert len(result["webhook_enabled"]) == 1

    def test_build_advanced_config_trigger_duration(self):
        result = AdvancedConfigurationBuilder.build_advanced_config(trigger_duration="5m")
        assert result["triggerAfterPersistsDuration"] == "5m"

    def test_build_advanced_config_no_trigger_absent(self):
        result = AdvancedConfigurationBuilder.build_advanced_config()
        assert "triggerAfterPersistsDuration" not in result

    def test_build_advanced_config_is_percentage_true(self):
        result = AdvancedConfigurationBuilder.build_advanced_config(is_percentage=True)
        assert result["isPercentage"] is True

    def test_build_advanced_config_is_percentage_false(self):
        result = AdvancedConfigurationBuilder.build_advanced_config(is_percentage=False)
        assert result["isPercentage"] is False

    def test_build_advanced_config_is_percentage_none_absent(self):
        result = AdvancedConfigurationBuilder.build_advanced_config()
        assert "isPercentage" not in result


# ---------------------------------------------------------------------------
# validate_input decorator
# ---------------------------------------------------------------------------

class TestValidateInputDecorator:
    @pytest.mark.asyncio
    async def test_decorator_validates_and_updates_argument(self):
        @validate_input({"name": InputValidator.validate_anomaly_name})
        async def handler(*args, **kwargs):
            return args[-1]["name"]

        result = await handler({"name": "  My Alert  "})
        assert result == "My Alert"

    @pytest.mark.asyncio
    async def test_decorator_passes_through_when_key_absent(self):
        @validate_input({"name": InputValidator.validate_anomaly_name})
        async def handler(*args, **kwargs):
            return args[-1].get("other_key", "default")

        result = await handler({"other_key": "kept"})
        assert result == "kept"

    @pytest.mark.asyncio
    async def test_decorator_reraises_validation_error(self):
        @validate_input({"name": InputValidator.validate_anomaly_name})
        async def handler(*args, **kwargs):
            return args[-1]["name"]

        with pytest.raises(ValidationError):
            await handler({"name": ""})

    @pytest.mark.asyncio
    async def test_decorator_with_dict_validator_calls_func(self):
        called_with = []

        def my_validator(val, multiplier=1):
            called_with.append(val)
            return val * multiplier

        @validate_input({"count": {"func": my_validator, "kwargs": {"multiplier": 2}}})
        async def handler(*args, **kwargs):
            return args[-1]["count"]

        result = await handler({"count": 5})
        assert result == 10
        assert called_with == [5]

    @pytest.mark.asyncio
    async def test_decorator_converts_unexpected_exception_to_validation_error(self):
        def bad_validator(val):
            raise RuntimeError("unexpected error")

        @validate_input({"name": bad_validator})
        async def handler(*args, **kwargs):
            pass

        with pytest.raises(ValidationError) as exc_info:
            await handler({"name": "test"})
        assert "unexpected error" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_decorator_last_arg_not_dict_skips_validation(self):
        @validate_input({"name": InputValidator.validate_anomaly_name})
        async def handler(*args, **kwargs):
            return "done"

        # pass non-dict as last arg — no validation should run
        result = await handler("not_a_dict")
        assert result == "done"


# ---------------------------------------------------------------------------
# Module-level constants sanity checks
# ---------------------------------------------------------------------------

class TestModuleLevelConstants:
    def test_anomaly_validation_rules_name_validates_correctly(self):
        # The name validator in ANOMALY_VALIDATION_RULES must reject empty names
        # and accept valid ones — verifying the right function is wired up.
        validator = ANOMALY_VALIDATION_RULES["name"]
        assert validator("My Anomaly") == "My Anomaly"
        with pytest.raises(ValidationError):
            validator("")

    def test_anomaly_validation_rules_detection_rules_validates_list(self):
        # The detection_rules lambda must validate each rule in the list.
        validator = ANOMALY_VALIDATION_RULES["detection_rules"]
        valid_rule = {"rule_type": "THRESHOLD", "metric": "error_rate", "operator": ">", "value": 5}
        result = validator([valid_rule])
        assert len(result) == 1
        assert result[0]["rule_type"] == "THRESHOLD"

    def test_alert_validation_rules_alert_id_validates_uuid(self):
        validator = ALERT_VALIDATION_RULES["alert_id"]
        uid = "123e4567-e89b-12d3-a456-426614174000"
        assert validator(uid) == uid

    def test_alert_validation_rules_invalid_uuid_raises(self):
        validator = ALERT_VALIDATION_RULES["alert_id"]
        with pytest.raises(ValidationError):
            validator("not-a-uuid")

    def test_pagination_rules_page_accepts_zero(self):
        validator = PAGINATION_VALIDATION_RULES["page"]
        assert validator(0) == 0

    def test_pagination_rules_size_rejects_zero(self):
        validator = PAGINATION_VALIDATION_RULES["size"]
        with pytest.raises(ValidationError):
            validator(0)

    def test_pagination_rules_size_rejects_over_1000(self):
        validator = PAGINATION_VALIDATION_RULES["size"]
        with pytest.raises(ValidationError):
            validator(1001)
