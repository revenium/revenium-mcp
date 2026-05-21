from typing import Optional

from ..auth.tenant_context import TenantContext

_NO_CONTEXT_NAMESPACE = "_no_ctx_"
_SEP = ":"


class CacheKeyFactory:

    @staticmethod
    def make_key(ctx: Optional[TenantContext], key: str) -> str:
        if not key or not key.strip():
            raise ValueError("cache key must not be empty")

        normalized = key.strip()

        if ctx is None:
            return f"{_NO_CONTEXT_NAMESPACE}{_SEP}{_SEP}{normalized}"

        if _SEP in ctx.team_id:
            raise ValueError(f"team_id must not contain '{_SEP}'")
        if ctx.team_id == _NO_CONTEXT_NAMESPACE:
            raise ValueError(f"team_id must not equal the reserved namespace '{_NO_CONTEXT_NAMESPACE}'")
        if ctx.tenant_id and _SEP in ctx.tenant_id:
            raise ValueError(f"tenant_id must not contain '{_SEP}'")

        tenant_part = ctx.tenant_id or ""
        return f"{ctx.team_id}{_SEP}{tenant_part}{_SEP}{normalized}"
