"""Factory for building AuthConfig from various sources."""

from . import AuthConfig, ConfigManager
from .tenant_context import TenantContext


class AuthConfigFactory:
    """Constructs AuthConfig from a TenantContext or environment variables.

    Two paths:
      - from_tenant_context(ctx): multi-tenant per-request path
      - from_env(): backward-compatible env path (uses ConfigManager cache)

    Phase 1 limitation — fields dropped during TenantContext -> AuthConfig:
        ``user_id`` and ``scopes`` carried on TenantContext are intentionally
        not forwarded to AuthConfig, because AuthConfig does not model them.
        AuthConfig represents what the upstream Revenium API needs to make a
        request (api_key, team/tenant ids, base_url, transport tunables); it
        does not currently carry caller identity for audit trails or OAuth
        scope sets for access control.

        Audit-trail uses of ``user_id`` and scope-based access enforcement
        are deferred to Phase 2, when AuthConfig will be extended to model
        these fields and the factory will forward them. Until then, callers
        that need the authenticated user or granted scopes must read them
        directly from the TenantContext.
    """

    @staticmethod
    def from_tenant_context(ctx: TenantContext) -> AuthConfig:
        """Build AuthConfig from a TenantContext.

        Maps ctx fields to AuthConfig. Fields not present in TenantContext
        (timeout, environment, max_retries) take AuthConfig defaults.
        """
        # Phase 1 limitation: user_id and ctx.scopes are not propagated to
        # AuthConfig (Phase 2 will extend AuthConfig to model audit + scope
        # enforcement).
        return AuthConfig(
            api_key=ctx.api_key,
            team_id=ctx.team_id,
            tenant_id=ctx.tenant_id,
            base_url=ctx.base_url,
        )

    @staticmethod
    def from_env() -> AuthConfig:
        """Load AuthConfig from environment (backward-compatible path).

        Delegates to the ConfigManager singleton (uses cache), preserving
        the current behavior of ReveniumClient() with no arguments.
        """
        return ConfigManager().get_config()
