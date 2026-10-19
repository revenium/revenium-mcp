"""Tenant-context and PermissionError propagation through tool dispatch.

Covers the production dispatch path: standardized_tool_execution and
introspection handle_tool_execution must propagate auth failures (no retry,
no masking as a tool-error response) and must hand the ContextVar-resolved
tenant context to the direct-execution fallback.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from mcp.types import TextContent

from src.revenium_mcp_server.auth.claims_middleware import _current_tenant
from src.revenium_mcp_server.auth.tenant_context import TenantContext
from src.revenium_mcp_server.capability_manager.integration_service import (
    ucm_integration_service,
)
from src.revenium_mcp_server.common import tool_execution
from src.revenium_mcp_server.common.error_handling import (
    ErrorCodes,
    IntrospectionError,
    ToolError,
    ToolNotFoundError,
)
from src.revenium_mcp_server.introspection.integration import (
    introspection_integration,
)

_AUTH_ERROR = (
    "Tenant context unavailable — TenantContextMiddleware (clerk) "
    "or ApiKeyAuthMiddleware (api_key) did not run"
)


@pytest.fixture(autouse=True)
def _quiet_ucm(monkeypatch):
    """Keep the direct-execution fallback deterministic: no UCM helper."""
    monkeypatch.setattr(
        ucm_integration_service,
        "get_health_status",
        AsyncMock(return_value={"status": "unhealthy"}),
    )


@pytest.mark.asyncio
async def test_permission_error_skips_direct_fallback(monkeypatch):
    """An auth failure on the introspection path must propagate as-is and
    must NOT trigger a second execution via the direct fallback."""
    direct_calls = {"count": 0}

    class FakeTool:
        def __init__(self, ucm_helper=None):
            pass

        async def handle_action(self, action, arguments, ctx=None):
            direct_calls["count"] += 1
            return [TextContent(type="text", text="must not run")]

    async def _raise_permission(tool_name, action, arguments, ctx=None):
        raise PermissionError(_AUTH_ERROR)

    monkeypatch.setattr(
        introspection_integration, "handle_tool_execution", _raise_permission
    )

    with pytest.raises(PermissionError, match="Tenant context unavailable"):
        await tool_execution.standardized_tool_execution(
            tool_name="fake_tool",
            action="list",
            arguments={},
            tool_class=FakeTool,
        )
    assert direct_calls["count"] == 0


@pytest.mark.asyncio
async def test_tool_error_skips_direct_fallback(monkeypatch):
    """A handler refusal on the introspection path must reach the caller and
    must NOT trigger a second platform call via the direct fallback."""
    direct_calls = {"count": 0}

    class FakeTool:
        def __init__(self, ucm_helper=None):
            pass

        async def handle_action(self, action, arguments, ctx=None):
            direct_calls["count"] += 1
            return [TextContent(type="text", text="must not run")]

    async def _raise_refusal(tool_name, action, arguments, ctx=None):
        raise ToolError("platform said no", suggestions=["try again later"])

    monkeypatch.setattr(
        introspection_integration, "handle_tool_execution", _raise_refusal
    )

    with pytest.raises(ToolError, match="platform said no"):
        await tool_execution.standardized_tool_execution(
            tool_name="fake_tool",
            action="list",
            arguments={},
            tool_class=FakeTool,
        )
    assert direct_calls["count"] == 0


@pytest.mark.asyncio
async def test_permission_error_from_direct_fallback_propagates(monkeypatch):
    """When the fallback DOES run (non-auth introspection failure) and then
    hits the auth failure, the PermissionError still propagates unwrapped."""

    class FakeTool:
        def __init__(self, ucm_helper=None):
            pass

        async def handle_action(self, action, arguments, ctx=None):
            raise PermissionError(_AUTH_ERROR)

    async def _raise_introspection(tool_name, action, arguments, ctx=None):
        raise IntrospectionError(
            "introspection unavailable", tool_name=tool_name, action=action
        )

    monkeypatch.setattr(
        introspection_integration, "handle_tool_execution", _raise_introspection
    )

    with pytest.raises(PermissionError, match="Tenant context unavailable"):
        await tool_execution.standardized_tool_execution(
            tool_name="fake_tool",
            action="list",
            arguments={},
            tool_class=FakeTool,
        )


@pytest.mark.asyncio
async def test_contextvar_ctx_reaches_direct_fallback(monkeypatch):
    """ctx resolved from the ContextVar must be handed to the direct-execution
    fallback's handle_action call."""
    seen = {}

    class FakeTool:
        def __init__(self, ucm_helper=None):
            pass

        async def handle_action(self, action, arguments, ctx=None):
            seen["ctx"] = ctx
            return [TextContent(type="text", text="ok")]

    async def _raise_introspection(tool_name, action, arguments, ctx=None):
        raise IntrospectionError(
            "introspection unavailable", tool_name=tool_name, action=action
        )

    monkeypatch.setattr(
        introspection_integration, "handle_tool_execution", _raise_introspection
    )

    ctx = TenantContext(team_id="team_a", api_key="hak_tenant_a")
    token = _current_tenant.set(ctx)
    try:
        result = await tool_execution.standardized_tool_execution(
            tool_name="fake_tool",
            action="list",
            arguments={},
            tool_class=FakeTool,
        )
    finally:
        _current_tenant.reset(token)

    assert result[0].text == "ok"
    assert seen["ctx"] is ctx


