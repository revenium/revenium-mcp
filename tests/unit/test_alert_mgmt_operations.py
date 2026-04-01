"""Unit tests for Alert Management CRUD and Enable/Disable operations.

Covers:
- Part A: _handle_list, _handle_get, _handle_update, _handle_delete,
          _handle_clear_all, _handle_query
- Part B: _handle_enable_anomaly, _handle_disable_anomaly,
          _handle_enable_multiple, _handle_disable_multiple,
          _handle_enable_all_anomalies, _handle_disable_all_anomalies,
          _handle_toggle_anomaly_status, _handle_get_anomaly_status
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp.types import TextContent

from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from src.revenium_mcp_server.common.error_handling import ToolError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_client():
    """Create a mock ReveniumClient."""
    client = AsyncMock()
    client.get_anomaly_by_id = AsyncMock()
    client.update_anomaly = AsyncMock()
    client.get_anomalies = AsyncMock()
    client._extract_embedded_data = MagicMock()
    return client


@pytest.fixture
def alert_mgmt(mock_client):
    """AlertManagement with get_client patched to return mock_client."""
    tools = AlertManagement()
    tools.get_client = AsyncMock(return_value=mock_client)
    # Mock sub-managers so they don't hit the network
    tools.anomaly_manager = MagicMock()
    tools.alert_manager = MagicMock()
    return tools


def _text(content_list):
    """Extract text from a list of TextContent."""
    return content_list[0].text


# ===========================================================================
# Part A — CRUD Operations
# ===========================================================================

class TestHandleList:
    """Tests for _handle_list."""

    @pytest.mark.asyncio
    async def test_list_anomalies_routes_to_anomaly_operations(self, alert_mgmt, mock_client):
        """List with resource_type=anomalies delegates to _handle_anomaly_operations."""
        expected = [TextContent(type="text", text="anomaly list")]
        with patch.object(alert_mgmt, "_handle_anomaly_operations", new_callable=AsyncMock, return_value=expected) as mock_op:
            result = await alert_mgmt._handle_list(mock_client, {"resource_type": "anomalies"})
            mock_op.assert_called_once_with(mock_client, "list", {"resource_type": "anomalies"})
            assert result == expected

    @pytest.mark.asyncio
    async def test_list_alerts_calls_alert_manager(self, alert_mgmt, mock_client):
        """List with resource_type=alerts delegates to alert_manager.list_alerts."""
        expected = [TextContent(type="text", text="alert list")]
        alert_mgmt.alert_manager.list_alerts = AsyncMock(return_value=expected)
        result = await alert_mgmt._handle_list(mock_client, {"resource_type": "alerts"})
        alert_mgmt.alert_manager.list_alerts.assert_called_once()
        assert result == expected

    @pytest.mark.asyncio
    async def test_list_alerts_passes_pagination(self, alert_mgmt, mock_client):
        """Pagination params are forwarded to alert_manager.list_alerts."""
        expected = [TextContent(type="text", text="ok")]
        alert_mgmt.alert_manager.list_alerts = AsyncMock(return_value=expected)
        args = {"resource_type": "alerts", "page": 2, "size": 10, "filters": {"severity": "high"}, "query": "cost"}
        await alert_mgmt._handle_list(mock_client, args)
        alert_mgmt.alert_manager.list_alerts.assert_called_once_with(mock_client, 2, 10, {"severity": "high"}, "cost")

    @pytest.mark.asyncio
    async def test_list_alerts_defaults_pagination(self, alert_mgmt, mock_client):
        """Default pagination is page=0, size=20."""
        expected = [TextContent(type="text", text="ok")]
        alert_mgmt.alert_manager.list_alerts = AsyncMock(return_value=expected)
        await alert_mgmt._handle_list(mock_client, {"resource_type": "alerts"})
        alert_mgmt.alert_manager.list_alerts.assert_called_once_with(mock_client, 0, 20, {}, None)

    @pytest.mark.asyncio
    async def test_list_invalid_resource_type_raises(self, alert_mgmt, mock_client):
        """Invalid resource_type raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_list(mock_client, {"resource_type": "widgets"})
        assert "widgets" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_list_alerts_api_error_raises_tool_error(self, alert_mgmt, mock_client):
        """API error in list_alerts is wrapped in ToolError."""
        alert_mgmt.alert_manager.list_alerts = AsyncMock(side_effect=RuntimeError("connection refused"))
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_list(mock_client, {"resource_type": "alerts"})
        assert "Failed to list alerts" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_list_alerts_tool_error_reraises(self, alert_mgmt, mock_client):
        """ToolError from list_alerts is re-raised without wrapping."""
        original = ToolError(message="original error")
        alert_mgmt.alert_manager.list_alerts = AsyncMock(side_effect=original)
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_list(mock_client, {"resource_type": "alerts"})
        assert exc_info.value is original

    @pytest.mark.asyncio
    async def test_list_semantic_detection_when_no_resource_type(self, alert_mgmt, mock_client):
        """When resource_type is absent, _detect_semantic_intent is called."""
        expected = [TextContent(type="text", text="ok")]
        with patch.object(alert_mgmt, "_detect_semantic_intent", return_value="anomalies") as mock_detect:
            with patch.object(alert_mgmt, "_handle_anomaly_operations", new_callable=AsyncMock, return_value=expected):
                await alert_mgmt._handle_list(mock_client, {"query": "show me alerts"})
                mock_detect.assert_called_once()


