"""Redis-like caching strategies for enhanced MCP server performance.

This module implements Redis-inspired caching patterns including:
- LRU eviction policies
- Cache warming strategies
- Pipeline operations
- Pub/Sub for cache invalidation
- Intelligent prefetching
- Cache analytics and optimization
"""

import asyncio
import hashlib
import json
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Union

from loguru import logger

# Import existing cache components


@dataclass
class CacheEntry:
    """Enhanced cache entry with Redis-like metadata."""

    value: Any
    created_at: datetime
    last_accessed: datetime
    access_count: int
    ttl_seconds: Optional[int]
    tags: Set[str]
    size_bytes: int

    def is_expired(self) -> bool:
        """Check if entry has expired."""
        if self.ttl_seconds is None:
            return False
        return (datetime.now(timezone.utc) - self.created_at).total_seconds() > self.ttl_seconds

    def should_warm(self, warming_threshold: float = 0.8) -> bool:
        """Check if entry should be warmed (refreshed proactively)."""
        if self.ttl_seconds is None:
            return False
        age_ratio = (
            datetime.now(timezone.utc) - self.created_at
        ).total_seconds() / self.ttl_seconds
        return age_ratio >= warming_threshold


@dataclass
class CacheStats:
    """Comprehensive cache statistics."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    warming_operations: int = 0
    prefetch_operations: int = 0
    pipeline_operations: int = 0
    memory_usage_bytes: int = 0
    avg_access_time_ms: float = 0.0
    hot_keys: List[str] = None

    def __post_init__(self):
        if self.hot_keys is None:
            self.hot_keys = []

    @property
    def hit_rate(self) -> float:
        """Calculate hit rate percentage."""
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0


class RedisLikeCache:
    """Redis-inspired cache with advanced optimization strategies."""

    def __init__(
        self,
        max_size: int = 10000,
        default_ttl: int = 3600,
        warming_threshold: float = 0.8,
        eviction_policy: str = "lru",
    ):
        """Initialize Redis-like cache.

        Args:
            max_size: Maximum number of entries
            default_ttl: Default TTL in seconds
            warming_threshold: When to start cache warming (0.0-1.0)
            eviction_policy: Eviction policy ('lru', 'lfu', 'ttl')
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.warming_threshold = warming_threshold
        self.eviction_policy = eviction_policy

        # Cache storage
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()

        # Statistics
        self._stats = CacheStats()

        # Cache warming and prefetching
        self._warming_tasks: Set[str] = set()
        self._prefetch_patterns: Dict[str, List[str]] = defaultdict(list)
        self._access_patterns: Dict[str, List[datetime]] = defaultdict(list)

        # Pipeline operations
        self._pipeline_queue: List[Dict[str, Any]] = []
        self._pipeline_lock = asyncio.Lock()

        # Background tasks
        self._background_tasks_started = False

    async def get(self, key: str, default: Any = None) -> Any:
        """Get value from cache with Redis-like behavior.

        Args:
            key: Cache key
            default: Default value if not found

        Returns:
            Cached value or default
        """
        start_time = time.time()

        async with self._lock:
            if key not in self._cache:
                self._stats.misses += 1
                self._update_access_time(start_time)
                return default

            entry = self._cache[key]

            # Check expiration
            if entry.is_expired():
                del self._cache[key]
                self._stats.evictions += 1
                self._stats.misses += 1
                self._update_access_time(start_time)
                return default

            # Update access metadata
            entry.last_accessed = datetime.now(timezone.utc)
            entry.access_count += 1

            # Move to end for LRU
            if self.eviction_policy == "lru":
                self._cache.move_to_end(key)

            # Track access patterns
            self._track_access_pattern(key)

            # Check if warming is needed
            if entry.should_warm(self.warming_threshold) and key not in self._warming_tasks:
                await self._schedule_warming(key)

            self._stats.hits += 1
            self._update_access_time(start_time)

            # Trigger prefetching based on patterns
            await self._trigger_prefetch(key)

            return entry.value

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        tags: Optional[Union[Set[str], List[str]]] = None,
    ) -> bool:
        """Set value in cache with Redis-like options.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds
            tags: Tags for cache invalidation

        Returns:
            True if successfully set
        """
        if not self._background_tasks_started:
            self._start_background_tasks()
            self._background_tasks_started = True

        async with self._lock:
            # Calculate size
            size_bytes = len(json.dumps(value, default=str).encode("utf-8"))

            # Normalize tags to set
            normalized_tags = set()
            if tags:
                if isinstance(tags, (list, tuple)):
                    normalized_tags = set(tags)
                elif isinstance(tags, set):
                    normalized_tags = tags

            # Create entry
            entry = CacheEntry(
                value=value,
                created_at=datetime.now(timezone.utc),
                last_accessed=datetime.now(timezone.utc),
                access_count=1,
                ttl_seconds=ttl or self.default_ttl,
                tags=normalized_tags,
                size_bytes=size_bytes,
            )

            # Evict if necessary
            await self._evict_if_needed()

            # Store entry
            self._cache[key] = entry
            self._stats.memory_usage_bytes += size_bytes

            logger.debug(f"Cached {key} with TTL {entry.ttl_seconds}s, size {size_bytes} bytes")
            return True

    async def delete(self, key: str) -> bool:
        """Delete key from cache.

        Args:
            key: Cache key to delete

        Returns:
            True if key existed and was deleted
        """
        async with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                self._stats.memory_usage_bytes -= entry.size_bytes
                del self._cache[key]
                return True
            return False

    async def invalidate_by_tags(self, tags: Set[str]) -> int:
        """Invalidate all entries with matching tags.

        Args:
            tags: Tags to match for invalidation

        Returns:
            Number of entries invalidated
        """
        async with self._lock:
            keys_to_delete = []
            for key, entry in self._cache.items():
                if entry.tags.intersection(tags):
                    keys_to_delete.append(key)

            for key in keys_to_delete:
                await self.delete(key)

            logger.info(f"Invalidated {len(keys_to_delete)} entries by tags: {tags}")
            return len(keys_to_delete)

    async def pipeline_execute(self, operations: List[Dict[str, Any]]) -> List[Any]:
        """Execute multiple operations in a pipeline.

        Args:
            operations: List of operations to execute

        Returns:
            List of results
        """
        async with self._pipeline_lock:
            results = []

            for op in operations:
                op_type = op.get("type")
                key = op.get("key")

                if op_type == "get":
                    result = await self.get(key, op.get("default"))
                    results.append(result)
                elif op_type == "set":
                    result = await self.set(key, op.get("value"), op.get("ttl"), op.get("tags"))
                    results.append(result)
                elif op_type == "delete":
                    result = await self.delete(key)
                    results.append(result)
                else:
                    results.append(None)

            self._stats.pipeline_operations += 1
            return results

    async def warm_cache(self, key: str, loader: Callable) -> bool:
        """Warm cache entry by reloading data.

        Args:
            key: Cache key to warm
            loader: Function to load fresh data

        Returns:
            True if successfully warmed
        """
        try:
            if key in self._warming_tasks:
                return False

            self._warming_tasks.add(key)
            logger.debug(f"Warming cache for {key}")

            # Load fresh data
            fresh_data = await loader()

            # Update cache
            if fresh_data is not None:
                # Preserve existing TTL and tags if entry exists
                existing_entry = self._cache.get(key)
                ttl = existing_entry.ttl_seconds if existing_entry else None
                tags = existing_entry.tags if existing_entry else set()

                await self.set(key, fresh_data, ttl, tags)
                self._stats.warming_operations += 1
                logger.debug(f"Successfully warmed cache for {key}")
                return True

            return False

        except Exception as e:
            logger.error(f"Cache warming failed for {key}: {e}")
            return False
        finally:
            self._warming_tasks.discard(key)

    async def prefetch(self, keys: List[str], loader: Callable) -> int:
        """Prefetch multiple keys into cache.

        Args:
            keys: List of keys to prefetch
            loader: Function to load data for keys

        Returns:
            Number of keys successfully prefetched
        """
        try:
            # Load data for all keys
            data = await loader(keys)
            count = 0

            for key in keys:
                if key in data:
                    await self.set(key, data[key])
                    count += 1

            self._stats.prefetch_operations += 1
            logger.info(f"Prefetched {count}/{len(keys)} keys")
            return count

        except Exception as e:
            logger.error(f"Prefetch failed: {e}")
            return 0

    async def get_stats(self) -> CacheStats:
        """Get comprehensive cache statistics.

        Returns:
            Cache statistics
        """
        async with self._lock:
            # Calculate hot keys (most accessed)
            key_access_counts = [(key, entry.access_count) for key, entry in self._cache.items()]
            hot_keys = [
                key for key, _ in sorted(key_access_counts, key=lambda x: x[1], reverse=True)[:10]
            ]

            self._stats.hot_keys = hot_keys
            self._stats.memory_usage_bytes = sum(entry.size_bytes for entry in self._cache.values())

            return self._stats

    def _start_background_tasks(self):
        """Start background maintenance tasks."""
        asyncio.create_task(self._cleanup_expired_entries())
        asyncio.create_task(self._analyze_access_patterns())

    async def _cleanup_expired_entries(self):
        """Background task to clean up expired entries."""
        while True:
            try:
                await asyncio.sleep(60)  # Run every minute

                async with self._lock:
                    expired_keys = []
                    for key, entry in self._cache.items():
                        if entry.is_expired():
                            expired_keys.append(key)

                    for key in expired_keys:
                        entry = self._cache[key]
                        self._stats.memory_usage_bytes -= entry.size_bytes
                        del self._cache[key]
                        self._stats.evictions += 1

                    if expired_keys:
                        logger.debug(f"Cleaned up {len(expired_keys)} expired entries")

            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")

    async def _analyze_access_patterns(self):
        """Background task to analyze access patterns for prefetching."""
        while True:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes

                # Analyze patterns and update prefetch rules
                for key, accesses in self._access_patterns.items():
                    # Keep only recent accesses (last hour)
                    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
                    recent_accesses = [a for a in accesses if a > cutoff]
                    self._access_patterns[key] = recent_accesses

                logger.debug("Access pattern analysis completed")

            except Exception as e:
                logger.error(f"Error in pattern analysis: {e}")

    async def _evict_if_needed(self):
        """Evict entries if cache is full."""
        while len(self._cache) >= self.max_size:
            if self.eviction_policy == "lru":
                # Remove least recently used
                key, entry = self._cache.popitem(last=False)
            elif self.eviction_policy == "lfu":
                # Remove least frequently used
                min_key = min(self._cache.keys(), key=lambda k: self._cache[k].access_count)
                entry = self._cache.pop(min_key)
            elif self.eviction_policy == "ttl":
                # Remove entry with shortest remaining TTL
                min_key = min(
                    self._cache.keys(),
                    key=lambda k: (
                        self._cache[k].created_at
                        + timedelta(seconds=self._cache[k].ttl_seconds or 0)
                    ),
                )
                entry = self._cache.pop(min_key)
            else:
                # Default to LRU
                key, entry = self._cache.popitem(last=False)

            self._stats.memory_usage_bytes -= entry.size_bytes
            self._stats.evictions += 1

    async def _schedule_warming(self, key: str):
        """Schedule cache warming for a key."""
        # This would be implemented with actual data loaders
        # For now, just track that warming was requested
        self._warming_tasks.add(key)
        logger.debug(f"Scheduled warming for {key}")

    async def _trigger_prefetch(self, key: str):
        """Trigger prefetching based on access patterns."""
        # Simple pattern: if key ends with number, prefetch next few
        if key[-1].isdigit():
            base_key = key[:-1]
            current_num = int(key[-1])

            # Prefetch next 2 keys
            for i in range(1, 3):
                next_key = f"{base_key}{current_num + i}"
                if next_key not in self._cache:
                    logger.debug(f"Would prefetch {next_key} based on access to {key}")

    def _track_access_pattern(self, key: str):
        """Track access patterns for intelligent prefetching."""
        now = datetime.now(timezone.utc)
        self._access_patterns[key].append(now)

        # Keep only recent accesses
        cutoff = now - timedelta(hours=1)
        self._access_patterns[key] = [a for a in self._access_patterns[key] if a > cutoff]

    def _update_access_time(self, start_time: float):
        """Update average access time statistics."""
        access_time_ms = (time.time() - start_time) * 1000

        # Simple moving average
        if self._stats.avg_access_time_ms == 0:
            self._stats.avg_access_time_ms = access_time_ms
        else:
            self._stats.avg_access_time_ms = (self._stats.avg_access_time_ms * 0.9) + (
                access_time_ms * 0.1
            )


# Global Redis-like cache instance
redis_like_cache = RedisLikeCache(
    max_size=50000, default_ttl=3600, warming_threshold=0.8, eviction_policy="lru"
)


def redis_cache_decorator(
    ttl: Optional[int] = None, tags: Optional[Set[str]] = None, enable_warming: bool = True
):
    """Decorator for Redis-like caching with advanced features.

    Args:
        ttl: Time to live in seconds
        tags: Tags for cache invalidation
        enable_warming: Enable cache warming
    """

    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs):
            # Generate cache key
            key_data = {"function": func.__name__, "args": str(args), "kwargs": kwargs}
            cache_key = hashlib.sha256(json.dumps(key_data, sort_keys=True).encode()).hexdigest()

            # Try to get cached result
            cached_result = await redis_like_cache.get(cache_key)
            if cached_result is not None:
                return cached_result

            # Execute function and cache result
            result = await func(*args, **kwargs)
            await redis_like_cache.set(cache_key, result, ttl, tags)
            return result

        return wrapper

    return decorator
