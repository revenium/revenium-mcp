"""Unit tests for AuthConfigFactory."""

import pytest

from revenium_mcp_server.auth import AuthConfig, EnvironmentType
from revenium_mcp_server.auth.config_factory import AuthConfigFactory
from revenium_mcp_server.auth.tenant_context import TenantContext


class TestFromTenantContext:
    def test_maps_required_fields(self):
        ctx = TenantContext(team_id="team-1", api_key="abcdef1234567890")
        cfg = AuthConfigFactory.from_tenant_context(ctx)
        assert isinstance(cfg, AuthConfig)
        assert cfg.team_id == "team-1"
        assert cfg.api_key == "abcdef1234567890"

    def test_maps_optional_tenant_id(self):
        ctx = TenantContext(
            team_id="team-1",
            api_key="abcdef1234567890",
            tenant_id="tenant-9",
        )
        cfg = AuthConfigFactory.from_tenant_context(ctx)
        assert cfg.tenant_id == "tenant-9"

    def test_omits_optional_tenant_id(self):
        ctx = TenantContext(team_id="team-1", api_key="abcdef1234567890")
        cfg = AuthConfigFactory.from_tenant_context(ctx)
        assert cfg.tenant_id is None

    def test_uses_authconfig_defaults_for_extras(self):
        ctx = TenantContext(team_id="team-1", api_key="abcdef1234567890")
        cfg = AuthConfigFactory.from_tenant_context(ctx)
        # These come from AuthConfig defaults, not from ctx
        assert cfg.timeout == 30.0
        assert cfg.max_retries == 3
        assert cfg.environment == EnvironmentType.DEVELOPMENT

    def test_base_url_from_ctx(self):
        ctx = TenantContext(
            team_id="team-1",
            api_key="abcdef1234567890",
            base_url="https://custom.example.com",
        )
        cfg = AuthConfigFactory.from_tenant_context(ctx)
        assert cfg.base_url == "https://custom.example.com"


class TestFromEnv:
    @pytest.fixture(autouse=True)
    def _reset_auth_cache(self):
        """Ensure ConfigManager singleton cache is empty before each test.

        Each test in this class monkeypatches env vars and expects from_env()
        to read them fresh. Without this fixture, a previously-cached config
        from a prior test could leak through and produce a flaky assertion.
        """
        from revenium_mcp_server.auth import ConfigManager
        ConfigManager().clear_cache()

    def test_returns_authconfig(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_API_KEY", "env-key-1234567890")
        monkeypatch.setenv("REVENIUM_TEAM_ID", "env-team-1")

        cfg = AuthConfigFactory.from_env()
        assert isinstance(cfg, AuthConfig)
        assert cfg.api_key == "env-key-1234567890"
        assert cfg.team_id == "env-team-1"

    def test_uses_configmanager_cache(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_API_KEY", "cache-key-1234567890")
        monkeypatch.setenv("REVENIUM_TEAM_ID", "cache-team")

        cfg1 = AuthConfigFactory.from_env()
        cfg2 = AuthConfigFactory.from_env()
        # Same singleton cached object — identity check
        assert cfg1 is cfg2

    def test_raises_when_env_missing(self, monkeypatch):
        monkeypatch.delenv("REVENIUM_API_KEY", raising=False)

        with pytest.raises(ValueError, match="REVENIUM_API_KEY"):
            AuthConfigFactory.from_env()
