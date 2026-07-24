"""Resolver that maps JWT claims to a TenantContext."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from loguru import logger

from . import ConfigManager
from ..config_store import get_config_value
from ..constants import DEFAULT_BASE_URL
from .api_key_scope import APIKeyScope
from .tenant_context import TenantContext


class TenantResolver(ABC):
    """Abstract resolver that produces a TenantContext from JWT claims."""

    @abstractmethod
    def resolve(
        self, claims: dict, *, clerk_jwt: Optional[str] = None
    ) -> TenantContext:
        """Map verified JWT claims (and the verified token itself) to a TenantContext."""


class EnvTenantResolver(TenantResolver):
    """Backward-compat resolver: ignores claims, returns env-backed context."""

    def resolve(
        self, claims: dict, *, clerk_jwt: Optional[str] = None
    ) -> TenantContext:
        cfg = ConfigManager().get_config()
        return TenantContext(
            team_id=cfg.team_id,
            api_key=cfg.api_key,
            tenant_id=cfg.tenant_id,
            base_url=cfg.base_url,
        )


class ClerkTenantResolver(TenantResolver):
    """Maps Clerk JWT claims to a TenantContext carrying the caller's own JWT.

    Multi-tenant: the tenant comes from the JWT, not from deployment env.
    Downstream calls authenticate with the forwarded JWT — no shared API key.
    """

    REQUIRED_CLAIMS = ("revenium_team_id", "tenant_id", "sub")

    def resolve(
        self, claims: dict, *, clerk_jwt: Optional[str] = None
    ) -> TenantContext:
        resolved = {c: _get_claim(claims, c) for c in self.REQUIRED_CLAIMS}
        missing = [
            c for c in self.REQUIRED_CLAIMS
            if not (isinstance(resolved[c], str) and resolved[c].strip())
        ]
        if missing:
            raise PermissionError(
                f"JWT is missing required claim(s): {', '.join(missing)}"
            )
        if not clerk_jwt or not clerk_jwt.strip():
            raise PermissionError(
                "No verified access token available to forward downstream"
            )

        # ConfigManager requires REVENIUM_API_KEY, which clerk mode no longer
        # has — resolve the downstream base URL directly (same pattern as
        # ApiKeyAuthMiddleware).
        base_url = get_config_value("REVENIUM_BASE_URL") or DEFAULT_BASE_URL
        return TenantContext(
            team_id=resolved["revenium_team_id"],
            tenant_id=resolved["tenant_id"],
            user_id=resolved["sub"],
            clerk_jwt=clerk_jwt,
            base_url=base_url,
            scopes=_parse_scopes(claims.get("scope")),
            api_key_scopes=_parse_api_key_scopes(
                _get_claim(claims, "revenium_api_scopes")
            ),
        )


def _get_claim(claims: dict, name: str) -> Any:
    """Read a claim top-level, falling back to nested ``private_metadata``.

    Clerk OAuth ID tokens carry custom user claims nested under a
    ``private_metadata`` object; session-token-shaped JWTs carry them
    top-level. Prefer the top-level value when present.
    """
    top = claims.get(name)
    if top not in (None, ""):
        return top
    pm = claims.get("private_metadata")
    if isinstance(pm, dict):
        return pm.get(name)
    return None


def _parse_scopes(scope_claim) -> Optional[list[str]]:
    if not scope_claim:
        return None
    if isinstance(scope_claim, str):
        parsed = scope_claim.split()
    elif isinstance(scope_claim, (list, tuple)):
        parsed = [s for s in scope_claim if isinstance(s, str) and s]
    else:
        logger.warning(
            "Unexpected type for 'scope' JWT claim: {}", type(scope_claim).__name__
        )
        return None
    return parsed or None


def _parse_api_key_scopes(claim) -> Optional[list[APIKeyScope]]:
    """Parse the 'revenium_api_scopes' JWT claim into validated enum members.

    Accepts space-separated string or list of strings. Normalizes each token
    to uppercase, drops any value not in APIKeyScope (with a warning), and
    dedupes. Returns None when the resulting list is empty.
    """
    if not claim:
        return None
    if isinstance(claim, str):
        tokens = claim.split()
    elif isinstance(claim, (list, tuple)):
        tokens = [s for s in claim if isinstance(s, str) and s]
    else:
        logger.warning(
            "Unexpected type for 'revenium_api_scopes' JWT claim: {}",
            type(claim).__name__,
        )
        return None
    normalized = [t.strip().upper() for t in tokens if t and t.strip()]

    known = {s.value for s in APIKeyScope}
    valid: list[APIKeyScope] = []
    seen: set[APIKeyScope] = set()
    for token in normalized:
        if token not in known:
            logger.warning("Dropping unknown api-key scope from JWT: {!r}", token)
            continue
        member = APIKeyScope(token)
        if member not in seen:
            valid.append(member)
            seen.add(member)
    return valid or None


def get_resolver() -> TenantResolver:
    """Return the resolver matching the active AUTH_MODE."""
    from .auth_mode import read_auth_mode
    if read_auth_mode() == "clerk":
        return ClerkTenantResolver()
    # api_key mode never reaches here: ApiKeyAuthMiddleware builds the
    # TenantContext directly from the verified AccessToken, so no resolver
    # is consulted. env mode falls through to the env-backed resolver.
    return EnvTenantResolver()
