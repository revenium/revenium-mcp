"""Unit tests for Alert Management Tools.

Tests the AlertManagement class from the decomposed tools module.
"""

import pytest
from unittest.mock import AsyncMock

from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from src.revenium_mcp_server.models import AlertType, OperatorType
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
    async def test_get_capabilities_renders_operators_and_alert_types(self, alert_tools):
        """get_capabilities must populate Available Operators and Alert Types from
        the OperatorType / AlertType enums when UCM does not supply them.

        BACK-1113 audit shape — both section headers were rendered with no items
        underneath, leaving callers unable to discover the supported set.
        """
        result = await alert_tools.handle_action("get_capabilities", {})
        text = result[0].text

        assert "## **Available Operators**" in text
        # Drive assertions from the enums directly so new members are covered automatically.
        for op in OperatorType:
            assert f"**{op.value}**" in text, f"Available Operators section missing {op.value}"

        assert "## **Alert Types**" in text
        for at in AlertType:
            assert f"**{at.value}**" in text, f"Alert Types section missing {at.value}"

    @pytest.mark.asyncio
    async def test_build_capabilities_text_falls_back_when_ucm_lists_are_empty(
        self, alert_tools
    ):
        """Empty UCM lists must trigger the enum fallback, not render empty headers."""
        text = await alert_tools._build_enhanced_capabilities_text(
            {"operators": [], "alert_types": []}
        )
        assert "## **Available Operators**" in text
        assert "**GREATER_THAN**" in text
        assert "## **Alert Types**" in text
        assert "**THRESHOLD**" in text

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
        """create_simple with dry_run=True returns a preview and does NOT create."""
        alert_tools.anomaly_manager.create_anomaly = AsyncMock()
        arguments = {
            "name": "Test Simple Alert",
            "email": "test@example.com",
            "metric": "TOTAL_COST",
            "threshold": 50,
            "dry_run": True,
        }

        result = await alert_tools.handle_action("create_simple", arguments)

        # No real create call was made.
        alert_tools.anomaly_manager.create_anomaly.assert_not_called()
        # Response is a single preview envelope, not an error envelope.
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        text = result[0].text
        assert "DRY RUN" in text
        assert "Test Simple Alert" in text
        assert "TOTAL_COST" in text

    @pytest.mark.asyncio
    async def test_create_simple_executes_without_dry_run(self, alert_tools):
        """create_simple without dry_run performs the real create."""
        sentinel = [TextContent(type="text", text="created")]
        alert_tools.anomaly_manager.create_anomaly = AsyncMock(return_value=sentinel)
        arguments = {
            "name": "Real Alert",
            "email": "test@example.com",
            "metric": "TOTAL_COST",
            "threshold": 50,
        }

        result = await alert_tools.handle_action("create_simple", arguments)

        alert_tools.anomaly_manager.create_anomaly.assert_awaited_once()
        assert result == sentinel
        _client, payload = alert_tools.anomaly_manager.create_anomaly.call_args.args
        assert payload["label"] == "Real Alert"
        assert payload["name"] == "Real Alert"
        assert payload["alertType"] == "THRESHOLD"
        assert payload["metricType"] == "TOTAL_COST"
        assert payload["threshold"] == 50.0

    @pytest.mark.asyncio
    @pytest.mark.timeout(15)
    async def test_slack_mixin_fails_closed_without_ctx(self, alert_tools, monkeypatch):
        """In api_key mode with no tenant context, the Slack mixin path must
        fail closed via get_client() rather than building an env client."""
        from src.revenium_mcp_server.auth.claims_middleware import _current_tenant

        monkeypatch.setenv("AUTH_MODE", "api_key")
        token = _current_tenant.set(None)
        try:
            with pytest.raises(PermissionError):
                await alert_tools.prompt_for_slack_addition({})
        finally:
            _current_tenant.reset(token)

    @pytest.mark.asyncio
    @pytest.mark.timeout(15)
    async def test_slack_selection_fails_closed_without_ctx(self, alert_tools, monkeypatch):
        """handle_slack_configuration_selection must fail closed in api_key mode."""
        from src.revenium_mcp_server.auth.claims_middleware import _current_tenant

        monkeypatch.setenv("AUTH_MODE", "api_key")
        token = _current_tenant.set(None)
        try:
            with pytest.raises(PermissionError):
                await alert_tools.handle_slack_configuration_selection()
        finally:
            _current_tenant.reset(token)

    @pytest.mark.asyncio
    @pytest.mark.timeout(15)
    async def test_slack_apply_fails_closed_without_ctx(self, alert_tools, monkeypatch):
        """apply_slack_to_notification_config must fail closed in api_key mode.

        Passes an explicit slack_config_id so the method reaches get_client()
        (it returns early when no slack_config_id can be resolved)."""
        from src.revenium_mcp_server.auth.claims_middleware import _current_tenant

        monkeypatch.setenv("AUTH_MODE", "api_key")
        token = _current_tenant.set(None)
        try:
            with pytest.raises(PermissionError):
                await alert_tools.apply_slack_to_notification_config(
                    {}, slack_config_id="sc_test"
                )
        finally:
            _current_tenant.reset(token)

    @pytest.mark.asyncio
    @pytest.mark.timeout(15)
    async def test_post_alert_prompting_fails_closed_without_ctx(self, alert_tools, monkeypatch):
        """Post-creation Slack prompting must not swallow the mixin's fail-closed
        PermissionError — the broad except must re-raise auth failures."""
        from src.revenium_mcp_server.auth.claims_middleware import _current_tenant

        monkeypatch.setenv("AUTH_MODE", "api_key")
        monkeypatch.setattr(alert_tools, "should_prompt_for_slack", lambda *a, **k: True)
        token = _current_tenant.set(None)
        try:
            with pytest.raises(PermissionError):
                await alert_tools._post_alert_creation_prompting(
                    alert_data={},
                    notification_config={},
                    alert_context={},
                )
        finally:
            _current_tenant.reset(token)


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