class TestHandleGet:
    """Tests for _handle_get."""

    @pytest.mark.asyncio
    async def test_get_anomalies_routes_correctly(self, alert_mgmt, mock_client):
        """Get with resource_type=anomalies delegates to anomaly operations."""
        expected = [TextContent(type="text", text="anomaly detail")]
        with patch.object(alert_mgmt, "_handle_anomaly_operations", new_callable=AsyncMock, return_value=expected) as mock_op:
            result = await alert_mgmt._handle_get(mock_client, {"resource_type": "anomalies", "anomaly_id": "123"})
            mock_op.assert_called_once_with(mock_client, "get", {"resource_type": "anomalies", "anomaly_id": "123"})
            assert result == expected

    @pytest.mark.asyncio
    async def test_get_alerts_routes_correctly(self, alert_mgmt, mock_client):
        """Get with resource_type=alerts delegates to alert operations."""
        expected = [TextContent(type="text", text="alert detail")]
        with patch.object(alert_mgmt, "_handle_alert_operations", new_callable=AsyncMock, return_value=expected) as mock_op:
            result = await alert_mgmt._handle_get(mock_client, {"resource_type": "alerts", "alert_id": "456"})
            mock_op.assert_called_once_with(mock_client, "get", {"resource_type": "alerts", "alert_id": "456"})
            assert result == expected

    @pytest.mark.asyncio
    async def test_get_defaults_to_anomalies(self, alert_mgmt, mock_client):
        """When resource_type is missing, defaults to anomalies."""
        expected = [TextContent(type="text", text="ok")]
        with patch.object(alert_mgmt, "_handle_anomaly_operations", new_callable=AsyncMock, return_value=expected) as mock_op:
            await alert_mgmt._handle_get(mock_client, {"anomaly_id": "123"})
            mock_op.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_invalid_resource_type_raises(self, alert_mgmt, mock_client):
        """Invalid resource_type raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_get(mock_client, {"resource_type": "invalid"})
        assert "invalid" in str(exc_info.value).lower()


class TestHandleUpdate:
    """Tests for _handle_update."""

    @pytest.mark.asyncio
    async def test_update_anomalies_routes_correctly(self, alert_mgmt, mock_client):
        """Update with resource_type=anomalies delegates to anomaly operations."""
        expected = [TextContent(type="text", text="updated")]
        with patch.object(alert_mgmt, "_handle_anomaly_operations", new_callable=AsyncMock, return_value=expected) as mock_op:
            result = await alert_mgmt._handle_update(mock_client, {"resource_type": "anomalies", "anomaly_id": "123", "anomaly_data": {"name": "x"}})
            mock_op.assert_called_once()
            assert result == expected

    @pytest.mark.asyncio
    async def test_update_non_anomalies_raises(self, alert_mgmt, mock_client):
        """Update with resource_type=alerts raises ToolError (alerts are read-only)."""
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_update(mock_client, {"resource_type": "alerts"})
        assert "read-only" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_update_defaults_to_anomalies(self, alert_mgmt, mock_client):
        """When resource_type is missing, defaults to anomalies."""
        expected = [TextContent(type="text", text="ok")]
        with patch.object(alert_mgmt, "_handle_anomaly_operations", new_callable=AsyncMock, return_value=expected):
            result = await alert_mgmt._handle_update(mock_client, {"anomaly_id": "123", "anomaly_data": {"name": "x"}})
            assert result == expected

    @pytest.mark.asyncio
    async def test_update_dry_run_success(self, alert_mgmt, mock_client):
        """Dry run returns validation result without calling API."""
        result = await alert_mgmt._handle_update(mock_client, {
            "resource_type": "anomalies",
            "dry_run": True,
            "anomaly_id": "123",
            "anomaly_data": {"name": "Test"}
        })
        text = _text(result)
        assert "DRY RUN" in text
        assert "valid" in text.lower()

    @pytest.mark.asyncio
    async def test_update_dry_run_missing_id(self, alert_mgmt, mock_client):
        """Dry run with missing anomaly_id returns failure message."""
        result = await alert_mgmt._handle_update(mock_client, {
            "resource_type": "anomalies",
            "dry_run": True,
            "anomaly_data": {"name": "Test"}
        })
        text = _text(result)
        assert "Missing" in text or "Failed" in text

    @pytest.mark.asyncio
    async def test_update_dry_run_missing_data(self, alert_mgmt, mock_client):
        """Dry run with missing anomaly_data returns failure message."""
        result = await alert_mgmt._handle_update(mock_client, {
            "resource_type": "anomalies",
            "dry_run": True,
            "anomaly_id": "123"
        })
        text = _text(result)
        assert "Missing" in text or "Failed" in text


class TestHandleDelete:
    """Tests for _handle_delete."""

    @pytest.mark.asyncio
    async def test_delete_anomalies_routes_correctly(self, alert_mgmt, mock_client):
        """Delete with resource_type=anomalies delegates to anomaly operations."""
        expected = [TextContent(type="text", text="deleted")]
        with patch.object(alert_mgmt, "_handle_anomaly_operations", new_callable=AsyncMock, return_value=expected) as mock_op:
            result = await alert_mgmt._handle_delete(mock_client, {"resource_type": "anomalies", "anomaly_id": "123"})
            mock_op.assert_called_once_with(mock_client, "delete", {"resource_type": "anomalies", "anomaly_id": "123"})
            assert result == expected

    @pytest.mark.asyncio
    async def test_delete_non_anomalies_raises(self, alert_mgmt, mock_client):
        """Delete with resource_type=alerts raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_delete(mock_client, {"resource_type": "alerts"})
        assert "historical" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_delete_defaults_to_anomalies(self, alert_mgmt, mock_client):
        """When resource_type is missing, defaults to anomalies."""
        expected = [TextContent(type="text", text="ok")]
        with patch.object(alert_mgmt, "_handle_anomaly_operations", new_callable=AsyncMock, return_value=expected):
            result = await alert_mgmt._handle_delete(mock_client, {"anomaly_id": "123"})
            assert result == expected


