"""The hosted transport rejects browser requests from unlisted origins (BACK-5052)."""

from __future__ import annotations

import pytest
from fastmcp import FastMCP
from starlette.testclient import TestClient

from src.revenium_mcp_server.middleware.allowed_origins import (
    DEFAULT_ALLOWED_ORIGINS,
    build_allowed_origins,
)

SERVER_BASE_URL = "https://mcp.example.invalid/some/path"
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "origin-test", "version": "0"},
    },
}
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def test_defaults_cover_claude_and_the_inspector_on_localhost():
    assert build_allowed_origins({}) == list(DEFAULT_ALLOWED_ORIGINS)


def test_the_servers_own_origin_and_configured_extras_are_added():
    origins = build_allowed_origins(
        {
            "MCP_SERVER_BASE_URL": SERVER_BASE_URL,
            "REVENIUM_ALLOWED_ORIGINS": " https://ai.dev.hcapp.io , ,https://claude.ai",
        }
    )

    assert origins == [
        *DEFAULT_ALLOWED_ORIGINS,
        "https://mcp.example.invalid",
        "https://ai.dev.hcapp.io",
    ]


def test_a_base_url_without_a_scheme_adds_nothing():
    assert build_allowed_origins(
        {"MCP_SERVER_BASE_URL": "mcp.example.invalid"}
    ) == list(DEFAULT_ALLOWED_ORIGINS)


@pytest.fixture
def hosted_transport():
    app = FastMCP("origin-guard").http_app(
        host_origin_protection="auto",
        allowed_origins=build_allowed_origins({"MCP_SERVER_BASE_URL": SERVER_BASE_URL}),
    )
    with TestClient(app, base_url="https://mcp.example.invalid") as client:
        yield client


def _initialize(client: TestClient, origin: str | None):
    headers = dict(MCP_HEADERS)
    if origin is not None:
        headers["Origin"] = origin
    return client.post("/mcp", json=INITIALIZE, headers=headers)


def test_an_unlisted_origin_is_forbidden(hosted_transport):
    assert _initialize(hosted_transport, "https://evil.example").status_code == 403


@pytest.mark.parametrize(
    "origin",
    [
        pytest.param(None, id="no_origin_header"),
        pytest.param("https://claude.ai", id="claude_ai"),
        pytest.param("https://claude.com", id="claude_com"),
        pytest.param("http://localhost:6274", id="inspector_localhost"),
        pytest.param("http://127.0.0.1:6274", id="inspector_loopback"),
        pytest.param("https://mcp.example.invalid", id="own_origin"),
    ],
)
def test_allowed_callers_reach_the_transport(hosted_transport, origin):
    assert _initialize(hosted_transport, origin).status_code == 200
