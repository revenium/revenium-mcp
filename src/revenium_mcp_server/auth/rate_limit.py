"""In-memory sliding-window rate limiting for the HTTP transport.

Defense-in-depth behind the ALB/WAF per-IP rules: per-credential limiting on
the MCP endpoint, per-IP limiting on the OAuth endpoints. Single-process
in-memory state — sufficient for the current single-task deployment; not a
distributed limiter.

Scope notes:
- FastMCP mounts user middleware inside its auth layer, so on the MCP
  endpoint token verification runs before this limiter — it caps tool
  execution and downstream load, not verification CPU.
- Per-credential buckets are bypassable by rotating the Authorization
  header (each unique value gets a fresh bucket); the WAF per-IP rules at
  the ALB remain the outer defense for that pattern.
"""
from __future__ import annotations

import hashlib
import os
import time
from collections import OrderedDict, deque
from typing import TYPE_CHECKING, Callable, Optional

from .auth_events import emit_auth_event

if TYPE_CHECKING:
    from starlette.middleware import Middleware

DEFAULT_MCP_LIMIT_PER_MINUTE = 120
DEFAULT_AUTH_LIMIT_PER_MINUTE = 20
_AUTH_PATHS = ("/authorize", "/token", "/register")
_MAX_TRACKED_KEYS = 10_000


class SlidingWindowLimiter:
    """Sliding-window counter per key. limit=0 disables the limiter."""

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: float = 60.0,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._now = time_fn
        self._hits: "OrderedDict[str, deque[float]]" = OrderedDict()

    def allow(self, key: str) -> tuple[bool, float]:
        """Return (allowed, retry_after_seconds)."""
        if self._limit <= 0:
            return True, 0.0
        now = self._now()
        window_start = now - self._window
        bucket = self._hits.get(key)
        if bucket is None:
            if len(self._hits) >= _MAX_TRACKED_KEYS:
                self._hits.popitem(last=False)  # evict least-recently-touched
            bucket = deque()
            self._hits[key] = bucket
        else:
            self._hits.move_to_end(key)
        while bucket and bucket[0] <= window_start:
            bucket.popleft()
        if len(bucket) >= self._limit:
            retry_after = max(bucket[0] + self._window - now, 0.0)
            return False, retry_after
        bucket.append(now)
        return True, 0.0


def _client_key(scope: dict) -> str:
    """Prefer the credential fingerprint; fall back to client IP."""
    for name, value in scope.get("headers") or []:
        if name == b"authorization" and value.strip():
            # Full digest: a truncated prefix would be birthday-attackable,
            # letting a crafted token share (and drain) a victim's bucket.
            return "cred:" + hashlib.sha256(value.strip()).hexdigest()
    return _ip_key(scope)


def _ip_key(scope: dict) -> str:
    """Per-IP key, proxy-aware.

    Behind the ALB every connection shares the load balancer's source IP, so
    keying on scope["client"] would collapse all callers into one shared
    bucket. The rightmost X-Forwarded-For entry is the one appended by the
    proxy this server sits behind, so it is the only hop worth trusting;
    earlier entries are caller-controlled and ignored.
    """
    for name, value in scope.get("headers") or []:
        if name == b"x-forwarded-for" and value.strip():
            rightmost = value.decode("latin-1").split(",")[-1].strip()
            if rightmost:
                return f"ip:{rightmost}"
    client = scope.get("client")
    return f"ip:{client[0]}" if client else "ip:unknown"


class RateLimitMiddleware:
    """ASGI middleware: 429 + Retry-After when a window is exhausted."""

    def __init__(
        self,
        app: Callable,
        *,
        mcp_limit: int = DEFAULT_MCP_LIMIT_PER_MINUTE,
        auth_limit: int = DEFAULT_AUTH_LIMIT_PER_MINUTE,
        window_seconds: float = 60.0,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._app = app
        self._mcp_limiter = SlidingWindowLimiter(
            limit=mcp_limit, window_seconds=window_seconds, time_fn=time_fn
        )
        self._auth_limiter = SlidingWindowLimiter(
            limit=auth_limit, window_seconds=window_seconds, time_fn=time_fn
        )

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path.rstrip("/") in _AUTH_PATHS:
            allowed, retry_after = self._auth_limiter.allow(_ip_key(scope))
        elif path.startswith("/mcp"):
            # Prefix match is intentional: covers /mcp and any sub-path the
            # streamable transport mounts under it.
            allowed, retry_after = self._mcp_limiter.allow(_client_key(scope))
        else:
            allowed, retry_after = True, 0.0
        if allowed:
            await self._app(scope, receive, send)
            return
        # Rate-limit rejections are security-relevant — emit one structured
        # auth event so they are visible on the same pipeline as other auth
        # failures. ip/user_agent are filled in best-effort by the emitter.
        emit_auth_event(
            outcome="failure",
            auth_mode="rate_limit",
            reason="rate_limit_exceeded",
        )
        body = b'{"error":"rate_limit_exceeded"}'
        await send({
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json"),
                (b"retry-after", str(max(int(retry_after) + 1, 1)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})


def _read_limit(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)  # let a typo fail startup loudly
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}")
    return value


def build_rate_limit_middleware() -> Optional[list["Middleware"]]:
    """Starlette Middleware list for FastMCP's http app, or None when disabled."""
    mcp_limit = _read_limit("MCP_RATE_LIMIT_PER_MINUTE", DEFAULT_MCP_LIMIT_PER_MINUTE)
    auth_limit = _read_limit("MCP_AUTH_RATE_LIMIT_PER_MINUTE", DEFAULT_AUTH_LIMIT_PER_MINUTE)
    if mcp_limit == 0 and auth_limit == 0:
        return None
    from starlette.middleware import Middleware

    return [Middleware(RateLimitMiddleware, mcp_limit=mcp_limit, auth_limit=auth_limit)]