class TestHandleClearAll:
    """Tests for _handle_clear_all."""

    @pytest.mark.asyncio
    async def test_clear_all_anomalies_routes_correctly(self, alert_mgmt, mock_client):
        """Clear all with resource_type=anomalies delegates to anomaly operations."""
        expected = [TextContent(type="text", text="cleared")]
        with patch.object(alert_mgmt, "_handle_anomaly_operations", new_callable=AsyncMock, return_value=expected) as mock_op:
            result = await alert_mgmt._handle_clear_all(mock_client, {"resource_type": "anomalies"})
            mock_op.assert_called_once_with(mock_client, "clear_all", {"resource_type": "anomalies"})
            assert result == expected

    @pytest.mark.asyncio
    async def test_clear_all_non_anomalies_raises(self, alert_mgmt, mock_client):
        """Clear all with resource_type=alerts raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_clear_all(mock_client, {"resource_type": "alerts"})
        assert "historical" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_clear_all_defaults_to_anomalies(self, alert_mgmt, mock_client):
        """When resource_type is missing, defaults to anomalies."""
        expected = [TextContent(type="text", text="ok")]
        with patch.object(alert_mgmt, "_handle_anomaly_operations", new_callable=AsyncMock, return_value=expected):
            result = await alert_mgmt._handle_clear_all(mock_client, {})
            assert result == expected


class TestHandleQuery:
    """Tests for _handle_query."""

    @pytest.mark.asyncio
    async def test_query_alerts_routes_correctly(self, alert_mgmt, mock_client):
        """Query with resource_type=alerts delegates to alert operations."""
        expected = [TextContent(type="text", text="query results")]
        with patch.object(alert_mgmt, "_handle_alert_operations", new_callable=AsyncMock, return_value=expected) as mock_op:
            result = await alert_mgmt._handle_query(mock_client, {"resource_type": "alerts", "query": "high cost"})
            mock_op.assert_called_once_with(mock_client, "query", {"resource_type": "alerts", "query": "high cost"})
            assert result == expected

    @pytest.mark.asyncio
    async def test_query_anomalies_routes_correctly(self, alert_mgmt, mock_client):
        """Query with resource_type=anomalies delegates to anomaly operations."""
        expected = [TextContent(type="text", text="anomaly query")]
        with patch.object(alert_mgmt, "_handle_anomaly_operations", new_callable=AsyncMock, return_value=expected) as mock_op:
            result = await alert_mgmt._handle_query(mock_client, {"resource_type": "anomalies"})
            mock_op.assert_called_once_with(mock_client, "query", {"resource_type": "anomalies"})
            assert result == expected

    @pytest.mark.asyncio
    async def test_query_defaults_to_alerts(self, alert_mgmt, mock_client):
        """When resource_type is missing, defaults to alerts."""
        expected = [TextContent(type="text", text="ok")]
        with patch.object(alert_mgmt, "_handle_alert_operations", new_callable=AsyncMock, return_value=expected) as mock_op:
            await alert_mgmt._handle_query(mock_client, {"query": "show all"})
            mock_op.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_invalid_resource_type_raises(self, alert_mgmt, mock_client):
        """Invalid resource_type raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_query(mock_client, {"resource_type": "invalid"})
        assert "invalid" in str(exc_info.value).lower()


