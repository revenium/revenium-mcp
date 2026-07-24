"""Single structured emitter for authentication outcomes.

One event per auth success/failure across all auth modes, on the existing
loguru pipeline. Field set: auth_outcome, auth_mode, client_id (clerk) /
key_fingerprint (api_key), sub, tenant_id, ip, user_agent, aud, reason
(failure only). Raw tokens must never be passed in.

Failures are emitted at WARNING (visible at the production-default log level);
successes are emitted at INFO (set LOG_LEVEL=INFO to receive them).
"""
from __future__ import annotations

from typing import Optional

from loguru import logger


def _request_metadata() -> dict:
    """Best-effort ip/user_agent from the active HTTP request scope."""
    try:
        from fastmcp.server.dependencies import get_http_request

        request = get_http_request()
        meta = {}
        # Behind the ALB scope.client is the load balancer; the rightmost
        # X-Forwarded-For hop is the one the trusted proxy appended.
        forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[-1].strip()
        if forwarded:
            meta["ip"] = forwarded
        elif request.client and request.client.host:
            meta["ip"] = request.client.host
        ua = request.headers.get("user-agent")
        if ua:
            meta["user_agent"] = ua
        return meta
    except Exception:
        return {}


def emit_auth_event(
    *,
    outcome: str,
    auth_mode: str,
    client_id: Optional[str] = None,
    key_fingerprint: Optional[str] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    aud: Optional[str] = None,
    reason: Optional[str] = None,
) -> None:
    """Emit one structured auth event. Absent fields are omitted, never faked."""
    fields = {
        "auth_outcome": outcome,
        "auth_mode": auth_mode,
        "client_id": client_id,
        "key_fingerprint": key_fingerprint,
        "sub": user_id,
        "tenant_id": tenant_id,
        "aud": aud,
        "reason": reason,
    }
    fields = {k: v for k, v in fields.items() if v is not None}
    fields.update(_request_metadata())
    # Failures are security signals — emit at WARNING so they are visible at
    # the production-default log level; successes stay at INFO (enable
    # LOG_LEVEL=INFO to receive them).
    level = "WARNING" if outcome == "failure" else "INFO"
    logger.bind(**fields).log(level, "auth_event outcome={} mode={}", outcome, auth_mode)
