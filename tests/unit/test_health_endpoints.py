"""Tests for /health and /ready endpoints registered via register_health_endpoints."""
from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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
    health_endpoints._last_platform_probe = None
    health_endpoints._probe_lock = asyncio.Lock()
    health_endpoints._refresh_task = None
    yield
    _cancel_pending_refresh(health_endpoints)
    health_endpoints._last_probe = None
    health_endpoints._last_platform_probe = None
    health_endpoints._probe_lock = asyncio.Lock()
    health_endpoints._refresh_task = None


def _cancel_pending_refresh(health_endpoints) -> None:
    task = getattr(health_endpoints, "_refresh_task", None)
    if task is None or task.done():
        return
    try:
        task.cancel()
    except RuntimeError:
        # The test's event loop is already closed; the task died with it.
        pass


async def _drain_refresh() -> None:
    """Cancel and await any background refresh a /health call started."""
    from src.revenium_mcp_server import health_endpoints

    task = getattr(health_endpoints, "_refresh_task", None)
    if task is None:
        return
    if not task.done():
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


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
    await _drain_refresh()

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert set(body["platform"]) == {
        "status_code",
        "checked_at",
        "age_seconds",
        "error",
    }


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
    await _drain_refresh()

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert "platform" in body


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


# ── /health platform state ───────────────────────────────────────

_HOSTED_MODES = ["api_key", "clerk"]
_PLATFORM_NOT_CHECKED = {
    "status_code": None,
    "checked_at": None,
    "age_seconds": None,
    "error": None,
}


def _install_platform_stub(monkeypatch, head):
    """Replace the shared httpx client the probe uses with a stub ``head``."""
    stub = SimpleNamespace(head=head)
    monkeypatch.setattr(
        "src.revenium_mcp_server.client.get_shared_http_client",
        lambda *a, **k: stub,
    )
    return stub


def _install_platform_transport(monkeypatch, handler):
    """Route the real client code through an ``httpx.MockTransport``."""
    transport_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        "src.revenium_mcp_server.client.get_shared_http_client",
        lambda *a, **k: transport_client,
    )
    return transport_client


def _hosted_mode(monkeypatch, auth_mode, base_url="https://platform.test"):
    monkeypatch.setenv("AUTH_MODE", auth_mode)
    monkeypatch.setenv("REVENIUM_BASE_URL", base_url)


