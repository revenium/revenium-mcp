"""Introspection Registry.

This module provides the registry for managing metadata providers
and tool introspection capabilities.
"""

import asyncio
from typing import Dict, List, Optional

from loguru import logger

from .metadata import MetadataProvider


class IntrospectionRegistry:
    """Registry for managing tool metadata providers."""

    def __init__(self):
        """Initialize the registry."""
        self._providers: Dict[str, MetadataProvider] = {}
        self._lock = asyncio.Lock()

    async def register_provider(self, tool_name: str, provider: MetadataProvider) -> None:
        """Register a metadata provider for a tool.

        Args:
            tool_name: Name of the tool
            provider: Metadata provider instance
        """
        async with self._lock:
            self._providers[tool_name] = provider
            logger.debug(f"Registered metadata provider for tool: {tool_name}")

    async def unregister_provider(self, tool_name: str) -> None:
        """Unregister a metadata provider.

        Args:
            tool_name: Name of the tool
        """
        async with self._lock:
            if tool_name in self._providers:
                del self._providers[tool_name]
                logger.debug(f"Unregistered metadata provider for tool: {tool_name}")

    async def get_provider(self, tool_name: str) -> Optional[MetadataProvider]:
        """Get the metadata provider registered for a tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Metadata provider or None if not found
        """
        return self._providers.get(tool_name)

    async def list_tools(self) -> List[str]:
        """List all registered tool names.

        Returns:
            List of tool names
        """
        return list(self._providers.keys())

    async def has_provider(self, tool_name: str) -> bool:
        """Check if a provider is registered for a tool.

        Args:
            tool_name: Name of the tool

        Returns:
            True if provider exists, False otherwise
        """
        return tool_name in self._providers

    async def clear(self) -> None:
        """Clear all registered providers."""
        async with self._lock:
            self._providers.clear()
            logger.debug("Cleared all metadata providers")
