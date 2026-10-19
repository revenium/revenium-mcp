"""The organization a request acts for, as a key for per-process in-memory state."""
from __future__ import annotations

from typing import NamedTuple, Optional

from .auth_mode import read_auth_mode
from .claims_middleware import current_tenant_context
from .tenant_context import TenantContext


class TenantScope(NamedTuple):
    """Identifies whose data an in-memory entry is: one Revenium team within a tenant on one deployment.

    ``base_url`` is part of the key because the same team id on two Revenium
    deployments names two unrelated organizations.
    """

    team_id: str
    tenant_id: str
    base_url: str


LOCAL_TENANT_SCOPE = TenantScope(team_id="", tenant_id="", base_url="")


def tenant_scope(ctx: Optional[TenantContext] = None) -> TenantScope:
    """Return the scope of the organization this request acts for.

    Uses ``ctx`` when given, otherwise the context the per-request auth
    middleware bound. With neither, env mode is one customer per process and
    gets ``LOCAL_TENANT_SCOPE``; clerk and api_key modes fail closed rather
    than file every caller under one shared scope.

    Raises:
        PermissionError: In clerk/api_key mode when no tenant context exists.
    """
    resolved = ctx if ctx is not None else current_tenant_context()
    if resolved is not None:
        return TenantScope(
            team_id=resolved.team_id,
            tenant_id=resolved.tenant_id or "",
            base_url=resolved.base_url,
        )
    if read_auth_mode() in ("clerk", "api_key"):
        raise PermissionError(
            "Tenant context unavailable — TenantContextMiddleware (clerk) "
            "or ApiKeyAuthMiddleware (api_key) did not run"
        )
    return LOCAL_TENANT_SCOPE
