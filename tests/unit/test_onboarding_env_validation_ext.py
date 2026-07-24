"""Unit tests for EnvironmentVariableValidator (onboarding/env_validation.py)."""

import pytest
from unittest.mock import AsyncMock, patch

from src.revenium_mcp_server.onboarding.env_validation import (
    EnvironmentVariableValidator,
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


class TestClerkModeHealth:
    """validate_all_debug_auto_discovery_format must be auth-mode aware (BACK-2184)."""

    def _offline(self, validator):
        """Patch the network probes so the summary computes offline (clerk mode w/o a static key)."""
        return (
            patch.object(
                validator,
                "test_api_connectivity_debug_auto_discovery",
                new=AsyncMock(return_value={"status": "error"}),
            ),
            patch.object(
                validator,
                "test_discovered_configuration_debug_auto_discovery",
                new=AsyncMock(return_value={"status": "error", "discovered_count": 0, "values": {}}),
            ),
            patch.object(
                validator,
                "test_auth_config_debug_auto_discovery",
                new=AsyncMock(return_value={"status": "error"}),
            ),
        )

    @pytest.mark.asyncio
    async def test_clerk_mode_healthy_from_oauth_config(self, monkeypatch):
        monkeypatch.setenv("AUTH_MODE", "clerk")
        monkeypatch.setenv("CLERK_DOMAIN", "clerk.example.com")
        monkeypatch.setenv("CLERK_OAUTH_CLIENT_ID", "client_abc")
        monkeypatch.setenv("CLERK_OAUTH_CLIENT_SECRET", "sk_clerk_test_value")
        monkeypatch.setenv("MCP_SERVER_BASE_URL", "https://mcp.example.com")
        monkeypatch.delenv("REVENIUM_API_KEY", raising=False)
        validator = EnvironmentVariableValidator()
        p1, p2, p3 = self._offline(validator)
        with p1, p2, p3:
            result = await validator.validate_all_debug_auto_discovery_format()
        assert result.summary["auth_mode"] == "clerk"
        assert result.summary["clerk_configured"] is True
        # Healthy despite no static API key and a failed direct API call.
        assert result.summary["overall_status"] is True

    @pytest.mark.asyncio
    async def test_clerk_mode_unhealthy_when_oauth_config_missing(self, monkeypatch):
        monkeypatch.setenv("AUTH_MODE", "clerk")
        monkeypatch.delenv("CLERK_DOMAIN", raising=False)
        monkeypatch.delenv("CLERK_OAUTH_CLIENT_ID", raising=False)
        monkeypatch.delenv("CLERK_OAUTH_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("MCP_SERVER_BASE_URL", raising=False)
        monkeypatch.delenv("REVENIUM_API_KEY", raising=False)
        validator = EnvironmentVariableValidator()
        p1, p2, p3 = self._offline(validator)
        with p1, p2, p3:
            result = await validator.validate_all_debug_auto_discovery_format()
        assert result.summary["clerk_configured"] is False
        assert result.summary["overall_status"] is False

    @pytest.mark.asyncio
    async def test_clerk_mode_auth_config_works_from_oauth_config(self, monkeypatch):
        """In clerk mode the flag follows the OAuth config, not the API-key probe."""
        monkeypatch.setenv("AUTH_MODE", "clerk")
        monkeypatch.setenv("CLERK_DOMAIN", "clerk.example.com")
        monkeypatch.setenv("CLERK_OAUTH_CLIENT_ID", "client_abc")
        monkeypatch.setenv("CLERK_OAUTH_CLIENT_SECRET", "sk_clerk_test_value")
        monkeypatch.setenv("MCP_SERVER_BASE_URL", "https://mcp.example.com")
        monkeypatch.delenv("REVENIUM_API_KEY", raising=False)
        validator = EnvironmentVariableValidator()
        p1, p2, p3 = self._offline(validator)
        with p1, p2, p3:
            result = await validator.validate_all_debug_auto_discovery_format()
        # The probe (patched to error, as it does without a static key) must not
        # drag the flag down when the OAuth configuration is complete.
        assert result.summary["auth_config_works"] is True

    @pytest.mark.asyncio
    async def test_clerk_mode_auth_config_works_false_when_oauth_missing(self, monkeypatch):
        monkeypatch.setenv("AUTH_MODE", "clerk")
        for name in (
            "CLERK_DOMAIN",
            "CLERK_OAUTH_CLIENT_ID",
            "CLERK_OAUTH_CLIENT_SECRET",
            "MCP_SERVER_BASE_URL",
            "REVENIUM_API_KEY",
        ):
            monkeypatch.delenv(name, raising=False)
        validator = EnvironmentVariableValidator()
        p1, p2, p3 = self._offline(validator)
        with p1, p2, p3:
            result = await validator.validate_all_debug_auto_discovery_format()
        assert result.summary["auth_config_works"] is False

    @pytest.mark.asyncio
    async def test_api_key_mode_overall_status_unchanged(self, monkeypatch):
        monkeypatch.setenv("AUTH_MODE", "api_key")
        monkeypatch.setenv("REVENIUM_API_KEY", "rev_sk_test_key")
        validator = EnvironmentVariableValidator()
        with patch.object(
            validator,
            "test_api_connectivity_debug_auto_discovery",
            new=AsyncMock(return_value={"status": "success"}),
        ), patch.object(
            validator,
            "test_discovered_configuration_debug_auto_discovery",
            new=AsyncMock(return_value={"status": "error", "discovered_count": 0, "values": {}}),
        ), patch.object(
            validator,
            "test_auth_config_debug_auto_discovery",
            new=AsyncMock(return_value={"status": "error"}),
        ):
            result = await validator.validate_all_debug_auto_discovery_format()
        assert result.summary["auth_mode"] == "api_key"
        # Unchanged: still requires the static key + connectivity.
        assert result.summary["overall_status"] is True
        # Unchanged: the ConfigManager probe still governs the flag outside clerk mode.
        assert result.summary["auth_config_works"] is False
