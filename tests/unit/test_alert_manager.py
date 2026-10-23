"""Unit tests for AlertManager in alerts/alert_manager.py.

Tests the behavioral logic of alert data extraction, formatting,
natural language query parsing, and duration calculation.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timedelta, timezone

from src.revenium_mcp_server.alerts.alert_manager import (
    PRE_RULE_ACTIVITY_LABEL,
    PRE_RULE_ACTIVITY_VALUE,
    AlertManager,
)
from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.common.error_handling import ToolError


@pytest.fixture
def manager():
    """Create an AlertManager instance."""
    return AlertManager()


# ---------------------------------------------------------------------------
# _extract_alert_name: determines display name from nested API response
# ---------------------------------------------------------------------------


class TestExtractAlertName:
    """Test alert name extraction from various API response shapes."""

    def test_name_from_nested_anomaly(self, manager):
        """Name should come from the nested anomaly object first."""
        alert = {"anomaly": {"name": "Cost Spike Alert"}}
        assert manager._extract_alert_name(alert) == "Cost Spike Alert"

    def test_label_from_nested_anomaly(self, manager):
        """Label field in anomaly should be used if name is absent."""
        alert = {"anomaly": {"label": "Budget Threshold"}}
        assert manager._extract_alert_name(alert) == "Budget Threshold"

    def test_fallback_to_alert_level_fields(self, manager):
        """Should fall back to top-level name/label/description/title."""
        alert = {"anomaly": {}, "title": "Fallback Title"}
        assert manager._extract_alert_name(alert) == "Fallback Title"

    def test_fallback_to_alert_id(self, manager):
        """When no name fields exist, construct from alert ID."""
        alert = {"id": "abc-123"}
        assert manager._extract_alert_name(alert) == "Alert Event abc-123"

    def test_untitled_when_no_info(self, manager):
        """When no name info at all, return 'Untitled Alert'."""
        assert manager._extract_alert_name({}) == "Untitled Alert"

    def test_whitespace_only_name_is_skipped(self, manager):
        """Whitespace-only names should be skipped."""
        alert = {"anomaly": {"name": "   "}, "name": "Real Name"}
        assert manager._extract_alert_name(alert) == "Real Name"

    def test_non_dict_anomaly_ignored(self, manager):
        """Non-dict anomaly field should be handled gracefully."""
        alert = {"anomaly": "not-a-dict", "name": "Direct Name"}
        assert manager._extract_alert_name(alert) == "Direct Name"


# ---------------------------------------------------------------------------
# _extract_alert_state: determines Firing/Resolved/Disabled from alert data
# ---------------------------------------------------------------------------


class TestExtractAlertState:
    """Test alert state extraction logic covering all decision branches."""

    def test_resolved_true(self, manager):
        alert = {"resolved": True}
        assert manager._extract_alert_state(alert) == "Resolved"

    def test_resolved_false(self, manager):
        alert = {"resolved": False}
        assert manager._extract_alert_state(alert) == "Firing"

    def test_has_resolved_timestamp_means_resolved(self, manager):
        alert = {"resolvedTimestamp": "2024-01-01T00:00:00Z"}
        assert manager._extract_alert_state(alert) == "Resolved"

    def test_has_triggered_timestamp_only_means_firing(self, manager):
        alert = {"triggeredTimestamp": "2024-01-01T00:00:00Z"}
        assert manager._extract_alert_state(alert) == "Firing"

    def test_anomaly_disabled(self, manager):
        alert = {"anomaly": {"enabled": False}}
        assert manager._extract_alert_state(alert) == "Disabled"

    def test_anomaly_firing(self, manager):
        alert = {"anomaly": {"enabled": True, "firing": True}}
        assert manager._extract_alert_state(alert) == "Firing"

    def test_anomaly_ready(self, manager):
        alert = {"anomaly": {"enabled": True, "firing": False}}
        assert manager._extract_alert_state(alert) == "Ready"

    def test_legacy_status_mapping_without_anomaly_key(self, manager):
        """Legacy string states should map when no anomaly key is present.

        The anomaly fallback defaults to {} which triggers "Ready" branch.
        Only when anomaly key is absent entirely do we reach the state mapping.
        We need to pass anomaly=None or not-dict to skip it.
        """
        # When anomaly is absent from dict but state is present,
        # the default empty dict triggers "Ready" via the anomaly branch.
        # The state mapping is only reached via the final fallback.
        # Test the final fallback path by ensuring anomaly field is not a dict.
        assert manager._extract_alert_state({"anomaly": "not-dict", "state": "open"}) == "Firing"
        assert manager._extract_alert_state({"anomaly": "not-dict", "state": "active"}) == "Firing"
        assert manager._extract_alert_state({"anomaly": "not-dict", "state": "closed"}) == "Resolved"
        assert manager._extract_alert_state({"anomaly": "not-dict", "state": "acknowledged"}) == "Acknowledged"
        assert manager._extract_alert_state({"anomaly": "not-dict", "status": "firing"}) == "Firing"

    def test_empty_anomaly_defaults_to_ready(self, manager):
        """When anomaly is empty dict with no firing/enabled, returns Ready."""
        assert manager._extract_alert_state({"state": "open"}) == "Ready"

    def test_unknown_state_title_cased(self, manager):
        """Unknown states should be title-cased via the fallback path."""
        assert manager._extract_alert_state({"anomaly": "not-dict", "state": "pending"}) == "Pending"

    def test_non_string_state(self, manager):
        """Non-string state values should be converted."""
        alert = {"anomaly": "not-dict", "state": 42}
        result = manager._extract_alert_state(alert)
        assert result == "42"


# ---------------------------------------------------------------------------
# _extract_threshold_condition: formats threshold display string
# ---------------------------------------------------------------------------


class TestExtractThresholdCondition:
    """Test threshold condition extraction and formatting."""

    def test_from_nested_anomaly(self, manager):
        alert = {"anomaly": {"operatorType": "GREATER_THAN", "threshold": 100}}
        assert manager._extract_threshold_condition(alert) == "> 100"

    def test_percentage_threshold(self, manager):
        alert = {"anomaly": {"operatorType": "LESS_THAN", "threshold": 5, "isPercentage": True}}
        assert manager._extract_threshold_condition(alert) == "< 5%"

    def test_large_number_formatting_millions(self, manager):
        alert = {"anomaly": {"operatorType": "GREATER_THAN", "threshold": 2500000}}
        assert manager._extract_threshold_condition(alert) == "> 2,500,000"

    def test_large_number_formatting_thousands(self, manager):
        alert = {"anomaly": {"operatorType": "GREATER_THAN_OR_EQUAL_TO", "threshold": 5000}}
        result = manager._extract_threshold_condition(alert)
        assert result == "\u2265 5,000"

    def test_all_operator_mappings(self, manager):
        """All operator types should map to readable symbols."""
        operators = {
            "GREATER_THAN": ">",
            "GREATER_THAN_OR_EQUAL_TO": "\u2265",
            "LESS_THAN": "<",
            "LESS_THAN_OR_EQUAL_TO": "\u2264",
            "EQUALS": "=",
            "NOT_EQUALS": "\u2260",
        }
        for op_type, symbol in operators.items():
            alert = {"anomaly": {"operatorType": op_type, "threshold": 10}}
            result = manager._extract_threshold_condition(alert)
            assert result.startswith(symbol), f"{op_type} should map to {symbol}"

    def test_fallback_to_direct_fields(self, manager):
        alert = {"operatorType": "LESS_THAN", "threshold": 50}
        assert manager._extract_threshold_condition(alert) == "< 50"

    def test_unknown_operator_passed_through(self, manager):
        alert = {"anomaly": {"operatorType": "CUSTOM_OP", "threshold": 7}}
        assert manager._extract_threshold_condition(alert) == "CUSTOM_OP 7"

    def test_no_threshold_returns_na(self, manager):
        assert manager._extract_threshold_condition({}) == "N/A"


# ---------------------------------------------------------------------------
# _extract_triggered_value: formats triggered value with number formatting
# ---------------------------------------------------------------------------


class TestExtractTriggeredValue:
    """Test triggered value extraction and number formatting."""

    def test_small_value(self, manager):
        assert manager._extract_triggered_value({"triggeredValue": 42}) == "42"

    def test_thousands(self, manager):
        assert manager._extract_triggered_value({"triggeredValue": 5000}) == "5,000"

    def test_millions(self, manager):
        assert manager._extract_triggered_value({"triggeredValue": 1500000}) == "1,500,000"

    def test_string_value(self, manager):
        assert manager._extract_triggered_value({"triggeredValue": "custom"}) == "custom"

    def test_missing_returns_na(self, manager):
        assert manager._extract_triggered_value({}) == "N/A"

    def test_zero_value(self, manager):
        assert manager._extract_triggered_value({"triggeredValue": 0}) == "0"


# ---------------------------------------------------------------------------
# _extract_metric_type, _extract_alert_type, _extract_period_duration
# ---------------------------------------------------------------------------


class TestExtractMetricType:
    def test_from_anomaly(self, manager):
        alert = {"anomaly": {"metricType": "TOTAL_COST"}}
        assert manager._extract_metric_type(alert) == "TOTAL_COST"

    def test_from_direct_field(self, manager):
        alert = {"metricType": "ERROR_RATE"}
        assert manager._extract_metric_type(alert) == "ERROR_RATE"

    def test_fallback_fields(self, manager):
        alert = {"metric_name": "TOKEN_COUNT"}
        assert manager._extract_metric_type(alert) == "TOKEN_COUNT"

    def test_missing_returns_na(self, manager):
        assert manager._extract_metric_type({}) == "N/A"


class TestExtractAlertType:
    def test_known_type_mapping(self, manager):
        alert = {"anomaly": {"alertType": "CUMULATIVE_USAGE"}}
        assert manager._extract_alert_type(alert) == "Cumulative Usage"

    def test_threshold_type(self, manager):
        alert = {"anomaly": {"alertType": "THRESHOLD"}}
        assert manager._extract_alert_type(alert) == "Threshold"

    def test_unknown_type_formatted(self, manager):
        alert = {"anomaly": {"alertType": "SOME_NEW_TYPE"}}
        assert manager._extract_alert_type(alert) == "Some New Type"

    def test_fallback_to_direct_field(self, manager):
        alert = {"alertType": "RELATIVE_CHANGE"}
        assert manager._extract_alert_type(alert) == "Relative Change"

    def test_missing_returns_na(self, manager):
        assert manager._extract_alert_type({}) == "N/A"


class TestExtractPeriodDuration:
    def test_known_periods(self, manager):
        alert = {"anomaly": {"periodDuration": "FIVE_MINUTES"}}
        assert manager._extract_period_duration(alert) == "5 minutes"

    def test_daily(self, manager):
        alert = {"anomaly": {"periodDuration": "DAILY"}}
        assert manager._extract_period_duration(alert) == "Daily"

    def test_unknown_period_formatted(self, manager):
        alert = {"anomaly": {"periodDuration": "TWO_HOURS"}}
        assert manager._extract_period_duration(alert) == "Two Hours"

    def test_missing_returns_na(self, manager):
        assert manager._extract_period_duration({}) == "N/A"


# ---------------------------------------------------------------------------
# _extract_team_info: formats team display string
# ---------------------------------------------------------------------------


class TestExtractTeamInfo:
    def test_team_with_label_and_id(self, manager):
        alert = {"team": {"label": "Engineering", "id": "team-1"}}
        assert manager._extract_team_info(alert) == "Engineering (team-1)"

    def test_team_with_label_only(self, manager):
        alert = {"team": {"label": "Engineering"}}
        assert manager._extract_team_info(alert) == "Engineering"

    def test_team_with_id_only(self, manager):
        alert = {"team": {"id": "team-1"}}
        assert manager._extract_team_info(alert) == "team-1"

    def test_no_team_returns_na(self, manager):
        assert manager._extract_team_info({}) == "N/A"


# ---------------------------------------------------------------------------
# _extract_severity: extracts severity from various fields
# ---------------------------------------------------------------------------


class TestExtractSeverity:
    def test_direct_severity(self, manager):
        assert manager._extract_severity({"severity": "high"}) == "High"

    def test_priority_field(self, manager):
        assert manager._extract_severity({"priority": "critical"}) == "Critical"

    def test_from_threshold_violation(self, manager):
        alert = {"threshold_violation": {"severity": "low"}}
        assert manager._extract_severity(alert) == "Low"

    def test_default_medium(self, manager):
        assert manager._extract_severity({}) == "Medium"


# ---------------------------------------------------------------------------
# _extract_triggered_time / _extract_resolved_time: timestamp extraction
# ---------------------------------------------------------------------------


class TestExtractTimestamps:
    def test_triggered_from_primary_field(self, manager):
        alert = {"triggeredTimestamp": "2024-01-15T10:30:00Z"}
        assert manager._extract_triggered_time(alert) == "2024-01-15T10:30:00Z"

    def test_triggered_from_datetime_object(self, manager):
        dt = datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
        alert = {"triggeredTimestamp": dt}
        assert "2024-01-15" in manager._extract_triggered_time(alert)

    def test_triggered_fallback_fields(self, manager):
        alert = {"created": "2024-01-15T10:30:00Z"}
        assert manager._extract_triggered_time(alert) == "2024-01-15T10:30:00Z"

    def test_triggered_missing(self, manager):
        assert manager._extract_triggered_time({}) is None

    def test_resolved_from_primary_field(self, manager):
        alert = {"resolvedTimestamp": "2024-01-15T11:30:00Z"}
        assert manager._extract_resolved_time(alert) == "2024-01-15T11:30:00Z"

    def test_resolved_fallback_fields(self, manager):
        alert = {"updated": "2024-01-15T11:30:00Z"}
        assert manager._extract_resolved_time(alert) == "2024-01-15T11:30:00Z"

    def test_resolved_missing(self, manager):
        assert manager._extract_resolved_time({}) is None

    def test_non_string_non_datetime_timestamp(self, manager):
        """Numeric timestamps should be converted to string."""
        alert = {"triggeredTimestamp": 1705312200}
        result = manager._extract_triggered_time(alert)
        assert result == "1705312200"


# ---------------------------------------------------------------------------
# _format_timestamp: format for display
# ---------------------------------------------------------------------------


class TestFormatTimestamp:
    def test_none_returns_na(self, manager):
        assert manager._format_timestamp(None) == "N/A"

    def test_valid_iso_timestamp(self, manager):
        result = manager._format_timestamp("2024-01-15T10:30:00Z")
        assert "2024-01-15" in result
        assert "10:30:00" in result

    def test_invalid_timestamp_truncated(self, manager):
        result = manager._format_timestamp("not-a-timestamp-but-long-enough-string")
        # Should return first 19 chars as fallback
        assert len(result) == 19


# ---------------------------------------------------------------------------
# _calculate_duration: calculates human-readable duration
# ---------------------------------------------------------------------------


class TestCalculateDuration:
    def test_no_triggered_time(self, manager):
        assert manager._calculate_duration({}) == "N/A"

    def test_resolved_duration_seconds(self, manager):
        alert = {
            "triggeredTimestamp": "2024-01-15T10:30:00Z",
            "resolvedTimestamp": "2024-01-15T10:30:45Z",
        }
        result = manager._calculate_duration(alert)
        assert "45s" in result

    def test_resolved_duration_minutes(self, manager):
        alert = {
            "triggeredTimestamp": "2024-01-15T10:00:00Z",
            "resolvedTimestamp": "2024-01-15T10:05:30Z",
        }
        result = manager._calculate_duration(alert)
        assert "5m" in result

    def test_resolved_duration_hours(self, manager):
        alert = {
            "triggeredTimestamp": "2024-01-15T10:00:00Z",
            "resolvedTimestamp": "2024-01-15T12:30:00Z",
        }
        result = manager._calculate_duration(alert)
        assert "2h" in result

    def test_ongoing_duration(self, manager):
        """Alert without resolved timestamp should show ongoing."""
        alert = {"triggeredTimestamp": "2020-01-15T10:00:00Z"}
        result = manager._calculate_duration(alert)
        assert "ongoing" in result

    def test_parse_error_returns_na(self, manager):
        alert = {"triggeredTimestamp": "garbage-timestamp"}
        result = manager._calculate_duration(alert)
        assert "N/A" in result


# ---------------------------------------------------------------------------
# _parse_natural_language_query: NLP query parsing for alert history
# ---------------------------------------------------------------------------


class TestParseNaturalLanguageQuery:
    """BACK-2783: only names GET /sources/ai/alert declares may be produced.

    The endpoint has no severity and no status parameter, so the words that
    used to become `severity=`/`status=` query params must not reach the API —
    they never filtered anything, they just made an unfiltered list look
    filtered.
    """

    @pytest.mark.parametrize(
        "query",
        [
            "show critical alerts",
            "high severity alerts",
            "medium priority alerts",
            "low alerts",
            "open alerts",
            "acknowledged alerts",
            "investigating alerts",
        ],
    )
    def test_no_undeclared_keys(self, manager, query):
        filters = manager._parse_natural_language_query(query)
        assert "severity" not in filters
        assert "status" not in filters
        assert set(filters) <= {"start", "end"}

    def test_date_range_still_parsed(self, manager):
        filters = manager._parse_natural_language_query("critical alerts in the last 24 hours")
        assert filters.get("start")
        assert filters.get("end")

    def test_empty_query(self, manager):
        filters = manager._parse_natural_language_query("")
        # Should not crash; no severity or status
        assert "severity" not in filters
        assert "status" not in filters


# ---------------------------------------------------------------------------
# _extract_notification_addresses / _extract_anomaly_name
# ---------------------------------------------------------------------------


class TestExtractNotificationAddresses:
    def test_with_addresses(self, manager):
        alert = {"notificationAddresses": ["a@b.com", "c@d.com"]}
        assert manager._extract_notification_addresses(alert) == "a@b.com, c@d.com"

    def test_empty_list(self, manager):
        assert manager._extract_notification_addresses({"notificationAddresses": []}) == "None"

    def test_missing_field(self, manager):
        assert manager._extract_notification_addresses({}) == "None"


class TestExtractAnomalyName:
    def test_from_name_field(self, manager):
        alert = {"name": "Budget Alert"}
        assert manager._extract_anomaly_name(alert) == "Budget Alert"

    def test_from_anomaly_name_field(self, manager):
        alert = {"anomalyName": "Token Alert"}
        assert manager._extract_anomaly_name(alert) == "Token Alert"

    def test_fallback_to_id(self, manager):
        alert = {"id": "abc-123"}
        assert manager._extract_anomaly_name(alert) == "ID: abc-123"

    def test_no_info_returns_na(self, manager):
        assert manager._extract_anomaly_name({}) == "N/A"


# ---------------------------------------------------------------------------
# Async API methods: list_alerts, get_alert, update_alert, delete_alert,
# acknowledge_alert
# ---------------------------------------------------------------------------


class TestListAlerts:
    @pytest.mark.asyncio
    async def test_empty_response(self, manager):
        """Empty results should return a 'no alerts found' message."""
        client = MagicMock()
        client.get_alerts = AsyncMock(return_value={})
        client._extract_embedded_data = MagicMock(return_value=[])
        client._extract_pagination_info = MagicMock(return_value={})

        result = await manager.list_alerts(client)
        assert len(result) == 1
        assert "No alerts found" in result[0].text

    @pytest.mark.asyncio
    async def test_returns_formatted_alert_list(self, manager):
        """Should format alerts with all extracted fields."""
        alert_data = {
            "id": "alert-1",
            "resolved": False,
            "anomaly": {
                "name": "Cost Alert",
                "operatorType": "GREATER_THAN",
                "threshold": 100,
                "metricType": "TOTAL_COST",
                "alertType": "THRESHOLD",
                "periodDuration": "FIFTEEN_MINUTES",
            },
            "triggeredTimestamp": "2024-01-15T10:00:00Z",
            "triggeredValue": 150,
            "team": {"label": "Engineering", "id": "t1"},
        }
        client = MagicMock()
        client.get_alerts = AsyncMock(return_value={})
        client._extract_embedded_data = MagicMock(return_value=[alert_data])
        client._extract_pagination_info = MagicMock(
            return_value={"totalPages": 1, "totalElements": 1}
        )

        result = await manager.list_alerts(client)
        text = result[0].text
        assert "Cost Alert" in text
        assert "Active" in text
        assert "TOTAL_COST" in text
        assert "> $100.00" in text

    @pytest.mark.asyncio
    async def test_query_appended_to_output(self, manager):
        """When a query is provided, it should appear in the output."""
        client = MagicMock()
        client.get_alerts = AsyncMock(return_value={})
        client._extract_embedded_data = MagicMock(return_value=[])
        client._extract_pagination_info = MagicMock(return_value={})

        result = await manager.list_alerts(client, query="critical alerts")
        # Even with no results, no crash
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_natural_language_query_filters_merged(self, manager):
        """NL query should be parsed and merged with explicit filters."""
        client = MagicMock()
        client.get_alerts = AsyncMock(return_value={})
        client._extract_embedded_data = MagicMock(return_value=[])
        client._extract_pagination_info = MagicMock(return_value={})

        await manager.list_alerts(client, filters={"resolved": False}, query="last 24 hours")
        # The caller's filters survive, and the NL parse contributes only the
        # date range the endpoint declares (BACK-2783).
        call_kwargs = client.get_alerts.call_args[1]
        assert call_kwargs.get("resolved") is False
        assert call_kwargs.get("start")
        assert call_kwargs.get("end")
        assert "severity" not in call_kwargs


class TestGetAlert:
    @pytest.mark.asyncio
    async def test_formats_alert_details(self, manager):
        """get_alert should return formatted detail text."""
        alert_data = {
            "id": "alert-1",
            "resolved": True,
            "anomaly": {
                "name": "Budget Alert",
                "description": "Budget threshold exceeded",
                "operatorType": "GREATER_THAN",
                "threshold": 500,
                "metricType": "TOTAL_COST",
                "alertType": "CUMULATIVE_USAGE",
                "periodDuration": "MONTHLY",
            },
            "triggeredTimestamp": "2024-01-15T10:00:00Z",
            "resolvedTimestamp": "2024-01-15T12:00:00Z",
            "triggeredValue": 600,
            "team": {"label": "Billing", "id": "t2"},
        }
        client = MagicMock()
        client.get_alert_by_id = AsyncMock(return_value=alert_data)

        result = await manager.get_alert(client, "alert-1")
        text = result[0].text
        assert "Budget Alert" in text
        assert "Resolved" in text
        assert "Budget threshold exceeded" in text
        assert "TOTAL_COST" in text

    @pytest.mark.asyncio
    async def test_includes_filters_and_integrations(self, manager):
        """Detail view should show filters and integration info."""
        alert_data = {
            "id": "alert-2",
            "anomaly": {"name": "Test"},
            "filters": [{"type": "model", "value": "gpt-4"}],
            "slackConfigurations": ["slack-1"],
            "webhookConfigurations": ["webhook-1"],
        }
        client = MagicMock()
        client.get_alert_by_id = AsyncMock(return_value=alert_data)

        result = await manager.get_alert(client, "alert-2")
        text = result[0].text
        assert "Filters" in text
        assert "Slack" in text
        assert "Webhooks" in text

    @pytest.mark.asyncio
    async def test_includes_api_link(self, manager):
        alert_data = {
            "id": "alert-3",
            "anomaly": {},
            "_links": {"self": {"href": "https://api.revenium.io/alerts/3"}},
        }
        client = MagicMock()
        client.get_alert_by_id = AsyncMock(return_value=alert_data)

        result = await manager.get_alert(client, "alert-3")
        assert "https://api.revenium.io/alerts/3" in result[0].text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [403, 404])
    async def test_get_alert_translates_not_found_status_codes(self, manager, status_code):
        """get_alert folds 403/404 from the alerts service into the
        AlertNotFoundError envelope so the @handle_alert_tool_errors
        decorator renders a rich 'alert not found' message — callers
        no longer see the catch-all 'Unexpected Error' prose surfaced
        by the decorator's last-resort handler (BACK-1142; same shape
        as BACK-1098 on manage_tools). The envelope is raised so the caller
        sees it flagged as an error (BACK-4705)."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        client = MagicMock()
        client.get_alert_by_id = AsyncMock(
            side_effect=ReveniumAPIError("not found", status_code=status_code)
        )

        with pytest.raises(ToolError) as exc_info:
            await manager.get_alert(client, "NONEXISTENT_12345")

        assert exc_info.value.error_code == "ALERT_NOT_FOUND"
        text = exc_info.value.message
        assert "Unexpected Error" not in text
        assert "NONEXISTENT_12345" in text
        # AlertNotFoundError.format_user_message() renders 'not found' prose
        assert "not found" in text.lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [500, 503])
    async def test_get_alert_server_error_is_not_a_not_found(self, manager, status_code):
        """A platform server error on an alert history read is named a server
        error and flagged, never folded into 'not found' (BACK-4705)."""
        from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError

        client = MagicMock()
        client.get_alert_by_id = AsyncMock(
            side_effect=ReveniumAPIError("upstream broke", status_code=status_code)
        )

        with pytest.raises(ToolError) as exc_info:
            await manager.get_alert(client, "alert_abc")

        assert exc_info.value.error_code == ErrorCodes.API_ERROR
        message = exc_info.value.message
        assert "server error" in message.lower()
        assert "alert_abc" in message
        assert str(status_code) in message
        assert "not found" not in message.lower()

    @pytest.mark.asyncio
    async def test_get_alert_other_status_codes_propagate_as_exception(self, manager):
        """A malformed id answers 400, which the client already words as
        "Invalid Alert ID"; get_alert must pass that error on unchanged rather
        than fold it into AlertNotFoundError."""
        client_error = ReveniumAPIError(
            "Invalid Alert ID\n\nThe provided alert ID is not valid or does not exist.",
            status_code=400,
        )
        client = MagicMock()
        client.get_alert_by_id = AsyncMock(side_effect=client_error)

        with pytest.raises(ReveniumAPIError) as exc_info:
            await manager.get_alert(client, "NONEXISTENT_12345")

        assert exc_info.value is client_error
        assert exc_info.value.status_code == 400
        assert exc_info.value.message.startswith("Invalid Alert ID")

    @pytest.mark.asyncio
    async def test_get_alert_unauthorized_tool_error_propagates_not_invalid_value(
        self, manager
    ):
        """UnauthorizedToolError must propagate through the decorator (it
        subclasses ValueError via AuthenticationError, and pre-fix matched
        the decorator's `except ValueError` branch and surfaced as
        'Invalid Value' TextContent with isError=false)."""
        from src.revenium_mcp_server.common.auth_response_envelope import (
            auth_error_to_tool_error,
        )
        from src.revenium_mcp_server.common.error_handling import (
            ErrorCodes,
            ToolError,
        )

        client = MagicMock()
        client.get_alert_by_id = AsyncMock(
            side_effect=auth_error_to_tool_error("missing credential")
        )

        with pytest.raises(ToolError) as exc_info:
            await manager.get_alert(client, "alert-id")

        assert exc_info.value.error_code == ErrorCodes.UNAUTHORIZED
        assert "Invalid Value" not in exc_info.value.message


