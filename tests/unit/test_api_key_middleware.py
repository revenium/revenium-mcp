"""Unit tests for the api_key TokenVerifier and context-populating middleware."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.auth.api_key_validator import (
    ApiKeyIdentity,
    InvalidTokenError,
    KeyExpiredError,
    KeySuspendedError,
)
from src.revenium_mcp_server.auth.api_key_middleware import (
    ApiKeyAuthMiddleware,
    ApiKeyTokenVerifier,
)

_GET_CONFIG_VALUE_PATCH = "src.revenium_mcp_server.auth.api_key_middleware.get_config_value"
_MOCK_BASE_URL = "https://api.revenium.io"


def _mock_config_manager(base_url: str = _MOCK_BASE_URL):
    """Patch base-URL resolution in the middleware module to return base_url."""
    return patch(_GET_CONFIG_VALUE_PATCH, return_value=base_url)


IDENTITY = ApiKeyIdentity(
    user_id="usr_123",
    tenant_id="tenant_abc",
    team_id="team_xyz",
    team_ids=("team_xyz",),
    email="cfo@acme.test",
    roles=["ROLE_TENANT_ADMIN"],
    scope_from_prefix="READ",
)

MULTI_TEAM_IDENTITY = ApiKeyIdentity(
    user_id="usr_123",
    tenant_id="tenant_abc",
    team_id="team_xyz",
    team_ids=("team_xyz", "team_second"),
    email="cfo@acme.test",
    roles=["ROLE_TENANT_ADMIN"],
    scope_from_prefix="READ",
)


def _verifier(validate_side_effect=None, validate_return=None):
    validator = MagicMock()
    validator.validate = AsyncMock(
        return_value=validate_return, side_effect=validate_side_effect
    )
    validator.invalidate = MagicMock()
    verifier = ApiKeyTokenVerifier(
        validator=validator, base_url="https://mcp.test.io"
    )
    return verifier, validator


@pytest.mark.asyncio
async def test_verify_token_success_returns_access_token_with_claims():
    verifier, _ = _verifier(validate_return=IDENTITY)
    token = await verifier.verify_token("rev_rk_abcdef123456")
    assert token is not None
    assert token.token == "rev_rk_abcdef123456"
    assert token.claims["tenant_id"] == "tenant_abc"
    assert token.claims["team_id"] == "team_xyz"
    assert token.claims["user_id"] == "usr_123"
    assert token.claims["scope_from_prefix"] == "READ"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [InvalidTokenError("x"), KeySuspendedError("y"), KeyExpiredError("z")],
)
async def test_verify_token_failure_returns_none(exc):
    verifier, _ = _verifier(validate_side_effect=exc)
    assert await verifier.verify_token("rev_rk_badkey1234567") is None


@pytest.mark.asyncio
async def test_middleware_populates_current_tenant():
    from src.revenium_mcp_server.auth.claims_middleware import current_tenant_context

    validator = MagicMock()
    validator.invalidate = MagicMock()
    mw = ApiKeyAuthMiddleware(validator=validator)

    fake_access_token = MagicMock()
    fake_access_token.token = "rev_rk_abcdef123456"
    fake_access_token.claims = {
        "tenant_id": "tenant_abc",
        "team_id": "team_xyz",
        "user_id": "usr_123",
        "scope_from_prefix": "READ",
    }

    seen = {}

    async def call_next(ctx):
        c = current_tenant_context()
        seen["tenant_id"] = c.tenant_id
        seen["team_id"] = c.team_id
        seen["user_id"] = c.user_id
        seen["api_key"] = c.api_key
        return "ok"

    with _mock_config_manager():
        with patch(
            "src.revenium_mcp_server.auth.api_key_middleware.get_access_token",
            return_value=fake_access_token,
        ):
            result = await mw.on_call_tool(MagicMock(), call_next)

    assert result == "ok"
    assert seen == {
        "tenant_id": "tenant_abc",
        "team_id": "team_xyz",
        "user_id": "usr_123",
        "api_key": "rev_rk_abcdef123456",
    }
    assert current_tenant_context() is None


@pytest.mark.asyncio
async def test_middleware_resolves_base_url_without_server_api_key(monkeypatch):
    """Regression: api_key mode has no server-wide REVENIUM_API_KEY, so the
    middleware must not consult ConfigManager (which would raise). It resolves
    the downstream base URL from REVENIUM_BASE_URL instead."""
    from src.revenium_mcp_server.auth.claims_middleware import current_tenant_context

    monkeypatch.delenv("REVENIUM_API_KEY", raising=False)
    monkeypatch.delenv("REVENIUM_TEAM_ID", raising=False)
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.dev.revenium.io")

    validator = MagicMock()
    validator.invalidate = MagicMock()
    mw = ApiKeyAuthMiddleware(validator=validator)

    fake_access_token = MagicMock()
    fake_access_token.token = "rev_rk_abcdef123456"
    fake_access_token.claims = {
        "tenant_id": "tenant_abc",
        "team_id": "team_xyz",
        "user_id": "usr_123",
        "scope_from_prefix": "READ",
    }

    seen = {}

    async def call_next(ctx):
        seen["base_url"] = current_tenant_context().base_url
        return "ok"

    with patch(
        "src.revenium_mcp_server.auth.api_key_middleware.get_access_token",
        return_value=fake_access_token,
    ):
        result = await mw.on_call_tool(MagicMock(), call_next)

    assert result == "ok"
    assert seen["base_url"] == "https://api.dev.revenium.io"


@pytest.mark.asyncio
async def test_middleware_invalidates_on_downstream_auth_error():
    validator = MagicMock()
    validator.invalidate = MagicMock()
    mw = ApiKeyAuthMiddleware(validator=validator)

    fake_access_token = MagicMock()
    fake_access_token.token = "rev_rk_abcdef123456"
    fake_access_token.claims = {
        "tenant_id": "tenant_abc",
        "team_id": "team_xyz",
        "user_id": "usr_123",
        "scope_from_prefix": "READ",
    }

    from src.revenium_mcp_server.client import ReveniumAPIError

    async def call_next(ctx):
        raise ReveniumAPIError("forbidden", status_code=403)

    with _mock_config_manager():
        with patch(
            "src.revenium_mcp_server.auth.api_key_middleware.get_access_token",
            return_value=fake_access_token,
        ):
            with pytest.raises(ReveniumAPIError):
                await mw.on_call_tool(MagicMock(), call_next)

    validator.invalidate.assert_called_once_with("rev_rk_abcdef123456")


@pytest.mark.asyncio
async def test_middleware_does_not_invalidate_on_non_auth_error():
    """A non-auth downstream error (e.g. 500) re-raises but must NOT invalidate."""
    validator = MagicMock()
    validator.invalidate = MagicMock()
    mw = ApiKeyAuthMiddleware(validator=validator)

    fake_access_token = MagicMock()
    fake_access_token.token = "rev_rk_abcdef123456"
    fake_access_token.claims = {
        "tenant_id": "tenant_abc",
        "team_id": "team_xyz",
        "user_id": "usr_123",
        "scope_from_prefix": "READ",
    }

    from src.revenium_mcp_server.client import ReveniumAPIError

    async def call_next(ctx):
        raise ReveniumAPIError("server error", status_code=500)

    with _mock_config_manager():
        with patch(
            "src.revenium_mcp_server.auth.api_key_middleware.get_access_token",
            return_value=fake_access_token,
        ):
            with pytest.raises(ReveniumAPIError):
                await mw.on_call_tool(MagicMock(), call_next)

    validator.invalidate.assert_not_called()


@pytest.mark.asyncio
async def test_verify_token_claims_include_team_ids():
    verifier, _ = _verifier(validate_return=MULTI_TEAM_IDENTITY)
    token = await verifier.verify_token("rev_rk_abcdef123456")
    assert token is not None
    assert token.claims["team_ids"] == ["team_xyz", "team_second"]


@pytest.mark.asyncio
async def test_middleware_resets_context_when_call_next_raises():
    """The _current_tenant ContextVar must be reset even on a downstream exception."""
    from src.revenium_mcp_server.auth.claims_middleware import current_tenant_context

    validator = MagicMock()
    validator.invalidate = MagicMock()
    mw = ApiKeyAuthMiddleware(validator=validator)

    fake_access_token = MagicMock()
    fake_access_token.token = "rev_rk_abcdef123456"
    fake_access_token.claims = {
        "tenant_id": "tenant_abc",
        "team_id": "team_xyz",
        "user_id": "usr_123",
        "scope_from_prefix": "READ",
    }

    from src.revenium_mcp_server.client import ReveniumAPIError

    async def call_next(ctx):
        raise ReveniumAPIError("boom", status_code=403)

    with _mock_config_manager():
        with patch(
            "src.revenium_mcp_server.auth.api_key_middleware.get_access_token",
            return_value=fake_access_token,
        ):
            with pytest.raises(ReveniumAPIError):
                await mw.on_call_tool(MagicMock(), call_next)

    assert current_tenant_context() is None


def _headers_patch(headers):
    return patch(
        "src.revenium_mcp_server.auth.api_key_middleware.get_http_headers",
        return_value=headers,
    )


def _multi_team_access_token(*, include_team_ids: bool = True):
    fake = MagicMock()
    fake.token = "rev_rk_abcdef123456"
    fake.claims = {
        "tenant_id": "tenant_abc",
        "team_id": "team_xyz",
        "user_id": "usr_123",
        "scope_from_prefix": "READ",
    }
    if include_team_ids:
        fake.claims["team_ids"] = ["team_xyz", "team_second"]
    return fake


@pytest.mark.asyncio
async def test_valid_team_override_selects_requested_team():
    from src.revenium_mcp_server.auth.claims_middleware import current_tenant_context

    validator = MagicMock()
    validator.invalidate = MagicMock()
    mw = ApiKeyAuthMiddleware(validator=validator)

    seen = {}

    async def call_next(ctx):
        seen["team_id"] = current_tenant_context().team_id
        return "ok"

    with _mock_config_manager(), _headers_patch(
        {"x-revenium-team-id": "team_second"}
    ), patch(
        "src.revenium_mcp_server.auth.api_key_middleware.get_access_token",
        return_value=_multi_team_access_token(),
    ):
        result = await mw.on_call_tool(MagicMock(), call_next)

    assert result == "ok"
    assert seen["team_id"] == "team_second"


@pytest.mark.asyncio
async def test_invalid_team_override_rejected_tool_not_called():
    from src.revenium_mcp_server.auth.claims_middleware import current_tenant_context

    validator = MagicMock()
    validator.invalidate = MagicMock()
    mw = ApiKeyAuthMiddleware(validator=validator)

    called = []

    async def call_next(ctx):
        called.append(True)
        return "ok"

    with _mock_config_manager(), _headers_patch(
        {"x-revenium-team-id": "team_forbidden"}
    ), patch(
        "src.revenium_mcp_server.auth.api_key_middleware.get_access_token",
        return_value=_multi_team_access_token(),
    ):
        with pytest.raises(PermissionError, match="not available"):
            await mw.on_call_tool(MagicMock(), call_next)

    assert called == []
    assert current_tenant_context() is None


@pytest.mark.asyncio
async def test_empty_header_falls_back_to_default_team():
    from src.revenium_mcp_server.auth.claims_middleware import current_tenant_context

    validator = MagicMock()
    validator.invalidate = MagicMock()
    mw = ApiKeyAuthMiddleware(validator=validator)

    seen = {}

    async def call_next(ctx):
        seen["team_id"] = current_tenant_context().team_id
        return "ok"

    with _mock_config_manager(), _headers_patch(
        {"x-revenium-team-id": "   "}
    ), patch(
        "src.revenium_mcp_server.auth.api_key_middleware.get_access_token",
        return_value=_multi_team_access_token(),
    ):
        result = await mw.on_call_tool(MagicMock(), call_next)

    assert result == "ok"
    assert seen["team_id"] == "team_xyz"


@pytest.mark.asyncio
async def test_override_with_missing_team_ids_claim_fails_closed():
    validator = MagicMock()
    validator.invalidate = MagicMock()
    mw = ApiKeyAuthMiddleware(validator=validator)

    async def call_next(ctx):  # pragma: no cover - must not run
        return "ok"

    with _mock_config_manager(), _headers_patch(
        {"x-revenium-team-id": "team_second"}
    ), patch(
        "src.revenium_mcp_server.auth.api_key_middleware.get_access_token",
        return_value=_multi_team_access_token(include_team_ids=False),
    ):
        with pytest.raises(PermissionError, match="not available"):
            await mw.on_call_tool(MagicMock(), call_next)


@pytest.mark.asyncio
async def test_verifier_to_middleware_round_trip_with_override():
    """The claims produced by verify_token satisfy the middleware's override check."""
    from src.revenium_mcp_server.auth.claims_middleware import current_tenant_context

    verifier, validator = _verifier(validate_return=MULTI_TEAM_IDENTITY)
    access_token = await verifier.verify_token("rev_rk_abcdef123456")
    assert access_token is not None

    mw = ApiKeyAuthMiddleware(validator=validator)
    seen = {}

    async def call_next(ctx):
        seen["team_id"] = current_tenant_context().team_id
        return "ok"

    with _mock_config_manager(), _headers_patch(
        {"x-revenium-team-id": "team_second"}
    ), patch(
        "src.revenium_mcp_server.auth.api_key_middleware.get_access_token",
        return_value=access_token,
    ):
        result = await mw.on_call_tool(MagicMock(), call_next)

    assert result == "ok"
    assert seen["team_id"] == "team_second"


