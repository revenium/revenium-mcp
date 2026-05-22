"""Unit tests for TenantResolver implementations."""
from __future__ import annotations

import pytest
from unittest.mock import patch

from src.revenium_mcp_server.auth.api_key_scope import APIKeyScope


# ── EnvTenantResolver ────────────────────────────────────────────

def test_env_resolver_returns_context_from_config_manager():
    from src.revenium_mcp_server.auth.tenant_resolver import EnvTenantResolver

    with patch(
        "src.revenium_mcp_server.auth.tenant_resolver.ConfigManager"
    ) as mock_cm:
        mock_cfg = mock_cm.return_value.get_config.return_value
        mock_cfg.team_id = "team_env"
        mock_cfg.api_key = "key_env_abcd"
        mock_cfg.tenant_id = "tenant_env"
        mock_cfg.base_url = "https://api.revenium.io"

        resolver = EnvTenantResolver()
        ctx = resolver.resolve({"irrelevant": "claims"})

    assert ctx.team_id == "team_env"
    assert ctx.api_key == "key_env_abcd"
    assert ctx.tenant_id == "tenant_env"
    assert ctx.base_url == "https://api.revenium.io"
    assert ctx.user_id is None


def test_env_resolver_ignores_claims():
    from src.revenium_mcp_server.auth.tenant_resolver import EnvTenantResolver

    with patch(
        "src.revenium_mcp_server.auth.tenant_resolver.ConfigManager"
    ) as mock_cm:
        mock_cfg = mock_cm.return_value.get_config.return_value
        mock_cfg.team_id = "team_env"
        mock_cfg.api_key = "key_env_abcd"
        mock_cfg.tenant_id = "tenant_env"
        mock_cfg.base_url = "https://api.revenium.io"

        resolver = EnvTenantResolver()
        ctx_with = resolver.resolve({"revenium_team_id": "other_team"})
        ctx_without = resolver.resolve({})

    assert ctx_with.team_id == ctx_without.team_id == "team_env"


# ── ClerkTenantResolver ──────────────────────────────────────────

@pytest.fixture
def mock_config_manager():
    with patch(
        "src.revenium_mcp_server.auth.tenant_resolver.ConfigManager"
    ) as mock_cm:
        mock_cfg = mock_cm.return_value.get_config.return_value
        mock_cfg.team_id = "team_env"
        mock_cfg.api_key = "shared_key_abcd"
        mock_cfg.tenant_id = "tenant_expected"
        mock_cfg.base_url = "https://api.revenium.io"
        yield mock_cfg


def test_clerk_resolver_happy_path(mock_config_manager):
    from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

    resolver = ClerkTenantResolver()
    claims = {
        "revenium_team_id": "team_jwt",
        "tenant_id": "tenant_expected",
        "sub": "user_abc",
        "scope": "openid profile email",
    }
    ctx = resolver.resolve(claims)

    assert ctx.team_id == "team_jwt"
    assert ctx.tenant_id == "tenant_expected"
    assert ctx.user_id == "user_abc"
    assert ctx.api_key == "shared_key_abcd"
    assert ctx.base_url == "https://api.revenium.io"
    assert ctx.scopes == ["openid", "profile", "email"]


def test_clerk_resolver_missing_team_id(mock_config_manager):
    from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

    resolver = ClerkTenantResolver()
    with pytest.raises(PermissionError, match="revenium_team_id"):
        resolver.resolve(
            {"tenant_id": "tenant_expected", "sub": "user_abc"}
        )


def test_clerk_resolver_missing_tenant_id(mock_config_manager):
    from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

    resolver = ClerkTenantResolver()
    with pytest.raises(PermissionError, match=r"missing required claim\(s\): .*tenant_id"):
        resolver.resolve(
            {"revenium_team_id": "team_jwt", "sub": "user_abc"}
        )


def test_clerk_resolver_missing_sub(mock_config_manager):
    from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

    resolver = ClerkTenantResolver()
    with pytest.raises(PermissionError, match="sub"):
        resolver.resolve(
            {"revenium_team_id": "team_jwt", "tenant_id": "tenant_expected"}
        )


def test_clerk_resolver_tenant_mismatch(mock_config_manager):
    from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

    resolver = ClerkTenantResolver()
    claims = {
        "revenium_team_id": "team_jwt",
        "tenant_id": "tenant_wrong",
        "sub": "user_abc",
    }
    with pytest.raises(PermissionError, match="does not match this deployment"):
        resolver.resolve(claims)


