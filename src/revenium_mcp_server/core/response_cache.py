"""Advanced response caching system for MCP server performance optimization.

This module provides multi-level caching using DiskCache for persistent, high-performance
caching of API responses, validation results, and UCM capabilities.

Performance targets:
- Cache hit latency: <25µs (DiskCache performance)
- API response cache: 80% hit rate expected
- Validation cache: 70% hit rate expected
- Expected latency reduction: 100-150ms
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Union

from loguru import logger

if TYPE_CHECKING:
    from ..auth.tenant_context import TenantContext

from ..common.cache_key_factory import CacheKeyFactory

try:
    import diskcache as dc

    DISKCACHE_AVAILABLE = True
except ImportError:
    logger.warning("diskcache not available, using in-memory fallback")
    DISKCACHE_AVAILABLE = False
    dc = None

# Import Prometheus metrics if available
# Prometheus metrics removed - infrastructure monitoring handled externally
PROMETHEUS_METRICS_AVAILABLE = False

# Import Redis-like cache for enhanced performance
try:
    from .redis_like_cache import redis_like_cache

    REDIS_LIKE_CACHE_AVAILABLE = True
    # Only log in verbose startup mode
    import os
    startup_verbose = os.getenv("MCP_STARTUP_VERBOSE", "false").lower() == "true"
    if startup_verbose:
        logger.info("Redis-like cache available for enhanced performance")
except ImportError:
    logger.debug("Redis-like cache not available, using standard caching")
    REDIS_LIKE_CACHE_AVAILABLE = False
    redis_like_cache = None

# Create fallback classes if DiskCache is not available
if not DISKCACHE_AVAILABLE:

    class MockCache:
        def __init__(self, *args, **kwargs):
            self._data = {}

        def get(self, key, default=None):
            return self._data.get(key, default)

        def set(self, key, value, expire=None):
            self._data[key] = value
            return True

        def delete(self, key):
            return self._data.pop(key, None) is not None

        def clear(self):
            self._data.clear()
            return len(self._data)

        def memoize(self, expire=None):
            return lambda f: f

    # Create a mock dc module with Cache class
    class MockDC:
        Cache = MockCache

    dc = MockDC()  # noqa: F811


class ResponseCacheManager:
    """Multi-level response cache manager for enterprise performance optimization."""

    def __init__(self, cache_dir: str = ".cache/mcp_response_cache"):
        """Initialize the response cache manager.

        Args:
            cache_dir: Directory for persistent cache storage
        """
        self.cache_dir = cache_dir
        self.enabled = DISKCACHE_AVAILABLE

        if not self.enabled:
            logger.warning("DiskCache not available, using in-memory fallback")
            self._init_fallback_caches()
            return

        try:
            # L1: Request-scoped cache (in-memory, 1 request lifetime)
            self.l1_cache: Dict[str, Any] = {}

            # L2: Session cache (DiskCache, 5-minute TTL)
            self.l2_cache = dc.Cache(
                directory=f"{cache_dir}/l2_session",
                size_limit=100 * 1024 * 1024,  # 100MB
                timeout=1,
            )

            # L3: Persistent cache (DiskCache, 1-hour TTL)
            self.l3_cache = dc.Cache(
                directory=f"{cache_dir}/l3_persistent",
                size_limit=500 * 1024 * 1024,  # 500MB
                timeout=1,
            )

            # L4: Long-term cache (DiskCache, 24-hour TTL for stable data)
            self.l4_cache = dc.Cache(
                directory=f"{cache_dir}/l4_longterm",
                size_limit=1024 * 1024 * 1024,  # 1GB
                timeout=1,
            )

            # Cache statistics
            self.stats = {
                "l1_hits": 0,
                "l1_misses": 0,
                "l2_hits": 0,
                "l2_misses": 0,
                "l3_hits": 0,
                "l3_misses": 0,
                "l4_hits": 0,
                "l4_misses": 0,
                "total_requests": 0,
            }

            # Only log in verbose startup mode
            import os

            startup_verbose = os.getenv("MCP_STARTUP_VERBOSE", "false").lower() == "true"
            if startup_verbose:
                logger.info(f"ResponseCacheManager initialized with DiskCache at {cache_dir}")

        except Exception as e:
            logger.error(f"Failed to initialize DiskCache: {e}")
            self.enabled = False
            self._init_fallback_caches()

    def _init_fallback_caches(self):
        """Initialize fallback in-memory caches."""
        self.l1_cache = {}
        self.l2_cache = dc.Cache()
        self.l3_cache = dc.Cache()
        self.l4_cache = dc.Cache()
        self.stats = {
            "l1_hits": 0,
            "l1_misses": 0,
            "l2_hits": 0,
            "l2_misses": 0,
            "l3_hits": 0,
            "l3_misses": 0,
            "l4_hits": 0,
            "l4_misses": 0,
            "total_requests": 0,
        }

    def _generate_cache_key(
        self,
        prefix: str,
        data: Union[str, Dict[str, Any]],
        ctx: Optional[TenantContext] = None,
    ) -> str:
        if isinstance(data, str):
            content = data
        else:
            content = json.dumps(data, sort_keys=True, default=str)

        hash_obj = hashlib.sha256(content.encode("utf-8"))
        raw_key = f"{prefix}:{hash_obj.hexdigest()[:16]}"
        return CacheKeyFactory.make_key(ctx, raw_key)

    async def get_cached_response(
        self,
        cache_type: str,
        key_data: Union[str, Dict[str, Any]],
        cache_level: str = "auto",
        ctx: Optional[TenantContext] = None,
    ) -> Optional[Any]:
        if not self.enabled:
            return None

        self.stats["total_requests"] += 1

        try:
            cache_key = self._generate_cache_key(cache_type, key_data, ctx)

            # Try Redis-like cache first for enhanced performance
            if REDIS_LIKE_CACHE_AVAILABLE and redis_like_cache and cache_level in ("auto", "redis"):
                redis_result = await redis_like_cache.get(cache_key)
                if redis_result is not None:
                    logger.debug(f"Redis-like cache hit for {cache_type}: {cache_key[:20]}...")
                    return redis_result
            # L1 cache check (fastest)
            if cache_level in ("auto", "l1") and cache_key in self.l1_cache:
                self.stats["l1_hits"] += 1
                logger.debug(f"L1 cache hit for {cache_type}: {cache_key[:20]}...")
                return self.l1_cache[cache_key]

            if cache_level == "l1":
                self.stats["l1_misses"] += 1
                return None

            # L2 cache check (session)
            if cache_level in ("auto", "l2"):
                result = await self._async_cache_get(self.l2_cache, cache_key)
                if result is not None:
                    self.stats["l2_hits"] += 1
                    # Promote to L1 for faster access
                    self.l1_cache[cache_key] = result
                    logger.debug(f"L2 cache hit for {cache_type}: {cache_key[:20]}...")
                    return result
                elif cache_level == "l2":
                    self.stats["l2_misses"] += 1
                    return None

            # L3 cache check (persistent)
            if cache_level in ("auto", "l3"):
                result = await self._async_cache_get(self.l3_cache, cache_key)
                if result is not None:
                    self.stats["l3_hits"] += 1
                    # Promote to L1 and L2
                    self.l1_cache[cache_key] = result
                    await self._async_cache_set(self.l2_cache, cache_key, result, expire=300)
                    logger.debug(f"L3 cache hit for {cache_type}: {cache_key[:20]}...")
                    return result
                elif cache_level == "l3":
                    self.stats["l3_misses"] += 1
                    return None

            # L4 cache check (long-term)
            if cache_level in ("auto", "l4"):
                result = await self._async_cache_get(self.l4_cache, cache_key)
                if result is not None:
                    self.stats["l4_hits"] += 1
                    # Promote to all upper levels
                    self.l1_cache[cache_key] = result
                    await self._async_cache_set(self.l2_cache, cache_key, result, expire=300)
                    await self._async_cache_set(self.l3_cache, cache_key, result, expire=3600)
                    logger.debug(f"L4 cache hit for {cache_type}: {cache_key[:20]}...")
                    return result
                else:
                    self.stats["l4_misses"] += 1

            # Cache miss
            if cache_level == "auto":
                self.stats["l1_misses"] += 1
                self.stats["l2_misses"] += 1
                self.stats["l3_misses"] += 1
                self.stats["l4_misses"] += 1

            return None

        except Exception as e:
            logger.error(f"Error getting cached response: {e}")
            return None

    async def set_cached_response(
        self,
        cache_type: str,
        key_data: Union[str, Dict[str, Any]],
        value: Any,
        ttl_seconds: Optional[int] = None,
        ctx: Optional[TenantContext] = None,
    ) -> bool:
        if not self.enabled:
            return False

        try:
            cache_key = self._generate_cache_key(cache_type, key_data, ctx)
            # Determine TTL based on cache type
            if ttl_seconds is None:
                ttl_map = {
                    "api": 300,  # 5 minutes for API responses
                    "validation": 600,  # 10 minutes for validation results
                    "ucm": 900,  # 15 minutes for UCM capabilities
                    "model_provider": 3600,  # 1 hour for model/provider combinations
                }
                ttl_seconds = ttl_map.get(cache_type, 300)

            # Store in Redis-like cache for enhanced performance
            if REDIS_LIKE_CACHE_AVAILABLE and redis_like_cache:
                # Determine tags for cache invalidation
                tags = {cache_type}
                if cache_type == "ucm":
                    tags.add("capabilities")
                elif cache_type == "validation":
                    tags.add("validation")

                await redis_like_cache.set(cache_key, value, ttl_seconds, tags)

            # Store in L1 (immediate access)
            self.l1_cache[cache_key] = value

            # Store in appropriate persistent cache based on TTL
            if ttl_seconds <= 300:  # 5 minutes or less -> L2
                await self._async_cache_set(self.l2_cache, cache_key, value, expire=ttl_seconds)
            elif ttl_seconds <= 3600:  # 1 hour or less -> L3
                await self._async_cache_set(self.l3_cache, cache_key, value, expire=ttl_seconds)
            else:  # Longer -> L4
                await self._async_cache_set(self.l4_cache, cache_key, value, expire=ttl_seconds)

            logger.debug(f"Cached {cache_type} response: {cache_key[:20]}... (TTL: {ttl_seconds}s)")
            return True

        except Exception as e:
            logger.error(f"Error setting cached response: {e}")
            return False

    async def _async_cache_get(self, cache: Any, key: str) -> Optional[Any]:
        """Async wrapper for cache get operations."""
        if not self.enabled:
            return None

        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, cache.get, key)
        except Exception as e:
            logger.debug(f"Cache get error: {e}")
            return None

    async def _async_cache_set(
        self, cache: Any, key: str, value: Any, expire: Optional[int] = None
    ) -> bool:
        """Async wrapper for cache set operations."""
        if not self.enabled:
            return False

        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, cache.set, key, value, expire)
        except Exception as e:
            logger.debug(f"Cache set error: {e}")
            return False

    def clear_request_cache(self) -> None:
        """Clear L1 request-scoped cache."""
        self.l1_cache.clear()
        logger.debug("L1 request cache cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics and update Prometheus metrics.

        Returns:
            Dictionary with cache hit/miss statistics and ratios
        """
        total_hits = sum(self.stats[k] for k in self.stats if k.endswith("_hits"))
        total_misses = sum(self.stats[k] for k in self.stats if k.endswith("_misses"))
        total_lookups = total_hits + total_misses

        hit_rate = (total_hits / total_lookups) if total_lookups > 0 else 0

        # Update Prometheus metrics if available
        try:
            from ..monitoring.metrics import update_cache_stats
            for level in ["l1", "l2", "l3", "l4"]:
                level_hits = self.stats.get(f"{level}_hits", 0)
                level_misses = self.stats.get(f"{level}_misses", 0)
                level_total = level_hits + level_misses
                level_hit_rate = (level_hits / level_total) if level_total > 0 else 0

                # Update metrics for different cache types
                for cache_type in ["api", "validation", "ucm"]:
                    update_cache_stats(
                        cache_type, level, level_hit_rate, 0
                    )  # Size tracking would need more work
        except ImportError:
            # Prometheus metrics not available, skip
            pass

        return {
            **self.stats,
            "total_hits": total_hits,
            "total_misses": total_misses,
            "total_lookups": total_lookups,
            "hit_rate_percent": round(hit_rate * 100, 2),
            "cache_enabled": self.enabled,
        }

    async def warm_cache(
        self,
        cache_type: str,
        data_loader: Callable,
        ctx: Optional[TenantContext] = None,
    ) -> int:
        if not self.enabled:
            return 0

        try:
            data = await data_loader()
            count = 0

            if REDIS_LIKE_CACHE_AVAILABLE and redis_like_cache:
                operations = []
                for key, value in data.items():
                    cache_key = self._generate_cache_key(cache_type, key, ctx)
                    operations.append(
                        {
                            "type": "set",
                            "key": cache_key,
                            "value": value,
                            "ttl": 3600,  # 1 hour for warmed data
                            "tags": {cache_type, "warmed"},
                        }
                    )

                # Execute batch operations
                if operations:
                    results = await redis_like_cache.pipeline_execute(operations)
                    count = sum(1 for result in results if result)
                    logger.info(f"Redis-like cache warming: {count} items cached for {cache_type}")

            for key, value in data.items():
                success = await self.set_cached_response(cache_type, key, value, ctx=ctx)
                if success:
                    count += 1

            logger.info(f"Cache warming completed: {count} items cached for {cache_type}")
            return count

        except Exception as e:
            logger.error(f"Cache warming failed: {e}")
            return 0

    async def warm_frequently_accessed_data(
        self, ctx: Optional[TenantContext] = None
    ) -> Dict[str, int]:
        results = {}

        # Warm UCM capabilities for common resource types
        async def load_ucm_data():
            return {
                "products_capabilities": {
                    "currencies": ["USD", "EUR", "GBP"],
                    "plan_types": ["BASIC", "PREMIUM"],
                },
                "alerts_capabilities": {
                    "metrics": ["TOTAL_COST", "REQUEST_COUNT"],
                    "periods": ["daily", "weekly"],
                },
                "subscriptions_capabilities": {
                    "billing_periods": ["MONTHLY", "YEARLY"],
                    "statuses": ["ACTIVE", "CANCELLED"],
                },
            }

        results["ucm"] = await self.warm_cache("ucm", load_ucm_data, ctx=ctx)

        # Warm validation patterns for common field combinations
        async def load_validation_data():
            return {
                "common_model_providers": {
                    "gpt-4o": "openai",
                    "claude-3-5-sonnet": "anthropic",
                    "gemini-pro": "google",
                },
                "validation_rules": {
                    "required_fields": ["model", "provider", "input_tokens", "output_tokens"],
                    "optional_fields": ["organization_id", "task_type", "agent"],
                },
            }

        results["validation"] = await self.warm_cache("validation", load_validation_data, ctx=ctx)

        # Warm API response patterns
        async def load_api_data():
            return {
                "health_check": {"status": "healthy", "timestamp": "cached"},
                "capabilities_schema": {"type": "object", "properties": {}},
            }

        results["api"] = await self.warm_cache("api", load_api_data, ctx=ctx)

        total_warmed = sum(results.values())
        logger.info(
            f"Cache warming completed: {total_warmed} total items across {len(results)} cache types"
        )

        return results


