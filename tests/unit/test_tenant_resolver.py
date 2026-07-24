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


# ── ClerkTenantResolver (multi-tenant) ───────────────────────────

JWT = "eyJhbGciOiJSUzI1NiJ9.payload.signature"


def _claims(**overrides):
    base = {
        "sub": "user_abc",
        "revenium_team_id": "team_from_jwt",
        "tenant_id": "tenant_from_jwt",
    }
    base.update(overrides)
    return base


class TestClerkResolverMultiTenant:
    def test_resolves_without_env_pinning(self, monkeypatch):
        monkeypatch.delenv("REVENIUM_TENANT_ID", raising=False)
        monkeypatch.delenv("REVENIUM_API_KEY", raising=False)
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        ctx = resolver.resolve(_claims(), clerk_jwt=JWT)
        assert ctx.tenant_id == "tenant_from_jwt"
        assert ctx.team_id == "team_from_jwt"
        assert ctx.user_id == "user_abc"
        assert ctx.clerk_jwt == JWT
        assert ctx.api_key is None

    def test_two_tenants_resolve_on_same_instance(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        a = resolver.resolve(_claims(tenant_id="tenant_a"), clerk_jwt=JWT)
        b = resolver.resolve(_claims(tenant_id="tenant_b"), clerk_jwt=JWT)
        assert a.tenant_id == "tenant_a"
        assert b.tenant_id == "tenant_b"

    def test_missing_claims_still_rejected(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        claims = _claims()
        del claims["revenium_team_id"]
        with pytest.raises(PermissionError, match="revenium_team_id"):
            resolver.resolve(claims, clerk_jwt=JWT)

    def test_missing_jwt_rejected(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        with pytest.raises(PermissionError, match="access token"):
            resolver.resolve(_claims(), clerk_jwt=None)

    def test_resolves_tenant_claims_from_nested_private_metadata(self, monkeypatch):
        """Clerk OAuth ID tokens nest custom claims under private_metadata."""
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        claims = {
            "sub": "user_abc",
            "email": "u@example.com",
            "private_metadata": {
                "revenium_team_id": "team_nested",
                "tenant_id": "tenant_nested",
            },
        }
        ctx = resolver.resolve(claims, clerk_jwt=JWT)
        assert ctx.team_id == "team_nested"
        assert ctx.tenant_id == "tenant_nested"
        assert ctx.user_id == "user_abc"

    def test_top_level_claims_take_precedence_over_nested(self, monkeypatch):
        """A top-level claim (e.g. a session-token-shaped JWT) still wins."""
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        claims = {
            "sub": "user_abc",
            "revenium_team_id": "team_top",
            "tenant_id": "tenant_top",
            "private_metadata": {
                "revenium_team_id": "team_nested",
                "tenant_id": "tenant_nested",
            },
        }
        ctx = resolver.resolve(claims, clerk_jwt=JWT)
        assert ctx.team_id == "team_top"
        assert ctx.tenant_id == "tenant_top"

    def test_missing_nested_claim_still_rejected(self, monkeypatch):
        """A private_metadata block missing revenium_team_id is rejected."""
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        claims = {
            "sub": "user_abc",
            "private_metadata": {"tenant_id": "tenant_nested"},
        }
        with pytest.raises(PermissionError, match="revenium_team_id"):
            resolver.resolve(claims, clerk_jwt=JWT)


def _make_clerk_resolver():
    """Instantiate ClerkTenantResolver without ConfigManager side-effects."""
    from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver
    return ClerkTenantResolver()


# ── get_resolver() ───────────────────────────────────────────────

def test_get_resolver_defaults_to_env(monkeypatch):
    from src.revenium_mcp_server.auth.tenant_resolver import (
        EnvTenantResolver,
        get_resolver,
    )

    monkeypatch.delenv("AUTH_MODE", raising=False)
    assert isinstance(get_resolver(), EnvTenantResolver)


def test_get_resolver_returns_clerk_when_clerk(monkeypatch):
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
            "tenant_id": "tenant_from_jwt",
            "sub": "user_abc",
        }

    def test_parses_string_claim(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        claims = {**self._base_claims(), "revenium_api_scopes": "READ WRITE"}
        ctx = resolver.resolve(claims, clerk_jwt=JWT)
        assert ctx.api_key_scopes == [APIKeyScope.READ, APIKeyScope.WRITE]

    def test_parses_list_claim(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        claims = {**self._base_claims(), "revenium_api_scopes": ["read", "write"]}
        ctx = resolver.resolve(claims, clerk_jwt=JWT)
        assert ctx.api_key_scopes == [APIKeyScope.READ, APIKeyScope.WRITE]

    def test_normalizes_case(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        claims = {**self._base_claims(), "revenium_api_scopes": "read metering"}
        ctx = resolver.resolve(claims, clerk_jwt=JWT)
        assert ctx.api_key_scopes == [APIKeyScope.READ, APIKeyScope.METERING]

    def test_drops_unknown_with_warning(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        # The project uses loguru; patch the module-level logger to capture
        # warnings (pytest's caplog does NOT catch loguru by default).
        with patch("src.revenium_mcp_server.auth.tenant_resolver.logger") as mock_logger:
            resolver = _make_clerk_resolver()
            claims = {**self._base_claims(), "revenium_api_scopes": "READ BANANA WRITE"}
            ctx = resolver.resolve(claims, clerk_jwt=JWT)

        assert ctx.api_key_scopes == [APIKeyScope.READ, APIKeyScope.WRITE]
        mock_logger.warning.assert_called_once()
        # call_args is a (args_tuple, kwargs_dict) pair; check both that the
        # dropped token appears somewhere in the call so we don't depend on
        # the exact format-string vs. positional-arg split.
        assert "BANANA" in str(mock_logger.warning.call_args)

    def test_dedupes(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        claims = {**self._base_claims(), "revenium_api_scopes": "READ READ WRITE"}
        ctx = resolver.resolve(claims, clerk_jwt=JWT)
        assert ctx.api_key_scopes == [APIKeyScope.READ, APIKeyScope.WRITE]

    def test_all_unknown_returns_none(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        claims = {**self._base_claims(), "revenium_api_scopes": "BANANA APPLE"}
        ctx = resolver.resolve(claims, clerk_jwt=JWT)
        assert ctx.api_key_scopes is None

    def test_missing_claim_returns_none(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        ctx = resolver.resolve(self._base_claims(), clerk_jwt=JWT)
        assert ctx.api_key_scopes is None

    def test_empty_list_returns_none(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        claims = {**self._base_claims(), "revenium_api_scopes": []}
        ctx = resolver.resolve(claims, clerk_jwt=JWT)
        assert ctx.api_key_scopes is None

    def test_oidc_scopes_untouched(self, monkeypatch):
        """Regression: existing ctx.scopes (OIDC) semantics preserved."""
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        claims = {
            **self._base_claims(),
            "scope": "openid email",
            "revenium_api_scopes": "READ",
        }
        ctx = resolver.resolve(claims, clerk_jwt=JWT)
        assert ctx.scopes == ["openid", "email"]
        assert ctx.api_key_scopes == [APIKeyScope.READ]

    def test_non_iterable_claim_returns_none(self, monkeypatch):
        """JWT claim of unexpected type (bool / int) must not crash."""
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        for bad_value in (True, 42, {"foo": "bar"}):
            claims = {**self._base_claims(), "revenium_api_scopes": bad_value}
            ctx = resolver.resolve(claims, clerk_jwt=JWT)
            assert ctx.api_key_scopes is None, f"failed for value {bad_value!r}"

    def test_list_with_non_string_elements_drops_them(self, monkeypatch):
        """JWT claim list containing non-string elements must skip them, not crash."""
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        claims = {**self._base_claims(), "revenium_api_scopes": ["READ", 42, None, "WRITE"]}
        ctx = resolver.resolve(claims, clerk_jwt=JWT)
        assert ctx.api_key_scopes == [APIKeyScope.READ, APIKeyScope.WRITE]

    def test_scope_as_list(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        claims = {
            **self._base_claims(),
            "scope": ["openid", "email"],
        }
        ctx = resolver.resolve(claims, clerk_jwt=JWT)
        assert ctx.scopes == ["openid", "email"]

    def test_empty_scope(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        ctx = resolver.resolve(self._base_claims(), clerk_jwt=JWT)
        assert ctx.scopes is None

    def test_filters_empty_scope_elements(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        claims = {**self._base_claims(), "scope": ["", "openid", ""]}
        ctx = resolver.resolve(claims, clerk_jwt=JWT)
        assert ctx.scopes == ["openid"]

    def test_all_empty_scope_list_becomes_none(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        claims = {**self._base_claims(), "scope": ["", ""]}
        ctx = resolver.resolve(claims, clerk_jwt=JWT)
        assert ctx.scopes is None

    def test_oidc_scope_non_iterable_returns_none(self, monkeypatch):
        """JWT 'scope' claim of unexpected type must not crash _parse_scopes."""
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.example.com")
        resolver = _make_clerk_resolver()
        for bad_value in (True, 42, {"foo": "bar"}):
            claims = {**self._base_claims(), "scope": bad_value}
            ctx = resolver.resolve(claims, clerk_jwt=JWT)
            assert ctx.scopes is None, f"failed for value {bad_value!r}"