def test_clerk_resolver_init_raises_if_tenant_id_unset():
    from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

    with patch(
        "src.revenium_mcp_server.auth.tenant_resolver.ConfigManager"
    ) as mock_cm:
        mock_cfg = mock_cm.return_value.get_config.return_value
        mock_cfg.tenant_id = None
        with pytest.raises(RuntimeError, match="REVENIUM_TENANT_ID must be set"):
            ClerkTenantResolver()


def test_clerk_resolver_scope_as_list(mock_config_manager):
    from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

    resolver = ClerkTenantResolver()
    claims = {
        "revenium_team_id": "team_jwt",
        "tenant_id": "tenant_expected",
        "sub": "user_abc",
        "scope": ["openid", "email"],
    }
    ctx = resolver.resolve(claims)
    assert ctx.scopes == ["openid", "email"]


def test_clerk_resolver_empty_scope(mock_config_manager):
    from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

    resolver = ClerkTenantResolver()
    claims = {
        "revenium_team_id": "team_jwt",
        "tenant_id": "tenant_expected",
        "sub": "user_abc",
    }
    ctx = resolver.resolve(claims)
    assert ctx.scopes is None


def test_clerk_resolver_filters_empty_scope_elements(mock_config_manager):
    from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

    resolver = ClerkTenantResolver()
    claims = {
        "revenium_team_id": "team_jwt",
        "tenant_id": "tenant_expected",
        "sub": "user_abc",
        "scope": ["", "openid", ""],
    }
    ctx = resolver.resolve(claims)
    assert ctx.scopes == ["openid"]


def test_clerk_resolver_all_empty_scope_list_becomes_none(mock_config_manager):
    from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

    resolver = ClerkTenantResolver()
    claims = {
        "revenium_team_id": "team_jwt",
        "tenant_id": "tenant_expected",
        "sub": "user_abc",
        "scope": ["", ""],
    }
    ctx = resolver.resolve(claims)
    assert ctx.scopes is None


def test_clerk_resolver_oidc_scope_non_iterable_returns_none(mock_config_manager):
    """JWT 'scope' claim of unexpected type must not crash _parse_scopes."""
    from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

    resolver = ClerkTenantResolver()
    for bad_value in (True, 42, {"foo": "bar"}):
        claims = {
            "revenium_team_id": "team_jwt",
            "tenant_id": "tenant_expected",
            "sub": "user_abc",
            "scope": bad_value,
        }
        ctx = resolver.resolve(claims)
        assert ctx.scopes is None, f"failed for value {bad_value!r}"


def test_clerk_resolver_tenant_mismatch_does_not_leak_expected(mock_config_manager):
    """PermissionError on tenant mismatch must not disclose the server's REVENIUM_TENANT_ID."""
    from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

    resolver = ClerkTenantResolver()
    claims = {
        "revenium_team_id": "team_jwt",
        "tenant_id": "tenant_wrong",
        "sub": "user_abc",
    }
    try:
        resolver.resolve(claims)
        assert False, "should have raised PermissionError"
    except PermissionError as e:
        # Neither the JWT-supplied tenant_id NOR the server's configured value
        # should appear in the error message.
        assert "tenant_wrong" not in str(e)
        assert "tenant_expected" not in str(e)
        # But the error class and high-level message should still be correct.
        assert "does not match this deployment" in str(e)


# ── get_resolver() ───────────────────────────────────────────────

def test_get_resolver_defaults_to_env(monkeypatch):
    from src.revenium_mcp_server.auth.tenant_resolver import (
        EnvTenantResolver,
        get_resolver,
    )

    monkeypatch.delenv("AUTH_MODE", raising=False)
    assert isinstance(get_resolver(), EnvTenantResolver)


def test_get_resolver_returns_clerk_when_clerk(monkeypatch, mock_config_manager):
    from src.revenium_mcp_server.auth.tenant_resolver import (
        ClerkTenantResolver,
        get_resolver,
    )

    monkeypatch.setenv("AUTH_MODE", "clerk")
    assert isinstance(get_resolver(), ClerkTenantResolver)


def test_get_resolver_rejects_unknown_auth_mode(monkeypatch):
    """get_resolver must raise on unknown AUTH_MODE, matching _read_auth_mode's strictness."""
    from src.revenium_mcp_server.auth.tenant_resolver import get_resolver

    monkeypatch.setenv("AUTH_MODE", "oauth2")
    with pytest.raises(ValueError, match="AUTH_MODE must be"):
        get_resolver()


