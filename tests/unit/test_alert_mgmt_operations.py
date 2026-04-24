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
            mock_client, "create", {"periodDuration": "FIVE_MINUTES"}
        )
        called_data = alert_mgmt.anomaly_manager.create_anomaly.call_args[0][1]
        assert called_data == {"periodDuration": "FIVE_MINUTES"}

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
