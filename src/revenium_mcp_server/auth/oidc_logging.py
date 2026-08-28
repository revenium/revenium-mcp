"""OIDCProxy subclass that emits structured auth events on token verification.

Also carries our RFC 9207 authorization-response ``iss`` check, which FastMCP
does not implement (see ``response_iss``).
"""
from __future__ import annotations

from typing import Any

from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.oauth_proxy.ui import create_error_html
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from loguru import logger
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from .auth_events import emit_auth_event
from .response_iss import (
    collapse_iss_values,
    ISS_UNVERIFIABLE,
    evaluate_response_iss,
    require_response_iss,
)
from .tenant_resolver import _get_claim


class AuthLoggingOIDCProxy(OIDCProxy):
    """Emits one structured auth event per verify_token call.

    Also enforces the RFC 9207 issuer check on the upstream IdP callback, which
    FastMCP does not implement. The audience is captured at construction so
    failure events can carry it even when no validated token exists.
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

    async def _handle_idp_callback(
        self, request: Request
    ) -> HTMLResponse | RedirectResponse:
        """Enforce RFC 9207 ``iss`` before the authorization code is redeemed.

        NOTE: This overrides a FastMCP-internal route handler
        (``OAuthProxy._handle_idp_callback``, bound as the endpoint for the
        proxy's redirect path in ``get_routes``) and relies on FastMCP not
        reading the ``iss`` authorization-response parameter itself. Verified
        against fastmcp >=3.2.0,<4.0.0; revisit on FastMCP upgrades — if the
        handler is renamed, or if FastMCP grows its own RFC 9207 support, this
        wrapper becomes dead code or a double check.

        The guard runs before delegating so a mixed-up authorization response is
        rejected without the code ever reaching the upstream token endpoint. It
        applies to error responses as well, which RFC 9207 also stamps.
        """
        # getlist, not get: QueryParams.get silently returns the LAST
        # occurrence of a repeated key, so a polluted ?iss=a&iss=b callback
        # would be judged only on the attacker-chosen trailing value.
        received, dup_reason = collapse_iss_values(
            request.query_params.getlist("iss")
        )
        accepted: bool
        reason: str | None
        if dup_reason is not None:
            accepted, reason = False, dup_reason
        else:
            accepted, reason = evaluate_response_iss(
                received=received,
                expected=str(getattr(self.oidc_config, "issuer", None) or ""),
                require_present=require_response_iss(),
            )
        if not accepted:
            emit_auth_event(
                outcome="failure",
                auth_mode="clerk",
                aud=self._expected_audience,
                reason=reason,
            )
            logger.warning(
                "rejecting IdP callback: RFC 9207 issuer check failed ({}); "
                "the authorization code was not redeemed",
                reason,
            )
            return HTMLResponse(
                content=create_error_html(
                    error_title="Authorization Error",
                    error_message=(
                        "The identity provider's response could not be matched "
                        "to the expected authorization server. Please try "
                        "authenticating again."
                    ),
                ),
                status_code=400,
            )
        if reason == ISS_UNVERIFIABLE:
            # The callback carried an issuer but no expected issuer was
            # available to compare it against. In clerk mode that should be
            # impossible, so it most likely means a FastMCP upgrade moved
            # ``oidc_config.issuer`` — warn rather than fail the login, because
            # losing this defence-in-depth check is less harmful than breaking
            # every login on a patch bump, but it must not pass silently.
            logger.warning(
                "RFC 9207 issuer check could not run: no expected issuer is "
                "available from the OIDC configuration"
            )
        elif reason:
            logger.debug("RFC 9207 issuer check tolerated the response ({})", reason)
        return await super()._handle_idp_callback(request)

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
