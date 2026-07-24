"""BACK-2067 — the clerk-mode OIDC proxy verifies and forwards the ID token.

Clerk OAuth *access* tokens are minimal (no email, no custom metadata); the
*ID* token carries `email` plus the nested `private_metadata` claims that both
the MCP resolver and HyperCurrent need. So the proxy must (a) verify the ID
token inbound and (b) forward the ID token — not the access token — downstream.

FastMCP's OAuthProxy patches the validated AccessToken back to the access token
when `_uses_alternate_verification()` is True; we override it to False so the
forwarded `AccessToken.token` stays the verified ID token.
"""
from __future__ import annotations

import pytest


def _make_proxy(discovery_url: str):
    from src.revenium_mcp_server.auth.oidc_logging import AuthLoggingOIDCProxy

    return AuthLoggingOIDCProxy(
        config_url=discovery_url,
        client_id="test-client",
        client_secret="test-secret",
        base_url="https://mcp.example.com",
        required_scopes=["openid", "profile", "email", "private_metadata"],
        algorithm="RS256",
        verify_id_token=True,
        audience="https://mcp.example.com/mcp",
    )


def test_proxy_verifies_id_token(fake_clerk):
    proxy = _make_proxy(fake_clerk["discovery_url"])
    assert proxy._verify_id_token is True


def test_proxy_forwards_id_token_not_access_token(fake_clerk):
    """The validated AccessToken must reflect the verified ID token.

    With id_token verification on, FastMCP would by default patch the result
    back to the upstream access token (`_uses_alternate_verification()` True).
    We forward the ID token downstream, so that patch must be disabled.
    """
    proxy = _make_proxy(fake_clerk["discovery_url"])
    assert proxy._uses_alternate_verification() is False


@pytest.mark.asyncio
async def test_verify_token_preserves_id_token(fake_clerk, monkeypatch):
    """Exercise verify_token and assert the returned token is the ID token.

    Fully driving FastMCP's internal token-swap path requires a live Clerk
    token exchange (FastMCP-issued reference token + JTI store), which isn't
    reproducible offline. So we stub the parent ``OIDCProxy.verify_token`` to
    return an AccessToken whose ``.token`` is a sentinel ID token, then assert:

    1. ``AuthLoggingOIDCProxy.verify_token`` returns that AccessToken unchanged
       (``.token`` still equals the ID-token sentinel, not the access token), and
    2. ``_uses_alternate_verification()`` is False — so FastMCP would not swap
       the validated token back to the upstream access token downstream.
    """
    from fastmcp.server.auth.auth import AccessToken
    from fastmcp.server.auth.oidc_proxy import OIDCProxy

    proxy = _make_proxy(fake_clerk["discovery_url"])

    id_token_sentinel = "ID_TOKEN_SENTINEL.value"
    validated = AccessToken(
        token=id_token_sentinel,
        client_id="test-client",
        scopes=["openid", "email"],
        claims={
            "sub": "user_abc",
            "private_metadata": {"tenant_id": "tenant_expected"},
        },
    )

    async def _fake_parent_verify(self, token: str) -> AccessToken:
        return validated

    monkeypatch.setattr(OIDCProxy, "verify_token", _fake_parent_verify)

    result = await proxy.verify_token("upstream-access-token")

    assert result is validated
    assert result.token == id_token_sentinel
    # The override must not have swapped to the upstream access token.
    assert result.token != "upstream-access-token"
    # And FastMCP's swap path stays disabled.
    assert proxy._uses_alternate_verification() is False


@pytest.mark.asyncio
async def test_verify_token_restores_scopes_from_proxy_jwt(fake_clerk, monkeypatch):
    """When the parent returns an AccessToken with no scopes, the proxy reads
    the granted scopes back from the proxy-minted FastMCP JWT.
    """
    from types import SimpleNamespace

    from fastmcp.server.auth.auth import AccessToken
    from fastmcp.server.auth.oidc_proxy import OIDCProxy

    proxy = _make_proxy(fake_clerk["discovery_url"])

    validated = AccessToken(
        token="id-token",
        client_id="test-client",
        scopes=[],
        claims={"sub": "user_abc"},
    )

    async def _fake_parent_verify(self, token: str) -> AccessToken:
        return validated

    monkeypatch.setattr(OIDCProxy, "verify_token", _fake_parent_verify)
    proxy._jwt_issuer = SimpleNamespace(
        verify_token=lambda t: {"scope": "openid profile email private_metadata"}
    )

    result = await proxy.verify_token("proxy-minted-jwt")

    assert result.scopes == ["openid", "profile", "email", "private_metadata"]


@pytest.mark.asyncio
async def test_verify_token_scope_restoration_failure_is_safe(fake_clerk, monkeypatch):
    """If scope restoration raises, auth must not break — scopes stay empty."""
    from types import SimpleNamespace

    from fastmcp.server.auth.auth import AccessToken
    from fastmcp.server.auth.oidc_proxy import OIDCProxy

    proxy = _make_proxy(fake_clerk["discovery_url"])

    validated = AccessToken(
        token="id-token",
        client_id="test-client",
        scopes=[],
        claims={"sub": "user_abc"},
    )

    async def _fake_parent_verify(self, token: str) -> AccessToken:
        return validated

    monkeypatch.setattr(OIDCProxy, "verify_token", _fake_parent_verify)

    def _raise(t):
        raise RuntimeError("boom")

    proxy._jwt_issuer = SimpleNamespace(verify_token=_raise)

    result = await proxy.verify_token("proxy-minted-jwt")

    assert result.scopes == []
