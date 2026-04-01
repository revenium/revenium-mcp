"""Unit tests for EnvironmentVariableValidator (onboarding/env_validation.py)."""

import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.revenium_mcp_server.onboarding.env_validation import (
    EnvironmentVariableValidator,
    EnvironmentVariableStatus,
    ValidationResult,
    get_debug_auto_discovery_env_vars,
    get_all_env_vars_dict,
)


class TestDebugAutoDiscoveryEnvVars:
    """Test environment variable collection in debug_auto_discovery format."""

    def test_masks_api_key(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_API_KEY", "secret_key_123")
        validator = EnvironmentVariableValidator()
        result = validator.get_debug_auto_discovery_env_vars()
        assert result["REVENIUM_API_KEY"] == "SET (hidden)"

    def test_shows_non_sensitive_values(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_TEAM_ID", "team_xyz")
        validator = EnvironmentVariableValidator()
        result = validator.get_debug_auto_discovery_env_vars()
        assert result["REVENIUM_TEAM_ID"] == "team_xyz"

    def test_not_set_for_missing(self, monkeypatch):
        monkeypatch.delenv("REVENIUM_TENANT_ID", raising=False)
        validator = EnvironmentVariableValidator()
        result = validator.get_debug_auto_discovery_env_vars()
        assert result["REVENIUM_TENANT_ID"] == "NOT SET"

    def test_all_six_core_vars_present(self):
        validator = EnvironmentVariableValidator()
        result = validator.get_debug_auto_discovery_env_vars()
        expected_keys = {
            "REVENIUM_API_KEY",
            "REVENIUM_TEAM_ID",
            "REVENIUM_TENANT_ID",
            "REVENIUM_OWNER_ID",
            "REVENIUM_DEFAULT_EMAIL",
            "REVENIUM_BASE_URL",
        }
        assert set(result.keys()) == expected_keys


class TestExtendedEnvVars:
    """Test extended environment variable collection."""

    def test_extended_vars_include_slack(self):
        validator = EnvironmentVariableValidator()
        result = validator.get_extended_env_vars()
        assert "REVENIUM_DEFAULT_SLACK_CONFIG_ID" in result

    def test_get_all_includes_both(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_API_KEY", "key123")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        validator = EnvironmentVariableValidator()
        result = validator.get_all_environment_variables_dict()
        # Should have core + extended vars
        assert "REVENIUM_API_KEY" in result
        assert "LOG_LEVEL" in result


class TestDiscoveredConfiguration:
    """Test discovered configuration methods."""

    @pytest.mark.asyncio
    async def test_discovered_config_returns_values(self):
        validator = EnvironmentVariableValidator()
        with patch(
            "src.revenium_mcp_server.onboarding.env_validation.get_config_value",
            side_effect=lambda key: {
                "REVENIUM_TEAM_ID": "t1",
                "REVENIUM_TENANT_ID": "tn1",
                "REVENIUM_OWNER_ID": "o1",
                "REVENIUM_DEFAULT_EMAIL": "a@b.com",
                "REVENIUM_BASE_URL": "https://api.example.com",
            }.get(key),
        ):
            result = await validator.test_discovered_configuration_debug_auto_discovery()
        assert result["status"] == "success"
        assert result["discovered_count"] == 5
        assert result["values"]["team_id"] == "t1"

    @pytest.mark.asyncio
    async def test_discovered_config_handles_error(self):
        validator = EnvironmentVariableValidator()
        with patch(
            "src.revenium_mcp_server.onboarding.env_validation.get_config_value",
            side_effect=RuntimeError("boom"),
        ):
            result = await validator.test_discovered_configuration_debug_auto_discovery()
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_extended_discovered_config(self):
        validator = EnvironmentVariableValidator()
        with patch(
            "src.revenium_mcp_server.onboarding.env_validation.get_config_value",
            side_effect=lambda key: {
                "REVENIUM_TEAM_ID": "t1",
                "REVENIUM_TENANT_ID": None,
                "REVENIUM_OWNER_ID": None,
                "REVENIUM_DEFAULT_EMAIL": None,
                "REVENIUM_BASE_URL": None,
                "REVENIUM_APP_BASE_URL": "https://app.example.com",
                "REVENIUM_DEFAULT_SLACK_CONFIG_ID": None,
            }.get(key),
        ):
            result = await validator.test_discovered_configuration_extended()
        assert result["status"] == "success"
        assert result["values"]["app_base_url"] == "https://app.example.com"


class TestAuthConfig:
    """Test auth configuration testing."""

    @pytest.mark.asyncio
    async def test_auth_config_with_api_key(self):
        validator = EnvironmentVariableValidator()
        with patch(
            "src.revenium_mcp_server.onboarding.env_validation.get_config_value",
            side_effect=lambda key: {
                "REVENIUM_API_KEY": "test_key_abcdef123456",
                "REVENIUM_TEAM_ID": "team1",
                "REVENIUM_TENANT_ID": None,
                "REVENIUM_BASE_URL": None,
            }.get(key),
        ):
            result = await validator.test_auth_config()
        assert result["status"] == "success"
        assert result["config"]["has_api_key"] is True
        # Warnings for missing optional items
        assert any("TENANT_ID" in w for w in result.get("warnings", []))

    @pytest.mark.asyncio
    async def test_auth_config_missing_api_key(self):
        validator = EnvironmentVariableValidator()
        with patch(
            "src.revenium_mcp_server.onboarding.env_validation.get_config_value",
            return_value=None,
        ):
            result = await validator.test_auth_config()
        assert result["status"] == "error"
        assert "API_KEY" in result["error"]


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_get_debug_auto_discovery_env_vars_function(self):
        result = get_debug_auto_discovery_env_vars()
        assert isinstance(result, dict)
        assert "REVENIUM_API_KEY" in result

    def test_get_all_env_vars_dict_function(self):
        result = get_all_env_vars_dict()
        assert isinstance(result, dict)
        assert len(result) > 6  # More than just core vars
