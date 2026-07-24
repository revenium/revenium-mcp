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


# ===========================================================================
# BACK-1136 — periodDuration accepted as flat kwarg on create/update
# ===========================================================================

class TestPeriodDurationFlatKwarg:
    """Regression for BACK-1136 — periodDuration is documented in get_examples
    but the MCP signature previously omitted it, so the FastMCP-generated
    schema rejected callers that passed it as a top-level kwarg with
    extra_forbidden. The fix exposes it as a signature parameter and threads
    it into anomaly_data on create + the updatable_fields list on update."""

    @pytest.mark.asyncio
    async def test_create_injects_flat_period_duration_into_empty_anomaly_data(
        self, alert_mgmt, mock_client
    ):
        """A flat periodDuration with no anomaly_data wraps into a dict and
        reaches anomaly_manager.create_anomaly."""
        alert_mgmt.anomaly_manager.create_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="created")]
        )
        await alert_mgmt._handle_anomaly_operations(
            mock_client, "create", {"periodDuration": "FIFTEEN_MINUTES"}
        )
        called_data = alert_mgmt.anomaly_manager.create_anomaly.call_args[0][1]
        assert called_data == {"periodDuration": "FIFTEEN_MINUTES"}

    @pytest.mark.asyncio
    async def test_create_merges_flat_period_duration_when_anomaly_data_lacks_it(
        self, alert_mgmt, mock_client
    ):
        """A flat periodDuration is added to anomaly_data when not nested."""
        alert_mgmt.anomaly_manager.create_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="created")]
        )
        await alert_mgmt._handle_anomaly_operations(
            mock_client,
            "create",
            {
                "anomaly_data": {"name": "Spike", "alertType": "THRESHOLD"},
                "periodDuration": "FIFTEEN_MINUTES",
            },
        )
        called_data = alert_mgmt.anomaly_manager.create_anomaly.call_args[0][1]
        assert called_data["periodDuration"] == "FIFTEEN_MINUTES"
        assert called_data["name"] == "Spike"

    @pytest.mark.asyncio
    async def test_create_does_not_overwrite_nested_period_duration(
        self, alert_mgmt, mock_client
    ):
        """Nested periodDuration wins over flat kwarg (explicit > implicit)."""
        alert_mgmt.anomaly_manager.create_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="created")]
        )
        await alert_mgmt._handle_anomaly_operations(
            mock_client,
            "create",
            {
                "anomaly_data": {"name": "Spike", "periodDuration": "ONE_HOUR"},
                "periodDuration": "FIVE_MINUTES",
            },
        )
        called_data = alert_mgmt.anomaly_manager.create_anomaly.call_args[0][1]
        assert called_data["periodDuration"] == "ONE_HOUR"

    @pytest.mark.asyncio
    async def test_update_threads_flat_period_duration_through_direct_params(
        self, alert_mgmt, mock_client
    ):
        """periodDuration is part of updatable_fields and reaches update_anomaly."""
        alert_mgmt.anomaly_manager.update_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="updated")]
        )
        await alert_mgmt._handle_anomaly_operations(
            mock_client,
            "update",
            {"anomaly_id": "anom_42", "periodDuration": "MONTHLY"},
        )
        called_id = alert_mgmt.anomaly_manager.update_anomaly.call_args[0][1]
        called_data = alert_mgmt.anomaly_manager.update_anomaly.call_args[0][2]
        assert called_id == "anom_42"
        assert called_data["periodDuration"] == "MONTHLY"