class TestUpdateAlert:
    @pytest.mark.asyncio
    async def test_successful_update(self, manager):
        client = MagicMock()
        client.update_alert = AsyncMock(
            return_value={"id": "a1", "anomaly": {"name": "Updated Alert"}}
        )

        result = await manager.update_alert(client, "a1", {"name": "Updated Alert"})
        assert "Updated Successfully" in result[0].text

    @pytest.mark.asyncio
    async def test_non_dict_update_data_returns_error(self, manager):
        """Validation errors are caught by the decorator and raised flagged."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        client = MagicMock()
        with pytest.raises(ToolError) as exc_info:
            await manager.update_alert(client, "a1", "not-a-dict")
        assert "must be a dictionary" in exc_info.value.message


class TestDeleteAlert:
    @pytest.mark.asyncio
    async def test_successful_delete(self, manager):
        client = MagicMock()
        client.delete_alert = AsyncMock(return_value=None)

        result = await manager.delete_alert(client, "a1")
        assert "Deleted Successfully" in result[0].text
        assert "a1" in result[0].text


class TestAcknowledgeAlert:
    @pytest.mark.asyncio
    async def test_acknowledge_with_user(self, manager):
        client = MagicMock()
        client.update_alert = AsyncMock(
            return_value={"id": "a1", "anomaly": {"name": "My Alert"}}
        )

        result = await manager.acknowledge_alert(client, "a1", acknowledged_by="admin@co.com")
        text = result[0].text
        assert "Acknowledged Successfully" in text
        assert "admin@co.com" in text

    @pytest.mark.asyncio
    async def test_acknowledge_without_user(self, manager):
        client = MagicMock()
        client.update_alert = AsyncMock(
            return_value={"id": "a1", "anomaly": {"name": "My Alert"}}
        )

        result = await manager.acknowledge_alert(client, "a1")
        text = result[0].text
        assert "System" in text

    @pytest.mark.asyncio
    async def test_acknowledge_passes_status(self, manager):
        """Acknowledge should send 'acknowledged' status to the API."""
        client = MagicMock()
        client.update_alert = AsyncMock(return_value={"id": "a1"})

        await manager.acknowledge_alert(client, "a1")
        call_args = client.update_alert.call_args
        update_data = call_args[0][1]
        assert update_data["status"] == "acknowledged"


# ---------------------------------------------------------------------------
# includesPreRuleActivity: tells a reader a first-day alert apart from a
# steady-state one (BACK-3350)
# ---------------------------------------------------------------------------


def _alert_with_pre_rule_activity(value=None):
    alert = {
        "id": "alert-pra",
        "resolved": False,
        "anomaly": {"name": "Cost Alert", "metricType": "TOTAL_COST"},
        "triggeredValue": 150,
    }
    if value is not None:
        alert["includesPreRuleActivity"] = value
    return alert


def _list_client(alert):
    client = MagicMock()
    client.get_alerts = AsyncMock(return_value={})
    client._extract_embedded_data = MagicMock(return_value=[alert])
    client._extract_pagination_info = MagicMock(
        return_value={"totalPages": 1, "totalElements": 1}
    )
    return client


class TestExtractPreRuleActivity:
    def test_true_returns_the_qualifier(self, manager):
        assert (
            manager._extract_pre_rule_activity({"includesPreRuleActivity": True})
            == PRE_RULE_ACTIVITY_VALUE
        )

    def test_false_returns_none(self, manager):
        assert manager._extract_pre_rule_activity({"includesPreRuleActivity": False}) is None

    def test_absent_returns_none(self, manager):
        assert manager._extract_pre_rule_activity({}) is None


class TestPreRuleActivityRendering:
    @pytest.mark.asyncio
    async def test_list_names_the_qualifier_when_true(self, manager):
        result = await manager.list_alerts(_list_client(_alert_with_pre_rule_activity(True)))
        text = result[0].text
        assert "Pre-Rule Activity: Counted (usage from before the rule was created)" in text

    @pytest.mark.asyncio
    async def test_list_omits_the_qualifier_when_false(self, manager):
        result = await manager.list_alerts(_list_client(_alert_with_pre_rule_activity(False)))
        assert PRE_RULE_ACTIVITY_LABEL not in result[0].text

    @pytest.mark.asyncio
    async def test_list_omits_the_qualifier_when_absent(self, manager):
        result = await manager.list_alerts(_list_client(_alert_with_pre_rule_activity()))
        assert PRE_RULE_ACTIVITY_LABEL not in result[0].text

    @pytest.mark.asyncio
    async def test_detail_names_the_qualifier_when_true(self, manager):
        client = MagicMock()
        client.get_alert_by_id = AsyncMock(return_value=_alert_with_pre_rule_activity(True))

        result = await manager.get_alert(client, "alert-pra")
        assert (
            "**Pre-Rule Activity:** Counted (usage from before the rule was created)"
            in result[0].text
        )

    @pytest.mark.asyncio
    async def test_detail_omits_the_qualifier_when_false(self, manager):
        client = MagicMock()
        client.get_alert_by_id = AsyncMock(return_value=_alert_with_pre_rule_activity(False))

        result = await manager.get_alert(client, "alert-pra")
        assert PRE_RULE_ACTIVITY_LABEL not in result[0].text

    @pytest.mark.asyncio
    async def test_detail_omits_the_qualifier_when_absent(self, manager):
        client = MagicMock()
        client.get_alert_by_id = AsyncMock(return_value=_alert_with_pre_rule_activity())

        result = await manager.get_alert(client, "alert-pra")
        assert PRE_RULE_ACTIVITY_LABEL not in result[0].text


def _sent_instant(client, key):
    value = client.get_alerts.await_args.kwargs[key]
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestAlertHistoryWindowFollowsTheClock:
    """The server builds one tool at startup; every window must count from the question."""

    @pytest.mark.asyncio
    async def test_last_hour_counts_back_from_the_question_not_from_tool_start(
        self, frozen_utc_clock
    ):
        from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement

        frozen_utc_clock.current = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
        client = _list_client(_alert_with_pre_rule_activity())
        tool = AlertManagement()
        tool.get_client = AsyncMock(return_value=client)

        asked = datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc)
        frozen_utc_clock.current = asked
        await tool.handle_action(
            "list", {"resource_type": "alerts", "query": "show alerts from the last hour"}
        )
        assert _sent_instant(client, "end") == asked
        assert _sent_instant(client, "start") == asked - timedelta(hours=1)

        asked_again = asked + timedelta(seconds=10)
        frozen_utc_clock.current = asked_again
        await tool.handle_action(
            "list", {"resource_type": "alerts", "query": "show alerts from the last hour"}
        )
        assert _sent_instant(client, "end") == asked_again
        assert _sent_instant(client, "start") == asked_again - timedelta(hours=1)

        await tool.handle_action(
            "list", {"resource_type": "alerts", "query": "show high cost alerts"}
        )
        assert _sent_instant(client, "end") == asked_again
        assert _sent_instant(client, "start") == asked_again - timedelta(days=30)


class TestAlertHistoryNamesItsWindow:
    """Every answer says which window it read, and an unusable window is refused."""

    @pytest.mark.asyncio
    async def test_the_answer_names_the_window_it_read(self, manager, frozen_utc_clock):
        client = _list_client(_alert_with_pre_rule_activity())
        result = await manager.list_alerts(
            client, query="show alerts from 2026-10-12 to 2026-10-14"
        )
        assert (
            "**Window:** 2026-10-12T00:00:00.000Z to 2026-10-14T23:59:59.999Z (UTC)"
            in result[0].text
        )

    @pytest.mark.asyncio
    async def test_an_empty_answer_still_names_the_window(self, manager, frozen_utc_clock):
        client = _list_client(_alert_with_pre_rule_activity())
        client._extract_embedded_data = MagicMock(return_value=[])
        result = await manager.list_alerts(client, query="show alerts yesterday")
        text = result[0].text
        assert "No alerts found" in text
        assert "**Window:** 2026-10-14T00:00:00.000Z to 2026-10-14T23:59:59.999Z (UTC)" in text

    @pytest.mark.asyncio
    async def test_the_answer_says_when_no_date_range_was_recognized(
        self, manager, frozen_utc_clock
    ):
        client = _list_client(_alert_with_pre_rule_activity())
        result = await manager.list_alerts(client, query="show alerts last quarter")
        text = result[0].text
        assert "**Window:** 2026-09-15T15:30:45.123Z to 2026-10-15T15:30:45.123Z (UTC)" in text
        assert "no date range recognized in the question, so the last 30 days" in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "query",
        [
            "show alerts from 2026-10-14 to 2026-10-12",
            "show alerts from Oct 14 to Oct 12",
            "show alerts from October 14th to October 2nd",
        ],
    )
    async def test_an_inverted_range_is_refused_without_a_platform_call(
        self, manager, frozen_utc_clock, query
    ):
        client = _list_client(_alert_with_pre_rule_activity())
        with pytest.raises(ToolError) as exc_info:
            await manager.list_alerts(client, query=query)
        assert str(exc_info.value).startswith("Window refused:")
        assert exc_info.value.field == "query"
        assert client.get_alerts.await_count == 0

    @pytest.mark.asyncio
    async def test_an_unreadable_date_is_refused_as_an_error_naming_the_filter(
        self, manager, frozen_utc_clock
    ):
        client = _list_client(_alert_with_pre_rule_activity())
        with pytest.raises(ToolError) as exc_info:
            await manager.list_alerts(client, filters={"start": "garbage"})
        assert str(exc_info.value).startswith("Window refused:")
        assert exc_info.value.field == "filters.start"
        assert client.get_alerts.await_count == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "start",
        ["2026-10-01", "2026-10-01T00:00:00Z", "2026-10-01T02:00:00+02:00"],
    )
    async def test_every_date_form_reaches_the_platform_in_millisecond_utc(
        self, manager, frozen_utc_clock, start
    ):
        client = _list_client(_alert_with_pre_rule_activity())
        await manager.list_alerts(client, filters={"start": start, "end": "2026-10-15"})
        sent = client.get_alerts.await_args.kwargs
        assert (sent["start"], sent["end"]) == (
            "2026-10-01T00:00:00.000Z",
            "2026-10-15T23:59:59.999Z",
        )

    @pytest.mark.asyncio
    async def test_explicit_calendar_days_are_sent_in_the_platform_form(
        self, manager, frozen_utc_clock
    ):
        client = _list_client(_alert_with_pre_rule_activity())
        await manager.list_alerts(client, filters={"start": "2026-10-12", "end": "2026-10-14"})
        sent = client.get_alerts.await_args.kwargs
        assert (sent["start"], sent["end"]) == (
            "2026-10-12T00:00:00.000Z",
            "2026-10-14T23:59:59.999Z",
        )

    @pytest.mark.asyncio
    async def test_explicit_dates_survive_an_undated_question(self, manager, frozen_utc_clock):
        client = _list_client(_alert_with_pre_rule_activity())
        result = await manager.list_alerts(
            client,
            filters={"start": "2026-10-01T00:00:00.000Z", "end": "2026-10-02T00:00:00.000Z"},
            query="show high cost alerts",
        )
        sent = client.get_alerts.await_args.kwargs
        assert (sent["start"], sent["end"]) == (
            "2026-10-01T00:00:00.000Z",
            "2026-10-02T00:00:00.000Z",
        )
        assert "no date range recognized" not in result[0].text


def _fired_alert(triggered_value, threshold, metric_type, **anomaly_fields):
    return {
        "triggeredValue": triggered_value,
        "anomaly": {
            "operatorType": "GREATER_THAN",
            "threshold": threshold,
            "metricType": metric_type,
            **anomaly_fields,
        },
    }


class TestAlertValuesKeepTheirUnits:
    """A fired value prints in full, with a currency for cost, never as 1.0K."""

    def test_cost_overshoot_keeps_its_cents_and_currency(self, manager):
        alert = _fired_alert(1023.48633754, 1000.0, "TOTAL_COST")
        assert manager._extract_threshold_condition(alert) == "> $1,000.00"
        assert manager._extract_triggered_value(alert) == "$1,023.49"

    def test_cost_under_a_thousand_is_rounded_to_cents(self, manager):
        alert = _fired_alert(705.02063079, 700.0, "TOTAL_COST")
        assert manager._extract_threshold_condition(alert) == "> $700.00"
        assert manager._extract_triggered_value(alert) == "$705.02"

    def test_small_cost_keeps_its_significant_digits(self, manager):
        alert = _fired_alert(0.0523, 0.05, "COST_PER_TRANSACTION")
        assert manager._extract_threshold_condition(alert) == "> $0.05"
        assert manager._extract_triggered_value(alert) == "$0.0523"

    def test_counts_keep_every_digit(self, manager):
        alert = _fired_alert(1500000, 1023, "TOKEN_COUNT")
        assert manager._extract_threshold_condition(alert) == "> 1,023"
        assert manager._extract_triggered_value(alert) == "1,500,000"

    def test_percentage_rule_has_no_currency(self, manager):
        alert = _fired_alert(35.5, 20, "TOTAL_COST", isPercentage=True)
        assert manager._extract_triggered_value(alert) == "35.5"
        assert manager._extract_threshold_condition(alert) == "> 20%"

    def test_percent_increase_condition_reads_in_words(self, manager):
        alert = _fired_alert(35.5, 20, "TOTAL_COST", operatorType="PERCENT_INCREASE")
        assert manager._extract_threshold_condition(alert) == "increases by 20%"

    def test_cost_below_a_millionth_keeps_its_significant_digits(self, manager):
        alert = _fired_alert(0.0000002, 0.0000001, "COST_PER_TRANSACTION")
        assert manager._extract_threshold_condition(alert) == "> $0.0000001"
        assert manager._extract_triggered_value(alert) == "$0.0000002"

    def test_fraction_below_a_millionth_keeps_its_significant_digits(self, manager):
        alert = _fired_alert(0.0000002, 0.0000001, "ERROR_RATE")
        assert manager._extract_triggered_value(alert) == "0.0000002"

    def test_negative_cost_puts_the_sign_first(self, manager):
        alert = _fired_alert(-5, 0, "TOTAL_COST")
        assert manager._extract_triggered_value(alert) == "-$5.00"

    @pytest.mark.asyncio
    async def test_list_shows_the_overshoot(self, manager):
        alert = {"id": "l3moXN", **_fired_alert(1023.48633754, 1000.0, "TOTAL_COST")}
        result = await manager.list_alerts(_list_client(alert))
        text = result[0].text
        assert "Condition: > $1,000.00" in text
        assert "Triggered Value: $1,023.49" in text
