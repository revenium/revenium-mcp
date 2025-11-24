"""Tool registry for dynamic tool description lookup.

This module provides utilities for accessing tool metadata from the single
source of truth (tool classes) to support the dynamic MCP tool description
architecture.
"""

import logging
from typing import Any, Dict, List, Optional, Type

from .unified_tool_base import ToolBase

logger = logging.getLogger(__name__)


def get_tool_description(tool_name: str) -> str:
    """Get tool description from tool class registry.

    Args:
        tool_name: Name of the tool to get description for

    Returns:
        Tool description string, or fallback if not found
    """
    try:
        tool_class = _get_tool_class(tool_name)
        if tool_class and hasattr(tool_class, "tool_description"):
            return tool_class.tool_description
        else:
            logger.warning(f"Tool class {tool_name} missing tool_description property")
            return f"Tool: {tool_name} (description unavailable)"
    except Exception as e:
        logger.warning(f"Could not get description for {tool_name}: {e}")
        return f"Tool: {tool_name} (description unavailable)"


def get_tool_business_category(tool_name: str) -> str:
    """Get business category for tool.

    Args:
        tool_name: Name of the tool to get category for

    Returns:
        Business category string, or default if not found
    """
    try:
        tool_class = _get_tool_class(tool_name)
        if tool_class and hasattr(tool_class, "business_category"):
            return tool_class.business_category
        else:
            return "Miscellaneous Tools"
    except Exception as e:
        logger.warning(f"Could not get business category for {tool_name}: {e}")
        return "Miscellaneous Tools"


def get_tools_by_category() -> Dict[str, List[Type[ToolBase]]]:
    """Get all tools organized by business category.

    Returns:
        Dictionary mapping category names to lists of tool classes
    """
    try:
        tool_registry = _get_tool_registry()
        categories: Dict[str, List[Type[ToolBase]]] = {}

        for tool_class in tool_registry.values():
            if tool_class and hasattr(tool_class, "business_category"):
                category = tool_class.business_category
                if category not in categories:
                    categories[category] = []
                categories[category].append(tool_class)

        return categories
    except Exception as e:
        logger.error(f"Error organizing tools by category: {e}")
        return {}


def _get_tool_class(tool_name: str) -> Optional[Type[ToolBase]]:
    """Get tool class by name from registry.

    Args:
        tool_name: Name of the tool

    Returns:
        Tool class or None if not found
    """
    tool_registry = _get_tool_registry()
    return tool_registry.get(tool_name)


def _get_tool_registry() -> Dict[str, Type[ToolBase]]:
    """Get the complete tool registry mapping tool names to classes.

    Returns:
        Dictionary mapping tool names to tool classes

    Note:
        This function will be populated with imports as we convert each tool.
        Starting with imports for converted tools only.
    """
    registry = {}

    # Import and register converted tool classes
    # Note: We'll add imports here as we convert each tool

    try:
        # Alert management (first converted tool)
        from .alert_management import AlertManagement

        registry["manage_alerts"] = AlertManagement
    except ImportError:
        pass  # Tool not converted yet

    try:
        # Group 1 tools
        from .product_management import ProductManagement

        registry["manage_products"] = ProductManagement
    except ImportError:
        pass

    try:
        from .subscription_management import SubscriptionManagement

        registry["manage_subscriptions"] = SubscriptionManagement
    except ImportError:
        pass

    try:
        from .customer_management import CustomerManagement

        registry["manage_customers"] = CustomerManagement
    except ImportError:
        pass

    try:
        from .source_management import SourceManagement

        registry["manage_sources"] = SourceManagement
    except ImportError:
        pass

    try:
        from .metering_elements_management import MeteringElementsManagement

        registry["manage_metering_elements"] = MeteringElementsManagement
    except ImportError:
        pass

    try:
        # Group 2 tools
        from .metering_management import MeteringManagement

        registry["manage_metering"] = MeteringManagement
    except ImportError:
        pass



    try:
        from .business_analytics_management import BusinessAnalyticsManagement

        registry["business_analytics_management"] = BusinessAnalyticsManagement
    except ImportError:
        pass

    try:
        from .workflow_management import WorkflowManagement

        registry["manage_workflows"] = WorkflowManagement
    except ImportError:
        pass

    try:
        from .subscriber_credentials_management import SubscriberCredentialsManagement

        registry["manage_subscriber_credentials"] = SubscriberCredentialsManagement
    except ImportError:
        pass

    try:
        from .manage_capabilities import ManageCapabilities

        registry["manage_capabilities"] = ManageCapabilities
    except ImportError:
        pass

    try:
        from .tool_introspection import ToolIntrospection

        registry["tool_introspection"] = ToolIntrospection
    except ImportError:
        pass

    # NOTE: revenium_log_analysis has been consolidated into system_diagnostics
    # The standalone tool is no longer registered to avoid phantom tool issues
    # All log analysis functionality is available through system_diagnostics:
    # - get_internal_logs
    # - get_integration_logs
    # - get_recent_logs
    # - search_logs
    # - analyze_operations

    # CONSOLIDATED TOOLS - These are the new unified tools that replace multiple individual tools
    try:
        from .slack_management import SlackManagement

        registry["slack_management"] = SlackManagement
    except ImportError:
        pass

    try:
        from .system_setup import SystemSetup

        registry["system_setup"] = SystemSetup
    except ImportError:
        pass

    try:
        from .system_diagnostics import SystemDiagnostics

        registry["system_diagnostics"] = SystemDiagnostics
    except ImportError:
        pass

    # REMOVED: simple_chart_test - caused mcptools deadlock, chart features not used in production

    return registry


def validate_tool_descriptions() -> Dict[str, Any]:
    """Validate that all registered tools have required metadata.

    Returns:
        Validation report with any issues found
    """
    tool_registry = _get_tool_registry()
    validation_report = {
        "total_tools": len(tool_registry),
        "valid_tools": 0,
        "missing_description": [],
        "missing_category": [],
        "issues": [],
    }

    for tool_name, tool_class in tool_registry.items():
        has_description = hasattr(tool_class, "tool_description") and tool_class.tool_description
        has_category = hasattr(tool_class, "business_category") and tool_class.business_category

        if not has_description:
            validation_report["missing_description"].append(tool_name)

        if not has_category:
            validation_report["missing_category"].append(tool_name)

        if has_description and has_category:
            validation_report["valid_tools"] += 1
        else:
            validation_report["issues"].append(f"{tool_name}: missing required metadata")

    return validation_report
