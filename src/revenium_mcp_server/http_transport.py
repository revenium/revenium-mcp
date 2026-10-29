"""HTTP transport wiring: the ASGI middleware list and the uvicorn settings.

BACK-5049: behind the load balancer a call to ``/mcp/`` was answered with
Starlette's trailing-slash redirect, built from the scheme uvicorn saw (plain
http), so https clients were sent to an http URL. Both halves are fixed here,
in the application, so the fix holds whatever proxy fronts the server.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Optional

import fastmcp
from starlette.middleware import Middleware

from .auth.rate_limit import build_rate_limit_middleware

DEFAULT_FORWARDED_ALLOW_IPS = "*"


class McpPathAliasMiddleware:
    """Serve ``<mcp_path>/`` as ``<mcp_path>`` instead of redirecting to it."""

    def __init__(self, app: Callable, *, mcp_path: str) -> None:
        self._app = app
        self._mcp_path = mcp_path.rstrip("/")
        self._alias = self._mcp_path + "/"

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") == "http" and scope.get("path") == self._alias:
            scope = {
                **scope,
                "path": self._mcp_path,
                "raw_path": self._mcp_path.encode(),
            }
        await self._app(scope, receive, send)


def mcp_endpoint_path() -> str:
    return fastmcp.settings.streamable_http_path


def build_http_middleware() -> list[Middleware]:
    """Path alias first so the rate limiter and the router both see the canonical path."""
    alias = Middleware(McpPathAliasMiddleware, mcp_path=mcp_endpoint_path())
    rate_limit: Optional[list[Middleware]] = build_rate_limit_middleware()
    return [alias, *(rate_limit or [])]


def build_uvicorn_config() -> dict[str, Any]:
    """Trust the fronting proxy's X-Forwarded-Proto so absolute URLs keep https.

    uvicorn trusts only 127.0.0.1 by default, but the load balancer reaches the
    hosted task from its own subnet address, so every peer is trusted unless
    FORWARDED_ALLOW_IPS narrows the list where the network does not.
    """
    return {
        "proxy_headers": True,
        "forwarded_allow_ips": os.getenv("FORWARDED_ALLOW_IPS")
        or DEFAULT_FORWARDED_ALLOW_IPS,
    }
