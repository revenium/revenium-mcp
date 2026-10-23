"""Extended unit tests for AlertManagement — deep CRUD coverage.

Covers handle_action routing for create, update, delete, list, enable/disable,
bulk operations, and specialized alert creation actions.
Mocks self.get_client() to avoid real API calls.
"""

import ast
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp.types import TextContent

from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from src.revenium_mcp_server.common.error_handling import ToolError


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_client():
    client = MagicMock()
    client.team_id = "team_test"
    client.get_anomaly_by_id = AsyncMock(
        return_value={"id": "anom_1", "name": "Test Alert", "enabled": True}
    )
    client.update_anomaly = AsyncMock(
        return_value={"id": "anom_1", "name": "Test Alert", "enabled": False}
    )
    return client


def _make_alert_with_client():
    """Return (AlertManagement, mock_client) with get_client patched."""
    tools = AlertManagement()
    client = _make_client()
    tools.get_client = AsyncMock(return_value=client)
    return tools, client


# ===========================================================================
# handle_action — list routing
# ===========================================================================


class TestHandleActionList:
    """Cover list action routing for anomalies and alerts."""

    @pytest.mark.asyncio
    async def test_list_anomalies(self):
        tools, client = _make_alert_with_client()
        tools.anomaly_manager.list_anomalies = AsyncMock(
            return_value=[TextContent(type="text", text="Anomalies list")]
        )
        result = await tools.handle_action("list", {"resource_type": "anomalies"})
        assert result[0].text == "Anomalies list"
        tools.anomaly_manager.list_anomalies.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_alerts(self):
        tools, client = _make_alert_with_client()
        tools.alert_manager.list_alerts = AsyncMock(
            return_value=[TextContent(type="text", text="Alerts list")]
        )
        result = await tools.handle_action("list", {"resource_type": "alerts"})
        assert result[0].text == "Alerts list"
        tools.alert_manager.list_alerts.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_invalid_resource_type_raises(self):
        tools, _ = _make_alert_with_client()
        with pytest.raises(Exception) as exc_info:
            await tools.handle_action("list", {"resource_type": "invalid_type"})
        assert "resource_type" in str(exc_info.value).lower() or "invalid" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_list_without_resource_type_uses_semantic_detection(self):
        """When resource_type is not specified, semantic detection kicks in."""
        tools, _ = _make_alert_with_client()
        tools.anomaly_manager.list_anomalies = AsyncMock(
            return_value=[TextContent(type="text", text="Detected anomalies")]
        )
        # Default semantic detection should route to anomalies
        result = await tools.handle_action("list", {})
        assert result[0].text == "Detected anomalies"


# ===========================================================================
# handle_action — get routing
# ===========================================================================


class TestHandleActionGet:
    """Cover get action routing."""

    @pytest.mark.asyncio
    async def test_get_anomaly(self):
        tools, client = _make_alert_with_client()
        tools.anomaly_manager.get_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="Anomaly details")]
        )
        result = await tools.handle_action("get", {"resource_type": "anomalies", "anomaly_id": "anom_1"})
        assert result[0].text == "Anomaly details"

    @pytest.mark.asyncio
    async def test_get_anomaly_missing_id_returns_error(self):
        tools, _ = _make_alert_with_client()
        with pytest.raises(ToolError) as exc_info:
            await tools.handle_action("get", {"resource_type": "anomalies"})
        assert "anomaly_id" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_get_alert_by_id(self):
        tools, client = _make_alert_with_client()
        tools.alert_manager.get_alert = AsyncMock(
            return_value=[TextContent(type="text", text="Alert details")]
        )
        result = await tools.handle_action("get", {"resource_type": "alerts", "alert_id": "alert_1"})
        assert result[0].text == "Alert details"

    @pytest.mark.asyncio
    async def test_get_invalid_resource_type_raises(self):
        tools, _ = _make_alert_with_client()
        with pytest.raises(Exception):
            await tools.handle_action("get", {"resource_type": "invalid"})


# ===========================================================================
# handle_action — create routing
# ===========================================================================


@pytest.mark.usefixtures("alert_owner_email")
class TestHandleActionCreate:
    """Cover create action for anomalies."""

    @pytest.mark.asyncio
    async def test_create_anomaly_delegates(self):
        tools, _ = _make_alert_with_client()
        tools.anomaly_manager.create_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="Anomaly created")]
        )
        result = await tools.handle_action("create", {
            "resource_type": "anomalies",
            "anomaly_data": {
                "name": "New Alert",
                "metricType": "TOTAL_COST",
                "threshold": 100,
                "alertType": "THRESHOLD",
                "operatorType": "GREATER_THAN",
            },
        })
        assert result[0].text == "Anomaly created"

    @pytest.mark.asyncio
    async def test_create_missing_anomaly_data_returns_error(self):
        """BACK-2937: the refusal raises so the envelope carries isError."""
        tools, _ = _make_alert_with_client()
        with pytest.raises(ToolError) as exc_info:
            await tools.handle_action("create", {"resource_type": "anomalies"})
        assert "anomaly_data" in exc_info.value.message.lower()
        assert "MISSING_PARAMETER" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_create_dry_run_valid(self):
        tools, _ = _make_alert_with_client()
        result = await tools.handle_action("create", {
            "resource_type": "anomalies",
            "dry_run": True,
            "anomaly_data": {
                "name": "Dry Run Alert",
                "alertType": "THRESHOLD",
                "metricType": "TOTAL_COST",
                "operatorType": "GREATER_THAN",
                "threshold": 100,
            },
        })
        text = result[0].text
        assert "DRY RUN" in text

    @pytest.mark.asyncio
    async def test_create_non_anomaly_resource_raises(self):
        tools, _ = _make_alert_with_client()
        with pytest.raises(ToolError) as exc_info:
            await tools.handle_action("create", {"resource_type": "alerts", "anomaly_data": {}})
        assert "cannot create" in str(exc_info.value).lower()


