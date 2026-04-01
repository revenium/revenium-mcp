"""Unit tests for capability_manager/factory.py.

Tests UCMFactory (creates configured UCM instances) and UCMIntegrationHelper
(replaces hardcoded capabilities with UCM-powered lookups).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.capability_manager.factory import (
    UCMFactory,
    UCMIntegrationHelper,
)


@pytest.fixture
def mock_client():
    """Create a mock ReveniumClient."""
    client = MagicMock()
    client.get = AsyncMock()
    return client


@pytest.fixture
def mock_ucm(mock_client):
    """Create a mock UnifiedCapabilityManager."""
    from src.revenium_mcp_server.capability_manager.core import UnifiedCapabilityManager

    ucm = UnifiedCapabilityManager(mock_client, cache_ttl=60)
    ucm.verifier = MagicMock()
    ucm.discovery = MagicMock()
    return ucm


class TestUCMFactory:
    """Test UCMFactory.create_ucm factory method."""

    @pytest.mark.asyncio
    async def test_create_ucm_with_provided_client(self, mock_client):
        """create_ucm uses the provided client to build a UCM instance."""
        ucm = await UCMFactory.create_ucm(
            client=mock_client, cache_ttl=120, cleanup_interval=60
        )
        assert ucm.client is mock_client

    @pytest.mark.asyncio
    async def test_create_ucm_raises_without_client_or_env(self, monkeypatch):
        """create_ucm raises ValueError when no client and no API key env var."""
        monkeypatch.delenv("REVENIUM_API_KEY", raising=False)
        with pytest.raises(ValueError, match="Failed to create"):
            await UCMFactory.create_ucm()

    @pytest.mark.asyncio
    async def test_create_ucm_uses_env_defaults(self, mock_client, monkeypatch):
        """create_ucm reads cache_ttl and cleanup_interval from environment."""
        monkeypatch.setenv("UCM_CACHE_TTL", "500")
        monkeypatch.setenv("UCM_CLEANUP_INTERVAL", "100")
        ucm = await UCMFactory.create_ucm(client=mock_client)
        assert ucm.cache.ttl == 500

    @pytest.mark.asyncio
    async def test_create_mcp_integration(self, mock_ucm):
        """create_mcp_integration returns an MCPCapabilityIntegration."""
        integration = await UCMFactory.create_mcp_integration(mock_ucm)
        assert integration.ucm is mock_ucm


class TestUCMFactoryCreateDefaultClient:
    """Test _create_default_client environment-based client creation."""

    @pytest.mark.asyncio
    async def test_returns_none_without_api_key(self, monkeypatch):
        """Returns None when REVENIUM_API_KEY is not set."""
        monkeypatch.delenv("REVENIUM_API_KEY", raising=False)
        result = await UCMFactory._create_default_client()
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_without_team_id(self, monkeypatch):
        """Returns None when REVENIUM_TEAM_ID is not set."""
        monkeypatch.setenv("REVENIUM_API_KEY", "test-key")
        monkeypatch.delenv("REVENIUM_TEAM_ID", raising=False)
        with patch(
            "src.revenium_mcp_server.capability_manager.factory.get_config_value",
            return_value=None,
        ):
            result = await UCMFactory._create_default_client()
            assert result is None


class TestUCMIntegrationHelper:
    """Test UCMIntegrationHelper capability replacement and validation."""

    @pytest.mark.asyncio
    async def test_replace_hardcoded_capabilities(self, mock_ucm):
        """replace_hardcoded_capabilities replaces get_capabilities method."""
        helper = UCMIntegrationHelper(mock_ucm)
        tool = MagicMock()
        tool.get_capabilities = lambda: {"old": True}

        # Set up UCM to return new capabilities
        await mock_ucm.cache.set("products", {"new": True})

        await helper.replace_hardcoded_capabilities(tool, "products")

        # The method should now be UCM-powered
        result = await tool.get_capabilities()
        assert result == {"new": True}

    @pytest.mark.asyncio
    async def test_replace_skips_tool_without_method(self, mock_ucm):
        """replace_hardcoded_capabilities is a no-op for tools without get_capabilities."""
        helper = UCMIntegrationHelper(mock_ucm)
        tool = MagicMock(spec=[])  # no get_capabilities attribute
        await helper.replace_hardcoded_capabilities(tool, "products")
        # Should not raise, just warn

    @pytest.mark.asyncio
    async def test_validate_capability_value_from_list(self, mock_ucm):
        """validate_capability_value returns True when value is in the list."""
        helper = UCMIntegrationHelper(mock_ucm)
        await mock_ucm.cache.set("products", {"currencies": ["USD", "EUR"]})
        # Need to mock discovery/verifier to avoid real API calls
        mock_ucm.discovery.discover_capabilities = AsyncMock(return_value={})
        mock_ucm.verifier.verify_capabilities = AsyncMock(return_value={})
        result = await helper.validate_capability_value("products", "currencies", "USD")
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_capability_value_not_in_list(self, mock_ucm):
        """validate_capability_value returns False when value is not in the list."""
        helper = UCMIntegrationHelper(mock_ucm)
        await mock_ucm.cache.set("products", {"currencies": ["USD", "EUR"]})
        mock_ucm.discovery.discover_capabilities = AsyncMock(return_value={})
        mock_ucm.verifier.verify_capabilities = AsyncMock(return_value={})
        result = await helper.validate_capability_value("products", "currencies", "XYZ")
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_metering_provider(self, mock_ucm):
        """validate_capability_value handles metering provider_summary structure."""
        helper = UCMIntegrationHelper(mock_ucm)
        metering_caps = {
            "provider_summary": {"samples": ["openai", "anthropic"]},
        }
        await mock_ucm.cache.set("metering", metering_caps)
        mock_ucm.discovery.discover_capabilities = AsyncMock(return_value={})
        mock_ucm.verifier.verify_capabilities = AsyncMock(return_value={})
        result = await helper.validate_capability_value("metering", "providers", "openai")
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_metering_model_extracts_name(self, mock_ucm):
        """validate_capability_value extracts model name from provider/model format."""
        helper = UCMIntegrationHelper(mock_ucm)
        metering_caps = {
            "model_summary": {"samples": ["openai/gpt-4", "anthropic/claude-3"]},
        }
        await mock_ucm.cache.set("metering", metering_caps)
        mock_ucm.discovery.discover_capabilities = AsyncMock(return_value={})
        mock_ucm.verifier.verify_capabilities = AsyncMock(return_value={})
        result = await helper.validate_capability_value("metering", "models", "gpt-4")
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_returns_false_on_error(self, mock_ucm):
        """validate_capability_value returns False when UCM raises."""
        helper = UCMIntegrationHelper(mock_ucm)
        mock_ucm.discovery.discover_capabilities = AsyncMock(
            side_effect=RuntimeError("broken")
        )
        mock_ucm.verifier.verify_capabilities = AsyncMock(
            side_effect=RuntimeError("broken")
        )
        # Clear cache so it tries API
        await mock_ucm.cache.clear()
        result = await helper.validate_capability_value("products", "currencies", "USD")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_valid_values_returns_list(self, mock_ucm):
        """get_valid_values returns the list of values for a capability."""
        helper = UCMIntegrationHelper(mock_ucm)
        await mock_ucm.cache.set("products", {"currencies": ["USD", "EUR"]})
        mock_ucm.discovery.discover_capabilities = AsyncMock(return_value={})
        mock_ucm.verifier.verify_capabilities = AsyncMock(return_value={})
        result = await helper.get_valid_values("products", "currencies")
        assert result == ["USD", "EUR"]

    @pytest.mark.asyncio
    async def test_get_valid_values_returns_dict_keys(self, mock_ucm):
        """get_valid_values returns keys when capability is a dict."""
        helper = UCMIntegrationHelper(mock_ucm)
        await mock_ucm.cache.set("products", {"plans": {"basic": {}, "pro": {}}})
        mock_ucm.discovery.discover_capabilities = AsyncMock(return_value={})
        mock_ucm.verifier.verify_capabilities = AsyncMock(return_value={})
        result = await helper.get_valid_values("products", "plans")
        assert set(result) == {"basic", "pro"}

    @pytest.mark.asyncio
    async def test_get_valid_values_returns_empty_on_missing(self, mock_ucm):
        """get_valid_values returns empty list when capability doesn't exist."""
        helper = UCMIntegrationHelper(mock_ucm)
        await mock_ucm.cache.set("products", {})
        mock_ucm.discovery.discover_capabilities = AsyncMock(return_value={})
        mock_ucm.verifier.verify_capabilities = AsyncMock(return_value={})
        result = await helper.get_valid_values("products", "nonexistent")
        assert result == []