class TestTriggerAfterPersistsDurationFlatKwarg:
    """Parallel regression to TestPeriodDurationFlatKwarg: triggerAfterPersistsDuration
    is exposed as a top-level kwarg and documented in get_examples payloads, so a
    caller who passes it flat on create must have it threaded into anomaly_data
    rather than silently dropped."""

    @pytest.mark.asyncio
    async def test_create_injects_flat_trigger_into_empty_anomaly_data(
        self, alert_mgmt, mock_client
    ):
        """A flat triggerAfterPersistsDuration with no anomaly_data wraps into a dict."""
        alert_mgmt.anomaly_manager.create_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="created")]
        )
        await alert_mgmt._handle_anomaly_operations(
            mock_client, "create", {"triggerAfterPersistsDuration": "FIFTEEN_MINUTES"}
        )
        called_data = alert_mgmt.anomaly_manager.create_anomaly.call_args[0][1]
        assert called_data == {"triggerAfterPersistsDuration": "FIFTEEN_MINUTES"}

    @pytest.mark.asyncio
    async def test_create_merges_flat_trigger_when_anomaly_data_lacks_it(
        self, alert_mgmt, mock_client
    ):
        """A flat triggerAfterPersistsDuration is added to anomaly_data when not nested."""
        alert_mgmt.anomaly_manager.create_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="created")]
        )
        await alert_mgmt._handle_anomaly_operations(
            mock_client,
            "create",
            {
                "anomaly_data": {"name": "Spike", "alertType": "THRESHOLD"},
                "triggerAfterPersistsDuration": "FIFTEEN_MINUTES",
            },
        )
        called_data = alert_mgmt.anomaly_manager.create_anomaly.call_args[0][1]
        assert called_data["triggerAfterPersistsDuration"] == "FIFTEEN_MINUTES"
        assert called_data["name"] == "Spike"

    @pytest.mark.asyncio
    async def test_create_does_not_overwrite_nested_trigger(
        self, alert_mgmt, mock_client
    ):
        """Nested triggerAfterPersistsDuration wins over flat kwarg (explicit > implicit)."""
        alert_mgmt.anomaly_manager.create_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="created")]
        )
        await alert_mgmt._handle_anomaly_operations(
            mock_client,
            "create",
            {
                "anomaly_data": {
                    "name": "Spike",
                    "triggerAfterPersistsDuration": "ONE_HOUR",
                },
                "triggerAfterPersistsDuration": "FIVE_MINUTES",
            },
        )
        called_data = alert_mgmt.anomaly_manager.create_anomaly.call_args[0][1]
        assert called_data["triggerAfterPersistsDuration"] == "ONE_HOUR"


class TestFlatKwargInjectionPreservesFalsyValues:
    """Regression for code-review feedback (PR #150): the injection guard must
    use `is not None` (not truthiness) so falsy-but-explicitly-passed values
    like "" reach the backend rather than being silently dropped at the MCP
    layer. The backend is the correct place to reject semantically invalid
    durations — silently dropping them masks the caller's intent."""

    @pytest.mark.asyncio
    async def test_create_forwards_explicit_empty_string_period_duration(
        self, alert_mgmt, mock_client
    ):
        """An explicit periodDuration='' is forwarded, not dropped."""
        alert_mgmt.anomaly_manager.create_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="created")]
        )
        await alert_mgmt._handle_anomaly_operations(
            mock_client,
            "create",
            {
                "anomaly_data": {"name": "Spike"},
                "periodDuration": "",
            },
        )
        called_data = alert_mgmt.anomaly_manager.create_anomaly.call_args[0][1]
        assert "periodDuration" in called_data
        assert called_data["periodDuration"] == ""

    @pytest.mark.asyncio
    async def test_create_forwards_explicit_empty_string_trigger(
        self, alert_mgmt, mock_client
    ):
        """An explicit triggerAfterPersistsDuration='' is forwarded, not dropped."""
        alert_mgmt.anomaly_manager.create_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="created")]
        )
        await alert_mgmt._handle_anomaly_operations(
            mock_client,
            "create",
            {
                "anomaly_data": {"name": "Spike"},
                "triggerAfterPersistsDuration": "",
            },
        )
        called_data = alert_mgmt.anomaly_manager.create_anomaly.call_args[0][1]
        assert "triggerAfterPersistsDuration" in called_data
        assert called_data["triggerAfterPersistsDuration"] == ""

    @pytest.mark.asyncio
    async def test_create_skips_truly_absent_fields(self, alert_mgmt, mock_client):
        """When neither flat kwarg is passed (key absent or None), neither
        is injected — the loop must distinguish absent from explicitly empty."""
        alert_mgmt.anomaly_manager.create_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="created")]
        )
        await alert_mgmt._handle_anomaly_operations(
            mock_client,
            "create",
            {
                "anomaly_data": {"name": "Spike"},
                "periodDuration": None,
                # triggerAfterPersistsDuration not in dict at all
            },
        )
        called_data = alert_mgmt.anomaly_manager.create_anomaly.call_args[0][1]
        assert "periodDuration" not in called_data
        assert "triggerAfterPersistsDuration" not in called_data
        assert called_data == {"name": "Spike"}


