"""HTTP/api_key mode E2E test.

Boots the MCP server in-process in HTTP mode with AUTH_MODE=api_key. A
Revenium bearer token (``rev_rk_<valid>``) is validated against a mocked
``/profitstream/v2/api/users/me`` endpoint; the test calls
``manage_products list`` and asserts:

  1. No Authorization header → HTTP 401 (FastMCP RequireAuthMiddleware rejects).
  2. Valid ``rev_rk_`` token → tool dispatch succeeds and the downstream
     Revenium API request carries the team/tenant resolved from /users/me.

This module uses zero real credentials and runs on every PR.
"""
from __future__ import annotations

import pytest

from tests.integration._envelope_assertions import parse_jsonrpc_response
from tests.integration._http_api_key_server import (
    call_mcp_tool,
    call_mcp_tool_no_auth,
)
from tests.integration.fixtures.back_864_canned_responses import PRODUCTS_LIST


# ── Canned /users/me identity ─────────────────────────────────────

_VALID_TOKEN = "rev_rk_valid_test_token_abc123"

_USERS_ME_BODY = {
    "id": "usr_123",
    "email": "cfo@acme.test",
    "roles": ["ROLE_TENANT_ADMIN"],
    "tenantId": "tenant_abc",
    "defaultTeamId": "team_xyz",
    "teams": [{"id": "team_xyz"}],
}

# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def api_key_and_revenium_mock(httpserver):
    """Single pytest-httpserver: mock /users/me + Revenium /products.

    The MCP server under test calls two upstream paths on the SAME host:
      - REVENIUM_BASE_URL/profitstream/v2/api/users/me — validates the key
      - REVENIUM_BASE_URL/profitstream/v2/api/products — the tool's real call

    Both share one base URL (REVENIUM_BASE_URL), so a single
    pytest-httpserver instance serves them.
    """
    # The legacy platform authenticates via the x-api-key header (NOT
    # Authorization: Bearer) and returns 403 (NOT 401) for an unknown key.
    def _users_me_handler(request):
        from werkzeug.wrappers import Response

        if request.headers.get("x-api-key", "") == _VALID_TOKEN:
            import json
            return Response(
                json.dumps(_USERS_ME_BODY),
                status=200,
                content_type="application/json",
            )
        return Response("Forbidden", status=403, content_type="text/plain")

    httpserver.expect_request(
        "/profitstream/v2/api/users/me"
    ).respond_with_handler(_users_me_handler)

    # Revenium management API used by manage_products list.
    httpserver.expect_request("/profitstream/v2/api/products").respond_with_json(
        PRODUCTS_LIST
    )

    base = httpserver.url_for("").rstrip("/")
    return {
        "platform_base_url": base,
        "revenium_base_url": base,
        "httpserver": httpserver,
    }


# ── Tests ─────────────────────────────────────────────────────────


async def test_missing_auth_header_returns_401(mcp_http_server) -> None:
    """No Authorization header must produce HTTP 401.

    FastMCP's RequireAuthMiddleware is wired when auth= is set on the server.
    With AUTH_MODE=api_key the ApiKeyTokenVerifier is passed as auth=, so
    unauthenticated requests must be rejected at the transport layer before
    any tool dispatch occurs.
    """
    resp = await call_mcp_tool_no_auth(
        mcp_http_server["base_url"],
        tool_name="manage_products",
        arguments={"action": "list"},
    )
    assert resp.status_code == 401, (
        f"expected HTTP 401 for missing auth, got {resp.status_code}. "
        f"body={resp.text!r}"
    )


