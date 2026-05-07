"""Extended unit tests for AlertManagement — deep CRUD coverage.

Covers handle_action routing for create, update, delete, list, enable/disable,
bulk operations, and specialized alert creation actions.
Mocks self.get_client() to avoid real API calls.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp.types import TextContent

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
        result = await tools.handle_action("get", {"resource_type": "anomalies"})
        assert isinstance(result[0], TextContent)
        assert "anomaly_id" in result[0].text.lower()

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
        tools, _ = _make_alert_with_client()
        result = await tools.handle_action("create", {"resource_type": "anomalies"})
        assert isinstance(result[0], TextContent)
        assert "anomaly_data" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_create_dry_run_valid(self):
        tools, _ = _make_alert_with_client()
        result = await tools.handle_action("create", {
            "resource_type": "anomalies",
            "dry_run": True,
            "anomaly_data": {
                "name": "Dry Run Alert",
                "metricType": "TOTAL_COST",
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
        result = await tools.handle_action("delete", {"resource_type": "anomalies"})
        assert isinstance(result[0], TextContent)
        assert "anomaly_id" in result[0].text.lower()

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
# handle_action — get_metrics routing
# ===========================================================================


class TestHandleActionGetMetrics:
    """Cover get_metrics action."""

    @pytest.mark.asyncio
    async def test_get_metrics_with_id(self):
        tools, _ = _make_alert_with_client()
        tools.anomaly_manager.get_anomaly_metrics = AsyncMock(
            return_value=[TextContent(type="text", text="Metrics")]
        )
        result = await tools.handle_action("get_metrics", {"anomaly_id": "anom_1"})
        assert result[0].text == "Metrics"

    @pytest.mark.asyncio
    async def test_get_metrics_missing_id_returns_error(self):
        tools, _ = _make_alert_with_client()
        result = await tools.handle_action("get_metrics", {})
        assert isinstance(result[0], TextContent)
        assert "anomaly_id" in result[0].text.lower()


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
            "resource_type": "anomalies", "filters": {"enabled": True},
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


class TestHandleActionValidate:
    """Cover validate action."""

    @pytest.mark.asyncio
    async def test_validate_with_data_returns_ucm_error(self):
        """Validate returns UCM guidance since hardcoded validation was removed."""
        tools, _ = _make_alert_with_client()
        result = await tools.handle_action("validate", {
            "anomaly_data": {"name": "Test", "metricType": "TOTAL_COST"},
        })
        assert isinstance(result[0], TextContent)
        # Should mention UCM or validation
        text_lower = result[0].text.lower()
        assert "ucm" in text_lower or "validation" in text_lower

    @pytest.mark.asyncio
    async def test_validate_missing_data_returns_error(self):
        tools, _ = _make_alert_with_client()
        result = await tools.handle_action("validate", {})
        assert isinstance(result[0], TextContent)
        assert "anomaly_data" in result[0].text.lower()


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
                "period_minutes": 5,
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
                    "threshold": 100, "period_minutes": 5, "email": "a@b.com",
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
                    "name": "Test", "period_minutes": 5, "email": "a@b.com",
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
                "period_minutes": 5,
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
                    "period_minutes": 5,
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
                "anomaly_data": {"name": "Simple", "email": "a@b.com"},
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
                "anomaly_data": {
                    "name": "Custom",
                    "email": "a@b.com",
                    "metric": "ERROR_RATE",
                    "threshold": 5,
                },
            })
        assert result[0].text == "Custom simple created"


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
        result = await tools._handle_anomaly_operations(client, "update", {})
        assert isinstance(result[0], TextContent)
        assert "anomaly_id" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_anomaly_update_no_data_returns_updatable_fields(self):
        tools, client = _make_alert_with_client()
        result = await tools._handle_anomaly_operations(client, "update", {"anomaly_id": "a1"})
        text = result[0].text
        # Should list updatable fields
        assert "name" in text or "threshold" in text

    @pytest.mark.asyncio
    async def test_anomaly_update_invalid_data_type(self):
        tools, client = _make_alert_with_client()
        result = await tools._handle_anomaly_operations(client, "update", {
            "anomaly_id": "a1",
            "anomaly_data": "not_a_dict",
        })
        assert isinstance(result[0], TextContent)
        text_lower = result[0].text.lower()
        assert "dict" in text_lower or "object" in text_lower or "type" in text_lower

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
    async def test_anomaly_get_metrics_missing_id(self):
        tools, client = _make_alert_with_client()
        result = await tools._handle_anomaly_operations(client, "get_metrics", {})
        assert "anomaly_id" in result[0].text.lower()

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
        result = await tools._handle_anomaly_operations(client, "unknown_anomaly_action", {})
        text_lower = result[0].text.lower()
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
        result = await tools._handle_alert_operations(client, "list", {})
        text_lower = result[0].text.lower()
        assert "unknown" in text_lower or "not supported" in text_lower

    @pytest.mark.asyncio
    async def test_alert_get_missing_id(self):
        tools, client = _make_alert_with_client()
        result = await tools._handle_alert_operations(client, "get", {})
        assert isinstance(result[0], TextContent)
        assert "alert_id" in result[0].text.lower()

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
