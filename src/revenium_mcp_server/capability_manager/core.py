"""Core Unified Capability Manager implementation.

This module contains the main UnifiedCapabilityManager class that serves as the
single source of truth for all API capabilities across the MCP server.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List

from ..client import ReveniumClient
from ..exceptions import ValidationError
from .cache import CapabilityCache
from .discovery import CapabilityDiscovery
from .verification import CapabilityVerifier

logger = logging.getLogger(__name__)


class UnifiedCapabilityManager:
    """Single source of truth for all API capabilities.

    The UCM provides centralized capability management with dynamic verification
    against actual API endpoints, eliminating hardcoded validation layers.
    """

    def __init__(self, client: ReveniumClient, cache_ttl: int = 3600):
        """Initialize the Unified Capability Manager.

        Args:
            client: Revenium API client for capability verification
            cache_ttl: Cache time-to-live in seconds (default: 1 hour)
        """
        self.client = client
        self.cache = CapabilityCache(ttl=cache_ttl)
        self.verifier = CapabilityVerifier(client)
        self.discovery = CapabilityDiscovery(client)

        # Track supported resource types
        self.supported_resource_types = {
            "system",
            "products",
            "subscriptions",
            "customers",
            "alerts",
            "sources",
            "metering_elements",
            "metering",
        }

        # Capability change listeners for MCP notifications
        self._change_listeners: List[Callable] = []

        # Circuit breaker state
        self._verification_failures: Dict[str, int] = {}
        self._max_failures = 3

        # Lock for thread safety
        self._lock = asyncio.Lock()

    async def get_capabilities(self, resource_type: str) -> Dict[str, Any]:
        """Get verified capabilities for a resource type.

        Args:
            resource_type: Type of resource (products, subscriptions, etc.)

        Returns:
            Dictionary containing verified capabilities

        Raises:
            ValidationError: If resource type is not supported
        """
        if resource_type not in self.supported_resource_types:
            raise ValidationError(
                message=f"Unsupported resource type: {resource_type}",
                field="resource_type",
                expected=f"One of: {', '.join(self.supported_resource_types)}",
            )

        # Check cache first
        cached_capabilities = await self.cache.get(resource_type)
        if cached_capabilities:
            logger.debug(f"Retrieved cached capabilities for {resource_type}")
            return cached_capabilities

        # Verify capabilities against API
        try:
            capabilities = await self._verify_and_cache_capabilities(resource_type)
            logger.info(f"Verified and cached capabilities for {resource_type}")
            return capabilities
        except Exception as e:
            logger.error(f"Failed to verify capabilities for {resource_type}: {e}")
            # Fall back to conservative defaults
            return await self._get_fallback_capabilities(resource_type)

    async def verify_capability(self, resource_type: str, capability: str) -> bool:
        """Verify a specific capability works with actual API.

        Args:
            resource_type: Type of resource
            capability: Specific capability to verify

        Returns:
            True if capability is verified, False otherwise
        """
        # Check circuit breaker
        failure_key = f"{resource_type}:{capability}"
        if self._verification_failures.get(failure_key, 0) >= self._max_failures:
            logger.warning(f"Circuit breaker open for {failure_key}")
            return False

        try:
            result = await self.verifier.verify_single_capability(resource_type, capability)

            # Reset failure count on success
            if result and failure_key in self._verification_failures:
                del self._verification_failures[failure_key]

            return result
        except Exception as e:
            # Increment failure count
            self._verification_failures[failure_key] = (
                self._verification_failures.get(failure_key, 0) + 1
            )
            logger.error(f"Capability verification failed for {failure_key}: {e}")
            return False

    async def refresh_capabilities(self) -> None:
        """Re-verify all capabilities against current API."""
        logger.info("Starting capability refresh for all resource types")

        async with self._lock:
            refresh_results = {}

            for resource_type in self.supported_resource_types:
                try:
                    # Clear cache for this resource type
                    await self.cache.invalidate(resource_type)

                    # Re-verify capabilities
                    capabilities = await self._verify_and_cache_capabilities(resource_type)
                    refresh_results[resource_type] = {
                        "status": "success",
                        "capabilities_count": len(capabilities),
                    }

                except Exception as e:
                    refresh_results[resource_type] = {"status": "failed", "error": str(e)}
                    logger.error(f"Failed to refresh capabilities for {resource_type}: {e}")

            # Notify listeners of capability changes
            await self._notify_capability_changes(refresh_results)

            logger.info(f"Capability refresh completed: {refresh_results}")

    async def add_change_listener(self, listener: Callable) -> None:
        """Add a listener for capability changes.

        Args:
            listener: Async callable that receives capability change notifications
        """
        self._change_listeners.append(listener)

    async def remove_change_listener(self, listener: Callable) -> None:
        """Remove a capability change listener.

        Args:
            listener: Listener to remove
        """
        if listener in self._change_listeners:
            self._change_listeners.remove(listener)

    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status of the capability manager.

        Returns:
            Dictionary containing health metrics
        """
        cache_stats = await self.cache.get_stats()

        return {
            "status": "healthy",
            "supported_resource_types": list(self.supported_resource_types),
            "cache_stats": cache_stats,
            "verification_failures": dict(self._verification_failures),
            "circuit_breakers_open": len(
                [k for k, v in self._verification_failures.items() if v >= self._max_failures]
            ),
            "change_listeners": len(self._change_listeners),
        }

    async def _verify_and_cache_capabilities(self, resource_type: str) -> Dict[str, Any]:
        """Verify capabilities and cache the results.

        Args:
            resource_type: Type of resource to verify

        Returns:
            Verified capabilities dictionary
        """
        # Discover capabilities from API
        discovered_capabilities = await self.discovery.discover_capabilities(resource_type)

        # Verify discovered capabilities
        verified_capabilities = await self.verifier.verify_capabilities(
            resource_type, discovered_capabilities
        )

        # Cache the verified capabilities
        await self.cache.set(resource_type, verified_capabilities)

        return verified_capabilities

    async def _get_fallback_capabilities(self, resource_type: str) -> Dict[str, Any]:
        """Get conservative fallback capabilities when verification fails.

        Args:
            resource_type: Type of resource

        Returns:
            Conservative capability set including manually set capabilities
        """
        logger.warning(f"Using fallback capabilities for {resource_type}")

        # Check if we have manually set capabilities in cache
        cached_capabilities = await self.cache.get(resource_type)
        if cached_capabilities:
            logger.info(f"Found manually set capabilities for {resource_type}, preserving them")
            return cached_capabilities

        # No manually set capabilities, return empty set
        logger.info(f"No capabilities available for {resource_type}")
        return {}

    async def _notify_capability_changes(self, changes: Dict[str, Any]) -> None:
        """Notify listeners of capability changes.

        Args:
            changes: Dictionary of capability changes by resource type
        """
        if not self._change_listeners:
            return

        notification = {"timestamp": datetime.utcnow().isoformat(), "changes": changes}

        for listener in self._change_listeners:
            try:
                await listener(notification)
            except Exception as e:
                logger.error(f"Failed to notify capability change listener: {e}")

    async def set_capability(self, resource_type: str, capability_name: str, value: str) -> None:
        """Set a capability value for a resource type.

        Args:
            resource_type: Type of resource
            capability_name: Name of the capability to set
            value: Value to set for the capability

        Raises:
            ValidationError: If resource type is not supported
        """
        if resource_type not in self.supported_resource_types:
            raise ValidationError(
                message=f"Unsupported resource type: {resource_type}",
                field="resource_type",
                expected=f"One of: {', '.join(self.supported_resource_types)}",
            )

        async with self._lock:
            try:
                # Get current capabilities from cache, or initialize empty if not cached
                current_capabilities = await self.cache.get(resource_type)
                if current_capabilities is None:
                    current_capabilities = {}

                # Update the capability value
                current_capabilities[capability_name] = value

                # Cache the updated capabilities
                await self.cache.set(resource_type, current_capabilities)

                logger.info(
                    f"Successfully set capability {capability_name}={value} for {resource_type}"
                )

                # Notify listeners of the capability change
                change_notification = {
                    resource_type: {
                        "status": "updated",
                        "capability": capability_name,
                        "new_value": value,
                    }
                }
                await self._notify_capability_changes(change_notification)

            except Exception as e:
                logger.error(
                    f"Failed to set capability {capability_name}={value} for {resource_type}: {e}"
                )
                raise

    async def get_resource_types(self) -> List[str]:
        """Get list of supported resource types.

        Returns:
            List of supported resource type names
        """
        return list(self.supported_resource_types)
