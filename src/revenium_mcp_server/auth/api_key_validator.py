"""Per-request Revenium API-key validation against the platform /users/me.

Pure module: no FastMCP imports. Wrapped by ApiKeyTokenVerifier for the
FastMCP auth gate. Validates a bearer token by calling the HyperCurrent
Management API and caches the resulting identity for a short TTL.
"""
from __future__ import annotations

import asyncio
import hashlib
from typing import Literal

import httpx
from cachetools import TTLCache
from loguru import logger
from pydantic import BaseModel, ConfigDict, ValidationError

from ..client import get_shared_http_client

DEFAULT_CACHE_TTL_SECONDS = 30
_CACHE_MAXSIZE = 10_000
_USERS_ME_PATH = "/profitstream/v2/api/users/me"


class ApiKeyValidationError(Exception):
    """Base class for all API-key validation failures."""


class InvalidTokenError(ApiKeyValidationError):
    """401 from /users/me: key unknown, revoked, or soft-deleted."""


class KeySuspendedError(ApiKeyValidationError):
    """403 'API key is suspended'."""


class KeyExpiredError(ApiKeyValidationError):
    """403 'API key has expired'."""


class InsufficientScopeError(ApiKeyValidationError):
    """403 'Insufficient API key scope', or the rev_mk_ edge pre-check."""


class ApiKeyIdentity(BaseModel):
    """Identity resolved from a validated API key (one UserResource)."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    tenant_id: str
    team_id: str
    email: str
    roles: list[str]
    scope_from_prefix: Literal["WRITE", "READ", "METERING", "UNKNOWN"]


def _strip_bearer(token: str) -> str:
    stripped = token.strip()
    if stripped[:7].lower() == "bearer ":
        return stripped[7:].strip()
    return stripped


def _fingerprint(token: str) -> str:
    """First 8 hex chars of SHA-256 — safe to log, never the raw token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]


def _cache_key(token: str) -> str:
    """Full SHA-256 hex digest — the cache lookup key (collision-resistant)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _scope_from_prefix(token: str) -> Literal["WRITE", "READ", "METERING", "UNKNOWN"]:
    if token.startswith("rev_sk_"):
        return "WRITE"
    if token.startswith("rev_rk_"):
        return "READ"
    if token.startswith("rev_mk_"):
        return "METERING"
    return "UNKNOWN"


class ApiKeyValidator:
    """Validates bearer tokens against /users/me with a short-TTL identity cache."""

    def __init__(
        self,
        *,
        platform_base_url: str,
        ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self._base_url = platform_base_url.rstrip("/")
        self._cache: TTLCache = TTLCache(maxsize=_CACHE_MAXSIZE, ttl=ttl_seconds)
        # Per-key single-flight: concurrent requests for the SAME cache key
        # share one /users/me call; requests for DIFFERENT keys never block
        # each other. _inflight_guard only protects the short dict lookup.
        self._inflight_locks: dict[str, asyncio.Lock] = {}
        self._inflight_guard = asyncio.Lock()

    def invalidate(self, token: str) -> None:
        """Drop a cached identity so the next request re-validates."""
        self._cache.pop(_cache_key(_strip_bearer(token)), None)

    async def validate(self, token: str) -> ApiKeyIdentity:
        token = _strip_bearer(token)
        scope = _scope_from_prefix(token)
        if scope == "METERING":
            raise InsufficientScopeError(
                "Metering-only keys (rev_mk_) cannot access the MCP server's "
                "management surface"
            )

        key = _cache_key(token)
        # Fast path: cache hits return concurrently without the lock.
        cached: ApiKeyIdentity | None = self._cache.get(key)
        if cached is not None:
            return cached
        # Slow path: acquire a per-key lock so concurrent requests for the same
        # key collapse to a single /users/me call (single-flight), while
        # distinct keys validate concurrently.
        async with self._inflight_guard:
            lock = self._inflight_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._inflight_locks[key] = lock

        async with lock:
            # Re-check under the lock in case a concurrent request for the same
            # key populated the entry while we waited.
            cached_locked: ApiKeyIdentity | None = self._cache.get(key)
            if cached_locked is not None:
                return cached_locked
            try:
                identity = await self._fetch(token, scope)
                self._cache[key] = identity
                return identity
            finally:
                # Drop the per-key lock so the map cannot grow unbounded. On
                # success a late waiter re-checks and hits the now-populated
                # cache; on failure (no cache entry) waiters retry independently
                # — negative caching to dedupe failed lookups is deferred.
                async with self._inflight_guard:
                    self._inflight_locks.pop(key, None)

    async def _fetch(
        self,
        token: str,
        scope: Literal["WRITE", "READ", "METERING", "UNKNOWN"],
    ) -> ApiKeyIdentity:
        client = get_shared_http_client()
        try:
            resp = await client.get(
                f"{self._base_url}{_USERS_ME_PATH}",
                headers={"x-api-key": token},
            )
        except httpx.HTTPError as exc:
            logger.info(
                "API-key validation transport error {} for key_fingerprint={}",
                type(exc).__name__,
                _fingerprint(token),
            )
            raise ApiKeyValidationError(
                f"Platform unreachable: {type(exc).__name__}"
            ) from exc
        status = resp.status_code
        fp = _fingerprint(token)

        if status == 200:
            try:
                data = resp.json()
                # defaultTeamId can be null; fall back to the first team so a
                # user without an explicit default still resolves a tenant.
                team_id = data.get("defaultTeamId")
                if not team_id:
                    teams = data.get("teams") or []
                    if not teams:
                        # Structurally valid response, but the account has no
                        # team — raise a clear error instead of letting a None
                        # team_id fail Pydantic and surface as "Malformed".
                        raise ApiKeyValidationError(
                            "Account has no team assigned; cannot resolve a tenant"
                        )
                    team_id = teams[0]["id"]
                return ApiKeyIdentity(
                    user_id=data["id"],
                    tenant_id=data["tenantId"],
                    team_id=team_id,
                    email=data.get("email", ""),
                    roles=data.get("roles", []),
                    scope_from_prefix=scope,
                )
            except (KeyError, ValidationError, ValueError) as exc:
                logger.warning(
                    "Malformed /users/me 200 response for key_fingerprint={}: {}",
                    fp,
                    type(exc).__name__,
                )
                raise ApiKeyValidationError(
                    "Malformed /users/me response from platform"
                ) from exc
        if status == 401:
            logger.info("API-key validation 401 for key_fingerprint={}", fp)
            raise InvalidTokenError("API key is invalid, revoked, or unknown")
        if status == 403:
            body = resp.text.lower()
            # Cap the reflected body so an oversized or sensitive 403 payload
            # cannot bloat exception messages or crash dumps.
            detail = resp.text[:512]
            logger.info("API-key validation 403 for key_fingerprint={}", fp)
            if "suspended" in body:
                raise KeySuspendedError(detail)
            if "expired" in body:
                raise KeyExpiredError(detail)
            if "scope" in body:
                raise InsufficientScopeError(detail)
            raise ApiKeyValidationError(f"Forbidden: {detail}")
        logger.warning(
            "API-key validation unexpected status={} for key_fingerprint={}",
            status,
            fp,
        )
        raise ApiKeyValidationError(
            f"Unexpected status {status} from platform /users/me"
        )
