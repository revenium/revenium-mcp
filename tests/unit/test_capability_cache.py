"""Unit tests for capability_manager/cache.py.

Tests the CapabilityCache and CapabilityCacheManager classes which provide
TTL-based caching, cache warming, eviction, and automatic cleanup.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.revenium_mcp_server.capability_manager.cache import (
    CapabilityCache,
    CapabilityCacheManager,
)


@pytest.fixture
def cache():
    """Create a CapabilityCache with a short TTL for testing."""
    return CapabilityCache(ttl=60)


@pytest.fixture
def expired_cache():
    """Create a CapabilityCache with entries that are already expired."""
    c = CapabilityCache(ttl=1)  # 1 second TTL
    return c


class TestCapabilityCacheGetSet:
    """Test get/set round-trip behaviors."""

    @pytest.mark.asyncio
    async def test_set_then_get_returns_cached_data(self, cache):
        """Data stored via set() is retrievable via get()."""
        data = {"currencies": ["USD", "EUR"], "billing_models": ["subscription"]}
        await cache.set("products", data)
        result = await cache.get("products")
        assert result == data

    @pytest.mark.asyncio
    async def test_get_returns_copy_not_reference(self, cache):
        """get() returns a defensive copy so mutations don't affect cache."""
        data = {"key": "value"}
        await cache.set("test", data)
        result = await cache.get("test")
        result["key"] = "mutated"
        original = await cache.get("test")
        assert original["key"] == "value"

    @pytest.mark.asyncio
    async def test_set_stores_copy_not_reference(self, cache):
        """set() stores a defensive copy so external mutations don't affect cache."""
        data = {"key": "original"}
        await cache.set("test", data)
        data["key"] = "mutated"
        result = await cache.get("test")
        assert result["key"] == "original"

    @pytest.mark.asyncio
    async def test_get_missing_key_returns_none(self, cache):
        """get() returns None for keys that were never stored."""
        result = await cache.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_expired_entry_returns_none(self):
        """get() returns None after TTL expires."""
        cache = CapabilityCache(ttl=0)  # immediate expiry
        await cache.set("products", {"x": 1})
        # Force expiry by backdating the timestamp
        cache._timestamps["products"] = datetime.now(timezone.utc) - timedelta(seconds=10)
        result = await cache.get("products")
        assert result is None


class TestCapabilityCacheMetrics:
    """Test that cache tracks hits, misses, and evictions correctly."""

    @pytest.mark.asyncio
    async def test_miss_increments_on_absent_key(self, cache):
        """Cache miss is recorded when key doesn't exist."""
        await cache.get("missing")
        stats = await cache.get_stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 0

    @pytest.mark.asyncio
    async def test_hit_increments_on_present_key(self, cache):
        """Cache hit is recorded when key exists and is not expired."""
        await cache.set("k", {"v": 1})
        await cache.get("k")
        stats = await cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 0

    @pytest.mark.asyncio
    async def test_hit_rate_calculation(self, cache):
        """Hit rate is correctly calculated as percentage."""
        await cache.set("k", {"v": 1})
        await cache.get("k")       # hit
        await cache.get("k")       # hit
        await cache.get("missing") # miss
        stats = await cache.get_stats()
        # 2 hits, 1 miss => 66.67%
        assert stats["hit_rate_percent"] == pytest.approx(66.67, abs=0.01)

    @pytest.mark.asyncio
    async def test_stats_with_zero_requests(self, cache):
        """Hit rate is 0 when no requests have been made."""
        stats = await cache.get_stats()
        assert stats["hit_rate_percent"] == 0
        assert stats["cached_entries"] == 0


