"""In-memory sliding-window rate limiting for the HTTP transport."""
from __future__ import annotations

import pytest

from src.revenium_mcp_server.auth.rate_limit import (
    RateLimitMiddleware,
    SlidingWindowLimiter,
)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class TestSlidingWindowLimiter:
    def test_allows_up_to_limit(self):
        clock = FakeClock()
        limiter = SlidingWindowLimiter(limit=3, window_seconds=60, time_fn=clock)
        assert all(limiter.allow("k")[0] for _ in range(3))
        allowed, retry_after = limiter.allow("k")
        assert not allowed
        assert retry_after > 0

    def test_window_slides(self):
        clock = FakeClock()
        limiter = SlidingWindowLimiter(limit=2, window_seconds=60, time_fn=clock)
        limiter.allow("k")
        limiter.allow("k")
        assert not limiter.allow("k")[0]
        clock.now += 61
        assert limiter.allow("k")[0]

    def test_keys_are_independent(self):
        limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
        assert limiter.allow("a")[0]
        assert limiter.allow("b")[0]
        assert not limiter.allow("a")[0]

    def test_limit_zero_disables(self):
        limiter = SlidingWindowLimiter(limit=0, window_seconds=60)
        assert all(limiter.allow("k")[0] for _ in range(100))


def _scope(path, headers=None, client=("10.0.0.1", 1234)):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return {"type": "http", "path": path, "headers": raw, "client": client}


class _App:
    def __init__(self):
        self.calls = 0

    async def __call__(self, scope, receive, send):
        self.calls += 1
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


async def _run(mw, scope):
    sent = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.request"}

    await mw(scope, receive, send)
    return sent


