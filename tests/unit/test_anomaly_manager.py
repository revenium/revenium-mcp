"""Unit tests for AnomalyManager in alerts/anomaly_manager.py.

Tests formatting helpers, validation logic, notification processing,
and CRUD operations with mocked API client.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.alerts.anomaly_manager import AnomalyManager
from src.revenium_mcp_server.exceptions import ValidationError


@pytest.fixture
def manager():
    return AnomalyManager()


# ---------------------------------------------------------------------------
# _format_frequency_info: maps API period codes to human-readable strings
# ---------------------------------------------------------------------------


class TestFormatFrequencyInfo:
    def test_known_frequencies(self, manager):
        assert manager._format_frequency_info("ONE_MINUTE") == "Every minute"
        assert manager._format_frequency_info("FIVE_MINUTES") == "Every 5 minutes"
        assert manager._format_frequency_info("ONE_HOUR") == "Every hour"
        assert manager._format_frequency_info("ONE_DAY") == "Daily"
        assert manager._format_frequency_info("SEVEN_DAYS") == "Weekly"
        assert manager._format_frequency_info("THIRTY_DAYS") == "Monthly"

    def test_unknown_frequency_passthrough(self, manager):
        assert manager._format_frequency_info("UNKNOWN_PERIOD") == "UNKNOWN_PERIOD"


# ---------------------------------------------------------------------------
# _format_trigger_duration_info: maps trigger persistence codes
# ---------------------------------------------------------------------------


class TestFormatTriggerDurationInfo:
    def test_known_durations(self, manager):
        assert manager._format_trigger_duration_info("FIVE_MINUTES") == "5 minutes"
        assert manager._format_trigger_duration_info("ONE_HOUR") == "1 hour"
        assert manager._format_trigger_duration_info("ONE_DAY") == "1 day"
        assert manager._format_trigger_duration_info("SEVEN_DAYS") == "1 week"

    def test_unknown_duration_passthrough(self, manager):
        assert manager._format_trigger_duration_info("CUSTOM_DURATION") == "CUSTOM_DURATION"


# ---------------------------------------------------------------------------
# _format_notification_summary: concise notification count for list views
# ---------------------------------------------------------------------------


class TestFormatNotificationSummary:
    def test_email_only(self, manager):
        data = {"notificationAddresses": ["a@b.com", "c@d.com"]}
        assert manager._format_notification_summary(data) == "2 emails"

    def test_single_email(self, manager):
        data = {"notificationAddresses": ["a@b.com"]}
        assert manager._format_notification_summary(data) == "1 email"

    def test_slack_only(self, manager):
        data = {"slackConfigurations": ["cfg-1", "cfg-2", "cfg-3"]}
        assert manager._format_notification_summary(data) == "3 Slack"

    def test_email_and_slack(self, manager):
        data = {
            "notificationAddresses": ["a@b.com"],
            "slackConfigurations": ["cfg-1"],
        }
        result = manager._format_notification_summary(data)
        assert "1 email" in result
        assert "1 Slack" in result

    def test_no_notifications(self, manager):
        assert manager._format_notification_summary({}) == "No notifications"


# ---------------------------------------------------------------------------
# _process_advanced_configuration: copies advanced fields to validated dict
# ---------------------------------------------------------------------------


class TestProcessAdvancedConfiguration:
    def test_notification_addresses(self, manager):
        validated = {}
        manager._process_advanced_configuration(
            {"notification_addresses": ["a@b.com"]}, validated
        )
        assert validated["notification_addresses"] == ["a@b.com"]

    def test_filters(self, manager):
        validated = {}
        manager._process_advanced_configuration(
            {"filters": [{"dimension": "MODEL", "operator": "IS", "value": "gpt-4"}]},
            validated,
        )
        assert len(validated["filters"]) == 1

    def test_alert_type_snake_case(self, manager):
        validated = {}
        manager._process_advanced_configuration({"alert_type": "THRESHOLD"}, validated)
        assert validated["alert_type"] == "THRESHOLD"

    def test_alert_type_camel_case(self, manager):
        validated = {}
        manager._process_advanced_configuration({"alertType": "CUMULATIVE_USAGE"}, validated)
        assert validated["alert_type"] == "CUMULATIVE_USAGE"

    def test_empty_lists_ignored(self, manager):
        validated = {}
        manager._process_advanced_configuration(
            {"notification_addresses": [], "filters": []}, validated
        )
        assert "notification_addresses" not in validated
        assert "filters" not in validated


# ---------------------------------------------------------------------------
# _has_direct_api_format / _validate_direct_api_format
# ---------------------------------------------------------------------------


class TestHasDirectApiFormat:
    def test_complete_api_format(self, manager):
        data = {
            "alertType": "THRESHOLD",
            "metricType": "TOTAL_COST",
            "operatorType": "GREATER_THAN",
            "threshold": 100,
        }
        assert manager._has_direct_api_format(data) is True

    def test_missing_fields(self, manager):
        assert manager._has_direct_api_format({"alertType": "THRESHOLD"}) is False
        assert manager._has_direct_api_format({}) is False


class TestValidateDirectApiFormat:
    def test_valid_data(self, manager):
        data = {
            "alertType": "THRESHOLD",
            "metricType": "TOTAL_COST",
            "operatorType": "GREATER_THAN",
            "threshold": 100,
        }
        result = manager._validate_direct_api_format(data)
        assert result["alertType"] == "THRESHOLD"
        assert result["threshold"] == 100.0

    def test_invalid_alert_type_raises(self, manager):
        data = {
            "alertType": "INVALID_TYPE",
            "metricType": "TOTAL_COST",
            "operatorType": "GREATER_THAN",
            "threshold": 100,
        }
        with pytest.raises(ValidationError):
            manager._validate_direct_api_format(data)

    def test_invalid_threshold_raises(self, manager):
        data = {
            "alertType": "THRESHOLD",
            "metricType": "TOTAL_COST",
            "operatorType": "GREATER_THAN",
            "threshold": "not-a-number",
        }
        with pytest.raises(ValidationError):
            manager._validate_direct_api_format(data)

    def test_missing_required_field_raises(self, manager):
        data = {
            "alertType": "THRESHOLD",
            "metricType": "TOTAL_COST",
            # missing operatorType and threshold
        }
        with pytest.raises(ValidationError):
            manager._validate_direct_api_format(data)

    def test_optional_period_duration_validated(self, manager):
        data = {
            "alertType": "THRESHOLD",
            "metricType": "TOTAL_COST",
            "operatorType": "GREATER_THAN",
            "threshold": 100,
            "periodDuration": "INVALID_PERIOD",
        }
        with pytest.raises(ValidationError):
            manager._validate_direct_api_format(data)

    def test_optional_boolean_validated(self, manager):
        data = {
            "alertType": "THRESHOLD",
            "metricType": "TOTAL_COST",
            "operatorType": "GREATER_THAN",
            "threshold": 100,
            "isPercentage": "not-a-bool",
        }
        with pytest.raises(ValidationError):
            manager._validate_direct_api_format(data)

    def test_optional_list_validated(self, manager):
        data = {
            "alertType": "THRESHOLD",
            "metricType": "TOTAL_COST",
            "operatorType": "GREATER_THAN",
            "threshold": 100,
            "notificationAddresses": "not-a-list",
        }
        with pytest.raises(ValidationError):
            manager._validate_direct_api_format(data)

    def test_increases_by_with_non_relative_change_raises(self, manager):
        data = {
            "alertType": "THRESHOLD",
            "metricType": "TOTAL_COST",
            "operatorType": "INCREASES_BY",
            "threshold": 10,
        }
        with pytest.raises(ValidationError) as exc_info:
            manager._validate_direct_api_format(data)
        assert "RELATIVE_CHANGE" in exc_info.value.message

    def test_decreases_by_with_non_relative_change_raises(self, manager):
        data = {
            "alertType": "CUMULATIVE_USAGE",
            "metricType": "TOTAL_COST",
            "operatorType": "DECREASES_BY",
            "threshold": 10,
        }
        with pytest.raises(ValidationError) as exc_info:
            manager._validate_direct_api_format(data)
        assert "RELATIVE_CHANGE" in exc_info.value.message

    def test_relative_change_with_threshold_operator_raises(self, manager):
        data = {
            "alertType": "RELATIVE_CHANGE",
            "metricType": "TOTAL_COST",
            "operatorType": "GREATER_THAN",
            "threshold": 10,
        }
        with pytest.raises(ValidationError) as exc_info:
            manager._validate_direct_api_format(data)
        assert "relative operator" in exc_info.value.message

    def test_relative_change_with_increases_by_valid(self, manager):
        data = {
            "alertType": "RELATIVE_CHANGE",
            "metricType": "TOTAL_COST",
            "operatorType": "INCREASES_BY",
            "threshold": 10,
        }
        result = manager._validate_direct_api_format(data)
        assert result["alertType"] == "RELATIVE_CHANGE"
        assert result["operatorType"] == "INCREASES_BY"

    def test_relative_change_with_decreases_by_valid(self, manager):
        data = {
            "alertType": "RELATIVE_CHANGE",
            "metricType": "TOTAL_COST",
            "operatorType": "DECREASES_BY",
            "threshold": 10,
        }
        result = manager._validate_direct_api_format(data)
        assert result["alertType"] == "RELATIVE_CHANGE"
        assert result["operatorType"] == "DECREASES_BY"


# ---------------------------------------------------------------------------
# _process_convenience_notification_fields
# ---------------------------------------------------------------------------


class TestProcessConvenienceNotificationFields:
    def test_email_convenience(self, manager):
        data = {"email": "user@co.com", "alertType": "THRESHOLD"}
        result = manager._process_convenience_notification_fields(data)
        assert "email" not in result
        assert result["notificationAddresses"] == ["user@co.com"]

    def test_slack_config_id_convenience(self, manager):
        data = {"slackConfigId": "slack-123"}
        result = manager._process_convenience_notification_fields(data)
        assert "slackConfigId" not in result
        assert result["slackConfigurations"] == ["slack-123"]

    def test_tracking_period_daily(self, manager):
        data = {"trackingPeriod": "daily"}
        result = manager._process_convenience_notification_fields(data)
        assert result["periodDuration"] == "DAILY"

    def test_tracking_period_monthly(self, manager):
        data = {"trackingPeriod": "monthly"}
        result = manager._process_convenience_notification_fields(data)
        assert result["periodDuration"] == "MONTHLY"

    def test_tracking_period_unknown_passthrough(self, manager):
        data = {"trackingPeriod": "biweekly"}
        result = manager._process_convenience_notification_fields(data)
        assert result["periodDuration"] == "biweekly"

    def test_does_not_duplicate_email(self, manager):
        data = {
            "email": "user@co.com",
            "notificationAddresses": ["user@co.com"],
        }
        result = manager._process_convenience_notification_fields(data)
        assert result["notificationAddresses"] == ["user@co.com"]

    def test_empty_email_ignored(self, manager):
        data = {"email": "  "}
        result = manager._process_convenience_notification_fields(data)
        assert "notificationAddresses" not in result


# ---------------------------------------------------------------------------
# Async CRUD operations
# ---------------------------------------------------------------------------


class TestListAnomalies:
    @pytest.mark.asyncio
    async def test_empty_response_no_anomalies(self, manager):
        client = MagicMock()
        client.get_anomalies = AsyncMock(return_value={})
        client._extract_embedded_data = MagicMock(return_value=[])
        client._extract_pagination_info = MagicMock(
            return_value={"totalElements": 0, "totalPages": 1}
        )

        result = await manager.list_anomalies(client)
        assert "No AI anomalies found" in result[0].text

    @pytest.mark.asyncio
    async def test_page_beyond_results(self, manager):
        client = MagicMock()
        client.get_anomalies = AsyncMock(return_value={})
        client._extract_embedded_data = MagicMock(return_value=[])
        client._extract_pagination_info = MagicMock(
            return_value={"totalElements": 10, "totalPages": 2}
        )

        result = await manager.list_anomalies(client, page=5)
        assert "beyond available results" in result[0].text

    @pytest.mark.asyncio
    async def test_formats_anomaly_list(self, manager):
        anomaly = {
            "id": "anom-1",
            "name": "Cost Spike",
            "alertType": "THRESHOLD",
            "metricType": "TOTAL_COST",
            "enabled": True,
            "threshold": 100,
            "createdAt": "2024-01-15T10:00:00Z",
            "filters": [],
        }
        client = MagicMock()
        client.get_anomalies = AsyncMock(return_value={})
        client._extract_embedded_data = MagicMock(return_value=[anomaly])
        client._extract_pagination_info = MagicMock(
            return_value={"totalPages": 1, "totalElements": 1}
        )

        result = await manager.list_anomalies(client)
        text = result[0].text
        assert "Cost Spike" in text
        assert "anom-1" in text
        assert "Enabled" in text

    @pytest.mark.asyncio
    async def test_filter_summary_single_filter(self, manager):
        anomaly = {
            "id": "anom-2",
            "name": "Filtered",
            "enabled": True,
            "filters": [{"dimension": "MODEL", "operator": "CONTAINS", "value": "gpt-4"}],
            "createdAt": "2024-01-15",
        }
        client = MagicMock()
        client.get_anomalies = AsyncMock(return_value={})
        client._extract_embedded_data = MagicMock(return_value=[anomaly])
        client._extract_pagination_info = MagicMock(
            return_value={"totalPages": 1, "totalElements": 1}
        )

        result = await manager.list_anomalies(client)
        text = result[0].text
        assert "MODEL" in text
        assert "gpt-4" in text

    @pytest.mark.asyncio
    async def test_persistence_duration_shown(self, manager):
        anomaly = {
            "id": "anom-3",
            "name": "Persistent",
            "enabled": True,
            "filters": [],
            "triggerAfterPersistsDuration": "FIVE_MINUTES",
            "createdAt": "2024-01-15",
        }
        client = MagicMock()
        client.get_anomalies = AsyncMock(return_value={})
        client._extract_embedded_data = MagicMock(return_value=[anomaly])
        client._extract_pagination_info = MagicMock(
            return_value={"totalPages": 1, "totalElements": 1}
        )

        result = await manager.list_anomalies(client)
        assert "5 minutes" in result[0].text


class TestGetAnomaly:
    @pytest.mark.asyncio
    async def test_formats_anomaly_details(self, manager):
        anomaly = {
            "id": "anom-1",
            "name": "Cost Alert",
            "enabled": True,
            "description": "Monitors total cost",
            "createdAt": "2024-01-15",
            "updatedAt": "2024-01-16",
            "alertType": "THRESHOLD",
            "metricType": "TOTAL_COST",
            "operatorType": "GREATER_THAN",
            "threshold": 100,
            "periodDuration": "FIFTEEN_MINUTES",
        }
        client = MagicMock()
        client.get_anomaly_by_id = AsyncMock(return_value=anomaly)
        client.get_slack_configuration_by_id = AsyncMock()

        result = await manager.get_anomaly(client, "anom-1")
        text = result[0].text
        assert "Cost Alert" in text
        assert "TOTAL_COST" in text
        assert "> 100" in text
        assert "15 minutes" in text or "Every 15 minutes" in text

    @pytest.mark.asyncio
    async def test_shows_filters(self, manager):
        anomaly = {
            "id": "anom-2",
            "name": "Filtered Alert",
            "filters": [{"dimension": "PROVIDER", "operator": "IS", "value": "openai"}],
        }
        client = MagicMock()
        client.get_anomaly_by_id = AsyncMock(return_value=anomaly)
        client.get_slack_configuration_by_id = AsyncMock()

        result = await manager.get_anomaly(client, "anom-2")
        text = result[0].text
        assert "PROVIDER" in text
        assert "openai" in text


class TestCreateAnomaly:
    @pytest.mark.asyncio
    async def test_non_dict_returns_error(self, manager):
        """Validation errors are caught by decorator and returned as text."""
        client = MagicMock()
        result = await manager.create_anomaly(client, "not-a-dict")
        assert "must be a dictionary" in result[0].text

    @pytest.mark.asyncio
    async def test_missing_name_returns_error(self, manager):
        client = MagicMock()
        result = await manager.create_anomaly(client, {"metricType": "TOTAL_COST"})
        assert "name" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_missing_rules_and_api_format_returns_error(self, manager):
        """Must have either detection_rules or direct API format."""
        client = MagicMock()
        result = await manager.create_anomaly(client, {"name": "Test Alert"})
        assert "detection_rules" in result[0].text or "required" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_successful_create_with_direct_api_format(self, manager):
        created = {
            "id": "new-1",
            "name": "Budget Alert",
            "alertType": "CUMULATIVE_USAGE",
            "metricType": "TOTAL_COST",
            "operatorType": "GREATER_THAN",
            "threshold": 1000,
            "enabled": True,
            "createdAt": "2024-01-15",
        }
        client = MagicMock()
        client.team_id = "team-1"
        client.create_anomaly = AsyncMock(return_value=created)

        result = await manager.create_anomaly(
            client,
            {
                "name": "Budget Alert",
                "alertType": "CUMULATIVE_USAGE",
                "metricType": "TOTAL_COST",
                "operatorType": "GREATER_THAN",
                "threshold": 1000,
            },
        )
        text = result[0].text
        assert "Created Successfully" in text
        assert "Budget Alert" in text


class TestUpdateAnomaly:
    @pytest.mark.asyncio
    async def test_non_dict_returns_error(self, manager):
        """Validation errors are caught by decorator and returned as text."""
        client = MagicMock()
        result = await manager.update_anomaly(client, "anom-1", "bad")
        assert "must be a dictionary" in result[0].text

    @pytest.mark.asyncio
    async def test_email_field_conversion(self, manager):
        """Email convenience field should be converted to notificationAddresses."""
        current = {"id": "anom-1", "name": "Test", "enabled": True}
        updated = {"id": "anom-1", "name": "Test", "enabled": True}
        client = MagicMock()
        client.get_anomaly_by_id = AsyncMock(return_value=current)
        client.update_anomaly = AsyncMock(return_value=updated)
        client.get_slack_configuration_by_id = AsyncMock()

        await manager.update_anomaly(client, "anom-1", {"email": "test@co.com"})
        call_args = client.update_anomaly.call_args[0]
        merged_data = call_args[1]
        assert merged_data["notificationAddresses"] == ["test@co.com"]

    @pytest.mark.asyncio
    async def test_period_minutes_conversion(self, manager):
        """period_minutes should be converted to periodDuration."""
        current = {"id": "anom-1", "name": "Test"}
        client = MagicMock()
        client.get_anomaly_by_id = AsyncMock(return_value=current)
        client.update_anomaly = AsyncMock(return_value=current)
        client.get_slack_configuration_by_id = AsyncMock()

        await manager.update_anomaly(client, "anom-1", {"period_minutes": 15})
        merged_data = client.update_anomaly.call_args[0][1]
        assert merged_data["periodDuration"] == "FIFTEEN_MINUTES"

    @pytest.mark.asyncio
    async def test_invalid_period_minutes_returns_error(self, manager):
        """Invalid period_minutes caught by decorator, returned as text."""
        current = {"id": "anom-1", "name": "Test"}
        client = MagicMock()
        client.get_anomaly_by_id = AsyncMock(return_value=current)

        result = await manager.update_anomaly(client, "anom-1", {"period_minutes": 99})
        assert "period_minutes" in result[0].text.lower() or "invalid" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_is_percentage_bool_conversion(self, manager):
        current = {"id": "anom-1", "name": "Test"}
        client = MagicMock()
        client.get_anomaly_by_id = AsyncMock(return_value=current)
        client.update_anomaly = AsyncMock(return_value=current)
        client.get_slack_configuration_by_id = AsyncMock()

        await manager.update_anomaly(client, "anom-1", {"is_percentage": "true"})
        merged_data = client.update_anomaly.call_args[0][1]
        assert merged_data["isPercentage"] is True

    @pytest.mark.asyncio
    async def test_tracking_period_conversion(self, manager):
        current = {"id": "anom-1", "name": "Test"}
        client = MagicMock()
        client.get_anomaly_by_id = AsyncMock(return_value=current)
        client.update_anomaly = AsyncMock(return_value=current)
        client.get_slack_configuration_by_id = AsyncMock()

        await manager.update_anomaly(client, "anom-1", {"tracking_period": "monthly"})
        merged_data = client.update_anomaly.call_args[0][1]
        assert merged_data["periodDuration"] == "MONTHLY"


class TestDeleteAnomaly:
    @pytest.mark.asyncio
    async def test_successful_delete(self, manager):
        client = MagicMock()
        client.delete_anomaly = AsyncMock(return_value=None)

        result = await manager.delete_anomaly(client, "anom-1")
        assert "Deleted Successfully" in result[0].text
        assert "anom-1" in result[0].text


class TestClearAllAnomalies:
    @pytest.mark.asyncio
    async def test_no_anomalies_to_clear(self, manager):
        client = MagicMock()
        client.get_anomalies = AsyncMock(return_value={})
        client._extract_embedded_data = MagicMock(return_value=[])

        result = await manager.clear_all_anomalies(client)
        assert "No anomalies to clear" in result[0].text

    @pytest.mark.asyncio
    async def test_clears_all_anomalies(self, manager):
        client = MagicMock()
        client.get_anomalies = AsyncMock(return_value={})
        client._extract_embedded_data = MagicMock(
            return_value=[{"id": "a1"}, {"id": "a2"}, {"id": "a3"}]
        )
        client.delete_anomaly = AsyncMock(return_value=None)

        result = await manager.clear_all_anomalies(client)
        text = result[0].text
        assert "3" in text
        assert client.delete_anomaly.call_count == 3

    @pytest.mark.asyncio
    async def test_partial_failure_warning(self, manager):
        """Should warn when some deletions fail."""
        client = MagicMock()
        client.get_anomalies = AsyncMock(return_value={})
        client._extract_embedded_data = MagicMock(
            return_value=[{"id": "a1"}, {"id": "a2"}]
        )
        client.delete_anomaly = AsyncMock(side_effect=[None, Exception("API error")])

        result = await manager.clear_all_anomalies(client)
        text = result[0].text
        assert "1" in text  # 1 deleted
        assert "could not be deleted" in text


class TestFormatNotificationConfiguration:
    @pytest.mark.asyncio
    async def test_no_notifications(self, manager):
        client = MagicMock()
        result = await manager._format_notification_configuration(client, {})
        assert "No notifications configured" in result

    @pytest.mark.asyncio
    async def test_email_notifications(self, manager):
        client = MagicMock()
        data = {"notificationAddresses": ["admin@co.com", "ops@co.com"]}
        result = await manager._format_notification_configuration(client, data)
        assert "admin@co.com" in result
        assert "ops@co.com" in result

    @pytest.mark.asyncio
    async def test_slack_notifications_fetched(self, manager):
        client = MagicMock()
        client.get_slack_configuration_by_id = AsyncMock(
            return_value={
                "name": "Prod Alerts",
                "channelName": "alerts",
                "teamName": "Engineering",
            }
        )
        data = {"slackConfigurations": ["slack-1"]}
        result = await manager._format_notification_configuration(client, data)
        assert "Prod Alerts" in result
        assert "#alerts" in result

    @pytest.mark.asyncio
    async def test_slack_fetch_failure_graceful(self, manager):
        client = MagicMock()
        client.get_slack_configuration_by_id = AsyncMock(
            side_effect=Exception("Not found")
        )
        data = {"slackConfigurations": ["slack-1"]}
        result = await manager._format_notification_configuration(client, data)
        assert "Details unavailable" in result
