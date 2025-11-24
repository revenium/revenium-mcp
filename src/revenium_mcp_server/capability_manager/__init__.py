"""Unified Capability Manager Package.

This package provides the Unified Capability Manager (UCM) architecture that serves as
the single source of truth for all API capabilities across the Revenium MCP server.

The UCM eliminates hardcoded validation layers and provides dynamic capability
verification against actual API endpoints.
"""

from .cache import CapabilityCache, CapabilityCacheManager
from .core import UnifiedCapabilityManager
from .discovery import CapabilityDiscovery
from .factory import UCMFactory, UCMIntegrationHelper
from .mcp_integration import MCPCapabilityIntegration
from .verification import CapabilityVerifier

__all__ = [
    "UnifiedCapabilityManager",
    "CapabilityVerifier",
    "CapabilityCache",
    "CapabilityCacheManager",
    "CapabilityDiscovery",
    "MCPCapabilityIntegration",
    "UCMFactory",
    "UCMIntegrationHelper",
]
