"""Unit tests for Alert Creation Suite — lines 2357-3139.

Covers:
- _resolve_notification_email (2357-2405)
- _resolve_notification_config (2406-2442)
- _handle_create_cumulative_usage_alert (2480-2653)
- _handle_create_threshold_alert (2654-2858)
- _handle_create_from_text (2859-2920)
- _simple_parse_alert_text (2921-3067)
- _handle_create_simple (3068-3139)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from typing import Dict, Any

from mcp.types import TextContent

from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.exceptions import ValidationError


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_tools_with_client():
    """Return (AlertManagement, mock_client) with get_client patched."""
    tools = AlertManagement()
    client = MagicMock()
    client.team_id = "team_test"
    tools.get_client = AsyncMock(return_value=client)
    tools.anomaly_manager.create_anomaly = AsyncMock(
        return_value=[TextContent(type="text", text="Alert created successfully")]
    )
    return tools, client


def _notification_config(email="test@example.com", slack=None):
    return {
        "notificationAddresses": [email],
        "slackConfigurations": [slack] if slack else [],
    }


# ===========================================================================
# _resolve_notification_email
# ===========================================================================


class TestResolveNotificationEmail:
    """Cover _resolve_notification_email: provided, env var, discovered, error."""

    def test_returns_provided_email(self):
        tools = AlertManagement()
        result = tools._resolve_notification_email("user@corp.com")
        assert result == "user@corp.com"

    def test_strips_whitespace_from_provided(self):
        tools = AlertManagement()
        result = tools._resolve_notification_email("  padded@email.com  ")
        assert result == "padded@email.com"

    def test_skips_empty_provided_email(self):
        """Empty string should not be treated as provided."""
        tools = AlertManagement()
        with patch.dict("os.environ", {"REVENIUM_DEFAULT_EMAIL": "env@corp.com"}):
            result = tools._resolve_notification_email("")
        assert result == "env@corp.com"

    def test_skips_whitespace_only_provided_email(self):
        tools = AlertManagement()
        with patch.dict("os.environ", {"REVENIUM_DEFAULT_EMAIL": "env@corp.com"}):
            result = tools._resolve_notification_email("   ")
        assert result == "env@corp.com"

    def test_falls_back_to_env_var(self):
        tools = AlertManagement()
        with patch.dict("os.environ", {"REVENIUM_DEFAULT_EMAIL": "env@test.com"}):
            result = tools._resolve_notification_email(None)
        assert result == "env@test.com"

    def test_strips_env_var_email(self):
        tools = AlertManagement()
        with patch.dict("os.environ", {"REVENIUM_DEFAULT_EMAIL": "  env@test.com  "}):
            result = tools._resolve_notification_email(None)
        assert result == "env@test.com"

    def test_skips_dummy_env_email(self):
        """The dummy@email.com sentinel should be skipped."""
        tools = AlertManagement()
        mock_config = MagicMock()
        mock_config.default_email = "discovered@corp.com"
        with patch.dict("os.environ", {"REVENIUM_DEFAULT_EMAIL": "dummy@email.com"}):
            with patch(
                "src.revenium_mcp_server.config_store.get_discovered_config_sync",
                return_value=mock_config,
            ):
                result = tools._resolve_notification_email(None)
        assert result == "discovered@corp.com"

    def test_falls_back_to_discovered_config(self):
        tools = AlertManagement()
        mock_config = MagicMock()
        mock_config.default_email = "discovered@test.com"
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "src.revenium_mcp_server.config_store.get_discovered_config_sync",
                return_value=mock_config,
            ):
                result = tools._resolve_notification_email(None)
        assert result == "discovered@test.com"

    def test_discovered_config_stripped(self):
        tools = AlertManagement()
        mock_config = MagicMock()
        mock_config.default_email = "  trimme@test.com  "
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "src.revenium_mcp_server.config_store.get_discovered_config_sync",
                return_value=mock_config,
            ):
                result = tools._resolve_notification_email(None)
        assert result == "trimme@test.com"

    def test_raises_validation_error_when_nothing_available(self):
        tools = AlertManagement()
        mock_config = MagicMock()
        mock_config.default_email = None
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "src.revenium_mcp_server.config_store.get_discovered_config_sync",
                return_value=mock_config,
            ):
                with pytest.raises(ValidationError) as exc_info:
                    tools._resolve_notification_email(None)
                assert "email" in str(exc_info.value).lower()

    def test_raises_when_discovered_email_empty(self):
        tools = AlertManagement()
        mock_config = MagicMock()
        mock_config.default_email = "   "
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "src.revenium_mcp_server.config_store.get_discovered_config_sync",
                return_value=mock_config,
            ):
                with pytest.raises(ValidationError):
                    tools._resolve_notification_email(None)

    def test_provided_email_takes_precedence_over_env(self):
        tools = AlertManagement()
        with patch.dict("os.environ", {"REVENIUM_DEFAULT_EMAIL": "env@corp.com"}):
            result = tools._resolve_notification_email("provided@corp.com")
        assert result == "provided@corp.com"

    def test_env_var_takes_precedence_over_discovered(self):
        tools = AlertManagement()
        mock_config = MagicMock()
        mock_config.default_email = "discovered@corp.com"
        with patch.dict("os.environ", {"REVENIUM_DEFAULT_EMAIL": "env@corp.com"}):
            with patch(
                "src.revenium_mcp_server.config_store.get_discovered_config_sync",
                return_value=mock_config,
            ):
                result = tools._resolve_notification_email(None)
        assert result == "env@corp.com"


# ===========================================================================
# _resolve_notification_config
# ===========================================================================


class TestResolveNotificationConfig:
    """Cover _resolve_notification_config: email + Slack resolution."""

    def test_config_with_email_only(self):
        tools = AlertManagement()
        with patch.object(tools, "_resolve_notification_email", return_value="a@b.com"):
            with patch(
                "src.revenium_mcp_server.config_store.get_config_value",
                return_value=None,
            ):
                config = tools._resolve_notification_config("a@b.com")
        assert config["notificationAddresses"] == ["a@b.com"]
        assert config["slackConfigurations"] == []

    def test_config_with_provided_slack_id(self):
        tools = AlertManagement()
        with patch.object(tools, "_resolve_notification_email", return_value="a@b.com"):
            config = tools._resolve_notification_config("a@b.com", "slack-cfg-123")
        assert config["slackConfigurations"] == ["slack-cfg-123"]

    def test_config_falls_back_to_default_slack(self):
        tools = AlertManagement()
        with patch.object(tools, "_resolve_notification_email", return_value="a@b.com"):
            with patch(
                "src.revenium_mcp_server.config_store.get_config_value",
                return_value="default-slack-id",
            ):
                config = tools._resolve_notification_config("a@b.com")
        assert config["slackConfigurations"] == ["default-slack-id"]

    def test_provided_slack_overrides_default(self):
        tools = AlertManagement()
        with patch.object(tools, "_resolve_notification_email", return_value="a@b.com"):
            with patch(
                "src.revenium_mcp_server.config_store.get_config_value",
                return_value="default-slack-id",
            ):
                config = tools._resolve_notification_config("a@b.com", "custom-slack")
        assert config["slackConfigurations"] == ["custom-slack"]

    def test_propagates_validation_error_from_email(self):
        tools = AlertManagement()
        with patch.object(
            tools,
            "_resolve_notification_email",
            side_effect=ValidationError(message="No email", field="email"),
        ):
            with pytest.raises(ValidationError):
                tools._resolve_notification_config(None)


# ===========================================================================
# _handle_create_cumulative_usage_alert
# ===========================================================================


class TestHandleCreateCumulativeUsageAlert:
    """Cover _handle_create_cumulative_usage_alert: validation, happy path, errors."""

    @pytest.mark.asyncio
    async def test_happy_path_monthly(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            with patch.object(
                tools, "_post_alert_creation_prompting", new_callable=AsyncMock, return_value=""
            ):
                result = await tools._handle_create_cumulative_usage_alert(
                    client,
                    {"name": "Budget Alert", "threshold": 1000, "period": "monthly", "email": "a@b.com"},
                )
        assert isinstance(result[0], TextContent)
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["alertType"] == "CUMULATIVE_USAGE"
        assert call_data["periodDuration"] == "MONTHLY"
        assert call_data["threshold"] == 1000.0

    @pytest.mark.asyncio
    async def test_daily_period(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            with patch.object(
                tools, "_post_alert_creation_prompting", new_callable=AsyncMock, return_value=""
            ):
                await tools._handle_create_cumulative_usage_alert(
                    client,
                    {"name": "Daily", "threshold": 100, "period": "daily"},
                )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["periodDuration"] == "DAILY"

    @pytest.mark.asyncio
    async def test_weekly_period(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            with patch.object(
                tools, "_post_alert_creation_prompting", new_callable=AsyncMock, return_value=""
            ):
                await tools._handle_create_cumulative_usage_alert(
                    client,
                    {"name": "Weekly", "threshold": 500, "period": "weekly"},
                )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["periodDuration"] == "WEEKLY"

    @pytest.mark.asyncio
    async def test_quarterly_period(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            with patch.object(
                tools, "_post_alert_creation_prompting", new_callable=AsyncMock, return_value=""
            ):
                await tools._handle_create_cumulative_usage_alert(
                    client,
                    {"name": "Quarterly", "threshold": 5000, "period": "quarterly"},
                )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["periodDuration"] == "QUARTERLY"

    @pytest.mark.asyncio
    async def test_custom_metric_type(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            with patch.object(
                tools, "_post_alert_creation_prompting", new_callable=AsyncMock, return_value=""
            ):
                await tools._handle_create_cumulative_usage_alert(
                    client,
                    {"name": "Token Budget", "threshold": 10000, "metric": "TOKEN_COUNT"},
                )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["metricType"] == "TOKEN_COUNT"

    @pytest.mark.asyncio
    async def test_metric_type_fallback_to_metric_type_key(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            with patch.object(
                tools, "_post_alert_creation_prompting", new_callable=AsyncMock, return_value=""
            ):
                await tools._handle_create_cumulative_usage_alert(
                    client,
                    {"name": "Test", "threshold": 100, "metric_type": "ERROR_RATE"},
                )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["metricType"] == "ERROR_RATE"

    @pytest.mark.asyncio
    async def test_default_metric_type_is_total_cost(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            with patch.object(
                tools, "_post_alert_creation_prompting", new_callable=AsyncMock, return_value=""
            ):
                await tools._handle_create_cumulative_usage_alert(
                    client,
                    {"name": "Default Metric", "threshold": 100},
                )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["metricType"] == "TOTAL_COST"

    @pytest.mark.asyncio
    async def test_missing_name_returns_error(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            result = await tools._handle_create_cumulative_usage_alert(
                client,
                {"threshold": 1000},
            )
        assert isinstance(result[0], TextContent)
        assert "name" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_missing_threshold_returns_error(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            result = await tools._handle_create_cumulative_usage_alert(
                client,
                {"name": "Test Alert"},
            )
        assert isinstance(result[0], TextContent)
        assert "threshold" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_negative_threshold_returns_error(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            result = await tools._handle_create_cumulative_usage_alert(
                client,
                {"name": "Test", "threshold": -50},
            )
        assert isinstance(result[0], TextContent)
        assert "threshold" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_zero_threshold_returns_error(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            result = await tools._handle_create_cumulative_usage_alert(
                client,
                {"name": "Test", "threshold": 0},
            )
        assert isinstance(result[0], TextContent)
        # 0 is falsy, so it hits the "not threshold" check
        assert "threshold" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_non_numeric_threshold_returns_error(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            result = await tools._handle_create_cumulative_usage_alert(
                client,
                {"name": "Test", "threshold": "not-a-number"},
            )
        assert isinstance(result[0], TextContent)
        assert "threshold" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_invalid_period_returns_error(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            result = await tools._handle_create_cumulative_usage_alert(
                client,
                {"name": "Test", "threshold": 100, "period": "biweekly"},
            )
        assert isinstance(result[0], TextContent)
        assert "period" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_notification_validation_error_returns_message(self):
        tools, client = _make_tools_with_client()
        mock_err = ValidationError(message="No email found", field="email")
        with patch.object(
            tools, "_resolve_notification_config", side_effect=mock_err
        ):
            result = await tools._handle_create_cumulative_usage_alert(
                client,
                {"name": "Test", "threshold": 100},
            )
        assert isinstance(result[0], TextContent)
        assert "email" in result[0].text.lower() or "error" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_api_error_returns_resource_error(self):
        tools, client = _make_tools_with_client()
        tools.anomaly_manager.create_anomaly = AsyncMock(
            side_effect=RuntimeError("API connection failed")
        )
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            result = await tools._handle_create_cumulative_usage_alert(
                client,
                {"name": "Test", "threshold": 100},
            )
        assert isinstance(result[0], TextContent)
        assert "failed" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_period_case_insensitive(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            with patch.object(
                tools, "_post_alert_creation_prompting", new_callable=AsyncMock, return_value=""
            ):
                await tools._handle_create_cumulative_usage_alert(
                    client,
                    {"name": "Test", "threshold": 100, "period": "MONTHLY"},
                )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["periodDuration"] == "MONTHLY"

    @pytest.mark.asyncio
    async def test_slack_config_passed_through(self):
        tools, client = _make_tools_with_client()
        config = _notification_config(slack="slack-123")
        with patch.object(
            tools, "_resolve_notification_config", return_value=config
        ):
            with patch.object(
                tools, "_post_alert_creation_prompting", new_callable=AsyncMock, return_value=""
            ):
                await tools._handle_create_cumulative_usage_alert(
                    client,
                    {"name": "Test", "threshold": 100, "slack_config_id": "slack-123"},
                )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["slackConfigurations"] == ["slack-123"]

    @pytest.mark.asyncio
    async def test_post_creation_prompting_appended(self):
        tools, client = _make_tools_with_client()
        tools.anomaly_manager.create_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="Created!")]
        )
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            with patch.object(
                tools,
                "_post_alert_creation_prompting",
                new_callable=AsyncMock,
                return_value="\n\nSlack prompt message",
            ):
                result = await tools._handle_create_cumulative_usage_alert(
                    client,
                    {"name": "Test", "threshold": 100},
                )
        assert "Created!" in result[0].text
        assert "Slack prompt message" in result[0].text

    @pytest.mark.asyncio
    async def test_anomaly_data_fields_structure(self):
        """Verify all expected fields in the anomaly_data passed to create_anomaly."""
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            with patch.object(
                tools, "_post_alert_creation_prompting", new_callable=AsyncMock, return_value=""
            ):
                await tools._handle_create_cumulative_usage_alert(
                    client,
                    {"name": "Complete Alert", "threshold": 500, "period": "monthly"},
                )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["label"] == "Complete Alert"
        assert call_data["name"] == "Complete Alert"
        assert call_data["alertType"] == "CUMULATIVE_USAGE"
        assert call_data["operatorType"] == "GREATER_THAN"
        assert call_data["isPercentage"] is False
        assert call_data["enabled"] is True
        assert call_data["triggerAfterPersistsDuration"] == ""
        assert call_data["filters"] == []


# ===========================================================================
# _handle_create_threshold_alert
# ===========================================================================


class TestHandleCreateThresholdAlert:
    """Cover _handle_create_threshold_alert: validation, periods, persistence."""

    @pytest.mark.asyncio
    async def test_happy_path_five_minutes(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            result = await tools._handle_create_threshold_alert(
                client,
                {"name": "Spike Alert", "threshold": 100, "period_minutes": 5},
            )
        assert isinstance(result[0], TextContent)
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["alertType"] == "THRESHOLD"
        assert call_data["periodDuration"] == "FIVE_MINUTES"

    @pytest.mark.asyncio
    async def test_one_minute_period(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            await tools._handle_create_threshold_alert(
                client,
                {"name": "Fast Alert", "threshold": 50, "period_minutes": 1},
            )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["periodDuration"] == "ONE_MINUTE"

    @pytest.mark.asyncio
    async def test_ten_minute_period(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            await tools._handle_create_threshold_alert(
                client,
                {"name": "Ten Min", "threshold": 50, "period_minutes": 10},
            )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["periodDuration"] == "TEN_MINUTES"

    @pytest.mark.asyncio
    async def test_fifteen_minute_period(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            await tools._handle_create_threshold_alert(
                client,
                {"name": "15min", "threshold": 50, "period_minutes": 15},
            )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["periodDuration"] == "FIFTEEN_MINUTES"

    @pytest.mark.asyncio
    async def test_thirty_minute_period(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            await tools._handle_create_threshold_alert(
                client,
                {"name": "30min", "threshold": 50, "period_minutes": 30},
            )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["periodDuration"] == "THIRTY_MINUTES"

    @pytest.mark.asyncio
    async def test_one_hour_period(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            await tools._handle_create_threshold_alert(
                client,
                {"name": "Hourly", "threshold": 50, "period_minutes": 60},
            )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["periodDuration"] == "ONE_HOUR"

    @pytest.mark.asyncio
    async def test_missing_name_raises(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            with pytest.raises(Exception):
                await tools._handle_create_threshold_alert(
                    client, {"threshold": 100, "period_minutes": 5}
                )

    @pytest.mark.asyncio
    async def test_missing_threshold_raises(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            with pytest.raises(Exception):
                await tools._handle_create_threshold_alert(
                    client, {"name": "Test", "period_minutes": 5}
                )

    @pytest.mark.asyncio
    async def test_negative_threshold_raises(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            with pytest.raises(Exception):
                await tools._handle_create_threshold_alert(
                    client, {"name": "Test", "threshold": -10, "period_minutes": 5}
                )

    @pytest.mark.asyncio
    async def test_non_numeric_threshold_raises(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            with pytest.raises(Exception):
                await tools._handle_create_threshold_alert(
                    client, {"name": "Test", "threshold": "abc", "period_minutes": 5}
                )

    @pytest.mark.asyncio
    async def test_invalid_period_minutes_raises(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            with pytest.raises(Exception):
                await tools._handle_create_threshold_alert(
                    client, {"name": "Test", "threshold": 100, "period_minutes": 99}
                )

    @pytest.mark.asyncio
    async def test_valid_trigger_duration(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            await tools._handle_create_threshold_alert(
                client,
                {
                    "name": "Persist",
                    "threshold": 100,
                    "period_minutes": 5,
                    "triggerAfterPersistsDuration": "FIFTEEN_MINUTES",
                },
            )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["triggerAfterPersistsDuration"] == "FIFTEEN_MINUTES"
        assert "persistence" in call_data["description"]

    @pytest.mark.asyncio
    async def test_invalid_trigger_duration_raises(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            with pytest.raises(Exception):
                await tools._handle_create_threshold_alert(
                    client,
                    {
                        "name": "Test",
                        "threshold": 100,
                        "period_minutes": 5,
                        "triggerAfterPersistsDuration": "INVALID",
                    },
                )

    @pytest.mark.asyncio
    async def test_custom_metric_type(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            await tools._handle_create_threshold_alert(
                client,
                {"name": "Token Alert", "threshold": 5000, "metric": "TOKEN_COUNT"},
            )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["metricType"] == "TOKEN_COUNT"

    @pytest.mark.asyncio
    async def test_notification_validation_error_returns_message(self):
        tools, client = _make_tools_with_client()
        mock_err = ValidationError(message="No email", field="email")
        with patch.object(
            tools, "_resolve_notification_config", side_effect=mock_err
        ):
            result = await tools._handle_create_threshold_alert(
                client,
                {"name": "Test", "threshold": 100},
            )
        assert isinstance(result[0], TextContent)
        assert "No email" in result[0].text or "error" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_api_error_raises_tool_error(self):
        tools, client = _make_tools_with_client()
        tools.anomaly_manager.create_anomaly = AsyncMock(
            side_effect=RuntimeError("Connection timeout")
        )
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            with pytest.raises(ToolError):
                await tools._handle_create_threshold_alert(
                    client,
                    {"name": "Test", "threshold": 100, "period_minutes": 5},
                )

    @pytest.mark.asyncio
    async def test_tool_error_re_raised(self):
        tools, client = _make_tools_with_client()
        tools.anomaly_manager.create_anomaly = AsyncMock(
            side_effect=ToolError(message="Specific tool error")
        )
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            with pytest.raises(ToolError) as exc_info:
                await tools._handle_create_threshold_alert(
                    client,
                    {"name": "Test", "threshold": 100, "period_minutes": 5},
                )
            assert "Specific tool error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_anomaly_data_structure(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            await tools._handle_create_threshold_alert(
                client,
                {"name": "Structure Test", "threshold": 200, "period_minutes": 10},
            )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["label"] == "Structure Test"
        assert call_data["alertType"] == "THRESHOLD"
        assert call_data["operatorType"] == "GREATER_THAN"
        assert call_data["isPercentage"] is False
        assert call_data["enabled"] is True
        assert call_data["filters"] == []


# ===========================================================================
# _handle_create_from_text
# ===========================================================================


class TestHandleCreateFromText:
    """Cover _handle_create_from_text: semantic parsing, fallback, errors."""

    @pytest.mark.asyncio
    async def test_missing_text_raises(self):
        tools, client = _make_tools_with_client()
        with pytest.raises(Exception):
            await tools._handle_create_from_text(client, {})

    @pytest.mark.asyncio
    async def test_empty_text_raises(self):
        tools, client = _make_tools_with_client()
        with pytest.raises(Exception):
            await tools._handle_create_from_text(client, {"text": ""})

    @pytest.mark.asyncio
    async def test_semantic_processor_used_first(self):
        tools, client = _make_tools_with_client()
        parsed = {"detection_rules": [{"type": "threshold"}], "name": "Parsed Alert"}
        tools.semantic_processor.parse_alert_request = MagicMock(return_value=parsed)
        await tools._handle_create_from_text(
            client, {"text": "alert me when cost exceeds 100"}
        )
        tools.semantic_processor.parse_alert_request.assert_called_once()
        # Should pass parsed data to create_anomaly
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["name"] == "Parsed Alert"

    @pytest.mark.asyncio
    async def test_falls_back_to_simple_parse_when_no_rules(self):
        tools, client = _make_tools_with_client()
        # semantic_processor returns no detection_rules
        tools.semantic_processor.parse_alert_request = MagicMock(return_value={})
        with patch.object(
            tools,
            "_simple_parse_alert_text",
            return_value={"name": "Fallback Alert", "alertType": "THRESHOLD"},
        ) as mock_parse:
            with patch.object(
                tools, "_resolve_notification_config", return_value=_notification_config()
            ):
                await tools._handle_create_from_text(
                    client, {"text": "alert when stuff happens"}
                )
        mock_parse.assert_called_once()

    @pytest.mark.asyncio
    async def test_falls_back_when_parsed_data_none(self):
        tools, client = _make_tools_with_client()
        tools.semantic_processor.parse_alert_request = MagicMock(return_value=None)
        with patch.object(
            tools,
            "_simple_parse_alert_text",
            return_value={"name": "Fallback", "alertType": "THRESHOLD"},
        ) as mock_parse:
            await tools._handle_create_from_text(
                client, {"text": "some alert text"}
            )
        mock_parse.assert_called_once()

    @pytest.mark.asyncio
    async def test_api_error_raises_tool_error(self):
        tools, client = _make_tools_with_client()
        tools.semantic_processor.parse_alert_request = MagicMock(
            return_value={"detection_rules": [{}]}
        )
        tools.anomaly_manager.create_anomaly = AsyncMock(
            side_effect=RuntimeError("API down")
        )
        with pytest.raises(ToolError):
            await tools._handle_create_from_text(
                client, {"text": "alert me when cost exceeds 100"}
            )

    @pytest.mark.asyncio
    async def test_tool_error_re_raised(self):
        tools, client = _make_tools_with_client()
        tools.semantic_processor.parse_alert_request = MagicMock(
            return_value={"detection_rules": [{}]}
        )
        tools.anomaly_manager.create_anomaly = AsyncMock(
            side_effect=ToolError(message="Preserved error")
        )
        with pytest.raises(ToolError) as exc_info:
            await tools._handle_create_from_text(
                client, {"text": "alert me when cost exceeds 100"}
            )
        assert "Preserved error" in str(exc_info.value)


# ===========================================================================
# _simple_parse_alert_text
# ===========================================================================


class TestSimpleParseAlertText:
    """Cover _simple_parse_alert_text: keyword detection, metric, threshold extraction."""

    def _parse(self, text: str) -> Dict[str, Any]:
        tools = AlertManagement()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            return tools._simple_parse_alert_text(text)

    # --- Alert type detection ---

    def test_spike_keyword_yields_threshold(self):
        result = self._parse("alert me on spike above 500")
        assert result["alertType"] == "THRESHOLD"

    def test_exceeds_keyword_yields_threshold(self):
        result = self._parse("notify when cost exceeds 200")
        assert result["alertType"] == "THRESHOLD"

    def test_monthly_keyword_yields_cumulative(self):
        result = self._parse("monthly budget alert at 1000")
        assert result["alertType"] == "CUMULATIVE_USAGE"

    def test_budget_keyword_yields_cumulative(self):
        result = self._parse("set a budget alert at $5000")
        assert result["alertType"] == "CUMULATIVE_USAGE"

    def test_daily_keyword_yields_cumulative_daily(self):
        result = self._parse("daily budget of 100")
        assert result["alertType"] == "CUMULATIVE_USAGE"
        assert result["periodDuration"] == "DAILY"

    def test_weekly_tracking_period(self):
        result = self._parse("weekly usage tracking at 500")
        assert result["periodDuration"] == "WEEKLY"

    def test_quarterly_tracking_period(self):
        result = self._parse("quarterly budget alert at 10000")
        assert result["periodDuration"] == "QUARTERLY"

    def test_default_cumulative_period_is_monthly(self):
        result = self._parse("cumulative usage alert at 1000")
        assert result["periodDuration"] == "MONTHLY"

    def test_unclear_text_defaults_to_threshold(self):
        result = self._parse("something weird 42")
        assert result["alertType"] == "THRESHOLD"
        assert result["periodDuration"] == "FIVE_MINUTES"

    # --- Metric type detection ---

    def test_token_keyword_maps_to_token_count(self):
        result = self._parse("alert when tokens exceed 10000")
        assert result["metricType"] == "TOKEN_COUNT"

    def test_error_rate_keyword(self):
        result = self._parse("alert on error rate above 5")
        assert result["metricType"] == "ERROR_RATE"

    def test_cost_keyword_maps_to_total_cost(self):
        result = self._parse("alert when cost goes above 1000")
        assert result["metricType"] == "TOTAL_COST"

    def test_spending_keyword_maps_to_total_cost(self):
        result = self._parse("alert on spending above 500")
        assert result["metricType"] == "TOTAL_COST"

    def test_errors_keyword_maps_to_error_count(self):
        result = self._parse("alert when errors exceed 100")
        assert result["metricType"] == "ERROR_COUNT"

    def test_requests_per_minute_keyword(self):
        result = self._parse("alert when requests per minute exceed 1000")
        assert result["metricType"] == "REQUESTS_PER_MINUTE"

    def test_default_metric_is_total_cost(self):
        result = self._parse("alert at 500")
        assert result["metricType"] == "TOTAL_COST"

    # --- Threshold extraction ---

    def test_extracts_integer_threshold(self):
        result = self._parse("alert at 500")
        assert result["threshold"] == 500.0

    def test_extracts_decimal_threshold(self):
        result = self._parse("alert at 99.5")
        assert result["threshold"] == 99.5

    def test_extracts_threshold_with_dollar_sign(self):
        result = self._parse("budget alert at $1000")
        assert result["threshold"] == 1000.0

    def test_extracts_threshold_with_commas(self):
        result = self._parse("alert at $10,000")
        assert result["threshold"] == 10000.0

    def test_default_threshold_when_no_number(self):
        result = self._parse("alert on high usage")
        assert result["threshold"] == 100.0

    # --- Name generation ---

    def test_short_text_name(self):
        result = self._parse("budget alert")
        assert result["name"] == "Auto-generated Alert: budget alert"

    def test_long_text_truncated(self):
        long_text = "a" * 60
        result = self._parse(long_text)
        assert result["name"].endswith("...")
        assert len(result["name"]) < 80

    # --- Structure ---

    def test_all_required_fields_present(self):
        result = self._parse("monthly budget at 1000")
        required = [
            "label", "name", "alertType", "metricType", "operatorType",
            "threshold", "isPercentage", "description", "enabled",
            "notificationAddresses", "slackConfigurations",
            "triggerAfterPersistsDuration", "filters", "periodDuration",
        ]
        for field in required:
            assert field in result, f"Missing field: {field}"

    def test_notification_fallback_when_config_raises(self):
        """When _resolve_notification_config raises, fallback email logic runs."""
        tools = AlertManagement()
        with patch.object(
            tools,
            "_resolve_notification_config",
            side_effect=ValidationError(message="No email", field="email"),
        ):
            with patch.dict("os.environ", {"REVENIUM_DEFAULT_EMAIL": "fallback@test.com"}):
                result = tools._simple_parse_alert_text("budget alert at 500")
        assert result["notificationAddresses"] == ["fallback@test.com"]

    def test_notification_fallback_skips_dummy_email(self):
        tools = AlertManagement()
        mock_config = MagicMock()
        mock_config.default_email = "discovered@test.com"
        with patch.object(
            tools,
            "_resolve_notification_config",
            side_effect=ValidationError(message="No email", field="email"),
        ):
            with patch.dict("os.environ", {"REVENIUM_DEFAULT_EMAIL": "dummy@email.com"}):
                with patch(
                    "src.revenium_mcp_server.config_store.get_discovered_config_sync",
                    return_value=mock_config,
                ):
                    result = tools._simple_parse_alert_text("alert at 100")
        assert result["notificationAddresses"] == ["discovered@test.com"]

    def test_notification_fallback_to_admin_default(self):
        tools = AlertManagement()
        mock_config = MagicMock()
        mock_config.default_email = None
        with patch.object(
            tools,
            "_resolve_notification_config",
            side_effect=ValidationError(message="No email", field="email"),
        ):
            with patch.dict("os.environ", {}, clear=True):
                with patch(
                    "src.revenium_mcp_server.config_store.get_discovered_config_sync",
                    return_value=mock_config,
                ):
                    result = tools._simple_parse_alert_text("alert at 100")
        assert result["notificationAddresses"] == ["admin@example.com"]


# ===========================================================================
# _handle_create_simple
# ===========================================================================


class TestHandleCreateSimple:
    """Cover _handle_create_simple: defaults, custom params, errors."""

    @pytest.mark.asyncio
    async def test_happy_path_with_defaults(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            result = await tools._handle_create_simple(client, {"email": "a@b.com"})
        assert isinstance(result[0], TextContent)
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["name"] == "Simple Alert"
        assert call_data["metricType"] == "TOTAL_COST"
        assert call_data["threshold"] == 100.0
        assert call_data["periodDuration"] == "FIVE_MINUTES"
        assert call_data["alertType"] == "THRESHOLD"

    @pytest.mark.asyncio
    async def test_custom_name(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            await tools._handle_create_simple(
                client, {"name": "Custom Name", "email": "a@b.com"}
            )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["name"] == "Custom Name"

    @pytest.mark.asyncio
    async def test_custom_metric_and_threshold(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            await tools._handle_create_simple(
                client,
                {"metric": "ERROR_RATE", "threshold": 5, "email": "a@b.com"},
            )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["metricType"] == "ERROR_RATE"
        assert call_data["threshold"] == 5.0

    @pytest.mark.asyncio
    async def test_notification_error_returns_message(self):
        tools, client = _make_tools_with_client()
        mock_err = ValidationError(message="No email", field="email")
        with patch.object(
            tools, "_resolve_notification_config", side_effect=mock_err
        ):
            result = await tools._handle_create_simple(client, {})
        assert isinstance(result[0], TextContent)
        assert "No email" in result[0].text or "error" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_api_error_raises_tool_error(self):
        tools, client = _make_tools_with_client()
        tools.anomaly_manager.create_anomaly = AsyncMock(
            side_effect=RuntimeError("Connection failed")
        )
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            with pytest.raises(ToolError):
                await tools._handle_create_simple(client, {"email": "a@b.com"})

    @pytest.mark.asyncio
    async def test_tool_error_re_raised(self):
        tools, client = _make_tools_with_client()
        tools.anomaly_manager.create_anomaly = AsyncMock(
            side_effect=ToolError(message="Preserved")
        )
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            with pytest.raises(ToolError) as exc_info:
                await tools._handle_create_simple(client, {"email": "a@b.com"})
            assert "Preserved" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_slack_config_id_passed(self):
        tools, client = _make_tools_with_client()
        config = _notification_config(slack="slack-xyz")
        with patch.object(
            tools, "_resolve_notification_config", return_value=config
        ):
            await tools._handle_create_simple(
                client, {"email": "a@b.com", "slack_config_id": "slack-xyz"}
            )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert call_data["slackConfigurations"] == ["slack-xyz"]

    @pytest.mark.asyncio
    async def test_description_contains_metric(self):
        tools, client = _make_tools_with_client()
        with patch.object(
            tools, "_resolve_notification_config", return_value=_notification_config()
        ):
            await tools._handle_create_simple(
                client, {"metric": "TOKEN_COUNT", "email": "a@b.com"}
            )
        call_data = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert "TOKEN_COUNT" in call_data["description"]