# ===========================================================================
# BACK-1137 — alert_id accepted as alias for anomaly_id
# ===========================================================================

class TestAlertIdAlias:
    """Regression for BACK-1137 — capabilities text references alert_id while
    anomaly handlers require anomaly_id, so callers following the docs hit a
    'missing anomaly_id' error. handle_action now coerces alert_id into
    anomaly_id when anomaly_id is absent, leaving alerts-resource paths
    untouched (they read alert_id directly)."""

    @pytest.mark.asyncio
    async def test_get_anomaly_accepts_alert_id_alias(self, alert_mgmt, mock_client):
        """get with alert_id (no anomaly_id) reaches the anomaly handler."""
        alert_mgmt.anomaly_manager.get_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="anomaly")]
        )
        await alert_mgmt.handle_action("get", {"alert_id": "anom_42"})
        called_id = alert_mgmt.anomaly_manager.get_anomaly.call_args[0][1]
        assert called_id == "anom_42"

    @pytest.mark.asyncio
    async def test_anomaly_id_wins_when_both_provided(self, alert_mgmt, mock_client):
        """Explicit anomaly_id is preserved when alert_id is also passed."""
        alert_mgmt.anomaly_manager.get_anomaly = AsyncMock(
            return_value=[TextContent(type="text", text="anomaly")]
        )
        await alert_mgmt.handle_action(
            "get", {"anomaly_id": "anom_real", "alert_id": "anom_alias"}
        )
        called_id = alert_mgmt.anomaly_manager.get_anomaly.call_args[0][1]
        assert called_id == "anom_real"

    @pytest.mark.asyncio
    async def test_explicit_falsy_anomaly_id_is_not_overwritten_by_alias(
        self, alert_mgmt, mock_client
    ):
        """anomaly_id="" must still win over alert_id (PR #151 review): the
        alias guard now uses key-presence, not truthiness, so an explicitly-
        passed falsy value reaches the handler unchanged rather than being
        silently overwritten by alert_id. The downstream handler may still
        reject the empty value — the contract enforced here is only that
        the dispatch-level coercion does not mutate arguments when
        anomaly_id is present (even if falsy).
        """
        captured_args: dict = {}

        async def capture_args(client, arguments):  # noqa: ARG001
            captured_args.update(arguments)
            return [TextContent(type="text", text="captured")]

        with patch.object(
            alert_mgmt, "_handle_get", new=AsyncMock(side_effect=capture_args),
        ):
            await alert_mgmt.handle_action(
                "get", {"anomaly_id": "", "alert_id": "anom_alias"}
            )

        # The dispatch must not have copied alert_id over the explicit
        # (falsy) anomaly_id — the empty value is preserved.
        assert captured_args["anomaly_id"] == ""
        assert captured_args["alert_id"] == "anom_alias"

    @pytest.mark.asyncio
    async def test_alerts_resource_get_still_uses_alert_id(self, alert_mgmt, mock_client):
        """resource_type=alerts paths read alert_id directly; the alias does
        not break them or shadow alert_id with a stale anomaly_id."""
        alert_mgmt.alert_manager.get_alert = AsyncMock(
            return_value=[TextContent(type="text", text="alert event")]
        )
        await alert_mgmt.handle_action(
            "get", {"resource_type": "alerts", "alert_id": "evt_123"}
        )
        called_id = alert_mgmt.alert_manager.get_alert.call_args[0][1]
        assert called_id == "evt_123"

    @pytest.mark.asyncio
    async def test_disable_anomaly_accepts_alert_id_alias(self, alert_mgmt, mock_client):
        """The standalone disable handler also benefits from the alias since
        the coercion happens at handle_action dispatch."""
        mock_client.get_anomaly_by_id.return_value = {
            "id": "anom_99",
            "name": "X",
            "enabled": True,
        }
        mock_client.update_anomaly.return_value = {
            "id": "anom_99",
            "name": "X",
            "enabled": False,
        }
        result = await alert_mgmt.handle_action("disable", {"alert_id": "anom_99"})
        text = _text(result)
        assert "anom_99" in text


from tests.unit._helpers_no_framework_leak import assert_no_framework_leak