class TestCapabilityCacheInvalidation:
    """Test cache invalidation and clearing."""

    @pytest.mark.asyncio
    async def test_invalidate_existing_key_returns_true(self, cache):
        """invalidate() returns True and removes the entry."""
        await cache.set("k", {"v": 1})
        result = await cache.invalidate("k")
        assert result is True
        assert await cache.get("k") is None

    @pytest.mark.asyncio
    async def test_invalidate_missing_key_returns_false(self, cache):
        """invalidate() returns False for nonexistent keys."""
        result = await cache.invalidate("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_clear_removes_all_entries(self, cache):
        """clear() removes all cached entries."""
        await cache.set("a", {"v": 1})
        await cache.set("b", {"v": 2})
        await cache.clear()
        assert await cache.get("a") is None
        assert await cache.get("b") is None

    @pytest.mark.asyncio
    async def test_eviction_increments_counter(self, cache):
        """Evictions increment the evictions counter."""
        await cache.set("k", {"v": 1})
        await cache.invalidate("k")
        stats = await cache.get_stats()
        assert stats["evictions"] == 1


class TestCapabilityCacheCleanup:
    """Test cleanup_expired behavior."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_expired_entries(self):
        """cleanup_expired removes only expired entries."""
        cache = CapabilityCache(ttl=60)
        await cache.set("fresh", {"v": 1})
        await cache.set("stale", {"v": 2})
        # Backdate the stale entry
        cache._timestamps["stale"] = datetime.now(timezone.utc) - timedelta(seconds=120)
        removed = await cache.cleanup_expired()
        assert removed == 1
        assert await cache.get("fresh") is not None

    @pytest.mark.asyncio
    async def test_cleanup_returns_zero_when_nothing_expired(self, cache):
        """cleanup_expired returns 0 when no entries are expired."""
        await cache.set("fresh", {"v": 1})
        removed = await cache.cleanup_expired()
        assert removed == 0


class TestCapabilityCacheWarming:
    """Test cache warming (proactive refresh near expiry)."""

    @pytest.mark.asyncio
    async def test_warming_not_triggered_when_entry_is_fresh(self, cache):
        """Cache warming is not triggered for entries well within TTL."""
        await cache.set("k", {"v": 1})
        refresh_cb = AsyncMock(return_value={"v": 2})
        await cache.get("k", refresh_callback=refresh_cb)
        # Should not have called the callback
        refresh_cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_warming_triggered_when_near_expiry(self):
        """Cache warming triggers when entry age exceeds warming threshold."""
        cache = CapabilityCache(ttl=100)
        await cache.set("k", {"v": 1})
        # Backdate to 85% of TTL (past the 80% warming threshold)
        cache._timestamps["k"] = datetime.now(timezone.utc) - timedelta(seconds=85)
        refresh_cb = AsyncMock(return_value={"v": "refreshed"})
        result = await cache.get("k", refresh_callback=refresh_cb)
        # Original data should be returned (warming is async background)
        assert result == {"v": 1}
        # Give background task time to run
        await asyncio.sleep(0.1)
        refresh_cb.assert_called_once_with("k")

    @pytest.mark.asyncio
    async def test_warming_not_triggered_when_disabled(self):
        """Cache warming does not trigger when disabled."""
        cache = CapabilityCache(ttl=100)
        cache._warming_enabled = False
        await cache.set("k", {"v": 1})
        cache._timestamps["k"] = datetime.now(timezone.utc) - timedelta(seconds=85)
        refresh_cb = AsyncMock(return_value={"v": "refreshed"})
        await cache.get("k", refresh_callback=refresh_cb)
        await asyncio.sleep(0.05)
        refresh_cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_warming_failure_does_not_corrupt_cache(self):
        """If warming callback raises, existing data is preserved."""
        cache = CapabilityCache(ttl=100)
        await cache.set("k", {"v": "original"})
        cache._timestamps["k"] = datetime.now(timezone.utc) - timedelta(seconds=85)
        refresh_cb = AsyncMock(side_effect=RuntimeError("API down"))
        await cache.get("k", refresh_callback=refresh_cb)
        await asyncio.sleep(0.1)
        # Original data should still be there
        result = await cache.get("k")
        assert result == {"v": "original"}


class TestGetCacheStats:
    """Test the synchronous get_cache_stats method."""

    def test_initial_cache_stats(self, cache):
        """Initial stats reflect empty cache."""
        stats = cache.get_cache_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["cache_size"] == 0
        assert stats["warming_enabled"] is True
        assert stats["total_requests"] == 0
        assert stats["hit_rate_percent"] == 0


class TestCapabilityCacheManager:
    """Test CapabilityCacheManager start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_sets_running_state(self):
        """start() sets the running flag and creates a cleanup task."""
        cache = CapabilityCache(ttl=60)
        manager = CapabilityCacheManager(cache, cleanup_interval=300)
        await manager.start()
        assert manager._running is True
        assert manager._cleanup_task is not None
        await manager.stop()

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self):
        """Calling start() twice does not create duplicate tasks."""
        cache = CapabilityCache(ttl=60)
        manager = CapabilityCacheManager(cache, cleanup_interval=300)
        await manager.start()
        task1 = manager._cleanup_task
        await manager.start()  # second call
        assert manager._cleanup_task is task1  # same task
        await manager.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_cleanup_task(self):
        """stop() cancels the cleanup task and clears running flag."""
        cache = CapabilityCache(ttl=60)
        manager = CapabilityCacheManager(cache, cleanup_interval=300)
        await manager.start()
        await manager.stop()
        assert manager._running is False

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self):
        """Calling stop() when not running is a no-op."""
        cache = CapabilityCache(ttl=60)
        manager = CapabilityCacheManager(cache, cleanup_interval=300)
        await manager.stop()  # should not raise
        assert manager._running is False
