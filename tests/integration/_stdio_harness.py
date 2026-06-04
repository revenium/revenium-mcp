"""Stdio harness — spawns the packaged revenium-mcp binary as a subprocess
and returns a FastMCP Client wired up to talk to it.

Used by tests/integration/test_stdio_env_regression.py.
"""
from __future__ import annotations

import os
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


def build_stdio_client(mock_base_url: str, extra_env: dict[str, str] | None = None) -> Client[Any]:
    """Build a FastMCP Client that spawns revenium-mcp as a subprocess in env-auth/stdio mode.

    Args:
        mock_base_url: URL of the pytest-httpserver fake Revenium API
                       (e.g. "http://127.0.0.1:12345")
        extra_env: additional env vars to merge into the subprocess environment

    Returns:
        A Client ready to be used as `async with client:`.
    """
    env: dict[str, str] = {
        # subprocess env= fully REPLACES the child environment, so inherit the
        # parent's (PATH, HOME, SSL_CERT_FILE, …) or the spawned server may fail
        # to boot or do TLS/config lookups.
        **os.environ,
        "AUTH_MODE": "env",
        # Pin the transport explicitly so a stray local .env (e.g.
        # TRANSPORT_MODE=http) cannot flip the spawned server to HTTP and break
        # the stdio handshake.
        "TRANSPORT_MODE": "stdio",
        "REVENIUM_API_KEY": "hak_test_e2e",
        "REVENIUM_TEAM_ID": "team_test",
        "REVENIUM_TENANT_ID": "tenant_test",
        "REVENIUM_BASE_URL": mock_base_url,
        "REVENIUM_APP_BASE_URL": mock_base_url,
        # Disable any optional onboarding/discovery network probes.
        "REVENIUM_OWNER_ID": "owner_test",
        "REVENIUM_DEFAULT_EMAIL": "test@example.com",
        # Use the full business profile so all anchor tools are registered.
        # Default is "starter" (7 tools); regression tests need the full set.
        "TOOL_PROFILE": "business",
    }
    if extra_env:
        env.update(extra_env)

    transport = StdioTransport(
        command="revenium-mcp",
        args=[],
        env=env,
    )
    return Client(transport, init_timeout=30.0)
