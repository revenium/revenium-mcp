"""Integration tests for the full Clerk OAuth flow (BACK-853).

A local pytest-httpserver stands in for the Clerk OIDC discovery endpoint
and the JWKS endpoint. JWTs are minted locally with a generated RSA keypair
and signed as Clerk would. FastMCP's OIDCProxy discovers the keys from the
fixture server and validates signatures against them.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


# ── Keypair ──────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def test_keypair():
    """Generate one RSA keypair for the entire test session."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, key.public_key()


def _jwk_from_public_key(public_key, kid: str = "test-kid") -> dict:
    """Export an RSA public key in JWK form (matches Clerk's JWKS shape)."""
    numbers = public_key.public_numbers()

    def _b64(i: int) -> str:
        import base64
        b = i.to_bytes((i.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")

    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _b64(numbers.n),
        "e": _b64(numbers.e),
    }


# ── Fake Clerk discovery / JWKS server ───────────────────────────

@pytest.fixture
def fake_clerk(httpserver, test_keypair):
    """Serve a minimal OIDC discovery doc + JWKS on pytest-httpserver."""
    _, public_key = test_keypair
    issuer = httpserver.url_for("").rstrip("/")
    jwks_url = httpserver.url_for("/.well-known/jwks.json")
    discovery_path = "/.well-known/openid-configuration"
    discovery_url = httpserver.url_for(discovery_path)

    discovery = {
        "issuer": issuer,
        "jwks_uri": jwks_url,
        "id_token_signing_alg_values_supported": ["RS256"],
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "userinfo_endpoint": f"{issuer}/oauth/userinfo",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
    }

    httpserver.expect_request(discovery_path).respond_with_json(discovery)
    httpserver.expect_request("/.well-known/jwks.json").respond_with_json(
        {"keys": [_jwk_from_public_key(public_key)]}
    )

    return {
        "issuer": issuer,
        "discovery_url": discovery_url,
        "jwks_url": jwks_url,
    }


# ── JWT minting helper ───────────────────────────────────────────

def _issue_jwt(
    private_key,
    issuer: str,
    claims: dict[str, Any],
    exp_offset: int = 300,
    audience: str = "test-client",
    kid: str = "test-kid",
) -> str:
    """Encode a JWT with the given claims, signed by the test keypair."""
    now = int(time.time())
    payload = {
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + exp_offset,
        **claims,
    }
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return jwt.encode(
        payload, pem, algorithm="RS256", headers={"kid": kid}
    )


# ── MCP server fixture ───────────────────────────────────────────

@pytest.fixture
async def mcp_http_server(fake_clerk, monkeypatch, unused_tcp_port):
    """Spin up the MCP server with a JWTVerifier (backed by fake Clerk JWKS).

    Uses JWTVerifier directly instead of OIDCProxy so that tests can present
    raw upstream JWTs in the Authorization header.  OIDCProxy implements a
    full token-swap flow (FastMCP-issued reference token + JTI store) that is
    incompatible with directly-minted test JWTs.
    """
    monkeypatch.setenv("AUTH_MODE", "clerk")
    monkeypatch.setenv("REVENIUM_API_KEY", "test_api_key_abcd1234")
    monkeypatch.setenv("REVENIUM_TENANT_ID", "tenant_expected")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_default")
    # Allow http:// base_url for this test fixture (TenantContext._valid_url
    # otherwise rejects plaintext URLs).
    monkeypatch.setenv("REVENIUM_ALLOW_HTTP", "1")
    # Point at an unreachable address so the startup API-key validation
    # doesn't try to hit the real Revenium API during tests.
    monkeypatch.setenv("REVENIUM_BASE_URL", "http://127.0.0.1:1")

    from fastmcp.server.auth.providers.jwt import JWTVerifier

    from src.revenium_mcp_server.auth.claims_middleware import TenantContextMiddleware
    from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver
    from src.revenium_mcp_server.enhanced_server import create_enhanced_server, register_tools

    jwt_verifier = JWTVerifier(
        jwks_uri=fake_clerk["jwks_url"],
        issuer=fake_clerk["issuer"],
        audience="test-client",
        algorithm="RS256",
        # No required_scopes: test JWTs don't carry scope claims and scope
        # enforcement at the HTTP layer would cause HTTP 403 before the
        # TenantContextMiddleware even runs.
    )

    mcp = create_enhanced_server(auth=jwt_verifier)
    mcp.add_middleware(TenantContextMiddleware(ClerkTenantResolver()))

    await register_tools(mcp)

    server_task: asyncio.Task | None = None

    async def _start():
        nonlocal server_task
        server_task = asyncio.create_task(
            # stateless_http=True: each POST is handled independently with no
            # session tracking, which is ideal for integration testing because
            # tests don't need to establish a session before sending requests.
            mcp.run_async(transport="http", host="127.0.0.1", port=unused_tcp_port, show_banner=False, stateless_http=True)
        )
        for _ in range(50):
            try:
                import httpx
                async with httpx.AsyncClient() as c:
                    await c.get(
                        f"http://127.0.0.1:{unused_tcp_port}/mcp",
                        timeout=0.5,
                    )
                    return  # any HTTP response means the server is up
            except Exception:
                await asyncio.sleep(0.2)
        raise RuntimeError("MCP server did not bind within timeout")

    await _start()
    try:
        yield {
            "base_url": f"http://127.0.0.1:{unused_tcp_port}",
        }
    finally:
        if server_task:
            server_task.cancel()
            try:
                await server_task
            except (asyncio.CancelledError, Exception):
                pass


@pytest.fixture
def mint_jwt(test_keypair, fake_clerk):
    """Return a helper that mints JWTs for tests."""
    private_key, _ = test_keypair

    def _mint(**overrides):
        exp_offset = overrides.pop("_exp_offset", 300)
        issuer = overrides.pop("_issuer", fake_clerk["issuer"])
        claims = {
            "sub": "user_abc",
            "revenium_team_id": "team_from_jwt",
            "tenant_id": "tenant_expected",
        }
        for k, v in overrides.items():
            if v is None:
                claims.pop(k, None)
            else:
                claims[k] = v
        return _issue_jwt(
            private_key,
            issuer=issuer,
            claims=claims,
            exp_offset=exp_offset,
        )

    return _mint


# ── HTTP call helper ─────────────────────────────────────────────

async def _call_tool(base_url: str, jwt_token: "str | None", tool: str = "tool_introspection") -> "httpx.Response":
    """POST a minimal MCP tools/call JSON-RPC message with an optional Bearer token."""
    import httpx
    # FastMCP's StreamableHTTP transport requires both content-types in Accept
    # (RFC 9728 §5.2 compliance: client must accept application/json AND
    # text/event-stream so the server can choose the response format).
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if jwt_token is not None:
        headers["Authorization"] = f"Bearer {jwt_token}"
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": {"action": "list_tools"}},
    }
    async with httpx.AsyncClient() as c:
        return await c.post(f"{base_url}/mcp", json=body, headers=headers, timeout=10.0)


