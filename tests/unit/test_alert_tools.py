"""Unit tests for Alert Management Tools.

Tests the AlertManagement class from the decomposed tools module.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from mcp.types import TextContent


@pytest.fixture
def alert_tools():
    """Create alert management tools instance."""
    return AlertManagement()


@pytest.fixture
def alert_tools_with_mock():
    """Create alert management tools with mocked anomaly_manager for update tests."""
    tools = AlertManagement()
    # Mock the anomaly_manager.update_anomaly to capture what gets passed
    tools.anomaly_manager.update_anomaly = AsyncMock(return_value=[
        TextContent(type="text", text="Update successful")
    ])
    return tools


class TestAlertManagement:
    """Test the AlertManagement class."""

    def test_initialization(self, alert_tools):
        """Test that AlertManagement initializes with callable action handler and managers."""
        assert callable(alert_tools.handle_action)
        assert callable(getattr(alert_tools.anomaly_manager, "create_anomaly", None))
        assert callable(getattr(alert_tools.alert_manager, "list_alerts", None))

    @pytest.mark.asyncio
    async def test_get_capabilities(self, alert_tools):
        """Test get_capabilities action."""
        result = await alert_tools.handle_action("get_capabilities", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        # Check for key content (flexible matching)
        text = result[0].text.lower()
        assert "capabilities" in text or "alert" in text

    @pytest.mark.asyncio
    async def test_get_examples(self, alert_tools):
        """Test get_examples action."""
        result = await alert_tools.handle_action("get_examples", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        # Check for example content
        text = result[0].text.lower()
        assert "example" in text or "create" in text

    @pytest.mark.asyncio
    async def test_validate_action(self, alert_tools):
        """Test validate action with valid data."""
        arguments = {
            "anomaly_data": {
                "name": "Test Alert",
                "metricType": "TOTAL_COST",
                "operatorType": "GREATER_THAN",
                "threshold": 100,
                "notificationAddresses": ["test@example.com"]
            }
        }
        result = await alert_tools.handle_action("validate", arguments)

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_unknown_action_raises_error(self, alert_tools):
        """Test that unknown action raises an error."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        with pytest.raises(ToolError) as exc_info:
            await alert_tools.handle_action("completely_invalid_action_xyz", {})

        assert "unknown action" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_create_simple_preview(self, alert_tools):
        """Test create_simple action in preview mode."""
        arguments = {
            "anomaly_data": {
                "name": "Test Simple Alert",
                "email": "test@example.com",
                "metric": "TOTAL_COST",
                "threshold": 50,
                "check_period_minutes": 1
            },
            "dry_run": True
        }
        result = await alert_tools.handle_action("create_simple", arguments)

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)