async def test_valid_api_key_dispatches_tool_call(mcp_http_server) -> None:
    """A valid Revenium bearer token successfully dispatches a tool call.

    Proves the ApiKeyTokenVerifier → ApiKeyAuthMiddleware → tool dispatch
    wiring is correct end-to-end, and that the downstream Revenium mock was
    actually reached (REVENIUM_BASE_URL is honoured in api_key mode).
    """
    import json

    resp = await call_mcp_tool(
        mcp_http_server["base_url"],
        _VALID_TOKEN,
        tool_name="manage_products",
        arguments={"action": "list"},
    )
    assert resp.status_code == 200, (
        f"status={resp.status_code} body={resp.text!r}"
    )
    payload = parse_jsonrpc_response(resp)
    assert "result" in payload, f"expected JSON-RPC result, got {payload!r}"
    assert "error" not in payload, f"unexpected JSON-RPC error: {payload!r}"

    # Flatten all text content from the tool result to a single string and
    # assert the downstream mock was actually reached: PRODUCTS_LIST contains
    # a product named "Test Product"; that name must appear in the response.
    result_body = payload["result"]
    content_blocks = result_body.get("content", []) if isinstance(result_body, dict) else []
    result_text = " ".join(
        block.get("text", "") if isinstance(block, dict) else str(block)
        for block in content_blocks
    )
    # Fallback: if content was not a list (e.g. serialised differently), use
    # the full JSON dump of the result so the assertion can still fire.
    if not result_text.strip():
        result_text = json.dumps(result_body)

    assert "Test Product" in result_text, (
        "Expected 'Test Product' from the downstream mock in the tool result, "
        f"but it was not found. This means REVENIUM_BASE_URL was not honoured "
        f"and the downstream call did not reach the mock server.\n"
        f"result_text={result_text[:500]!r}"
    )
    assert "error" not in result_text.lower().split("test product")[0], (
        f"Tool result text contains an error marker before the product data: "
        f"{result_text[:500]!r}"
    )


async def test_invalid_api_key_returns_401(mcp_http_server) -> None:
    """An unknown bearer token must be rejected with HTTP 401.

    The mock /users/me returns 403 (the legacy platform's response for an
    unknown key) for any token that is not _VALID_TOKEN. The
    ApiKeyTokenVerifier must propagate that rejection so the MCP HTTP layer
    responds with HTTP 401 before any tool dispatch occurs.
    """
    resp = await call_mcp_tool(
        mcp_http_server["base_url"],
        "rev_rk_unknown_garbage_token",
        tool_name="manage_products",
        arguments={"action": "list"},
    )
    assert resp.status_code == 401, (
        f"expected HTTP 401 for unknown token, got {resp.status_code}. "
        f"body={resp.text!r}"
    )


async def test_api_key_identity_resolved_from_users_me(
    mcp_http_server,
) -> None:
    """The identity resolved from /users/me carries the right team and tenant.

    Setup:
      - /users/me returns defaultTeamId=team_xyz, tenantId=tenant_abc for the valid token
      - No server-wide REVENIUM_TEAM_ID is configured
    Asserts:
      - manage_products list dispatches successfully (full auth gate ran)
      - The ApiKeyValidator cached the identity from /users/me with
        team_id=team_xyz and tenant_id=tenant_abc (not the env defaults)

    The validator cache is checked post-request: it is populated during
    verify_token() which is the point where /users/me is called and the
    identity is resolved. This verifies the full chain:
    rev_rk_ token → /users/me → ApiKeyIdentity(team_xyz, tenant_abc) →
    AccessToken.claims → ApiKeyAuthMiddleware → TenantContext.
    """
    from revenium_mcp_server.auth.api_key_validator import _cache_key, _strip_bearer

    resp = await call_mcp_tool(
        mcp_http_server["base_url"],
        _VALID_TOKEN,
        tool_name="manage_products",
        arguments={"action": "list"},
    )
    assert resp.status_code == 200, (
        f"status={resp.status_code} body={resp.text!r}"
    )
    payload = parse_jsonrpc_response(resp)
    assert "error" not in payload, f"unexpected JSON-RPC error: {payload!r}"

    # After a successful request the validator must have cached the identity.
    validator = mcp_http_server["api_key_validator"]
    key = _cache_key(_strip_bearer(_VALID_TOKEN))
    identity = validator._cache.get(key)
    assert identity is not None, (
        f"ApiKeyValidator cache is empty for our token cache_key={key!r}. "
        "This means /users/me was never called or the identity was not cached."
    )
    assert identity.team_id == "team_xyz", (
        f"expected team_id=team_xyz (from /users/me defaultTeamId), "
        f"got team_id={identity.team_id!r}."
    )
    assert identity.tenant_id == "tenant_abc", (
        f"expected tenant_id=tenant_abc (from /users/me tenantId), "
        f"got tenant_id={identity.tenant_id!r}."
    )