@pytest.mark.asyncio
async def test_handle_tool_execution_reraises_permission_error(monkeypatch):
    """The introspection dispatcher must re-raise PermissionError instead of
    converting it into a tool-error text response."""

    class FakeProvider:
        async def handle_action(self, action, arguments, ctx=None):
            raise PermissionError(_AUTH_ERROR)

    async def _get_provider(tool_name):
        return FakeProvider()

    monkeypatch.setattr(
        introspection_integration.engine.registry, "get_provider", _get_provider
    )

    with pytest.raises(PermissionError, match="Tenant context unavailable"):
        await introspection_integration.handle_tool_execution(
            "fake_tool", "list", {}
        )


@pytest.mark.asyncio
async def test_registered_provider_receives_the_resolved_context(monkeypatch):
    """BACK-4633: the introspection path every registered tool takes first must
    hand the provider the tenant context standardized_tool_execution resolved."""
    seen = {}

    class RecordingProvider:
        async def handle_action(self, action, arguments, ctx=None):
            seen["ctx"] = ctx
            return [TextContent(type="text", text="ok")]

    async def _get_provider(tool_name):
        return RecordingProvider()

    monkeypatch.setattr(
        introspection_integration.engine.registry, "get_provider", _get_provider
    )

    ctx = TenantContext(team_id="team_a", api_key="hak_tenant_a")
    token = _current_tenant.set(ctx)
    try:
        result = await tool_execution.standardized_tool_execution(
            tool_name="fake_tool",
            action="list",
            arguments={},
            tool_class=object,
        )
    finally:
        _current_tenant.reset(token)

    assert result[0].text == "ok"
    assert seen["ctx"] is ctx


@pytest.mark.asyncio
async def test_tool_error_from_introspection_is_raised_once(monkeypatch):
    """A ToolError the action raised on the introspection path is the answer.
    It must reach the caller as-is, without re-running the whole action on a
    fresh tool instance through the direct fallback (a second round of
    platform calls and waits for the same error)."""
    runs = {"introspection": 0, "direct": 0}

    class FakeTool:
        def __init__(self, ucm_helper=None):
            pass

        async def handle_action(self, action, arguments, ctx=None):
            runs["direct"] += 1
            return [TextContent(type="text", text="must not run")]

    async def _raise_tool_error(tool_name, action, arguments, ctx=None):
        runs["introspection"] += 1
        raise ToolError(
            message="Transaction lookup failed", error_code=ErrorCodes.API_ERROR
        )

    monkeypatch.setattr(
        introspection_integration, "handle_tool_execution", _raise_tool_error
    )

    with pytest.raises(ToolError, match="Transaction lookup failed") as raised:
        await tool_execution.standardized_tool_execution(
            tool_name="fake_tool",
            action="lookup_transactions",
            arguments={},
            tool_class=FakeTool,
        )
    assert raised.value.error_code == ErrorCodes.API_ERROR
    assert runs == {"introspection": 1, "direct": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        IntrospectionError("introspection unavailable", tool_name="t", action="a"),
        ToolNotFoundError("not registered", tool_name="t", action="a"),
    ],
)
async def test_introspection_failures_still_fall_back(monkeypatch, error):
    """Introspection-layer failures are not ToolErrors and still fall back to
    direct execution."""

    class FakeTool:
        def __init__(self, ucm_helper=None):
            pass

        async def handle_action(self, action, arguments, ctx=None):
            return [TextContent(type="text", text="direct ok")]

    async def _raise(tool_name, action, arguments, ctx=None):
        raise error

    monkeypatch.setattr(introspection_integration, "handle_tool_execution", _raise)

    result = await tool_execution.standardized_tool_execution(
        tool_name="fake_tool", action="list", arguments={}, tool_class=FakeTool
    )
    assert result[0].text == "direct ok"
