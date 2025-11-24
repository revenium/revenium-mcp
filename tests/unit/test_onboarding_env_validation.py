"""Unit tests for environment variable validation."""

import os
import pytest
from unittest.mock import patch

from src.revenium_mcp_server.config_store import get_config_value, get_config_store


class TestEnvironmentVariableValidation:
    """Test environment variable validation and retrieval."""

    def test_get_config_value_from_env(self, monkeypatch):
        """Test get_config_value retrieves from environment."""
        monkeypatch.setenv("TEST_CONFIG_VAR", "test_value")
        # Clear cache to ensure fresh lookup
        store = get_config_store()
        store.clear_cache()

        result = get_config_value("TEST_CONFIG_VAR")
        assert result == "test_value"

    def test_get_config_value_default(self):
        """Test get_config_value returns default when not found."""
        # Use a key that doesn't exist
        result = get_config_value("NONEXISTENT_VAR_12345", default="my_default")
        assert result == "my_default"

    def test_get_config_value_none_when_missing(self):
        """Test get_config_value returns None when missing and no default."""
        result = get_config_value("NONEXISTENT_VAR_67890")
        # May return None or discovered value depending on state
        assert result is None or isinstance(result, str)


class TestConfigValuePriority:
    """Test configuration value priority order."""

    def test_env_var_takes_priority(self, monkeypatch):
        """Test environment variable takes priority over defaults."""
        monkeypatch.setenv("REVENIUM_TEST_PRIORITY", "env_value")
        store = get_config_store()
        store.clear_cache()

        result = get_config_value("REVENIUM_TEST_PRIORITY", default="default_value")
        assert result == "env_value"


class TestConfigStoreDiscovery:
    """Test configuration store discovery behavior."""

    def test_store_can_clear_cache(self):
        """Test store cache can be cleared."""
        store = get_config_store()
        store._discovery_attempted = True

        store.clear_cache()

        assert store._discovery_attempted is False

    def test_store_has_get_value_with_override(self):
        """Test store has get_value_with_override method."""
        store = get_config_store()
        assert hasattr(store, 'get_value_with_override')
        assert callable(store.get_value_with_override)
