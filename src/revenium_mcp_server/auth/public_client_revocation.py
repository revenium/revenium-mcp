"""RFC 7009 token revocation that public OAuth clients can use.

The mcp SDK's ``RevocationRequest`` declares ``client_secret`` without a
default, so ``/revoke`` answers 400 to a public client (Claude registers with
``token_endpoint_auth_method="none"``) even after ``ClientAuthenticator`` has
accepted it, and the SDK metadata advertises only secret-based revocation.
Upstream: modelcontextprotocol/python-sdk#3508 (fix in PR #3512). When the
installed mcp makes the field optional, ``test_public_client_revocation.py``
fails on purpose: drop ``PublicClientRevocationRequest`` then.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, Protocol

from mcp.server.auth.errors import stringify_pydantic_error
from mcp.server.auth.handlers.revoke import RevocationErrorResponse, RevocationRequest
from mcp.server.auth.json_response import PydanticJSONResponse
from mcp.server.auth.middleware.client_auth import (
    AuthenticationError,
    ClientAuthenticator,
)
from mcp.server.auth.routes import REVOCATION_PATH, cors_middleware
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

PUBLIC_CLIENT_AUTH_METHOD = "none"
AUTHORIZATION_SERVER_METADATA_PATH = "/.well-known/oauth-authorization-server"
REVOCATION_AUTH_METHODS_FIELD = "revocation_endpoint_auth_methods_supported"
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class PublicClientRevocationRequest(RevocationRequest):
    client_secret: str | None = None


class ClientTokenRevoker(Protocol):
    async def revoke_client_token(
        self, client: OAuthClientInformationFull, token: str
    ) -> None: ...


@dataclass
class PublicClientRevocationHandler:
    revoker: ClientTokenRevoker
    client_authenticator: ClientAuthenticator

    async def handle(self, request: Request) -> Response:
        try:
            client = await self.client_authenticator.authenticate_request(request)
        except AuthenticationError as exc:
            return _revocation_error(401, "unauthorized_client", exc.message)
        try:
            revocation = PublicClientRevocationRequest.model_validate(
                dict(await request.form())
            )
        except ValidationError as exc:
            return _revocation_error(
                400, "invalid_request", stringify_pydantic_error(exc)
            )
        await self.revoker.revoke_client_token(client, revocation.token)
        return Response(status_code=200, headers=NO_STORE_HEADERS)


def _revocation_error(
    status_code: int,
    error: Literal["invalid_request", "unauthorized_client"],
    description: str,
) -> Response:
    return PydanticJSONResponse(
        status_code=status_code,
        content=RevocationErrorResponse(error=error, error_description=description),
    )


class PublicRevocationMetadataApp:
    """Adds ``none`` to the revocation auth methods of the wrapped metadata response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        start: Message = {}
        chunks: list[bytes] = []

        async def capture(message: Message) -> None:
            nonlocal start
            if message["type"] == "http.response.start":
                start = message
                return
            if message["type"] != "http.response.body":
                await send(message)
                return
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                await _send_rewritten(start, b"".join(chunks), send)

        await self.app(scope, receive, capture)


async def _send_rewritten(start: Message, body: bytes, send: Send) -> None:
    body = _with_public_revocation(body) if start.get("status") == 200 else body
    headers = [
        (name, value)
        for name, value in start.get("headers", [])
        if name.lower() != b"content-length"
    ]
    headers.append((b"content-length", str(len(body)).encode()))
    await send({**start, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def _with_public_revocation(body: bytes) -> bytes:
    try:
        metadata = json.loads(body)
    except ValueError:
        return body
    methods = (
        metadata.get(REVOCATION_AUTH_METHODS_FIELD)
        if isinstance(metadata, dict)
        else None
    )
    if not isinstance(methods, list) or PUBLIC_CLIENT_AUTH_METHOD in methods:
        return body
    metadata[REVOCATION_AUTH_METHODS_FIELD] = [PUBLIC_CLIENT_AUTH_METHOD, *methods]
    return json.dumps(metadata).encode()


def with_public_client_revocation(
    routes: list[Route],
    revoker: ClientTokenRevoker,
    client_authenticator: ClientAuthenticator,
) -> list[Route]:
    """Swap the SDK ``/revoke`` route and advertise ``none`` wherever it is mounted."""
    if not any(_is_route(route, REVOCATION_PATH) for route in routes):
        return routes
    handler = PublicClientRevocationHandler(revoker, client_authenticator)
    return [_replace(route, handler) for route in routes]


def _replace(route: Route, handler: PublicClientRevocationHandler) -> Route:
    if _is_route(route, REVOCATION_PATH):
        return Route(
            REVOCATION_PATH,
            endpoint=cors_middleware(handler.handle, ["POST", "OPTIONS"]),
            methods=["POST", "OPTIONS"],
        )
    if isinstance(route, Route) and route.path.startswith(
        AUTHORIZATION_SERVER_METADATA_PATH
    ):
        return Route(
            route.path,
            endpoint=PublicRevocationMetadataApp(route.app),
            methods=list(route.methods or ["GET", "OPTIONS"]),
            name=route.name,
            include_in_schema=route.include_in_schema,
        )
    return route


def _is_route(route: Route, path: str) -> bool:
    return isinstance(route, Route) and route.path == path
