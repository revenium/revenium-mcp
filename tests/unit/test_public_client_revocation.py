"""Public OAuth clients can revoke their tokens at /revoke (BACK-5051)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastmcp.server.auth.oauth_proxy.models import (
    JTIMapping,
    RefreshTokenMetadata,
    UpstreamTokenSet,
    _hash_token,
)
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration
from key_value.aio.stores.memory import MemoryStore
from mcp.server.auth.handlers.revoke import RevocationRequest
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.routing import Route

from src.revenium_mcp_server.auth.oidc_logging import AuthLoggingOIDCProxy
from src.revenium_mcp_server.auth.public_client_revocation import (
    with_public_client_revocation,
)

ISSUER = "https://clerk.example.invalid"
SERVER = "https://mcp.example.invalid"
PUBLIC_CLIENT = "claude-public-client"
OTHER_CLIENT = "another-public-client"
UPSTREAM_TOKEN_ID = "upstream-token-set-1"
UPSTREAM_ID_TOKEN = "upstream-id-token"

DISCOVERY = OIDCConfiguration.model_validate(
    {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/oauth/authorize",
        "token_endpoint": f"{ISSUER}/oauth/token",
        "revocation_endpoint": f"{ISSUER}/oauth/token/revoke",
        "jwks_uri": f"{ISSUER}/.well-known/jwks.json",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
    }
)


def test_upstream_revocation_request_still_requires_a_client_secret():
    field = RevocationRequest.model_fields.get("client_secret")
    assert field is not None, (
        "mcp dropped RevocationRequest.client_secret; revisit public_client_revocation.py"
    )
    assert field.is_required(), (
        "mcp now accepts a revocation without client_secret (python-sdk#3508 landed): "
        "remove PublicClientRevocationRequest but keep the /revoke route swap, "
        "which is also what revokes access tokens (AuthLoggingOIDCProxy.revoke_client_token)"
    )


@pytest.fixture
async def proxy() -> AuthLoggingOIDCProxy:
    with patch.object(
        AuthLoggingOIDCProxy, "get_oidc_configuration", return_value=DISCOVERY
    ):
        proxy = AuthLoggingOIDCProxy(
            config_url=f"{ISSUER}/.well-known/openid-configuration",
            client_id="clerk-oauth-client",
            client_secret="clerk-oauth-client-secret",
            base_url=SERVER,
            required_scopes=["openid"],
            verify_id_token=True,
            algorithm="RS256",
            client_storage=MemoryStore(),
        )
    proxy.set_mcp_path("/mcp")
    for client_id in (PUBLIC_CLIENT, OTHER_CLIENT):
        await proxy.register_client(
            OAuthClientInformationFull(
                client_id=client_id,
                redirect_uris=[AnyUrl("https://claude.ai/api/mcp/auth_callback")],
                token_endpoint_auth_method="none",
            )
        )
    return proxy


def _client_for(proxy: AuthLoggingOIDCProxy) -> httpx.AsyncClient:
    app = Starlette(routes=proxy.get_routes("/mcp"))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=SERVER)


async def _issue_access_token(
    proxy: AuthLoggingOIDCProxy, client_id: str, jti: str
) -> str:
    """A proxy token that ``load_access_token`` accepts until it is revoked."""
    now = time.time()
    await proxy._upstream_token_store.put(
        key=UPSTREAM_TOKEN_ID,
        value=UpstreamTokenSet(
            upstream_token_id=UPSTREAM_TOKEN_ID,
            access_token=UPSTREAM_ID_TOKEN,
            refresh_token=None,
            refresh_token_expires_at=None,
            expires_at=now + 3600,
            token_type="Bearer",
            scope="openid",
            client_id=client_id,
            created_at=now,
            raw_token_data={"id_token": UPSTREAM_ID_TOKEN},
        ),
    )
    proxy._token_validator.verify_token = AsyncMock(
        return_value=AccessToken(
            token=UPSTREAM_ID_TOKEN, client_id="clerk-oauth-client", scopes=["openid"]
        )
    )
    await proxy._jti_mapping_store.put(
        key=jti,
        value=JTIMapping(jti=jti, upstream_token_id=UPSTREAM_TOKEN_ID, created_at=now),
    )
    return proxy.jwt_issuer.issue_access_token(
        client_id=client_id, scopes=["openid"], jti=jti, expires_in=600
    )


async def test_a_public_client_revokes_its_access_token_with_only_token_and_client_id(
    proxy,
):
    token = await _issue_access_token(proxy, PUBLIC_CLIENT, "access-jti-1")
    assert await proxy.load_access_token(token) is not None

    async with _client_for(proxy) as client:
        response = await client.post(
            "/revoke", data={"token": token, "client_id": PUBLIC_CLIENT}
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert await proxy._jti_mapping_store.get(key="access-jti-1") is None
    assert await proxy.load_access_token(token) is None


async def test_a_public_client_revokes_its_refresh_token(proxy):
    refresh = proxy.jwt_issuer.issue_refresh_token(
        client_id=PUBLIC_CLIENT, scopes=["openid"], jti="refresh-jti-1", expires_in=600
    )
    await proxy._refresh_token_store.put(
        key=_hash_token(refresh),
        value=RefreshTokenMetadata(
            client_id=PUBLIC_CLIENT, scopes=["openid"], created_at=time.time()
        ),
    )
    registered = await proxy.get_client(PUBLIC_CLIENT)

    async with _client_for(proxy) as client:
        response = await client.post(
            "/revoke", data={"token": refresh, "client_id": PUBLIC_CLIENT}
        )

    assert response.status_code == 200
    assert await proxy.load_refresh_token(registered, refresh) is None


async def test_a_client_cannot_revoke_another_clients_access_token(proxy):
    token = await _issue_access_token(proxy, OTHER_CLIENT, "access-jti-2")

    async with _client_for(proxy) as client:
        response = await client.post(
            "/revoke", data={"token": token, "client_id": PUBLIC_CLIENT}
        )

    assert response.status_code == 200
    assert await proxy.load_access_token(token) is not None


async def test_an_unknown_token_is_acknowledged_per_rfc_7009(proxy):
    async with _client_for(proxy) as client:
        response = await client.post(
            "/revoke", data={"token": "not-a-token", "client_id": PUBLIC_CLIENT}
        )

    assert response.status_code == 200


async def test_an_unregistered_client_is_refused(proxy):
    async with _client_for(proxy) as client:
        response = await client.post(
            "/revoke", data={"token": "anything", "client_id": "nobody"}
        )

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized_client"


async def test_a_request_without_a_token_is_invalid(proxy):
    async with _client_for(proxy) as client:
        response = await client.post("/revoke", data={"client_id": PUBLIC_CLIENT})

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


async def test_the_metadata_advertises_public_client_revocation(proxy):
    async with _client_for(proxy) as client:
        response = await client.get("/.well-known/oauth-authorization-server")

    assert response.status_code == 200
    metadata = response.json()
    assert metadata["revocation_endpoint"] == f"{SERVER}/revoke"
    assert "none" in metadata["revocation_endpoint_auth_methods_supported"]
    assert "none" in metadata["token_endpoint_auth_methods_supported"]


async def test_the_metadata_preflight_is_left_alone(proxy):
    async with _client_for(proxy) as client:
        response = await client.options(
            "/.well-known/oauth-authorization-server",
            headers={
                "Origin": "https://claude.ai",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200


def test_routes_without_revocation_are_returned_unchanged():
    routes = [
        Route("/.well-known/oauth-authorization-server", endpoint=lambda request: None)
    ]

    assert (
        with_public_client_revocation(routes, revoker=None, client_authenticator=None)
        is routes
    )  # type: ignore[arg-type]
