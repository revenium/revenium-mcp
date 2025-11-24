"""Helper functions for MCP resource management.

This module contains helper functions extracted from the main resources module
to maintain compliance with the 300-line limit per module.
"""

from datetime import datetime
from typing import Any, Dict, List


def get_builtin_resource_definitions() -> List:
    """Get built-in resource definitions.

    Returns:
        List of built-in MCPResource instances
    """
    # Import here to avoid circular imports
    from .resources import MCPResource, ResourceMimeType, ResourceType

    return [
        # Analytics Resources
        MCPResource(
            uri="revenium://analytics/cost-trends",
            name="Cost Trends Analysis",
            description="Historical cost analysis and trending data for AI transactions",
            mime_type=ResourceMimeType.JSON,
            resource_type=ResourceType.ANALYTICS,
            annotations={
                "category": "financial",
                "update_frequency": "hourly",
                "data_retention": "90_days",
            },
        ),
        MCPResource(
            uri="revenium://analytics/usage-patterns",
            name="Usage Patterns Analysis",
            description="AI usage pattern analysis and optimization recommendations",
            mime_type=ResourceMimeType.JSON,
            resource_type=ResourceType.ANALYTICS,
            annotations={
                "category": "operational",
                "update_frequency": "daily",
                "includes_predictions": True,
            },
        ),
        MCPResource(
            uri="revenium://analytics/performance-metrics",
            name="Performance Metrics",
            description="Real-time performance metrics and KPIs for AI operations",
            mime_type=ResourceMimeType.JSON,
            resource_type=ResourceType.ANALYTICS,
            annotations={
                "category": "performance",
                "update_frequency": "real_time",
                "metrics_included": ["latency", "throughput", "error_rate"],
            },
        ),
        # Transaction Resources
        MCPResource(
            uri="revenium://transactions/recent",
            name="Recent AI Transactions",
            description="Latest AI transaction data with detailed metadata",
            mime_type=ResourceMimeType.JSON,
            resource_type=ResourceType.TRANSACTIONS,
            annotations={
                "category": "operational",
                "update_frequency": "real_time",
                "max_records": 1000,
            },
        ),
        MCPResource(
            uri="revenium://transactions/summary",
            name="Transaction Summary",
            description="Aggregated transaction summary with key statistics",
            mime_type=ResourceMimeType.JSON,
            resource_type=ResourceType.TRANSACTIONS,
            annotations={
                "category": "summary",
                "update_frequency": "hourly",
                "aggregation_period": "24_hours",
            },
        ),
        # Alert Resources
        MCPResource(
            uri="revenium://alerts/active",
            name="Active Alerts",
            description="Currently active alerts and their status",
            mime_type=ResourceMimeType.JSON,
            resource_type=ResourceType.ALERTS,
            annotations={
                "category": "monitoring",
                "update_frequency": "real_time",
                "severity_levels": ["low", "medium", "high", "critical"],
            },
        ),
        MCPResource(
            uri="revenium://alerts/history",
            name="Alert History",
            description="Historical alert data and resolution patterns",
            mime_type=ResourceMimeType.JSON,
            resource_type=ResourceType.ALERTS,
            annotations={
                "category": "historical",
                "update_frequency": "daily",
                "retention_period": "30_days",
            },
        ),
        # Report Resources
        MCPResource(
            uri="revenium://reports/executive-summary",
            name="Executive Summary Report",
            description="High-level executive summary of AI operations and costs",
            mime_type=ResourceMimeType.HTML,
            resource_type=ResourceType.REPORTS,
            annotations={
                "category": "executive",
                "update_frequency": "daily",
                "format": "executive_dashboard",
            },
        ),
        MCPResource(
            uri="revenium://reports/cost-optimization",
            name="Cost Optimization Report",
            description="Detailed cost optimization recommendations and savings opportunities",
            mime_type=ResourceMimeType.MARKDOWN,
            resource_type=ResourceType.REPORTS,
            annotations={
                "category": "optimization",
                "update_frequency": "weekly",
                "includes_recommendations": True,
            },
        ),
        # Dashboard Resources
        MCPResource(
            uri="revenium://dashboards/real-time",
            name="Real-time Operations Dashboard",
            description="Live dashboard data for real-time AI operations monitoring",
            mime_type=ResourceMimeType.JSON,
            resource_type=ResourceType.DASHBOARDS,
            annotations={
                "category": "real_time",
                "update_frequency": "real_time",
                "refresh_interval": "30_seconds",
            },
        ),
    ]


def generate_mock_content_by_type(resource) -> Dict[str, Any]:
    """Generate mock content based on resource type.

    Args:
        resource: Resource to generate content for

    Returns:
        Mock content dictionary
    """
    # Import here to avoid circular imports
    from .resources import ResourceType

    if resource.resource_type == ResourceType.ANALYTICS:
        return _generate_analytics_content()
    elif resource.resource_type == ResourceType.TRANSACTIONS:
        return _generate_transaction_content()
    elif resource.resource_type == ResourceType.ALERTS:
        return _generate_alert_content()
    else:
        return _generate_default_content(resource)


def _generate_analytics_content() -> Dict[str, Any]:
    """Generate analytics mock content."""
    return {
        "timestamp": datetime.now().isoformat(),
        "metrics": {
            "total_cost": 1250.75,
            "transaction_count": 15420,
            "average_cost_per_transaction": 0.081,
            "cost_trend": "increasing",
            "efficiency_score": 87.3,
        },
        "trends": [
            {"date": "2025-06-20", "cost": 1180.50, "transactions": 14200},
            {"date": "2025-06-21", "cost": 1250.75, "transactions": 15420},
        ],
    }


def _generate_transaction_content() -> Dict[str, Any]:
    """Generate transaction mock content."""
    return {
        "timestamp": datetime.now().isoformat(),
        "transactions": [
            {
                "id": "tx_001",
                "timestamp": "2025-06-21T12:30:00Z",
                "model": "gpt-4",
                "cost": 0.12,
                "tokens": 1500,
                "status": "completed",
            },
            {
                "id": "tx_002",
                "timestamp": "2025-06-21T12:29:45Z",
                "model": "gpt-3.5-turbo",
                "cost": 0.05,
                "tokens": 800,
                "status": "completed",
            },
        ],
        "summary": {"total_transactions": 2, "total_cost": 0.17, "average_cost": 0.085},
    }


def _generate_alert_content() -> Dict[str, Any]:
    """Generate alert mock content."""
    return {
        "timestamp": datetime.now().isoformat(),
        "active_alerts": [
            {
                "id": "alert_001",
                "severity": "medium",
                "title": "Cost threshold exceeded",
                "description": "Daily cost has exceeded $1000 threshold",
                "created_at": "2025-06-21T10:00:00Z",
                "status": "active",
            }
        ],
        "alert_summary": {
            "total_active": 1,
            "by_severity": {"low": 0, "medium": 1, "high": 0, "critical": 0},
        },
    }


def _generate_default_content(resource) -> Dict[str, Any]:
    """Generate default mock content."""
    return {
        "timestamp": datetime.now().isoformat(),
        "resource_type": resource.resource_type.value,
        "message": f"Mock content for {resource.name}",
        "data": {"placeholder": True},
    }