# Global cache manager instance
response_cache = ResponseCacheManager()


def cache_response(
    cache_type: str, ttl_seconds: Optional[int] = None
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = kwargs.pop("ctx", None)
            cache_key_data = {"function": func.__name__, "args": str(args), "kwargs": kwargs}

            cached_result = await response_cache.get_cached_response(
                cache_type, cache_key_data, ctx=ctx
            )
            if cached_result is not None:
                return cached_result

            result = await func(*args, **kwargs)
            await response_cache.set_cached_response(
                cache_type, cache_key_data, result, ttl_seconds, ctx=ctx
            )
            return result

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = kwargs.pop("ctx", None)
            cache_key_data = {"function": func.__name__, "args": str(args), "kwargs": kwargs}

            try:
                loop = asyncio.get_running_loop()
                cached_result = loop.run_until_complete(
                    response_cache.get_cached_response(cache_type, cache_key_data, ctx=ctx)
                )
                if cached_result is not None:
                    return cached_result
            except RuntimeError:
                pass

            result = func(*args, **kwargs)

            try:
                loop = asyncio.get_running_loop()
                loop.run_until_complete(
                    response_cache.set_cached_response(
                        cache_type, cache_key_data, result, ttl_seconds, ctx=ctx
                    )
                )
            except RuntimeError:
                pass

            return result

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator
