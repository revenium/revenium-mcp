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

Decision (BACK-2472): DECLINED — this limiter gains no per-tool bucket
keyed on the ``Mcp-Name`` header. Per-tool limiting is the edge's job,
briefed to infrastructure as BACK-3057 (hypercurrent-infrastructure).

The capability is genuinely available now. On mcp 2.1.1 the client stamps
``mcp-method`` (``MCP_METHOD_HEADER``) on every streamable-HTTP request and
``mcp-name`` (``MCP_NAME_HEADER``) for the methods in
``NAME_BEARING_METHODS`` — ``tools/call`` -> ``name`` is the row that
carries the tool name — and the server enforces agreement with the body:
``classify_inbound_request`` in ``mcp/shared/inbound.py``, called from
``mcp/server/_streamable_http_modern.py`` next to
``find_duplicated_routing_header``, rejects a header that disagrees with
the body as ``HEADER_MISMATCH``. A gateway can therefore key on the tool
name without parsing JSON, and can trust what it reads. This repo neither
reads nor emits those headers; it is the client that sends them.

The reason not to spend that here is the scope notes above: a per-tool
bucket added to this middleware would inherit all three constraints
unchanged. Its keys stay attacker-rotatable (a fresh Authorization value
is a fresh per-tool bucket too, so the caller most motivated to hammer one
expensive tool is exactly the caller who can reset its budget), its state
stays one process's memory (a second task silently doubles every budget),
and it stays positioned where the module records it — capping tool
execution, not verification (the precise ordering against FastMCP's auth
layer is flagged as unverified in
``docs/architecture/server-and-runtime.md``, which is itself a reason not
to build a security control on top of it). The ALB/WAF has none of those
three limits and now has the tool name, so that is where the enforcement
belongs.

Reopens if either holds: the deployment stops being single-task and this
limiter gains shared (distributed) state, or the edge is shown unable to
key on the header and an in-process budget is the only option left. The
shape to build then is a second ``SlidingWindowLimiter`` keyed on
``(credential, mcp-name)`` for a configurable allowlist of expensive
tools, applied only when the header is present — a legacy client sends
neither header, and absence must read as "unknown tool", not as an error —
leaving the flat per-credential bucket and ``DEFAULT_MCP_LIMIT_PER_MINUTE``
untouched.
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