class TestAlertListPaginationValidation:
    """BACK-1270 / item #5 — Pydantic leak guard on manage_alerts list."""

    @pytest.mark.asyncio
    async def test_list_alerts_rejects_float_size_with_structured_error(
        self, alert_mgmt, mock_client
    ):
        with pytest.raises(ToolError) as exc:
            await alert_mgmt._handle_list(
                mock_client, {"resource_type": "alerts", "page": 0, "size": 3.7}
            )
        assert exc.value.field == "size"
        assert_no_framework_leak(exc.value.message)

    @pytest.mark.asyncio
    async def test_list_anomalies_rejects_float_size_with_structured_error(
        self, alert_mgmt, mock_client
    ):
        with pytest.raises(ToolError) as exc:
            await alert_mgmt._handle_anomaly_operations(
                mock_client, "list", {"page": 0, "size": 3.7}
            )
        assert exc.value.field == "size"
        assert_no_framework_leak(exc.value.message)


class TestDryRunLiveParity:
    """dry_run must accept-or-reject exactly like live create — a false-green
    dry-run tells the caller a create will succeed when it will 400."""

    @pytest.mark.asyncio
    async def test_dry_run_rejects_payload_live_would_reject(self):
        """The audit probe: direct-format payload missing operatorType (and
        the rest of the direct-API quartet) passed dry-run but 400'd live."""
        from src.revenium_mcp_server.tools_decomposed.alert_management import (
            AlertManagement,
        )

        tools = AlertManagement()
        client = MagicMock()
        tools.get_client = AsyncMock(return_value=client)
        result = await tools.handle_action(
            "create",
            {
                "dry_run": True,
                "anomaly_data": {"name": "Spike", "alertType": "THRESHOLD"},
            },
        )
        text = result[0].text
        assert "ready for creation" not in text.lower()
        assert "detection_rules or direct api format" in text.lower() or "error" in text.lower()

    @pytest.mark.asyncio
    async def test_dry_run_accepts_payload_live_would_accept(self):
        from src.revenium_mcp_server.tools_decomposed.alert_management import (
            AlertManagement,
        )

        tools = AlertManagement()
        client = MagicMock()
        tools.get_client = AsyncMock(return_value=client)
        result = await tools.handle_action(
            "create",
            {
                "dry_run": True,
                "anomaly_data": {
                    "name": "Spike",
                    "alertType": "THRESHOLD",
                    "metricType": "TOTAL_COST",
                    "operatorType": "GREATER_THAN",
                    "threshold": 100,
                },
            },
        )
        text = result[0].text
        assert "DRY RUN" in text
        assert "valid" in text.lower()

    @pytest.mark.asyncio
    async def test_dry_run_lets_unexpected_errors_propagate(self):
        """Only validation failures become 'Dry Run Validation Failed' — a
        programming error inside the validator must reach error monitoring."""
        from unittest.mock import patch as _patch
        from src.revenium_mcp_server.tools_decomposed.alert_management import (
            AlertManagement,
        )

        tools = AlertManagement()
        client = MagicMock()
        with _patch.object(
            tools.anomaly_manager, "validate_anomaly_payload",
            side_effect=RuntimeError("validator bug"),
        ):
            with pytest.raises(RuntimeError):
                await tools._handle_create(
                    client,
                    {"resource_type": "anomalies", "dry_run": True, "anomaly_data": {"name": "x"}},
                )

    @pytest.mark.asyncio
    async def test_dry_run_accepts_documented_flat_payload(self):
        """dry_run must see the SAME assembled payload live create sees — the
        flat-field merge applies to both, or a documented flat payload
        false-fails in preview while succeeding live."""
        from src.revenium_mcp_server.tools_decomposed.alert_management import (
            AlertManagement,
        )

        tools = AlertManagement()
        client = MagicMock()
        tools.get_client = AsyncMock(return_value=client)
        result = await tools.handle_action(
            "create",
            {
                "dry_run": True,
                "name": "High Cost Alert",
                "alertType": "THRESHOLD",
                "metricType": "TOTAL_COST",
                "threshold": 100,
                "periodDuration": "FIFTEEN_MINUTES",
                "email": "alerts@company.com",
            },
        )
        text = result[0].text
        assert "Dry Run Successful" in text or "DRY RUN" in text
        assert "Missing anomaly_data" not in text

    @pytest.mark.asyncio
    async def test_dry_run_rejects_banned_period_like_live(self):
        from src.revenium_mcp_server.tools_decomposed.alert_management import (
            AlertManagement,
        )
        from src.revenium_mcp_server.common.error_handling import ToolError

        tools = AlertManagement()
        client = MagicMock()
        tools.get_client = AsyncMock(return_value=client)
        with pytest.raises(ToolError) as exc_info:
            await tools.handle_action(
                "create",
                {
                    "dry_run": True,
                    "name": "Spike",
                    "alertType": "THRESHOLD",
                    "metricType": "TOTAL_COST",
                    "threshold": 100,
                    "periodDuration": "FIVE_MINUTES",
                    "email": "a@b.io",
                },
            )
        assert "FIFTEEN_MINUTES" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Part C: _handle_reset_budget (budget accumulation reset)
