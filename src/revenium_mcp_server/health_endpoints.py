"""HTTP /health (liveness) and /ready (readiness) endpoints for the MCP server.

These endpoints are auth-exempt by FastMCP design: custom routes added via
``@mcp.custom_route`` are appended outside ``RequireAuthMiddleware``
(see ``fastmcp/server/http.py:328-353``). Calling
``register_health_endpoints(mcp)`` once during server construction is enough;
no extra opt-out is required for clerk mode.

In stdio mode the routes are registered but never reachable (no HTTP server
binds). This matches FastMCP's native pattern and keeps
``create_enhanced_server`` free of transport branching.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

if TYPE_CHECKING:
    from fastmcp import FastMCP


PROBE_TTL_SECONDS = 10.0
PROBE_TIMEOUT_SECONDS = 3.0

# Closed enum of /ready failure reasons exposed to unauthenticated callers.
# Operators triage from logs; the wire body stays minimal.
_REASON_UNREACHABLE = "revenium_api_unreachable"
_REASON_AUTH = "auth_failed"
_REASON_TIMEOUT = "timeout"


@dataclass(frozen=True)
class _ProbeResult:
    ok: bool
    reason: str | None  # None when ok=True
    expires_at: float  # time.monotonic() ceiling for this cached result


# Module-level cache state. Tests zero this via the reset_health_cache
# autouse fixture; production wires through the asyncio.Lock to avoid
# thundering-herd probes when TTL expires under concurrent traffic.
_last_probe: _ProbeResult | None = None
_probe_lock = asyncio.Lock()


def _expires_at() -> float:
    return time.monotonic() + PROBE_TTL_SECONDS


async def _probe_platform_reachable() -> _ProbeResult:
    """HEAD the platform base URL with a tight timeout. No key required.

    Any HTTP response (even 401/404) proves the host is reachable, which is all
    readiness needs in api_key mode (per-request keys are validated per call).
    """
    base = os.getenv("REVENIUM_BASE_URL", "").strip().rstrip("/")
    if not base:
        return _ProbeResult(False, _REASON_UNREACHABLE, _expires_at())

    from .client import get_shared_http_client

    try:
        await asyncio.wait_for(
            get_shared_http_client().head(base),
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return _ProbeResult(False, _REASON_TIMEOUT, _expires_at())
    except Exception:
        return _ProbeResult(False, _REASON_UNREACHABLE, _expires_at())
    return _ProbeResult(True, None, _expires_at())


async def _probe_revenium() -> _ProbeResult:
    """Probe Revenium readiness.

    env: authenticated /users/me validation via the env-baked key.
    clerk/api_key: no server-wide key exists (credentials are per-request),
    so probe platform base-URL reachability only.
    Never raises.
    """
    from .auth.auth_mode import read_auth_mode

    if read_auth_mode() in ("api_key", "clerk"):
        return await _probe_platform_reachable()

    from .client import ReveniumClient

    try:
        result = await asyncio.wait_for(
            ReveniumClient().validate_api_key(),
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return _ProbeResult(False, _REASON_TIMEOUT, _expires_at())
    except Exception:
        # Defence in depth: validate_api_key already classifies HTTP/connect
        # errors into the dict it returns. Reaching this branch means
        # something more fundamental broke (DNS, TLS, library bug,
        # misconfigured client). Treat as unreachable.
        return _ProbeResult(False, _REASON_UNREACHABLE, _expires_at())

    if result["valid"]:
        return _ProbeResult(True, None, _expires_at())
    status = result.get("status_code")
    reason = _REASON_AUTH if status in (401, 403) else _REASON_UNREACHABLE
    return _ProbeResult(False, reason, _expires_at())


async def _get_ready_status() -> _ProbeResult:
    """Return the current readiness, probing Revenium at most once per TTL.

    Fast path: cache hit returns immediately without taking the lock.
    Slow path: lock + double-check so N concurrent callers trigger exactly
    one probe.
    """
    global _last_probe
    now = time.monotonic()
    if _last_probe is not None and _last_probe.expires_at > now:
        return _last_probe
    async with _probe_lock:
        if _last_probe is not None and _last_probe.expires_at > time.monotonic():
            return _last_probe
        _last_probe = await _probe_revenium()
        return _last_probe


def register_health_endpoints(mcp: "FastMCP") -> None:
    """Register ``GET /health`` and ``GET /ready`` on ``mcp``.

    Both routes are auth-exempt by FastMCP design (custom routes are
    appended outside ``RequireAuthMiddleware``). Safe to call in env mode
    and clerk mode alike.
    """

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> Response:
        return JSONResponse({"status": "healthy"})

    @mcp.custom_route("/ready", methods=["GET"])
    async def ready(request: Request) -> Response:
        result = await _get_ready_status()
        if result.ok:
            return JSONResponse({"status": "ready"})
        return JSONResponse(
            {"status": "not_ready", "reason": result.reason},
            status_code=503,
        )
