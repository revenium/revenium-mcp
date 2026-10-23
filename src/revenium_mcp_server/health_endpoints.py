"""HTTP /health (liveness) and /ready (readiness) endpoints for the MCP server.

These endpoints are auth-exempt by FastMCP design: custom routes added via
``@mcp.custom_route`` are appended outside ``RequireAuthMiddleware``
(see ``fastmcp/server/http.py:328-353``). Calling
``register_health_endpoints(mcp)`` once during server construction is enough;
no extra opt-out is required for clerk mode.

``/ready`` answers for the server itself. ``/health`` is liveness and always
answers 200 without waiting on any external call; its body also reports the
platform's answer to a keyless HEAD of the platform root
(``_last_platform_probe``, rendered by ``_platform_state``) in every auth
mode, refreshing it in the background when stale (``_kick_refresh``). That
refresh never sends a key. The platform's status code never affects readiness.
In the api_key and clerk modes ``/ready`` reads the same keyless HEAD
(``_shared_platform_probe``), so a server polled on both routes sends one
platform check per ``PROBE_TTL_SECONDS``.

In stdio mode the routes are registered but never reachable (no HTTP server
binds). This matches FastMCP's native pattern and keeps
``create_enhanced_server`` free of transport branching.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, TypeGuard

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
    status_code: int | None = None  # platform HTTP answer; None when unanswered
    checked_at: float | None = None  # time.time() of the probe, for /health


# Module-level cache state. Tests zero this via the reset_health_cache
# autouse fixture; production wires through the asyncio.Lock to avoid
# thundering-herd probes when TTL expires under concurrent traffic.
_last_probe: _ProbeResult | None = None
_probe_lock = asyncio.Lock()
_last_platform_probe: _ProbeResult | None = None
# Held so the background refresh /health starts is not garbage-collected.
_refresh_task: asyncio.Task[_ProbeResult] | None = None


def _expires_at() -> float:
    return time.monotonic() + PROBE_TTL_SECONDS


def _failed(reason: str) -> _ProbeResult:
    return _ProbeResult(False, reason, _expires_at(), checked_at=time.time())


async def _probe_platform_reachable() -> _ProbeResult:
    """HEAD the platform base URL with a tight timeout. No key required.

    Any HTTP response (even 401/404/5xx) proves the host is reachable, which is
    all readiness needs in api_key mode (per-request keys are validated per
    call). Every result is recorded in ``_last_platform_probe`` for /health;
    the status code never affects readiness. Only ``_kick_refresh`` runs it,
    so one HEAD is in flight at a time and results land in order.
    """
    global _last_platform_probe
    _last_platform_probe = await _head_platform()
    return _last_platform_probe


async def _head_platform() -> _ProbeResult:
    base = os.getenv("REVENIUM_BASE_URL", "").strip().rstrip("/")
    if not base:
        return _failed(_REASON_UNREACHABLE)

    from .client import get_shared_http_client

    try:
        response = await asyncio.wait_for(
            get_shared_http_client().head(base),
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return _failed(_REASON_TIMEOUT)
    except Exception:
        return _failed(_REASON_UNREACHABLE)
    return _ProbeResult(
        True, None, _expires_at(), response.status_code, time.time()
    )


async def _probe_revenium() -> _ProbeResult:
    """Probe Revenium readiness.

    env: authenticated /users/me validation via the env-baked key.
    clerk/api_key: no server-wide key exists (credentials are per-request),
    so probe platform base-URL reachability only.
    Never raises.
    """
    from .auth.auth_mode import read_auth_mode

    if read_auth_mode() in ("api_key", "clerk"):
        return await _shared_platform_probe()

    from .client import ReveniumClient

    try:
        result = await asyncio.wait_for(
            ReveniumClient().validate_api_key(),
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return _failed(_REASON_TIMEOUT)
    except Exception:
        # Defence in depth: validate_api_key already classifies HTTP/connect
        # errors into the dict it returns. Reaching this branch means
        # something more fundamental broke (DNS, TLS, library bug,
        # misconfigured client). Treat as unreachable.
        return _failed(_REASON_UNREACHABLE)

    if result["valid"]:
        return _ProbeResult(True, None, _expires_at(), checked_at=time.time())
    status = result.get("status_code")
    return _failed(_REASON_AUTH if status in (401, 403) else _REASON_UNREACHABLE)


async def _get_ready_status() -> _ProbeResult:
    """Return the current readiness, probing Revenium at most once per TTL.

    Fast path: cache hit returns immediately without taking the lock.
    Slow path: lock + double-check so N concurrent callers trigger exactly
    one probe.
    """
    global _last_probe
    if _is_fresh(_last_probe):
        return _last_probe
    async with _probe_lock:
        if _is_fresh(_last_probe):
            return _last_probe
        _last_probe = await _probe_revenium()
        return _last_probe


def _is_fresh(probe: _ProbeResult | None) -> TypeGuard[_ProbeResult]:
    return probe is not None and probe.expires_at > time.monotonic()


def _platform_state(probe: _ProbeResult | None) -> dict[str, Any]:
    """The platform's state as last seen by the keyless HEAD, for /health.

    Exposes only the status code, the time and the closed reason enum; never
    the base URL or any error text.
    """
    if probe is None or probe.checked_at is None:
        return {
            "status_code": None,
            "checked_at": None,
            "age_seconds": None,
            "error": None,
        }
    return {
        "status_code": probe.status_code,
        "checked_at": datetime.fromtimestamp(
            probe.checked_at, tz=timezone.utc
        ).isoformat(),
        "age_seconds": round(time.time() - probe.checked_at, 1),
        "error": probe.reason if probe.status_code is None else None,
    }


def _retrieve_refresh_exception(task: asyncio.Task[_ProbeResult]) -> None:
    if not task.cancelled():
        task.exception()


def _kick_refresh() -> asyncio.Task[_ProbeResult]:
    """The background keyless HEAD in flight, started when none is running."""
    global _refresh_task
    if _refresh_task is not None and not _refresh_task.done():
        return _refresh_task
    _refresh_task = asyncio.get_running_loop().create_task(
        _probe_platform_reachable()
    )
    _refresh_task.add_done_callback(_retrieve_refresh_exception)
    return _refresh_task


async def _shared_platform_probe() -> _ProbeResult:
    """The keyless HEAD's answer /health shows: a fresh one, else the one in flight.

    Shielded because the refresh is shared: a /ready request that is cancelled
    must not cancel the HEAD another route is waiting on.
    """
    probe = _last_platform_probe
    if _is_fresh(probe):
        return probe
    return await asyncio.shield(_kick_refresh())


def register_health_endpoints(mcp: "FastMCP") -> None:
    """Register ``GET /health`` and ``GET /ready`` on ``mcp``.

    Both routes are auth-exempt by FastMCP design (custom routes are
    appended outside ``RequireAuthMiddleware``). Safe to call in env mode
    and clerk mode alike.
    """

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> Response:
        probe = _last_platform_probe
        if not _is_fresh(probe):
            _kick_refresh()
        return JSONResponse({"status": "healthy", "platform": _platform_state(probe)})

    @mcp.custom_route("/ready", methods=["GET"])
    async def ready(request: Request) -> Response:
        result = await _get_ready_status()
        if result.ok:
            return JSONResponse({"status": "ready"})
        return JSONResponse(
            {"status": "not_ready", "reason": result.reason},
            status_code=503,
        )
