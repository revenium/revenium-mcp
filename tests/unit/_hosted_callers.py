"""Drive work through the hosted (api_key mode) request path as a given caller.

The caller's key is verified by ApiKeyTokenVerifier against a fake validator,
and ApiKeyAuthMiddleware builds the request's TenantContext from the verified
token, exactly as on the hosted server. The platform is replaced by AsyncMocks
on a ReveniumClient scoped to that context.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Iterator, Optional, TypeVar
from unittest.mock import AsyncMock, MagicMock, patch

from fastmcp.server.auth.auth import AccessToken

from src.revenium_mcp_server.auth.api_key_middleware import (
    ApiKeyAuthMiddleware,
    ApiKeyTokenVerifier,
)
from src.revenium_mcp_server.auth.api_key_validator import ApiKeyIdentity
from src.revenium_mcp_server.auth.claims_middleware import current_tenant_context
from src.revenium_mcp_server.auth.config_factory import AuthConfigFactory
from src.revenium_mcp_server.client import ReveniumClient

T = TypeVar("T")

_MIDDLEWARE = "src.revenium_mcp_server.auth.api_key_middleware"
_task_access_token: ContextVar[Optional[AccessToken]] = ContextVar(
    "test_task_access_token", default=None
)


def identity(user_id: str, team_id: str, tenant_id: str, email: str) -> ApiKeyIdentity:
    return ApiKeyIdentity(
        user_id=user_id,
        tenant_id=tenant_id,
        team_id=team_id,
        team_ids=(team_id,),
        email=email,
        roles=["ROLE_TENANT_ADMIN"],
        scope_from_prefix="WRITE",
    )


@contextmanager
def hosted_request_path() -> Iterator[None]:
    """Route get_access_token to the verified token of the running task."""
    with patch(f"{_MIDDLEWARE}.get_access_token", side_effect=_task_access_token.get), patch(
        f"{_MIDDLEWARE}.get_http_headers", return_value={}
    ):
        yield


async def as_api_key_caller(
    caller: ApiKeyIdentity, work: Callable[[], Awaitable[T]]
) -> T:
    """Run work inside the hosted request path, signed in with caller's own key."""
    validator = MagicMock()
    validator.validate = AsyncMock(return_value=caller)
    validator.invalidate = MagicMock()
    verifier = ApiKeyTokenVerifier(validator=validator, base_url="https://mcp.test")
    access = await verifier.verify_token(f"rev_sk_{caller.user_id}_0123456789")
    assert access is not None
    _task_access_token.set(access)

    async def call_next(_context: Any) -> T:
        return await work()

    return await ApiKeyAuthMiddleware(validator).on_call_tool(MagicMock(), call_next)


def stubbed_platform_client() -> ReveniumClient:
    """A client scoped to the current request, with every write the tests drive stubbed."""
    ctx = current_tenant_context()
    assert ctx is not None, "must run inside as_api_key_caller"
    client = ReveniumClient(auth_config=AuthConfigFactory.from_tenant_context(ctx))
    client.post = AsyncMock(return_value={"id": "created"})  # type: ignore[method-assign]
    client.create_source = AsyncMock(return_value={"id": "src_new"})  # type: ignore[method-assign]
    client.create_subscription = AsyncMock(return_value={"id": "sub_new"})  # type: ignore[method-assign]
    client.update_product = AsyncMock(return_value={"id": "prod_1"})  # type: ignore[method-assign]
    return client


def posted_body(client: ReveniumClient) -> dict:
    return client.post.call_args.kwargs["data"]  # type: ignore[attr-defined]