# ===========================================================================
# handle_action — update routing
# ===========================================================================


class TestHandleActionUpdate:
    """Cover update action for anomalies."""

    @pytest.mark.asyncio
    async def test_update_anomaly_with_data(self):
        tools, _ = _make_alert_with_client()
        tools.anomaly_manager.update_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="Updated")]
        )
        result = await tools.handle_action("update", {
            "resource_type": "anomalies",
            "anomaly_id": "anom_1",
            "anomaly_data": {"threshold": 200},
        })
        assert result[0].text == "Updated"

    @pytest.mark.asyncio
    async def test_update_dry_run_valid(self):
        tools, _ = _make_alert_with_client()
        result = await tools.handle_action("update", {
            "resource_type": "anomalies",
            "dry_run": True,
            "anomaly_id": "anom_1",
            "anomaly_data": {"threshold": 200},
        })
        text = result[0].text
        assert "DRY RUN" in text

    @pytest.mark.asyncio
    async def test_update_non_anomaly_raises(self):
        tools, _ = _make_alert_with_client()
        with pytest.raises(ToolError):
            await tools.handle_action("update", {
                "resource_type": "alerts",
                "anomaly_id": "anom_1",
                "anomaly_data": {},
            })


# ===========================================================================
# handle_action — delete routing
# ===========================================================================


class TestHandleActionDelete:
    """Cover delete action."""

    @pytest.mark.asyncio
    async def test_delete_anomaly(self):
        tools, _ = _make_alert_with_client()
        tools.anomaly_manager.delete_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="Deleted")]
        )
        result = await tools.handle_action("delete", {
            "resource_type": "anomalies",
            "anomaly_id": "anom_1",
        })
        assert result[0].text == "Deleted"

    @pytest.mark.asyncio
    async def test_delete_missing_id_returns_error(self):
        tools, _ = _make_alert_with_client()
        with pytest.raises(ToolError) as exc_info:
            await tools.handle_action("delete", {"resource_type": "anomalies"})
        assert "anomaly_id" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_delete_non_anomaly_raises(self):
        tools, _ = _make_alert_with_client()
        with pytest.raises(ToolError):
            await tools.handle_action("delete", {"resource_type": "alerts", "anomaly_id": "a1"})


# ===========================================================================
# handle_action — clear_all routing
# ===========================================================================


class TestHandleActionClearAll:
    """Cover clear_all action."""

    @pytest.mark.asyncio
    async def test_clear_all_without_confirm_returns_warning(self):
        tools, _ = _make_alert_with_client()
        result = await tools.handle_action("clear_all", {"resource_type": "anomalies"})
        text = result[0].text
        assert "Confirmation Required" in text or "confirm" in text.lower()

    @pytest.mark.asyncio
    async def test_clear_all_with_confirm_delegates(self):
        tools, _ = _make_alert_with_client()
        tools.anomaly_manager.clear_all_anomalies = AsyncMock(
            return_value=[TextContent(type="text", text="All cleared")]
        )
        result = await tools.handle_action("clear_all", {
            "resource_type": "anomalies", "confirm": True,
        })
        assert result[0].text == "All cleared"

    @pytest.mark.asyncio
    async def test_clear_all_non_anomaly_raises(self):
        tools, _ = _make_alert_with_client()
        with pytest.raises(ToolError):
            await tools.handle_action("clear_all", {"resource_type": "alerts"})


# ===========================================================================
# handle_action: get_metrics refusal
# ===========================================================================


