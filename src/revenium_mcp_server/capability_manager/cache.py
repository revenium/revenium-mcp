"""Capability caching system for the Unified Capability Manager.

This module provides efficient caching of verified capabilities with TTL support,
performance metrics, and optimized cache warming strategies.
"""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Set

from loguru import logger


class CapabilityCache:
    """High-performance cache for verified capabilities with TTL support and cache warming."""

    def __init__(self, ttl: int = 3600):
        """Initialize the capability cache.

        Args:
            ttl: Time-to-live for cached entries in seconds (default: 1 hour)
        """
        self.ttl = ttl
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._timestamps: Dict[str, datetime] = {}
        self._lock = asyncio.Lock()

        # Performance metrics
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._cache_warming_hits = 0

        # Cache warming configuration
        self._warming_enabled = True
        self._warming_threshold = 0.8  # Refresh when 80% of TTL has passed
        self._warming_tasks: Set[str] = set()  # Track ongoing warming tasks

    async def get(
        self, key: str, refresh_callback: Optional[Callable] = None
    ) -> Optional[Dict[str, Any]]:
        """Get cached capabilities for a resource type with optional cache warming.

        Args:
            key: Resource type key
            refresh_callback: Optional callback to refresh cache when near expiry

        Returns:
            Cached capabilities or None if not found/expired
        """
        async with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None

            # Check if entry has expired
            if self._is_expired(key):
                await self._evict(key)
                self._misses += 1
                return None

            # Check if cache warming is needed (entry is near expiry)
            if (
                self._warming_enabled
                and refresh_callback
                and self._should_warm_cache(key)
                and key not in self._warming_tasks
            ):
                # Start cache warming in background (don't await)
                self._warming_tasks.add(key)
                asyncio.create_task(self._warm_cache(key, refresh_callback))
                self._cache_warming_hits += 1
                logger.debug(f"Started cache warming for {key}")

            self._hits += 1
            logger.debug(f"Cache hit for {key}")
            return self._cache[key].copy()

    async def set(self, key: str, value: Dict[str, Any]) -> None:
        """Cache capabilities for a resource type.

        Args:
            key: Resource type key
            value: Capabilities to cache
        """
        async with self._lock:
            self._cache[key] = value.copy()
            self._timestamps[key] = datetime.now(timezone.utc)
            logger.debug(f"Cached capabilities for {key}")

    async def invalidate(self, key: str) -> bool:
        """Invalidate cached capabilities for a resource type.

        Args:
            key: Resource type key

        Returns:
            True if key was cached, False otherwise
        """
        async with self._lock:
            if key in self._cache:
                await self._evict(key)
                logger.debug(f"Invalidated cache for {key}")
                return True
            return False

    async def clear(self) -> None:
        """Clear all cached capabilities."""
        async with self._lock:
            self._cache.clear()
            self._timestamps.clear()
            logger.info("Cleared all cached capabilities")

    async def get_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics.

        Returns:
            Dictionary containing cache metrics
        """
        async with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0

            return {
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate_percent": round(hit_rate, 2),
                "evictions": self._evictions,
                "cached_entries": len(self._cache),
                "ttl_seconds": self.ttl,
            }

    async def cleanup_expired(self) -> int:
        """Remove expired entries from cache.

        Returns:
            Number of entries removed
        """
        async with self._lock:
            expired_keys = [key for key in self._cache.keys() if self._is_expired(key)]

            for key in expired_keys:
                await self._evict(key)

            if expired_keys:
                logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

            return len(expired_keys)

    def _is_expired(self, key: str) -> bool:
        """Check if a cache entry has expired.

        Args:
            key: Resource type key

        Returns:
            True if expired, False otherwise
        """
        if key not in self._timestamps:
            return True

        expiry_time = self._timestamps[key] + timedelta(seconds=self.ttl)
        return datetime.now(timezone.utc) > expiry_time

    async def _evict(self, key: str) -> None:
        """Remove a key from cache.

        Args:
            key: Resource type key to remove
        """
        if key in self._cache:
            del self._cache[key]
        if key in self._timestamps:
            del self._timestamps[key]
        self._evictions += 1

    def _should_warm_cache(self, key: str) -> bool:
        """Check if cache entry should be warmed (refreshed proactively).

        Args:
            key: Cache key to check

        Returns:
            True if cache should be warmed, False otherwise
        """
        if key not in self._timestamps:
            return False

        # Calculate how much of the TTL has passed
        age = datetime.now(timezone.utc) - self._timestamps[key]
        age_ratio = age.total_seconds() / self.ttl

        # Warm cache when it's reached the warming threshold
        return age_ratio >= self._warming_threshold

    async def _warm_cache(self, key: str, refresh_callback: Callable) -> None:
        """Warm cache by refreshing data in background.

        Args:
            key: Cache key to warm
            refresh_callback: Callback function to refresh the data
        """
        try:
            logger.debug(f"Warming cache for {key}")

            # Call the refresh callback to get new data
            new_data = await refresh_callback(key)

            if new_data:
                # Update cache with new data
                await self.set(key, new_data)
                logger.debug(f"Cache warmed successfully for {key}")
            else:
                logger.warning(f"Cache warming failed for {key} - no data returned")

        except Exception as e:
            logger.error(f"Cache warming failed for {key}: {e}")
        finally:
            # Remove from warming tasks
            self._warming_tasks.discard(key)

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics.

        Returns:
            Dictionary containing cache statistics
        """
        total_requests = self._hits + self._misses
        hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0

        return {
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "cache_warming_hits": self._cache_warming_hits,
            "hit_rate_percent": round(hit_rate, 2),
            "total_requests": total_requests,
            "cache_size": len(self._cache),
            "ttl_seconds": self.ttl,
            "warming_enabled": self._warming_enabled,
            "warming_threshold": self._warming_threshold,
            "active_warming_tasks": len(self._warming_tasks),
        }


class CapabilityCacheManager:
    """Manager for automatic cache maintenance and cleanup."""

    def __init__(self, cache: CapabilityCache, cleanup_interval: int = 300):
        """Initialize the cache manager.

        Args:
            cache: CapabilityCache instance to manage
            cleanup_interval: Cleanup interval in seconds (default: 5 minutes)
        """
        self.cache = cache
        self.cleanup_interval = cleanup_interval
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start automatic cache cleanup."""
        if self._running:
            return

        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info(f"Started cache cleanup with {self.cleanup_interval}s interval")

    async def stop(self) -> None:
        """Stop automatic cache cleanup."""
        if not self._running:
            return

        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        logger.info("Stopped cache cleanup")

    async def _cleanup_loop(self) -> None:
        """Main cleanup loop."""
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                if self._running:
                    expired_count = await self.cache.cleanup_expired()
                    if expired_count > 0:
                        logger.debug(f"Cache cleanup removed {expired_count} expired entries")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cache cleanup loop: {e}")
                await asyncio.sleep(60)  # Wait before retrying
