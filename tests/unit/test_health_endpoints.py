"""Tests for /health and /ready endpoints registered via register_health_endpoints."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport


@pytest.fixture(autouse=True)
def reset_health_cache():
    """Zero module-level cache + lock between tests so each test starts cold.

    The lock must be re-created (not just released) because pytest-asyncio
    runs each test in a fresh event loop (``asyncio_default_fixture_loop_scope
    = "function"``); reusing a Lock bound to a closed loop raises
    ``RuntimeError: bound to a different event loop`` on Python 3.12+.
    """
    from src.revenium_mcp_server import health_endpoints

    health_endpoints._last_probe = None
    health_endpoints._probe_lock = asyncio.Lock()
    yield
    health_endpoints._last_probe = None
    health_endpoints._probe_lock = asyncio.Lock()


def _build_mcp():
    """Build a FastMCP server with the health endpoints registered."""
    from fastmcp import FastMCP

    from src.revenium_mcp_server.health_endpoints import register_health_endpoints

    mcp = FastMCP(name="test-server")
    register_health_endpoints(mcp)
    return mcp


@pytest.mark.asyncio
async def test_health_returns_200_with_status_healthy():
    mcp = _build_mcp()
    app = mcp.http_app()

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


# ── _probe_revenium ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_probe_returns_ok_when_validate_api_key_is_valid():
    from src.revenium_mcp_server import health_endpoints

    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.validate_api_key",
        new=AsyncMock(return_value={"valid": True, "status_code": 200}),
    ):
        result = await health_endpoints._probe_revenium()

    assert result.ok is True
    assert result.reason is None
    assert result.expires_at > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_probe_returns_auth_failed_on_401_or_403(status_code):
    from src.revenium_mcp_server import health_endpoints

    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.validate_api_key",
        new=AsyncMock(return_value={"valid": False, "status_code": status_code}),
    ):
        result = await health_endpoints._probe_revenium()

    assert result.ok is False
    assert result.reason == "auth_failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [None, 500, 502, 503])
async def test_probe_returns_unreachable_on_other_failures(status_code):
    from src.revenium_mcp_server import health_endpoints

    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.validate_api_key",
        new=AsyncMock(return_value={"valid": False, "status_code": status_code}),
    ):
        result = await health_endpoints._probe_revenium()

    assert result.ok is False
    assert result.reason == "revenium_api_unreachable"


@pytest.mark.asyncio
async def test_probe_returns_timeout_when_validate_takes_too_long():
    from src.revenium_mcp_server import health_endpoints

    async def slow_validate(self):
        await asyncio.sleep(10.0)  # well past PROBE_TIMEOUT_SECONDS
        return {"valid": True}

    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.validate_api_key",
        new=slow_validate,
    ):
        result = await asyncio.wait_for(
            health_endpoints._probe_revenium(),
            timeout=health_endpoints.PROBE_TIMEOUT_SECONDS + 1.0,
        )

    assert result.ok is False
    assert result.reason == "timeout"


@pytest.mark.asyncio
async def test_probe_returns_unreachable_when_validate_raises():
    from src.revenium_mcp_server import health_endpoints

    async def boom(self):
        raise RuntimeError("transport blew up")

    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.validate_api_key",
        new=boom,
    ):
        result = await health_endpoints._probe_revenium()

    assert result.ok is False
    assert result.reason == "revenium_api_unreachable"


# ── _get_ready_status (cache) ────────────────────────────────────


@pytest.mark.asyncio
async def test_get_ready_status_caches_result_within_ttl():
    from src.revenium_mcp_server import health_endpoints

    mock = AsyncMock(return_value={"valid": True, "status_code": 200})
    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.validate_api_key",
        new=mock,
    ):
        first = await health_endpoints._get_ready_status()
        second = await health_endpoints._get_ready_status()

    assert first.ok is True
    assert second.ok is True
    assert mock.call_count == 1, "second call should hit the cache, not probe again"


@pytest.mark.asyncio
async def test_get_ready_status_reprobes_after_ttl_expiry(monkeypatch):
    from src.revenium_mcp_server import health_endpoints

    fake_now = [1000.0]

    def fake_monotonic():
        return fake_now[0]

    monkeypatch.setattr(health_endpoints.time, "monotonic", fake_monotonic)

    mock = AsyncMock(return_value={"valid": True, "status_code": 200})
    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.validate_api_key",
        new=mock,
    ):
        await health_endpoints._get_ready_status()
        # Jump forward past the TTL.
        fake_now[0] += health_endpoints.PROBE_TTL_SECONDS + 1.0
        await health_endpoints._get_ready_status()

    assert mock.call_count == 2


@pytest.mark.asyncio
async def test_get_ready_status_collapses_concurrent_callers_into_one_probe():
    from src.revenium_mcp_server import health_endpoints

    started = asyncio.Event()
    release = asyncio.Event()
    call_count = 0

    async def slow_validate(self):
        nonlocal call_count
        call_count += 1
        started.set()
        # Hold the probe until all callers are queued behind the lock.
        await release.wait()
        return {"valid": True, "status_code": 200}

    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.validate_api_key",
        new=slow_validate,
    ):
        # Spawn 10 concurrent callers against a cold cache.
        tasks = [
            asyncio.create_task(health_endpoints._get_ready_status())
            for _ in range(10)
        ]
        # Wait for the in-flight probe, then let it complete.
        await started.wait()
        release.set()
        results = await asyncio.gather(*tasks)

    assert call_count == 1, "lock should serialise probes to 1 call"
    assert all(r.ok for r in results)


# ── /ready route ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ready_returns_200_when_revenium_reachable():
    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.validate_api_key",
        new=AsyncMock(return_value={"valid": True, "status_code": 200}),
    ):
        mcp = _build_mcp()
        app = mcp.http_app()
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/ready")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fixture_status_code, expected_reason",
    [
        (401, "auth_failed"),
        (403, "auth_failed"),
        (500, "revenium_api_unreachable"),
        (None, "revenium_api_unreachable"),
    ],
)
async def test_ready_returns_503_with_reason_on_failure(
    fixture_status_code, expected_reason
):
    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.validate_api_key",
        new=AsyncMock(
            return_value={"valid": False, "status_code": fixture_status_code}
        ),
    ):
        mcp = _build_mcp()
        app = mcp.http_app()
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/ready")

    assert resp.status_code == 503
    assert resp.json() == {"status": "not_ready", "reason": expected_reason}


# ── Auth-exempt verification ─────────────────────────────────────


@pytest.mark.asyncio
async def test_health_and_ready_skip_auth_middleware():
    """Custom routes must not be gated by RequireAuthMiddleware.

    Builds a FastMCP server with a stub AuthProvider attached, then
    confirms /health and /ready return 200/200 without an Authorization
    header. The /mcp protocol path under the same server WOULD return 401
    in that scenario; the custom routes go around that wrapper.
    """
    from unittest.mock import MagicMock

    from fastmcp import FastMCP
    from fastmcp.server.auth.auth import AuthProvider

    from src.revenium_mcp_server.health_endpoints import register_health_endpoints

    # Stub auth provider: no actual JWKS, just enough for FastMCP to attach
    # RequireAuthMiddleware around the /mcp path.
    auth = MagicMock(spec=AuthProvider)
    auth.required_scopes = []
    auth.get_middleware.return_value = []
    auth.get_routes.return_value = []
    auth._get_resource_url.return_value = None

    mcp = FastMCP(name="auth-test", auth=auth)
    register_health_endpoints(mcp)
    app = mcp.http_app()

    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.validate_api_key",
        new=AsyncMock(return_value={"valid": True, "status_code": 200}),
    ):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            health_resp = await client.get("/health")
            ready_resp = await client.get("/ready")

    assert health_resp.status_code == 200, health_resp.text
    assert ready_resp.status_code == 200, ready_resp.text


# ── Integration with create_enhanced_server ──────────────────────


@pytest.mark.asyncio
async def test_create_enhanced_server_registers_health_endpoints(monkeypatch):
    """The actual server constructor must wire /health and /ready in."""
    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test")
    monkeypatch.setenv("REVENIUM_BASE_URL", "http://127.0.0.1:1")

    from src.revenium_mcp_server.enhanced_server import create_enhanced_server

    mcp = create_enhanced_server()
    app = mcp.http_app()

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


# ── api_key mode: reachability probe, no validate_api_key ────────


@pytest.mark.asyncio
async def test_api_key_mode_probe_does_not_call_validate_api_key(monkeypatch):
    """In api_key mode, readiness must NOT call ReveniumClient.validate_api_key
    (there is no env-baked key); it probes platform reachability instead."""
    monkeypatch.setenv("AUTH_MODE", "api_key")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://platform.test")

    # autouse reset_health_cache has already zeroed _last_probe

    called = {"validate": False}

    class _Boom:
        async def validate_api_key(self):
            called["validate"] = True
            return {"valid": True}

    monkeypatch.setattr(
        "src.revenium_mcp_server.client.ReveniumClient", lambda *a, **k: _Boom()
    )

    from src.revenium_mcp_server import health_endpoints

    result = await health_endpoints._probe_revenium()
    assert called["validate"] is False
    assert result.ok in (True, False)  # a reachability result, not an auth result


@pytest.mark.asyncio
async def test_api_key_mode_missing_url_returns_not_ready(monkeypatch):
    """api_key mode with no REVENIUM_BASE_URL → not ready, not a crash."""
    monkeypatch.setenv("AUTH_MODE", "api_key")
    monkeypatch.delenv("REVENIUM_BASE_URL", raising=False)

    from src.revenium_mcp_server import health_endpoints

    result = await health_endpoints._probe_revenium()
    assert result.ok is False
    assert result.reason == "revenium_api_unreachable"


@pytest.mark.asyncio
async def test_clerk_mode_probe_does_not_call_validate_api_key(monkeypatch):
    """In clerk mode, readiness must NOT call ReveniumClient.validate_api_key
    (no env-baked key; credentials are per-request JWTs); it probes platform
    reachability instead — otherwise /ready is permanently 503."""
    monkeypatch.setenv("AUTH_MODE", "clerk")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://platform.test")
    monkeypatch.delenv("REVENIUM_API_KEY", raising=False)

    called = {"validate": False}

    class _Boom:
        async def validate_api_key(self):
            called["validate"] = True
            return {"valid": True}

    monkeypatch.setattr(
        "src.revenium_mcp_server.client.ReveniumClient", lambda *a, **k: _Boom()
    )

    from src.revenium_mcp_server import health_endpoints

    result = await health_endpoints._probe_revenium()
    assert called["validate"] is False
    assert result.ok in (True, False)  # a reachability result, not an auth result