class TestHandleActionGetMetrics:
    """get_metrics is refused, never dispatched."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("anomaly_id", ["anom_1", "no_such_alert"])
    async def test_get_metrics_is_refused_and_names_the_alternatives(self, anomaly_id):
        """The platform has no per-alert metrics read (BACK-4703)."""
        tools, client = _make_alert_with_client()
        client.get = AsyncMock(return_value={"value": 1})

        with pytest.raises(ToolError) as exc_info:
            await tools.handle_action("get_metrics", {"anomaly_id": anomaly_id})

        message = str(exc_info.value)
        assert exc_info.value.field == "action"
        assert "get_budget_progress" in message
        assert "get(" in message
        client.get.assert_not_awaited()
        client.get_anomaly_by_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_metrics_is_not_advertised(self):
        tools, _ = _make_alert_with_client()

        assert "get_metrics" not in await tools._get_supported_actions()
        for action in ("get_capabilities", "get_examples", "get_agent_summary"):
            result = await tools.handle_action(action, {})
            text = "\n".join(item.text for item in result if hasattr(item, "text"))
            assert "get_metrics" not in text, action


# ===========================================================================
# handle_action — query routing
# ===========================================================================


class TestHandleActionQuery:
    """Cover query action."""

    @pytest.mark.asyncio
    async def test_query_alerts(self):
        tools, _ = _make_alert_with_client()
        tools.alert_manager.list_alerts = AsyncMock(
            return_value=[TextContent(type="text", text="Query results")]
        )
        result = await tools.handle_action("query", {
            "resource_type": "alerts", "query": "high cost",
        })
        assert result[0].text == "Query results"

    @pytest.mark.asyncio
    async def test_query_anomalies(self):
        tools, _ = _make_alert_with_client()
        tools.anomaly_manager.list_anomalies = AsyncMock(
            return_value=[TextContent(type="text", text="Query anomalies")]
        )
        result = await tools.handle_action("query", {
            "resource_type": "anomalies", "filters": {"query": "budget"},
        })
        assert result[0].text == "Query anomalies"

    @pytest.mark.asyncio
    async def test_query_invalid_resource_type_raises(self):
        tools, _ = _make_alert_with_client()
        with pytest.raises(Exception):
            await tools.handle_action("query", {"resource_type": "invalid"})


# ===========================================================================
# handle_action — validate routing
# ===========================================================================


@pytest.mark.usefixtures("alert_owner_email")
class TestHandleActionValidate:
    """Cover validate action."""

    @pytest.mark.asyncio
    async def test_validate_with_data_runs_the_create_checks(self):
        """Validate refuses what create refuses: this alert has no alertType."""
        tools, client = _make_alert_with_client()
        alert = {"name": "Test", "metricType": "TOTAL_COST"}
        with pytest.raises(ToolError) as validated:
            await tools.handle_action("validate", {"anomaly_data": dict(alert)})
        with pytest.raises(ToolError) as created:
            await tools.handle_action("create", {"anomaly_data": dict(alert)})
        assert validated.value.message == created.value.message
        assert "alertType" in validated.value.message
        assert "ucm" not in validated.value.message.lower()
        client.create_anomaly.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_missing_data_raises_a_flagged_error(self):
        tools, _ = _make_alert_with_client()
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action("validate", {})
        assert refusal.value.field == "anomaly_data"


# ===========================================================================
# handle_action — enable/disable routing
# ===========================================================================


class TestHandleActionEnableDisable:
    """Cover enable and disable actions."""

    @pytest.mark.asyncio
    async def test_enable_anomaly(self):
        tools, client = _make_alert_with_client()
        client.get_anomaly_by_id.return_value = {"id": "anom_1", "name": "Alert", "enabled": False}
        client.update_anomaly.return_value = {"id": "anom_1", "name": "Alert", "enabled": True}
        result = await tools.handle_action("enable", {"anomaly_id": "anom_1"})
        text = result[0].text
        assert "enabled" in text.lower()
        # Verify the update was actually called with enabled=True
        client.update_anomaly.assert_called_once()
        update_payload = client.update_anomaly.call_args[0][1]
        assert update_payload["enabled"] is True

    @pytest.mark.asyncio
    async def test_enable_missing_id_raises(self):
        tools, _ = _make_alert_with_client()
        with pytest.raises(Exception):
            await tools.handle_action("enable", {})

    @pytest.mark.asyncio
    async def test_disable_anomaly(self):
        tools, client = _make_alert_with_client()
        client.get_anomaly_by_id.return_value = {"id": "anom_1", "name": "Alert", "enabled": True}
        client.update_anomaly.return_value = {"id": "anom_1", "name": "Alert", "enabled": False}
        result = await tools.handle_action("disable", {"anomaly_id": "anom_1"})
        text = result[0].text
        assert "Disabled" in text or "disabled" in text.lower()

    @pytest.mark.asyncio
    async def test_disable_missing_id_raises(self):
        tools, _ = _make_alert_with_client()
        with pytest.raises(Exception):
            await tools.handle_action("disable", {})

    @pytest.mark.asyncio
    async def test_enable_api_error_raises_tool_error(self):
        tools, client = _make_alert_with_client()
        client.get_anomaly_by_id.side_effect = RuntimeError("API down")
        with pytest.raises(ToolError):
            await tools.handle_action("enable", {"anomaly_id": "anom_1"})

    @pytest.mark.asyncio
    async def test_disable_api_error_raises_tool_error(self):
        tools, client = _make_alert_with_client()
        client.get_anomaly_by_id.side_effect = RuntimeError("API down")
        with pytest.raises(ToolError):
            await tools.handle_action("disable", {"anomaly_id": "anom_1"})


# ===========================================================================
# handle_action — enable/disable multiple
# ===========================================================================


class TestHandleActionBulkEnableDisable:
    """Cover enable_multiple and disable_multiple actions."""

    @pytest.mark.asyncio
    async def test_enable_multiple_missing_ids_raises(self):
        tools, _ = _make_alert_with_client()
        with pytest.raises(Exception):
            await tools.handle_action("enable_multiple", {})

    @pytest.mark.asyncio
    async def test_disable_multiple_missing_ids_raises(self):
        tools, _ = _make_alert_with_client()
        with pytest.raises(Exception):
            await tools.handle_action("disable_multiple", {})

    @pytest.mark.asyncio
    async def test_enable_multiple_with_ids(self):
        tools, client = _make_alert_with_client()
        client.get_anomaly_by_id.return_value = {"id": "a1", "name": "Alert", "enabled": False}
        client.update_anomaly.return_value = {"id": "a1", "name": "Alert", "enabled": True}
        result = await tools.handle_action("enable_multiple", {"anomaly_ids": ["a1"]})
        # Bulk enable response must show results summary
        assert "Bulk Enable" in result[0].text or "Successful" in result[0].text

    @pytest.mark.asyncio
    async def test_disable_multiple_with_ids(self):
        tools, client = _make_alert_with_client()
        client.get_anomaly_by_id.return_value = {"id": "a1", "name": "Alert", "enabled": True}
        client.update_anomaly.return_value = {"id": "a1", "name": "Alert", "enabled": False}
        result = await tools.handle_action("disable_multiple", {"anomaly_ids": ["a1"]})
        # Bulk disable response must show results summary
        assert "Bulk Disable" in result[0].text or "Successful" in result[0].text


# ===========================================================================
# handle_action — create_threshold_alert
# ===========================================================================


class TestHandleActionCreateThresholdAlert:
    """Cover create_threshold_alert action."""

    @pytest.mark.asyncio
    async def test_create_threshold_alert_valid(self):
        tools, _ = _make_alert_with_client()
        tools.anomaly_manager.create_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="Threshold alert created")]
        )
        with patch.object(tools, "_resolve_notification_config", return_value={
            "notificationAddresses": ["test@example.com"],
            "slackConfigurations": [],
        }):
            result = await tools.handle_action("create_threshold_alert", {
                "name": "Cost Spike",
                "threshold": 100,
                "period_minutes": 15,
                "email": "test@example.com",
            })
        assert result[0].text == "Threshold alert created"

    @pytest.mark.asyncio
    async def test_create_threshold_alert_missing_name_raises(self):
        tools, _ = _make_alert_with_client()
        with patch.object(tools, "_resolve_notification_config", return_value={
            "notificationAddresses": ["a@b.com"],
            "slackConfigurations": [],
        }):
            with pytest.raises(Exception):
                await tools.handle_action("create_threshold_alert", {
                    "threshold": 100, "period_minutes": 15, "email": "a@b.com",
                })

    @pytest.mark.asyncio
    async def test_create_threshold_alert_missing_threshold_raises(self):
        tools, _ = _make_alert_with_client()
        with patch.object(tools, "_resolve_notification_config", return_value={
            "notificationAddresses": ["a@b.com"],
            "slackConfigurations": [],
        }):
            with pytest.raises(Exception):
                await tools.handle_action("create_threshold_alert", {
                    "name": "Test", "period_minutes": 15, "email": "a@b.com",
                })

    @pytest.mark.asyncio
    async def test_create_threshold_alert_invalid_period_raises(self):
        tools, _ = _make_alert_with_client()
        with patch.object(tools, "_resolve_notification_config", return_value={
            "notificationAddresses": ["a@b.com"],
            "slackConfigurations": [],
        }):
            with pytest.raises(Exception):
                await tools.handle_action("create_threshold_alert", {
                    "name": "Test", "threshold": 100, "period_minutes": 99, "email": "a@b.com",
                })

    @pytest.mark.asyncio
    async def test_create_threshold_alert_with_trigger_duration(self):
        tools, _ = _make_alert_with_client()
        tools.anomaly_manager.create_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="Created with persistence")]
        )
        with patch.object(tools, "_resolve_notification_config", return_value={
            "notificationAddresses": ["a@b.com"],
            "slackConfigurations": [],
        }):
            result = await tools.handle_action("create_threshold_alert", {
                "name": "Persist Alert",
                "threshold": 100,
                "period_minutes": 15,
                "email": "a@b.com",
                "triggerAfterPersistsDuration": "FIFTEEN_MINUTES",
            })
        assert result[0].text == "Created with persistence"

    @pytest.mark.asyncio
    async def test_create_threshold_alert_invalid_trigger_duration_raises(self):
        tools, _ = _make_alert_with_client()
        with patch.object(tools, "_resolve_notification_config", return_value={
            "notificationAddresses": ["a@b.com"],
            "slackConfigurations": [],
        }):
            with pytest.raises(Exception):
                await tools.handle_action("create_threshold_alert", {
                    "name": "Test",
                    "threshold": 100,
                    "period_minutes": 15,
                    "email": "a@b.com",
                    "triggerAfterPersistsDuration": "INVALID_DURATION",
                })

    @pytest.mark.asyncio
    async def test_create_threshold_alert_with_custom_metric(self):
        tools, _ = _make_alert_with_client()
        tools.anomaly_manager.create_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="Created")]
        )
        with patch.object(tools, "_resolve_notification_config", return_value={
            "notificationAddresses": ["a@b.com"],
            "slackConfigurations": [],
        }):
            result = await tools.handle_action("create_threshold_alert", {
                "name": "Token Alert",
                "threshold": 5000,
                "period_minutes": 15,
                "email": "a@b.com",
                "metric": "TOKEN_COUNT",
            })
        assert result[0].text == "Created"


# ===========================================================================
# handle_action — create_simple
# ===========================================================================


class TestHandleActionCreateSimple:
    """Cover create_simple action."""

    @pytest.mark.asyncio
    async def test_create_simple_with_defaults(self):
        tools, _ = _make_alert_with_client()
        tools.anomaly_manager.create_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="Simple alert created")]
        )
        with patch.object(tools, "_resolve_notification_config", return_value={
            "notificationAddresses": ["a@b.com"],
            "slackConfigurations": [],
        }):
            result = await tools.handle_action("create_simple", {
                "name": "Simple", "email": "a@b.com",
            })
        assert result[0].text == "Simple alert created"

    @pytest.mark.asyncio
    async def test_create_simple_custom_metric_and_threshold(self):
        tools, _ = _make_alert_with_client()
        tools.anomaly_manager.create_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="Custom simple created")]
        )
        with patch.object(tools, "_resolve_notification_config", return_value={
            "notificationAddresses": ["a@b.com"],
            "slackConfigurations": [],
        }):
            result = await tools.handle_action("create_simple", {
                "name": "Custom",
                "email": "a@b.com",
                "metric": "ERROR_RATE",
                "threshold": 5,
            })
        assert result[0].text == "Custom simple created"
        sent = tools.anomaly_manager.create_anomaly.call_args[0][1]
        assert sent["metricType"] == "ERROR_RATE"
        assert sent["threshold"] == 5.0


# ===========================================================================
# handle_action — toggle_status and get_status
# ===========================================================================


class TestHandleActionToggleAndStatus:
    """Cover toggle_status and get_status actions."""

    @pytest.mark.asyncio
    async def test_toggle_status(self):
        tools, _ = _make_alert_with_client()
        with patch.object(
            tools, "_handle_toggle_anomaly_status", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Toggled")],
        ):
            result = await tools.handle_action("toggle_status", {"anomaly_id": "anom_1"})
        assert result[0].text == "Toggled"

    @pytest.mark.asyncio
    async def test_get_status(self):
        tools, _ = _make_alert_with_client()
        with patch.object(
            tools, "_handle_get_anomaly_status", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Status: enabled")],
        ):
            result = await tools.handle_action("get_status", {"anomaly_id": "anom_1"})
        assert result[0].text == "Status: enabled"


# ===========================================================================
# handle_action — enable_all and disable_all
# ===========================================================================


class TestHandleActionEnableDisableAll:
    """Cover enable_all and disable_all actions."""

    @pytest.mark.asyncio
    async def test_enable_all(self):
        tools, _ = _make_alert_with_client()
        with patch.object(
            tools, "_handle_enable_all_anomalies", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="All enabled")],
        ):
            result = await tools.handle_action("enable_all", {})
        assert result[0].text == "All enabled"

    @pytest.mark.asyncio
    async def test_disable_all(self):
        tools, _ = _make_alert_with_client()
        with patch.object(
            tools, "_handle_disable_all_anomalies", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="All disabled")],
        ):
            result = await tools.handle_action("disable_all", {})
        assert result[0].text == "All disabled"


# ===========================================================================
# handle_action — create_from_text and create_cumulative_usage_alert
# ===========================================================================


class TestHandleActionSpecializedCreation:
    """Cover create_from_text and create_cumulative_usage_alert routing."""

    @pytest.mark.asyncio
    async def test_create_from_text(self):
        tools, _ = _make_alert_with_client()
        with patch.object(
            tools, "_handle_create_from_text", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Created from text")],
        ):
            result = await tools.handle_action("create_from_text", {"text": "alert me when cost exceeds 100"})
        assert result[0].text == "Created from text"

    @pytest.mark.asyncio
    async def test_create_cumulative_usage_alert(self):
        tools, _ = _make_alert_with_client()
        with patch.object(
            tools, "_handle_create_cumulative_usage_alert", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Cumulative alert created")],
        ):
            result = await tools.handle_action("create_cumulative_usage_alert", {
                "name": "Budget Alert", "threshold": 1000, "period": "monthly",
            })
        assert result[0].text == "Cumulative alert created"

    @pytest.mark.asyncio
    async def test_test_ucm_integration(self):
        tools, _ = _make_alert_with_client()
        with patch.object(
            tools, "_handle_test_ucm_integration", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="UCM OK")],
        ):
            result = await tools.handle_action("test_ucm_integration", {})
        assert result[0].text == "UCM OK"


# ===========================================================================
# _handle_anomaly_operations — internal update logic
# ===========================================================================


class TestAnomalyOperationsUpdateInternal:
    """Cover _handle_anomaly_operations update path (beyond handle_action routing)."""

    @pytest.mark.asyncio
    async def test_anomaly_update_missing_id_returns_error(self):
        tools, client = _make_alert_with_client()
        with pytest.raises(ToolError) as exc_info:
            await tools._handle_anomaly_operations(client, "update", {})
        assert "anomaly_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_anomaly_update_no_data_returns_updatable_fields(self):
        tools, client = _make_alert_with_client()
        with pytest.raises(ToolError) as exc_info:
            await tools._handle_anomaly_operations(client, "update", {"anomaly_id": "a1"})
        text = str(exc_info.value)
        assert "name" in text and "email" in text

    @pytest.mark.asyncio
    async def test_anomaly_update_invalid_data_type(self):
        tools, client = _make_alert_with_client()
        with pytest.raises(ToolError) as exc_info:
            await tools._handle_anomaly_operations(client, "update", {
                "anomaly_id": "a1",
                "anomaly_data": "not_a_dict",
            })
        assert "dict" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_anomaly_update_with_merged_data(self):
        tools, client = _make_alert_with_client()
        tools.anomaly_manager.update_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="Updated")]
        )
        result = await tools._handle_anomaly_operations(client, "update", {
            "anomaly_id": "a1",
            "anomaly_data": {"name": "Base"},
            "threshold": 500,
        })
        call_args = tools.anomaly_manager.update_anomaly.call_args
        passed_data = call_args[0][2]
        assert passed_data["name"] == "Base"
        assert passed_data["threshold"] == 500

    @pytest.mark.asyncio
    async def test_anomaly_clear_all_without_confirm(self):
        tools, client = _make_alert_with_client()
        result = await tools._handle_anomaly_operations(client, "clear_all", {})
        assert "Confirmation" in result[0].text or "confirm" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_anomaly_query_uses_list(self):
        tools, client = _make_alert_with_client()
        tools.anomaly_manager.list_anomalies = AsyncMock(
            return_value=[TextContent(type="text", text="Query results")]
        )
        result = await tools._handle_anomaly_operations(client, "query", {})
        tools.anomaly_manager.list_anomalies.assert_called_once()

    @pytest.mark.asyncio
    async def test_anomaly_unknown_action(self):
        tools, client = _make_alert_with_client()
        with pytest.raises(ToolError) as exc_info:
            await tools._handle_anomaly_operations(client, "unknown_anomaly_action", {})
        text_lower = exc_info.value.message.lower()
        assert "unknown" in text_lower or "not supported" in text_lower


# ===========================================================================
# _handle_alert_operations — list and get
# ===========================================================================


class TestAlertOperations:
    """Cover _handle_alert_operations internal routing."""

    @pytest.mark.asyncio
    async def test_alert_list_routes_through_handle_list_not_alert_operations(self):
        """`_handle_alert_operations` is only ever invoked with action='get' or
        'query' (callers at lines 657 and 853). The list path is owned by
        `_handle_list`, which has its own pagination guard. Passing 'list' here
        falls through to the unsupported-action error — verifying the dead
        branch removal in the BACK-1270 follow-up bundle."""
        tools, client = _make_alert_with_client()
        with pytest.raises(ToolError) as exc_info:
            await tools._handle_alert_operations(client, "list", {})
        text_lower = exc_info.value.message.lower()
        assert "unknown" in text_lower or "not supported" in text_lower

    @pytest.mark.asyncio
    async def test_alert_get_missing_id(self):
        tools, client = _make_alert_with_client()
        with pytest.raises(ToolError) as exc_info:
            await tools._handle_alert_operations(client, "get", {})
        assert "alert_id" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_alert_query(self):
        tools, client = _make_alert_with_client()
        tools.alert_manager.list_alerts = AsyncMock(
            return_value=[TextContent(type="text", text="Query")]
        )
        result = await tools._handle_alert_operations(client, "query", {})
        assert result[0].text == "Query"


# ===========================================================================
# _detect_semantic_intent
# ===========================================================================


class TestSemanticIntentDetection:
    """Cover _detect_semantic_intent for resource type detection."""

    def test_default_returns_anomalies(self):
        tools = AlertManagement()
        result = tools._detect_semantic_intent({})
        assert result == "anomalies"

    def test_history_keyword_returns_alerts(self):
        tools = AlertManagement()
        result = tools._detect_semantic_intent({"query": "show me alert history"})
        assert result == "alerts"

    def test_rules_keyword_returns_anomalies(self):
        tools = AlertManagement()
        result = tools._detect_semantic_intent({"query": "list monitoring rules"})
        assert result == "anomalies"

    @pytest.mark.parametrize(
        "query",
        [
            "show my active alert rules",
            "rules for the duration of a spike",
            "which rules notify me when cost spikes",
            "show the last rule I made",
            "show elasticsearch rules",
            "show the rule definitions",
        ],
    )
    def test_a_rule_question_with_a_history_leaning_word_reaches_the_rules(self, query):
        assert AlertManagement()._detect_semantic_intent({"query": query}) == "anomalies"

    @pytest.mark.parametrize(
        "query",
        [
            "show alerts this week",
            "show alerts today",
            "show alerts from Oct 12 to Oct 14",
            "show active alerts",
            "show rules that fired in the last 24 hours",
            "show budget alerts this month",
        ],
    )
    def test_a_history_question_reaches_alert_history(self, query):
        assert AlertManagement()._detect_semantic_intent({"query": query}) == "alerts"

    @pytest.mark.parametrize("query", ["show elasticsearch thresholds", "show the whenever list"])
    def test_a_keyword_inside_another_word_does_not_decide(self, query):
        assert AlertManagement()._detect_semantic_intent({"query": query}) == "anomalies"


# ===========================================================================
# Every manage_alerts refusal reaches the caller flagged as an error
# ===========================================================================

_ALERT_MANAGEMENT_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "revenium_mcp_server"
    / "tools_decomposed"
    / "alert_management.py"
)
_ERROR_HANDLERS_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "revenium_mcp_server"
    / "error_handlers.py"
)

_ALERTS_PACKAGE = _ERROR_HANDLERS_SOURCE.parent / "alerts"


def _builds_text_content(node):
    return any(
        isinstance(inner, ast.Call)
        and getattr(inner.func, "id", getattr(inner.func, "attr", None)) == "TextContent"
        for inner in ast.walk(node)
    )


_PLATFORM_METHODS = (
    "get_alert_by_id",
    "get_anomaly_by_id",
    "get_anomalies",
    "create_anomaly",
    "update_anomaly",
    "delete_anomaly",
    "get_anomaly_metrics",
)

_FOUND_ALERT = {
    "id": "alert_found",
    "resolved": False,
    "anomaly": {"name": "Budget Alert", "description": "Budget threshold exceeded"},
    "triggeredTimestamp": "2026-10-01T10:00:00Z",
}
_FOUND_ANOMALY = {"id": "anom_found", "name": "Cost Spike", "enabled": True}
_VALID_ANOMALY_DATA = {
    "name": "Dry Run Alert",
    "alertType": "THRESHOLD",
    "metricType": "TOTAL_COST",
    "operatorType": "GREATER_THAN",
    "threshold": 100,
}


def _platform_stub(**overrides):
    """A client whose every platform call is an AsyncMock the test can inspect."""
    client = MagicMock()
    client.team_id = "team_test"
    client.get_alert_by_id = AsyncMock(return_value=_FOUND_ALERT)
    client.get_anomaly_by_id = AsyncMock(return_value=_FOUND_ANOMALY)
    client.get_anomalies = AsyncMock(return_value={})
    client._extract_embedded_data = MagicMock(return_value=[_FOUND_ANOMALY])
    client._extract_pagination_info = MagicMock(
        return_value={"totalElements": 1, "totalPages": 1, "number": 0, "size": 20}
    )
    client.create_anomaly = AsyncMock(return_value={"id": "anom_new"})
    client.update_anomaly = AsyncMock(return_value=_FOUND_ANOMALY)
    client.delete_anomaly = AsyncMock(return_value=None)
    client.get_anomaly_metrics = AsyncMock(return_value={})
    for name, value in overrides.items():
        setattr(client, name, value)
    return client


async def _call_manage_alerts(arguments, client):
    from tests.unit.test_tool_config_registry_m4 import _call_through_the_boundary

    with patch.object(AlertManagement, "get_client", AsyncMock(return_value=client)), patch.object(
        AlertManagement,
        "_resolve_notification_config",
        return_value={"notificationAddresses": ["ops@example.com"], "slackConfigurations": []},
    ):
        is_error, text, _ = await _call_through_the_boundary(
            "_register_manage_alerts", "manage_alerts", arguments, execute=True
        )
    return is_error, text


class TestManageAlertsErrorsCarryTheFlag:
    """A refusal is an error, not a result: every manage_alerts path that
    reports a failure must reach the caller with the error flag set, keeping
    the guidance text the customer reads (BACK-4705)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [403, 404])
    async def test_unknown_anomaly_id_is_flagged_not_found(self, status_code):
        client = _platform_stub(
            get_anomaly_by_id=AsyncMock(
                side_effect=ReveniumAPIError("missing", status_code=status_code)
            )
        )

        is_error, text = await _call_manage_alerts(
            {"action": "get", "anomaly_id": "NONEXISTENT_67890"}, client
        )

        assert is_error, text
        assert "**Error**: Anomaly with ID 'NONEXISTENT_67890'" in text
        assert "not found" in text.lower()
        assert "List all anomalies to see available IDs" in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [403, 404])
    async def test_unknown_alert_id_is_flagged_not_found(self, status_code):
        client = _platform_stub(
            get_alert_by_id=AsyncMock(
                side_effect=ReveniumAPIError("missing", status_code=status_code)
            )
        )

        is_error, text = await _call_manage_alerts(
            {"action": "get", "resource_type": "alerts", "alert_id": "NONEXISTENT_12345"},
            client,
        )

        assert is_error, text
        assert "**Error**: Alert with ID 'NONEXISTENT_12345'" in text
        assert "not found" in text.lower()
        assert "List all alerts to see available IDs" in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [500, 503])
    async def test_alert_history_server_error_is_flagged_and_named(self, status_code):
        client = _platform_stub(
            get_alert_by_id=AsyncMock(
                side_effect=ReveniumAPIError("upstream broke", status_code=status_code)
            )
        )

        is_error, text = await _call_manage_alerts(
            {"action": "get", "resource_type": "alerts", "alert_id": "alert_abc"}, client
        )

        assert is_error, text
        assert "server error" in text.lower()
        assert str(status_code) in text
        assert "alert_abc" in text
        assert "not found" not in text.lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "arguments, platform_method, label",
        [
            (
                {"action": "get", "resource_type": "alerts", "alert_id": "NONEXISTENT_12345"},
                "get_alert_by_id",
                "Alert",
            ),
            ({"action": "get", "anomaly_id": "NONEXISTENT_67890"}, "get_anomaly_by_id", "Anomaly"),
        ],
        ids=["alert", "anomaly"],
    )
    async def test_malformed_id_stays_flagged_as_invalid(
        self, arguments, platform_method, label
    ):
        """Dev answers a malformed id with HTTP 400 "Failed to decode hashed Id",
        which the client words as "Invalid ... ID"; that path is left as it is."""
        client_error = ReveniumAPIError(
            f"Invalid {label} ID\n\nThe provided {label.lower()} ID is not valid "
            "or does not exist.",
            status_code=400,
        )
        client = _platform_stub(**{platform_method: AsyncMock(side_effect=client_error)})

        is_error, text = await _call_manage_alerts(arguments, client)

        assert is_error, text
        assert f"Invalid {label} ID" in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "arguments, expected_fragments",
        [
            (
                {"action": "get"},
                ["anomaly_id", "**MISSING_PARAMETER**", "**Suggestions**"],
            ),
            (
                {"action": "get", "resource_type": "alerts"},
                ["alert_id", "**MISSING_PARAMETER**", "**Suggestions**"],
            ),
            (
                {"action": "delete"},
                ["anomaly_id", "**MISSING_PARAMETER**", "**Suggestions**"],
            ),
            (
                {"action": "get_metrics"},
                ["get_metrics is not available", "get_budget_progress", "**Valid actions**"],
            ),
            (
                {"action": "validate"},
                ["anomaly_data", "**MISSING_PARAMETER**", "**Suggestions**"],
            ),
            (
                {"action": "create_cumulative_usage_alert", "threshold": 100},
                ["name", "**MISSING_PARAMETER**", "**Suggestions**"],
            ),
            (
                {"action": "create", "dry_run": True},
                ["anomaly_data", "**MISSING_PARAMETER**", "**Suggestions**"],
            ),
            (
                {"action": "update", "dry_run": True, "anomaly_id": "anom_found"},
                ["update_data", "**MISSING_PARAMETER**", "**Suggestions**"],
            ),
            (
                {"action": "get", "resource_type": "alerts", "alert_id": "   "},
                ["Alert ID cannot be empty or whitespace"],
            ),
            (
                {"action": "get", "anomaly_id": "   "},
                ["Anomaly ID cannot be empty or whitespace"],
            ),
        ],
        ids=[
            "get-anomaly",
            "get-alert",
            "delete",
            "get_metrics",
            "validate",
            "cumulative-missing-name",
            "create-dry-run-missing-data",
            "update-dry-run-missing-data",
            "whitespace-alert-id",
            "whitespace-anomaly-id",
        ],
    )
    async def test_missing_required_argument_is_flagged(self, arguments, expected_fragments):
        client = _platform_stub()

        is_error, text = await _call_manage_alerts(arguments, client)

        assert is_error, text
        for fragment in expected_fragments:
            assert fragment in text, fragment
        for method in _PLATFORM_METHODS:
            getattr(client, method).assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("alert_owner_email")
    async def test_create_refusal_from_the_manager_is_flagged(self):
        client = _platform_stub()

        is_error, text = await _call_manage_alerts(
            {
                "action": "create",
                "anomaly_data": {**_VALID_ANOMALY_DATA, "periodDuration": "NOT_A_PERIOD"},
            },
            client,
        )

        assert is_error, text
        assert "periodDuration" in text
        client.create_anomaly.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "preview",
        [{"action": "create", "dry_run": True}, {"action": "validate"}],
        ids=["dry-run-reject-verdict", "validate-reject-verdict"],
    )
    @pytest.mark.usefixtures("alert_owner_email")
    async def test_preview_refusal_is_flagged_like_the_live_create(self, preview):
        client = _platform_stub()
        refused = {**_VALID_ANOMALY_DATA, "periodDuration": "NOT_A_PERIOD"}

        previewed = await _call_manage_alerts({**preview, "anomaly_data": dict(refused)}, client)
        created = await _call_manage_alerts(
            {"action": "create", "anomaly_data": dict(refused)}, client
        )

        assert previewed == created
        assert previewed[0] is True, previewed[1]
        assert "periodDuration" in previewed[1]
        client.create_anomaly.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_inverted_alert_history_window_is_flagged(self):
        client = _platform_stub(get_alerts=AsyncMock(return_value={}))

        is_error, text = await _call_manage_alerts(
            {
                "action": "list",
                "resource_type": "alerts",
                "filters": {"start": "2026-10-14", "end": "2026-10-12"},
            },
            client,
        )

        assert is_error, text
        refusal = text.removeprefix("Error calling tool 'manage_alerts': ")
        assert refusal.startswith("Window refused: start"), text
        client.get_alerts.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "arguments",
        [
            {"action": "get", "resource_type": "alerts", "alert_id": "alert_found"},
            {"action": "get", "anomaly_id": "anom_found"},
            {"action": "list", "resource_type": "anomalies"},
            {"action": "create", "dry_run": True, "anomaly_data": _VALID_ANOMALY_DATA},
            {"action": "validate", "anomaly_data": _VALID_ANOMALY_DATA},
            {"action": "clear_all"},
        ],
        ids=[
            "get-alert-found",
            "get-anomaly-found",
            "list",
            "valid-create-dry-run",
            "valid-validate",
            "clear_all-confirmation-preview",
        ],
    )
    @pytest.mark.usefixtures("alert_owner_email")
    async def test_success_paths_stay_unflagged(self, arguments):
        is_error, text = await _call_manage_alerts(arguments, _platform_stub())

        assert is_error is False, text

    def test_no_alert_tool_path_returns_formatted_error_text(self):
        """Structural guard: no formatter-built error text is returned by the tool, the decorator's except branches, or an except branch in the alerts package."""
        tool_source = _ALERT_MANAGEMENT_SOURCE.read_text()
        assert "format_structured_error" not in tool_source

        tool_tree = ast.parse(tool_source)
        raised_calls = set()
        for node in ast.walk(tool_tree):
            is_raise = isinstance(node, ast.Raise)
            is_refusal = (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "raise_refusal"
            )
            if is_raise or is_refusal:
                raised_calls.update(id(inner) for inner in ast.walk(node))
        returned_messages = [
            node.lineno
            for node in ast.walk(tool_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "format_user_message"
            and id(node) not in raised_calls
        ]
        assert returned_messages == [], returned_messages

        decorator = next(
            node
            for node in ast.walk(ast.parse(_ERROR_HANDLERS_SOURCE.read_text()))
            if isinstance(node, ast.FunctionDef) and node.name == "handle_alert_tool_errors"
        )
        returns_in_handlers = [
            inner.lineno
            for handler in ast.walk(decorator)
            if isinstance(handler, ast.ExceptHandler)
            for inner in ast.walk(handler)
            if isinstance(inner, ast.Return)
        ]
        assert returns_in_handlers == [], returns_in_handlers

        text_returned_from_handlers = [
            f"{source.name}:{inner.lineno}"
            for source in sorted(_ALERTS_PACKAGE.glob("*.py"))
            for handler in ast.walk(ast.parse(source.read_text()))
            if isinstance(handler, ast.ExceptHandler)
            for inner in ast.walk(handler)
            if isinstance(inner, ast.Return) and _builds_text_content(inner)
        ]
        assert text_returned_from_handlers == [], text_returned_from_handlers