class TestRateLimitMiddleware:
    @pytest.mark.asyncio
    async def test_mcp_path_limited_by_auth_header(self):
        app = _App()
        clock = FakeClock()
        mw = RateLimitMiddleware(
            app, mcp_limit=2, auth_limit=10, window_seconds=60, time_fn=clock
        )
        headers = {"authorization": "Bearer tok_a"}
        await _run(mw, _scope("/mcp", headers))
        await _run(mw, _scope("/mcp", headers))
        sent = await _run(mw, _scope("/mcp", headers))
        start = sent[0]
        assert start["status"] == 429
        header_names = {k for k, _ in start["headers"]}
        assert b"retry-after" in header_names
        assert app.calls == 2

    @pytest.mark.asyncio
    async def test_rejection_emits_structured_auth_event(self):
        from loguru import logger

        app = _App()
        mw = RateLimitMiddleware(app, mcp_limit=1, auth_limit=10, window_seconds=60)
        headers = {"authorization": "Bearer tok_a"}
        await _run(mw, _scope("/mcp", headers))

        records = []
        sink_id = logger.add(lambda msg: records.append(msg.record), level="WARNING")
        try:
            sent = await _run(mw, _scope("/mcp", headers))
        finally:
            logger.remove(sink_id)

        assert sent[0]["status"] == 429
        assert records, "no auth event emitted on rate-limit rejection"
        extra = records[0]["extra"]
        assert extra["auth_outcome"] == "failure"
        assert extra["reason"] == "rate_limit_exceeded"

    @pytest.mark.asyncio
    async def test_distinct_tokens_get_distinct_budgets(self):
        app = _App()
        mw = RateLimitMiddleware(app, mcp_limit=1, auth_limit=10, window_seconds=60)
        await _run(mw, _scope("/mcp", {"authorization": "Bearer tok_a"}))
        sent = await _run(mw, _scope("/mcp", {"authorization": "Bearer tok_b"}))
        assert sent[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_auth_paths_use_auth_limit_keyed_by_ip(self):
        app = _App()
        mw = RateLimitMiddleware(app, mcp_limit=100, auth_limit=1, window_seconds=60)
        await _run(mw, _scope("/token"))
        sent = await _run(mw, _scope("/token"))
        assert sent[0]["status"] == 429

    @pytest.mark.asyncio
    async def test_other_paths_unlimited(self):
        app = _App()
        mw = RateLimitMiddleware(app, mcp_limit=1, auth_limit=1, window_seconds=60)
        for _ in range(5):
            sent = await _run(mw, _scope("/health"))
            assert sent[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_non_http_scope_passthrough(self):
        called = {}

        async def lifespan_app(scope, receive, send):
            called["yes"] = True

        mw = RateLimitMiddleware(lifespan_app, mcp_limit=1, auth_limit=1, window_seconds=60)
        await mw({"type": "lifespan"}, None, None)
        assert called.get("yes")


class TestEvictionAndConfig:
    def test_lru_eviction_caps_tracked_keys(self, monkeypatch):
        import src.revenium_mcp_server.auth.rate_limit as rl

        monkeypatch.setattr(rl, "_MAX_TRACKED_KEYS", 3)
        limiter = SlidingWindowLimiter(limit=5, window_seconds=60)
        for key in ("a", "b", "c"):
            limiter.allow(key)
        limiter.allow("d")  # evicts least-recently-touched ("a")
        assert len(limiter._hits) == 3
        assert "a" not in limiter._hits
        assert "d" in limiter._hits

    def test_read_limit_env_parsing(self, monkeypatch):
        from src.revenium_mcp_server.auth.rate_limit import _read_limit

        monkeypatch.delenv("X_LIMIT", raising=False)
        assert _read_limit("X_LIMIT", 42) == 42
        monkeypatch.setenv("X_LIMIT", "7")
        assert _read_limit("X_LIMIT", 42) == 7
        monkeypatch.setenv("X_LIMIT", "-1")
        with pytest.raises(ValueError, match="X_LIMIT"):
            _read_limit("X_LIMIT", 42)
        monkeypatch.setenv("X_LIMIT", "abc")
        with pytest.raises(ValueError, match="X_LIMIT"):
            _read_limit("X_LIMIT", 42)

    def test_build_middleware_disabled_when_both_zero(self, monkeypatch):
        from src.revenium_mcp_server.auth.rate_limit import build_rate_limit_middleware

        monkeypatch.setenv("MCP_RATE_LIMIT_PER_MINUTE", "0")
        monkeypatch.setenv("MCP_AUTH_RATE_LIMIT_PER_MINUTE", "0")
        assert build_rate_limit_middleware() is None
        monkeypatch.setenv("MCP_AUTH_RATE_LIMIT_PER_MINUTE", "5")
        assert build_rate_limit_middleware() is not None

    @pytest.mark.asyncio
    async def test_missing_client_falls_back_to_unknown_key(self):
        app = _App()
        mw = RateLimitMiddleware(app, mcp_limit=1, auth_limit=1, window_seconds=60)
        sent = await _run(mw, _scope("/token", client=None))
        assert sent[0]["status"] == 200
        sent = await _run(mw, _scope("/token", client=None))
        assert sent[0]["status"] == 429

    @pytest.mark.asyncio
    async def test_auth_path_trailing_slash_still_limited(self):
        app = _App()
        mw = RateLimitMiddleware(app, mcp_limit=100, auth_limit=1, window_seconds=60)
        await _run(mw, _scope("/token/"))
        sent = await _run(mw, _scope("/token"))
        assert sent[0]["status"] == 429


class TestProxyAwareIpKey:
    @pytest.mark.asyncio
    async def test_auth_path_keys_by_rightmost_xff_behind_proxy(self):
        app = _App()
        mw = RateLimitMiddleware(app, mcp_limit=100, auth_limit=1, window_seconds=60)
        # Two different real clients behind the same ALB source IP must get
        # independent buckets via the rightmost X-Forwarded-For hop.
        sent = await _run(
            mw, _scope("/token", {"x-forwarded-for": "203.0.113.7"}, client=("10.0.0.9", 1))
        )
        assert sent[0]["status"] == 200
        sent = await _run(
            mw, _scope("/token", {"x-forwarded-for": "198.51.100.3"}, client=("10.0.0.9", 1))
        )
        assert sent[0]["status"] == 200
        sent = await _run(
            mw, _scope("/token", {"x-forwarded-for": "203.0.113.7"}, client=("10.0.0.9", 1))
        )
        assert sent[0]["status"] == 429

    @pytest.mark.asyncio
    async def test_only_rightmost_xff_hop_is_trusted(self):
        app = _App()
        mw = RateLimitMiddleware(app, mcp_limit=100, auth_limit=1, window_seconds=60)
        # Caller-controlled left entries must not buy a fresh bucket.
        await _run(
            mw,
            _scope("/token", {"x-forwarded-for": "1.1.1.1, 203.0.113.7"}, client=("10.0.0.9", 1)),
        )
        sent = await _run(
            mw,
            _scope("/token", {"x-forwarded-for": "2.2.2.2, 203.0.113.7"}, client=("10.0.0.9", 1)),
        )
        assert sent[0]["status"] == 429

    @pytest.mark.asyncio
    async def test_no_xff_falls_back_to_scope_client(self):
        app = _App()
        mw = RateLimitMiddleware(app, mcp_limit=100, auth_limit=1, window_seconds=60)
        await _run(mw, _scope("/token", client=("203.0.113.7", 1)))
        sent = await _run(mw, _scope("/token", client=("198.51.100.3", 1)))
        assert sent[0]["status"] == 200