# ---------------------------------------------------------------------------

class TestHandleResetBudget:
    """Tests for _handle_reset_budget."""

    @pytest.mark.asyncio
    async def test_reset_budget_success(self, alert_mgmt, mock_client):
        """Successful reset renders the anomaly id and reset confirmation."""
        mock_client.reset_anomaly_budget.return_value = {
            "anomalyId": "a1",
            "currentAccumulation": 0,
        }
        result = await alert_mgmt._handle_reset_budget(mock_client, {"anomaly_id": "a1"})
        text = _text(result)
        assert "a1" in text
        assert "reset" in text.lower()
        mock_client.reset_anomaly_budget.assert_awaited_once_with("a1")

    @pytest.mark.asyncio
    async def test_reset_budget_missing_id_raises(self, alert_mgmt, mock_client):
        with pytest.raises(ToolError):
            await alert_mgmt._handle_reset_budget(mock_client, {})

    @pytest.mark.asyncio
    async def test_reset_budget_404_translates_to_not_found(self, alert_mgmt, mock_client):
        from src.revenium_mcp_server.client import ReveniumAPIError

        mock_client.reset_anomaly_budget.side_effect = ReveniumAPIError(
            "not found", status_code=404
        )
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_reset_budget(mock_client, {"anomaly_id": "missing"})
        assert "missing" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_reset_budget_422_explains_cumulative_usage_requirement(
        self, alert_mgmt, mock_client
    ):
        """422 means the anomaly is not a CUMULATIVE_USAGE budget alert."""
        from src.revenium_mcp_server.client import ReveniumAPIError

        mock_client.reset_anomaly_budget.side_effect = ReveniumAPIError(
            "not cumulative", status_code=422
        )
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_reset_budget(mock_client, {"anomaly_id": "a1"})
        assert "CUMULATIVE_USAGE" in str(exc_info.value.message) or any(
            "CUMULATIVE_USAGE" in s for s in exc_info.value.suggestions
        )

    @pytest.mark.asyncio
    async def test_reset_budget_routed_via_handle_action_with_alert_id_alias(
        self, alert_mgmt, mock_client
    ):
        """handle_action routes reset_budget and honors the alert_id alias."""
        mock_client.reset_anomaly_budget.return_value = {"anomalyId": "a9"}
        result = await alert_mgmt.handle_action("reset_budget", {"alert_id": "a9"})
        text = _text(result)
        assert "a9" in text
        mock_client.reset_anomaly_budget.assert_awaited_once_with("a9")

    @pytest.mark.asyncio
    async def test_reset_budget_in_supported_actions(self, alert_mgmt):
        actions = await alert_mgmt._get_supported_actions()
        assert "reset_budget" in actions


# ---------------------------------------------------------------------------
# BACK-2374 Part D: get_budget_portfolio (tenant-wide budget-progress read)
# ---------------------------------------------------------------------------

