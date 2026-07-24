"""Integration tests for the full Clerk OAuth flow (BACK-853).

A local pytest-httpserver stands in for the Clerk OIDC discovery endpoint
and the JWKS endpoint. JWTs are minted locally with a generated RSA keypair
and signed as Clerk would. FastMCP's OIDCProxy discovers the keys from the
fixture server and validates signatures against them.

Shared Clerk fixtures are imported from _clerk_fixtures so they can be
reused across BACK-865/866/867.
"""
from __future__ import annotations

import asyncio

import pytest

# fake_clerk / mint_jwt / test_keypair are provided via conftest.py re-export
# (avoids Ruff F811 from importing fixture names used as parameters).


# ── MCP server fixture ───────────────────────────────────────────

@pytest.fixture
def fake_downstream():
    """Stand-in for the downstream Revenium platform API."""
    from pytest_httpserver import HTTPServer

    server = HTTPServer()
    server.start()
    yield server
    server.stop()


@pytest.fixture
async def mcp_http_server(fake_clerk, fake_downstream, monkeypatch, unused_tcp_port):
    """Spin up the MCP server with a JWTVerifier (backed by fake Clerk JWKS).

    Uses JWTVerifier directly instead of OIDCProxy so that tests can present
    raw upstream JWTs in the Authorization header.  OIDCProxy implements a
    full token-swap flow (FastMCP-issued reference token + JTI store) that is
    incompatible with directly-minted test JWTs.
    """
    monkeypatch.setenv("AUTH_MODE", "clerk")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_default")
    # Allow http:// base_url for this test fixture (TenantContext._valid_url
    # otherwise rejects plaintext URLs).
    monkeypatch.setenv("REVENIUM_ALLOW_HTTP", "1")
    monkeypatch.setenv("REVENIUM_BASE_URL", fake_downstream.url_for("").rstrip("/"))

    from fastmcp.server.auth.providers.jwt import JWTVerifier

    from revenium_mcp_server.auth.claims_middleware import TenantContextMiddleware
    from revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver
    from revenium_mcp_server.enhanced_server import create_enhanced_server, register_tools

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


# ── Scenario 5: two tenants on one deployment resolve independently ──

@pytest.mark.asyncio
async def test_two_tenants_succeed_on_same_server(mcp_http_server, mint_jwt):
    resp_a = await _call_tool(mcp_http_server["base_url"], mint_jwt(tenant_id="tenant_a"))
    resp_b = await _call_tool(mcp_http_server["base_url"], mint_jwt(tenant_id="tenant_b"))
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    for resp in (resp_a, resp_b):
        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            assert '"result"' in resp.text, resp.text
        else:
            assert "result" in resp.json()


# ── Scenario 6: no Authorization header → 401 ────────────────────

@pytest.mark.asyncio
async def test_no_authorization_header_returns_401(mcp_http_server):
    resp = await _call_tool(mcp_http_server["base_url"], jwt_token=None)
    assert resp.status_code == 401


# ── Scenario 7: downstream calls carry the caller's JWT, not x-api-key ──

async def _call_tool_action(base_url: str, jwt_token: str, tool: str, action: str) -> "httpx.Response":
    import httpx
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {jwt_token}",
    }
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": {"action": action}},
    }
    async with httpx.AsyncClient() as c:
        return await c.post(f"{base_url}/mcp", json=body, headers=headers, timeout=15.0)


@pytest.mark.asyncio
async def test_downstream_call_forwards_bearer_jwt(mcp_http_server, mint_jwt, fake_downstream):
    fake_downstream.expect_request("/profitstream/v2/api/products").respond_with_json(
        {"_embedded": {"products": []}, "page": {"totalElements": 0}}
    )
    token = mint_jwt()
    await _call_tool_action(
        mcp_http_server["base_url"], token, tool="manage_products", action="list"
    )
    assert fake_downstream.log, "no downstream request was made"
    req, _ = fake_downstream.log[0]
    assert req.headers.get("Authorization") == f"Bearer {token}"
    assert "x-api-key" not in req.headers


# ── Scenario 8: audience mismatch → 401 ──────────────────────────

@pytest.mark.asyncio
async def test_wrong_audience_returns_401(mcp_http_server, mint_jwt):
    token = mint_jwt(_audience="some-other-oauth-app")
    resp = await _call_tool(mcp_http_server["base_url"], token)
    assert resp.status_code == 401


# ── Scenario 9: matching audience accepted (guards scenario 8 against
#    false positives from unrelated 401 causes) ───────────────────

@pytest.mark.asyncio
async def test_matching_audience_succeeds(mcp_http_server, mint_jwt):
    token = mint_jwt(_audience="test-client")
    resp = await _call_tool(mcp_http_server["base_url"], token)
    assert resp.status_code == 200


# ── Scenario 10: MCP endpoint rate limit returns 429 ─────────────

@pytest.mark.asyncio
async def test_mcp_rate_limit_returns_429(fake_clerk, monkeypatch, unused_tcp_port, mint_jwt):
    monkeypatch.setenv("AUTH_MODE", "clerk")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_default")
    monkeypatch.setenv("REVENIUM_ALLOW_HTTP", "1")
    monkeypatch.setenv("REVENIUM_BASE_URL", "http://127.0.0.1:1")

    from fastmcp.server.auth.providers.jwt import JWTVerifier
    from starlette.middleware import Middleware

    from revenium_mcp_server.auth.claims_middleware import TenantContextMiddleware
    from revenium_mcp_server.auth.rate_limit import RateLimitMiddleware
    from revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver
    from revenium_mcp_server.enhanced_server import create_enhanced_server, register_tools

    jwt_verifier = JWTVerifier(
        jwks_uri=fake_clerk["jwks_url"],
        issuer=fake_clerk["issuer"],
        audience="test-client",
        algorithm="RS256",
    )
    mcp = create_enhanced_server(auth=jwt_verifier)
    mcp.add_middleware(TenantContextMiddleware(ClerkTenantResolver()))
    await register_tools(mcp)

    import asyncio

    server_task = asyncio.create_task(
        mcp.run_async(
            transport="http",
            host="127.0.0.1",
            port=unused_tcp_port,
            show_banner=False,
            stateless_http=True,
            middleware=[Middleware(RateLimitMiddleware, mcp_limit=2, auth_limit=2)],
        )
    )
    try:
        base_url = f"http://127.0.0.1:{unused_tcp_port}"
        import httpx
        for _ in range(50):
            try:
                async with httpx.AsyncClient() as c:
                    await c.get(f"{base_url}/mcp", timeout=0.5)
                break
            except Exception:
                await asyncio.sleep(0.2)
        token = mint_jwt()
        statuses = []
        for _ in range(4):
            resp = await _call_tool(base_url, token)
            statuses.append(resp.status_code)
        assert 429 in statuses, statuses
    finally:
        server_task.cancel()
        try:
            await server_task
        except (asyncio.CancelledError, Exception):
            pass
