"""The hosted endpoint answers /mcp and /mcp/ directly and keeps https behind the proxy (BACK-5049)."""

from __future__ import annotations

import pytest
import uvicorn
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient

from src.revenium_mcp_server.http_transport import (
    DEFAULT_FORWARDED_ALLOW_IPS,
    McpPathAliasMiddleware,
    build_http_middleware,
    build_uvicorn_config,
)

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "back-5049", "version": "1.0"},
    },
}
MCP_HEADERS = {"accept": "application/json, text/event-stream"}


def _server() -> FastMCP:
    mcp = FastMCP("back-5049")

    @mcp.custom_route("/probe", methods=["GET"])
    async def probe(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    return mcp


def _app():
    return _server().http_app(middleware=build_http_middleware())


def _behind_proxy(app):
    config = uvicorn.Config(app, **build_uvicorn_config())
    config.load()
    return config.loaded_app


@pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
def test_both_endpoint_spellings_answer_the_handshake_without_a_redirect(path):
    with TestClient(_app(), base_url="https://mcp.example.test") as client:
        response = client.post(
            path, json=INITIALIZE, headers=MCP_HEADERS, follow_redirects=False
        )

    assert response.status_code == 200
    assert "location" not in response.headers
    assert '"serverInfo"' in response.text


def test_a_redirect_built_behind_the_proxy_keeps_the_forwarded_https_scheme(
    monkeypatch,
):
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    with TestClient(
        _behind_proxy(_app()), base_url="http://mcp.example.test"
    ) as client:
        response = client.get(
            "/probe/", headers={"x-forwarded-proto": "https"}, follow_redirects=False
        )

    assert response.status_code == 307
    assert response.headers["location"] == "https://mcp.example.test/probe"


def test_an_untrusted_peer_cannot_set_the_scheme(monkeypatch):
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "10.0.0.1")
    with TestClient(
        _behind_proxy(_app()), base_url="http://mcp.example.test"
    ) as client:
        response = client.get(
            "/probe/", headers={"x-forwarded-proto": "https"}, follow_redirects=False
        )

    assert response.headers["location"] == "http://mcp.example.test/probe"


def test_the_proxy_is_trusted_by_default(monkeypatch):
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)

    assert build_uvicorn_config() == {
        "proxy_headers": True,
        "forwarded_allow_ips": DEFAULT_FORWARDED_ALLOW_IPS,
    }


def test_the_path_alias_runs_before_the_rate_limiter(monkeypatch):
    monkeypatch.delenv("MCP_RATE_LIMIT_PER_MINUTE", raising=False)
    monkeypatch.delenv("MCP_AUTH_RATE_LIMIT_PER_MINUTE", raising=False)

    middleware = build_http_middleware()

    assert middleware[0].cls is McpPathAliasMiddleware
    assert len(middleware) == 2


def test_the_rate_limiter_can_be_disabled_without_losing_the_alias(monkeypatch):
    monkeypatch.setenv("MCP_RATE_LIMIT_PER_MINUTE", "0")
    monkeypatch.setenv("MCP_AUTH_RATE_LIMIT_PER_MINUTE", "0")

    assert [m.cls for m in build_http_middleware()] == [McpPathAliasMiddleware]


async def test_the_alias_leaves_other_paths_untouched():
    seen: list[str] = []

    async def app(scope, receive, send):
        seen.append(scope["path"])

    alias = McpPathAliasMiddleware(app, mcp_path="/mcp")
    for path in ("/mcp/", "/mcp", "/mcp/extra", "/probe/"):
        await alias(
            {"type": "http", "path": path, "raw_path": path.encode()}, None, None
        )

    assert seen == ["/mcp", "/mcp", "/mcp/extra", "/probe/"]
