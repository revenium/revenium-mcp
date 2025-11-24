"""Unit tests for onboarding detection service."""

import pytest
from unittest.mock import AsyncMock, patch

from src.revenium_mcp_server.config_store import (
    ConfigurationStore,
    DiscoveredConfig,
    get_config_store,
)


class TestDiscoveredConfig:
    """Test DiscoveredConfig dataclass."""

    def test_creation_empty(self):
        """Test creating empty config."""
        config = DiscoveredConfig()
        assert config.team_id is None
        assert config.tenant_id is None
        assert config.owner_id is None

    def test_creation_with_values(self):
        """Test creating config with values."""
        config = DiscoveredConfig(
            team_id="team-123",
            tenant_id="tenant-456",
            owner_id="owner-789",
            default_email="test@example.com"
        )
        assert config.team_id == "team-123"
        assert config.tenant_id == "tenant-456"
        assert config.owner_id == "owner-789"
        assert config.default_email == "test@example.com"

    def test_to_dict(self):
        """Test to_dict method excludes None values."""
        config = DiscoveredConfig(
            team_id="team-123",
            tenant_id=None,
            owner_id="owner-789"
        )
        result = config.to_dict()
        assert "team_id" in result
        assert "owner_id" in result
        assert "tenant_id" not in result

    def test_has_required_fields_false(self):
        """Test has_required_fields returns False when missing fields."""
        config = DiscoveredConfig()
        assert config.has_required_fields() is False

    def test_has_required_fields_true(self):
        """Test has_required_fields returns True when all present."""
        config = DiscoveredConfig(
            api_key="key",
            team_id="team",
            tenant_id="tenant",
            owner_id="owner"
        )
        assert config.has_required_fields() is True


class TestConfigurationStore:
    """Test ConfigurationStore functionality."""

    def test_singleton_pattern(self):
        """Test ConfigurationStore is singleton."""
        store1 = ConfigurationStore()
        store2 = ConfigurationStore()
        assert store1 is store2

    def test_get_config_store_function(self):
        """Test get_config_store returns singleton."""
        store = get_config_store()
        assert store is not None
        assert isinstance(store, ConfigurationStore)

    def test_clear_cache(self):
        """Test clear_cache resets discovery state."""
        store = get_config_store()
        # Set some state
        store._discovery_attempted = True
        store._discovered_config = DiscoveredConfig(team_id="test")

        # Clear
        store.clear_cache()

        assert store._discovery_attempted is False
        assert store._discovered_config is None


class TestOnboardingDetectionHelpers:
    """Test helper functions for onboarding detection."""

    def test_discovered_config_dataclass_fields(self):
        """Test DiscoveredConfig has expected fields."""
        config = DiscoveredConfig()
        assert hasattr(config, 'team_id')
        assert hasattr(config, 'tenant_id')
        assert hasattr(config, 'owner_id')
        assert hasattr(config, 'default_email')
        assert hasattr(config, 'default_slack_config_id')
        assert hasattr(config, 'api_key')
        assert hasattr(config, 'base_url')
        assert hasattr(config, 'app_base_url')
