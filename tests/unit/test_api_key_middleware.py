"""Unit tests for the api_key TokenVerifier and context-populating middleware."""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastmcp.exceptions import ToolError

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


_SIGNED_IN_KEY = "rev_rk_abcdef123456"
_USERS_ME_BODY = {
    "id": "usr_123",
    "email": "cfo@acme.test",
    "roles": ["ROLE_TENANT_ADMIN"],
    "tenantId": "tenant_abc",
    "defaultTeamId": "team_xyz",
}


class _Platform:
    """Answers /users/me with the signed-in user and every other path with `answer`.

    Once `revoke()` is called, /users/me refuses the key as the live platform does.
    """

    def __init__(self, answer: httpx.Response) -> None:
        self.answer = answer
        self.sign_ins = 0
        self.revoked = False
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def revoke(self) -> None:
        self.revoked = True

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/users/me"):
            self.sign_ins += 1
            if self.revoked:
                return httpx.Response(403, json={"error": "Forbidden"})
            return httpx.Response(200, json=_USERS_ME_BODY)
        return self.answer


def _platform_client(platform: _Platform):
    from src.revenium_mcp_server.auth import AuthConfig
    from src.revenium_mcp_server.auth.claims_middleware import current_tenant_context
    from src.revenium_mcp_server.client import ReveniumClient

    tenant = current_tenant_context()
    client = ReveniumClient(
        auth_config=AuthConfig(
            api_key=tenant.api_key,
            team_id=tenant.team_id,
            base_url=tenant.base_url,
            max_retries=0,
        )
    )
    client.client = platform.http
    return client


def _read_products(client):
    return client.get("/profitstream/v2/api/products")


def _analytics_read(base_url: str, params=None):
    def read(client):
        return client._request(
            "GET", "/v2/api/ai/recommendations/runs", params=params, base_url=base_url, use_bearer=True
        )

    return read


class _HostedSession:
    """One hosted caller: each `request()` signs in, then runs one tool call, as an HTTP request does."""

    def __init__(self, verifier: ApiKeyTokenVerifier, mcp) -> None:
        self._verifier = verifier
        self._mcp = mcp

    async def sign_in(self):
        return await self._verifier.verify_token(_SIGNED_IN_KEY)

    async def request(self) -> None:
        access_token = await self.sign_in()
        with patch(
            "src.revenium_mcp_server.auth.api_key_middleware.get_access_token",
            return_value=access_token,
        ):
            await self._mcp.call_tool("list_products", raise_on_error=False)


@asynccontextmanager
async def _hosted_session(
    platform: _Platform, *, tool_reports_refusal: bool = True, request=_read_products
):
    from fastmcp import Client, FastMCP

    from src.revenium_mcp_server.auth.api_key_validator import ApiKeyValidator
    from src.revenium_mcp_server.client import ReveniumAPIError

    validator = ApiKeyValidator(platform_base_url=_MOCK_BASE_URL)
    verifier = ApiKeyTokenVerifier(validator=validator, base_url="https://mcp.test.io")
    server = FastMCP("hosted")
    server.add_middleware(ApiKeyAuthMiddleware(validator=validator))

    @server.tool
    async def list_products() -> str:
        try:
            await request(_platform_client(platform))
        except ReveniumAPIError:
            if tool_reports_refusal:
                raise
            return "No products found."
        return "ok"

    with patch(
        "src.revenium_mcp_server.auth.api_key_validator.get_shared_http_client",
        return_value=platform.http,
    ), _mock_config_manager(_MOCK_BASE_URL):
        async with Client(server) as mcp:
            yield _HostedSession(verifier, mcp)


async def _sign_ins_after_a_tool_call(
    platform: _Platform, *, tool_reports_refusal: bool = True, request=_read_products
):
    """Sign in, run one hosted tool call against `platform`, then sign in again.

    Returns how many times /users/me was asked: 1 means the second sign-in was
    served from the cache, 2 means the key was re-validated.
    """
    async with _hosted_session(
        platform, tool_reports_refusal=tool_reports_refusal, request=request
    ) as session:
        await session.request()
        await session.sign_in()
    return platform.sign_ins


