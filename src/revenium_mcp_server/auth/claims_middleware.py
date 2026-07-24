"""Middleware that bridges FastMCP's verified JWT claims to a TenantContext."""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional

from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from loguru import logger

from .auth_events import emit_auth_event
from .tenant_context import TenantContext
from .tenant_resolver import TenantResolver

_current_tenant: ContextVar[Optional[TenantContext]] = ContextVar(
    "revenium_tenant_context", default=None
)


def current_tenant_context() -> Optional[TenantContext]:
    """Public accessor for the current request's TenantContext (None if not set)."""
    return _current_tenant.get()


class TenantContextMiddleware(Middleware):
    """Populates a ContextVar with a TenantContext derived from verified JWT claims.

    Runs on every tool call (post-auth, pre-handler). Reads the verified
    AccessToken injected by FastMCP's OIDCProxy, runs the configured resolver,
    and stores the result in _current_tenant so ToolBase.execute() can read it.
    """

    def __init__(self, resolver: TenantResolver) -> None:
        self._resolver = resolver

    async def on_call_tool(
        self, context: MiddlewareContext, call_next: CallNext
    ) -> Any:
        token = get_access_token()
        claims = token.claims if token is not None else {}
        # OAuthProxy's token swap stores the upstream Clerk access token and
        # returns it as AccessToken.token — that is the credential forwarded
        # downstream, re-read per request so upstream refreshes flow through.
        clerk_jwt = token.token if token is not None else None
        try:
            tenant_ctx = self._resolver.resolve(claims, clerk_jwt=clerk_jwt)
        except PermissionError as e:
            logger.warning("Tenant resolution rejected: {}", e)
            emit_auth_event(
                outcome="failure",
                auth_mode="clerk",
                user_id=(claims or {}).get("sub"),
                reason="tenant_resolution_rejected",
            )
            raise  # FastMCP wraps it as a JSON-RPC error inside HTTP 200

        reset_token = _current_tenant.set(tenant_ctx)
        try:
            return await call_next(context)
        finally:
            _current_tenant.reset(reset_token)