class TestAlertUpdateFlexibleParams:
    """Test flexible parameter handling for alert updates (P2 Enhancement).

    Tests the three parameter styles supported:
    1. Direct params: update(anomaly_id='123', name='New', threshold=100)
    2. JSON object: update(anomaly_id='123', anomaly_data={'name': 'New'})
    3. Hybrid mode: Direct params take precedence over anomaly_data
    """

    # =========================================================================
    # ERROR HANDLING TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_update_missing_anomaly_id_error(self, alert_tools):
        """Test that update without anomaly_id returns appropriate error."""
        result = await alert_tools.handle_action("update", {
            "anomaly_data": {"threshold": 200}
        })

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        text = result[0].text.lower()
        assert "anomaly_id" in text or "missing" in text

    @pytest.mark.asyncio
    async def test_update_missing_update_data_error(self, alert_tools):
        """Test that update without any update data returns helpful error."""
        result = await alert_tools.handle_action("update", {
            "anomaly_id": "test_alert_123"
        })

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        text = result[0].text.lower()
        # Should mention the flexible parameter options
        assert "update" in text or "param" in text or "data" in text

    @pytest.mark.asyncio
    async def test_update_error_shows_all_updatable_fields(self, alert_tools):
        """Test that update error message shows expanded updatable fields list."""
        result = await alert_tools.handle_action("update", {
            "anomaly_id": "test_alert_123"
        })

        assert len(result) >= 1
        text = result[0].text

        # Should include expanded updatable fields from P2 enhancement
        expected_fields = ["name", "threshold", "enabled", "description", "tags", "metricType"]
        fields_found = sum(1 for field in expected_fields if field in text)
        assert fields_found >= 3, f"Expected at least 3 updatable fields in error message, found {fields_found}"

    @pytest.mark.asyncio
    async def test_update_invalid_anomaly_data_type_error(self, alert_tools):
        """Test that non-dict anomaly_data returns type error."""
        result = await alert_tools.handle_action("update", {
            "anomaly_id": "test_alert_123",
            "anomaly_data": "not a dict"
        })

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        text = result[0].text.lower()
        assert "dict" in text or "object" in text or "type" in text

    # =========================================================================
    # POSITIVE TESTS - Verify parameter merging logic works correctly
    # =========================================================================

    @pytest.mark.asyncio
    async def test_update_with_direct_params_only(self, alert_tools_with_mock):
        """Test update using only direct parameters (Style 1)."""
        result = await alert_tools_with_mock.handle_action("update", {
            "anomaly_id": "alert_123",
            "name": "Updated Alert Name",
            "threshold": 500
        })

        # Verify the mock was called
        alert_tools_with_mock.anomaly_manager.update_anomaly.assert_called_once()

        # Get the call arguments
        call_args = alert_tools_with_mock.anomaly_manager.update_anomaly.call_args
        _, kwargs = call_args if call_args.kwargs else (call_args[0], {})
        passed_anomaly_id = call_args[0][1] if len(call_args[0]) > 1 else kwargs.get('anomaly_id')
        passed_data = call_args[0][2] if len(call_args[0]) > 2 else kwargs.get('anomaly_data', kwargs)

        assert passed_anomaly_id == "alert_123"
        assert passed_data.get("name") == "Updated Alert Name"
        assert passed_data.get("threshold") == 500

    @pytest.mark.asyncio
    async def test_update_with_anomaly_data_only(self, alert_tools_with_mock):
        """Test update using only anomaly_data object (Style 2)."""
        result = await alert_tools_with_mock.handle_action("update", {
            "anomaly_id": "alert_456",
            "anomaly_data": {
                "name": "JSON Style Update",
                "enabled": False,
                "description": "Updated via anomaly_data"
            }
        })

        # Verify the mock was called
        alert_tools_with_mock.anomaly_manager.update_anomaly.assert_called_once()

        # Get the call arguments
        call_args = alert_tools_with_mock.anomaly_manager.update_anomaly.call_args
        passed_anomaly_id = call_args[0][1]
        passed_data = call_args[0][2]

        assert passed_anomaly_id == "alert_456"
        assert passed_data.get("name") == "JSON Style Update"
        assert passed_data.get("enabled") is False
        assert passed_data.get("description") == "Updated via anomaly_data"

    @pytest.mark.asyncio
    async def test_update_hybrid_mode_direct_params_override(self, alert_tools_with_mock):
        """Test hybrid mode where direct params override anomaly_data (Style 3)."""
        result = await alert_tools_with_mock.handle_action("update", {
            "anomaly_id": "alert_789",
            "anomaly_data": {
                "name": "Base Name",
                "threshold": 100,
                "description": "From anomaly_data"
            },
            # Direct params should override
            "threshold": 999,
            "tags": ["high-priority"]
        })

        # Verify the mock was called
        alert_tools_with_mock.anomaly_manager.update_anomaly.assert_called_once()

        # Get the call arguments
        call_args = alert_tools_with_mock.anomaly_manager.update_anomaly.call_args
        passed_anomaly_id = call_args[0][1]
        passed_data = call_args[0][2]

        assert passed_anomaly_id == "alert_789"
        # Direct param should override anomaly_data
        assert passed_data.get("threshold") == 999, "Direct param should override anomaly_data"
        # anomaly_data values should be preserved when no direct param
        assert passed_data.get("name") == "Base Name", "anomaly_data value should be preserved"
        assert passed_data.get("description") == "From anomaly_data"
        # Direct param that wasn't in anomaly_data should be added
        assert passed_data.get("tags") == ["high-priority"]

    @pytest.mark.asyncio
    async def test_update_with_new_p2_fields(self, alert_tools_with_mock):
        """Test update with fields added in P2 enhancement."""
        result = await alert_tools_with_mock.handle_action("update", {
            "anomaly_id": "alert_p2",
            "description": "P2 field test",
            "tags": ["test", "p2"],
            "metricType": "TOTAL_COST",
            "period": "HOUR",
            "triggerAfterPersistsDuration": "PT5M"
        })

        # Verify the mock was called
        alert_tools_with_mock.anomaly_manager.update_anomaly.assert_called_once()

        # Get the call arguments
        call_args = alert_tools_with_mock.anomaly_manager.update_anomaly.call_args
        passed_data = call_args[0][2]

        # All P2 fields should be passed through
        assert passed_data.get("description") == "P2 field test"
        assert passed_data.get("tags") == ["test", "p2"]
        assert passed_data.get("metricType") == "TOTAL_COST"
        assert passed_data.get("period") == "HOUR"
        assert passed_data.get("triggerAfterPersistsDuration") == "PT5M"

    @pytest.mark.asyncio
    async def test_update_ignores_non_updatable_fields(self, alert_tools_with_mock):
        """Test that fields not in updatable_fields list are ignored."""
        result = await alert_tools_with_mock.handle_action("update", {
            "anomaly_id": "alert_filter",
            "name": "Valid Field",
            "invalid_field": "Should be ignored",
            "another_invalid": 123
        })

        # Verify the mock was called
        alert_tools_with_mock.anomaly_manager.update_anomaly.assert_called_once()

        # Get the call arguments
        call_args = alert_tools_with_mock.anomaly_manager.update_anomaly.call_args
        passed_data = call_args[0][2]

        # Valid field should be present
        assert passed_data.get("name") == "Valid Field"
        # Invalid fields from direct params should NOT be present
        assert "invalid_field" not in passed_data
        assert "another_invalid" not in passed_data


class TestAlertManagementIntegration:
    """Integration-style tests for AlertManagement."""

    @pytest.mark.asyncio
    async def test_workflow_capabilities_then_examples(self, alert_tools):
        """Test getting capabilities and then examples."""
        # Get capabilities
        cap_result = await alert_tools.handle_action("get_capabilities", {})
        assert len(cap_result) >= 1
        assert isinstance(cap_result[0], TextContent)

        # Get examples
        examples_result = await alert_tools.handle_action("get_examples", {})
        assert len(examples_result) >= 1
        assert isinstance(examples_result[0], TextContent)