@pytest.mark.asyncio
async def test_absent_header_uses_default_team():
    from src.revenium_mcp_server.auth.claims_middleware import current_tenant_context

    validator = MagicMock()
    validator.invalidate = MagicMock()
    mw = ApiKeyAuthMiddleware(validator=validator)

    seen = {}

    async def call_next(ctx):
        seen["team_id"] = current_tenant_context().team_id
        return "ok"

    with _mock_config_manager(), _headers_patch({}), patch(
        "src.revenium_mcp_server.auth.api_key_middleware.get_access_token",
        return_value=_multi_team_access_token(),
    ):
        result = await mw.on_call_tool(MagicMock(), call_next)

    assert result == "ok"
    assert seen["team_id"] == "team_xyz"


@pytest.mark.asyncio
async def test_override_with_none_team_ids_claim_fails_closed():
    validator = MagicMock()
    validator.invalidate = MagicMock()
    mw = ApiKeyAuthMiddleware(validator=validator)

    fake = _multi_team_access_token(include_team_ids=False)
    fake.claims["team_ids"] = None

    async def call_next(ctx):  # pragma: no cover - must not run
        return "ok"

    with _mock_config_manager(), _headers_patch(
        {"x-revenium-team-id": "team_second"}
    ), patch(
        "src.revenium_mcp_server.auth.api_key_middleware.get_access_token",
        return_value=fake,
    ):
        with pytest.raises(PermissionError, match="not available"):
            await mw.on_call_tool(MagicMock(), call_next)