class TestHandleGetBudgetPortfolio:
    """Tests for _handle_get_budget_portfolio."""

    @staticmethod
    def _entry(**over):
        # Real dev payload shape: portfolio/bulk items carry the hashed id
        # under alertId (anomalyId only exists on the single per-anomaly
        # endpoint, as the numeric internal id).
        base = {
            "alertId": "a1",
            "name": "Monthly Budget",
            "metricType": "TOTAL_COST",
            "threshold": 1000,
            "currentValue": 250,
            "percentUsed": 25,
            "aheadBehindVsLinear": {"status": "ON_TRACK"},
        }
        base.update(over)
        return base

    @pytest.mark.asyncio
    async def test_portfolio_renders_entry_fields(self, alert_mgmt, mock_client):
        mock_client.get_budget_portfolio = AsyncMock(return_value={
            "_embedded": {"budgetProgressList": [self._entry()]},
            "page": {"number": 0, "size": 20, "totalElements": 1, "totalPages": 1},
        })
        mock_client._extract_embedded_data = MagicMock(return_value=[self._entry()])
        mock_client._extract_pagination_info = MagicMock(
            return_value={"number": 0, "size": 20, "totalElements": 1, "totalPages": 1}
        )
        result = await alert_mgmt._handle_get_budget_portfolio(mock_client, {})
        text = _text(result)
        assert "Monthly Budget" in text
        assert "a1" in text
        assert "TOTAL_COST" in text
        assert "ON_TRACK" in text
        assert "25" in text  # percentUsed

    @pytest.mark.asyncio
    async def test_portfolio_empty_state(self, alert_mgmt, mock_client):
        mock_client.get_budget_portfolio = AsyncMock(return_value={"_embedded": {}})
        mock_client._extract_embedded_data = MagicMock(return_value=[])
        mock_client._extract_pagination_info = MagicMock(return_value={})
        result = await alert_mgmt._handle_get_budget_portfolio(mock_client, {})
        text = _text(result)
        assert "no budget alerts" in text.lower()

    @pytest.mark.asyncio
    async def test_portfolio_forwards_pagination_and_filters(self, alert_mgmt, mock_client):
        mock_client.get_budget_portfolio = AsyncMock(return_value={"_embedded": {}})
        mock_client._extract_embedded_data = MagicMock(return_value=[])
        mock_client._extract_pagination_info = MagicMock(return_value={})
        await alert_mgmt._handle_get_budget_portfolio(
            mock_client, {"page": 2, "size": 5, "include_trend": True, "now": "2026-07-01T00:00:00Z"}
        )
        kwargs = mock_client.get_budget_portfolio.call_args.kwargs
        assert kwargs["page"] == 2
        assert kwargs["size"] == 5
        assert kwargs["includeTrend"] is True
        assert kwargs["now"] == "2026-07-01T00:00:00Z"

    @pytest.mark.asyncio
    async def test_portfolio_degrades_entry_without_numeric_fields(self, alert_mgmt, mock_client):
        """An entry missing numeric currentValue/threshold renders 'state
        unavailable', never zeros or a Python None (BACK-2354 precedent)."""
        entry = self._entry(currentValue=None, threshold=None, percentUsed=None)
        mock_client.get_budget_portfolio = AsyncMock(return_value={"_embedded": {}})
        mock_client._extract_embedded_data = MagicMock(return_value=[entry])
        mock_client._extract_pagination_info = MagicMock(return_value={})
        result = await alert_mgmt._handle_get_budget_portfolio(mock_client, {})
        text = _text(result)
        assert "state unavailable" in text.lower()
        assert "None" not in text

    @pytest.mark.asyncio
    async def test_portfolio_routed_via_handle_action(self, alert_mgmt, mock_client):
        mock_client.get_budget_portfolio = AsyncMock(return_value={"_embedded": {}})
        mock_client._extract_embedded_data = MagicMock(return_value=[])
        mock_client._extract_pagination_info = MagicMock(return_value={})
        result = await alert_mgmt.handle_action("get_budget_portfolio", {})
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_portfolio_in_supported_actions(self, alert_mgmt):
        actions = await alert_mgmt._get_supported_actions()
        assert "get_budget_portfolio" in actions


# ---------------------------------------------------------------------------
# BACK-2374 Part E: get_budget_progress (single per-anomaly OR bulk read)
# ---------------------------------------------------------------------------

