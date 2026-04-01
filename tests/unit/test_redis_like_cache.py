"""Tests for core/redis_like_cache.py — LRU/LFU/TTL cache with eviction and pipelines."""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.revenium_mcp_server.core.redis_like_cache import (
    CacheEntry,
    CacheStats,
    RedisLikeCache,
)


# ---------------------------------------------------------------------------
# CacheEntry
# ---------------------------------------------------------------------------

class TestCacheEntry:
    def _make_entry(self, ttl=60, age_seconds=0):
        created = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        return CacheEntry(
            value="data",
            created_at=created,
            last_accessed=created,
            access_count=1,
            ttl_seconds=ttl,
            tags=set(),
            size_bytes=10,
        )

    def test_not_expired_when_fresh(self):
        entry = self._make_entry(ttl=60, age_seconds=0)
        assert entry.is_expired() is False

    def test_expired_when_old(self):
        entry = self._make_entry(ttl=1, age_seconds=5)
        assert entry.is_expired() is True

    def test_no_ttl_never_expires(self):
        entry = self._make_entry(ttl=None, age_seconds=9999)
        # ttl_seconds=None set manually
        entry.ttl_seconds = None
        assert entry.is_expired() is False

    def test_should_warm_when_near_expiry(self):
        entry = self._make_entry(ttl=100, age_seconds=85)
        assert entry.should_warm(warming_threshold=0.8) is True

    def test_should_not_warm_when_fresh(self):
        entry = self._make_entry(ttl=100, age_seconds=10)
        assert entry.should_warm(warming_threshold=0.8) is False

    def test_should_warm_no_ttl_returns_false(self):
        entry = self._make_entry(ttl=None)
        entry.ttl_seconds = None
        assert entry.should_warm() is False


# ---------------------------------------------------------------------------
# CacheStats
# ---------------------------------------------------------------------------

class TestCacheStats:
    def test_hit_rate_with_data(self):
        stats = CacheStats(hits=75, misses=25)
        assert stats.hit_rate == 75.0


# ---------------------------------------------------------------------------
# RedisLikeCache — basic operations
# ---------------------------------------------------------------------------

class TestRedisLikeCacheBasic:
    @pytest.mark.asyncio
    async def test_set_and_get(self):
        cache = RedisLikeCache(max_size=100, default_ttl=60)
        cache._background_tasks_started = True  # Skip background tasks
        await cache.set("key1", {"value": 42})
        result = await cache.get("key1")
        assert result["value"] == 42

    @pytest.mark.asyncio
    async def test_get_missing_returns_default(self):
        cache = RedisLikeCache(max_size=100)
        result = await cache.get("nonexistent", default="fallback")
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_get_expired_returns_default(self):
        cache = RedisLikeCache(max_size=100, default_ttl=60)
        cache._background_tasks_started = True
        await cache.set("key1", "value", ttl=1)

        # Manually expire it
        entry = cache._cache["key1"]
        entry.created_at = datetime.now(timezone.utc) - timedelta(seconds=100)

        result = await cache.get("key1", default="gone")
        assert result == "gone"

    @pytest.mark.asyncio
    async def test_delete_existing_key(self):
        cache = RedisLikeCache(max_size=100)
        cache._background_tasks_started = True
        await cache.set("key1", "value")
        assert await cache.delete("key1") is True
        assert await cache.get("key1") is None

    @pytest.mark.asyncio
    async def test_delete_missing_key(self):
        cache = RedisLikeCache(max_size=100)
        assert await cache.delete("nope") is False

    @pytest.mark.asyncio
    async def test_stats_track_hits_and_misses(self):
        cache = RedisLikeCache(max_size=100)
        cache._background_tasks_started = True
        await cache.set("k", "v")
        await cache.get("k")
        await cache.get("missing")
        assert cache._stats.hits == 1
        assert cache._stats.misses == 1


# ---------------------------------------------------------------------------
# Eviction policies
# ---------------------------------------------------------------------------

class TestEvictionPolicies:
    @pytest.mark.asyncio
    async def test_lru_eviction(self):
        cache = RedisLikeCache(max_size=2, eviction_policy="lru")
        cache._background_tasks_started = True
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.set("c", 3)  # Should evict "a"
        assert await cache.get("a") is None
        assert await cache.get("c") == 3

    @pytest.mark.asyncio
    async def test_lfu_eviction(self):
        cache = RedisLikeCache(max_size=2, eviction_policy="lfu")
        cache._background_tasks_started = True
        await cache.set("a", 1)
        await cache.set("b", 2)
        # Access "a" more to increase its count
        await cache.get("a")
        await cache.get("a")
        await cache.set("c", 3)  # Should evict "b" (lower access count)
        assert await cache.get("a") is not None
        assert await cache.get("b") is None


