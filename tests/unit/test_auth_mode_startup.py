"""Unit tests for auth-mode startup helpers in enhanced_server.py."""
from __future__ import annotations

import pytest

from src.revenium_mcp_server.enhanced_server import _read_auth_mode
from src.revenium_mcp_server.enhanced_server import _require_envs


def test_read_auth_mode_defaults_to_env(monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    assert _read_auth_mode() == "env"


def test_read_auth_mode_accepts_env(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "env")
    assert _read_auth_mode() == "env"


def test_read_auth_mode_accepts_clerk(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "clerk")
    assert _read_auth_mode() == "clerk"


def test_read_auth_mode_case_insensitive(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "CLERK")
    assert _read_auth_mode() == "clerk"


def test_read_auth_mode_strips_whitespace(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "  clerk  ")
    assert _read_auth_mode() == "clerk"


def test_read_auth_mode_rejects_invalid(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "oauth2")
    with pytest.raises(ValueError, match="AUTH_MODE must be"):
        _read_auth_mode()


def test_read_auth_mode_rejects_empty_string(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "")
    with pytest.raises(ValueError, match="AUTH_MODE must be"):
        _read_auth_mode()


def test_require_envs_returns_dict_when_all_set(monkeypatch):
    monkeypatch.setenv("FOO", "a")
    monkeypatch.setenv("BAR", "b")
    result = _require_envs(["FOO", "BAR"])
    assert result == {"FOO": "a", "BAR": "b"}


def test_require_envs_raises_listing_missing(monkeypatch):
    monkeypatch.setenv("FOO", "a")
    monkeypatch.delenv("BAR", raising=False)
    monkeypatch.delenv("BAZ", raising=False)
    with pytest.raises(ValueError, match="BAR.*BAZ|BAZ.*BAR"):
        _require_envs(["FOO", "BAR", "BAZ"])


def test_require_envs_rejects_empty_string(monkeypatch):
    monkeypatch.setenv("FOO", "")
    with pytest.raises(ValueError, match="FOO"):
        _require_envs(["FOO"])


def test_require_envs_treats_whitespace_as_missing(monkeypatch):
    """Whitespace-only env values must fail _require_envs at startup, not pass
    through and crash per-request when Pydantic strips them in TenantContext."""
    from src.revenium_mcp_server.enhanced_server import _require_envs

    monkeypatch.setenv("FAKE_REQUIRED_FOR_TEST", "   ")
    with pytest.raises(ValueError):
        _require_envs(["FAKE_REQUIRED_FOR_TEST"])


from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def clerk_env(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "clerk")
    monkeypatch.setenv("TRANSPORT_MODE", "http")
    monkeypatch.setenv("CLERK_DOMAIN", "test-instance.clerk.accounts.dev")
    monkeypatch.setenv("CLERK_OAUTH_CLIENT_ID", "client_test")
    monkeypatch.setenv("CLERK_OAUTH_CLIENT_SECRET", "secret_test")
    monkeypatch.setenv("MCP_SERVER_BASE_URL", "https://mcp.test.io")
    monkeypatch.setenv("REVENIUM_TENANT_ID", "tenant_test")
    monkeypatch.setenv("REVENIUM_API_KEY", "key_test_abcd1234")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_test")

    from src.revenium_mcp_server.auth import ConfigManager
    ConfigManager().clear_cache()
    ConfigManager().load_from_env()

    yield

    # Teardown: clear cache so subsequent tests re-read from their own env
    ConfigManager().clear_cache()


def test_clerk_mode_missing_env_raises(monkeypatch):
    """Startup fails fast listing every missing Clerk env var."""
    from src.revenium_mcp_server.enhanced_server import _require_envs

    monkeypatch.setenv("AUTH_MODE", "clerk")
    for name in (
        "CLERK_DOMAIN",
        "CLERK_OAUTH_CLIENT_ID",
        "CLERK_OAUTH_CLIENT_SECRET",
        "MCP_SERVER_BASE_URL",
        "REVENIUM_TENANT_ID",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValueError) as exc:
        _require_envs([
            "CLERK_DOMAIN",
            "CLERK_OAUTH_CLIENT_ID",
            "CLERK_OAUTH_CLIENT_SECRET",
            "MCP_SERVER_BASE_URL",
            "REVENIUM_TENANT_ID",
        ])
    msg = str(exc.value)
    for name in (
        "CLERK_DOMAIN",
        "CLERK_OAUTH_CLIENT_ID",
        "CLERK_OAUTH_CLIENT_SECRET",
        "MCP_SERVER_BASE_URL",
        "REVENIUM_TENANT_ID",
    ):
        assert name in msg


def test_create_enhanced_server_accepts_auth_param(monkeypatch):
    """create_enhanced_server passes the auth object through to FastMCP."""
    from src.revenium_mcp_server.enhanced_server import create_enhanced_server

    monkeypatch.delenv("AUTH_MODE", raising=False)

    sentinel_auth = MagicMock(name="sentinel_auth")
    with patch(
        "src.revenium_mcp_server.enhanced_server.FastMCP"
    ) as mock_fastmcp:
        create_enhanced_server(auth=sentinel_auth)
    kwargs = mock_fastmcp.call_args.kwargs
    assert kwargs["auth"] is sentinel_auth


def test_create_enhanced_server_auth_defaults_to_none(monkeypatch):
    """With no auth arg, FastMCP is constructed with auth=None (env mode)."""
    from src.revenium_mcp_server.enhanced_server import create_enhanced_server

    monkeypatch.delenv("AUTH_MODE", raising=False)

    with patch(
        "src.revenium_mcp_server.enhanced_server.FastMCP"
    ) as mock_fastmcp:
        create_enhanced_server()
    kwargs = mock_fastmcp.call_args.kwargs
    assert kwargs["auth"] is None


def test_clerk_mode_registers_tenant_context_middleware(monkeypatch, clerk_env):
    """In clerk mode, TenantContextMiddleware is registered via mcp.add_middleware."""
    from src.revenium_mcp_server.enhanced_server import _register_tenant_middleware
    from src.revenium_mcp_server.auth.claims_middleware import (
        TenantContextMiddleware,
    )

    fake_mcp = MagicMock()
    _register_tenant_middleware(fake_mcp, auth_mode="clerk")
    assert fake_mcp.add_middleware.called
    added = fake_mcp.add_middleware.call_args.args[0]
    assert isinstance(added, TenantContextMiddleware)


def test_env_mode_does_not_register_tenant_context_middleware(monkeypatch):
    from src.revenium_mcp_server.enhanced_server import _register_tenant_middleware

    monkeypatch.delenv("AUTH_MODE", raising=False)
    fake_mcp = MagicMock()
    _register_tenant_middleware(fake_mcp, auth_mode="env")
    assert not fake_mcp.add_middleware.called


def test_api_key_mode_requires_validator(monkeypatch):
    from src.revenium_mcp_server.enhanced_server import _register_tenant_middleware

    fake_mcp = MagicMock()
    with pytest.raises(ValueError, match="validator is required"):
        _register_tenant_middleware(fake_mcp, auth_mode="api_key", validator=None)
    assert not fake_mcp.add_middleware.called


@pytest.mark.asyncio
async def test_main_wires_oidc_proxy_middleware_and_http_transport_in_clerk_mode(
    clerk_env, monkeypatch
):
    """Smoke test: main() in clerk mode instantiates OIDCProxy with the right kwargs,
    registers the TenantContextMiddleware, and starts HTTP transport.
    """
    from src.revenium_mcp_server import enhanced_server

    # Set HTTP host/port so we can assert on run_async kwargs
    monkeypatch.setenv("MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("MCP_PORT", "9000")
    # Ensure the config_url is derived from CLERK_DOMAIN (override is NOT set)
    monkeypatch.delenv("CLERK_OIDC_CONFIG_URL_OVERRIDE", raising=False)

    # Build the fake mcp instance that create_enhanced_server will return
    fake_mcp = MagicMock(name="fake_mcp")
    fake_mcp.run_async = AsyncMock(return_value=None)

    # Patch FastMCP so create_enhanced_server returns our fake_mcp
    mock_fastmcp_cls = MagicMock(name="FastMCP", return_value=fake_mcp)

    # Patch OIDCProxy (lazy-imported inside main() from fastmcp.server.auth.oidc_proxy)
    mock_oidc_proxy_instance = MagicMock(name="oidc_proxy_instance")
    mock_oidc_proxy_cls = MagicMock(name="OIDCProxy", return_value=mock_oidc_proxy_instance)

    # Patch ReveniumClient (lazy-imported inside main() from .client)
    mock_client_instance = MagicMock(name="revenium_client")
    mock_client_instance.validate_api_key = AsyncMock(return_value={"valid": True})
    mock_revenium_client_cls = MagicMock(name="ReveniumClient", return_value=mock_client_instance)

    # Patch ucm_integration_service and introspection_integration attributes on the module
    mock_ucm = MagicMock(name="ucm_integration_service")
    mock_ucm.initialize = AsyncMock(return_value=None)
    mock_ucm.integrate_with_mcp_server = AsyncMock(return_value=None)

    mock_introspection = MagicMock(name="introspection_integration")
    mock_introspection.initialize = AsyncMock(return_value=None)
    mock_introspection.get_server_summary = AsyncMock(
        return_value={"registered_tools": 0}
    )

    with (
        patch("src.revenium_mcp_server.enhanced_server.FastMCP", mock_fastmcp_cls),
        patch("fastmcp.server.auth.oidc_proxy.OIDCProxy", mock_oidc_proxy_cls),
        patch("src.revenium_mcp_server.client.ReveniumClient", mock_revenium_client_cls),
        patch("src.revenium_mcp_server.enhanced_server.install_crash_logging", return_value=MagicMock()),
        patch("src.revenium_mcp_server.enhanced_server.register_tools", new=AsyncMock(return_value=None)),
        patch.object(enhanced_server, "ucm_integration_service", mock_ucm),
        patch.object(enhanced_server, "introspection_integration", mock_introspection),
    ):
        await enhanced_server.main()

    # 1. OIDCProxy was instantiated with the correct kwargs
    mock_oidc_proxy_cls.assert_called_once()
    oidc_kwargs = mock_oidc_proxy_cls.call_args.kwargs
    assert oidc_kwargs["client_id"] == "client_test"
    assert oidc_kwargs["client_secret"] == "secret_test"
    assert oidc_kwargs["base_url"] == "https://mcp.test.io"
    assert oidc_kwargs["required_scopes"] == ["openid", "profile", "email"]
    assert oidc_kwargs["algorithm"] == "RS256"
    assert oidc_kwargs["config_url"] == (
        "https://test-instance.clerk.accounts.dev/.well-known/openid-configuration"
    )

    # 2. FastMCP was created with auth= pointing to the OIDCProxy instance
    mock_fastmcp_cls.assert_called_once()
    fastmcp_kwargs = mock_fastmcp_cls.call_args.kwargs
    assert fastmcp_kwargs["auth"] is mock_oidc_proxy_instance

    # 3. add_middleware called twice: FrameworkLeakGuardMiddleware (always, from
    #    create_enhanced_server) + TenantContextMiddleware (clerk mode only).
    from src.revenium_mcp_server.auth.claims_middleware import TenantContextMiddleware
    from src.revenium_mcp_server.middleware.framework_leak_guard import (
        FrameworkLeakGuardMiddleware,
    )

    assert fake_mcp.add_middleware.call_count == 2
    registered_types = {
        type(call.args[0]) for call in fake_mcp.add_middleware.call_args_list
    }
    assert FrameworkLeakGuardMiddleware in registered_types
    assert TenantContextMiddleware in registered_types

    # 4. run_async was called with transport="http", host, and port
    fake_mcp.run_async.assert_called_once_with(
        transport="http", host="127.0.0.1", port=9000
    )


def test_api_key_mode_registers_api_key_middleware(monkeypatch):
    from src.revenium_mcp_server.enhanced_server import _register_tenant_middleware
    from src.revenium_mcp_server.auth.api_key_middleware import ApiKeyAuthMiddleware

    fake_mcp = MagicMock()
    fake_validator = MagicMock()
    _register_tenant_middleware(
        fake_mcp, auth_mode="api_key", validator=fake_validator
    )
    assert fake_mcp.add_middleware.called
    added = fake_mcp.add_middleware.call_args.args[0]
    assert isinstance(added, ApiKeyAuthMiddleware)


def test_api_key_mode_missing_platform_url_raises(monkeypatch):
    """api_key mode fails fast when its required env vars are absent."""
    from src.revenium_mcp_server.enhanced_server import _require_envs

    monkeypatch.delenv("REVENIUM_BASE_URL", raising=False)
    monkeypatch.delenv("MCP_SERVER_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="REVENIUM_BASE_URL|MCP_SERVER_BASE_URL"):
        _require_envs(["REVENIUM_BASE_URL", "MCP_SERVER_BASE_URL"])


def test_api_key_cache_ttl_rejects_non_integer(monkeypatch):
    from src.revenium_mcp_server.enhanced_server import _read_api_key_cache_ttl
    monkeypatch.setenv("API_KEY_CACHE_TTL_SECONDS", "abc")
    with pytest.raises(ValueError, match="must be an integer"):
        _read_api_key_cache_ttl(30)


def test_api_key_cache_ttl_rejects_non_positive(monkeypatch):
    from src.revenium_mcp_server.enhanced_server import _read_api_key_cache_ttl
    monkeypatch.setenv("API_KEY_CACHE_TTL_SECONDS", "0")
    with pytest.raises(ValueError, match="positive"):
        _read_api_key_cache_ttl(30)


def test_api_key_cache_ttl_defaults_when_unset(monkeypatch):
    from src.revenium_mcp_server.enhanced_server import _read_api_key_cache_ttl
    monkeypatch.delenv("API_KEY_CACHE_TTL_SECONDS", raising=False)
    assert _read_api_key_cache_ttl(30) == 30
