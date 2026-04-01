"""Unit tests for AlertManager in alerts/alert_manager.py.

Tests the behavioral logic of alert data extraction, formatting,
natural language query parsing, and duration calculation.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from src.revenium_mcp_server.alerts.alert_manager import AlertManager
from src.revenium_mcp_server.exceptions import ValidationError
from mcp.types import TextContent


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
        assert manager._extract_threshold_condition(alert) == "> 2.5M"

    def test_large_number_formatting_thousands(self, manager):
        alert = {"anomaly": {"operatorType": "GREATER_THAN_OR_EQUAL_TO", "threshold": 5000}}
        result = manager._extract_threshold_condition(alert)
        assert result == "\u2265 5.0K"

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
        assert manager._extract_triggered_value({"triggeredValue": 5000}) == "5.0K"

    def test_millions(self, manager):
        assert manager._extract_triggered_value({"triggeredValue": 1500000}) == "1.5M"

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
    def test_severity_critical(self, manager):
        filters = manager._parse_natural_language_query("show critical alerts")
        assert filters.get("severity") == "critical"

    def test_severity_high(self, manager):
        filters = manager._parse_natural_language_query("high severity alerts")
        assert filters.get("severity") == "high"

    def test_severity_medium(self, manager):
        filters = manager._parse_natural_language_query("medium priority alerts")
        assert filters.get("severity") == "medium"

    def test_severity_low(self, manager):
        filters = manager._parse_natural_language_query("low alerts")
        assert filters.get("severity") == "low"

    def test_status_open(self, manager):
        filters = manager._parse_natural_language_query("open alerts")
        assert filters.get("status") == "open"

    def test_status_acknowledged(self, manager):
        filters = manager._parse_natural_language_query("acknowledged alerts")
        assert filters.get("status") == "acknowledged"

    def test_status_investigating(self, manager):
        filters = manager._parse_natural_language_query("investigating alerts")
        assert filters.get("status") == "investigating"

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
        assert "> 100" in text

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

        await manager.list_alerts(client, filters={"custom": "val"}, query="critical alerts")
        # Should not crash; the merged filters are passed to get_alerts
        call_kwargs = client.get_alerts.call_args[1]
        assert call_kwargs.get("severity") == "critical"
        assert call_kwargs.get("custom") == "val"


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
        """Validation errors are caught by decorator and returned as text."""
        client = MagicMock()
        result = await manager.update_alert(client, "a1", "not-a-dict")
        assert len(result) == 1
        assert "must be a dictionary" in result[0].text


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
