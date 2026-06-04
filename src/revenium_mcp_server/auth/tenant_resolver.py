"""Resolver that maps JWT claims to a TenantContext."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from loguru import logger

from . import ConfigManager
from .api_key_scope import APIKeyScope
from .tenant_context import TenantContext


class TenantResolver(ABC):
    """Abstract resolver that produces a TenantContext from JWT claims."""

    @abstractmethod
    def resolve(self, claims: dict) -> TenantContext:
        """Map verified JWT claims to a TenantContext."""


class EnvTenantResolver(TenantResolver):
    """Backward-compat resolver: ignores claims, returns env-backed context."""

    def resolve(self, claims: dict) -> TenantContext:
        cfg = ConfigManager().get_config()
        return TenantContext(
            team_id=cfg.team_id,
            api_key=cfg.api_key,
            tenant_id=cfg.tenant_id,
            base_url=cfg.base_url,
        )


class ClerkTenantResolver(TenantResolver):
    """Maps Clerk JWT claims + shared REVENIUM_API_KEY → TenantContext."""

    REQUIRED_CLAIMS = ("revenium_team_id", "tenant_id", "sub")

    def __init__(self) -> None:
        self._cfg = ConfigManager().get_config()
        self._expected_tenant_id = self._cfg.tenant_id
        if not self._expected_tenant_id:
            raise RuntimeError(
                "REVENIUM_TENANT_ID must be set when AUTH_MODE=clerk "
                "(used to validate JWT tenant_id matches the deployed tenant)."
            )

    def resolve(self, claims: dict) -> TenantContext:
        missing = [
            c for c in self.REQUIRED_CLAIMS
            if not (isinstance(claims.get(c), str) and claims.get(c).strip())
        ]
        if missing:
            raise PermissionError(
                f"JWT is missing required claim(s): {', '.join(missing)}"
            )

        jwt_tenant = claims["tenant_id"]
        if jwt_tenant != self._expected_tenant_id:
            raise PermissionError(
                "JWT tenant_id does not match this deployment"
            )

        return TenantContext(
            team_id=claims["revenium_team_id"],
            tenant_id=jwt_tenant,
            user_id=claims["sub"],
            api_key=self._cfg.api_key,
            base_url=self._cfg.base_url,
            scopes=_parse_scopes(claims.get("scope")),
            api_key_scopes=_parse_api_key_scopes(claims.get("revenium_api_scopes")),
        )


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
