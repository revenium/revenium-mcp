"""E2E: the per-request bearer reaches the downstream Revenium data plane.

Two scenarios against the in-process HTTP/api_key server:

  1. No server-wide credential configured — the downstream /products call
     must authenticate with the per-request bearer (x-api-key == bearer).
  2. A server-wide credential IS configured — the downstream call must STILL
     use the per-request bearer, never the server-wide key (anti
     cross-tenant-leak guarantee).

Zero real credentials; runs on every PR.
"""
from __future__ import annotations

import json

import pytest

from tests.integration._envelope_assertions import parse_jsonrpc_response
from tests.integration._http_api_key_server import call_mcp_tool
from tests.integration.fixtures.back_864_canned_responses import PRODUCTS_LIST

_VALID_TOKEN = "rev_rk_valid_test_token_abc123"

_USERS_ME_BODY = {
    "id": "usr_123",
    "email": "cfo@acme.test",
    "roles": ["ROLE_TENANT_ADMIN"],
    "tenantId": "tenant_abc",
    "defaultTeamId": "team_xyz",
    "teams": [{"id": "team_xyz"}],
}

_PRODUCTS_PATH = "/profitstream/v2/api/products"


@pytest.fixture
def api_key_and_revenium_mock(httpserver):
    """Single pytest-httpserver: mock /users/me + Revenium /products."""

    def _users_me_handler(request):
        from werkzeug.wrappers import Response

        if request.headers.get("x-api-key", "") == _VALID_TOKEN:
            return Response(
                json.dumps(_USERS_ME_BODY),
                status=200,
                content_type="application/json",
            )
        return Response("Forbidden", status=403, content_type="text/plain")

    httpserver.expect_request(
        "/profitstream/v2/api/users/me"
    ).respond_with_handler(_users_me_handler)
    httpserver.expect_request(_PRODUCTS_PATH).respond_with_json(PRODUCTS_LIST)

    base = httpserver.url_for("").rstrip("/")
    return {
        "platform_base_url": base,
        "revenium_base_url": base,
        "httpserver": httpserver,
    }


def _products_requests(httpserver):
    """All requests the downstream mock received on the products path."""
    return [req for req, _resp in httpserver.log if req.path == _PRODUCTS_PATH]


async def _call_products_list(server) -> None:
    resp = await call_mcp_tool(
        server["base_url"],
        _VALID_TOKEN,
        tool_name="manage_products",
        arguments={"action": "list"},
    )
    assert resp.status_code == 200, f"status={resp.status_code} body={resp.text!r}"
    payload = parse_jsonrpc_response(resp)
    assert "error" not in payload, f"unexpected JSON-RPC error: {payload!r}"


async def test_downstream_uses_per_request_bearer(mcp_http_server) -> None:
    """With NO server-wide credential, the data-plane request must carry the
    per-request bearer. Before the dispatch fix this failed with a
    missing-credential error because the cached env client was used."""
    await _call_products_list(mcp_http_server)

    requests = _products_requests(mcp_http_server["httpserver"])
    assert requests, "downstream /products endpoint was never reached"
    for req in requests:
        assert req.headers.get("x-api-key") == _VALID_TOKEN, (
            f"downstream credential mismatch: x-api-key="
            f"{req.headers.get('x-api-key')!r}, expected the request bearer"
        )
        # Tenant identity must also come from the request, not the env.
        assert req.args.get("teamId") == "team_xyz", (
            f"expected teamId=team_xyz (resolved from /users/me), "
            f"got {req.args.get('teamId')!r}"
        )


async def test_server_wide_credential_never_leaks(
    mcp_http_server_with_server_creds,
) -> None:
    """With a server-wide credential PRESENT in the env, the data-plane
    request must STILL carry the per-request bearer — the server-wide key
    must never appear in any outgoing request (cross-tenant-leak guard)."""
    await _call_products_list(mcp_http_server_with_server_creds)

    requests = _products_requests(mcp_http_server_with_server_creds["httpserver"])
    assert requests, "downstream /products endpoint was never reached"
    for req in requests:
        assert req.headers.get("x-api-key") == _VALID_TOKEN
        leaked = [
            (name, value)
            for name, value in req.headers.items()
            if "hak_server_wide" in value
        ]
        assert not leaked, f"server-wide credential leaked downstream: {leaked}"
        assert req.args.get("teamId") == "team_xyz", (
            f"expected teamId=team_xyz from the request identity, "
            f"got {req.args.get('teamId')!r} (team_server_wide would mean "
            f"env leakage)"
        )
        # The server-wide REVENIUM_TENANT_ID must not slip through as a query
        # param either — header-only checks would miss tenantId leakage.
        assert req.args.get("tenantId") != "tenant_server_wide", (
            f"server-wide tenantId leaked as a query param: "
            f"got {req.args.get('tenantId')!r}"
        )
