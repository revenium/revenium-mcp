"""Smoke test: env+http mode boots and serves an anonymous MCP request.

Validates the AC "Server accepts MCP requests over HTTP/SSE" for the new
env+http path. The clerk+http path is already covered by test_oauth_flow.py.

This test bypasses enhanced_server.main() and composes the server directly
(mirroring the pattern in test_oauth_flow.py) so it doesn't need to stub
out UCM init, API-key validation, onboarding, etc. The wiring inside main()
is exercised by the unit tests in test_transport_mode_startup.py.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest


@pytest.fixture
async def env_http_server(monkeypatch, unused_tcp_port):
    """Build the MCP server with no auth, run it over HTTP, yield base_url."""
    monkeypatch.setenv("AUTH_MODE", "env")
    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_smoke")
    # Avoid the startup API-key validation reaching the real network.
    monkeypatch.setenv("REVENIUM_BASE_URL", "http://127.0.0.1:1")

    from src.revenium_mcp_server.enhanced_server import create_enhanced_server, register_tools

    mcp = create_enhanced_server()  # auth=None
    await register_tools(mcp)

    server_task: asyncio.Task | None = None

    async def _start():
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
        # Poll until the port accepts a connection.
        for _ in range(50):
            try:
                async with httpx.AsyncClient() as c:
                    await c.get(
                        f"http://127.0.0.1:{unused_tcp_port}/mcp",
                        timeout=0.5,
                    )
                    return  # any HTTP response (incl. 405) means the port is bound
            except Exception:
                await asyncio.sleep(0.2)
        raise RuntimeError("MCP server did not bind within timeout")

    await _start()
    try:
        yield {"base_url": f"http://127.0.0.1:{unused_tcp_port}"}
    finally:
        if server_task:
            server_task.cancel()
            try:
                await server_task
            except (asyncio.CancelledError, Exception):
                pass


@pytest.mark.asyncio
async def test_env_http_serves_tools_list_anonymously(env_http_server):
    """env+http accepts an anonymous tools/list JSON-RPC over HTTP."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }
    async with httpx.AsyncClient() as c:
        resp = await asyncio.wait_for(
            c.post(
                f"{env_http_server['base_url']}/mcp",
                json=body,
                headers=headers,
                timeout=10.0,
            ),
            timeout=15.0,
        )

    assert resp.status_code == 200, (
        f"status={resp.status_code} ct={resp.headers.get('content-type')} "
        f"body={resp.text!r}"
    )
    # FastMCP streamable HTTP may respond as SSE or JSON depending on negotiation.
    content_type = resp.headers.get("content-type", "")
    body_text = resp.text
    if "text/event-stream" in content_type:
        assert '"result"' in body_text, body_text
        assert '"tools"' in body_text, body_text
    else:
        payload = resp.json()
        assert "result" in payload, payload
        assert "tools" in payload["result"], payload
        assert len(payload["result"]["tools"]) > 0


@pytest.mark.asyncio
async def test_env_http_serves_health_endpoint(env_http_server):
    """/health responds 200 with healthy status over the real HTTP transport."""
    async with httpx.AsyncClient() as c:
        resp = await asyncio.wait_for(
            c.get(f"{env_http_server['base_url']}/health", timeout=5.0),
            timeout=10.0,
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_env_http_ready_returns_503_when_backend_unreachable(env_http_server):
    """/ready returns 503 with a sanitised reason when Revenium is unreachable.

    The smoke fixture intentionally points REVENIUM_BASE_URL at an
    unreachable address so startup doesn't touch the network. /ready
    correctly reflects that the server can bind but cannot serve traffic.
    """
    async with httpx.AsyncClient() as c:
        resp = await asyncio.wait_for(
            c.get(f"{env_http_server['base_url']}/ready", timeout=5.0),
            timeout=10.0,
        )

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["reason"] in {"revenium_api_unreachable", "timeout"}
    # Body must NOT leak topology.
    assert "base_url" not in body
    assert "127.0.0.1" not in resp.text