class TestClerkResolverApiKeyScopes:
    """ClerkTenantResolver behavior for the revenium_api_scopes JWT claim."""

    def _base_claims(self):
        return {
            "revenium_team_id": "team_jwt",
            "tenant_id": "tenant_expected",
            "sub": "user_abc",
        }

    def test_parses_string_claim(self, mock_config_manager):
        from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

        resolver = ClerkTenantResolver()
        claims = {**self._base_claims(), "revenium_api_scopes": "READ WRITE"}
        ctx = resolver.resolve(claims)
        assert ctx.api_key_scopes == [APIKeyScope.READ, APIKeyScope.WRITE]

    def test_parses_list_claim(self, mock_config_manager):
        from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

        resolver = ClerkTenantResolver()
        claims = {**self._base_claims(), "revenium_api_scopes": ["read", "write"]}
        ctx = resolver.resolve(claims)
        assert ctx.api_key_scopes == [APIKeyScope.READ, APIKeyScope.WRITE]

    def test_normalizes_case(self, mock_config_manager):
        from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

        resolver = ClerkTenantResolver()
        claims = {**self._base_claims(), "revenium_api_scopes": "read metering"}
        ctx = resolver.resolve(claims)
        assert ctx.api_key_scopes == [APIKeyScope.READ, APIKeyScope.METERING]

    def test_drops_unknown_with_warning(self, mock_config_manager):
        from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

        # The project uses loguru; patch the module-level logger to capture
        # warnings (pytest's caplog does NOT catch loguru by default).
        with patch("src.revenium_mcp_server.auth.tenant_resolver.logger") as mock_logger:
            resolver = ClerkTenantResolver()
            claims = {**self._base_claims(), "revenium_api_scopes": "READ BANANA WRITE"}
            ctx = resolver.resolve(claims)

        assert ctx.api_key_scopes == [APIKeyScope.READ, APIKeyScope.WRITE]
        mock_logger.warning.assert_called_once()
        # call_args is a (args_tuple, kwargs_dict) pair; check both that the
        # dropped token appears somewhere in the call so we don't depend on
        # the exact format-string vs. positional-arg split.
        assert "BANANA" in str(mock_logger.warning.call_args)

    def test_dedupes(self, mock_config_manager):
        from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

        resolver = ClerkTenantResolver()
        claims = {**self._base_claims(), "revenium_api_scopes": "READ READ WRITE"}
        ctx = resolver.resolve(claims)
        assert ctx.api_key_scopes == [APIKeyScope.READ, APIKeyScope.WRITE]

    def test_all_unknown_returns_none(self, mock_config_manager):
        from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

        resolver = ClerkTenantResolver()
        claims = {**self._base_claims(), "revenium_api_scopes": "BANANA APPLE"}
        ctx = resolver.resolve(claims)
        assert ctx.api_key_scopes is None

    def test_missing_claim_returns_none(self, mock_config_manager):
        from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

        resolver = ClerkTenantResolver()
        ctx = resolver.resolve(self._base_claims())
        assert ctx.api_key_scopes is None

    def test_empty_list_returns_none(self, mock_config_manager):
        from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

        resolver = ClerkTenantResolver()
        claims = {**self._base_claims(), "revenium_api_scopes": []}
        ctx = resolver.resolve(claims)
        assert ctx.api_key_scopes is None

    def test_oidc_scopes_untouched(self, mock_config_manager):
        """Regression: existing ctx.scopes (OIDC) semantics preserved."""
        from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

        resolver = ClerkTenantResolver()
        claims = {
            **self._base_claims(),
            "scope": "openid email",
            "revenium_api_scopes": "READ",
        }
        ctx = resolver.resolve(claims)
        assert ctx.scopes == ["openid", "email"]
        assert ctx.api_key_scopes == [APIKeyScope.READ]

    def test_non_iterable_claim_returns_none(self, mock_config_manager):
        """JWT claim of unexpected type (bool / int) must not crash."""
        from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

        resolver = ClerkTenantResolver()
        for bad_value in (True, 42, {"foo": "bar"}):
            claims = {**self._base_claims(), "revenium_api_scopes": bad_value}
            ctx = resolver.resolve(claims)
            assert ctx.api_key_scopes is None, f"failed for value {bad_value!r}"

    def test_list_with_non_string_elements_drops_them(self, mock_config_manager):
        """JWT claim list containing non-string elements must skip them, not crash."""
        from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

        resolver = ClerkTenantResolver()
        claims = {**self._base_claims(), "revenium_api_scopes": ["READ", 42, None, "WRITE"]}
        ctx = resolver.resolve(claims)
        assert ctx.api_key_scopes == [APIKeyScope.READ, APIKeyScope.WRITE]
