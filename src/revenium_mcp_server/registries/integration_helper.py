"""Integration helper for business management registry.

This module provides integration functions to connect the business management
registry with the enhanced_server.py, enabling seamless transition from
individual functions to registry-based management.
"""

from dataclasses import asdict
from typing import List, Union

from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..shared_parameters import CustomerRequest, ProductRequest, SourceRequest, SubscriptionRequest
from .business_management_registry import BusinessManagementRegistry

# Global registry instance
_business_registry = None


def get_business_registry() -> BusinessManagementRegistry:
    """Get or create the business management registry instance."""
    global _business_registry
    if _business_registry is None:
        _business_registry = BusinessManagementRegistry()
    return _business_registry


# Integration functions for enhanced_server.py
async def manage_products_via_registry(
    request: ProductRequest,
) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
    """Manage products via business registry (≤25 lines, ≤3 params)."""
    registry = get_business_registry()
    return await registry.manage_products(request)


async def manage_customers_via_registry(
    request: CustomerRequest,
) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
    """Manage customers via business registry (≤25 lines, ≤3 params)."""
    registry = get_business_registry()
    return await registry.manage_customers(request)


async def manage_subscriptions_via_registry(
    request: SubscriptionRequest,
) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
    """Manage subscriptions via business registry (≤25 lines, ≤3 params)."""
    registry = get_business_registry()
    return await registry.manage_subscriptions(request)


async def manage_sources_via_registry(
    request: SourceRequest,
) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
    """Manage sources via business registry (≤25 lines, ≤3 params)."""
    registry = get_business_registry()
    return await registry.manage_sources(request)
