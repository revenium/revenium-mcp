"""RFC 9728 metadata, RFC 8707 resource forwarding, and PKCE posture of the
clerk-mode auth provider (production OIDCProxy against the fake Clerk)."""
from __future__ import annotations

import pytest


def _build_oidc_proxy(fake_clerk, base_url, audience, **extra):
    from fastmcp.server.auth.oidc_proxy import OIDCProxy

    return OIDCProxy(
        config_url=fake_clerk["discovery_url"],
        client_id="test-client",
        client_secret="test-secret",
        base_url=base_url,
        required_scopes=["openid", "profile", "email"],
        algorithm="RS256",
        audience=audience,
        **extra,
    )


@pytest.fixture
def oidc_app(fake_clerk):
    """FastMCP http app wired with the production OIDCProxy configuration."""
    from fastmcp import FastMCP

    base_url = "http://127.0.0.1:9999"  # never bound; ASGI-only
    audience = base_url + "/mcp"
    proxy = _build_oidc_proxy(fake_clerk, base_url, audience)
    mcp = FastMCP(name="metadata-test", auth=proxy)
    return mcp.http_app(), base_url, audience


@pytest.fixture
def oidc_app_no_consent(fake_clerk):
    """Same proxy config but with the consent interstitial disabled, so the
    /authorize redirect goes straight to the upstream IdP and the RFC 8707
    resource forwarding is directly observable in the redirect URL."""
    from fastmcp import FastMCP

    base_url = "http://127.0.0.1:9999"
    audience = base_url + "/mcp"
    proxy = _build_oidc_proxy(
        fake_clerk, base_url, audience, require_authorization_consent=False
    )
    mcp = FastMCP(name="metadata-test-noconsent", auth=proxy)
    return mcp.http_app(), base_url, audience


async def _get(app, path, **kwargs):
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.get(path, **kwargs)


@pytest.mark.asyncio
async def test_protected_resource_metadata_served(oidc_app):
    app, base_url, audience = oidc_app
    # FastMCP registers the RFC 9728 metadata at the path-scoped URL:
    # /.well-known/oauth-protected-resource/mcp  (mcp_path="/mcp" appended per
    # RFC 9728 §3.1). The root path may not be registered; we probe both and
    # accept whichever responds 200.
    for path in (
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource/mcp",
    ):
        resp = await _get(app, path)
        if resp.status_code == 200:
            break
    assert resp.status_code == 200, "no protected-resource metadata route found"
    doc = resp.json()
    assert doc["resource"].rstrip("/") == audience.rstrip("/")
    assert doc.get("authorization_servers"), doc
    assert doc.get("bearer_methods_supported"), doc
    assert "header" in doc["bearer_methods_supported"]


@pytest.mark.asyncio
async def test_authorize_forwards_resource_param(oidc_app_no_consent, fake_clerk):
    app, base_url, audience = oidc_app_no_consent
    import urllib.parse

    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        reg = await c.post(
            "/register",
            json={
                "client_name": "itest",
                "redirect_uris": ["http://127.0.0.1:33418/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )
        assert reg.status_code in (200, 201), reg.text
        client_id = reg.json()["client_id"]

        resp = await c.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": "http://127.0.0.1:33418/callback",
                "response_type": "code",
                "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
                "code_challenge_method": "S256",
                "state": "xyz",
                "resource": audience,
            },
            follow_redirects=False,
        )

    assert resp.status_code in (302, 307), resp.text
    location = resp.headers["location"]
    # The redirect must target the upstream IdP's authorize endpoint...
    assert location.startswith(fake_clerk["issuer"]), location
    # ...and carry the resource indicator for the canonical MCP URI.
    parsed = urllib.parse.urlparse(location)
    query = urllib.parse.parse_qs(parsed.query)
    assert query.get("resource") == [audience], query


@pytest.mark.asyncio
async def test_authorize_without_pkce_is_rejected(oidc_app):
    app, base_url, audience = oidc_app
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # FastMCP requires both authorization_code and refresh_token in grant_types.
        reg = await c.post(
            "/register",
            json={
                "client_name": "itest-nopkce",
                "redirect_uris": ["http://127.0.0.1:33418/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )
        client_id = reg.json()["client_id"]
        resp = await c.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": "http://127.0.0.1:33418/callback",
                "response_type": "code",
                "state": "xyz",
            },
            follow_redirects=False,
        )
    # PKCE (code_challenge + code_challenge_method) is required by FastMCP's
    # OAuthProvider. A missing code_challenge must be rejected with either:
    # - a redirect error (302/307 with error= in Location), or
    # - a 4xx error response directly.
    if resp.status_code in (302, 307):
        assert "error=" in resp.headers["location"], resp.headers["location"]
    else:
        assert 400 <= resp.status_code < 500, resp.text