# ===========================================================================
# Part B — Enable/Disable Operations
# ===========================================================================

class TestHandleEnableAnomaly:
    """Tests for _handle_enable_anomaly."""

    @pytest.mark.asyncio
    async def test_enable_success(self, alert_mgmt, mock_client):
        """Enable anomaly fetches, sets enabled=True, updates."""
        mock_client.get_anomaly_by_id.return_value = {"id": "a1", "name": "Test", "enabled": False}
        mock_client.update_anomaly.return_value = {"id": "a1", "name": "Test", "enabled": True}

        result = await alert_mgmt._handle_enable_anomaly(mock_client, {"anomaly_id": "a1"})
        text = _text(result)
        assert "Enabled" in text
        assert "a1" in text

        # Verify update was called with enabled=True
        call_data = mock_client.update_anomaly.call_args[0][1]
        assert call_data["enabled"] is True

    @pytest.mark.asyncio
    async def test_enable_missing_id_raises(self, alert_mgmt, mock_client):
        """Enable without anomaly_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_enable_anomaly(mock_client, {})
        assert "anomaly_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_enable_api_error_raises_tool_error(self, alert_mgmt, mock_client):
        """API error during enable is wrapped in ToolError."""
        mock_client.get_anomaly_by_id.side_effect = RuntimeError("network down")
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_enable_anomaly(mock_client, {"anomaly_id": "a1"})
        assert "Failed to enable" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_enable_tool_error_reraises(self, alert_mgmt, mock_client):
        """ToolError from client is re-raised without wrapping."""
        original = ToolError(message="not found")
        mock_client.get_anomaly_by_id.side_effect = original
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_enable_anomaly(mock_client, {"anomaly_id": "a1"})
        assert exc_info.value is original


class TestHandleDisableAnomaly:
    """Tests for _handle_disable_anomaly."""

    @pytest.mark.asyncio
    async def test_disable_success(self, alert_mgmt, mock_client):
        """Disable anomaly fetches, sets enabled=False, updates."""
        mock_client.get_anomaly_by_id.return_value = {"id": "a1", "name": "Test", "enabled": True}
        mock_client.update_anomaly.return_value = {"id": "a1", "name": "Test", "enabled": False}

        result = await alert_mgmt._handle_disable_anomaly(mock_client, {"anomaly_id": "a1"})
        text = _text(result)
        assert "Disabled" in text
        assert "a1" in text

        call_data = mock_client.update_anomaly.call_args[0][1]
        assert call_data["enabled"] is False

    @pytest.mark.asyncio
    async def test_disable_missing_id_raises(self, alert_mgmt, mock_client):
        """Disable without anomaly_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_disable_anomaly(mock_client, {})
        assert "anomaly_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_disable_api_error_raises_tool_error(self, alert_mgmt, mock_client):
        """API error during disable is wrapped in ToolError."""
        mock_client.get_anomaly_by_id.side_effect = RuntimeError("timeout")
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_disable_anomaly(mock_client, {"anomaly_id": "a1"})
        assert "Failed to disable" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_disable_tool_error_reraises(self, alert_mgmt, mock_client):
        """ToolError from client is re-raised without wrapping."""
        original = ToolError(message="not found")
        mock_client.get_anomaly_by_id.side_effect = original
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_disable_anomaly(mock_client, {"anomaly_id": "a1"})
        assert exc_info.value is original


