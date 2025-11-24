"""Integration tests for enhanced input validation in alert tools - Decomposed Version.

This test file has been simplified to work with the decomposed AlertToolsManager.
The original tests were designed for the monolithic AlertManagementTools which
had extensive private method testing. The decomposed version focuses on the
public handle_manage_alerts interface.

For comprehensive validation testing, use the actual MCP server integration tests.
"""

import pytest

from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from mcp.types import TextContent


@pytest.fixture
def alert_tools():
    """Create alert management tools instance."""
    return AlertToolsManager()


@pytest.fixture
def mock_client():
    """Create mock client."""
    from unittest.mock import AsyncMock
    return AsyncMock()


class TestEnhancedValidationIntegration:
    """Test enhanced validation integration with decomposed alert tools."""
    
    @pytest.mark.asyncio
    async def test_validate_action_success(self, alert_tools):
        """Test validation action with valid data."""
        # Valid anomaly data in new API format
        anomaly_data = {
            "label": "Valid Alert",
            "name": "Valid Alert",
            "teamId": "team-123",
            "alertType": "THRESHOLD",
            "metricType": "TOTAL_COST",
            "operatorType": "GREATER_THAN",
            "threshold": 100,
            "isPercentage": False,
            "periodDuration": "ONE_MINUTE",
            "description": "Valid test alert",
            "enabled": True,
            "notificationAddresses": ["test@example.com"],
            "slackConfigurations": [],
            "triggerAfterPersistsDuration": "",
            "filters": []
        }
        
        arguments = {"action": "validate", "anomaly_data": anomaly_data}
        result = await alert_tools.handle_manage_alerts(arguments)
        
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Validation" in result[0].text
    
    @pytest.mark.asyncio
    async def test_validate_action_missing_name(self, alert_tools):
        """Test validation with missing name."""
        anomaly_data = {
            "teamId": "team-123",
            "alertType": "THRESHOLD",
            "metricType": "TOTAL_COST",
            "operatorType": "GREATER_THAN",
            "threshold": 100,
            "notificationAddresses": ["test@example.com"]
            # Missing name/label
        }
        
        arguments = {"action": "validate", "anomaly_data": anomaly_data}
        result = await alert_tools.handle_manage_alerts(arguments)
        
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Validation" in result[0].text
    
    @pytest.mark.asyncio
    async def test_validate_action_invalid_metric(self, alert_tools):
        """Test validation with invalid metric."""
        anomaly_data = {
            "label": "Test Alert",
            "name": "Test Alert",
            "teamId": "team-123",
            "alertType": "THRESHOLD",
            "metricType": "INVALID_METRIC",  # Invalid metric
            "operatorType": "GREATER_THAN",
            "threshold": 100,
            "notificationAddresses": ["test@example.com"]
        }
        
        arguments = {"action": "validate", "anomaly_data": anomaly_data}
        result = await alert_tools.handle_manage_alerts(arguments)
        
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Validation" in result[0].text
    
    @pytest.mark.asyncio
    async def test_create_simple_validation(self, alert_tools):
        """Test create_simple action validation."""
        anomaly_data = {
            "name": "Simple Test Alert",
            "email": "test@example.com",
            "metric": "TOTAL_COST",
            "threshold": 100,
            "check_period_minutes": 1
        }
        
        arguments = {"action": "create_simple", "anomaly_data": anomaly_data}
        result = await alert_tools.handle_manage_alerts(arguments)
        
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Simple Alert Creation" in result[0].text
        assert "Simple Test Alert" in result[0].text


if __name__ == "__main__":
    pytest.main([__file__])