_KEY_REFUSALS = {
    "401": httpx.Response(401, json={"error": "Unauthorized"}),
    "403 naming no cause": httpx.Response(
        403, json={"status": 403, "error": "Forbidden", "path": "/v2/api/products"}
    ),
    "403 key suspended": httpx.Response(403, text="API key is suspended"),
    "403 numeric code": httpx.Response(403, json={"code": 403, "error": "Forbidden"}),
    "403 empty code": httpx.Response(403, json={"code": "", "error": "Forbidden"}),
    "403 list code": httpx.Response(403, json={"code": ["FORBIDDEN"], "error": "Forbidden"}),
    "403 boolean code": httpx.Response(403, json={"code": True, "error": "Forbidden"}),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("refusal", _KEY_REFUSALS.values(), ids=_KEY_REFUSALS.keys())
async def test_a_platform_refusal_on_a_tool_call_makes_the_next_sign_in_revalidate(refusal):
    """BACK-4675: a key revoked at the platform stops being served from the sign-in cache."""
    assert await _sign_ins_after_a_tool_call(_Platform(refusal)) == 2


@pytest.mark.asyncio
async def test_a_refusal_the_tool_turns_into_an_answer_still_revalidates():
    """The cache entry goes whether or not the tool raises the platform's refusal."""
    platform = _Platform(_KEY_REFUSALS["403 naming no cause"])
    assert await _sign_ins_after_a_tool_call(platform, tool_reports_refusal=False) == 2


_REQUEST_REFUSALS = {
    "500": httpx.Response(500, json={"error": "Internal Server Error"}),
    "404": httpx.Response(404, json={"error": "Not Found"}),
    "403 FORBIDDEN code": httpx.Response(
        403, json={"code": "FORBIDDEN", "message": "Access denied to this report"}
    ),
    "403 problem with a cause": httpx.Response(
        403,
        json={"code": "AI_RECOMMENDATIONS_DISABLED", "title": "Forbidden", "status": 403},
        headers={"content-type": "application/problem+json"},
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", _REQUEST_REFUSALS.values(), ids=_REQUEST_REFUSALS.keys())
async def test_a_failure_that_names_its_own_cause_keeps_the_cached_sign_in(answer):
    """A permission refusal on one request says nothing about the key, so it stays cached."""
    assert await _sign_ins_after_a_tool_call(_Platform(answer)) == 1


_CODELESS_403 = {"message": "Forbidden"}


@pytest.mark.asyncio
async def test_a_codeless_403_from_an_unpaired_analytics_host_keeps_the_cached_sign_in(monkeypatch):
    """That host turns away every key of another platform, so its refusal says nothing about this key."""
    from src.revenium_mcp_server.client import ReveniumClient
    from src.revenium_mcp_server.endpoint_registry import DEFAULT_APP_BASE_URL

    monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.revenium.invalid")
    monkeypatch.delenv("REVENIUM_APP_BASE_URL", raising=False)
    assert ReveniumClient._sent_to_unpaired_analytics_host(403, DEFAULT_APP_BASE_URL, True)

    platform = _Platform(httpx.Response(403, json=_CODELESS_403))
    read = _analytics_read(DEFAULT_APP_BASE_URL)
    assert await _sign_ins_after_a_tool_call(platform, request=read) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body", [_CODELESS_403, {"code": "", "message": "Forbidden"}], ids=["no code", "empty code"]
)
async def test_a_403_for_a_team_the_key_cannot_read_keeps_the_cached_sign_in(body):
    """A codeless 403 on a read that sent another team's id is about that team, not the key."""
    platform = _Platform(httpx.Response(403, json=body))
    read = _analytics_read("https://app.revenium.invalid", params={"teamId": "team_other"})
    assert await _sign_ins_after_a_tool_call(platform, request=read) == 1


class _ValidatorClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def validator_clock(monkeypatch):
    from functools import partial

    from cachetools import TTLCache

    from src.revenium_mcp_server.auth import api_key_validator

    clock = _ValidatorClock()
    monkeypatch.setattr(api_key_validator, "TTLCache", partial(TTLCache, timer=clock))
    return clock


def _ambiguous_eviction_interval() -> float:
    from src.revenium_mcp_server.auth.api_key_validator import (
        AMBIGUOUS_REFUSAL_EVICTION_INTERVAL_SECONDS,
    )

    return AMBIGUOUS_REFUSAL_EVICTION_INTERVAL_SECONDS


@pytest.mark.asyncio
async def test_a_burst_of_codeless_403s_from_a_valid_key_signs_it_in_again_once(validator_clock):
    """An agent probing ids it cannot see does not force one /users/me per tool call."""
    platform = _Platform(httpx.Response(403, json=_CODELESS_403))
    async with _hosted_session(platform) as session:
        for _ in range(5):
            await session.request()
            validator_clock.now += 1
        await session.sign_in()

    assert platform.sign_ins == 2


@pytest.mark.asyncio
async def test_a_codeless_403_after_the_interval_evicts_the_cached_sign_in_again(validator_clock):
    platform = _Platform(httpx.Response(403, json=_CODELESS_403))
    async with _hosted_session(platform) as session:
        await session.request()
        validator_clock.now += 1
        await session.request()
        assert platform.sign_ins == 2

        validator_clock.now += _ambiguous_eviction_interval()
        await session.request()
        await session.sign_in()

    assert platform.sign_ins == 3


@pytest.mark.asyncio
async def test_every_401_evicts_the_cached_sign_in(validator_clock):
    platform = _Platform(_KEY_REFUSALS["401"])
    async with _hosted_session(platform) as session:
        for _ in range(3):
            await session.request()
            validator_clock.now += 1
        await session.sign_in()

    assert platform.sign_ins == 4


@pytest.mark.asyncio
async def test_a_revoked_key_is_refused_on_the_call_after_its_first_codeless_403(validator_clock):
    platform = _Platform(httpx.Response(403, json=_CODELESS_403))
    async with _hosted_session(platform) as session:
        assert await session.sign_in() is not None
        platform.revoke()
        await session.request()

        assert await session.sign_in() is None


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
        with pytest.raises(ToolError, match="not available"):
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
        with pytest.raises(ToolError, match="not available"):
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
        with pytest.raises(ToolError, match="not available"):
            await mw.on_call_tool(MagicMock(), call_next)


@pytest.mark.asyncio
async def test_a_platform_lockout_at_sign_in_is_answered_429_with_the_wait(lockout_clock):
    """BACK-4717: the HTTP answer names the platform's wait, not a bad token."""
    import httpx
    from fastmcp.server.auth.middleware import RequireAuthMiddleware
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    from src.revenium_mcp_server.auth.api_key_validator import ApiKeyValidator

    platform = MagicMock()
    platform.get = AsyncMock(
        return_value=httpx.Response(
            429,
            text="Too many failed requests. Please retry after 42 seconds.",
            request=httpx.Request("GET", "https://platform.test/users/me"),
        )
    )
    verifier = ApiKeyTokenVerifier(
        validator=ApiKeyValidator(platform_base_url="https://platform.test"),
        base_url="https://mcp.test.io",
    )

    async def _tool(scope, receive, send):
        await PlainTextResponse("tool ran")(scope, receive, send)

    app = Starlette(
        routes=[Route("/mcp", RequireAuthMiddleware(_tool, required_scopes=[]))],
        middleware=verifier.get_middleware(),
    )
    with patch(
        "src.revenium_mcp_server.auth.api_key_validator.get_shared_http_client",
        return_value=platform,
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://mcp.test.io"
        ) as http:
            response = await http.get(
                "/mcp", headers={"Authorization": "Bearer rev_rk_abcdef123456"}
            )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "42"
    assert "42 seconds" in response.text
    assert "tool ran" not in response.text