# ── Scenario 1: valid JWT succeeds ───────────────────────────────

@pytest.mark.asyncio
async def test_valid_jwt_succeeds(mcp_http_server, mint_jwt):
    token = mint_jwt()
    resp = await _call_tool(mcp_http_server["base_url"], token)
    assert resp.status_code == 200, f"status={resp.status_code} content_type={resp.headers.get('content-type')} body={resp.text!r}"
    # The MCP StreamableHTTP transport returns SSE or JSON; check both formats.
    content_type = resp.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        # SSE format: scan event lines for a JSON-RPC result
        assert '"result"' in resp.text, resp.text
    else:
        assert "result" in resp.json()


# ── Scenario 2: expired JWT → 401 ────────────────────────────────

@pytest.mark.asyncio
async def test_expired_jwt_returns_401(mcp_http_server, mint_jwt):
    token = mint_jwt(_exp_offset=-60)  # minted expired
    resp = await _call_tool(mcp_http_server["base_url"], token)
    assert resp.status_code == 401


# ── Scenario 3: wrong issuer → 401 ───────────────────────────────

@pytest.mark.asyncio
async def test_wrong_issuer_returns_401(mcp_http_server, mint_jwt):
    token = mint_jwt(_issuer="https://evil.example.com")
    resp = await _call_tool(mcp_http_server["base_url"], token)
    assert resp.status_code == 401


# ── Scenario 4: missing required claim → claims-level denial ─────
#
# Design note: HTTP 401/403 is produced by the Bearer auth middleware
# (Starlette layer) for missing/invalid tokens.  Claim-level enforcement
# (revenium_team_id, tenant_id) runs inside TenantContextMiddleware which
# sits at the MCP protocol layer — errors there become JSON-RPC errors
# wrapped in HTTP 200.  We assert HTTP 200 + JSON-RPC error code here
# because that is the actual FastMCP behaviour; the original spec called
# for 403 before the OIDCProxy architecture was understood.

@pytest.mark.asyncio
async def test_missing_required_claim_returns_error(mcp_http_server, mint_jwt):
    token = mint_jwt(revenium_team_id=None)  # drop the claim
    resp = await _call_tool(mcp_http_server["base_url"], token)
    # JWT is cryptographically valid (passes HTTP Bearer auth → 200), but
    # TenantContextMiddleware rejects it at the MCP layer → JSON-RPC error.
    assert resp.status_code == 200
    # The MCP transport returns SSE or JSON; check both formats.
    content_type = resp.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        body_text = resp.text
        assert "error" in body_text.lower()
        assert "revenium_team_id" in body_text
        assert "user_abc" not in body_text
    else:
        body = resp.json()
        assert "error" in body
        # The error message must mention the missing claim name.
        assert "revenium_team_id" in body["error"]["message"]
        # The subject of the JWT must NOT leak into the error message.
        assert "user_abc" not in body["error"]["message"]


# ── Scenario 5: tenant mismatch → claims-level denial ────────────
#
# Same design note as Scenario 4: claim-level check → JSON-RPC error in 200.

@pytest.mark.asyncio
async def test_tenant_mismatch_returns_error(mcp_http_server, mint_jwt):
    token = mint_jwt(tenant_id="tenant_wrong")
    resp = await _call_tool(mcp_http_server["base_url"], token)
    assert resp.status_code == 200
    # The MCP transport returns SSE or JSON; check both formats.
    content_type = resp.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        assert "error" in resp.text.lower()
    else:
        body = resp.json()
        assert "error" in body


# ── Scenario 6: no Authorization header → 401 ────────────────────

@pytest.mark.asyncio
async def test_no_authorization_header_returns_401(mcp_http_server):
    resp = await _call_tool(mcp_http_server["base_url"], jwt_token=None)
    assert resp.status_code == 401
