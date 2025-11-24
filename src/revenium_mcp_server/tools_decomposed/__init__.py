"""MCP Tools Package.

This package contains all MCP tool implementations organized by functionality.
Each tool module handles a specific domain (products, subscriptions, sources, etc.).
"""

# Import consolidated management tools
from .alert_management import AlertManagement
from .customer_management import CustomerManagement
from .metering_elements_management import MeteringElementsManagement
from .metering_management import MeteringManagement

# Import product tools - UPDATED to use consolidated product management
from .product_management import ProductManagement

# Import source tools - UPDATED to use consolidated source management
from .source_management import SourceManagement

# Import subscription tools - UPDATED to use consolidated subscription management
from .subscription_management import SubscriptionManagement

# Import unified tool base class (legacy base classes removed)
from .unified_tool_base import ToolBase
from .workflow_management import WorkflowManagement

# Legacy base classes removed - use ToolBase only





# Performance monitoring tools removed - infrastructure monitoring handled externally

# Temporary backward compatibility import during decomposition
# Note: Removed circular import from ..tools to avoid import issues
# from ..tools import ReveniumTools

__all__ = [
    # Unified tool base class (recommended)
    "ToolBase",
    # Consolidated management tools
    "SourceManagement",
    "ProductManagement",
    "SubscriptionManagement",
    "AlertManagement",
    "CustomerManagement",
    "MeteringManagement",
    "MeteringElementsManagement",
    "WorkflowManagement",
    # Performance monitoring tools removed - infrastructure monitoring handled externally
]
