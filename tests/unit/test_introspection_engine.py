"""Unit tests for ToolIntrospectionEngine — caching, registration, metadata retrieval."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.introspection.engine import ToolIntrospectionEngine
from src.revenium_mcp_server.introspection.metadata import ToolMetadata, MetadataProvider


def _make_metadata(name: str = "test_tool") -> ToolMetadata:
    """Create a minimal ToolMetadata for testing."""
    return MagicMock(
        spec=ToolMetadata,
        name=name,
        dependencies=[],
        capabilities=[],
    )


def _make_provider(metadata: ToolMetadata = None) -> MetadataProvider:
    """Create a mock MetadataProvider."""
    provider = MagicMock(spec=MetadataProvider)
    provider.get_tool_metadata = AsyncMock(return_value=metadata or _make_metadata())
    provider.update_performance_metrics = AsyncMock()
    return provider


class TestToolRegistration:

    @pytest.mark.asyncio
    async def test_register_tool_adds_to_registry(self):
        engine = ToolIntrospectionEngine()
        provider = _make_provider()
        await engine.register_tool("my_tool", provider)
        tools = await engine.list_tools()
        assert "my_tool" in tools

    @pytest.mark.asyncio
    async def test_register_tool_clears_stale_cache(self):
        engine = ToolIntrospectionEngine()
        provider = _make_provider()
        # Simulate existing cache
        engine._metadata_cache["my_tool"] = _make_metadata()
        engine._last_cache_update["my_tool"] = datetime.now()

        await engine.register_tool("my_tool", provider)
        assert "my_tool" not in engine._metadata_cache


class TestGetToolMetadata:

    @pytest.mark.asyncio
    async def test_returns_metadata_from_provider(self):
        engine = ToolIntrospectionEngine()
        metadata = _make_metadata("tool_a")
        provider = _make_provider(metadata)
        await engine.register_tool("tool_a", provider)

        result = await engine.get_tool_metadata("tool_a")
        assert result is metadata

    @pytest.mark.asyncio
    async def test_caches_metadata(self):
        engine = ToolIntrospectionEngine()
        metadata = _make_metadata("tool_b")
        provider = _make_provider(metadata)
        await engine.register_tool("tool_b", provider)

        # First call -> cache miss
        await engine.get_tool_metadata("tool_b")
        # Second call -> cache hit
        await engine.get_tool_metadata("tool_b")

        assert engine._cache_stats["hits"] >= 1
        assert engine._cache_stats["misses"] >= 1

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_tool(self):
        engine = ToolIntrospectionEngine()
        result = await engine.get_tool_metadata("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_provider_returns_none(self):
        engine = ToolIntrospectionEngine()
        provider = MagicMock(spec=MetadataProvider)
        provider.get_tool_metadata = AsyncMock(return_value=None)
        provider.update_performance_metrics = AsyncMock()
        await engine.register_tool("null_tool", provider)
        result = await engine.get_tool_metadata("null_tool")
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_provider_exception(self):
        engine = ToolIntrospectionEngine()
        provider = MagicMock(spec=MetadataProvider)
        provider.get_tool_metadata = AsyncMock(side_effect=RuntimeError("provider crash"))
        await engine.register_tool("bad_tool", provider)
        result = await engine.get_tool_metadata("bad_tool")
        assert result is None


class TestCacheValidation:

    @pytest.mark.asyncio
    async def test_expired_cache_is_invalid(self):
        engine = ToolIntrospectionEngine()
        engine._metadata_cache["old_tool"] = _make_metadata()
        engine._last_cache_update["old_tool"] = datetime.now() - timedelta(seconds=120)
        assert await engine._is_cache_valid("old_tool") is False

    @pytest.mark.asyncio
    async def test_fresh_cache_is_valid(self):
        engine = ToolIntrospectionEngine()
        engine._metadata_cache["new_tool"] = _make_metadata()
        engine._last_cache_update["new_tool"] = datetime.now()
        assert await engine._is_cache_valid("new_tool") is True

    @pytest.mark.asyncio
    async def test_missing_cache_is_invalid(self):
        engine = ToolIntrospectionEngine()
        assert await engine._is_cache_valid("missing") is False


class TestClearCache:

    @pytest.mark.asyncio
    async def test_clear_specific_tool(self):
        engine = ToolIntrospectionEngine()
        engine._metadata_cache["tool_x"] = _make_metadata()
        engine._last_cache_update["tool_x"] = datetime.now()
        engine._metadata_cache["tool_y"] = _make_metadata()
        engine._last_cache_update["tool_y"] = datetime.now()

        await engine.clear_cache("tool_x")
        assert "tool_x" not in engine._metadata_cache
        assert "tool_y" in engine._metadata_cache

    @pytest.mark.asyncio
    async def test_clear_all(self):
        engine = ToolIntrospectionEngine()
        engine._metadata_cache["a"] = _make_metadata()
        engine._last_cache_update["a"] = datetime.now()
        engine._metadata_cache["b"] = _make_metadata()
        engine._last_cache_update["b"] = datetime.now()

        await engine.clear_cache()
        assert len(engine._metadata_cache) == 0


class TestGetToolDependencies:

    @pytest.mark.asyncio
    async def test_returns_dependency_names(self):
        engine = ToolIntrospectionEngine()
        dep = MagicMock()
        dep.tool_name = "dep_tool"
        metadata = _make_metadata()
        metadata.dependencies = [dep]
        provider = _make_provider(metadata)
        await engine.register_tool("has_deps", provider)

        deps = await engine.get_tool_dependencies("has_deps")
        assert deps == ["dep_tool"]

    @pytest.mark.asyncio
    async def test_returns_empty_for_unknown(self):
        engine = ToolIntrospectionEngine()
        assert await engine.get_tool_dependencies("nope") == []


class TestUpdatePerformance:

    @pytest.mark.asyncio
    async def test_invalidates_cache_on_update(self):
        engine = ToolIntrospectionEngine()
        provider = _make_provider()
        await engine.register_tool("perf_tool", provider)

        # Populate cache
        await engine.get_tool_metadata("perf_tool")
        assert "perf_tool" in engine._metadata_cache

        # Update performance
        await engine.update_tool_performance("perf_tool", 150.0, True)

        # Cache should be invalidated
        assert "perf_tool" not in engine._metadata_cache
        assert engine._cache_stats["invalidations"] >= 1


class TestGetCacheStats:

    def test_cache_stats_initial(self):
        engine = ToolIntrospectionEngine()
        stats = engine.get_cache_stats()
        assert stats["cache_hits"] == 0
        assert stats["cache_misses"] == 0
        assert stats["hit_rate_percent"] == 0
        assert stats["cache_ttl_seconds"] == 60

    @pytest.mark.asyncio
    async def test_cache_stats_after_activity(self):
        engine = ToolIntrospectionEngine()
        provider = _make_provider()
        await engine.register_tool("stats_tool", provider)

        await engine.get_tool_metadata("stats_tool")  # miss
        await engine.get_tool_metadata("stats_tool")  # hit

        stats = engine.get_cache_stats()
        assert stats["cache_misses"] >= 1
        assert stats["cache_hits"] >= 1
        assert stats["hit_rate_percent"] > 0