def _asgi_client(mcp):
    return httpx.AsyncClient(
        transport=ASGITransport(app=mcp.http_app()), base_url="http://test"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_mode", _HOSTED_MODES)
@pytest.mark.parametrize("code", [502, 503])
async def test_health_reports_platform_status_seen_by_last_readiness_probe(
    monkeypatch, auth_mode, code
):
    _hosted_mode(monkeypatch, auth_mode)
    _install_platform_stub(
        monkeypatch, AsyncMock(return_value=httpx.Response(code))
    )

    async with _asgi_client(_build_mcp()) as client:
        ready = await client.get("/ready")
        health = await client.get("/health")

    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "healthy"
    platform = body["platform"]
    assert platform["status_code"] == code
    checked_at = datetime.fromisoformat(platform["checked_at"])
    assert checked_at.tzinfo is not None
    assert 0 <= platform["age_seconds"] < 5
    assert platform["error"] is None


@pytest.mark.asyncio
async def test_health_before_any_readiness_probe_reports_platform_not_checked(
    monkeypatch,
):
    from src.revenium_mcp_server import health_endpoints

    _hosted_mode(monkeypatch, "api_key")
    never = asyncio.Event()

    async def head_that_never_answers(*args, **kwargs):
        await never.wait()

    _install_platform_stub(monkeypatch, head_that_never_answers)

    async with _asgi_client(_build_mcp()) as client:
        resp = await asyncio.wait_for(client.get("/health"), 1.0)

    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy", "platform": _PLATFORM_NOT_CHECKED}
    assert health_endpoints._refresh_task is not None
    await _drain_refresh()


@pytest.mark.asyncio
async def test_health_reports_unanswered_platform_without_a_status_code(
    monkeypatch,
):
    _hosted_mode(monkeypatch, "api_key")
    _install_platform_stub(
        monkeypatch, AsyncMock(side_effect=httpx.ConnectError("refused"))
    )

    async with _asgi_client(_build_mcp()) as client:
        ready = await client.get("/ready")
        health = await client.get("/health")

    assert ready.status_code == 503
    assert ready.json() == {
        "status": "not_ready",
        "reason": "revenium_api_unreachable",
    }
    assert health.status_code == 200
    platform = health.json()["platform"]
    assert platform["status_code"] is None
    assert platform["error"] == "revenium_api_unreachable"
    assert platform["checked_at"] is not None


@pytest.mark.asyncio
async def test_env_mode_ready_still_validates_the_key_on_a_platform_503(
    monkeypatch,
):
    from src.revenium_mcp_server import health_endpoints

    monkeypatch.delenv("AUTH_MODE", raising=False)
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://platform.test")
    monkeypatch.setattr(health_endpoints, "PROBE_TIMEOUT_SECONDS", 0.2)
    _install_platform_transport(monkeypatch, lambda request: httpx.Response(503))

    async with _asgi_client(_build_mcp()) as client:
        ready = await client.get("/ready")

    assert ready.status_code == 503
    assert ready.json()["status"] == "not_ready"
    assert ready.json()["reason"] in ("timeout", "revenium_api_unreachable")
    assert health_endpoints._last_platform_probe is None


@pytest.mark.asyncio
async def test_health_in_env_mode_refreshes_with_a_keyless_head_and_never_sends_the_key(
    monkeypatch,
):
    from src.revenium_mcp_server import health_endpoints

    monkeypatch.delenv("AUTH_MODE", raising=False)
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://platform.test")
    monkeypatch.setenv("REVENIUM_API_KEY", "hak_must_not_leave")
    seen = []

    def platform(request):
        seen.append(request)
        return httpx.Response(503)

    _install_platform_transport(monkeypatch, platform)
    validate = AsyncMock(return_value={"valid": True, "status_code": 200})
    monkeypatch.setattr(
        "src.revenium_mcp_server.client.ReveniumClient.validate_api_key", validate
    )

    async with _asgi_client(_build_mcp()) as client:
        cold = await client.get("/health")
        await health_endpoints._refresh_task
        warm = await client.get("/health")

    assert cold.status_code == 200
    assert warm.status_code == 200
    platform_state = warm.json()["platform"]
    assert platform_state["status_code"] == 503
    assert platform_state["error"] is None
    validate.assert_not_called()
    assert [r.method for r in seen] == ["HEAD"]
    assert "x-api-key" not in seen[0].headers
    assert "authorization" not in seen[0].headers
    assert "hak_must_not_leave" not in str(seen[0].headers)
    assert health_endpoints._last_probe is None


@pytest.mark.asyncio
async def test_health_in_env_mode_without_a_base_url_makes_no_request(
    monkeypatch,
):
    from src.revenium_mcp_server import health_endpoints

    monkeypatch.delenv("AUTH_MODE", raising=False)
    monkeypatch.delenv("REVENIUM_BASE_URL", raising=False)
    shared_client = MagicMock()
    monkeypatch.setattr(
        "src.revenium_mcp_server.client.get_shared_http_client", shared_client
    )

    async with _asgi_client(_build_mcp()) as client:
        await client.get("/health")
        await health_endpoints._refresh_task
        health = await client.get("/health")

    shared_client.assert_not_called()
    assert health.status_code == 200
    platform = health.json()["platform"]
    assert platform["status_code"] is None
    assert platform["error"] == "revenium_api_unreachable"


@pytest.mark.asyncio
async def test_health_refreshes_a_stale_platform_state_in_the_background(
    monkeypatch,
):
    from src.revenium_mcp_server import health_endpoints

    _hosted_mode(monkeypatch, "api_key")
    stub = _install_platform_stub(
        monkeypatch, AsyncMock(return_value=httpx.Response(503))
    )

    async with _asgi_client(_build_mcp()) as client:
        cold = await client.get("/health")
        assert cold.json()["platform"] == _PLATFORM_NOT_CHECKED
        await health_endpoints._refresh_task
        warm = await client.get("/health")
        await client.get("/health")
        await client.get("/health")

    assert warm.status_code == 200
    assert warm.json()["platform"]["status_code"] == 503
    assert stub.head.await_count == 1


@pytest.mark.asyncio
async def test_health_serves_an_expired_state_then_shows_the_refreshed_one(
    monkeypatch,
):
    from src.revenium_mcp_server import health_endpoints

    fake_now = [1000.0]
    monkeypatch.setattr(health_endpoints.time, "monotonic", lambda: fake_now[0])
    _hosted_mode(monkeypatch, "api_key")
    stub = _install_platform_stub(
        monkeypatch, AsyncMock(return_value=httpx.Response(200))
    )

    async with _asgi_client(_build_mcp()) as client:
        await client.get("/health")
        await health_endpoints._refresh_task
        fake_now[0] += health_endpoints.PROBE_TTL_SECONDS + 1.0
        stub.head.return_value = httpx.Response(503)
        expired = await client.get("/health")
        await health_endpoints._refresh_task
        refreshed = await client.get("/health")

    assert expired.status_code == 200
    assert expired.json()["platform"]["status_code"] == 200
    assert refreshed.json()["platform"]["status_code"] == 503
    assert stub.head.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_mode", _HOSTED_MODES)
@pytest.mark.parametrize("code", [301, 401, 404, 500, 502, 503])
async def test_ready_stays_ready_on_any_platform_answer_in_hosted_modes(
    monkeypatch, auth_mode, code
):
    _hosted_mode(monkeypatch, auth_mode)
    _install_platform_stub(
        monkeypatch, AsyncMock(return_value=httpx.Response(code))
    )

    async with _asgi_client(_build_mcp()) as client:
        resp = await client.get("/ready")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_mode", ["api_key", "env"])
async def test_health_body_exposes_no_platform_host(monkeypatch, auth_mode):
    from src.revenium_mcp_server import health_endpoints

    secret_host = "https://platform-secret.test"
    monkeypatch.setenv("REVENIUM_BASE_URL", secret_host)
    monkeypatch.setattr(health_endpoints, "PROBE_TIMEOUT_SECONDS", 0.2)

    def refuse(request):
        raise httpx.ConnectError(f"Cannot connect to {secret_host}")

    if auth_mode == "env":
        monkeypatch.delenv("AUTH_MODE", raising=False)
        _install_platform_transport(monkeypatch, refuse)
    else:
        monkeypatch.setenv("AUTH_MODE", auth_mode)
        _install_platform_stub(
            monkeypatch, AsyncMock(side_effect=httpx.ConnectError(secret_host))
        )

    async with _asgi_client(_build_mcp()) as client:
        await client.get("/ready")
        resp = await client.get("/health")

    assert resp.status_code == 200
    assert "platform-secret" not in resp.text
    assert "base_url" not in resp.text


# ── one platform check per cache period across /ready and /health (BACK-4741) ──


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_mode", _HOSTED_MODES)
async def test_ready_after_a_health_refresh_sends_no_second_head(monkeypatch, auth_mode):
    from src.revenium_mcp_server import health_endpoints

    _hosted_mode(monkeypatch, auth_mode)
    stub = _install_platform_stub(
        monkeypatch, AsyncMock(return_value=httpx.Response(403))
    )

    async with _asgi_client(_build_mcp()) as client:
        await client.get("/health")
        await health_endpoints._refresh_task
        ready = await client.get("/ready")
        health = await client.get("/health")

    assert ready.json() == {"status": "ready"}
    assert health.json()["platform"]["status_code"] == 403
    assert stub.head.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_mode", _HOSTED_MODES)
async def test_health_after_ready_sends_no_second_head(monkeypatch, auth_mode):
    _hosted_mode(monkeypatch, auth_mode)
    stub = _install_platform_stub(
        monkeypatch, AsyncMock(return_value=httpx.Response(200))
    )

    async with _asgi_client(_build_mcp()) as client:
        await client.get("/ready")
        health = await client.get("/health")
        await client.get("/ready")

    assert health.json()["platform"]["status_code"] == 200
    assert stub.head.await_count == 1


@pytest.mark.asyncio
async def test_ready_waits_on_the_refresh_health_started_instead_of_sending_another(
    monkeypatch,
):
    from src.revenium_mcp_server import health_endpoints

    _hosted_mode(monkeypatch, "api_key")
    release = asyncio.Event()
    calls = []

    async def slow_head(*args, **kwargs):
        calls.append(args)
        await release.wait()
        return httpx.Response(204)

    _install_platform_stub(monkeypatch, slow_head)

    async with _asgi_client(_build_mcp()) as client:
        await client.get("/health")
        refresh = health_endpoints._refresh_task
        ready = asyncio.create_task(client.get("/ready"))
        for _ in range(50):
            await asyncio.sleep(0)
        assert calls, "the refresh /health started never sent its HEAD"
        assert not ready.done(), "/ready answered without waiting on the running refresh"
        assert refresh is not None and not refresh.done()
        assert health_endpoints._refresh_task is refresh
        release.set()
        resp = await asyncio.wait_for(ready, 1.0)

    assert resp.json() == {"status": "ready"}
    assert len(calls) == 1
    assert health_endpoints._last_platform_probe.status_code == 204


@pytest.mark.asyncio
async def test_kick_refresh_returns_the_running_refresh_instead_of_starting_another(
    monkeypatch,
):
    from src.revenium_mcp_server import health_endpoints

    _hosted_mode(monkeypatch, "api_key")
    release = asyncio.Event()
    calls = []

    async def slow_head(*args, **kwargs):
        calls.append(args)
        await release.wait()
        return httpx.Response(200)

    _install_platform_stub(monkeypatch, slow_head)

    tasks = [health_endpoints._kick_refresh() for _ in range(20)]
    await asyncio.sleep(0)
    release.set()
    await health_endpoints._refresh_task

    assert isinstance(tasks[0], asyncio.Task)
    assert all(task is tasks[0] for task in tasks)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_cancelled_ready_does_not_cancel_the_shared_refresh(monkeypatch):
    from src.revenium_mcp_server import health_endpoints

    _hosted_mode(monkeypatch, "api_key")
    release = asyncio.Event()

    async def slow_head(*args, **kwargs):
        await release.wait()
        return httpx.Response(200)

    _install_platform_stub(monkeypatch, slow_head)

    waiter = asyncio.create_task(health_endpoints._shared_platform_probe())
    await asyncio.sleep(0)
    waiter.cancel()
    release.set()
    result = await health_endpoints._refresh_task

    assert waiter.cancelled()
    assert result.status_code == 200
    assert health_endpoints._last_platform_probe is result
