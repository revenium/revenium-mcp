"""Unit tests for the per-request API-key validator."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.auth.api_key_validator import (
    ApiKeyIdentity,
    ApiKeyValidator,
    ApiKeyValidationError,
    InsufficientScopeError,
    InvalidTokenError,
    KeyExpiredError,
    KeySuspendedError,
)

USERS_ME = {
    "id": "usr_123",
    "email": "cfo@acme.test",
    "roles": ["ROLE_TENANT_ADMIN"],
    "tenantId": "tenant_abc",
    "defaultTeamId": "team_xyz",
}


def _resp(status, *, json_body=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=json_body or {})
    r.text = text
    return r


def _validator_with_response(resp):
    """Build a validator whose shared HTTP client returns `resp` from .get()."""
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    v = ApiKeyValidator(platform_base_url="https://platform.test", ttl_seconds=30)
    return v, client


@pytest.mark.asyncio
async def test_valid_200_maps_identity():
    v, client = _validator_with_response(_resp(200, json_body=USERS_ME))
    with patch(
        "src.revenium_mcp_server.auth.api_key_validator.get_shared_http_client",
        return_value=client,
    ):
        identity = await v.validate("rev_rk_abcdef123456")
    assert isinstance(identity, ApiKeyIdentity)
    assert identity.user_id == "usr_123"
    assert identity.tenant_id == "tenant_abc"
    assert identity.team_id == "team_xyz"
    assert identity.scope_from_prefix == "READ"


@pytest.mark.asyncio
async def test_calls_profitstream_users_me_path():
    """The validator must hit the legacy /profitstream/v2/api/users/me path."""
    v, client = _validator_with_response(_resp(200, json_body=USERS_ME))
    with patch(
        "src.revenium_mcp_server.auth.api_key_validator.get_shared_http_client",
        return_value=client,
    ):
        await v.validate("rev_rk_abcdef123456")
    called_url = client.get.await_args.args[0]
    assert called_url == "https://platform.test/profitstream/v2/api/users/me"


@pytest.mark.asyncio
async def test_authenticates_with_x_api_key_header():
    """The legacy platform expects x-api-key, not Authorization: Bearer."""
    v, client = _validator_with_response(_resp(200, json_body=USERS_ME))
    with patch(
        "src.revenium_mcp_server.auth.api_key_validator.get_shared_http_client",
        return_value=client,
    ):
        await v.validate("rev_rk_abcdef123456")
    headers = client.get.await_args.kwargs["headers"]
    assert headers == {"x-api-key": "rev_rk_abcdef123456"}
    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_team_id_falls_back_to_first_team_when_default_null():
    """defaultTeamId can be null; resolve team_id from teams[0] instead."""
    body = {
        **USERS_ME,
        "defaultTeamId": None,
        "teams": [{"id": "team_first"}, {"id": "team_second"}],
    }
    v, client = _validator_with_response(_resp(200, json_body=body))
    with patch(
        "src.revenium_mcp_server.auth.api_key_validator.get_shared_http_client",
        return_value=client,
    ):
        identity = await v.validate("rev_rk_abcdef123456")
    assert identity.team_id == "team_first"


@pytest.mark.asyncio
async def test_no_team_raises_descriptive_error_not_malformed():
    """No defaultTeamId and no teams: clear error, not the 'Malformed' catch-all."""
    body = {**USERS_ME, "defaultTeamId": None, "teams": []}
    v, client = _validator_with_response(_resp(200, json_body=body))
    with patch(
        "src.revenium_mcp_server.auth.api_key_validator.get_shared_http_client",
        return_value=client,
    ):
        with pytest.raises(ApiKeyValidationError, match="no team") as exc_info:
            await v.validate("rev_rk_abcdef123456")
    assert "Malformed" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_metering_key_short_circuits_without_http():
    v, client = _validator_with_response(_resp(200, json_body=USERS_ME))
    with patch(
        "src.revenium_mcp_server.auth.api_key_validator.get_shared_http_client",
        return_value=client,
    ):
        with pytest.raises(InsufficientScopeError, match="Metering-only"):
            await v.validate("rev_mk_meteringkey123")
    client.get.assert_not_called()


@pytest.mark.asyncio
async def test_401_raises_invalid_token():
    v, client = _validator_with_response(_resp(401, text="Unauthorized"))
    with patch(
        "src.revenium_mcp_server.auth.api_key_validator.get_shared_http_client",
        return_value=client,
    ):
        with pytest.raises(InvalidTokenError):
            await v.validate("rev_rk_revokedkey1234")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,exc",
    [
        ("API key is suspended", KeySuspendedError),
        ("API key has expired", KeyExpiredError),
        ("Insufficient API key scope", InsufficientScopeError),
        ("Some other forbidden reason", ApiKeyValidationError),
    ],
)
async def test_403_maps_by_substring(text, exc):
    v, client = _validator_with_response(_resp(403, text=text))
    with patch(
        "src.revenium_mcp_server.auth.api_key_validator.get_shared_http_client",
        return_value=client,
    ):
        with pytest.raises(exc):
            await v.validate("rev_sk_somewritekey123")


@pytest.mark.asyncio
async def test_5xx_falls_through_to_base_error():
    v, client = _validator_with_response(_resp(503, text="upstream down"))
    with patch(
        "src.revenium_mcp_server.auth.api_key_validator.get_shared_http_client",
        return_value=client,
    ):
        with pytest.raises(ApiKeyValidationError):
            await v.validate("rev_rk_abcdef123456")


@pytest.mark.asyncio
async def test_cache_hit_avoids_second_http_call():
    v, client = _validator_with_response(_resp(200, json_body=USERS_ME))
    with patch(
        "src.revenium_mcp_server.auth.api_key_validator.get_shared_http_client",
        return_value=client,
    ):
        await v.validate("rev_rk_abcdef123456")
        await v.validate("rev_rk_abcdef123456")
    assert client.get.await_count == 1


@pytest.mark.asyncio
async def test_invalidate_evicts_cached_entry():
    v, client = _validator_with_response(_resp(200, json_body=USERS_ME))
    with patch(
        "src.revenium_mcp_server.auth.api_key_validator.get_shared_http_client",
        return_value=client,
    ):
        await v.validate("rev_rk_abcdef123456")
        v.invalidate("rev_rk_abcdef123456")
        await v.validate("rev_rk_abcdef123456")
    assert client.get.await_count == 2


@pytest.mark.asyncio
async def test_concurrent_same_key_single_flight():
    """A burst of concurrent validations for one key triggers exactly one HTTP call."""
    v, client = _validator_with_response(_resp(200, json_body=USERS_ME))
    with patch(
        "src.revenium_mcp_server.auth.api_key_validator.get_shared_http_client",
        return_value=client,
    ):
        await asyncio.gather(
            *[v.validate("rev_rk_abcdef123456") for _ in range(8)]
        )
    assert client.get.await_count == 1


@pytest.mark.asyncio
async def test_bearer_prefix_is_stripped():
    """A 'Bearer ' prefix is stripped; validate and invalidate hit the same slot."""
    v, client = _validator_with_response(_resp(200, json_body=USERS_ME))
    with patch(
        "src.revenium_mcp_server.auth.api_key_validator.get_shared_http_client",
        return_value=client,
    ):
        identity = await v.validate("Bearer rev_rk_abcdef123456")
        assert identity.user_id == "usr_123"
        # invalidate with the bearer form must evict the bare-token slot
        v.invalidate("Bearer rev_rk_abcdef123456")
        await v.validate("rev_rk_abcdef123456")
    assert client.get.await_count == 2


@pytest.mark.asyncio
async def test_malformed_200_raises_typed_error():
    """A 200 body missing required fields raises ApiKeyValidationError, not KeyError."""
    v, client = _validator_with_response(_resp(200, json_body={"unexpected": "shape"}))
    with patch(
        "src.revenium_mcp_server.auth.api_key_validator.get_shared_http_client",
        return_value=client,
    ):
        with pytest.raises(ApiKeyValidationError):
            await v.validate("rev_rk_abcdef123456")


@pytest.mark.asyncio
async def test_unknown_prefix_falls_through_to_upstream():
    """Non-rev-prefixed tokens are NOT short-circuited; the upstream decides.

    Intentional per design: scope is UNKNOWN and validity is delegated to
    /users/me (a valid third-party-shaped key still resolves)."""
    v, client = _validator_with_response(_resp(200, json_body=USERS_ME))
    with patch(
        "src.revenium_mcp_server.auth.api_key_validator.get_shared_http_client",
        return_value=client,
    ):
        identity = await v.validate("tok_not_rev_prefixed_123")
    assert identity.scope_from_prefix == "UNKNOWN"
    assert client.get.await_count == 1
