"""Consolidated Alert Management Tool.

This module provides comprehensive alert and anomaly management functionality
by consolidating the previous dual-layer architecture into a single, unified tool.

Combines functionality from:
- enhanced_alert_tools.py (metadata provider, natural language processing)
- alert_tools.py (business logic, API interactions)
- alert_bulk_methods.py (bulk operations)
- alert_enable_disable_methods.py (enable/disable operations)

Follows MCP best practices:
- Single responsibility: All alert functionality in one place
- Direct implementation: No delegation patterns
- Clear entry points: Unified routing and error handling
"""

import json
from typing import Any, Dict, List, Optional, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..alerts import AlertManager, AlertSemanticProcessor, AnalyticsEngine, AnomalyManager
from ..client import ReveniumAPIError, ReveniumClient
from ..common.error_handling import (
    ErrorCodes,
    ResourceError,
    ToolError,
    create_structured_missing_parameter_error,
    create_structured_validation_error,
    format_structured_error,
)
from ..common.pagination_performance import validate_pagination_with_performance
from ..common.ucm_config import log_ucm_status
from ..exceptions import ValidationError
from ..introspection.metadata import (
    DependencyType,
    ResourceRelationship,
    ToolCapability,
    ToolDependency,
    ToolType,
    UsagePattern,
)
from ..mixins.slack_prompting_mixin import SlackPromptingMixin
from ..models import MetricType
from ..schema.alert_schema import get_alert_metrics_capabilities
from .unified_tool_base import ToolBase