class TestHandleEnableMultiple:
    """Tests for _handle_enable_multiple."""

    @pytest.mark.asyncio
    async def test_enable_multiple_success(self, alert_mgmt, mock_client):
        """Enable multiple anomalies reports success counts."""
        mock_client.get_anomaly_by_id.side_effect = [
            {"id": "a1", "name": "Alert 1", "enabled": False},
            {"id": "a2", "name": "Alert 2", "enabled": False},
        ]
        mock_client.update_anomaly.side_effect = [
            {"id": "a1", "name": "Alert 1", "enabled": True},
            {"id": "a2", "name": "Alert 2", "enabled": True},
        ]

        result = await alert_mgmt._handle_enable_multiple(mock_client, {"anomaly_ids": ["a1", "a2"]})
        text = _text(result)
        assert "Successful" in text
        assert "2" in text

    @pytest.mark.asyncio
    async def test_enable_multiple_empty_list_raises(self, alert_mgmt, mock_client):
        """Empty anomaly_ids list raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_enable_multiple(mock_client, {"anomaly_ids": []})
        assert "anomaly_ids" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_enable_multiple_missing_param_raises(self, alert_mgmt, mock_client):
        """Missing anomaly_ids raises ToolError."""
        with pytest.raises(ToolError):
            await alert_mgmt._handle_enable_multiple(mock_client, {})

    @pytest.mark.asyncio
    async def test_enable_multiple_partial_failure(self, alert_mgmt, mock_client):
        """Partial failures are counted and reported."""
        mock_client.get_anomaly_by_id.side_effect = [
            {"id": "a1", "name": "Alert 1", "enabled": False},
            RuntimeError("not found"),
        ]
        mock_client.update_anomaly.return_value = {"id": "a1", "name": "Alert 1", "enabled": True}

        result = await alert_mgmt._handle_enable_multiple(mock_client, {"anomaly_ids": ["a1", "a2"]})
        text = _text(result)
        assert "Successful" in text
        assert "Failed" in text

    @pytest.mark.asyncio
    async def test_enable_multiple_tool_error_reraises(self, alert_mgmt, mock_client):
        """ToolError from client is re-raised, not counted as failure."""
        original = ToolError(message="auth error")
        mock_client.get_anomaly_by_id.side_effect = original
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_enable_multiple(mock_client, {"anomaly_ids": ["a1"]})
        assert exc_info.value is original


class TestHandleDisableMultiple:
    """Tests for _handle_disable_multiple."""

    @pytest.mark.asyncio
    async def test_disable_multiple_success(self, alert_mgmt, mock_client):
        """Disable multiple anomalies reports success counts."""
        mock_client.get_anomaly_by_id.side_effect = [
            {"id": "a1", "name": "Alert 1", "enabled": True},
            {"id": "a2", "name": "Alert 2", "enabled": True},
        ]
        mock_client.update_anomaly.side_effect = [
            {"id": "a1", "name": "Alert 1", "enabled": False},
            {"id": "a2", "name": "Alert 2", "enabled": False},
        ]

        result = await alert_mgmt._handle_disable_multiple(mock_client, {"anomaly_ids": ["a1", "a2"]})
        text = _text(result)
        assert "Successful" in text
        assert "2" in text

    @pytest.mark.asyncio
    async def test_disable_multiple_empty_list_raises(self, alert_mgmt, mock_client):
        """Empty anomaly_ids list raises ToolError."""
        with pytest.raises(ToolError):
            await alert_mgmt._handle_disable_multiple(mock_client, {"anomaly_ids": []})

    @pytest.mark.asyncio
    async def test_disable_multiple_partial_failure(self, alert_mgmt, mock_client):
        """Partial failures are counted and reported."""
        mock_client.get_anomaly_by_id.side_effect = [
            {"id": "a1", "name": "Alert 1", "enabled": True},
            RuntimeError("timeout"),
        ]
        mock_client.update_anomaly.return_value = {"id": "a1", "name": "Alert 1", "enabled": False}

        result = await alert_mgmt._handle_disable_multiple(mock_client, {"anomaly_ids": ["a1", "a2"]})
        text = _text(result)
        assert "Failed" in text

    @pytest.mark.asyncio
    async def test_disable_multiple_tool_error_reraises(self, alert_mgmt, mock_client):
        """ToolError from client is re-raised, not counted as failure."""
        original = ToolError(message="forbidden")
        mock_client.get_anomaly_by_id.side_effect = original
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_disable_multiple(mock_client, {"anomaly_ids": ["a1"]})
        assert exc_info.value is original


class TestHandleEnableAllAnomalies:
    """Tests for _handle_enable_all_anomalies."""

    @pytest.mark.asyncio
    async def test_enable_all_requires_confirmation(self, alert_mgmt, mock_client):
        """Without confirm=True, returns confirmation prompt."""
        result = await alert_mgmt._handle_enable_all_anomalies(mock_client, {})
        text = _text(result)
        assert "Confirmation Required" in text

    @pytest.mark.asyncio
    async def test_enable_all_confirm_false(self, alert_mgmt, mock_client):
        """confirm=False returns confirmation prompt."""
        result = await alert_mgmt._handle_enable_all_anomalies(mock_client, {"confirm": False})
        text = _text(result)
        assert "Confirmation Required" in text

    @pytest.mark.asyncio
    async def test_enable_all_no_anomalies(self, alert_mgmt, mock_client):
        """When no anomalies exist, returns appropriate message."""
        mock_client.get_anomalies.return_value = {}
        mock_client._extract_embedded_data.return_value = []

        result = await alert_mgmt._handle_enable_all_anomalies(mock_client, {"confirm": True})
        text = _text(result)
        assert "No alerts found" in text

    @pytest.mark.asyncio
    async def test_enable_all_enables_disabled_only(self, alert_mgmt, mock_client):
        """Already-enabled anomalies are skipped; disabled ones are enabled."""
        mock_client.get_anomalies.return_value = {"_embedded": {"anomalies": []}}
        mock_client._extract_embedded_data.return_value = [
            {"id": "1", "name": "Enabled Alert", "enabled": True},
            {"id": "2", "name": "Disabled Alert", "enabled": False},
        ]
        mock_client.get_anomaly_by_id.return_value = {"id": "2", "name": "Disabled Alert", "enabled": False}
        mock_client.update_anomaly.return_value = {"id": "2", "name": "Disabled Alert", "enabled": True}

        result = await alert_mgmt._handle_enable_all_anomalies(mock_client, {"confirm": True})
        text = _text(result)
        assert "Already Enabled" in text
        assert "1" in text  # already_enabled count
        assert "Enabled:" in text  # the one that was enabled

    @pytest.mark.asyncio
    async def test_enable_all_handles_individual_failure(self, alert_mgmt, mock_client):
        """Individual anomaly failure during enable_all is counted."""
        mock_client.get_anomalies.return_value = {}
        mock_client._extract_embedded_data.return_value = [
            {"id": "1", "name": "Alert 1", "enabled": False},
        ]
        mock_client.get_anomaly_by_id.side_effect = RuntimeError("not found")

        result = await alert_mgmt._handle_enable_all_anomalies(mock_client, {"confirm": True})
        text = _text(result)
        assert "Failed" in text

    @pytest.mark.asyncio
    async def test_enable_all_api_error_raises_tool_error(self, alert_mgmt, mock_client):
        """API error in get_anomalies is wrapped in ToolError."""
        mock_client.get_anomalies.side_effect = RuntimeError("server error")
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_enable_all_anomalies(mock_client, {"confirm": True})
        assert "Failed to enable all" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_enable_all_tool_error_reraises(self, alert_mgmt, mock_client):
        """ToolError from get_anomalies is re-raised."""
        original = ToolError(message="auth failed")
        mock_client.get_anomalies.side_effect = original
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_enable_all_anomalies(mock_client, {"confirm": True})
        assert exc_info.value is original

    @pytest.mark.asyncio
    async def test_enable_all_truncates_details_over_10(self, alert_mgmt, mock_client):
        """Results list is truncated to 10 with '... and N more' message."""
        anomalies = [{"id": str(i), "name": f"Alert {i}", "enabled": False} for i in range(15)]
        mock_client.get_anomalies.return_value = {}
        mock_client._extract_embedded_data.return_value = anomalies
        mock_client.get_anomaly_by_id.side_effect = [
            {"id": str(i), "name": f"Alert {i}", "enabled": False} for i in range(15)
        ]
        mock_client.update_anomaly.side_effect = [
            {"id": str(i), "name": f"Alert {i}", "enabled": True} for i in range(15)
        ]

        result = await alert_mgmt._handle_enable_all_anomalies(mock_client, {"confirm": True})
        text = _text(result)
        assert "more" in text


class TestHandleDisableAllAnomalies:
    """Tests for _handle_disable_all_anomalies."""

    @pytest.mark.asyncio
    async def test_disable_all_requires_confirmation(self, alert_mgmt, mock_client):
        """Without confirm=True, returns confirmation prompt."""
        result = await alert_mgmt._handle_disable_all_anomalies(mock_client, {})
        text = _text(result)
        assert "Confirmation Required" in text
        assert "WARNING" in text

    @pytest.mark.asyncio
    async def test_disable_all_no_anomalies(self, alert_mgmt, mock_client):
        """When no anomalies exist, returns appropriate message."""
        mock_client.get_anomalies.return_value = {}
        mock_client._extract_embedded_data.return_value = []

        result = await alert_mgmt._handle_disable_all_anomalies(mock_client, {"confirm": True})
        text = _text(result)
        assert "No alerts found" in text

    @pytest.mark.asyncio
    async def test_disable_all_disables_enabled_only(self, alert_mgmt, mock_client):
        """Already-disabled anomalies are skipped; enabled ones are disabled."""
        mock_client.get_anomalies.return_value = {}
        mock_client._extract_embedded_data.return_value = [
            {"id": "1", "name": "Enabled Alert", "enabled": True},
            {"id": "2", "name": "Disabled Alert", "enabled": False},
        ]
        mock_client.get_anomaly_by_id.return_value = {"id": "1", "name": "Enabled Alert", "enabled": True}
        mock_client.update_anomaly.return_value = {"id": "1", "name": "Enabled Alert", "enabled": False}

        result = await alert_mgmt._handle_disable_all_anomalies(mock_client, {"confirm": True})
        text = _text(result)
        assert "Already Disabled" in text
        assert "Disabled:" in text

    @pytest.mark.asyncio
    async def test_disable_all_handles_individual_failure(self, alert_mgmt, mock_client):
        """Individual anomaly failure during disable_all is counted."""
        mock_client.get_anomalies.return_value = {}
        mock_client._extract_embedded_data.return_value = [
            {"id": "1", "name": "Alert 1", "enabled": True},
        ]
        mock_client.get_anomaly_by_id.side_effect = RuntimeError("not found")

        result = await alert_mgmt._handle_disable_all_anomalies(mock_client, {"confirm": True})
        text = _text(result)
        assert "Failed" in text

    @pytest.mark.asyncio
    async def test_disable_all_api_error_raises_tool_error(self, alert_mgmt, mock_client):
        """API error in get_anomalies is wrapped in ToolError."""
        mock_client.get_anomalies.side_effect = RuntimeError("server error")
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_disable_all_anomalies(mock_client, {"confirm": True})
        assert "Failed to disable all" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_disable_all_tool_error_reraises(self, alert_mgmt, mock_client):
        """ToolError from get_anomalies is re-raised."""
        original = ToolError(message="auth failed")
        mock_client.get_anomalies.side_effect = original
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_disable_all_anomalies(mock_client, {"confirm": True})
        assert exc_info.value is original

    @pytest.mark.asyncio
    async def test_disable_all_truncates_details_over_10(self, alert_mgmt, mock_client):
        """Results list is truncated to 10 with '... and N more' message."""
        anomalies = [{"id": str(i), "name": f"Alert {i}", "enabled": True} for i in range(15)]
        mock_client.get_anomalies.return_value = {}
        mock_client._extract_embedded_data.return_value = anomalies
        mock_client.get_anomaly_by_id.side_effect = [
            {"id": str(i), "name": f"Alert {i}", "enabled": True} for i in range(15)
        ]
        mock_client.update_anomaly.side_effect = [
            {"id": str(i), "name": f"Alert {i}", "enabled": False} for i in range(15)
        ]

        result = await alert_mgmt._handle_disable_all_anomalies(mock_client, {"confirm": True})
        text = _text(result)
        assert "more" in text


class TestHandleToggleAnomalyStatus:
    """Tests for _handle_toggle_anomaly_status."""

    @pytest.mark.asyncio
    async def test_toggle_from_enabled_to_disabled(self, alert_mgmt, mock_client):
        """Toggle from enabled to disabled."""
        mock_client.get_anomaly_by_id.return_value = {"id": "a1", "name": "Test", "enabled": True}
        mock_client.update_anomaly.return_value = {"id": "a1", "name": "Test", "enabled": False}

        result = await alert_mgmt._handle_toggle_anomaly_status(mock_client, {"anomaly_id": "a1"})
        text = _text(result)
        assert "Toggled" in text
        assert "Disabled" in text
        assert "Previous Status" in text

    @pytest.mark.asyncio
    async def test_toggle_from_disabled_to_enabled(self, alert_mgmt, mock_client):
        """Toggle from disabled to enabled."""
        mock_client.get_anomaly_by_id.return_value = {"id": "a1", "name": "Test", "enabled": False}
        mock_client.update_anomaly.return_value = {"id": "a1", "name": "Test", "enabled": True}

        result = await alert_mgmt._handle_toggle_anomaly_status(mock_client, {"anomaly_id": "a1"})
        text = _text(result)
        assert "Toggled" in text
        assert "Enabled" in text

    @pytest.mark.asyncio
    async def test_toggle_missing_id_raises(self, alert_mgmt, mock_client):
        """Toggle without anomaly_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_toggle_anomaly_status(mock_client, {})
        assert "anomaly_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_toggle_api_error_raises_tool_error(self, alert_mgmt, mock_client):
        """API error during toggle is wrapped in ToolError."""
        mock_client.get_anomaly_by_id.side_effect = RuntimeError("network error")
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_toggle_anomaly_status(mock_client, {"anomaly_id": "a1"})
        assert "Failed to toggle" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_toggle_tool_error_reraises(self, alert_mgmt, mock_client):
        """ToolError from client is re-raised without wrapping."""
        original = ToolError(message="not found")
        mock_client.get_anomaly_by_id.side_effect = original
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_toggle_anomaly_status(mock_client, {"anomaly_id": "a1"})
        assert exc_info.value is original

    @pytest.mark.asyncio
    async def test_toggle_passes_correct_enabled_value(self, alert_mgmt, mock_client):
        """Toggle sets enabled to opposite of current value."""
        mock_client.get_anomaly_by_id.return_value = {"id": "a1", "name": "Test", "enabled": True}
        mock_client.update_anomaly.return_value = {"id": "a1", "name": "Test", "enabled": False}

        await alert_mgmt._handle_toggle_anomaly_status(mock_client, {"anomaly_id": "a1"})
        call_data = mock_client.update_anomaly.call_args[0][1]
        assert call_data["enabled"] is False


