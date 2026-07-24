"""Tests for TRANSPORT_MODE wiring inside enhanced_server.main()."""
from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def reset_alias_warnings():
    """Clear the per-process alias-warning dedup so each test starts clean."""
    from src.revenium_mcp_server import transport_mode

    transport_mode._warned_aliases.clear()
    yield
    transport_mode._warned_aliases.clear()


@pytest.fixture
def env_mode_env(monkeypatch):
    """Minimal env setup for AUTH_MODE=env path.

    REVENIUM_BASE_URL points at 127.0.0.1:1 (an address guaranteed to refuse
    connections) so the startup API-key validation fails fast instead of
    hitting the real Revenium API during unit tests.
    """
    monkeypatch.setenv("AUTH_MODE", "env")
    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_BASE_URL", "http://127.0.0.1:1")


@pytest.fixture
def clerk_mode_env(monkeypatch):
    """Minimal env setup for AUTH_MODE=clerk path (without TRANSPORT_MODE set)."""
    monkeypatch.setenv("AUTH_MODE", "clerk")
    monkeypatch.setenv("CLERK_DOMAIN", "test-instance.clerk.accounts.dev")
    monkeypatch.setenv("CLERK_OAUTH_CLIENT_ID", "client_test")
    monkeypatch.setenv("CLERK_OAUTH_CLIENT_SECRET", "secret_test")
    monkeypatch.setenv("MCP_SERVER_BASE_URL", "https://mcp.test.io")
    monkeypatch.setenv("REVENIUM_TENANT_ID", "tenant_test")
    monkeypatch.setenv("REVENIUM_API_KEY", "key_test_abcd1234")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_test")


def _build_main_mocks():
    """Construct mocks for main()'s heavy collaborators.

    Returns a dict with both the mocks themselves and a list of unstarted
    patch context managers. Tests enter the patches via ExitStack and can
    introspect the mocks afterward.
    """
    fake_mcp = MagicMock(name="fake_mcp")
    fake_mcp.run_async = AsyncMock(return_value=None)

    mock_fastmcp_cls = MagicMock(name="FastMCP", return_value=fake_mcp)
    mock_oidc_proxy_instance = MagicMock(name="oidc_proxy_instance")
    mock_oidc_proxy_cls = MagicMock(name="OIDCProxy", return_value=mock_oidc_proxy_instance)

    mock_client_instance = MagicMock(name="revenium_client")
    mock_client_instance.validate_api_key = AsyncMock(return_value={"valid": True})
    mock_revenium_client_cls = MagicMock(
        name="ReveniumClient", return_value=mock_client_instance
    )

    mock_ucm = MagicMock(name="ucm_integration_service")
    mock_ucm.initialize = AsyncMock(return_value=None)
    mock_ucm.integrate_with_mcp_server = AsyncMock(return_value=None)

    mock_introspection = MagicMock(name="introspection_integration")
    mock_introspection.initialize = AsyncMock(return_value=None)
    mock_introspection.get_server_summary = AsyncMock(
        return_value={"registered_tools": 0}
    )

    from src.revenium_mcp_server import enhanced_server

    patches = [
        patch("src.revenium_mcp_server.enhanced_server.FastMCP", mock_fastmcp_cls),
        patch("fastmcp.server.auth.oidc_proxy.OIDCProxy", mock_oidc_proxy_cls),
        patch("src.revenium_mcp_server.client.ReveniumClient", mock_revenium_client_cls),
        patch(
            "src.revenium_mcp_server.enhanced_server.install_crash_logging",
            return_value=MagicMock(),
        ),
        patch(
            "src.revenium_mcp_server.enhanced_server.register_tools",
            new=AsyncMock(return_value=None),
        ),
        patch.object(enhanced_server, "ucm_integration_service", mock_ucm),
        patch.object(enhanced_server, "introspection_integration", mock_introspection),
    ]
    return {
        "fake_mcp": fake_mcp,
        "FastMCP": mock_fastmcp_cls,
        "OIDCProxy": mock_oidc_proxy_cls,
        "patches": patches,
    }


@pytest.mark.asyncio
async def test_main_runs_stdio_when_TRANSPORT_MODE_unset(env_mode_env, monkeypatch):
    """Default path: no TRANSPORT_MODE → stdio. run_async called with no transport kwarg."""
    from src.revenium_mcp_server import enhanced_server

    monkeypatch.delenv("TRANSPORT_MODE", raising=False)
    mocks = _build_main_mocks()

    with ExitStack() as stack:
        for p in mocks["patches"]:
            stack.enter_context(p)
        await enhanced_server.main()

    fake_mcp = mocks["fake_mcp"]
    assert fake_mcp.run_async.call_count == 1
    call_kwargs = fake_mcp.run_async.call_args.kwargs
    assert "transport" not in call_kwargs


@pytest.mark.asyncio
async def test_main_runs_http_with_env_auth_and_warns(env_mode_env, monkeypatch):
    """env+http: run_async receives transport=http; warning logged about no-auth."""
    from src.revenium_mcp_server import enhanced_server
    from src.revenium_mcp_server import transport_mode

    monkeypatch.setenv("TRANSPORT_MODE", "http")
    monkeypatch.setenv("MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("MCP_PORT", "9876")

    warnings: list[str] = []
    monkeypatch.setattr(
        transport_mode.logger, "warning", lambda msg: warnings.append(msg)
    )

    mocks = _build_main_mocks()
    with ExitStack() as stack:
        for p in mocks["patches"]:
            stack.enter_context(p)
        await enhanced_server.main()

    assert mocks["fake_mcp"].run_async.call_count == 1
    run_kwargs = mocks["fake_mcp"].run_async.call_args.kwargs
    assert run_kwargs["transport"] == "http"
    assert run_kwargs["host"] == "127.0.0.1"
    assert run_kwargs["port"] == 9876
    assert "middleware" in run_kwargs
    assert any("without authentication" in m.lower() for m in warnings)


@pytest.mark.asyncio
async def test_main_fails_fast_on_clerk_plus_stdio(clerk_mode_env, monkeypatch):
    """clerk+stdio rejected at startup; FastMCP/OIDCProxy never constructed."""
    from src.revenium_mcp_server import enhanced_server

    monkeypatch.setenv("TRANSPORT_MODE", "stdio")
    mocks = _build_main_mocks()

    with ExitStack() as stack:
        for p in mocks["patches"]:
            stack.enter_context(p)
        with pytest.raises(
            ValueError, match="AUTH_MODE=clerk requires TRANSPORT_MODE=http"
        ):
            await enhanced_server.main()

    mocks["FastMCP"].assert_not_called()
    mocks["OIDCProxy"].assert_not_called()
