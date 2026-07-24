"""FastMCP integration for AUTH_MODE=api_key.

Two concerns live here:
  * ApiKeyTokenVerifier — the HTTP-layer auth gate (passed as auth=). FastMCP's
    RequireAuthMiddleware calls verify_token per request and emits 401 +
    WWW-Authenticate when it returns None.
  * ApiKeyAuthMiddleware — a post-auth on_call_tool middleware that reads the
    verified AccessToken, applies the optional X-Revenium-Team-Id override,
    and populates the existing _current_tenant ContextVar.
"""
from __future__ import annotations

from typing import Any

from fastmcp.server.auth.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token, get_http_headers
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from loguru import logger

from ..config_store import get_config_value
from ..constants import DEFAULT_BASE_URL
from .api_key_validator import (
    ApiKeyValidationError,
    ApiKeyValidator,
    _fingerprint,
    _strip_bearer,
)
from .auth_events import emit_auth_event
from .claims_middleware import _current_tenant
from .tenant_context import TenantContext


class ApiKeyTokenVerifier(TokenVerifier):
    """Validates a Revenium bearer token per request via ApiKeyValidator.

    Returns an AccessToken (carrying tenant claims) on success, or None on any
    validation failure. Phase 1: every failure collapses to HTTP 401 — the
    typed distinction is preserved in logs only.
    """

    def __init__(self, *, validator: ApiKeyValidator, base_url: str) -> None:
        super().__init__(base_url=base_url)
        self._validator = validator

    async def verify_token(self, token: str) -> AccessToken | None:
        fingerprint = _fingerprint(_strip_bearer(token))
        try:
            identity = await self._validator.validate(token)
        except ApiKeyValidationError as exc:
            logger.info(
                "api_key auth rejected: {} (key_fingerprint={})",
                type(exc).__name__,
                fingerprint,
            )
            emit_auth_event(
                outcome="failure",
                auth_mode="api_key",
                key_fingerprint=fingerprint,
                reason=type(exc).__name__,
            )
            return None

        emit_auth_event(
            outcome="success",
            auth_mode="api_key",
            key_fingerprint=fingerprint,
            user_id=identity.user_id,
            tenant_id=identity.tenant_id,
        )
        return AccessToken(
            token=_strip_bearer(token),
            client_id=identity.user_id,
            scopes=[identity.scope_from_prefix],
            claims={
                "tenant_id": identity.tenant_id,
                "team_id": identity.team_id,
                "team_ids": list(identity.team_ids),
                "user_id": identity.user_id,
                "scope_from_prefix": identity.scope_from_prefix,
            },
        )


class ApiKeyAuthMiddleware(Middleware):
    """Builds a TenantContext from the verified AccessToken (api_key mode)."""

    def __init__(self, validator: ApiKeyValidator) -> None:
        self._validator = validator

    async def on_call_tool(
        self, context: MiddlewareContext, call_next: CallNext
    ) -> Any:
        access = get_access_token()
        if access is None:
            raise RuntimeError(
                "ApiKeyAuthMiddleware reached without a verified access token; "
                "check middleware ordering (RequireAuthMiddleware must run first)"
            )
        claims = access.claims
        token = access.token

        # Per-request team selection: an explicit X-Revenium-Team-Id header
        # picks one of the caller's teams; absent/empty keeps the default
        # resolved at validation time. Unknown teams fail closed.
        headers = get_http_headers()
        requested = (headers.get("x-revenium-team-id") or "").strip()
        if not requested:
            team_id = claims["team_id"]
        elif requested in (claims.get("team_ids") or []):
            team_id = requested
        else:
            logger.warning(
                "Team override rejected for user_id={}: requested team not "
                "available to this API key",
                claims.get("user_id"),
            )
            # No raw token in scope here — post-auth claims only, so no fingerprint field.
            emit_auth_event(
                outcome="failure",
                auth_mode="api_key",
                user_id=claims.get("user_id"),
                tenant_id=claims.get("tenant_id"),
                reason="team_override_rejected",
            )
            raise PermissionError(
                f"Team '{requested}' is not available to this API key"
            )

        # api_key mode has no server-wide REVENIUM_API_KEY, so ConfigManager
        # (which requires one) cannot be used here. Resolve the downstream base
        # URL directly — honoring REVENIUM_BASE_URL when set, else the default.
        base_url = get_config_value("REVENIUM_BASE_URL") or DEFAULT_BASE_URL
        tenant_ctx = TenantContext(
            team_id=team_id,
            tenant_id=claims["tenant_id"],
            user_id=claims["user_id"],
            api_key=token,
            base_url=base_url,
        )

        reset_token = _current_tenant.set(tenant_ctx)
        try:
            return await call_next(context)
        except Exception as exc:
            # Best-effort: shrink the revocation window on an active 401/403.
            # The 30s TTL is the primary expiry mechanism.
            if getattr(exc, "status_code", None) in (401, 403):
                self._validator.invalidate(token)
            raise
        finally:
            _current_tenant.reset(reset_token)