class TestHandleGetAnomalyStatus:
    """Tests for _handle_get_anomaly_status."""

    @pytest.mark.asyncio
    async def test_get_status_success(self, alert_mgmt, mock_client):
        """Get status returns summary of enabled/disabled counts."""
        mock_client.get_anomalies.return_value = {}
        mock_client._extract_embedded_data.return_value = [
            {"id": "1", "name": "Alert 1", "enabled": True},
            {"id": "2", "name": "Alert 2", "enabled": False},
            {"id": "3", "name": "Alert 3", "enabled": True},
        ]

        result = await alert_mgmt._handle_get_anomaly_status(mock_client, {})
        text = _text(result)
        assert "Alert Status Summary" in text
        assert "Enabled" in text
        assert "Disabled" in text
        assert "3" in text  # total

    @pytest.mark.asyncio
    async def test_get_status_no_anomalies(self, alert_mgmt, mock_client):
        """When no anomalies exist, returns appropriate message."""
        mock_client.get_anomalies.return_value = {}
        mock_client._extract_embedded_data.return_value = []

        result = await alert_mgmt._handle_get_anomaly_status(mock_client, {})
        text = _text(result)
        assert "No alerts found" in text

    @pytest.mark.asyncio
    async def test_get_status_api_error_raises_tool_error(self, alert_mgmt, mock_client):
        """API error is wrapped in ToolError."""
        mock_client.get_anomalies.side_effect = RuntimeError("server error")
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_get_anomaly_status(mock_client, {})
        assert "Failed to get alert status" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_status_tool_error_reraises(self, alert_mgmt, mock_client):
        """ToolError from client is re-raised."""
        original = ToolError(message="auth failed")
        mock_client.get_anomalies.side_effect = original
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_get_anomaly_status(mock_client, {})
        assert exc_info.value is original

    @pytest.mark.asyncio
    async def test_get_status_truncates_over_20(self, alert_mgmt, mock_client):
        """Status list is truncated to 20 entries."""
        anomalies = [{"id": str(i), "name": f"Alert {i}", "enabled": True} for i in range(25)]
        mock_client.get_anomalies.return_value = {}
        mock_client._extract_embedded_data.return_value = anomalies

        result = await alert_mgmt._handle_get_anomaly_status(mock_client, {})
        text = _text(result)
        assert "more" in text

    @pytest.mark.asyncio
    async def test_get_status_all_enabled(self, alert_mgmt, mock_client):
        """All anomalies enabled shows correct counts."""
        mock_client.get_anomalies.return_value = {}
        mock_client._extract_embedded_data.return_value = [
            {"id": "1", "name": "Alert 1", "enabled": True},
            {"id": "2", "name": "Alert 2", "enabled": True},
        ]

        result = await alert_mgmt._handle_get_anomaly_status(mock_client, {})
        text = _text(result)
        assert "Enabled" in text
        assert "Disabled" in text

    @pytest.mark.asyncio
    async def test_get_status_uses_fallback_name(self, alert_mgmt, mock_client):
        """Anomaly without name uses 'Alert {id}' as fallback."""
        mock_client.get_anomalies.return_value = {}
        mock_client._extract_embedded_data.return_value = [
            {"id": "42", "enabled": True},
        ]

        result = await alert_mgmt._handle_get_anomaly_status(mock_client, {})
        text = _text(result)
        assert "Alert 42" in text
