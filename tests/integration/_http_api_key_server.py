"""In-process HTTP MCP server fixture for AUTH_MODE=api_key E2E tests.

Modelled on _http_clerk_server.py but replaces OIDC/JWT with the
ApiKeyTokenVerifier + ApiKeyAuthMiddleware path.

Contract:
    The fixture ``mcp_http_server`` depends on a fixture named
    ``api_key_and_revenium_mock`` which the consuming test module must define.
    ``api_key_and_revenium_mock`` returns a dict with keys:
        - platform_base_url: URL where the mock /profitstream/v2/api/users/me is served
        - revenium_base_url:  URL where the (mocked) Revenium API is served
        - httpserver:         the pytest-httpserver instance (for log inspection)

    This module does not register any Revenium API routes itself — the
    consumer's ``api_key_and_revenium_mock`` is responsible for that.

Mocking /users/me:
    ApiKeyValidator calls get_shared_http_client() (lru_cache singleton) to
    issue GET /profitstream/v2/api/users/me with an x-api-key header.  We clear
    the cache and point the validator at the pytest-httpserver's origin
    (REVENIUM_BASE_URL, the single base URL the validator and downstream calls
    share) so the validator's plain-HTTP call lands on our mock without any
    patching of internal httpx transport.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest


@asynccontextmanager
async def _run_mcp_http_server(mock, monkeypatch, unused_tcp_port, *, server_creds: bool):
    """Boot the MCP server (HTTP + api_key auth) against the caller's mock.

    server_creds=False (default fixture): no server-wide Revenium credential
    is configured — every downstream data-plane call must authenticate with
    the per-request bearer resolved by the auth middleware.

    server_creds=True: a server-wide credential IS present in the env. The
    downstream calls must STILL use the per-request bearer; the server-wide
    key must never appear in outgoing requests (anti cross-tenant leak).
    """
    monkeypatch.setenv("AUTH_MODE", "api_key")
    monkeypatch.setenv("TRANSPORT_MODE", "http")
    monkeypatch.setenv("MCP_SERVER_BASE_URL", "https://mcp.test.io")
    monkeypatch.setenv("REVENIUM_BASE_URL", mock["revenium_base_url"])
    monkeypatch.setenv("REVENIUM_ALLOW_HTTP", "1")
    monkeypatch.setenv("API_KEY_CACHE_TTL_SECONDS", "30")
    monkeypatch.setenv("TOOL_PROFILE", "business")

    # Clear the shared HTTP client cache so ApiKeyValidator gets a fresh
    # client that resolves against the current test's mock server URL.
    from revenium_mcp_server.client import get_shared_http_client

    get_shared_http_client.cache_clear()

    # Clear the ConfigManager singleton's config cache so that ReveniumClient()
    # re-reads REVENIUM_BASE_URL from the monkeypatched env instead of using a
    # value that was cached during a previous test or at import time.
    from revenium_mcp_server.auth import ConfigManager

    ConfigManager().clear_cache()

    from revenium_mcp_server.auth.api_key_validator import ApiKeyValidator
    from revenium_mcp_server.auth.api_key_middleware import (
        ApiKeyAuthMiddleware,
        ApiKeyTokenVerifier,
    )
    from revenium_mcp_server.enhanced_server import (
        create_enhanced_server,
        register_tools,
    )

    api_key_validator = ApiKeyValidator(
        platform_base_url=mock["platform_base_url"],
        ttl_seconds=30,
    )
    token_verifier = ApiKeyTokenVerifier(
        validator=api_key_validator,
        base_url="https://mcp.test.io",
    )

    mcp = create_enhanced_server(auth=token_verifier)

    # Credential env handling AFTER create_enhanced_server(): both the package
    # import above and create_enhanced_server() itself call
    # load_dotenv(override=False), either of which re-injects the repo .env
    # values into os.environ and would silently undo an earlier delenv. Applying
    # the env state and clearing the ConfigManager cache here — after the last
    # load_dotenv but before the server handles requests — guarantees the
    # server_creds=False harness genuinely runs without a server-wide credential
    # (and is not made to pass for the wrong reason on a developer machine with
    # a populated .env). Credentials are read lazily per request, so applying
    # them after server creation is safe.
    if server_creds:
        monkeypatch.setenv("REVENIUM_API_KEY", "hak_server_wide")
        monkeypatch.setenv("REVENIUM_TEAM_ID", "team_server_wide")
        monkeypatch.setenv("REVENIUM_TENANT_ID", "tenant_server_wide")
    else:
        monkeypatch.delenv("REVENIUM_API_KEY", raising=False)
        monkeypatch.delenv("REVENIUM_TEAM_ID", raising=False)
        monkeypatch.delenv("REVENIUM_TENANT_ID", raising=False)
    ConfigManager().clear_cache()

    mcp.add_middleware(ApiKeyAuthMiddleware(api_key_validator))
    await register_tools(mcp)

    server_task: asyncio.Task | None = None

    async def _start() -> None:
        nonlocal server_task
        server_task = asyncio.create_task(
            mcp.run_async(
                transport="http",
                host="127.0.0.1",
                port=unused_tcp_port,
                show_banner=False,
                stateless_http=True,
            )
        )
        for _ in range(50):
            try:
                async with httpx.AsyncClient() as c:
                    await c.get(
                        f"http://127.0.0.1:{unused_tcp_port}/mcp",
                        timeout=0.5,
                    )
                    return
            except Exception:
                await asyncio.sleep(0.2)
        raise RuntimeError("MCP server did not bind within timeout")

    await _start()
    try:
        yield {
            "base_url": f"http://127.0.0.1:{unused_tcp_port}",
            "httpserver": mock["httpserver"],
            # Expose the validator so tests can inspect cached identities.
            "api_key_validator": api_key_validator,
        }
    finally:
        if server_task:
            server_task.cancel()
            try:
                await server_task
            except (asyncio.CancelledError, Exception):
                pass
        # Restore the shared client cache and ConfigManager to a clean state.
        get_shared_http_client.cache_clear()
        from revenium_mcp_server.auth import ConfigManager
        ConfigManager().clear_cache()


@pytest.fixture
async def mcp_http_server(api_key_and_revenium_mock, monkeypatch, unused_tcp_port):
    """HTTP/api_key server with NO server-wide Revenium credential."""
    async with _run_mcp_http_server(
        api_key_and_revenium_mock, monkeypatch, unused_tcp_port, server_creds=False
    ) as server:
        yield server


@pytest.fixture
async def mcp_http_server_with_server_creds(
    api_key_and_revenium_mock, monkeypatch, unused_tcp_port
):
    """HTTP/api_key server WITH a server-wide credential present in the env."""
    async with _run_mcp_http_server(
        api_key_and_revenium_mock, monkeypatch, unused_tcp_port, server_creds=True
    ) as server:
        yield server


async def call_mcp_tool(
    base_url: str,
    api_token: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> httpx.Response:
    """POST a tools/call JSON-RPC message with a Bearer token."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {api_token}",
    }
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    async with httpx.AsyncClient() as c:
        return await c.post(
            f"{base_url}/mcp", json=body, headers=headers, timeout=15.0
        )


async def call_mcp_tool_no_auth(
    base_url: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> httpx.Response:
    """POST a tools/call JSON-RPC message WITHOUT an Authorization header."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    async with httpx.AsyncClient() as c:
        return await c.post(
            f"{base_url}/mcp", json=body, headers=headers, timeout=10.0
        )