class TestHandleGetBudgetProgress:
    """Tests for _handle_get_budget_progress (single + bulk paths)."""

    @staticmethod
    def _progress_bulk(**over):
        """Real bulk/portfolio item shape: hashed id under alertId."""
        base = {
            "alertId": "a1",
            "metricType": "TOTAL_COST",
            "threshold": 1000,
            "currentValue": 400,
            "remaining": 600,
            "percentUsed": 40,
            "aheadBehindVsLinear": {"status": "ON_TRACK"},
        }
        base.update(over)
        return base

    @staticmethod
    def _progress(**over):
        base = {
            "anomalyId": "a1",
            "metricType": "TOTAL_COST",
            "threshold": 1000,
            "currentValue": 400,
            "remaining": 600,
            "percentUsed": 40,
            "window": {"start": "2026-07-01", "now": "2026-07-10", "endExpected": "2026-07-31"},
            "aheadBehindVsLinear": {"expectedByNow": 300, "delta": 100, "status": "AHEAD"},
        }
        base.update(over)
        return base

    @pytest.mark.asyncio
    async def test_single_success_uses_per_anomaly_endpoint(self, alert_mgmt, mock_client):
        mock_client.get_anomaly_budget_progress = AsyncMock(return_value=self._progress())
        result = await alert_mgmt._handle_get_budget_progress(mock_client, {"anomaly_id": "a1"})
        text = _text(result)
        assert "a1" in text
        assert "TOTAL_COST" in text
        assert "AHEAD" in text
        mock_client.get_anomaly_budget_progress.assert_awaited_once()
        assert mock_client.get_anomaly_budget_progress.call_args[0][0] == "a1"

    @pytest.mark.asyncio
    async def test_single_labels_with_requested_hashed_id(self, alert_mgmt, mock_client):
        """The per-anomaly payload carries the numeric internal anomalyId
        (live dev evidence: 178302 for hashed id 5jgQQ7); the rendered entry
        must be identifiable by the id the caller passed."""
        mock_client.get_anomaly_budget_progress = AsyncMock(
            return_value=self._progress(anomalyId=178302)
        )
        result = await alert_mgmt._handle_get_budget_progress(
            mock_client, {"anomaly_id": "5jgQQ7"}
        )
        text = _text(result)
        assert "5jgQQ7" in text

    @pytest.mark.asyncio
    async def test_bulk_entries_render_hashed_alert_id(self, alert_mgmt, mock_client):
        """Bulk items carry the hashed id under alertId (not anomalyId) —
        the renderer must not print None (live dev evidence)."""
        mock_client.get_budget_progress_bulk = AsyncMock(
            return_value={"items": [self._progress_bulk(alertId="5jgQQ7")]}
        )
        result = await alert_mgmt._handle_get_budget_progress(
            mock_client, {"anomaly_ids": ["5jgQQ7"]}
        )
        text = _text(result)
        assert "5jgQQ7" in text
        assert "None" not in text

    @pytest.mark.asyncio
    async def test_single_forwards_filters(self, alert_mgmt, mock_client):
        mock_client.get_anomaly_budget_progress = AsyncMock(return_value=self._progress())
        await alert_mgmt._handle_get_budget_progress(
            mock_client, {"anomaly_id": "a1", "include_trend": True, "now": "2026-07-10T00:00:00Z"}
        )
        kwargs = mock_client.get_anomaly_budget_progress.call_args.kwargs
        assert kwargs["includeTrend"] is True
        assert kwargs["now"] == "2026-07-10T00:00:00Z"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [400, 403])
    async def test_single_400_403_translate_to_not_found(self, alert_mgmt, mock_client, status):
        """Live dev evidence: bogus ids 400, deleted ids 403 — GET-by-id has
        no input other than the id, so both mean 'no accessible alert'."""
        from src.revenium_mcp_server.client import ReveniumAPIError

        mock_client.get_anomaly_budget_progress = AsyncMock(
            side_effect=ReveniumAPIError("boom", status_code=status)
        )
        with pytest.raises(ToolError) as exc_info:
            await alert_mgmt._handle_get_budget_progress(
                mock_client, {"anomaly_id": "zZzBogus9"}
            )
        assert "zZzBogus9" in str(exc_info.value.message)

    async def test_single_404_translates_to_not_found(self, alert_mgmt, mock_client):
        from src.revenium_mcp_server.client import ReveniumAPIError
        mock_client.get_anomaly_budget_progress = AsyncMock(
            side_effect=ReveniumAPIError("not found", status_code=404)
        )
        with pytest.raises(ToolError) as exc:
            await alert_mgmt._handle_get_budget_progress(mock_client, {"anomaly_id": "missing"})
        assert "missing" in str(exc.value.message)

    @pytest.mark.asyncio
    async def test_single_422_explains_cumulative_usage_requirement(self, alert_mgmt, mock_client):
        from src.revenium_mcp_server.client import ReveniumAPIError
        mock_client.get_anomaly_budget_progress = AsyncMock(
            side_effect=ReveniumAPIError("not cumulative", status_code=422)
        )
        with pytest.raises(ToolError) as exc:
            await alert_mgmt._handle_get_budget_progress(mock_client, {"anomaly_id": "a1"})
        assert "CUMULATIVE_USAGE" in str(exc.value.message) or any(
            "CUMULATIVE_USAGE" in s for s in exc.value.suggestions
        )

    @pytest.mark.asyncio
    async def test_single_5xx_propagates(self, alert_mgmt, mock_client):
        from src.revenium_mcp_server.client import ReveniumAPIError
        mock_client.get_anomaly_budget_progress = AsyncMock(
            side_effect=ReveniumAPIError("boom", status_code=500)
        )
        with pytest.raises(ReveniumAPIError):
            await alert_mgmt._handle_get_budget_progress(mock_client, {"anomaly_id": "a1"})

    @pytest.mark.asyncio
    async def test_single_via_handle_action_alert_id_alias(self, alert_mgmt, mock_client):
        """alert_id is mapped to anomaly_id by handle_action, so the single
        per-anomaly path is reachable via the alias."""
        mock_client.get_anomaly_budget_progress = AsyncMock(return_value=self._progress(anomalyId=178302))
        result = await alert_mgmt.handle_action("get_budget_progress", {"alert_id": "a9"})
        text = _text(result)
        assert "a9" in text
        assert mock_client.get_anomaly_budget_progress.call_args[0][0] == "a9"

    @pytest.mark.asyncio
    async def test_bulk_forwards_ids_and_renders_each(self, alert_mgmt, mock_client):
        mock_client.get_budget_progress_bulk = AsyncMock(return_value={
            "items": [self._progress_bulk(alertId="a1"), self._progress_bulk(alertId="a2")]
        })
        result = await alert_mgmt._handle_get_budget_progress(
            mock_client, {"anomaly_ids": ["a1", "a2"]}
        )
        text = _text(result)
        assert "a1" in text
        assert "a2" in text
        assert mock_client.get_budget_progress_bulk.call_args[0][0] == ["a1", "a2"]

    @pytest.mark.asyncio
    async def test_bulk_degrades_entry_without_numeric_fields(self, alert_mgmt, mock_client):
        good = self._progress(anomalyId="a1")
        bad = self._progress(anomalyId="a2", currentValue=None, threshold=None, percentUsed=None)
        mock_client.get_budget_progress_bulk = AsyncMock(return_value={"items": [good, bad]})
        result = await alert_mgmt._handle_get_budget_progress(
            mock_client, {"anomaly_ids": ["a1", "a2"]}
        )
        text = _text(result)
        assert "a1" in text
        assert "a2" in text
        assert "state unavailable" in text.lower()
        assert "None" not in text

    @pytest.mark.asyncio
    async def test_requires_exactly_one_of_id_or_ids(self, alert_mgmt, mock_client):
        """Neither anomaly_id nor anomaly_ids -> structured validation error."""
        with pytest.raises(ToolError):
            await alert_mgmt._handle_get_budget_progress(mock_client, {})

    @pytest.mark.asyncio
    async def test_rejects_both_id_and_ids(self, alert_mgmt, mock_client):
        """Both anomaly_id and anomaly_ids -> structured validation error
        (exactly one is required)."""
        with pytest.raises(ToolError):
            await alert_mgmt._handle_get_budget_progress(
                mock_client, {"anomaly_id": "a1", "anomaly_ids": ["a2"]}
            )

    @pytest.mark.asyncio
    async def test_rejects_empty_ids_list(self, alert_mgmt, mock_client):
        """anomaly_ids=[] selects nothing -> structured validation error;
        the bulk endpoint must not be called with an empty ids param."""
        with pytest.raises(ToolError):
            await alert_mgmt._handle_get_budget_progress(mock_client, {"anomaly_ids": []})
        mock_client.get_budget_progress_bulk.assert_not_called()

    @pytest.mark.asyncio
    async def test_progress_in_supported_actions(self, alert_mgmt):
        actions = await alert_mgmt._get_supported_actions()
        assert "get_budget_progress" in actions
