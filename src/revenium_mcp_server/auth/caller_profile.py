"""The signed-in caller's own platform user, for sign-in modes whose token does not name it.

A Clerk token identifies the caller by Clerk's `sub`, which is not the platform
user id the platform requires as the owner of new records, so clerk mode asks
the platform's /users/me with the caller's own token.
"""
from __future__ import annotations

import asyncio
from typing import Dict, NamedTuple, Optional, Tuple

import httpx
from cachetools import TTLCache
from loguru import logger

from ..auto_discovery import email_from_user_profile
from ..client import get_shared_http_client
from .config_factory import AuthConfigFactory
from .tenant_context import TenantContext

USERS_ME_PATH = "/profitstream/v2/api/users/me"
DEFAULT_PROFILE_TTL_SECONDS = 300
# The lookup runs on every clerk tool call; without a cooldown an unhealthy
# /users/me would be hit (and waited on) once per call by every affected caller.
FAILED_LOOKUP_COOLDOWN_SECONDS = 30
PROFILE_LOOKUP_TIMEOUT_SECONDS = 5.0
_MAX_CACHED_CALLERS = 10_000

CallerKey = Tuple[str, str]


class CallerProfile(NamedTuple):
    owner_id: str
    email: Optional[str]


class CallerProfileLookup:
    """Fills owner_id and email on a TenantContext from the caller's /users/me, cached per caller."""

    def __init__(
        self,
        ttl_seconds: float = DEFAULT_PROFILE_TTL_SECONDS,
        failure_cooldown_seconds: float = FAILED_LOOKUP_COOLDOWN_SECONDS,
    ) -> None:
        self._profiles: TTLCache[CallerKey, CallerProfile] = TTLCache(
            maxsize=_MAX_CACHED_CALLERS, ttl=ttl_seconds
        )
        self._recent_failures: TTLCache[CallerKey, bool] = TTLCache(
            maxsize=_MAX_CACHED_CALLERS, ttl=failure_cooldown_seconds
        )
        self._in_flight: Dict[CallerKey, asyncio.Task[Optional[CallerProfile]]] = {}

    async def with_profile(self, ctx: TenantContext) -> TenantContext:
        if ctx.owner_id:
            return ctx
        profile = await self._profile_for(ctx)
        if profile is None:
            return ctx
        return ctx.model_copy(update={"owner_id": profile.owner_id, "email": profile.email})

    async def _profile_for(self, ctx: TenantContext) -> Optional[CallerProfile]:
        if not ctx.user_id:
            return await self._fetch(ctx)
        key: CallerKey = (ctx.base_url, ctx.user_id)
        cached: Optional[CallerProfile] = self._profiles.get(key)
        if cached is not None or key in self._recent_failures:
            return cached
        task = self._in_flight.get(key)
        if task is None:
            task = asyncio.create_task(self._fetch_and_remember(key, ctx))
            self._in_flight[key] = task
        return await asyncio.shield(task)

    async def _fetch_and_remember(
        self, key: CallerKey, ctx: TenantContext
    ) -> Optional[CallerProfile]:
        try:
            profile = await self._fetch(ctx)
            if profile is None:
                self._recent_failures[key] = True
            else:
                self._profiles[key] = profile
            return profile
        finally:
            self._in_flight.pop(key, None)

    async def _fetch(self, ctx: TenantContext) -> Optional[CallerProfile]:
        headers = AuthConfigFactory.from_tenant_context(ctx).get_auth_headers()
        try:
            response = await asyncio.wait_for(
                get_shared_http_client().get(f"{ctx.base_url}{USERS_ME_PATH}", headers=headers),
                timeout=PROFILE_LOOKUP_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Caller profile lookup timed out after {}s", PROFILE_LOOKUP_TIMEOUT_SECONDS
            )
            return None
        except httpx.HTTPError as exc:
            logger.warning("Caller profile lookup failed: {}", type(exc).__name__)
            return None
        if response.status_code != 200:
            logger.warning("Caller profile lookup answered HTTP {}", response.status_code)
            return None
        try:
            data = response.json()
        except ValueError:
            logger.warning("Caller profile lookup returned a body that is not JSON")
            return None
        owner_id = data.get("id") if isinstance(data, dict) else None
        if not owner_id:
            logger.warning("Caller profile lookup returned no user id")
            return None
        return CallerProfile(owner_id=owner_id, email=email_from_user_profile(data))
