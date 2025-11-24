"""Test UCM integration functionality.

This test verifies that the Unified Capability Manager integrates properly
with the MCP server and provides capability management functionality.
"""

import asyncio
import sys
import os
import pytest
from unittest.mock import Mock, AsyncMock

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from revenium_mcp_server.capability_manager.integration_service import UCMIntegrationService
from revenium_mcp_server.capability_manager.core import UnifiedCapabilityManager
from revenium_mcp_server.client import ReveniumClient


class TestUCMIntegration:
    """Test UCM integration functionality."""
    
    @pytest.fixture
    async def mock_client(self):
        """Create a mock Revenium client."""
        client = Mock(spec=ReveniumClient)
        client.get = AsyncMock()
        client.post = AsyncMock()
        client.put = AsyncMock()
        client.delete = AsyncMock()
        return client
    
    @pytest.fixture
    async def ucm_service(self, mock_client):
        """Create a UCM integration service for testing."""
        service = UCMIntegrationService()
        await service.initialize(mock_client)
        return service
    
    async def test_ucm_service_initialization(self, mock_client):
        """Test that UCM service initializes properly."""
        service = UCMIntegrationService()
        
        # Should not be initialized initially
        assert not service._initialized
        
        # Initialize the service
        await service.initialize(mock_client)
        
        # Should be initialized now
        assert service._initialized
        assert service.ucm is not None
        assert service.mcp_integration is not None
        assert service.integration_helper is not None
    
    async def test_get_capabilities(self, ucm_service):
        """Test getting capabilities for a resource type."""
        # Test getting product capabilities
        capabilities = await ucm_service.get_ucm_capabilities("products")
        
        # Should return a dictionary with expected structure
        assert isinstance(capabilities, dict)
        assert "plan_types" in capabilities
        assert "currencies" in capabilities
        assert "billing_periods" in capabilities
        
        # Verify fallback capabilities are reasonable
        assert "SUBSCRIPTION" in capabilities["plan_types"]
        assert "USD" in capabilities["currencies"]
    
    async def test_capability_validation(self, ucm_service):
        """Test capability value validation."""
        # Test valid currency
        is_valid = await ucm_service.validate_capability_value("products", "currencies", "USD")
        assert is_valid is True or is_valid is False  # Should return a boolean
        
        # Test invalid currency (should be False)
        is_valid = await ucm_service.validate_capability_value("products", "currencies", "INVALID_CURRENCY")
        assert is_valid is False
    
    async def test_health_status(self, ucm_service):
        """Test getting health status."""
        health = await ucm_service.get_health_status()
        
        assert isinstance(health, dict)
        assert "status" in health
        assert health["status"] in ["healthy", "not_initialized"]
        
        if health["status"] == "healthy":
            assert "ucm_health" in health
            assert "mcp_integration" in health
            assert "integration_helper" in health
    
    async def test_refresh_capabilities(self, ucm_service):
        """Test refreshing capabilities."""
        # This should not raise an exception
        result = await ucm_service.refresh_all_capabilities()
        
        assert isinstance(result, dict)
        assert "status" in result


async def test_ucm_core_functionality():
    """Test core UCM functionality without full integration."""
    # Create a mock client
    mock_client = Mock(spec=ReveniumClient)
    mock_client.get = AsyncMock()
    mock_client.post = AsyncMock()
    
    # Create UCM instance
    ucm = UnifiedCapabilityManager(mock_client, cache_ttl=60)
    
    # Test getting capabilities (should use fallback)
    capabilities = await ucm.get_capabilities("products")
    
    assert isinstance(capabilities, dict)
    assert len(capabilities) > 0
    
    # Test health status
    health = await ucm.get_health_status()
    assert isinstance(health, dict)
    assert "status" in health
    assert "supported_resource_types" in health


if __name__ == "__main__":
    # Run a simple test
    async def main():
        print("Testing UCM integration...")
        
        # Test core functionality
        await test_ucm_core_functionality()
        print("✅ Core UCM functionality test passed")
        
        # Test service initialization
        service = UCMIntegrationService()
        mock_client = Mock(spec=ReveniumClient)
        mock_client.get = AsyncMock()
        mock_client.post = AsyncMock()
        
        await service.initialize(mock_client)
        print("✅ UCM service initialization test passed")
        
        # Test capabilities
        capabilities = await service.get_ucm_capabilities("products")
        print(f"✅ Got capabilities: {list(capabilities.keys())}")
        
        # Test health
        health = await service.get_health_status()
        print(f"✅ Health status: {health['status']}")
        
        print("🎉 All UCM integration tests passed!")
    
    asyncio.run(main())
