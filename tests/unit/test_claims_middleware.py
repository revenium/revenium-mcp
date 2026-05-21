"""Unit tests for TenantContextMiddleware and the _current_tenant ContextVar."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.revenium_mcp_server.auth.tenant_context import TenantContext


def _make_fake_tenant(team_id: str = "team_x") -> TenantContext:
    return TenantContext(
        team_id=team_id,
        api_key="shared_key_abcd",
        tenant_id="tenant_x",
    )


@pytest.mark.asyncio
async def test_middleware_sets_context_var_from_resolved_tenant():
    from src.revenium_mcp_server.auth.claims_middleware import (
        TenantContextMiddleware,
        current_tenant_context,
    )

    resolver = MagicMock()
    resolver.resolve.return_value = _make_fake_tenant(team_id="inside")
    mw = TenantContextMiddleware(resolver)

    observed: list[TenantContext | None] = []

    async def call_next(context):
        observed.append(current_tenant_context())
        return "ok"

    with patch(
        "src.revenium_mcp_server.auth.claims_middleware.get_access_token"
    ) as mock_get:
        mock_get.return_value = MagicMock(claims={"revenium_team_id": "inside"})
        result = await mw.on_call_tool(context=MagicMock(), call_next=call_next)

    assert result == "ok"
    assert observed == [_make_fake_tenant(team_id="inside")]
    # After the middleware returns, ContextVar is reset
    assert current_tenant_context() is None


@pytest.mark.asyncio
async def test_middleware_resets_context_var_on_exception():
    from src.revenium_mcp_server.auth.claims_middleware import (
        TenantContextMiddleware,
        current_tenant_context,
    )

    resolver = MagicMock()
    resolver.resolve.return_value = _make_fake_tenant()
    mw = TenantContextMiddleware(resolver)

    async def call_next(context):
        raise RuntimeError("boom")

    with patch(
        "src.revenium_mcp_server.auth.claims_middleware.get_access_token"
    ) as mock_get:
        mock_get.return_value = MagicMock(claims={})
        with pytest.raises(RuntimeError, match="boom"):
            await mw.on_call_tool(context=MagicMock(), call_next=call_next)

    assert current_tenant_context() is None


@pytest.mark.asyncio
async def test_middleware_propagates_permission_error():
    from src.revenium_mcp_server.auth.claims_middleware import (
        TenantContextMiddleware,
    )

    resolver = MagicMock()
    resolver.resolve.side_effect = PermissionError("missing claim")
    mw = TenantContextMiddleware(resolver)

    async def call_next(context):
        raise AssertionError("should not be called")

    with patch(
        "src.revenium_mcp_server.auth.claims_middleware.get_access_token"
    ) as mock_get:
        mock_get.return_value = MagicMock(claims={})
        with pytest.raises(PermissionError, match="missing claim"):
            await mw.on_call_tool(context=MagicMock(), call_next=call_next)


@pytest.mark.asyncio
async def test_middleware_with_no_token_passes_empty_claims():
    from src.revenium_mcp_server.auth.claims_middleware import (
        TenantContextMiddleware,
    )

    resolver = MagicMock()
    resolver.resolve.return_value = _make_fake_tenant()
    mw = TenantContextMiddleware(resolver)

    async def call_next(context):
        return "ok"

    with patch(
        "src.revenium_mcp_server.auth.claims_middleware.get_access_token"
    ) as mock_get:
        mock_get.return_value = None
        await mw.on_call_tool(context=MagicMock(), call_next=call_next)

    resolver.resolve.assert_called_once_with({})


def test_current_tenant_context_default_is_none():
    from src.revenium_mcp_server.auth.claims_middleware import (
        current_tenant_context,
    )

    assert current_tenant_context() is None


@pytest.mark.asyncio
async def test_concurrent_requests_have_isolated_context():
    from contextvars import ContextVar
    from src.revenium_mcp_server.auth.claims_middleware import (
        TenantContextMiddleware,
        current_tenant_context,
    )

    resolver = MagicMock()

    def resolve_fn(claims):
        team_id = claims.get("revenium_team_id", "unknown")
        return _make_fake_tenant(team_id=team_id)

    resolver.resolve.side_effect = resolve_fn
    mw = TenantContextMiddleware(resolver)

    # Task-local team_id so concurrent tasks see distinct fake tokens
    # without two concurrent `with patch(...)` blocks racing on the same
    # target (which would leak a stale mock past the test boundary).
    _test_team: ContextVar[str] = ContextVar("test_team", default="unknown")

    def fake_get_access_token():
        return MagicMock(claims={"revenium_team_id": _test_team.get()})

    async def _run(team_id: str, observed: list):
        _test_team.set(team_id)

        async def call_next(context):
            # yield to the scheduler so the two tasks interleave
            await asyncio.sleep(0)
            observed.append((team_id, current_tenant_context()))
            return "ok"

        await mw.on_call_tool(context=MagicMock(), call_next=call_next)

    # Single patch at the outer scope — no concurrent stacking, no leak.
    with patch(
        "src.revenium_mcp_server.auth.claims_middleware.get_access_token",
        side_effect=fake_get_access_token,
    ):
        observed: list = []
        await asyncio.gather(_run("team_a", observed), _run("team_b", observed))

    # Each observation must match the team_id of its own request.
    for tid, ctx in observed:
        assert ctx is not None
        assert ctx.team_id == tid
