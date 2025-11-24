"""Tool Introspection Engine.

This module provides the central engine for managing tool metadata collection,
retrieval, and analysis across the MCP server.
"""

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from .metadata import MetadataProvider, ToolMetadata
from .registry import IntrospectionRegistry


class ToolIntrospectionEngine:
    """Central engine for tool introspection and metadata management."""

    def __init__(self):
        """Initialize the introspection engine with optimized caching."""
        self.registry = IntrospectionRegistry()
        self._metadata_cache: Dict[str, ToolMetadata] = {}
        self._cache_ttl_seconds = 60  # OPTIMIZATION: Reduced to 1 minute for faster cache refresh
        self._last_cache_update: Dict[str, datetime] = {}
        self._lock = asyncio.Lock()
        # OPTIMIZATION: Performance tracking for cache efficiency
        self._cache_stats = {"hits": 0, "misses": 0, "invalidations": 0}
        # OPTIMIZATION: Batch processing settings
        self._max_concurrent_metadata_requests = 20  # Limit concurrent requests

    async def register_tool(self, tool_name: str, provider: MetadataProvider) -> None:
        """Register a tool with the introspection engine.

        Args:
            tool_name: Name of the tool
            provider: Metadata provider instance
        """
        async with self._lock:
            await self.registry.register_provider(tool_name, provider)
            # Clear cache for this tool to force refresh
            if tool_name in self._metadata_cache:
                del self._metadata_cache[tool_name]
                del self._last_cache_update[tool_name]
            logger.info(f"Registered tool for introspection: {tool_name}")

    async def get_tool_metadata(self, tool_name: str) -> Optional[ToolMetadata]:
        """Get metadata for a specific tool with optimized caching.

        Args:
            tool_name: Name of the tool

        Returns:
            Tool metadata or None if not found
        """
        # OPTIMIZATION: Check cache first with performance tracking
        if await self._is_cache_valid(tool_name):
            self._cache_stats["hits"] += 1
            return self._metadata_cache.get(tool_name)

        # Cache miss - get from provider
        self._cache_stats["misses"] += 1
        provider = await self.registry.get_provider(tool_name)
        if not provider:
            logger.warning(f"No metadata provider found for tool: {tool_name}")
            return None

        try:
            metadata = await provider.get_tool_metadata()
            if metadata is None:
                logger.warning(f"Tool {tool_name} returned None metadata")
                return None

            async with self._lock:
                self._metadata_cache[tool_name] = metadata
                self._last_cache_update[tool_name] = datetime.now()

            logger.debug(f"Successfully cached metadata for tool {tool_name}")
            return metadata
        except Exception as e:
            logger.error(f"Error getting metadata for tool {tool_name}: {e}")
            # Log the full exception for debugging
            import traceback

            logger.debug(f"Full traceback for {tool_name} metadata error: {traceback.format_exc()}")
            return None

    async def list_tools(self) -> List[str]:
        """List all registered tool names.

        Returns:
            List of tool names
        """
        return await self.registry.list_tools()


    async def get_tool_dependencies(self, tool_name: str) -> List[str]:
        """Get dependencies for a specific tool.

        Args:
            tool_name: Name of the tool

        Returns:
            List of dependency tool names
        """
        metadata = await self.get_tool_metadata(tool_name)
        if not metadata:
            return []

        return [dep.tool_name for dep in metadata.dependencies]




    async def update_tool_performance(
        self, tool_name: str, execution_time_ms: float, success: bool
    ) -> None:
        """Update performance metrics for a tool with optimized non-blocking approach.

        Args:
            tool_name: Name of the tool
            execution_time_ms: Execution time in milliseconds
            success: Whether the execution was successful
        """
        provider = await self.registry.get_provider(tool_name)
        if provider:
            try:
                # OPTIMIZATION: Non-blocking performance update
                await provider.update_performance_metrics(execution_time_ms, success)
                # OPTIMIZATION: Efficient cache invalidation
                async with self._lock:
                    if tool_name in self._metadata_cache:
                        del self._metadata_cache[tool_name]
                        del self._last_cache_update[tool_name]
                        self._cache_stats["invalidations"] += 1
            except Exception as e:
                logger.error(f"Error updating performance metrics for {tool_name}: {e}")

    async def _is_cache_valid(self, tool_name: str) -> bool:
        """Check if cached metadata is still valid with optimized lock-free reads.

        PERFORMANCE OPTIMIZATION: Avoids lock contention by reading cache state
        without acquiring locks for validation checks.

        Args:
            tool_name: Name of the tool

        Returns:
            True if cache is valid, False otherwise
        """
        # OPTIMIZATION: Lock-free cache validation for better concurrency
        if tool_name not in self._metadata_cache:
            return False

        last_update = self._last_cache_update.get(tool_name)
        if not last_update:
            return False

        age_seconds = (datetime.now() - last_update).total_seconds()
        return age_seconds < self._cache_ttl_seconds

    async def clear_cache(self, tool_name: Optional[str] = None) -> None:
        """Clear metadata cache.

        Args:
            tool_name: Specific tool to clear, or None to clear all
        """
        async with self._lock:
            if tool_name:
                if tool_name in self._metadata_cache:
                    del self._metadata_cache[tool_name]
                    del self._last_cache_update[tool_name]
                    self._cache_stats["invalidations"] += 1
            else:
                self._metadata_cache.clear()
                self._last_cache_update.clear()
                self._cache_stats["invalidations"] += len(self._metadata_cache)

        logger.info(f"Cleared metadata cache for: {tool_name or 'all tools'}")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics.

        Returns:
            Dictionary containing cache performance metrics
        """
        total_requests = self._cache_stats["hits"] + self._cache_stats["misses"]
        hit_rate = (self._cache_stats["hits"] / total_requests * 100) if total_requests > 0 else 0

        return {
            "cache_hits": self._cache_stats["hits"],
            "cache_misses": self._cache_stats["misses"],
            "cache_invalidations": self._cache_stats["invalidations"],
            "hit_rate_percent": round(hit_rate, 2),
            "cached_tools": len(self._metadata_cache),
            "cache_ttl_seconds": self._cache_ttl_seconds,
        }



# Global introspection engine instance
introspection_engine = ToolIntrospectionEngine()