# ---------------------------------------------------------------------------
# Tag invalidation
# ---------------------------------------------------------------------------

class TestTagInvalidation:
    @pytest.mark.asyncio
    async def test_tags_stored_on_entries(self):
        """Verify tags are correctly stored and can be matched."""
        cache = RedisLikeCache(max_size=100)
        cache._background_tasks_started = True
        await cache.set("k1", "v1", tags={"api"})
        await cache.set("k2", "v2", tags={"api", "products"})
        await cache.set("k3", "v3", tags={"users"})

        # Verify tags are stored correctly
        assert cache._cache["k1"].tags == {"api"}
        assert cache._cache["k2"].tags == {"api", "products"}
        assert cache._cache["k3"].tags == {"users"}

        # Verify tag intersection works for matching
        assert cache._cache["k1"].tags.intersection({"api"})
        assert cache._cache["k2"].tags.intersection({"api"})
        assert not cache._cache["k3"].tags.intersection({"api"})

    @pytest.mark.asyncio
    async def test_set_normalizes_list_tags(self):
        cache = RedisLikeCache(max_size=100)
        cache._background_tasks_started = True
        await cache.set("k1", "v1", tags=["tag1", "tag2"])
        entry = cache._cache["k1"]
        assert isinstance(entry.tags, set)
        assert "tag1" in entry.tags

    @pytest.mark.asyncio
    async def test_set_normalizes_tuple_tags(self):
        cache = RedisLikeCache(max_size=100)
        cache._background_tasks_started = True
        await cache.set("k1", "v1", tags=("x", "y"))
        entry = cache._cache["k1"]
        assert isinstance(entry.tags, set)
        assert "x" in entry.tags


# ---------------------------------------------------------------------------
# Pipeline operations
# ---------------------------------------------------------------------------

class TestPipelineOperations:
    @pytest.mark.asyncio
    async def test_pipeline_set_and_get(self):
        cache = RedisLikeCache(max_size=100)
        cache._background_tasks_started = True
        ops = [
            {"type": "set", "key": "p1", "value": "hello"},
            {"type": "set", "key": "p2", "value": "world"},
            {"type": "get", "key": "p1"},
        ]
        results = await cache.pipeline_execute(ops)
        assert results[0] is True
        assert results[1] is True
        assert results[2] == "hello"

    @pytest.mark.asyncio
    async def test_pipeline_unknown_op(self):
        cache = RedisLikeCache(max_size=100)
        ops = [{"type": "unknown", "key": "x"}]
        results = await cache.pipeline_execute(ops)
        assert results[0] is None


# ---------------------------------------------------------------------------
# Cache warming and prefetch
# ---------------------------------------------------------------------------

class TestCacheWarming:
    @pytest.mark.asyncio
    async def test_warm_cache_loads_data(self):
        cache = RedisLikeCache(max_size=100)
        cache._background_tasks_started = True

        async def loader():
            return {"fresh": "data"}

        result = await cache.warm_cache("key1", loader)
        assert result is True
        assert await cache.get("key1") == {"fresh": "data"}

    @pytest.mark.asyncio
    async def test_warm_cache_skips_if_already_warming(self):
        cache = RedisLikeCache(max_size=100)
        cache._warming_tasks.add("key1")

        async def loader():
            return "data"

        result = await cache.warm_cache("key1", loader)
        assert result is False

    @pytest.mark.asyncio
    async def test_warm_cache_handles_loader_error(self):
        cache = RedisLikeCache(max_size=100)

        async def bad_loader():
            raise RuntimeError("failed")

        result = await cache.warm_cache("key1", bad_loader)
        assert result is False
        assert "key1" not in cache._warming_tasks

    @pytest.mark.asyncio
    async def test_prefetch_loads_subset(self):
        cache = RedisLikeCache(max_size=100)
        cache._background_tasks_started = True

        async def loader(keys):
            return {"k1": "v1", "k2": "v2"}

        count = await cache.prefetch(["k1", "k2", "k3"], loader)
        assert count == 2
        assert await cache.get("k1") == "v1"
        assert await cache.get("k3") is None

    @pytest.mark.asyncio
    async def test_prefetch_handles_error(self):
        cache = RedisLikeCache(max_size=100)

        async def bad_loader(keys):
            raise RuntimeError("oops")

        count = await cache.prefetch(["k1"], bad_loader)
        assert count == 0


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------