class AlertManagement(ToolBase, SlackPromptingMixin):
    """Consolidated alert and anomaly management tool.

    Provides comprehensive alert management functionality including:
    - AI anomaly detection and management
    - Alert querying and investigation
    - Natural language processing for alert creation
    - Bulk operations for enable/disable
    - Analytics and metrics
    - Metadata provider capabilities
    """

    tool_name = "manage_alerts"
    tool_description = "AI spending alerts and anomaly monitoring with three alert types: (1) Spike Detection - create_threshold_alert for real-time monitoring, (2) Budget Threshold - create_cumulative_usage_alert for period tracking, (3) Relative Change - create with alertType RELATIVE_CHANGE and INCREASES_BY/DECREASES_BY operators for trend detection. Supports persistence-based triggering with triggerAfterPersistsDuration. Use get_examples() for comprehensive usage guidance."
    business_category = "Revenium Cost Alert Functionality"
    tool_type = ToolType.ANALYTICS
    tool_version = "2.0.0"

    def __init__(self, ucm_helper=None) -> None:
        """Initialize the consolidated alert management tool.

        Args:
            ucm_helper: UCM integration helper for capability management
        """
        super().__init__(ucm_helper)

        # Initialize core managers
        self.anomaly_manager = AnomalyManager()
        self.alert_manager = AlertManager()
        self.semantic_processor = AlertSemanticProcessor()
        self.analytics_engine = AnalyticsEngine()
        self.formatter = UnifiedResponseFormatter("manage_alerts")

    async def close(self):
        """Close the alert management tool and cleanup resources."""
        # Close any resources if needed
        pass

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle alert management actions with unified routing.

        Args:
            action: Action to perform
            arguments: Action arguments

        Returns:
            Formatted response
        """
        try:
            # Get client
            client = await self.get_client()

            # Route to appropriate handler based on action
            if action == "list":
                return await self._handle_list(client, arguments)
            elif action == "get":
                return await self._handle_get(client, arguments)
            elif action == "create":
                return await self._handle_create(client, arguments)
            elif action == "update":
                return await self._handle_update(client, arguments)
            elif action == "delete":
                return await self._handle_delete(client, arguments)
            elif action == "clear_all":
                return await self._handle_clear_all(client, arguments)
            elif action == "get_metrics":
                return await self._handle_get_metrics(client, arguments)
            elif action == "query":
                return await self._handle_query(client, arguments)
            elif action == "validate":
                return await self._handle_validate(client, arguments)
            elif action == "get_capabilities":
                return await self._handle_get_capabilities()
            elif action == "test_ucm_integration":
                return await self._handle_test_ucm_integration()
            elif action == "get_examples":
                return await self._handle_get_examples(arguments)
            elif action == "get_agent_summary":
                return await self._handle_get_agent_summary()
            elif action == "create_cumulative_usage_alert":
                return await self._handle_create_cumulative_usage_alert(client, arguments)
            elif action == "create_threshold_alert":
                return await self._handle_create_threshold_alert(client, arguments)
            elif action == "create_from_text":
                return await self._handle_create_from_text(client, arguments)
            elif action == "create_simple":
                return await self._handle_create_simple(client, arguments)
            elif action == "enable":
                return await self._handle_enable_anomaly(client, arguments)
            elif action == "disable":
                return await self._handle_disable_anomaly(client, arguments)
            elif action == "enable_multiple":
                return await self._handle_enable_multiple(client, arguments)
            elif action == "disable_multiple":
                return await self._handle_disable_multiple(client, arguments)
            elif action == "enable_all":
                return await self._handle_enable_all_anomalies(client, arguments)
            elif action == "disable_all":
                return await self._handle_disable_all_anomalies(client, arguments)
            elif action == "toggle_status":
                return await self._handle_toggle_anomaly_status(client, arguments)
            elif action == "get_status":
                return await self._handle_get_anomaly_status(client, arguments)
            else:
                # Use structured error for unknown action
                raise ToolError(
                    message=f"Unknown action '{action}' is not supported",
                    error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
                    field="action",
                    value=action,
                    suggestions=[
                        "IMPORTANT: Always start with get_capabilities() and get_examples() to understand alert types!",
                        "Use get_capabilities() to see all available actions",
                        "Use get_examples() to see working examples",
                        "Check the action name for typos",
                    ],
                    examples={
                        "discovery_actions": [
                            "get_capabilities",
                            "get_examples",
                            "get_agent_summary",
                        ],
                        "creation_actions": [
                            "create_threshold_alert",
                            "create_cumulative_usage_alert",
                            "create_from_text",
                        ],
                        "management_actions": ["list", "get", "update", "delete", "clear_all"],
                        "analysis_actions": ["get_metrics", "query", "validate"],
                        "bulk_operations": [
                            "enable_all",
                            "disable_all",
                            "enable_multiple",
                            "disable_multiple",
                        ],
                        "individual_control": ["enable", "disable", "toggle_status", "get_status"],
                    },
                )

        except ToolError as e:
            logger.error(f"Tool error in alert management: {e}")
            # Re-raise ToolError to be handled by standardized_tool_execution
            raise e
        except ReveniumAPIError as e:
            logger.error(f"Revenium API error in alert management: {e}")
            # Re-raise ReveniumAPIError to be handled by standardized_tool_execution
            raise e
        except Exception as e:
            logger.error(f"Unexpected error in alert management: {e}")
            # Re-raise Exception to be handled by standardized_tool_execution
            raise e

    # ============================================================================
    # METADATA PROVIDER IMPLEMENTATION (from enhanced_alert_tools.py)
    # ============================================================================

    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get alert tool capabilities with UCM integration for dynamic parameter validation."""
        # Get UCM capabilities for dynamic trigger duration values
        ucm_trigger_durations = None
        if self.ucm_helper:
            try:
                ucm_capabilities = await self.ucm_helper.ucm.get_capabilities("alerts")
                ucm_trigger_durations = (
                    ucm_capabilities.get("trigger_durations") if ucm_capabilities else None
                )
            except Exception:
                # Fall back to static values if UCM is not available
                pass

        # Build trigger duration documentation
        if ucm_trigger_durations:
            trigger_duration_doc = f"str (optional) - Duration alert condition must persist before triggering. Valid values (UCM-verified): {', '.join(ucm_trigger_durations)}"
        else:
            # Fall back to TriggerDuration enum values
            trigger_duration_doc = "str (optional) - Duration alert condition must persist before triggering. Valid values from TriggerDuration enum: ONE_MINUTE, FIVE_MINUTES, FIFTEEN_MINUTES, THIRTY_MINUTES, ONE_HOUR, TWELVE_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, DAILY, WEEKLY, MONTHLY, QUARTERLY"

        return [
            ToolCapability(
                name="AI Anomaly Detection",
                description="Create and manage AI-powered anomaly detection rules",
                parameters={
                    "resource_type": "str (anomalies, alerts)",
                    "create": {"anomaly_data": "dict"},
                    "update": {"anomaly_id": "str", "anomaly_data": "dict"},
                    "delete": {"anomaly_id": "str"},
                },
                examples=[
                    "create(resource_type='anomalies', anomaly_data={'metric': 'TOTAL_COST', 'threshold': 100})",
                    "update(anomaly_id='anom_123', anomaly_data={'threshold': 150})",
                ],
                limitations=[
                    "Requires valid metric types",
                    "Threshold values must be positive",
                    "Some metrics require specific configurations",
                ],
            ),
            ToolCapability(
                name="Alert Investigation",
                description="Query and analyze triggered alerts with natural language",
                parameters={
                    "resource_type": "str (alerts)",
                    "query": "str (natural language)",
                    "filters": "dict (date ranges, severity)",
                },
                examples=[
                    "query(resource_type='alerts', query='show high cost alerts from last week')",
                    "list(resource_type='alerts', filters={'severity': 'HIGH'})",
                ],
                limitations=[
                    "Natural language parsing is best-effort",
                    "Complex queries may need manual filters",
                ],
            ),
            ToolCapability(
                name="Enhanced Alert Creation",
                description="Simplified alert creation with Budget Threshold and Spike Detection methods, supporting all metric types and persistence-based triggering",
                parameters={
                    "create_cumulative_usage_alert (Budget Threshold)": {
                        "name": "str (required)",
                        "threshold": "float (required)",
                        "period": "str (required)",
                        "email": "str (required)",
                        "metric": "str (optional) - TOTAL_COST, TOKEN_COUNT, ERROR_RATE, etc.",
                        "triggerAfterPersistsDuration": trigger_duration_doc,
                    },
                    "create_threshold_alert (Spike Detection)": {
                        "name": "str (required)",
                        "threshold": "float (required)",
                        "period_minutes": "float (required)",
                        "email": "str (required)",
                        "metric": "str (optional) - TOTAL_COST, TOKEN_COUNT, ERROR_RATE, etc.",
                        "triggerAfterPersistsDuration": trigger_duration_doc,
                    },
                    "create_from_text": {
                        "text": "str (required) - Natural language description including metric type"
                    },
                    "Advanced Alert Configuration": {
                        "triggerAfterPersistsDuration": trigger_duration_doc
                    },
                },
                examples=[
                    "# Budget Threshold alerts - track usage over time periods",
                    "create_cumulative_usage_alert(name='Budget Alert', threshold=5000, period='monthly', email='admin@co.com')",
                    "create_cumulative_usage_alert(name='Token Budget', metric='TOKEN_COUNT', threshold=1000, period='monthly', email='admin@co.com')",
                    "# Spike Detection alerts - immediate threshold monitoring",
                    "create_threshold_alert(name='Error Spike', metric='ERROR_RATE', threshold=1, period_minutes=5, email='ops@co.com')",
                    "# Persistence-based alerting - only trigger if condition persists",
                    "create_threshold_alert(name='Sustained Cost Spike', threshold=100, period_minutes=5, email='ops@co.com', triggerAfterPersistsDuration='FIFTEEN_MINUTES')",
                    "create_from_text(text='Alert when monthly token count exceeds 1000')",
                ],
                limitations=[
                    "Email addresses are required for notifications",
                    "Period values must be valid (daily, weekly, monthly, quarterly)",
                    "create_threshold_alert now supports triggerAfterPersistsDuration parameter",
                    "create_cumulative_usage_alert does not support triggerAfterPersistsDuration (use create() action)",
                    "triggerAfterPersistsDuration works with periodDuration to create persistence-based alerting",
                    f"Valid metrics: {', '.join([metric.value for metric in MetricType])}",
                ],
            ),
        ]

    async def _get_supported_actions(self) -> List[str]:
        """Get supported actions."""
        return [
            "list",
            "get",
            "create",
            "update",
            "delete",
            "clear_all",
            "get_metrics",
            "query",
            "validate",
            "get_capabilities",
            "get_examples",
            "get_agent_summary",
            "create_cumulative_usage_alert",
            "create_threshold_alert",
            "create_from_text",
            "create_simple",
            "enable",
            "disable",
            "enable_multiple",
            "disable_multiple",
            "enable_all",
            "disable_all",
            "toggle_status",
            "get_status",
        ]

    async def _get_tool_dependencies(self) -> List[ToolDependency]:
        """Get tool dependencies."""
        return [
            ToolDependency(
                tool_name="revenium_api",
                dependency_type=DependencyType.REQUIRES,
                description="Revenium Platform API for anomaly and alert operations",
                required_version="v1",
                conditional=False,
            ),
            ToolDependency(
                tool_name="alert_semantic_processor",
                dependency_type=DependencyType.ENHANCES,
                description="Natural language processing for alert creation",
                required_version=None,
                conditional=True,
            ),
        ]

    async def _get_resource_relationships(self) -> List[ResourceRelationship]:
        """Get resource relationships."""
        return [
            ResourceRelationship(
                resource_type="anomalies",
                relationship_type="generates",
                description="Anomalies generate alerts when conditions are met",
                cardinality="1:N",
                optional=False,
            ),
            ResourceRelationship(
                resource_type="products",
                relationship_type="monitors",
                description="Alerts can monitor specific products",
                cardinality="N:N",
                optional=True,
            ),
            ResourceRelationship(
                resource_type="sources",
                relationship_type="tracks",
                description="Alerts can track metrics from specific sources",
                cardinality="N:N",
                optional=True,
            ),
        ]

    async def _get_usage_patterns(self) -> List[UsagePattern]:
        """Get usage patterns."""
        return [
            UsagePattern(
                pattern_name="Cost Monitoring Setup",
                description="Set up comprehensive cost monitoring alerts",
                frequency=0.2,  # Setup once, so low frequency
                typical_sequence=[
                    "get_capabilities()",
                    "create_threshold_alert()  # Spike Detection - real-time monitoring",
                    "create_cumulative_usage_alert()  # Budget Threshold - period tracking",
                    "list()",
                ],
                common_parameters={"threshold": "float", "email": "str", "metric": "TOTAL_COST"},
                success_indicators=[
                    "Alerts created successfully",
                    "Notifications configured",
                    "Alerts enabled and active",
                ],
            ),
            UsagePattern(
                pattern_name="Alert Investigation",
                description="Investigate triggered alerts and analyze patterns",
                frequency=0.8,  # Daily usage, high frequency
                typical_sequence=["query()", "get_metrics()", "list(resource_type='alerts')"],
                common_parameters={"query": "str", "resource_type": "alerts", "filters": "dict"},
                success_indicators=[
                    "Relevant alerts found",
                    "Patterns identified",
                    "Issues resolved",
                ],
            ),
        ]

    async def _get_agent_summary(self) -> str:
        """Get agent summary."""
        return """
Comprehensive AI anomaly detection and alert management for the Revenium platform. Create intelligent monitoring rules, investigate triggered alerts, and analyze patterns with advanced metrics and natural language querying.

**Key Features:**
• AI-powered anomaly detection with configurable thresholds
• Real-time alert monitoring and investigation
• Natural language alert querying and analysis
• Comprehensive metrics and analytics
• Integration with products, sources, and teams"""

    async def _get_quick_start_guide(self) -> List[str]:
        """Get quick start guide."""
        return [
            "**ALWAYS START HERE**: get_capabilities() - Understand alert types and required fields",
            "**See Examples**: get_examples(alert_type='budget_threshold'), get_examples(alert_type='spike_detection'), or get_examples(alert_type='relative_change')",
            "**Quick Creation**: create_cumulative_usage_alert() for budget tracking, create_threshold_alert() for spike detection, or create with alertType RELATIVE_CHANGE for trend detection",
            "**Investigation**: query(text='show alerts from last week') for natural language search",
            "**Analytics**: get_metrics() to analyze alert patterns and frequency",
        ]

    async def _get_common_use_cases(self) -> List[str]:
        """Get common use cases."""
        return [
            "Monthly budget tracking with Budget Threshold alerts",
            "Real-time cost spike detection with Spike Detection alerts",
            "Error rate monitoring for API reliability",
            "Token usage tracking for AI model consumption",
            "Performance monitoring with response time alerts",
        ]

    async def _get_troubleshooting_tips(self) -> List[str]:
        """Get troubleshooting tips."""
        return [
            "Always specify 'alertType' explicitly to avoid confusion between Spike Detection and Budget Threshold alerts",
            "Include notification email addresses - alerts without emails won't notify anyone",
            "Use get_capabilities() to see all available metrics before creating alerts",
            "For Budget Threshold alerts, specify the tracking period (daily, weekly, monthly, quarterly)",
            "Test alert configurations with validate() before creating them",
        ]

    async def _get_tool_tags(self) -> List[str]:
        """Get tool tags."""
        return ["analytics", "alerts", "monitoring", "anomalies", "ai"]

    def _detect_semantic_intent(self, arguments: Dict[str, Any]) -> str:
        """Detect semantic intent to help route between alerts (history) and anomalies (definitions)."""
        # Check if resource_type is explicitly specified
        resource_type = arguments.get("resource_type")
        if resource_type:
            return resource_type

        # Check for semantic clues in other parameters
        query = arguments.get("query", "").lower()
        action = arguments.get("action", "").lower()

        # Keywords that suggest historical alerts (events)
        history_keywords = [
            "history",
            "historical",
            "fired",
            "triggered",
            "events",
            "incidents",
            "recent",
            "last",
            "past",
            "occurred",
            "happened",
            "when",
            "timeline",
            "resolved",
            "active",
            "ongoing",
            "duration",
            "frequency",
        ]

        # Keywords that suggest alert definitions (rules)
        definition_keywords = [
            "rules",
            "definitions",
            "configuration",
            "config",
            "setup",
            "create",
            "define",
            "configure",
            "manage",
            "enable",
            "disable",
            "threshold",
            "budget",
            "quota",
            "monitoring",
            "watch",
            "track",
        ]

        # Check query text for semantic clues
        if query:
            if any(keyword in query for keyword in history_keywords):
                return "alerts"  # Historical events
            elif any(keyword in query for keyword in definition_keywords):
                return "anomalies"  # Alert definitions

        # Check action for semantic clues
        if action in ["create", "update", "delete", "enable", "disable"]:
            return "anomalies"  # These actions work on definitions
        elif action in ["query"] and any(keyword in query for keyword in history_keywords):
            return "alerts"  # Query with historical context

        # Default to anomalies for backward compatibility
        return "anomalies"

    # ============================================================================
    # CORE BUSINESS LOGIC METHODS (from alert_tools.py)
    # ============================================================================

    async def _handle_list(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle list operations for both anomalies and alerts with semantic detection."""
        # Use semantic detection if resource_type not explicitly specified
        resource_type = arguments.get("resource_type")
        if not resource_type:
            resource_type = self._detect_semantic_intent(arguments)
            logger.info(f"Semantic detection determined resource_type='{resource_type}'")

        logger.info(f"Alert Management: _handle_list called with resource_type='{resource_type}'")

        if resource_type == "anomalies":
            logger.info("Routing to anomaly operations for list")
            return await self._handle_anomaly_operations(client, "list", arguments)
        elif resource_type == "alerts":
            logger.info("Routing to alert operations for list")
            try:
                # Extract and validate pagination parameters with performance guidance
                page = arguments.get("page", 0)
                size = arguments.get("size", 20)
                filters = arguments.get("filters", {})
                query = arguments.get("query")

                # Validate pagination with performance guidance
                validation_result = validate_pagination_with_performance(
                    page, size, "Alert Management"
                )

                logger.info(
                    f"Calling alert_manager.list_alerts with page={page}, size={size} (tier: {validation_result['performance_tier']})"
                )
                return await self.alert_manager.list_alerts(client, page, size, filters, query)
            except ToolError:
                # Re-raise ToolError exceptions without modification
                # This preserves helpful error messages with specific suggestions
                raise
            except Exception as e:
                logger.error(f"Error in alert list operation: {e}")
                raise ToolError(
                    message="Failed to list alerts",
                    error_code=ErrorCodes.API_ERROR,
                    field="resource_type",
                    value=resource_type,
                    suggestions=[
                        "Check your API connection and credentials",
                        "Verify the resource_type parameter is correct",
                        'Use resource_type="alerts" for historical events',
                        'Use resource_type="anomalies" for alert definitions',
                        "Try again in a few moments",
                    ],
                    context={
                        "resource_type": resource_type,
                        "action": "list",
                        "original_error": str(e),
                    },
                )
        else:
            raise create_structured_validation_error(
                message=f"Invalid resource_type '{resource_type}'",
                field="resource_type",
                value=resource_type,
                suggestions=[
                    "Use 'anomalies' for alert definitions/rules",
                    "Use 'alerts' for historical events/incidents",
                    'For alert history/events: list(resource_type="alerts")',
                    'For alert rules/config: list(resource_type="anomalies")',
                ],
                examples={
                    "valid_resource_types": ["anomalies", "alerts"],
                    "alert_definitions": 'list(resource_type="anomalies")',
                    "alert_history": 'list(resource_type="alerts")',
                },
            )

    async def _handle_get(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get operations for both anomalies and alerts."""
        resource_type = arguments.get("resource_type", "anomalies")

        if resource_type == "anomalies":
            return await self._handle_anomaly_operations(client, "get", arguments)
        elif resource_type == "alerts":
            return await self._handle_alert_operations(client, "get", arguments)
        else:
            raise create_structured_validation_error(
                message=f"Invalid resource_type '{resource_type}' for get operation",
                field="resource_type",
                value=resource_type,
                suggestions=[
                    "Use 'anomalies' to get alert definitions/rules",
                    "Use 'alerts' to get historical alert events",
                    "Check the resource_type parameter for typos",
                ],
                examples={
                    "valid_resource_types": ["anomalies", "alerts"],
                    "get_anomaly": 'get(resource_type="anomalies", anomaly_id="anom_123")',
                    "get_alert": 'get(resource_type="alerts", alert_id="alert_456")',
                },
            )

    async def _handle_create(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle create operations for anomalies."""
        resource_type = arguments.get("resource_type", "anomalies")
        dry_run = arguments.get("dry_run", False)

        if resource_type == "anomalies":
            # Handle dry_run mode for create operations
            if dry_run:
                anomaly_data = arguments.get("anomaly_data")
                if not anomaly_data:
                    return [
                        TextContent(
                            type="text",
                            text="**Dry Run Validation Failed**: Missing anomaly_data parameter",
                        )
                    ]

                # Validate required fields without creating
                validation_result = {
                    "dry_run": True,
                    "operation": "create_anomaly",
                    "valid": True,
                    "message": "**Dry Run Successful**: Anomaly data is valid and ready for creation",
                    "would_create": {
                        "name": anomaly_data.get("name", "Unnamed Alert"),
                        "type": anomaly_data.get("alertType", "THRESHOLD"),
                        "metric": anomaly_data.get("metricType", "TOTAL_COST"),
                        "threshold": anomaly_data.get("threshold", 0),
                    },
                }
                return [
                    TextContent(
                        type="text",
                        text=f"**DRY RUN MODE**\n\n{json.dumps(validation_result, indent=2)}",
                    )
                ]

            return await self._handle_anomaly_operations(client, "create", arguments)
        else:
            raise ToolError(
                message=f"Cannot create '{resource_type}' directly",
                error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
                field="resource_type",
                value=resource_type,
                suggestions=[
                    "Use resource_type='anomalies' to create alert definitions",
                    "Alerts are generated automatically when anomaly conditions are met",
                    "Create Spike Detection rules using create_threshold_alert() or Budget Threshold rules using create_cumulative_usage_alert()",
                    "Use get_examples() to see alert creation examples",
                ],
                examples={
                    "create_monitoring": 'create(resource_type="anomalies", anomaly_data={...})',
                    "spike_detection": 'create_threshold_alert(name="Error Spike", threshold=5, period_minutes=10)  # Spike Detection',
                    "budget_threshold": 'create_cumulative_usage_alert(name="Budget Alert", threshold=1000, period="monthly")  # Budget Threshold',
                },
            )

    async def _handle_update(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle update operations for anomalies."""
        resource_type = arguments.get("resource_type", "anomalies")
        dry_run = arguments.get("dry_run", False)

        if resource_type == "anomalies":
            # Handle dry_run mode for update operations
            if dry_run:
                anomaly_id = arguments.get("anomaly_id")
                anomaly_data = arguments.get("anomaly_data")
                if not anomaly_id or not anomaly_data:
                    return [
                        TextContent(
                            type="text",
                            text="**Dry Run Validation Failed**: Missing anomaly_id or anomaly_data parameter",
                        )
                    ]

                # Validate update data without updating
                validation_result = {
                    "dry_run": True,
                    "operation": "update_anomaly",
                    "valid": True,
                    "message": "**Dry Run Successful**: Update data is valid and ready for application",
                    "would_update": {"anomaly_id": anomaly_id, "changes": anomaly_data},
                }
                return [
                    TextContent(
                        type="text",
                        text=f"**DRY RUN MODE**\n\n{json.dumps(validation_result, indent=2)}",
                    )
                ]

            return await self._handle_anomaly_operations(client, "update", arguments)
        else:
            raise ToolError(
                message=f"Cannot update '{resource_type}' - alerts are read-only",
                error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
                field="resource_type",
                value=resource_type,
                suggestions=[
                    "Use resource_type='anomalies' to update alert definitions",
                    "Alerts are read-only historical events",
                    "To modify monitoring rules, update the corresponding anomaly",
                    'Use get(resource_type="alerts") to view alert history only',
                ],
                examples={
                    "update_monitoring": 'update(resource_type="anomalies", anomaly_id="anom_123", anomaly_data={...})',
                    "view_alerts": 'get(resource_type="alerts", alert_id="alert_456")',
                },
            )

    async def _handle_delete(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle delete operations for anomalies."""
        resource_type = arguments.get("resource_type", "anomalies")

        if resource_type == "anomalies":
            return await self._handle_anomaly_operations(client, "delete", arguments)
        else:
            raise ToolError(
                message=f"Cannot delete '{resource_type}' - alerts are historical records",
                error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
                field="resource_type",
                value=resource_type,
                suggestions=[
                    "Use resource_type='anomalies' to delete alert definitions",
                    "Alerts are historical events and cannot be deleted",
                    "To stop monitoring, delete the corresponding anomaly",
                    "Use disable() to temporarily stop alert generation",
                ],
                examples={
                    "delete_monitoring": 'delete(resource_type="anomalies", anomaly_id="anom_123")',
                    "disable_monitoring": 'disable(anomaly_id="anom_123")',
                },
            )

    async def _handle_clear_all(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle clear all operations for anomalies."""
        resource_type = arguments.get("resource_type", "anomalies")

        if resource_type == "anomalies":
            return await self._handle_anomaly_operations(client, "clear_all", arguments)
        else:
            raise ToolError(
                message=f"Cannot clear '{resource_type}' - alerts are historical records",
                error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
                field="resource_type",
                value=resource_type,
                suggestions=[
                    "Use resource_type='anomalies' to clear alert definitions",
                    "Alerts are historical events and cannot be cleared",
                    "To remove all monitoring, use clear_all with resource_type='anomalies'",
                    "Use disable_all() to stop all alert generation temporarily",
                ],
                examples={
                    "clear_monitoring": 'clear_all(resource_type="anomalies")',
                    "disable_all_monitoring": "disable_all()",
                },
            )

    async def _handle_get_metrics(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get metrics operations."""
        return await self._handle_anomaly_operations(client, "get_metrics", arguments)

    async def _handle_query(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle query operations for alerts."""
        resource_type = arguments.get("resource_type", "alerts")

        if resource_type == "alerts":
            return await self._handle_alert_operations(client, "query", arguments)
        elif resource_type == "anomalies":
            return await self._handle_anomaly_operations(client, "query", arguments)
        else:
            raise create_structured_validation_error(
                message=f"Invalid resource_type '{resource_type}' for query operation",
                field="resource_type",
                value=resource_type,
                suggestions=[
                    "Use 'alerts' to query historical alert events",
                    "Use 'anomalies' to query alert definitions/rules",
                    "Check the resource_type parameter for typos",
                ],
                examples={
                    "valid_resource_types": ["anomalies", "alerts"],
                    "query_alerts": 'query(resource_type="alerts", query="show high cost alerts")',
                    "query_anomalies": 'query(resource_type="anomalies", filters={"enabled": True})',
                },
            )

    async def _handle_validate(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle validate operations."""
        return await self._handle_anomaly_operations(client, "validate", arguments)

    # ============================================================================
    # ANOMALY OPERATIONS (from alert_tools.py)
    # ============================================================================

    async def _handle_anomaly_operations(
        self, client: ReveniumClient, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle anomaly-related operations."""
        if action == "list":
            page = arguments.get("page", 0)
            size = arguments.get("size", 20)
            filters = arguments.get("filters", {})

            # Validate pagination with performance guidance
            validate_pagination_with_performance(page, size, "Alert Management")

            return await self.anomaly_manager.list_anomalies(client, page, size, filters)

        elif action == "get":
            anomaly_id = arguments.get("anomaly_id")
            if not anomaly_id:
                error = create_structured_missing_parameter_error(
                    parameter_name="anomaly_id",
                    action="get",
                    examples={
                        "usage": 'get(anomaly_id="alert_123")',
                        "valid_format": "Anomaly ID should be a string identifier",
                        "example_ids": ["alert_123", "threshold_alert", "usage_monitor"],
                    },
                )
                return [TextContent(type="text", text=format_structured_error(error))]
            return await self.anomaly_manager.get_anomaly(client, anomaly_id)

        elif action == "create":
            anomaly_data = arguments.get("anomaly_data")
            if not anomaly_data:
                error = create_structured_missing_parameter_error(
                    parameter_name="anomaly_data",
                    action="create",
                    examples={
                        "convenience_methods": {
                            "real_time_monitoring": 'create_threshold_alert(name="Cost Spike", threshold=100, period_minutes=5)',
                            "budget_tracking": 'create_cumulative_usage_alert(name="Monthly Budget", threshold=1000, period="monthly")',
                            "note": "Convenience methods are easier and handle all required fields automatically!",
                        },
                        "advanced_usage": 'create(anomaly_data={"name": "High Usage Alert", "metricType": "TOTAL_COST", "threshold": 100, "alertType": "THRESHOLD", "operatorType": "GREATER_THAN"})',
                        "required_fields": [
                            "name",
                            "metricType",
                            "threshold",
                            "alertType",
                            "operatorType",
                        ],
                        "example_data": {
                            "name": "Cost Alert",
                            "metricType": "TOTAL_COST",
                            "threshold": 100,
                            "alertType": "THRESHOLD",
                            "operatorType": "GREATER_THAN",
                        },
                    },
                )
                return [TextContent(type="text", text=format_structured_error(error))]
            return await self.anomaly_manager.create_anomaly(client, anomaly_data)

        elif action == "update":
            anomaly_id = arguments.get("anomaly_id")
            anomaly_data = arguments.get("anomaly_data")

            if not anomaly_id:
                error = create_structured_missing_parameter_error(
                    parameter_name="anomaly_id",
                    action="update",
                    examples={
                        "usage": 'update(anomaly_id="alert_123", anomaly_data={...})',
                        "valid_format": "Anomaly ID should be a string identifier",
                        "example_ids": ["alert_123", "threshold_alert", "usage_monitor"],
                    },
                )
                return [TextContent(type="text", text=format_structured_error(error))]

            # Support both direct parameters AND anomaly_data for improved UX
            # Direct parameters take precedence over anomaly_data if both provided
            updatable_fields = [
                "name",
                "threshold",
                "alertType",
                "enabled",
                "slackConfigurations",
                "notificationAddresses",
                "description",
                "tags",
                "metricType",
                "period",
                "triggerAfterPersistsDuration",
            ]

            # Build update data from direct parameters
            direct_params = {}
            for field in updatable_fields:
                if field in arguments:
                    direct_params[field] = arguments[field]

            # Merge anomaly_data with direct parameters (direct params win)
            if anomaly_data:
                if not isinstance(anomaly_data, dict):
                    error = create_structured_missing_parameter_error(
                        parameter_name="anomaly_data",
                        action="update",
                        examples={
                            "usage": 'update(anomaly_id="alert_123", anomaly_data={"threshold": 200})',
                            "error": "anomaly_data must be a dictionary/object",
                            "received_type": str(type(anomaly_data).__name__),
                        },
                    )
                    return [TextContent(type="text", text=format_structured_error(error))]
                # Start with anomaly_data, then override with direct params
                final_update_data = {**anomaly_data, **direct_params}
            elif direct_params:
                # Only direct parameters provided
                final_update_data = direct_params
            else:
                # Neither anomaly_data nor direct parameters provided
                error = create_structured_missing_parameter_error(
                    parameter_name="update_data",
                    action="update",
                    examples={
                        "direct_params": 'update(anomaly_id="alert_123", name="New Name", threshold=200)',
                        "anomaly_data": 'update(anomaly_id="alert_123", anomaly_data={"threshold": 200})',
                        "hybrid": 'update(anomaly_id="alert_123", anomaly_data={"name": "Base"}, threshold=300)',
                        "updatable_fields": updatable_fields,
                        "slack_config_example": {"slackConfigurations": ["5jpABv"]},
                        "email_example": {"notificationAddresses": ["user@example.com"]},
                        "combined_example": {
                            "threshold": 200,
                            "enabled": True,
                            "slackConfigurations": ["5jpABv"],
                        },
                        "note": "Supports direct params, anomaly_data object, or both (direct params take precedence)",
                    },
                )
                return [TextContent(type="text", text=format_structured_error(error))]
            return await self.anomaly_manager.update_anomaly(client, anomaly_id, final_update_data)

        elif action == "delete":
            anomaly_id = arguments.get("anomaly_id")
            if not anomaly_id:
                error = create_structured_missing_parameter_error(
                    parameter_name="anomaly_id",
                    action="delete",
                    examples={
                        "usage": 'delete(anomaly_id="alert_123")',
                        "valid_format": "Anomaly ID should be a string identifier",
                        "example_ids": ["alert_123", "threshold_alert", "usage_monitor"],
                        "warning": "This action permanently removes the alert",
                    },
                )
                return [TextContent(type="text", text=format_structured_error(error))]
            return await self.anomaly_manager.delete_anomaly(client, anomaly_id)

        elif action == "clear_all":
            confirm = arguments.get("confirm")
            if not confirm:
                return [
                    TextContent(
                        type="text",
                        text="**Confirmation Required**: This will delete ALL anomalies\n\n"
                        "**To proceed**: Use `clear_all(confirm=True)`\n\n"
                        "**WARNING**: This action will:\n"
                        "• Delete every anomaly in your account\n"
                        "• Stop ALL alert monitoring\n"
                        "• Cannot be undone\n\n"
                        "**Alternative**: Delete specific anomalies using `delete(anomaly_id='...')`",
                    )
                ]
            return await self.anomaly_manager.clear_all_anomalies(client)

        elif action == "get_metrics":
            anomaly_id = arguments.get("anomaly_id")
            if not anomaly_id:
                error = create_structured_missing_parameter_error(
                    parameter_name="anomaly_id",
                    action="get_metrics",
                    examples={
                        "usage": 'get_metrics(anomaly_id="alert_123")',
                        "valid_format": "Anomaly ID should be a string identifier",
                        "example_ids": ["alert_123", "threshold_alert", "usage_monitor"],
                        "purpose": "Retrieve performance metrics for the specified alert",
                    },
                )
                return [TextContent(type="text", text=format_structured_error(error))]
            return await self.anomaly_manager.get_anomaly_metrics(client, anomaly_id)

        elif action == "query":
            filters = arguments.get("filters", {})
            # Use list with filters for query functionality
            return await self.anomaly_manager.list_anomalies(client, 0, 20, filters)

        elif action == "validate":
            anomaly_data = arguments.get("anomaly_data")
            if not anomaly_data:
                error = create_structured_missing_parameter_error(
                    parameter_name="anomaly_data",
                    action="validate",
                    examples={
                        "usage": 'validate(anomaly_data={"name": "Test Alert", "metricType": "TOTAL_COST", "threshold": 100})',
                        "required_fields": ["name", "metricType", "threshold", "alertType"],
                        "example_data": {
                            "name": "Validation Test",
                            "metricType": "TOTAL_COST",
                            "threshold": 100,
                            "alertType": "THRESHOLD",
                        },
                        "purpose": "Validate alert configuration before creation",
                    },
                )
                return [TextContent(type="text", text=format_structured_error(error))]
            try:
                # Force proper UCM integration for validation
                error = ToolError(
                    message="Alert validation unavailable - use UCM capabilities for validation",
                    error_code=ErrorCodes.UCM_ERROR,
                    field="validation",
                    value="hardcoded_validation_removed",
                    suggestions=[
                        "Use get_capabilities() to see valid alert types and required fields",
                        "Let the API handle validation during alert creation",
                        "Check UCM integration status with test_ucm_integration action",
                        "Verify alert configuration against UCM-provided capabilities",
                    ],
                    examples={
                        "capabilities_check": "get_capabilities() to see API-verified alert types and metrics",
                        "ucm_integration": "test_ucm_integration() to verify UCM connectivity",
                        "api_validation": "create() action will validate against real-time API requirements",
                        "monitoring_context": "MONITORING: UCM provides real-time validation for alert configuration",
                    },
                )
                return [TextContent(type="text", text=format_structured_error(error))]
            except Exception as e:
                error = ToolError(
                    message=f"Alert validation failed: {str(e)}",
                    error_code=ErrorCodes.VALIDATION_ERROR,
                    field="validation",
                    value=str(e),
                    suggestions=[
                        "Check alert configuration parameters",
                        "Use get_capabilities() to see valid alert types",
                        "Verify UCM integration is working properly",
                        "Try creating the alert directly to get API validation",
                    ],
                    examples={
                        "capabilities": "get_capabilities() for valid alert types",
                        "direct_creation": "create() action provides real-time API validation",
                        "monitoring_context": "MONITORING: Validation ensures alert configuration meets API requirements",
                    },
                )
                return [TextContent(type="text", text=format_structured_error(error))]

        else:
            error = ToolError(
                message=f"Unknown anomaly action '{action}' is not supported",
                error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
                field="action",
                value=action,
                suggestions=[
                    "Use get_capabilities() to see all available anomaly actions",
                    "Check the action name for typos",
                    "Use get_examples() to see working examples",
                    "For alert creation, use 'create' with proper anomaly_data",
                ],
                examples={
                    "basic_actions": ["list", "get", "create", "update", "delete"],
                    "monitoring_actions": ["get_metrics", "query", "validate"],
                    "management_actions": ["clear_all"],
                    "example_usage": {
                        "create_alert": 'create(anomaly_data={"name": "Cost Alert", "metricType": "TOTAL_COST", "threshold": 100})',
                        "list_alerts": "list(page=0, size=10)",
                        "get_metrics": 'get_metrics(anomaly_id="alert_123")',
                    },
                },
            )
            return [TextContent(type="text", text=format_structured_error(error))]

    # ============================================================================
    # ALERT OPERATIONS (from alert_tools.py)
    # ============================================================================

    async def _handle_alert_operations(
        self, client: ReveniumClient, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle alert-related operations."""
        if action == "list":
            page = arguments.get("page", 0)
            size = arguments.get("size", 20)
            filters = arguments.get("filters", {})
            query = arguments.get("query")
            return await self.alert_manager.list_alerts(client, page, size, filters, query)

        elif action == "get":
            alert_id = arguments.get("alert_id")
            if not alert_id:
                error = create_structured_missing_parameter_error(
                    parameter_name="alert_id",
                    action="get",
                    examples={
                        "usage": 'get(alert_id="alert_123")',
                        "valid_format": "Alert ID should be a string identifier",
                        "example_ids": ["alert_123", "cost_alert", "usage_alert"],
                        "note": "Alerts are read-only - use anomalies for creating new alerts",
                    },
                )
                return [TextContent(type="text", text=format_structured_error(error))]
            return await self.alert_manager.get_alert(client, alert_id)

        elif action == "query":
            query = arguments.get("query")
            filters = arguments.get("filters", {})
            # Use list with query parameter for natural language search
            return await self.alert_manager.list_alerts(client, 0, 20, filters, query)

        else:
            error = ToolError(
                message=f"Unknown alert action '{action}' is not supported",
                error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
                field="action",
                value=action,
                suggestions=[
                    "Alerts are read-only - use anomaly actions for creating new alerts",
                    "Use get_capabilities() to see all available alert actions",
                    "Check the action name for typos",
                    "For creating alerts, use anomaly management instead",
                ],
                examples={
                    "alert_actions": ["list", "get", "query"],
                    "anomaly_actions": ["create", "update", "delete"],
                    "example_usage": {
                        "list_alerts": "list() to see existing alerts",
                        "get_alert": 'get(alert_id="alert_123")',
                        "create_new": "Use anomaly create() to create new alerts",
                    },
                    "note": "Alerts are read-only. To create monitoring, use anomalies.",
                },
            )
            return [TextContent(type="text", text=format_structured_error(error))]

    # ============================================================================
    # ENHANCED CREATION METHODS (from enhanced_alert_tools.py)
    # ============================================================================

    async def _handle_get_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Enhanced capabilities with clear alert type guidance and semantic distinction."""
        # Get UCM capabilities if available for API-verified data
        ucm_capabilities = None
        if self.ucm_helper:
            try:
                ucm_capabilities = await self.ucm_helper.ucm.get_capabilities("alerts")
                log_ucm_status("Alert Management", True, True)
            except ToolError:
                # Re-raise ToolError exceptions without modification
                # This preserves helpful error messages with specific suggestions
                raise
            except Exception as e:
                log_ucm_status("Alert Management", True, False)
                logger.warning(f"Failed to get UCM alert capabilities, using static data: {e}")
        else:
            log_ucm_status("Alert Management", False)

        # Build enhanced capabilities with UCM data
        return [
            TextContent(
                type="text", text=await self._build_enhanced_capabilities_text(ucm_capabilities)
            )
        ]

    async def _build_enhanced_capabilities_text(
        self, ucm_capabilities: Optional[Dict[str, Any]]
    ) -> str:
        """Build enhanced capabilities text combining semantic guidance with UCM data."""
        text = """# **Alert Management Capabilities**

**Important Distinction**
### **ANOMALIES** (Alert Definitions/Rules)
- **What**: Configuration rules that define when to trigger alerts
- **Use**: `resource_type="anomalies"` or `list()` (default)
- **Actions**: create, update, delete, enable, disable
- **Think**: "Alert rules", "monitoring configuration", "alert definitions"

### **ALERTS** (Historical Events)
- **What**: Historical records of when anomalies actually fired
- **Use**: `resource_type="alerts"`
- **Actions**: list, get, query (read-only)
- **Think**: "Alert history", "fired alerts", "triggered events", "alert incidents"

**Common Use Cases"**                    **Recommended Actions:**
• "Show me alerts"                       → `list(resource_type="alerts")` (history)
• "List alert rules"                     → `list(resource_type="anomalies")` (definitions)
• "Alert history"                        → `list(resource_type="alerts")` (history)
• "Triggered alerts"                     → `list(resource_type="alerts")` (history)
• "Alert definitions"                    → `list(resource_type="anomalies")` (definitions)
• "Configure alerts"                     → `create_*_alert()` (definitions)
• "Recent alerts"                        → `list(resource_type="alerts")` (history)
• "Alert incidents"                      → `list(resource_type="alerts")` (history)

## **Quick Start Commands**

### **View Historical Fired Alerts**
```bash
list(resource_type="alerts")                    # Recent alert events
query(resource_type="alerts", query="last week") # Natural language search
get(resource_type="alerts", alert_id="evt_123")  # Specific alert event
```

### **Manage Alert Definitions/Rules**
```bash
list(resource_type="anomalies")                 # Alert rules/definitions
create_cumulative_usage_alert(...)              # Budget tracking rule
create_threshold_alert(...)                     # Real-time monitoring rule
```

## **Alert Type Decision Tree**

### **Need Budget/Quota Tracking?** → Budget Threshold
- Monthly spending limits: `create_cumulative_usage_alert(...)`
- Weekly token quotas: `create_cumulative_usage_alert(...)`
- Daily API call limits: `create_cumulative_usage_alert(...)`

### **Need Real-time Monitoring?** → Spike Detection
- Cost spike alerts: `create_threshold_alert(...)`
- Error rate monitoring: `create_threshold_alert(...)`
- Performance alerts: `create_threshold_alert(...)`

### **Need Trend/Change Detection?** → Relative Change
- Cost increase alerts: `create` with `alertType: RELATIVE_CHANGE`, `operatorType: INCREASES_BY`
- Cost decrease alerts: `create` with `alertType: RELATIVE_CHANGE`, `operatorType: DECREASES_BY`
- Percentage-based monitoring over daily, weekly, or monthly periods"""

        # Get metrics using single source of truth with UCM integration
        try:
            metrics_capabilities = await get_alert_metrics_capabilities(self.ucm_helper)
            text += "\n\n## **Available Metrics**\n"

            # Display categorized metrics if available
            if "cost_metrics" in metrics_capabilities:
                for category, metric_list in metrics_capabilities.items():
                    if category != "all" and metric_list:  # Skip 'all' category and empty lists
                        category_name = category.replace("_", " ").title()
                        text += f"\n### {category_name}\n"
                        for metric in metric_list:
                            text += f"- **{metric}**\n"
            else:
                # Fallback to flat list if categorization not available
                all_metrics = metrics_capabilities.get(
                    "all", [metric.value for metric in MetricType]
                )
                for metric in all_metrics:
                    text += f"- **{metric}**\n"

        except Exception as e:
            logger.warning(f"Failed to get metrics capabilities, using MetricType fallback: {e}")
            # Final fallback to MetricType enum
            text += "\n\n## **Available Metrics**\n"
            for metric in MetricType:
                text += f"- **{metric.value}**\n"

        # Add UCM-enhanced operators if available
        if ucm_capabilities and "operators" in ucm_capabilities:
            text += "\n\n## **Available Operators**\n"
            for operator in ucm_capabilities["operators"]:
                text += f"- **{operator}**\n"

        # Add UCM-enhanced alert types if available
        if ucm_capabilities and "alert_types" in ucm_capabilities:
            text += "\n\n## **Alert Types**\n"
            for alert_type in ucm_capabilities["alert_types"]:
                text += f"- **{alert_type}**\n"

        text += """

## **Persistence-Based Alerting**

The `triggerAfterPersistsDuration` parameter enables sophisticated alert behavior by requiring the alert condition to persist for a specified duration before triggering. This prevents false alarms from temporary spikes.

### **How It Works**
- **periodDuration**: How frequently the alert condition is evaluated (e.g., every 5 minutes)
- **triggerAfterPersistsDuration**: How long the condition must persist before triggering (e.g., 15 minutes)
- **Example**: With `periodDuration="FIVE_MINUTES"` and `triggerAfterPersistsDuration="FIFTEEN_MINUTES"`, the alert checks every 5 minutes and only triggers if the threshold is exceeded for 3 consecutive checks

### **Use Cases**
- **Sustained Cost Spikes**: Only alert if costs remain high for 30 minutes
- **Persistent Error Rates**: Only alert if error rate stays elevated for 15 minutes
- **Long-term Budget Overruns**: Only alert if monthly budget exceeded for 3 consecutive days"""

        # Add UCM-enhanced trigger duration values if available
        if ucm_capabilities and "trigger_durations" in ucm_capabilities:
            text += "\n\n### **Valid Duration Values**\n"
            trigger_durations = ucm_capabilities["trigger_durations"]

            # Group durations by category if they're provided as a list
            if isinstance(trigger_durations, list):
                # Categorize durations
                short_term = [
                    d
                    for d in trigger_durations
                    if d in ["ONE_MINUTE", "FIVE_MINUTES", "FIFTEEN_MINUTES", "THIRTY_MINUTES"]
                ]
                medium_term = [
                    d
                    for d in trigger_durations
                    if d in ["ONE_HOUR", "TWELVE_HOURS", "TWENTY_FOUR_HOURS"]
                ]
                long_term = [d for d in trigger_durations if d in ["SEVEN_DAYS", "THIRTY_DAYS"]]
                periodic = [
                    d for d in trigger_durations if d in ["DAILY", "WEEKLY", "MONTHLY", "QUARTERLY"]
                ]

                if short_term:
                    text += f"- **Short Term**: {', '.join(short_term)}\n"
                if medium_term:
                    text += f"- **Medium Term**: {', '.join(medium_term)}\n"
                if long_term:
                    text += f"- **Long Term**: {', '.join(long_term)}\n"
                if periodic:
                    text += f"- **Periodic**: {', '.join(periodic)}\n"
            else:
                # Handle other formats
                for duration in trigger_durations:
                    text += f"- **{duration}**\n"
        else:
            # Fallback to UCM-validated static values from TriggerDuration enum
            text += """

### **Valid Duration Values**
- **Short Term**: ONE_MINUTE, FIVE_MINUTES, FIFTEEN_MINUTES, THIRTY_MINUTES
- **Medium Term**: ONE_HOUR, TWELVE_HOURS, TWENTY_FOUR_HOURS
- **Long Term**: SEVEN_DAYS, THIRTY_DAYS
- **Periodic**: DAILY, WEEKLY, MONTHLY, QUARTERLY"""

        text += """

**Pro Tip**: When in doubt, use `resource_type="alerts"` for history and `resource_type="anomalies"` for configuration!"""

        return text

    async def _handle_test_ucm_integration(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Test UCM integration status and capabilities."""
        result_text = "**UCM Integration Test Results**\n\n"

        # Test UCM helper availability
        if self.ucm_helper:
            result_text += "**UCM Helper**: Available\n"

            # Test UCM capabilities call
            try:
                ucm_capabilities = await self.ucm_helper.get_capabilities("alerts")
                if ucm_capabilities:
                    result_text += "**UCM Capabilities**: Successfully retrieved\n"
                    result_text += (
                        f"**Alert Types**: {len(ucm_capabilities.get('alert_types', []))} types\n"
                    )
                    result_text += (
                        f"**Metrics**: {len(ucm_capabilities.get('metrics', {}))} categories\n"
                    )
                    result_text += (
                        f"**Operators**: {len(ucm_capabilities.get('operators', []))} operators\n"
                    )

                    # Show sample metrics
                    metrics = ucm_capabilities.get("metrics", {})
                    if metrics:
                        result_text += "\n**Sample UCM Metrics**:\n"
                        for category, metric_list in list(metrics.items())[
                            :2
                        ]:  # Show first 2 categories
                            result_text += f"- **{category}**: {', '.join(metric_list[:3])}{'...' if len(metric_list) > 3 else ''}\n"
                else:
                    result_text += "**UCM Capabilities**: Retrieved but empty\n"
            except ToolError:
                # Re-raise ToolError exceptions without modification
                # This preserves helpful error messages with specific suggestions
                raise
            except Exception as e:
                result_text += f"**UCM Capabilities**: Failed to retrieve - {str(e)}\n"
        else:
            result_text += "**UCM Helper**: Not available\n"
            result_text += "**Reason**: UCM helper was not passed to AlertManagement constructor\n"

        result_text += "\n**Diagnosis**:\n"
        if self.ucm_helper:
            result_text += "- UCM integration is working correctly\n"
            result_text += "- Enhanced metrics should be available in get_capabilities()\n"
        else:
            result_text += "- UCM helper is None - check introspection registration\n"
            result_text += "- Falling back to static capabilities\n"

        return [TextContent(type="text", text=result_text)]

    async def _handle_get_examples(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get examples based on alert type."""
        try:
            alert_type = (arguments.get("alert_type") or "").lower()

            # Support both old and new terminology for backward compatibility
            if alert_type in ["cumulative_usage", "budget_threshold"]:
                return [
                    TextContent(
                        type="text",
                        text="""**Budget Threshold Alert Examples**

These alerts track usage over time periods and reset each period.
Perfect for budget tracking and quota management.

## **Monthly Budget Alerts**
```json
{
  "name": "Monthly Budget Alert",
  "alertType": "CUMULATIVE_USAGE",
  "metricType": "TOTAL_COST",
  "threshold": 5000,
  "periodDuration": "MONTHLY",
  "email": "finance@company.com"
}
```

## **Weekly Token Quota**
```json
{
  "name": "Weekly Token Limit",
  "alertType": "CUMULATIVE_USAGE",
  "metricType": "TOKEN_COUNT",
  "threshold": 1000000,
  "periodDuration": "WEEKLY",
  "email": "engineering@company.com"
}
```

## **Provider-Specific Budget Tracking** (With Metric Filtering)
```json
{
  "name": "OpenAI Monthly Budget",
  "alertType": "CUMULATIVE_USAGE",
  "metricType": "TOTAL_COST",
  "threshold": 2000,
  "periodDuration": "MONTHLY",
  "email": "ai-team@company.com",
  "filters": [
    {
      "dimension": "PROVIDER",
      "operator": "CONTAINS",
      "value": "openai"
    }
  ]
}
```

## **Model-Specific Budget Tracking** (With Metric Filtering)
```json
{
  "name": "GPT-4 Weekly Budget",
  "alertType": "CUMULATIVE_USAGE",
  "metricType": "TOTAL_COST",
  "threshold": 1500,
  "periodDuration": "WEEKLY",
  "email": "ai-team@company.com",
  "filters": [
    {
      "dimension": "MODEL",
      "operator": "CONTAINS",
      "value": "gpt-4"
    }
  ]
}
```

## **Customer-Specific Budget Tracking** (With Metric Filtering)
```json
{
  "name": "Enterprise Customer Monthly Budget",
  "alertType": "CUMULATIVE_USAGE",
  "metricType": "TOTAL_COST",
  "threshold": 10000,
  "periodDuration": "MONTHLY",
  "email": "account-management@company.com",
  "filters": [
    {
      "dimension": "ORGANIZATION",
      "operator": "CONTAINS",
      "value": "enterprise-client"
    }
  ]
}
```

## **Product-Specific Budget Tracking** (With Metric Filtering)
```json
{
  "name": "API Service Monthly Budget",
  "alertType": "CUMULATIVE_USAGE",
  "metricType": "TOTAL_COST",
  "threshold": 3000,
  "periodDuration": "MONTHLY",
  "email": "product-team@company.com",
  "filters": [
    {
      "dimension": "PRODUCT",
      "operator": "CONTAINS",
      "value": "api-service"
    }
  ]
}
```

## **⏱️ Persistent Budget Monitoring**
```json
{
  "name": "Sustained Budget Overrun Alert",
  "alertType": "CUMULATIVE_USAGE",
  "metricType": "TOTAL_COST",
  "threshold": 5000,
  "periodDuration": "MONTHLY",
  "triggerAfterPersistsDuration": "SEVEN_DAYS",
  "email": "finance@company.com"
}
```

## **Persistent Token Usage Monitoring**
```json
{
  "name": "Sustained Token Usage Alert",
  "alertType": "CUMULATIVE_USAGE",
  "metricType": "TOKEN_COUNT",
  "threshold": 100000,
  "periodDuration": "WEEKLY",
  "triggerAfterPersistsDuration": "DAILY",
  "email": "engineering@company.com"
}
```

## **Quick Creation**
```bash
# Basic budget alert (email optional if REVENIUM_DEFAULT_EMAIL is set)
create_cumulative_usage_alert(
  name="Monthly Budget",
  threshold=5000,
  period="monthly"
)

# With explicit email
create_cumulative_usage_alert(
  name="Monthly Budget",
  threshold=5000,
  period="monthly",
  email="admin@company.com"
)

# Provider-specific budget alert (using create action with filters)
create(
  resource_type="anomalies",
  anomaly_data={
    "name": "OpenAI Monthly Budget",
    "alertType": "CUMULATIVE_USAGE",
    "metricType": "TOTAL_COST",
    "threshold": 2000,
    "periodDuration": "MONTHLY",
    "filters": [{"dimension": "PROVIDER", "operator": "CONTAINS", "value": "openai"}]
  }
)
```

**Pro Tip**: Use metric filtering to create targeted budget alerts that track spending for specific providers, models, customers, or products instead of global budgets!""",
                    )
                ]

            elif alert_type in ["threshold", "spike_detection"]:
                return [
                    TextContent(
                        type="text",
                        text="""**Spike Detection Alert Examples**

These alerts trigger immediately when values exceed thresholds.
Perfect for real-time monitoring and spike detection.

## **Cost Spike Detection**
```json
{
  "name": "High Cost Alert",
  "alertType": "THRESHOLD",
  "metricType": "TOTAL_COST",
  "threshold": 100,
  "periodDuration": "FIVE_MINUTES",
  "email": "alerts@company.com"
}
```

## **Error Rate Monitoring**
```json
{
  "name": "Error Rate Alert",
  "alertType": "THRESHOLD",
  "metricType": "ERROR_RATE",
  "threshold": 5,
  "isPercentage": true,
  "periodDuration": "ONE_MINUTE",
  "email": "engineering@company.com"
}
```

## **⏱️ Persistence-Based Alerting**
```json
{
  "name": "Sustained Cost Spike Alert",
  "alertType": "THRESHOLD",
  "metricType": "TOTAL_COST",
  "threshold": 200,
  "periodDuration": "FIVE_MINUTES",
  "triggerAfterPersistsDuration": "FIFTEEN_MINUTES",
  "email": "finance@company.com"
}
```

## **Persistent Error Monitoring**
```json
{
  "name": "Persistent Error Alert",
  "alertType": "THRESHOLD",
  "metricType": "ERROR_RATE",
  "threshold": 3,
  "isPercentage": true,
  "periodDuration": "ONE_MINUTE",
  "triggerAfterPersistsDuration": "FIFTEEN_MINUTES",
  "email": "ops@company.com"
}
```

## **Performance Monitoring**
```json
{
  "name": "Token Rate Alert",
  "alertType": "THRESHOLD",
  "metricType": "TOKENS_PER_MINUTE",
  "threshold": 1000,
  "periodDuration": "ONE_MINUTE",
  "email": "ops@company.com"
}
```

## **Provider-Specific Monitoring** (With Metric Filtering)
```json
{
  "name": "OpenAI Cost Alert",
  "alertType": "THRESHOLD",
  "metricType": "TOTAL_COST",
  "threshold": 500,
  "periodDuration": "FIFTEEN_MINUTES",
  "email": "ai-team@company.com",
  "filters": [
    {
      "dimension": "PROVIDER",
      "operator": "CONTAINS",
      "value": "openai"
    }
  ]
}
```

## **Model-Specific Monitoring** (With Metric Filtering)
```json
{
  "name": "GPT-4 Usage Alert",
  "alertType": "THRESHOLD",
  "metricType": "TOTAL_COST",
  "threshold": 200,
  "periodDuration": "THIRTY_MINUTES",
  "email": "ai-team@company.com",
  "filters": [
    {
      "dimension": "MODEL",
      "operator": "CONTAINS",
      "value": "gpt-4"
    }
  ]
}
```

## **Customer-Specific Monitoring** (With Metric Filtering)
```json
{
  "name": "Enterprise Customer Alert",
  "alertType": "THRESHOLD",
  "metricType": "TOTAL_COST",
  "threshold": 1000,
  "periodDuration": "ONE_HOUR",
  "email": "account-management@company.com",
  "filters": [
    {
      "dimension": "ORGANIZATION",
      "operator": "CONTAINS",
      "value": "enterprise-client"
    }
  ]
}
```

## **Product-Specific Monitoring** (With Metric Filtering)
```json
{
  "name": "API Service Cost Alert",
  "alertType": "THRESHOLD",
  "metricType": "TOTAL_COST",
  "threshold": 300,
  "periodDuration": "FIFTEEN_MINUTES",
  "email": "product-team@company.com",
  "filters": [
    {
      "dimension": "PRODUCT",
      "operator": "CONTAINS",
      "value": "api-service"
    }
  ]
}
```

## **Quick Creation**
```bash
# Basic alert (email optional if REVENIUM_DEFAULT_EMAIL is set)
create_threshold_alert(
  name="Cost Spike",
  threshold=100,
  period_minutes=5
)

# With explicit email
create_threshold_alert(
  name="Cost Spike",
  threshold=100,
  period_minutes=5,
  email="alerts@company.com"
)

# With persistence-based alerting
create_threshold_alert(
  name="Sustained Cost Spike",
  threshold=200,
  period_minutes=5,
  triggerAfterPersistsDuration="FIFTEEN_MINUTES",
  email="alerts@company.com"
)

# Provider-specific alert (using create action with filters)
create(
  resource_type="anomalies",
  anomaly_data={
    "name": "OpenAI Cost Alert",
    "alertType": "THRESHOLD",
    "metricType": "TOTAL_COST",
    "threshold": 500,
    "periodDuration": "FIFTEEN_MINUTES",
    "filters": [{"dimension": "PROVIDER", "operator": "CONTAINS", "value": "openai"}]
  }
)
```

## **Available Filter Dimensions**
- **PROVIDER**: Filter by AI provider (openai, anthropic, google, etc.)
- **MODEL**: Filter by AI model (gpt-4, claude-3, gemini, etc.)
- **ORGANIZATION**: Filter by customer/organization name
- **PRODUCT**: Filter by product or service name
- **AGENT**: Filter by agent/user identifier
- **SUBSCRIBER**: Filter by subscriber name or email

## **Available Filter Operators**
- **CONTAINS**: Partial match (case-insensitive)
- **IS**: Exact match
- **IS_NOT**: Exact non-match
- **STARTS_WITH**: Prefix match
- **ENDS_WITH**: Suffix match

**Pro Tip**: Use metric filtering to create targeted alerts that monitor specific providers, models, customers, or products instead of global thresholds!""",
                    )
                ]

            elif alert_type in ["relative_change"]:
                return [
                    TextContent(
                        type="text",
                        text="""**Relative Change Alert Examples**

These alerts detect percentage-based changes over time periods.
Use INCREASES_BY or DECREASES_BY operators with daily, weekly, or monthly periods.

## **Daily Cost Increase Detection**
```json
{
  "action": "create",
  "anomaly_data": {
    "name": "Daily Cost Increase Alert",
    "alertType": "RELATIVE_CHANGE",
    "metricType": "TOTAL_COST",
    "operatorType": "INCREASES_BY",
    "threshold": 20,
    "isPercentage": true,
    "periodDuration": "DAILY",
    "notificationAddresses": ["finance@company.com"]
  }
}
```

## **Weekly Cost Decrease Detection**
```json
{
  "action": "create",
  "anomaly_data": {
    "name": "Weekly Cost Drop Alert",
    "alertType": "RELATIVE_CHANGE",
    "metricType": "TOTAL_COST",
    "operatorType": "DECREASES_BY",
    "threshold": 30,
    "isPercentage": true,
    "periodDuration": "WEEKLY",
    "notificationAddresses": ["ops@company.com"]
  }
}
```

## **Monthly Token Usage Change**
```json
{
  "action": "create",
  "anomaly_data": {
    "name": "Monthly Token Increase Alert",
    "alertType": "RELATIVE_CHANGE",
    "metricType": "INPUT_TOKENS",
    "operatorType": "INCREASES_BY",
    "threshold": 50,
    "isPercentage": true,
    "periodDuration": "MONTHLY",
    "notificationAddresses": ["engineering@company.com"]
  }
}
```

## **Using Detection Rules Format**
```json
{
  "action": "create",
  "anomaly_data": {
    "name": "Cost Trend Alert",
    "detection_rules": [
      {
        "rule_type": "RELATIVE_CHANGE",
        "metric": "total_cost",
        "operator": "INCREASES_BY",
        "value": 25,
        "time_window": "weekly"
      }
    ],
    "notification_addresses": ["alerts@company.com"],
    "is_percentage": true
  }
}
```

## **Using Natural Language**
```json
{
  "action": "create_from_text",
  "text": "alert me when costs increase by 20% daily"
}
```

**Key Points**:
- Valid operators: INCREASES_BY, DECREASES_BY
- Valid periods: DAILY, WEEKLY, MONTHLY, QUARTERLY
- Sub-daily periods (e.g., 5 minutes) are automatically clamped to DAILY
- Use `isPercentage: true` for percentage-based thresholds""",
                    )
                ]

            elif alert_type == "update":
                return [
                    TextContent(
                        type="text",
                        text="""**Update Alert Examples**

These examples show how to update existing alerts with new configurations, including filters and user-friendly parameter names.

## **Required Parameters**
- `anomaly_id`: The ID of the alert to update
- `anomaly_data`: Dictionary containing the fields to update

## **Basic Alert Updates**

### **Update Alert Threshold**
```python
update(
    anomaly_id="5jXPdv",
    anomaly_data={"threshold": 500}
)
```

### **Enable/Disable Alert**
```python
update(
    anomaly_id="5jXPdv",
    anomaly_data={"enabled": false}
)
```

## **Filter Updates**

### **Add Provider Filter (API Format)**
```python
update(
    anomaly_id="5jXPdv",
    anomaly_data={
        "filters": [
            {"dimension": "PROVIDER", "operator": "CONTAINS", "value": "openai"}
        ]
    }
)
```

### **Add Provider Filter (User-Friendly Format)**
```python
update(
    anomaly_id="5jXPdv",
    anomaly_data={
        "filters": [
            {"field": "provider", "operator": "contains", "value": "openai"}
        ]
    }
)
```

### **Multiple Filters**
```python
update(
    anomaly_id="5jXPdv",
    anomaly_data={
        "filters": [
            {"dimension": "PROVIDER", "operator": "CONTAINS", "value": "anthropic"},
            {"dimension": "MODEL", "operator": "IS", "value": "claude-3-sonnet"}
        ]
    }
)
```

### **Remove All Filters**
```python
update(
    anomaly_id="5jXPdv",
    anomaly_data={"filters": []}
)
```

## **User-Friendly Parameter Updates**

### **Update Alert Type and Metric (User-Friendly)**
```python
update(
    anomaly_id="5jXPdv",
    anomaly_data={
        "alert_type": "threshold",
        "metric_type": "token_count"
    }
)
```

### **Update Period Using Minutes**
```python
update(
    anomaly_id="5jXPdv",
    anomaly_data={
        "period_minutes": 15  # Converts to "FIFTEEN_MINUTES"
    }
)
```

### **Update Email Notifications (User-Friendly)**
```python
update(
    anomaly_id="5jXPdv",
    anomaly_data={
        "email": "admin@company.com"  # Converts to notificationAddresses
    }
)
```

### **Update Percentage Flag**
```python
update(
    anomaly_id="5jXPdv",
    anomaly_data={
        "is_percentage": true  # Converts to isPercentage
    }
)
```

### **Update Alert Name**
```python
update(
    anomaly_id="5jXPdv",
    anomaly_data={"name": "Updated Monthly Budget Alert"}
)
```

## **Slack Configuration Updates**

### **Add Slack Notifications**
```python
# First get available Slack configs with: list_slack_configurations()
update(
    anomaly_id="5jXPdv",
    anomaly_data={"slackConfigurations": ["5jpABv"]}
)
```

### **Add Multiple Slack Channels**
```python
update(
    anomaly_id="5jXPdv",
    anomaly_data={"slackConfigurations": ["5jpABv", "config_2", "config_3"]}
)
```

### **Remove Slack Notifications**
```python
update(
    anomaly_id="5jXPdv",
    anomaly_data={"slackConfigurations": []}
)
```

## **Email Configuration Updates**

### **Add Email Notifications**
```python
update(
    anomaly_id="5jXPdv",
    anomaly_data={"notificationAddresses": ["admin@company.com"]}
)
```

### **Update Multiple Email Recipients**
```python
update(
    anomaly_id="5jXPdv",
    anomaly_data={"notificationAddresses": ["admin@company.com", "finance@company.com"]}
)
```

## **Combined Updates**

### **Update Threshold + Add Slack + Email**
```python
update(
    anomaly_id="5jXPdv",
    anomaly_data={
        "threshold": 1000,
        "slackConfigurations": ["5jpABv"],
        "notificationAddresses": ["admin@company.com"],
        "enabled": true
    }
)
```

### **Complete Alert Reconfiguration**
```python
update(
    anomaly_id="5jXPdv",
    anomaly_data={
        "name": "Updated Daily Budget Alert",
        "threshold": 750,
        "alertType": "CUMULATIVE_USAGE",
        "enabled": true,
        "slackConfigurations": ["5jpABv", "backup_channel"],
        "notificationAddresses": ["primary@company.com", "backup@company.com"]
    }
)
```

### **Complex Update with User-Friendly Parameters**
```python
update(
    anomaly_id="5jXPdv",
    anomaly_data={
        "threshold": 1000,
        "period_minutes": 30,
        "alert_type": "threshold",
        "metric_type": "total_cost",
        "is_percentage": false,
        "email": "ops@company.com",
        "slack_config_id": "5jpABv",
        "filters": [
            {"field": "provider", "operator": "contains", "value": "openai"}
        ]
    }
)
```

## **Parameter Conversion Reference**

The update action supports user-friendly parameter names that are automatically converted:

| User-Friendly | API Format | Example |
|----------------|------------|---------|
| `email` | `notificationAddresses` | `"email": "user@co.com"` |
| `slack_config_id` | `slackConfigurations` | `"slack_config_id": "5jpABv"` |
| `alert_type` | `alertType` | `"alert_type": "threshold"` |
| `metric_type` | `metricType` | `"metric_type": "total_cost"` |
| `operator_type` | `operatorType` | `"operator_type": "greater_than"` |
| `period_minutes` | `periodDuration` | `"period_minutes": 15` |
| `is_percentage` | `isPercentage` | `"is_percentage": true` |
| `trigger_after_persists_duration` | `triggerAfterPersistsDuration` | `"trigger_after_persists_duration": "FIFTEEN_MINUTES"` |

### **Period Minutes Conversion**
- `1` → `"ONE_MINUTE"`
- `5` → `"FIVE_MINUTES"`
- `15` → `"FIFTEEN_MINUTES"`
- `30` → `"THIRTY_MINUTES"`
- `60` → `"ONE_HOUR"`
- `720` → `"TWELVE_HOURS"`
- `1440` → `"TWENTY_FOUR_HOURS"`

## **Common Error Fix**

**Common Mistake:**
```python
# Missing anomaly_data parameter
update(anomaly_id="5jXPdv", slack_config_id="5jpABv")
```

**Correct Usage:**
```python
# Properly structured with anomaly_data
update(
    anomaly_id="5jXPdv",
    anomaly_data={"slackConfigurations": ["5jpABv"]}
)
```

## **Available Fields for Updates**
- `name` - Alert name
- `threshold` - Alert threshold value
- `alertType` - Type of alert (THRESHOLD, CUMULATIVE_USAGE, RELATIVE_CHANGE)
- `enabled` - Enable/disable status
- `slackConfigurations` - Array of Slack config IDs
- `notificationAddresses` - Array of email addresses

**Pro Tip**: Use `get(anomaly_id="your_id")` first to see current alert configuration, then update specific fields as needed!""",
                    )
                ]

            else:
                return [
                    TextContent(
                        type="text",
                        text="""**Alert Examples**

## **Quick Start**
- `get_examples(alert_type="budget_threshold")` - Budget/quota examples with filtering
- `get_examples(alert_type="spike_detection")` - Real-time monitoring examples with filtering
- `get_examples(alert_type="relative_change")` - Trend detection with INCREASES_BY/DECREASES_BY
- `get_examples(alert_type="update")` - How to update existing alerts (including Slack setup)

## **Alert Type Decision**

### **Budget Threshold** (CUMULATIVE_USAGE)
- Tracks usage over time periods (daily, weekly, monthly, quarterly)
- Resets at the beginning of each period
- Perfect for budget limits and quota management
- **Supports metric filtering** for provider, model, customer, or product-specific budgets
- Example: "Alert when monthly OpenAI spending exceeds $2000"

### **Spike Detection** (THRESHOLD)
- Triggers immediately when values exceed thresholds
- Continuous monitoring with configurable check periods
- Perfect for spike detection and performance monitoring
- **Supports metric filtering** for provider, model, customer, or product-specific monitoring
- **Supports persistence-based triggering** with triggerAfterPersistsDuration
- Example: "Alert when GPT-4 cost per 15 minutes exceeds $200"

### **Relative Change** (RELATIVE_CHANGE)
- Detects percentage-based changes over time
- Uses INCREASES_BY or DECREASES_BY operators
- Supports daily, weekly, monthly, and quarterly periods
- Example: "Alert when costs increase by 20% daily"

## **Persistence-Based Alerting**

All alert types support the `triggerAfterPersistsDuration` parameter for sophisticated alert behavior:

### **How It Works**
- **periodDuration**: Evaluation frequency (e.g., every 5 minutes)
- **triggerAfterPersistsDuration**: Required persistence duration (e.g., 15 minutes)
- **Behavior**: Alert only triggers if condition persists for the specified duration

### **Example Use Cases**
- **Sustained Cost Spikes**: Only alert if costs stay high for 30 minutes
- **Persistent Errors**: Only alert if error rate remains elevated for 10 minutes
- **Budget Overruns**: Only alert if monthly budget exceeded for 3 consecutive days

### **Valid Duration Values**
ONE_MINUTE, FIVE_MINUTES, FIFTEEN_MINUTES, THIRTY_MINUTES, ONE_HOUR, TWELVE_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, DAILY, WEEKLY, MONTHLY, QUARTERLY

## **Metric Filtering Capabilities**
Both alert types support advanced filtering to target specific entities:
- **Provider filtering**: Monitor specific AI providers (OpenAI, Anthropic, Google, etc.)
- **Model filtering**: Monitor specific AI models (GPT-4, Claude-3, Gemini, etc.)
- **Customer filtering**: Monitor specific customers or organizations
- **Product filtering**: Monitor specific products or services

## **Creation Method Selection Guide**

The manage_alerts tool provides two complementary approaches for creating alerts:

### **Convenience Methods** (Recommended)
Simplified methods for common alert scenarios with automatic configuration:

**Features:**
- **Automatic field handling**: All required fields configured automatically
- **Type safety**: Direct parameters with built-in validation
- **Clear interface**: Simple function parameters, no complex objects
- **Reliable operation**: Designed for immediate success

**Use cases:**
- Basic threshold monitoring without advanced features
- Simple budget tracking and quota management
- Quick alert setup with minimal configuration
- Standard real-time monitoring scenarios

### **Standard Method** (Advanced)
Full-featured method for complex alert configurations:

**Features:**
- **Maximum flexibility**: Support for all configuration options
- **Advanced filtering**: Provider, model, customer, and product filtering
- **Custom operators**: Full control over comparison logic
- **Complex scenarios**: Multiple conditions and advanced rules

**Use cases:**
- Budget alerts with persistence-based triggering
- Advanced filtering by provider, model, or customer
- Custom operator configurations beyond standard thresholds
- Complex notification settings and webhook integrations

### **Method Selection Guide**
```
Basic threshold monitoring → create_threshold_alert()
Budget tracking → create_cumulative_usage_alert()
Advanced filtering/operators → create() with anomaly_data
Complex configurations → create() with anomaly_data
```

## **Quick Creation Methods** (Basic Alerts)
```bash
# Basic budget tracking (email optional if REVENIUM_DEFAULT_EMAIL is set)
create_cumulative_usage_alert(name="Budget", threshold=5000, period="monthly")

# Basic real-time monitoring (email optional if REVENIUM_DEFAULT_EMAIL is set)
create_threshold_alert(name="Cost Spike", threshold=100, period_minutes=5)

# With explicit email
create_cumulative_usage_alert(name="Budget", threshold=5000, period="monthly", email="admin@co.com")
create_threshold_alert(name="Cost Spike", threshold=100, period_minutes=5, email="ops@co.com")

# Threshold alerts with persistence
create_threshold_alert(name="Sustained Cost Spike", threshold=200, period_minutes=5, triggerAfterPersistsDuration="FIFTEEN_MINUTES", email="ops@co.com")

```

## **Advanced Alert Creation** (Full create() Action)

### **When You Need Advanced Features:**
- **Persistence-based alerting**: triggerAfterPersistsDuration parameter
- **Provider/model filtering**: Monitor specific AI providers or models
- **Complex configurations**: Multiple filters, custom operators

```bash
# Advanced filtering (use create action)
create(resource_type="anomalies", anomaly_data={
  "name": "OpenAI Budget Alert",
  "alertType": "CUMULATIVE_USAGE",
  "metricType": "TOTAL_COST",
  "threshold": 2000,
  "periodDuration": "MONTHLY",
  "filters": [{"dimension": "PROVIDER", "operator": "CONTAINS", "value": "openai"}]
})

# Persistence-based alerting (use create action)
create(resource_type="anomalies", anomaly_data={
  "name": "Sustained Cost Spike Alert",
  "alertType": "THRESHOLD",
  "metricType": "TOTAL_COST",
  "threshold": 200,
  "periodDuration": "FIVE_MINUTES",
  "triggerAfterPersistsDuration": "FIFTEEN_MINUTES",
  "email": "finance@company.com"
})

create(resource_type="anomalies", anomaly_data={
  "name": "Persistent Budget Overrun",
  "alertType": "CUMULATIVE_USAGE",
  "metricType": "TOTAL_COST",
  "threshold": 5000,
  "periodDuration": "MONTHLY",
  "triggerAfterPersistsDuration": "SEVEN_DAYS",
  "email": "finance@company.com"
})

# Natural language (uses REVENIUM_DEFAULT_EMAIL automatically)
create_from_text(text="Alert when monthly OpenAI spending exceeds $2000")
```

## **Best Practices and Common Patterns**

### **Recommended Approach: Convenience Methods**
For most alert scenarios, convenience methods provide the simplest and most reliable approach:
```bash
# Real-time monitoring
create_threshold_alert(name="Cost Spike Alert", threshold=100, period_minutes=5)

# Budget tracking
create_cumulative_usage_alert(name="Monthly Budget", threshold=1000, period="monthly")
```

### **Advanced Configuration: Standard Method**
Use the standard method when you need complex configurations:
```bash
# Advanced filtering and custom operators
create(resource_type="anomalies", anomaly_data={
  "name": "Advanced Alert",
  "alertType": "THRESHOLD",
  "metricType": "TOTAL_COST",
  "operatorType": "GREATER_THAN",
  "threshold": 100,
  "filters": [{"dimension": "PROVIDER", "operator": "CONTAINS", "value": "openai"}]
})
```

### **Method Selection Guide**
- **Simple alerts**: Use convenience methods (`create_threshold_alert`, `create_cumulative_usage_alert`)
- **Relative change detection**: Use `create` with `alertType: RELATIVE_CHANGE` and `INCREASES_BY`/`DECREASES_BY` operators
- **Complex filtering**: Use standard method with `anomaly_data`
- **Custom operators**: Use standard method with `anomaly_data`
- **Multiple conditions**: Use standard method with `anomaly_data`

**Usage Guidance**:
- Use metric filtering to create targeted alerts instead of global thresholds
- Always specify the alert type explicitly to get the behavior you want
- Check specific alert type examples for detailed filtering syntax""",
                    )
                ]

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Error in get_examples: {e}")
            raise ToolError(
                message=f"Failed to get alert examples: {str(e)}",
                error_code=ErrorCodes.API_ERROR,
                field="get_examples",
                value=str(e),
                suggestions=[
                    "Try calling get_examples() without parameters for general examples",
                    "Use alert_type='budget_threshold' for budget tracking examples",
                    "Use alert_type='spike_detection' for real-time monitoring examples",
                    "Use alert_type='relative_change' for trend detection examples",
                    "Check if the alert_type parameter is spelled correctly",
                ],
                examples={
                    "general_examples": "get_examples()",
                    "budget_examples": "get_examples(alert_type='budget_threshold')",
                    "monitoring_examples": "get_examples(alert_type='spike_detection')",
                    "relative_change_examples": "get_examples(alert_type='relative_change')",
                },
            )

    async def _handle_get_agent_summary(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get agent summary."""
        return [
            TextContent(
                type="text",
                text="""**Alert Management Agent Summary**

**Primary Purpose**: Comprehensive AI anomaly detection and alert management for the Revenium platform.

**Key Capabilities**:
• **Smart Alert Creation**: Natural language processing for intuitive alert setup
• **Three Alert Types**: Budget Threshold tracking, Spike Detection monitoring, and Relative Change trend detection
• **Rich Analytics**: Pattern analysis, frequency tracking, and performance metrics
• **Bulk Operations**: Enable/disable multiple alerts efficiently
• **Investigation Tools**: Natural language querying of alert history

**Best Practices**:
1. **Always start with** `get_capabilities()` to understand available options
2. **Use specific methods** like `create_cumulative_usage_alert()` for clarity
3. **Email notifications**: Set REVENIUM_DEFAULT_EMAIL environment variable or provide email parameter
4. **Test configurations** with `validate()` before creating alerts
5. **Monitor alert patterns** with analytics to optimize thresholds

**Common Workflows**:
• **Setup**: capabilities → examples → create → validate
• **Investigation**: query → get_metrics → analyze patterns
• **Maintenance**: list → update thresholds → bulk enable/disable

**Integration**: Works seamlessly with products, sources, and team management for comprehensive monitoring.""",
            )
        ]

    def _resolve_notification_email(self, provided_email: Optional[str] = None) -> str:
        """Resolve notification email address with smart fallback logic.

        Args:
            provided_email: Email provided by user (optional)

        Returns:
            Resolved email address

        Raises:
            ValidationError: If no email can be resolved
        """
        import os

        # 1. Use provided email if available
        if provided_email and provided_email.strip():
            return provided_email.strip()

        # 2. Fall back to environment variable or discovered configuration
        from ..config_store import get_discovered_config_sync

        # Check environment variable first
        env_email = os.getenv("REVENIUM_DEFAULT_EMAIL")
        if env_email and env_email.strip() and env_email != "dummy@email.com":
            logger.debug(f"Using REVENIUM_DEFAULT_EMAIL: {env_email}")
            return env_email.strip()

        # Check discovered configuration
        discovered = get_discovered_config_sync()
        if discovered.default_email and discovered.default_email.strip():
            logger.debug(f"Using discovered email: {discovered.default_email}")
            return discovered.default_email.strip()

        # 3. No email available - raise structured error with clear guidance
        from ..exceptions import ValidationError

        raise ValidationError(
            message="Email address is required for alert notifications",
            field="email",
            expected="Valid email address or REVENIUM_DEFAULT_EMAIL environment variable",
            suggestion="Provide email parameter or set REVENIUM_DEFAULT_EMAIL environment variable",
            example={
                "with_email": "create_threshold_alert(name='Alert', threshold=100, email='admin@company.com')",
                "env_setup": "Add REVENIUM_DEFAULT_EMAIL='monitoring@company.com' to your .env file",
                "mcp_config": "Add REVENIUM_DEFAULT_EMAIL to your Claude Desktop configuration",
                "best_practice": "MONITORING: Set a dedicated monitoring email for all alerts",
            },
        )

    def _resolve_notification_config(
        self, provided_email: Optional[str] = None, slack_config_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Resolve notification configuration with email and Slack support.

        Args:
            provided_email: Email provided by user (optional)
            slack_config_id: Slack configuration ID provided by user (optional)

        Returns:
            Dictionary containing notification configuration

        Raises:
            ValidationError: If no email can be resolved
        """
        config = {}

        # Email resolution (existing pattern)
        email = self._resolve_notification_email(provided_email)
        config["notificationAddresses"] = [email]

        # Slack resolution (new pattern)
        if slack_config_id:
            config["slackConfigurations"] = [slack_config_id]
        else:
            # Try default Slack configuration
            from ..config_store import get_config_value

            default_slack = get_config_value("REVENIUM_DEFAULT_SLACK_CONFIG_ID")
            if default_slack:
                config["slackConfigurations"] = [default_slack]
                logger.debug(f"Using default Slack configuration: {default_slack}")
            else:
                config["slackConfigurations"] = []

        return config

    async def _post_alert_creation_prompting(
        self,
        alert_data: Dict[str, Any],  # noqa: ARG002
        notification_config: Dict[str, Any],
        alert_context: Dict[str, Any],
    ) -> str:
        """Handle post-creation Slack prompting and configuration.

        Args:
            alert_data: The created alert data
            notification_config: Current notification configuration
            alert_context: Context about the alert (name, type, etc.)

        Returns:
            Formatted prompting result message
        """
        try:
            # Check if Slack prompting is appropriate
            if not self.should_prompt_for_slack(notification_config):
                return ""

            # Generate the prompt
            prompt_result = await self.prompt_for_slack_addition(alert_context)

            if not prompt_result.get("should_prompt"):
                return ""

            # Format the prompting message
            prompting_message = self.format_slack_prompting_result(prompt_result)

            return prompting_message

        except Exception as e:
            # If prompting fails, don't block the main workflow
            logger.warning(f"Slack prompting failed: {e}")
            return ""

    async def _handle_create_cumulative_usage_alert(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Create a Budget Threshold alert for budget/quota tracking."""
        try:
            name = arguments.get("name")
            threshold = arguments.get("threshold")
            period = arguments.get("period", "monthly").lower()
            provided_email = arguments.get("email")
            slack_config_id = arguments.get("slack_config_id")
            # CRITICAL FIX: Add metric type support
            metric_type = arguments.get("metric", arguments.get("metric_type", "TOTAL_COST"))

            # Resolve notification configuration (email + Slack)
            try:
                notification_config = self._resolve_notification_config(
                    provided_email, slack_config_id
                )
            except ValidationError as e:
                return [TextContent(type="text", text=e.format_user_message())]

            # Validation
            if not name:
                error = create_structured_missing_parameter_error(
                    parameter_name="name",
                    action="create_cumulative_usage_alert",
                    examples={
                        "usage": "create_cumulative_usage_alert(name='Monthly Usage Alert', threshold=1000, period='monthly', email='admin@company.com')",
                        "valid_format": "Alert name should be descriptive",
                        "example_names": [
                            "Monthly Usage Alert",
                            "Cost Threshold Alert",
                            "Token Limit Alert",
                        ],
                    },
                )
                return [TextContent(type="text", text=format_structured_error(error))]
            if not threshold:
                error = create_structured_missing_parameter_error(
                    parameter_name="threshold",
                    action="create_cumulative_usage_alert",
                    examples={
                        "usage": "create_cumulative_usage_alert(name='Usage Alert', threshold=1000, period='monthly', email='admin@company.com')",
                        "valid_format": "Threshold should be a positive number",
                        "example_values": [100, 1000, 5000],
                    },
                )
                return [TextContent(type="text", text=format_structured_error(error))]

            # Validate threshold is a positive number
            try:
                threshold_value = float(threshold)
                if threshold_value <= 0:
                    raise ValueError("Threshold must be positive")
            except (ValueError, TypeError):
                error = create_structured_validation_error(
                    message=f"Invalid threshold value: {threshold}",
                    field="threshold",
                    value=threshold,
                    suggestions=[
                        "Provide a positive numeric threshold value",
                        "Use a reasonable threshold based on your usage patterns",
                        "Consider your metric scale (e.g., $1000 for monthly costs, 10000 for token counts)",
                    ],
                    examples={
                        "monthly_cost_budget": 1000.0,
                        "weekly_token_budget": 50000.0,
                        "daily_request_budget": 10000.0,
                        "quarterly_cost_budget": 5000.0,
                    },
                )
                return [TextContent(type="text", text=format_structured_error(error))]

            # Let the API handle metric validation based on UCM capabilities
            if metric_type:
                logger.info(f"Creating cumulative usage alert with metric: {metric_type}")
                # Note: Metric validation is handled by the API based on UCM capabilities

            # Map period to API format
            period_mapping = {
                "daily": "DAILY",
                "weekly": "WEEKLY",
                "monthly": "MONTHLY",
                "quarterly": "QUARTERLY",
            }

            tracking_period = period_mapping.get(period)
            if not tracking_period:
                error = create_structured_validation_error(
                    message=f"Invalid period '{period}'",
                    field="period",
                    value=period,
                    suggestions=[
                        "Use one of the supported period values",
                        "Check the period name for typos",
                        "Choose a period that matches your monitoring needs",
                    ],
                    examples={
                        "valid_periods": ["daily", "weekly", "monthly", "quarterly"],
                        "usage": "create_cumulative_usage_alert(period='monthly')",
                        "recommendations": {
                            "daily": "For high-frequency monitoring",
                            "weekly": "For regular usage tracking",
                            "monthly": "For billing cycle monitoring",
                            "quarterly": "For long-term trend analysis",
                        },
                    },
                )
                return [TextContent(type="text", text=format_structured_error(error))]

            # Create anomaly data using correct direct Revenium API format
            anomaly_data = {
                "label": name,
                "name": name,
                "alertType": "CUMULATIVE_USAGE",
                "metricType": metric_type,  # CRITICAL FIX: Use the specified metric type instead of hardcoded TOTAL_COST
                "operatorType": "GREATER_THAN",
                "threshold": float(threshold),
                "isPercentage": False,
                "periodDuration": tracking_period,  # For cumulative usage: DAILY, WEEKLY, MONTHLY, QUARTERLY
                "description": f"Cumulative usage alert for {metric_type} {period} tracking (threshold: {threshold})",
                "enabled": True,
                "notificationAddresses": notification_config["notificationAddresses"],
                "slackConfigurations": notification_config["slackConfigurations"],
                "triggerAfterPersistsDuration": "",
                "filters": [],
            }

            # Use AnomalyManager with direct API format validation
            result = await self.anomaly_manager.create_anomaly(client, anomaly_data)

            # Add Slack prompting if appropriate
            alert_context = {
                "name": name,
                "type": "cumulative usage alert",
                "metric": metric_type,
                "threshold": threshold,
                "period": period,
            }

            prompting_message = await self._post_alert_creation_prompting(
                anomaly_data, notification_config, alert_context
            )

            # If we have prompting message, append it to the result
            if prompting_message and result:
                # Extract the text from the result and append prompting
                if isinstance(result, list) and len(result) > 0:
                    original_text = result[0].text if hasattr(result[0], "text") else str(result[0])
                    enhanced_text = original_text + prompting_message
                    result[0] = TextContent(type="text", text=enhanced_text)

            return result

        except Exception as e:
            logger.error(f"Error creating cumulative usage alert: {e}")
            error = ResourceError(
                message=f"Failed to create cumulative usage alert: {str(e)}",
                error_code=ErrorCodes.RESOURCE_ERROR,
                resource_type="cumulative_usage_alert",
                suggestions=[
                    "Check that all required parameters are valid",
                    "Verify your API credentials and permissions",
                    "Try creating a simpler alert first",
                    "Use validate() to check your alert configuration",
                ],
                examples={
                    "retry": "Try the same request again",
                    "validate_first": "validate(alert_data={...}) before creating",
                    "simple_alert": "Use create_simple_alert() for basic alerts",
                },
            )
            return [TextContent(type="text", text=format_structured_error(error))]

    async def _handle_create_threshold_alert(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Create a Spike Detection alert for real-time monitoring with optional persistence support."""
        try:
            name = arguments.get("name")
            threshold = arguments.get("threshold")
            period_minutes = arguments.get("period_minutes", 5)
            provided_email = arguments.get("email")
            slack_config_id = arguments.get("slack_config_id")
            # CRITICAL FIX: Add metric type support
            metric_type = arguments.get("metric", arguments.get("metric_type", "TOTAL_COST"))
            # NEW: Add triggerAfterPersistsDuration support
            trigger_after_persists_duration = arguments.get("triggerAfterPersistsDuration", "")

            # Resolve notification configuration (email + Slack)
            try:
                notification_config = self._resolve_notification_config(
                    provided_email, slack_config_id
                )
            except ValidationError as e:
                return [TextContent(type="text", text=e.format_user_message())]

            # Validation with structured error handling
            if not name:
                raise create_structured_missing_parameter_error(
                    parameter_name="name",
                    action="create threshold alert",
                    examples={
                        "usage": "create_threshold_alert(name='High API Usage', threshold=1000, email='admin@company.com')",
                        "valid_format": "Alert name should be descriptive and unique",
                        "example_names": [
                            "High API Usage",
                            "Error Rate Alert",
                            "Token Limit Warning",
                        ],
                    },
                )
            if not threshold:
                raise create_structured_missing_parameter_error(
                    parameter_name="threshold",
                    action="create threshold alert",
                    examples={
                        "usage": "create_threshold_alert(name='High Usage', threshold=1000, email='admin@company.com')",
                        "valid_format": "Threshold should be a positive numeric value",
                        "example_values": [100, 1000, 5000, 10000],
                    },
                )

            # Validate threshold is a positive number
            try:
                threshold_value = float(threshold)
                if threshold_value <= 0:
                    raise ValueError("Threshold must be positive")
            except (ValueError, TypeError):
                raise create_structured_validation_error(
                    message=f"Invalid threshold value: {threshold}",
                    field="threshold",
                    value=threshold,
                    suggestions=[
                        "Provide a positive numeric threshold value",
                        "Use a reasonable threshold based on your monitoring needs",
                        "Consider your metric scale (e.g., $100 for costs, 1000 for token counts)",
                    ],
                    examples={
                        "cost_monitoring": 100.0,
                        "token_monitoring": 1000.0,
                        "error_rate_monitoring": 5.0,
                        "performance_monitoring": 500.0,
                    },
                )

            # Let the API handle metric validation based on UCM capabilities
            if metric_type:
                logger.info(f"Creating threshold alert with metric: {metric_type}")
                # Note: Metric validation is handled by the API based on UCM capabilities

            # Map period minutes to API format
            period_mapping = {
                1: "ONE_MINUTE",
                5: "FIVE_MINUTES",
                10: "TEN_MINUTES",
                15: "FIFTEEN_MINUTES",
                30: "THIRTY_MINUTES",
                60: "ONE_HOUR",
            }

            period_duration = period_mapping.get(int(period_minutes))
            if not period_duration:
                raise create_structured_validation_error(
                    message=f"Invalid period_minutes '{period_minutes}'",
                    field="period_minutes",
                    value=period_minutes,
                    suggestions=[
                        "Use one of the supported period durations",
                        "Check the period_minutes value for typos",
                        "Ensure the period aligns with monitoring requirements",
                        "Consider using standard monitoring intervals",
                    ],
                    examples={
                        "valid_periods": [1, 5, 10, 15, 30, 60],
                        "usage": "create_threshold_alert(period_minutes=15, ...)",
                        "monitoring_context": "Period determines how frequently the alert condition is evaluated",
                    },
                )

            # Validate triggerAfterPersistsDuration if provided
            if trigger_after_persists_duration:
                # Valid duration values from TriggerDuration enum
                valid_durations = [
                    "ONE_MINUTE",
                    "FIVE_MINUTES",
                    "FIFTEEN_MINUTES",
                    "THIRTY_MINUTES",
                    "ONE_HOUR",
                    "TWELVE_HOURS",
                    "TWENTY_FOUR_HOURS",
                    "SEVEN_DAYS",
                    "THIRTY_DAYS",
                    "DAILY",
                    "WEEKLY",
                    "MONTHLY",
                    "QUARTERLY",
                ]

                if trigger_after_persists_duration not in valid_durations:
                    raise create_structured_validation_error(
                        message=f"Invalid triggerAfterPersistsDuration '{trigger_after_persists_duration}'",
                        field="triggerAfterPersistsDuration",
                        value=trigger_after_persists_duration,
                        suggestions=[
                            "Use one of the supported duration values",
                            "Check the triggerAfterPersistsDuration value for typos",
                            "Ensure the duration aligns with your persistence requirements",
                            "Consider how long the condition should persist before triggering",
                        ],
                        examples={
                            "short_term": [
                                "ONE_MINUTE",
                                "FIVE_MINUTES",
                                "FIFTEEN_MINUTES",
                                "THIRTY_MINUTES",
                            ],
                            "medium_term": ["ONE_HOUR", "TWELVE_HOURS", "TWENTY_FOUR_HOURS"],
                            "long_term": ["SEVEN_DAYS", "THIRTY_DAYS"],
                            "periodic": ["DAILY", "WEEKLY", "MONTHLY", "QUARTERLY"],
                            "usage": "create_threshold_alert(triggerAfterPersistsDuration='FIFTEEN_MINUTES', ...)",
                            "persistence_context": "Duration the alert condition must persist before triggering",
                        },
                    )

            # Create anomaly data using correct direct Revenium API format
            description = f"Threshold alert for {metric_type} monitoring every {period_minutes} minutes (threshold: {threshold})"
            if trigger_after_persists_duration:
                description += f" with {trigger_after_persists_duration} persistence"

            anomaly_data = {
                "label": name,
                "name": name,
                "alertType": "THRESHOLD",
                "metricType": metric_type,  # CRITICAL FIX: Use the specified metric type instead of hardcoded TOTAL_COST
                "operatorType": "GREATER_THAN",
                "threshold": float(threshold),
                "isPercentage": False,
                "periodDuration": period_duration,
                "description": description,
                "enabled": True,
                "notificationAddresses": notification_config["notificationAddresses"],
                "slackConfigurations": notification_config["slackConfigurations"],
                "triggerAfterPersistsDuration": trigger_after_persists_duration,
                "filters": [],
            }

            # Use AnomalyManager with direct API format validation
            return await self.anomaly_manager.create_anomaly(client, anomaly_data)

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Error creating threshold alert: {e}")
            raise ToolError(
                message=f"Failed to create threshold alert: {str(e)}",
                error_code=ErrorCodes.API_ERROR,
                field="threshold_alert_creation",
                value=str(e),
                suggestions=[
                    "Check that all required parameters are provided correctly",
                    "Verify API connectivity and authentication",
                    "Ensure the alert name is unique",
                    "Use get_capabilities() to verify alert creation requirements",
                    "Try creating a simpler alert first to test connectivity",
                ],
                examples={
                    "retry_guidance": "Fix the identified issue and retry the alert creation",
                    "troubleshooting": [
                        "Check API credentials",
                        "Verify alert parameters",
                        "Test with basic alert",
                    ],
                    "monitoring_context": "CRITICAL: Alert creation failure means no monitoring will be active",
                },
            )

    async def _handle_create_from_text(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Create alert from natural language text."""
        try:
            text = arguments.get("text")
            if not text:
                raise create_structured_missing_parameter_error(
                    parameter_name="text",
                    action="create alert from text",
                    examples={
                        "usage": "create_from_text(text='Alert me when API errors exceed 5% in 10 minutes')",
                        "valid_format": "Natural language description of the alert condition",
                        "example_descriptions": [
                            "Alert me when API errors exceed 5% in 10 minutes",
                            "Notify when token usage goes above 10000 per hour",
                            "Send alert if request rate drops below 100 per minute",
                        ],
                    },
                )

            # Use semantic processor to parse the text
            parsed_data = self.semantic_processor.parse_alert_request(text)

            if not parsed_data or not parsed_data.get("detection_rules"):
                # Fallback to simple parsing
                parsed_data = self._simple_parse_alert_text(text)

            # Use AnomalyManager with direct API format validation
            return await self.anomaly_manager.create_anomaly(client, parsed_data)

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Error creating alert from text: {e}")
            raise ToolError(
                message=f"Failed to create alert from text: {str(e)}",
                error_code=ErrorCodes.API_ERROR,
                field="natural_language_alert_creation",
                value=str(e),
                suggestions=[
                    "Try using specific creation methods like create_cumulative_usage_alert() or create_threshold_alert()",
                    "Ensure the natural language description is clear and specific",
                    "Check that all required alert parameters can be extracted from the text",
                    "Verify API connectivity and authentication",
                    "Use simpler, more direct language for alert conditions",
                ],
                examples={
                    "alternative_methods": [
                        "create_threshold_alert()",
                        "create_cumulative_usage_alert()",
                    ],
                    "better_descriptions": [
                        "Alert when API errors exceed 5% in 10 minutes",
                        "Notify when token usage goes above 10000 per hour",
                    ],
                    "troubleshooting": "Natural language processing may fail with complex or ambiguous descriptions",
                },
            )

    def _simple_parse_alert_text(self, text: str) -> Dict[str, Any]:
        """Simple fallback parsing for natural language text."""
        text_lower = text.lower()

        # Determine alert type with better logic
        cumulative_keywords = [
            "monthly",
            "weekly",
            "daily",
            "budget",
            "quota",
            "limit",
            "total",
            "cumulative",
            "period",
        ]
        threshold_keywords = [
            "spike",
            "exceeds",
            "above",
            "real-time",
            "immediate",
            "instant",
            "per minute",
            "per hour",
        ]

        # Check for explicit threshold indicators first
        is_threshold = any(word in text_lower for word in threshold_keywords)
        is_cumulative = any(word in text_lower for word in cumulative_keywords)

        # Default logic: if both or neither, prefer cumulative for budget-like terms
        if is_threshold and not is_cumulative:
            alert_type = "THRESHOLD"
            period_duration = "FIVE_MINUTES"
            tracking_period = None
        elif is_cumulative or "budget" in text_lower or "monthly" in text_lower:
            alert_type = "CUMULATIVE_USAGE"
            period_duration = None
            # Determine tracking period
            if "daily" in text_lower:
                tracking_period = "DAILY"
            elif "weekly" in text_lower:
                tracking_period = "WEEKLY"
            elif "quarterly" in text_lower:
                tracking_period = "QUARTERLY"
            else:
                tracking_period = "MONTHLY"  # default
        else:
            # Default to threshold for unclear cases
            alert_type = "THRESHOLD"
            period_duration = "FIVE_MINUTES"
            tracking_period = None

        # CRITICAL FIX: Extract metric type from text
        metric_type = "TOTAL_COST"  # default
        metric_keywords = {
            "token": "TOKEN_COUNT",
            "tokens": "TOKEN_COUNT",
            "input token": "INPUT_TOKEN_COUNT",
            "output token": "OUTPUT_TOKEN_COUNT",
            "tokens per minute": "TOKENS_PER_MINUTE",
            "token rate": "TOKENS_PER_MINUTE",
            "requests per minute": "REQUESTS_PER_MINUTE",
            "request rate": "REQUESTS_PER_MINUTE",
            "error rate": "ERROR_RATE",
            "error count": "ERROR_COUNT",
            "errors": "ERROR_COUNT",
            "cost per transaction": "COST_PER_TRANSACTION",
            "cost": "TOTAL_COST",
            "spending": "TOTAL_COST",
        }

        # Check for metric keywords in text (case insensitive)
        for keyword, metric in metric_keywords.items():
            if keyword in text_lower:
                metric_type = metric
                break

        # Extract threshold
        import re

        threshold_match = re.search(r"[\$]?(\d+(?:,\d{3})*(?:\.\d+)?)", text)
        if threshold_match:
            # Remove commas and convert to float
            threshold_str = threshold_match.group(1).replace(",", "")
            threshold = float(threshold_str)
        else:
            threshold = 100.0

        # Generate name from text
        name = (
            f"Auto-generated Alert: {text[:50]}..."
            if len(text) > 50
            else f"Auto-generated Alert: {text}"
        )

        # Resolve notification configuration (email + Slack)
        try:
            notification_config = self._resolve_notification_config()
        except ValidationError:
            # Fallback to basic email resolution for text parsing
            import os

            from ..config_store import get_discovered_config_sync

            env_email = os.getenv("REVENIUM_DEFAULT_EMAIL")
            if env_email and env_email != "dummy@email.com":
                notification_email = env_email
            else:
                # Try discovered configuration
                discovered = get_discovered_config_sync()
                if discovered.default_email and discovered.default_email.strip():
                    notification_email = discovered.default_email
                else:
                    notification_email = "admin@example.com"

            notification_config = {
                "notificationAddresses": [notification_email],
                "slackConfigurations": [],
            }

        # Build alert data using correct direct Revenium API format
        alert_data = {
            "label": name,
            "name": name,
            "alertType": alert_type,
            "metricType": metric_type,  # CRITICAL FIX: Use parsed metric type instead of hardcoded TOTAL_COST
            "operatorType": "GREATER_THAN",
            "threshold": threshold,
            "isPercentage": False,
            "description": f"Alert created from: {text} (metric: {metric_type})",
            "enabled": True,
            "notificationAddresses": notification_config["notificationAddresses"],
            "slackConfigurations": notification_config["slackConfigurations"],
            "triggerAfterPersistsDuration": "",
            "filters": [],
        }

        # Add type-specific period duration
        if alert_type == "CUMULATIVE_USAGE":
            alert_data["periodDuration"] = tracking_period  # DAILY, WEEKLY, MONTHLY, QUARTERLY
        else:  # THRESHOLD
            alert_data["periodDuration"] = period_duration  # FIVE_MINUTES, ONE_HOUR, etc.

        return alert_data

    async def _handle_create_simple(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Create a simple alert with smart defaults."""
        try:
            name = arguments.get("name", "Simple Alert")
            provided_email = arguments.get("email")
            slack_config_id = arguments.get("slack_config_id")
            metric = arguments.get("metric", "TOTAL_COST")
            threshold = arguments.get("threshold", 100)

            # Resolve notification configuration (email + Slack)
            try:
                notification_config = self._resolve_notification_config(
                    provided_email, slack_config_id
                )
            except ValidationError as e:
                return [TextContent(type="text", text=e.format_user_message())]

            # Create simple threshold alert using correct direct Revenium API format
            anomaly_data = {
                "label": name,
                "name": name,
                "alertType": "THRESHOLD",
                "metricType": metric,
                "operatorType": "GREATER_THAN",
                "threshold": float(threshold),
                "isPercentage": False,
                "periodDuration": "FIVE_MINUTES",
                "description": f"Simple alert for {metric} monitoring",
                "enabled": True,
                "notificationAddresses": notification_config["notificationAddresses"],
                "slackConfigurations": notification_config["slackConfigurations"],
                "triggerAfterPersistsDuration": "",
                "filters": [],
            }

            # Use AnomalyManager with direct API format validation
            return await self.anomaly_manager.create_anomaly(client, anomaly_data)

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Error creating simple alert: {e}")
            raise ToolError(
                message=f"Failed to create simple alert: {str(e)}",
                error_code=ErrorCodes.API_ERROR,
                field="simple_alert_creation",
                value=str(e),
                suggestions=[
                    "Check that all required parameters are provided correctly",
                    "Verify API connectivity and authentication",
                    "Ensure the alert configuration is valid",
                    "Try using create_threshold_alert() for more specific control",
                    "Use get_capabilities() to verify alert creation requirements",
                ],
                examples={
                    "alternative_methods": [
                        "create_threshold_alert()",
                        "create_cumulative_usage_alert()",
                    ],
                    "retry_guidance": "Fix the identified issue and retry the alert creation",
                    "monitoring_context": "BILLING SAFETY: Simple alerts help prevent unexpected usage charges",
                },
            )

    # ============================================================================
    # BULK OPERATIONS (from alert_bulk_methods.py and alert_enable_disable_methods.py)
    # ============================================================================

    async def _handle_enable_anomaly(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Enable a single anomaly/alert."""
        anomaly_id = arguments.get("anomaly_id")

        if not anomaly_id:
            raise create_structured_missing_parameter_error(
                parameter_name="anomaly_id",
                action="enable anomaly",
                examples={
                    "usage": "enable(anomaly_id='alert-123')",
                    "valid_format": "Anomaly ID should be a string identifier",
                    "example_ids": ["alert-123", "anomaly-456", "threshold-789"],
                    "monitoring_context": "CRITICAL: Enabling anomalies activates monitoring and alerting",
                },
            )

        try:
            # Get current anomaly data and update enabled field
            current_anomaly = await client.get_anomaly_by_id(str(anomaly_id))
            update_data = current_anomaly.copy()
            update_data["enabled"] = True
            updated_anomaly = await client.update_anomaly(str(anomaly_id), update_data)

            return [
                TextContent(
                    type="text",
                    text=f"**Alert Enabled Successfully**\n\n"
                    f"**Name**: {updated_anomaly.get('name', 'Unnamed')}\n"
                    f"**ID**: `{anomaly_id}`\n"
                    f"**Status**: Now enabled and monitoring",
                )
            ]

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Error enabling anomaly {anomaly_id}: {e}")
            raise ToolError(
                message=f"Failed to enable alert {anomaly_id}: {str(e)}",
                error_code=ErrorCodes.API_ERROR,
                field="anomaly_enable",
                value=str(e),
                suggestions=[
                    "Verify the anomaly_id exists and is valid",
                    "Check API connectivity and authentication",
                    "Ensure the alert is not already enabled",
                    "Use list() to verify the alert exists before enabling",
                    "Try get_anomaly_status() to check current state",
                ],
                examples={
                    "verification_steps": [
                        "list()",
                        "get_anomaly_status()",
                        "enable(anomaly_id='valid_id')",
                    ],
                    "troubleshooting": [
                        "Check anomaly ID spelling",
                        "Verify alert exists",
                        "Test API connectivity",
                    ],
                    "monitoring_context": "CRITICAL: Failed enable means monitoring will not be active",
                },
            )

    async def _handle_disable_anomaly(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Disable a single anomaly/alert."""
        anomaly_id = arguments.get("anomaly_id")

        if not anomaly_id:
            raise create_structured_missing_parameter_error(
                parameter_name="anomaly_id",
                action="disable anomaly",
                examples={
                    "usage": "disable(anomaly_id='alert-123')",
                    "valid_format": "Anomaly ID should be a string identifier",
                    "example_ids": ["alert-123", "anomaly-456", "threshold-789"],
                    "monitoring_context": "CRITICAL: Disabling anomalies stops monitoring and alerting",
                },
            )

        try:
            # Get current anomaly data and update enabled field
            current_anomaly = await client.get_anomaly_by_id(str(anomaly_id))
            update_data = current_anomaly.copy()
            update_data["enabled"] = False
            updated_anomaly = await client.update_anomaly(str(anomaly_id), update_data)

            return [
                TextContent(
                    type="text",
                    text=f"**Alert Disabled Successfully**\n\n"
                    f"**Name**: {updated_anomaly.get('name', 'Unnamed')}\n"
                    f"**ID**: `{anomaly_id}`\n"
                    f"**Status**: Now disabled and not monitoring",
                )
            ]

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Error disabling anomaly {anomaly_id}: {e}")
            raise ToolError(
                message=f"Failed to disable alert {anomaly_id}: {str(e)}",
                error_code=ErrorCodes.API_ERROR,
                field="anomaly_disable",
                value=str(e),
                suggestions=[
                    "Verify the anomaly_id exists and is valid",
                    "Check API connectivity and authentication",
                    "Ensure the alert is not already disabled",
                    "Use list() to verify the alert exists before disabling",
                    "Try get_anomaly_status() to check current state",
                ],
                examples={
                    "verification_steps": [
                        "list()",
                        "get_anomaly_status()",
                        "disable(anomaly_id='valid_id')",
                    ],
                    "troubleshooting": [
                        "Check anomaly ID spelling",
                        "Verify alert exists",
                        "Test API connectivity",
                    ],
                    "monitoring_context": "CRITICAL: Failed disable means monitoring may remain active unexpectedly",
                },
            )

    async def _handle_enable_multiple(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Enable multiple anomalies/alerts."""
        anomaly_ids = arguments.get("anomaly_ids", [])

        if not anomaly_ids:
            raise create_structured_missing_parameter_error(
                parameter_name="anomaly_ids",
                action="enable multiple anomalies",
                examples={
                    "usage": "enable_multiple(anomaly_ids=['alert-123', 'alert-456'])",
                    "valid_format": "List of anomaly ID strings",
                    "example_lists": [
                        ["alert-123", "alert-456"],
                        ["threshold-789", "error-rate-101"],
                    ],
                    "monitoring_context": "CRITICAL: Bulk enabling activates monitoring for multiple alerts simultaneously",
                },
            )

        results = []
        successful = 0
        failed = 0

        for anomaly_id in anomaly_ids:
            try:
                current_anomaly = await client.get_anomaly_by_id(anomaly_id)
                update_data = current_anomaly.copy()
                update_data["enabled"] = True
                updated_anomaly = await client.update_anomaly(anomaly_id, update_data)
                results.append(f"Success: {updated_anomaly.get('name', anomaly_id)}")
                successful += 1
            except ToolError:
                # Re-raise ToolError exceptions without modification
                # This preserves helpful error messages with specific suggestions
                raise
            except Exception as e:
                results.append(f"Failed: {anomaly_id}: {str(e)}")
                failed += 1

        result_text = (
            f"**Bulk Enable Results**\n\n"
            f"**Total Processed:** {len(anomaly_ids)}\n"
            f"**Successful:** {successful}\n"
            f"**Failed:** {failed}\n\n"
            f"**Details:**\n" + "\n".join(results)
        )

        return [TextContent(type="text", text=result_text)]

    async def _handle_disable_multiple(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Disable multiple anomalies/alerts."""
        anomaly_ids = arguments.get("anomaly_ids", [])

        if not anomaly_ids:
            raise create_structured_missing_parameter_error(
                parameter_name="anomaly_ids",
                action="disable multiple anomalies",
                examples={
                    "usage": "disable_multiple(anomaly_ids=['alert-123', 'alert-456'])",
                    "valid_format": "List of anomaly ID strings",
                    "example_lists": [
                        ["alert-123", "alert-456"],
                        ["threshold-789", "error-rate-101"],
                    ],
                    "monitoring_context": "CRITICAL: Bulk disabling stops monitoring for multiple alerts simultaneously",
                },
            )

        results = []
        successful = 0
        failed = 0

        for anomaly_id in anomaly_ids:
            try:
                current_anomaly = await client.get_anomaly_by_id(anomaly_id)
                update_data = current_anomaly.copy()
                update_data["enabled"] = False
                updated_anomaly = await client.update_anomaly(anomaly_id, update_data)
                results.append(f"Success: {updated_anomaly.get('name', anomaly_id)}")
                successful += 1
            except ToolError:
                # Re-raise ToolError exceptions without modification
                # This preserves helpful error messages with specific suggestions
                raise
            except Exception as e:
                results.append(f"Failed: {anomaly_id}: {str(e)}")
                failed += 1

        result_text = (
            f"**Bulk Disable Results**\n\n"
            f"**Total Processed:** {len(anomaly_ids)}\n"
            f"**Successful:** {successful}\n"
            f"**Failed:** {failed}\n\n"
            f"**Details:**\n" + "\n".join(results)
        )

        return [TextContent(type="text", text=result_text)]

    async def _handle_enable_all_anomalies(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Enable all anomalies/alerts."""
        confirm = arguments.get("confirm")

        if not confirm:
            return [
                TextContent(
                    type="text",
                    text="**Confirmation Required**: This will enable ALL alerts in your system\n\n"
                    "**To proceed**: `enable_all(confirm=True)`\n\n"
                    "**What this does**:\n"
                    "• Enables every alert/anomaly in your account\n"
                    "• All alerts will start triggering notifications\n"
                    "• This action affects ALL alerts, not just yours\n\n"
                    "**Alternative**: Use `enable_multiple(anomaly_ids=[...])` for specific alerts",
                )
            ]

        try:
            # Get all anomalies
            response = await client.get_anomalies(page=0, size=1000)
            anomalies = client._extract_embedded_data(response)

            if not anomalies:
                return [
                    TextContent(
                        type="text",
                        text="**No alerts found**\n\nThere are no alerts in the system to enable.",
                    )
                ]

            results = []
            successful = 0
            failed = 0
            already_enabled = 0

            for anomaly in anomalies:
                anomaly_id = anomaly.get("id")
                anomaly_name = anomaly.get("name", f"Alert {anomaly_id}")

                if anomaly.get("enabled", True):
                    already_enabled += 1
                    continue

                try:
                    current_anomaly = await client.get_anomaly_by_id(str(anomaly_id))
                    update_data = current_anomaly.copy()
                    update_data["enabled"] = True
                    await client.update_anomaly(str(anomaly_id), update_data)
                    results.append(f"Enabled: {anomaly_name}")
                    successful += 1
                except Exception as e:
                    results.append(f"Failed: {anomaly_name}: {str(e)}")
                    failed += 1

            result_text = (
                f"**Enable All Alerts - Complete**\n\n"
                f"**Total Alerts:** {len(anomalies)}\n"
                f"**Enabled:** {successful}\n"
                f"**Already Enabled:** {already_enabled}\n"
                f"**Failed:** {failed}\n\n"
                f"**Summary:** {successful + already_enabled} alerts are now active"
            )

            if results:
                result_text += "\n\n**Details:**\n" + "\n".join(results[:10])  # Limit to first 10
                if len(results) > 10:
                    result_text += f"\n... and {len(results) - 10} more"

            return [TextContent(type="text", text=result_text)]

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Error enabling all anomalies: {e}")
            raise ToolError(
                message=f"Failed to enable all alerts: {str(e)}",
                error_code=ErrorCodes.API_ERROR,
                field="bulk_anomaly_enable",
                value=str(e),
                suggestions=[
                    "Check API connectivity and authentication",
                    "Verify that alerts exist before bulk enabling",
                    "Try enabling alerts individually to identify problematic ones",
                    "Use list() to verify available alerts",
                    "Ensure sufficient API permissions for bulk operations",
                ],
                examples={
                    "alternative_approach": "Enable alerts individually: enable(anomaly_id='alert-123')",
                    "verification_steps": ["list()", "enable_multiple(anomaly_ids=['id1', 'id2'])"],
                    "monitoring_context": "CRITICAL: Bulk enable failure means multiple monitoring systems may not be active",
                },
            )

    async def _handle_disable_all_anomalies(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Disable all anomalies/alerts."""
        confirm = arguments.get("confirm")

        if not confirm:
            return [
                TextContent(
                    type="text",
                    text="**Confirmation Required**: This will disable ALL alerts in your system\n\n"
                    "**To proceed**: `disable_all(confirm=True)`\n\n"
                    "**WARNING**: This action will:\n"
                    "• Disable every alert/anomaly in your account\n"
                    "• Stop ALL alert notifications\n"
                    "• Leave your system unmonitored\n"
                    "• Affect ALL alerts, not just yours\n\n"
                    "**Alternative**: Use `disable_multiple(anomaly_ids=[...])` for specific alerts",
                )
            ]

        try:
            # Get all anomalies
            response = await client.get_anomalies(page=0, size=1000)
            anomalies = client._extract_embedded_data(response)

            if not anomalies:
                return [
                    TextContent(
                        type="text",
                        text="**No alerts found**\n\nThere are no alerts in the system to disable.",
                    )
                ]

            results = []
            successful = 0
            failed = 0
            already_disabled = 0

            for anomaly in anomalies:
                anomaly_id = anomaly.get("id")
                anomaly_name = anomaly.get("name", f"Alert {anomaly_id}")

                if not anomaly.get("enabled", True):
                    already_disabled += 1
                    continue

                try:
                    current_anomaly = await client.get_anomaly_by_id(str(anomaly_id))
                    update_data = current_anomaly.copy()
                    update_data["enabled"] = False
                    await client.update_anomaly(str(anomaly_id), update_data)
                    results.append(f"Disabled: {anomaly_name}")
                    successful += 1
                except Exception as e:
                    results.append(f"Failed: {anomaly_name}: {str(e)}")
                    failed += 1

            result_text = (
                f"**Disable All Alerts - Complete**\n\n"
                f"**Total Alerts:** {len(anomalies)}\n"
                f"**Disabled:** {successful}\n"
                f"**Already Disabled:** {already_disabled}\n"
                f"**Failed:** {failed}\n\n"
                f"**Summary:** {successful + already_disabled} alerts are now inactive"
            )

            if results:
                result_text += "\n\n**Details:**\n" + "\n".join(results[:10])  # Limit to first 10
                if len(results) > 10:
                    result_text += f"\n... and {len(results) - 10} more"

            return [TextContent(type="text", text=result_text)]

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Error disabling all anomalies: {e}")
            raise ToolError(
                message=f"Failed to disable all alerts: {str(e)}",
                error_code=ErrorCodes.API_ERROR,
                field="bulk_anomaly_disable",
                value=str(e),
                suggestions=[
                    "Check API connectivity and authentication",
                    "Verify that alerts exist before bulk disabling",
                    "Try disabling alerts individually to identify problematic ones",
                    "Use list() to verify available alerts",
                    "Ensure sufficient API permissions for bulk operations",
                ],
                examples={
                    "alternative_approach": "Disable alerts individually: disable(anomaly_id='alert-123')",
                    "verification_steps": [
                        "list()",
                        "disable_multiple(anomaly_ids=['id1', 'id2'])",
                    ],
                    "monitoring_context": "CRITICAL: Bulk disable failure means some monitoring systems may remain active unexpectedly",
                },
            )

    async def _handle_toggle_anomaly_status(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Toggle the enabled/disabled status of an anomaly."""
        anomaly_id = arguments.get("anomaly_id")

        if not anomaly_id:
            raise create_structured_missing_parameter_error(
                parameter_name="anomaly_id",
                action="toggle anomaly status",
                examples={
                    "usage": "toggle_status(anomaly_id='alert-123')",
                    "valid_format": "Anomaly ID should be a string identifier",
                    "example_ids": ["alert-123", "anomaly-456", "threshold-789"],
                    "monitoring_context": "CRITICAL: Toggling status changes monitoring state (enabled ↔ disabled)",
                },
            )

        try:
            current_anomaly = await client.get_anomaly_by_id(str(anomaly_id))
            current_status = current_anomaly.get("enabled", True)
            new_status = not current_status

            update_data = current_anomaly.copy()
            update_data["enabled"] = new_status
            updated_anomaly = await client.update_anomaly(str(anomaly_id), update_data)

            status_text = "enabled" if new_status else "disabled"

            return [
                TextContent(
                    type="text",
                    text=f"**Alert Status Toggled**\n\n"
                    f"**Name**: {updated_anomaly.get('name', 'Unnamed')}\n"
                    f"**ID**: `{anomaly_id}`\n"
                    f"**Previous Status**: {'Enabled' if current_status else 'Disabled'}\n"
                    f"**New Status**: {'Enabled' if new_status else 'Disabled'}\n\n"
                    f"The alert is now {status_text}.",
                )
            ]

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Error toggling anomaly status {anomaly_id}: {e}")
            raise ToolError(
                message=f"Failed to toggle alert status {anomaly_id}: {repr(e)}",
                error_code=ErrorCodes.API_ERROR,
                field="anomaly_toggle",
                value=str(e),
                suggestions=[
                    "Verify the anomaly_id exists and is valid",
                    "Check API connectivity and authentication",
                    "Use get_anomaly_status() to check current state before toggling",
                    "Try enable() or disable() directly instead of toggle",
                    "Use list() to verify the alert exists",
                ],
                examples={
                    "alternative_methods": [
                        "enable(anomaly_id='alert-123')",
                        "disable(anomaly_id='alert-123')",
                    ],
                    "verification_steps": [
                        "get_anomaly_status()",
                        "list()",
                        "toggle_status(anomaly_id='valid_id')",
                    ],
                    "monitoring_context": "CRITICAL: Toggle failure means monitoring state is uncertain",
                },
            )

    async def _handle_get_anomaly_status(
        self, client: ReveniumClient, arguments: Dict[str, Any]  # noqa: ARG002
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get the current enabled/disabled status of anomalies."""
        try:
            # Get all anomalies
            response = await client.get_anomalies(page=0, size=1000)
            anomalies = client._extract_embedded_data(response)

            if not anomalies:
                return [
                    TextContent(
                        type="text",
                        text="📋 **No alerts found**\n\nThere are no alerts in the system.",
                    )
                ]

            enabled_count = 0
            disabled_count = 0
            status_list = []

            for anomaly in anomalies:
                anomaly_id = anomaly.get("id")
                anomaly_name = anomaly.get("name", f"Alert {anomaly_id}")
                enabled = anomaly.get("enabled", True)

                if enabled:
                    enabled_count += 1
                    status_text = "Enabled"
                else:
                    disabled_count += 1
                    status_text = "Disabled"

                status_list.append(f"**{anomaly_name}** - {status_text} (`{anomaly_id}`)")

            result_text = (
                f"**Alert Status Summary**\n\n"
                f"**Total Alerts:** {len(anomalies)}\n"
                f"**Enabled:** {enabled_count}\n"
                f"**Disabled:** {disabled_count}\n\n"
                f"**Individual Status:**\n" + "\n".join(status_list[:20])  # Limit to first 20
            )

            if len(status_list) > 20:
                result_text += f"\n... and {len(status_list) - 20} more alerts"

            return [TextContent(type="text", text=result_text)]

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Error getting anomaly status: {e}")
            raise ToolError(
                message=f"Failed to get alert status: {repr(e)}",
                error_code=ErrorCodes.API_ERROR,
                field="anomaly_status_retrieval",
                value=str(e),
                suggestions=[
                    "Check API connectivity and authentication",
                    "Verify that alerts exist in the system",
                    "Try list() to see available alerts first",
                    "Ensure sufficient API permissions for status queries",
                    "Check if the alert management service is running",
                ],
                examples={
                    "verification_steps": ["list()", "get_capabilities()", "get_anomaly_status()"],
                    "troubleshooting": [
                        "Test API connectivity",
                        "Verify authentication",
                        "Check service status",
                    ],
                    "monitoring_context": "Status retrieval failure means monitoring state visibility is limited",
                },
            )

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Context7 single source of truth for manage_alerts schema."""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": await self._get_supported_actions(),
                    "description": "Action to perform - create_threshold_alert for real-time monitoring, create_cumulative_usage_alert for budget tracking, list for viewing alerts",
                },
                # Core alert creation fields
                "name": {
                    "type": "string",
                    "description": "Alert name (required for creating alerts)",
                },
                "threshold": {
                    "anyOf": [{"type": "number"}, {"type": "string"}],
                    "description": "Alert threshold value (required for creating alerts)",
                },
                # Optional alert configuration
                "period": {
                    "type": "string",
                    "description": "Period for cumulative usage alerts (daily, weekly, monthly, quarterly)",
                },
                "period_minutes": {
                    "anyOf": [{"type": "number"}, {"type": "string"}],
                    "description": "Check frequency in minutes for threshold alerts (default: 5)",
                },
                "email": {
                    "type": "string",
                    "description": "Email for notifications (optional if REVENIUM_DEFAULT_EMAIL is set)",
                },
                "slack_config_id": {
                    "type": "string",
                    "description": "Slack configuration ID for notifications (optional)",
                },
                # Alert management fields
                "resource_type": {
                    "type": "string",
                    "enum": ["anomalies", "alerts"],
                    "description": "Type of resource - 'anomalies' for alert rules/definitions, 'alerts' for historical events",
                },
                "anomaly_id": {
                    "type": "string",
                    "description": "Alert rule ID for get/update/delete operations",
                },
                "alert_id": {
                    "type": "string",
                    "description": "Historical alert event ID for querying specific incidents",
                },
                # Query and filtering fields
                "query": {
                    "type": "string",
                    "description": "Natural language query for searching alerts/anomalies",
                },
                "text": {
                    "type": "string",
                    "description": "Natural language description for create_from_text action",
                },
                # Advanced configuration
                "anomaly_data": {
                    "type": "object",
                    "description": "Detailed alert configuration object (advanced usage)",
                },
                "metric": {
                    "type": "string",
                    "description": "Metric type for alert (TOTAL_COST, TOKEN_COUNT, etc.)",
                },
                "triggerAfterPersistsDuration": {
                    "type": "string",
                    "description": "Duration alert condition must persist before triggering (optional) - valid values: ONE_MINUTE, FIVE_MINUTES, FIFTEEN_MINUTES, THIRTY_MINUTES, ONE_HOUR, TWELVE_HOURS, TWENTY_FOUR_HOURS, SEVEN_DAYS, THIRTY_DAYS, DAILY, WEEKLY, MONTHLY, QUARTERLY",
                },
                "alert_type": {
                    "type": "string",
                    "description": "Alert type for examples (cumulative_usage, threshold)",
                },
            },
            "required": [
                "action"
            ],  # Context7: User-centric - only action required, other fields depend on action
            "additionalProperties": True,  # Context7: Allow all supported fields for maximum flexibility
        }


# Create singleton instance for easy access
# Module-level instantiation removed to prevent UCM warnings during import
# alert_management = AlertManagement(ucm_helper=None)
