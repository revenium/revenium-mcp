"""Unit tests for capability_manager/discovery.py.

Tests the CapabilityDiscovery engine which discovers capabilities
from API metadata and schema definitions for each resource type.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.capability_manager.discovery import CapabilityDiscovery


@pytest.fixture
def mock_client():
    """Create a mock ReveniumClient."""
    client = MagicMock()
    client.get = AsyncMock()
    return client


@pytest.fixture
def discovery(mock_client):
    """Create a CapabilityDiscovery instance."""
    return CapabilityDiscovery(mock_client)


class TestDiscoverCapabilities:
    """Test the main discover_capabilities dispatcher."""

    @pytest.mark.asyncio
    async def test_unknown_resource_type_returns_empty(self, discovery):
        """discover_capabilities returns empty dict for unregistered resource types."""
        result = await discovery.discover_capabilities("nonexistent")
        assert result == {}

    @pytest.mark.asyncio
    async def test_system_capabilities_include_key_sections(self, discovery):
        """System capabilities include MCP server, API, and health sections."""
        result = await discovery.discover_capabilities("system")
        assert "mcp_server" in result
        assert "api_integration" in result
        assert "capabilities" in result
        assert "health_monitoring" in result

    @pytest.mark.asyncio
    async def test_system_capabilities_resource_types_list(self, discovery):
        """System capabilities list all known resource types."""
        result = await discovery.discover_capabilities("system")
        resource_types = result["capabilities"]["resource_types"]
        assert "products" in resource_types
        assert "subscriptions" in resource_types
        assert "metering" in resource_types

    @pytest.mark.asyncio
    async def test_product_capabilities_include_enums(self, discovery):
        """Product capabilities include plan types, currencies, and billing periods."""
        result = await discovery.discover_capabilities("products")
        assert "plan_types" in result
        assert "currencies" in result
        assert "billing_periods" in result
        assert "trial_periods" in result
        assert "payment_sources" in result
        # Values should be lists of strings from enums
        assert isinstance(result["currencies"], list)
        assert len(result["currencies"]) > 0
        assert all(isinstance(v, str) for v in result["currencies"])

    @pytest.mark.asyncio
    async def test_product_capabilities_include_schema(self, discovery):
        """Product capabilities include schema with required fields."""
        result = await discovery.discover_capabilities("products")
        assert "schema" in result
        schema = result["schema"]["product_data"]
        assert "required" in schema
        assert "name" in schema["required"]

    @pytest.mark.asyncio
    async def test_subscription_capabilities_include_states(self, discovery):
        """Subscription capabilities include subscription states and fields."""
        result = await discovery.discover_capabilities("subscriptions")
        assert isinstance(result, dict)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_customer_capabilities(self, discovery):
        """Customer capabilities include subscriber/organization fields."""
        result = await discovery.discover_capabilities("customers")
        assert isinstance(result, dict)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_alert_capabilities(self, discovery):
        """Alert capabilities include alert types and severity levels."""
        result = await discovery.discover_capabilities("alerts")
        assert isinstance(result, dict)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_source_capabilities(self, discovery):
        """Source capabilities include source types."""
        result = await discovery.discover_capabilities("sources")
        assert isinstance(result, dict)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_metering_element_capabilities(self, discovery):
        """Metering element capabilities include element types."""
        result = await discovery.discover_capabilities("metering_elements")
        assert isinstance(result, dict)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_metering_capabilities(self, discovery):
        """Metering capabilities include metric types."""
        result = await discovery.discover_capabilities("metering")
        assert isinstance(result, dict)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_discovery_handles_exception_gracefully(self, discovery):
        """If a discovery method raises, returns empty dict."""
        # Replace a discovery method with one that raises
        discovery.discovery_methods["products"] = AsyncMock(
            side_effect=RuntimeError("broken")
        )
        result = await discovery.discover_capabilities("products")
        assert result == {}


class TestDiscoveryMethodsRegistered:
    """Test that all expected resource types have discovery methods."""

    def test_all_resource_types_have_methods(self, discovery):
        """All standard resource types are registered with discovery methods."""
        expected_types = [
            "system", "products", "subscriptions", "customers",
            "alerts", "sources", "metering_elements", "metering",
        ]
        for rt in expected_types:
            assert rt in discovery.discovery_methods, f"Missing discovery method for {rt}"

    def test_discovery_methods_are_callable(self, discovery):
        """All registered discovery methods are callable."""
        for name, method in discovery.discovery_methods.items():
            assert callable(method), f"Discovery method for {name} is not callable"
