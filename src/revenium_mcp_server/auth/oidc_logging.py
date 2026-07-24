"""OIDCProxy subclass that emits structured auth events on token verification."""
from __future__ import annotations

from typing import Any

from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from loguru import logger

from .auth_events import emit_auth_event
from .tenant_resolver import _get_claim


class AuthLoggingOIDCProxy(OIDCProxy):
    """Emits one structured auth event per verify_token call.

    The audience is captured at construction so failure events can carry it
    even when no validated token exists.
    """

    def __init__(self, *, audience: str | None = None, **kwargs: Any) -> None:
        super().__init__(audience=audience, **kwargs)
        self._expected_audience = audience

    def _uses_alternate_verification(self) -> bool:
        """Forward the verified ID token downstream, not the access token.

        NOTE: This overrides a FastMCP-internal method
        (``OAuthProxy._uses_alternate_verification``) and relies on FastMCP
        calling it to decide whether to swap the validated AccessToken back to
        the upstream access token. Verified against fastmcp >=3.2.0,<4.0.0;
        revisit on FastMCP upgrades — if this method is renamed/removed/inverted,
        ID-token forwarding breaks silently.

        With ``verify_id_token=True`` the upstream ID token is what we verify
        and what carries the identity claims (email + nested private_metadata)
        HyperCurrent needs. FastMCP's default would patch the validated
        AccessToken back to the upstream *access* token (minimal, no email),
        which would then be forwarded downstream and rejected. Returning False
        keeps ``AccessToken.token`` as the verified ID token.
        """
        return False

    async def verify_token(self, token: str) -> AccessToken | None:
        result = await super().verify_token(token)
        if result is None:
            emit_auth_event(
                outcome="failure",
                auth_mode="clerk",
                aud=self._expected_audience,
                reason="token_verification_failed",
            )
            return result

        # Restore the granted scopes. Because we forward the ID token
        # (_uses_alternate_verification → False), FastMCP's load_access_token
        # skips its scope patch, leaving result.scopes empty (an OIDC ID token
        # carries no `scope` claim). RequireAuthMiddleware would then 403 on the
        # server's required_scopes. The proxy-minted FastMCP JWT we just
        # verified holds the authoritative granted scopes, so read them back.
        if not result.scopes:
            try:
                granted = self.jwt_issuer.verify_token(token).get("scope", "")
                if granted:
                    result = result.model_copy(update={"scopes": granted.split()})
            except Exception as exc:  # scope restoration must never break auth
                logger.warning(
                    "clerk scope restoration failed ({}); inbound token will "
                    "carry no scopes and may be rejected by required-scope "
                    "enforcement",
                    type(exc).__name__,
                )

        claims = result.claims
        emit_auth_event(
            outcome="success",
            auth_mode="clerk",
            client_id=result.client_id,
            user_id=claims.get("sub"),
            tenant_id=_get_claim(claims, "tenant_id"),
            aud=self._expected_audience,
        )
        return result
