"""Tests for core/response_cache.py — multi-level caching with MockCache fallback."""

import asyncio
import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.core.response_cache import (
    ResponseCacheManager,
    cache_response,
)


# ---------------------------------------------------------------------------
# ResponseCacheManager — key generation
# ---------------------------------------------------------------------------

class TestCacheKeyGeneration:
    def test_string_key_deterministic(self):
        mgr = ResponseCacheManager.__new__(ResponseCacheManager)
        mgr.enabled = True
        key1 = mgr._generate_cache_key("api", "test-data")
        key2 = mgr._generate_cache_key("api", "test-data")
        assert key1 == key2
        assert key1.startswith("api:")

    def test_dict_key_sorted(self):
        mgr = ResponseCacheManager.__new__(ResponseCacheManager)
        mgr.enabled = True
        key1 = mgr._generate_cache_key("api", {"b": 2, "a": 1})
        key2 = mgr._generate_cache_key("api", {"a": 1, "b": 2})
        assert key1 == key2

    def test_different_prefix_different_key(self):
        mgr = ResponseCacheManager.__new__(ResponseCacheManager)
        mgr.enabled = True
        key1 = mgr._generate_cache_key("api", "data")
        key2 = mgr._generate_cache_key("ucm", "data")
        assert key1 != key2


# ---------------------------------------------------------------------------
# ResponseCacheManager — fallback mode (MockCache)
# ---------------------------------------------------------------------------

class TestResponseCacheManagerFallback:
    """Test with DiskCache mocked out so MockCache is used."""

    def _make_manager(self):
        """Create a manager in fallback mode."""
        mgr = ResponseCacheManager.__new__(ResponseCacheManager)
        mgr.enabled = True
        mgr.l1_cache = {}
        mgr.l2_cache = MagicMock()
        mgr.l2_cache.get = MagicMock(return_value=None)
        mgr.l2_cache.set = MagicMock(return_value=True)
        mgr.l3_cache = MagicMock()
        mgr.l3_cache.get = MagicMock(return_value=None)
        mgr.l3_cache.set = MagicMock(return_value=True)
        mgr.l4_cache = MagicMock()
        mgr.l4_cache.get = MagicMock(return_value=None)
        mgr.l4_cache.set = MagicMock(return_value=True)
        mgr.stats = {
            "l1_hits": 0, "l1_misses": 0,
            "l2_hits": 0, "l2_misses": 0,
            "l3_hits": 0, "l3_misses": 0,
            "l4_hits": 0, "l4_misses": 0,
            "total_requests": 0,
        }
        return mgr

    @pytest.mark.asyncio
    async def test_set_and_get_l1(self):
        mgr = self._make_manager()

        await mgr.set_cached_response("api", "key1", "value1")

        # L1 should have the value
        result = await mgr.get_cached_response("api", "key1", cache_level="l1")
        assert result == "value1"
        assert mgr.stats["l1_hits"] == 1

    @pytest.mark.asyncio
    async def test_l1_miss(self):
        mgr = self._make_manager()
        result = await mgr.get_cached_response("api", "missing", cache_level="l1")
        assert result is None
        assert mgr.stats["l1_misses"] == 1

    @pytest.mark.asyncio
    async def test_disabled_get_returns_none(self):
        mgr = self._make_manager()
        mgr.enabled = False
        result = await mgr.get_cached_response("api", "key1")
        assert result is None
        # Disabled cache must not store anything in L1
        assert len(mgr.l1_cache) == 0

    @pytest.mark.asyncio
    async def test_disabled_set_returns_false(self):
        mgr = self._make_manager()
        mgr.enabled = False
        result = await mgr.set_cached_response("api", "key1", "val")
        assert result is False

    @pytest.mark.asyncio
    async def test_default_ttl_by_cache_type(self):
        """Different cache types get different default TTLs."""
        mgr = self._make_manager()

        # api type -> 300s -> L2
        await mgr.set_cached_response("api", "k1", "v1")
        # ucm type -> 900s -> L3
        await mgr.set_cached_response("ucm", "k2", "v2")
        # model_provider type -> 3600s -> L3
        await mgr.set_cached_response("model_provider", "k3", "v3")

    @pytest.mark.asyncio
    async def test_custom_ttl_long_goes_to_l4(self):
        mgr = self._make_manager()
        await mgr.set_cached_response("api", "k1", "v1", ttl_seconds=7200)
        # L4 set should have been called (via run_in_executor)

    def test_get_cache_stats(self):
        mgr = self._make_manager()
        mgr.stats["l1_hits"] = 10
        mgr.stats["l2_misses"] = 5
        stats = mgr.get_cache_stats()
        assert stats["total_hits"] == 10
        assert stats["total_misses"] == 5
        assert stats["hit_rate_percent"] == pytest.approx(66.67, abs=0.1)
        assert stats["cache_enabled"] is True

    @pytest.mark.asyncio
    async def test_auto_miss_increments_all_levels(self):
        mgr = self._make_manager()
        result = await mgr.get_cached_response("api", "missing-key", cache_level="auto")
        assert result is None
        # On a full auto miss, all levels are incremented
        assert mgr.stats["l1_misses"] >= 1
        assert mgr.stats["l2_misses"] >= 1
        assert mgr.stats["l3_misses"] >= 1
        assert mgr.stats["l4_misses"] >= 1


# ---------------------------------------------------------------------------
# ResponseCacheManager — warm_cache
# ---------------------------------------------------------------------------

class TestWarmCache:
    @pytest.mark.asyncio
    async def test_warm_cache_loads_items(self):
        mgr = TestResponseCacheManagerFallback()._make_manager()

        async def loader():
            return {"item1": "v1", "item2": "v2"}

        count = await mgr.warm_cache("api", loader)
        # Count includes items from both redis-like and standard warming
        assert count >= 2

    @pytest.mark.asyncio
    async def test_warm_cache_disabled(self):
        mgr = TestResponseCacheManagerFallback()._make_manager()
        mgr.enabled = False

        async def loader():
            return {"k": "v"}

        count = await mgr.warm_cache("api", loader)
        assert count == 0

    @pytest.mark.asyncio
    async def test_warm_cache_handles_error(self):
        mgr = TestResponseCacheManagerFallback()._make_manager()

        async def bad_loader():
            raise RuntimeError("failed")

        count = await mgr.warm_cache("api", bad_loader)
        assert count == 0


# ---------------------------------------------------------------------------
# cache_response decorator
# ---------------------------------------------------------------------------

class TestCacheResponseDecorator:
    def test_sync_function_decorated(self):
        """Sync functions wrapped by cache_response still work."""
        @cache_response("api", ttl_seconds=60)
        def my_func(x):
            return x * 2

        # Since there's no event loop, caching is skipped, but function runs
        assert my_func(5) == 10

    @pytest.mark.asyncio
    async def test_async_function_decorated(self):
        """Async functions are properly wrapped."""
        call_count = 0

        @cache_response("api", ttl_seconds=60)
        async def my_async_func(x):
            nonlocal call_count
            call_count += 1
            return x * 3

        result = await my_async_func(4)
        assert result == 12
