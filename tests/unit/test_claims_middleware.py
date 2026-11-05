"""Unit tests for TenantContextMiddleware and the _current_tenant ContextVar."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from src.revenium_mcp_server.auth.tenant_context import TenantContext


def _make_fake_tenant(team_id: str = "team_x") -> TenantContext:
    return TenantContext(
        team_id=team_id,
        api_key="shared_key_abcd",
        tenant_id="tenant_x",
    )


def _mock_token(claims: dict, token: str = "jwt_token_value") -> MagicMock:
    """Build a mock AccessToken with both .claims and .token attributes."""
    m = MagicMock()
    m.claims = claims
    m.token = token
    return m


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
        mock_get.return_value = _mock_token({"revenium_team_id": "inside"}, token="tok_abc")
        result = await mw.on_call_tool(context=MagicMock(), call_next=call_next)

    assert result == "ok"
    assert observed == [_make_fake_tenant(team_id="inside")]
    # After the middleware returns, ContextVar is reset
    assert current_tenant_context() is None
    # The resolver must receive the token string from AccessToken.token
    resolver.resolve.assert_called_once_with(
        {"revenium_team_id": "inside"}, clerk_jwt="tok_abc"
    )


@pytest.mark.asyncio
async def test_middleware_passes_token_to_resolver():
    """Middleware forwards AccessToken.token as clerk_jwt to the resolver."""
    from src.revenium_mcp_server.auth.claims_middleware import TenantContextMiddleware

    resolver = MagicMock()
    resolver.resolve.return_value = _make_fake_tenant()
    mw = TenantContextMiddleware(resolver)

    async def call_next(context):
        return "ok"

    with patch(
        "src.revenium_mcp_server.auth.claims_middleware.get_access_token"
    ) as mock_get:
        mock_get.return_value = _mock_token({"sub": "user_1"}, token="upstream_clerk_jwt")
        await mw.on_call_tool(context=MagicMock(), call_next=call_next)

    resolver.resolve.assert_called_once_with(
        {"sub": "user_1"}, clerk_jwt="upstream_clerk_jwt"
    )


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
        mock_get.return_value = _mock_token({})
        with pytest.raises(RuntimeError, match="boom"):
            await mw.on_call_tool(context=MagicMock(), call_next=call_next)

    assert current_tenant_context() is None


@pytest.fixture(autouse=True)
def _production_app_host(monkeypatch):
    monkeypatch.delenv("REVENIUM_APP_BASE_URL", raising=False)
    monkeypatch.delenv("REVENIUM_BASE_URL", raising=False)


async def _refusal_for(claims: dict, token: str = "jwt_token_value") -> ToolError:
    """Drive on_call_tool through the real Clerk resolver and return its refusal."""
    from src.revenium_mcp_server.auth.claims_middleware import TenantContextMiddleware
    from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

    mw = TenantContextMiddleware(ClerkTenantResolver())

    async def call_next(context):
        raise AssertionError("a refused caller must not reach the tool")

    with patch(
        "src.revenium_mcp_server.auth.claims_middleware.get_access_token"
    ) as mock_get:
        mock_get.return_value = _mock_token(claims, token=token)
        with pytest.raises(ToolError) as excinfo:
            await mw.on_call_tool(context=MagicMock(), call_next=call_next)
    assert isinstance(excinfo.value.__cause__, PermissionError)
    return excinfo.value


@pytest.mark.asyncio
async def test_unlinked_sign_in_is_told_to_open_the_app_and_reconnect():
    error = await _refusal_for({"sub": "user_1"})

    assert str(error) == (
        "Your sign-in is not linked to a Revenium team yet. Open "
        "https://app.revenium.ai once with the same email, then reconnect the "
        "connector. For support: JWT is missing required claim(s): "
        "revenium_team_id, tenant_id."
    )
    assert "Internal server error" not in str(error)


@pytest.mark.asyncio
async def test_blank_team_id_counts_as_not_linked():
    error = await _refusal_for(
        {"sub": "user_1", "revenium_team_id": "  ", "tenant_id": "tenant_1"}
    )

    assert str(error).startswith("Your sign-in is not linked to a Revenium team yet.")
    assert str(error).endswith("missing required claim(s): revenium_team_id.")


@pytest.mark.asyncio
async def test_malformed_tenant_id_names_an_unreadable_sign_in():
    error = await _refusal_for(
        {"sub": "user_1", "revenium_team_id": "team_1", "tenant_id": 42}
    )

    assert str(error) == (
        "Your sign-in carries Revenium team details this server cannot read. "
        "Open https://app.revenium.ai once with the same email, then reconnect "
        "the connector. If it keeps happening, contact Revenium support. For "
        "support: JWT has malformed claim(s): tenant_id (expected a non-empty "
        "string)."
    )


@pytest.mark.asyncio
async def test_missing_and_malformed_claims_lead_with_not_linked_and_list_both():
    error = await _refusal_for({"sub": "user_1", "tenant_id": ["t"]})

    assert str(error).startswith("Your sign-in is not linked to a Revenium team yet.")
    assert str(error).endswith(
        "For support: JWT is missing required claim(s): revenium_team_id; "
        "JWT has malformed claim(s): tenant_id (expected a non-empty string)."
    )


@pytest.mark.asyncio
async def test_sign_in_without_a_forwardable_token_is_told_to_reconnect():
    error = await _refusal_for(
        {"sub": "user_1", "revenium_team_id": "team_1", "tenant_id": "tenant_1"},
        token="   ",
    )

    assert str(error) == (
        "Your sign-in reached the server without an access token it can use. "
        "Reconnect the connector to sign in again. For support: No verified "
        "access token available to forward downstream."
    )


@pytest.mark.asyncio
async def test_remedy_names_the_app_this_deployment_pairs_with(monkeypatch):
    monkeypatch.delenv("REVENIUM_APP_BASE_URL", raising=False)
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.dev.hcapp.io")

    error = await _refusal_for({"sub": "user_1"})

    assert str(error).startswith(
        "Your sign-in is not linked to a Revenium team yet. Open "
        "https://ai.dev.hcapp.io once with the same email, then reconnect the "
        "connector."
    )


@pytest.mark.asyncio
async def test_refusal_keeps_the_rejection_warning_in_the_log():
    from loguru import logger

    records: list[str] = []
    sink_id = logger.add(lambda msg: records.append(msg.record["message"]), level="WARNING")
    try:
        await _refusal_for({"sub": "user_1"})
    finally:
        logger.remove(sink_id)

    assert (
        "Tenant resolution rejected: JWT is missing required claim(s): "
        "revenium_team_id, tenant_id"
    ) in records


@pytest.mark.asyncio
async def test_refusal_from_a_bare_permission_error_still_names_the_remedy():
    from src.revenium_mcp_server.auth.claims_middleware import TenantContextMiddleware

    resolver = MagicMock()
    resolver.resolve.side_effect = PermissionError("missing claim")
    mw = TenantContextMiddleware(resolver)

    async def call_next(context):
        raise AssertionError("should not be called")

    with patch(
        "src.revenium_mcp_server.auth.claims_middleware.get_access_token"
    ) as mock_get:
        mock_get.return_value = _mock_token({})
        with pytest.raises(ToolError) as excinfo:
            await mw.on_call_tool(context=MagicMock(), call_next=call_next)

    assert str(excinfo.value) == (
        "Your sign-in is not linked to a Revenium team yet. Open "
        "https://app.revenium.ai once with the same email, then reconnect the "
        "connector. For support: missing claim."
    )


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

    resolver.resolve.assert_called_once_with({}, clerk_jwt=None)


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

    def resolve_fn(claims, *, clerk_jwt=None):
        team_id = claims.get("revenium_team_id", "unknown")
        return _make_fake_tenant(team_id=team_id)

    resolver.resolve.side_effect = resolve_fn
    mw = TenantContextMiddleware(resolver)

    # Task-local team_id so concurrent tasks see distinct fake tokens
    # without two concurrent `with patch(...)` blocks racing on the same
    # target (which would leak a stale mock past the test boundary).
    _test_team: ContextVar[str] = ContextVar("test_team", default="unknown")

    def fake_get_access_token():
        return _mock_token({"revenium_team_id": _test_team.get()})

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


@pytest.mark.asyncio
async def test_refusal_reaches_the_client_as_an_error_result_with_its_text():
    from fastmcp import Client, FastMCP

    from src.revenium_mcp_server.auth.claims_middleware import TenantContextMiddleware
    from src.revenium_mcp_server.auth.tenant_resolver import ClerkTenantResolver

    mcp = FastMCP("clerk-refusal-boundary")

    @mcp.tool
    def get_products() -> str:
        raise AssertionError("a refused caller must not reach the tool")

    mcp.add_middleware(TenantContextMiddleware(ClerkTenantResolver()))

    with patch(
        "src.revenium_mcp_server.auth.claims_middleware.get_access_token"
    ) as mock_get:
        mock_get.return_value = _mock_token({"sub": "user_1"})
        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_products", {}, raise_on_error=False
            )

    assert result.is_error is True
    text = result.content[0].text
    assert text.startswith("Your sign-in is not linked to a Revenium team yet.")
    assert "Internal server error" not in text
