"""Anomaly management functionality for Revenium MCP server.

This module provides CRUD operations and management functionality
for AI anomalies in the Revenium platform.
"""

import json
from typing import Any, Dict, List, Optional, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..client import ReveniumClient
from ..common.error_handling import ToolError, ErrorCodes
from ..error_handlers import (
    handle_alert_tool_errors,
    validate_anomaly_id,
)
from ..exceptions import ValidationError
from ..validators import InputValidator


class AnomalyManager:
    """Manages AI anomaly CRUD operations and related functionality."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the anomaly manager.

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}

    def _get_status_emoji(self, status: str) -> str:
        """Get emoji for anomaly status."""
        # Return empty string - no decorative emojis for status
        _ = status  # Suppress unused parameter warning
        return ""

    def _format_frequency_info(self, period_duration: str) -> str:
        """Format frequency information for display."""
        frequency_map = {
            "ONE_MINUTE": "Every minute",
            "FIVE_MINUTES": "Every 5 minutes",
            "TEN_MINUTES": "Every 10 minutes",
            "FIFTEEN_MINUTES": "Every 15 minutes",
            "THIRTY_MINUTES": "Every 30 minutes",
            "ONE_HOUR": "Every hour",
            "TWO_HOURS": "Every 2 hours",
            "SIX_HOURS": "Every 6 hours",
            "TWELVE_HOURS": "Every 12 hours",
            "ONE_DAY": "Daily",
            "THREE_DAYS": "Every 3 days",
            "SEVEN_DAYS": "Weekly",
            "FOURTEEN_DAYS": "Every 2 weeks",
            "THIRTY_DAYS": "Monthly",
        }
        return frequency_map.get(period_duration, period_duration)

    def _format_trigger_duration_info(self, trigger_duration: str) -> str:
        """Format trigger duration information for display."""
        duration_map = {
            "FIVE_MINUTES": "5 minutes",
            "TEN_MINUTES": "10 minutes",
            "FIFTEEN_MINUTES": "15 minutes",
            "THIRTY_MINUTES": "30 minutes",
            "ONE_HOUR": "1 hour",
            "TWO_HOURS": "2 hours",
            "SIX_HOURS": "6 hours",
            "TWELVE_HOURS": "12 hours",
            "ONE_DAY": "1 day",
            "THREE_DAYS": "3 days",
            "SEVEN_DAYS": "1 week",
            "FOURTEEN_DAYS": "2 weeks",
            "THIRTY_DAYS": "1 month",
        }
        return duration_map.get(trigger_duration, trigger_duration)

    def _process_advanced_configuration(
        self, anomaly_data: Dict[str, Any], validated_data: Dict[str, Any]
    ) -> None:
        """Process advanced configuration fields."""
        # Handle notification addresses
        if "notification_addresses" in anomaly_data:
            addresses = anomaly_data["notification_addresses"]
            if addresses and isinstance(addresses, list):
                validated_data["notification_addresses"] = addresses

        # Handle filters
        if "filters" in anomaly_data:
            filters = anomaly_data["filters"]
            if filters and isinstance(filters, list):
                validated_data["filters"] = filters

        # Handle alert type
        if "alert_type" in anomaly_data:
            validated_data["alert_type"] = str(anomaly_data["alert_type"])
        elif "alertType" in anomaly_data:
            validated_data["alert_type"] = str(anomaly_data["alertType"])

    @handle_alert_tool_errors("list_anomalies")
    async def list_anomalies(
        self,
        client: ReveniumClient,
        page: int = 0,
        size: int = 20,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """List AI anomalies with pagination.

        Args:
            client: Revenium API client
            page: Page number (0-based)
            size: Page size
            filters: Optional filters

        Returns:
            Formatted response with anomaly list
        """
        logger.info(f"Listing anomalies: page={page}, size={size}")

        # Call the client method directly
        response = await client.get_anomalies(page=page, size=size, **(filters or {}))

        # Extract anomalies from response
        anomalies = client._extract_embedded_data(response)
        page_info = client._extract_pagination_info(response)

        # Handle empty results with proper pagination context
        if not anomalies:
            total_elements = page_info.get("totalElements", 0)
            total_pages = page_info.get("totalPages", 1)
            current_page = page + 1

            if total_elements == 0:
                # No anomalies exist in the system
                return [
                    TextContent(
                        type="text",
                        text="📋 **No AI anomalies found**\n\nNo anomalies match your criteria.",
                    )
                ]
            elif current_page > total_pages:
                # Page is beyond available results
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"📋 **Page {current_page} is beyond available results**\n\n"
                            f"**Total anomalies:** {total_elements}\n"
                            f"**Available pages:** 1-{total_pages}\n"
                            f"**Requested page:** {current_page}\n\n"
                            f"Please use a page number between 1 and {total_pages}."
                        ),
                    )
                ]
            else:
                # This shouldn't happen, but handle gracefully
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"**No results on page {current_page}**\n\n"
                            f"**Total anomalies:** {total_elements}\n"
                            f"**Total pages:** {total_pages}\n\n"
                            f"This page appears to be empty. Please try a different page."
                        ),
                    )
                ]

        # Format the response
        anomaly_list = []
        for anomaly in anomalies:
            enabled_status = "Enabled" if anomaly.get("enabled", True) else "Disabled"

            # Generate notification summary
            notification_summary = self._format_notification_summary(anomaly)

            # Always show filter information - either specific filters or "No filters"
            anomaly_filters: List[Dict[str, Any]] = anomaly.get("filters", [])
            filter_summary = ""
            if anomaly_filters:
                filter_count = len(anomaly_filters)
                if filter_count == 1:
                    filter_item = anomaly_filters[0]
                    dimension = filter_item.get("dimension", "N/A")
                    operator = filter_item.get("operator", "CONTAINS")
                    value = filter_item.get("value", "N/A")
                    filter_summary = f"\n  • Filter: {dimension} {operator} '{value}'"
                else:
                    filter_summary = f"\n  • Filters: {filter_count} applied"
            else:
                filter_summary = "\n  • Scope: Global (no filters)"

            # Add persistence duration info if available
            persistence_info = ""
            trigger_duration = anomaly.get("triggerAfterPersistsDuration")
            if trigger_duration:
                trigger_info = self._format_trigger_duration_info(str(trigger_duration))
                persistence_info = f"\n  • Persistence: {trigger_info}"

            anomaly_text = (
                f"**{anomaly.get('name', 'Unnamed')}**\n"
                f"  • ID: `{anomaly.get('id', 'N/A')}`\n"
                f"  • Type: {anomaly.get('alertType', 'N/A')}\n"
                f"  • Metric: {anomaly.get('metricType', 'N/A')}\n"
                f"  • {enabled_status}\n"
                f"  • Threshold: {anomaly.get('threshold', 'N/A')}\n"
                f"  • Created: {(anomaly.get('createdAt') or anomaly.get('created', 'N/A'))[:10] if (anomaly.get('createdAt') or anomaly.get('created')) else 'N/A'}"
                f"{filter_summary}"
                f"{persistence_info}\n"
                f"  • Notifications: {notification_summary}"
            )
            anomaly_list.append(anomaly_text)

        # Create pagination info
        total_pages = page_info.get("totalPages", 1)
        current_page = page + 1
        total_elements = page_info.get("totalElements", len(anomalies))

        result_text = (
            f"**AI Anomalies** (Page {current_page} of {total_pages})\n\n"
            f'**Note**: Anomalies define the rules for alert generation. To see historical triggered alert events, use `resource_type="alerts"` with `action="list"`\n\n'
            f"Found {len(anomalies)} anomalies (Total: {total_elements})\n\n"
            + "\n\n".join(anomaly_list)
        )

        return [TextContent(type="text", text=result_text)]

    @handle_alert_tool_errors("get_anomaly")
    async def get_anomaly(
        self, client: ReveniumClient, anomaly_id: str
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get a specific AI anomaly by ID.

        Args:
            client: Revenium API client
            anomaly_id: ID of the anomaly to retrieve

        Returns:
            Formatted response with anomaly details
        """
        # Validate anomaly ID
        anomaly_id = validate_anomaly_id(anomaly_id)

        logger.info(f"Getting anomaly: {anomaly_id}")

        # Call the API client method
        anomaly = await client.get_anomaly_by_id(anomaly_id)

        # Format the response
        enabled_status = "✅ Enabled" if anomaly.get("enabled", True) else "❌ Disabled"

        detection_rules = anomaly.get("detection_rules", [])
        rules_text = ""
        if detection_rules:
            rules_list = []
            for i, rule in enumerate(detection_rules, 1):
                rules_list.append(
                    f"  {i}. **{rule.get('rule_type', 'unknown')}** rule\n"
                    f"     • Metric: {rule.get('metric', 'N/A')}\n"
                    f"     • Operator: {rule.get('operator', 'N/A')}\n"
                    f"     • Value: {rule.get('value', 'N/A')}"
                )
            rules_text = "\n\n**Detection Rules:**\n" + "\n\n".join(rules_list)

        thresholds = anomaly.get("thresholds", {})
        thresholds_text = ""
        if thresholds:
            threshold_list = [f"  • {k}: {v}" for k, v in thresholds.items()]
            thresholds_text = "\n\n**Thresholds:**\n" + "\n".join(threshold_list)

        # Add filter information if available
        filters = anomaly.get("filters", [])
        filters_text = ""
        if filters:
            filter_list = []
            for filter_item in filters:
                dimension = filter_item.get("dimension", "N/A")
                operator = filter_item.get("operator", "N/A")
                value = filter_item.get("value", "N/A")
                filter_list.append(f"  • {dimension} {operator} '{value}'")
            filters_text = "\n\n**Filters Applied:**\n" + "\n".join(filter_list)

        result_text = (
            f"**AI Anomaly Details**\n\n"
            f"**Name:** {anomaly.get('name', 'Unnamed')}\n"
            f"**ID:** `{anomaly.get('id', 'N/A')}`\n"
            f"**Status:** {anomaly.get('enabled', True) and 'Enabled' or 'Disabled'}\n"
            f"**State:** {enabled_status}\n"
            f"**Description:** {anomaly.get('description', 'No description')}\n"
            f"**Created:** {anomaly.get('createdAt', anomaly.get('created', 'N/A'))}\n"
            f"**Updated:** {anomaly.get('updatedAt', anomaly.get('updated', 'N/A'))}"
            f"{rules_text}"
            f"{thresholds_text}"
            f"{filters_text}"
        )

        # Add alert type and metric information
        alert_type = anomaly.get('alertType')
        metric_type = anomaly.get('metricType')
        threshold = anomaly.get('threshold')
        operator_type = anomaly.get('operatorType')

        if alert_type:
            result_text += f"\n\n**Alert Configuration:**"
            result_text += f"\n  • **Type:** {alert_type}"
            if metric_type:
                result_text += f"\n  • **Metric:** {metric_type}"
            if threshold is not None:
                threshold_text = str(threshold)
                if anomaly.get('isPercentage', False):
                    threshold_text += "%"
                if operator_type:
                    operator_mapping = {
                        "GREATER_THAN": ">",
                        "GREATER_THAN_OR_EQUAL_TO": "≥",
                        "LESS_THAN": "<",
                        "LESS_THAN_OR_EQUAL_TO": "≤",
                        "EQUALS": "=",
                        "NOT_EQUALS": "≠",
                    }
                    operator_symbol = operator_mapping.get(operator_type, operator_type)
                    result_text += f"\n  • **Threshold:** {operator_symbol} {threshold_text}"
                else:
                    result_text += f"\n  • **Threshold:** {threshold_text}"

        # Add frequency information if available
        period_duration = anomaly.get("periodDuration")
        if period_duration:
            frequency_info = self._format_frequency_info(str(period_duration))
            result_text += f"\n  • **Frequency:** {frequency_info}"

        # Add trigger persistence duration if available
        trigger_duration = anomaly.get("triggerAfterPersistsDuration")
        if trigger_duration:
            trigger_info = self._format_trigger_duration_info(str(trigger_duration))
            result_text += f"\n  • **Trigger Persistence:** {trigger_info}"

        # Add notification configuration display
        notification_text = await self._format_notification_configuration(client, anomaly)
        result_text += notification_text

        return [TextContent(type="text", text=result_text)]

    @handle_alert_tool_errors("create_anomaly")
    async def create_anomaly(
        self, client: ReveniumClient, anomaly_data: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Create a new AI anomaly with comprehensive validation.

        Args:
            client: Revenium API client
            anomaly_data: Anomaly configuration data

        Returns:
            Formatted response with created anomaly details
        """
        if not isinstance(anomaly_data, dict):
            raise ValidationError(
                message="anomaly_data must be a dictionary",
                field="anomaly_data",
                value=type(anomaly_data).__name__,
                expected="Dictionary with anomaly fields",
            )

        logger.info(f"Creating anomaly: {anomaly_data.get('name', 'Unnamed')}")

        # DEBUG: Log the incoming anomaly_data for troubleshooting JSON issues
        logger.debug(f"Incoming anomaly_data type: {type(anomaly_data)}")
        logger.debug(f"Incoming anomaly_data keys: {list(anomaly_data.keys()) if isinstance(anomaly_data, dict) else 'Not a dict'}")
        logger.debug(f"Incoming anomaly_data: {json.dumps(anomaly_data, indent=2, default=str)}")

        # Apply comprehensive validation and sanitization
        validated_data = {}

        # Validate and sanitize each field
        if "name" in anomaly_data:
            validated_data["name"] = InputValidator.validate_anomaly_name(anomaly_data["name"])
        else:
            raise ValidationError(
                message="Anomaly name is required", field="name", expected="Non-empty string"
            )

        if "description" in anomaly_data:
            validated_data["description"] = InputValidator.validate_description(
                anomaly_data["description"]
            )

        if "tags" in anomaly_data:
            validated_data["tags"] = InputValidator.validate_tags(anomaly_data["tags"])

        # Handle both detection_rules format AND direct API format
        if "detection_rules" in anomaly_data:
            # User provided detection_rules format - validate and convert
            if not anomaly_data["detection_rules"]:
                raise ValidationError(
                    message="At least one detection rule is required",
                    field="detection_rules",
                    expected="List with at least one detection rule",
                )
            validated_data["detection_rules"] = [
                InputValidator.validate_detection_rule(rule)
                for rule in anomaly_data["detection_rules"]
            ]
        elif self._has_direct_api_format(anomaly_data):
            # User provided direct API format - validate and use as-is
            validated_data.update(self._validate_direct_api_format(anomaly_data))
        else:
            raise ValidationError(
                message="Either detection_rules or direct API format (alertType, metricType, operatorType, threshold) is required",
                field="anomaly_data",
                expected="Detection rules list OR direct API format fields",
                suggestion="• For real-time monitoring: `create_threshold_alert(name='Alert', threshold=100, period_minutes=5)`\n"
                "• For budget tracking: `create_cumulative_usage_alert(name='Budget', threshold=1000, period='monthly')`\n\n"
                "**Or** provide all required fields: alertType, metricType, operatorType, threshold",
            )

        # Thresholds are optional in the API format (extracted from detection rules)
        if "thresholds" in anomaly_data:
            validated_data["thresholds"] = InputValidator.validate_thresholds(
                anomaly_data["thresholds"]
            )

        # Handle advanced configuration fields
        self._process_advanced_configuration(anomaly_data, validated_data)

        # Copy other basic fields with validation
        for field in ["status", "enabled", "team_id", "notification_settings", "metadata"]:
            if field in anomaly_data:
                if field == "team_id" and not anomaly_data[field]:
                    raise ValidationError(
                        message="Team ID is required", field="team_id", expected="Non-empty string"
                    )
                validated_data[field] = anomaly_data[field]

        # Convert to API format (only if we have detection_rules, otherwise use direct format)
        if "detection_rules" in validated_data:
            try:
                api_data = InputValidator.convert_to_api_format(validated_data)
            except Exception as e:
                raise ValidationError(
                    message=f"Failed to convert to API format: {str(e)}",
                    field="anomaly_data",
                    expected="Valid anomaly data structure",
                )
        else:
            # Direct API format - use validated data as-is, just add required fields
            api_data = validated_data.copy()

            # Apply operator mapping for filters in direct API format
            if "filters" in api_data and isinstance(api_data["filters"], list):
                operator_mapping = {
                    "EQUALS": "IS",
                    "NOT_EQUALS": "IS_NOT",
                    "EQUAL": "IS",
                    "NOT_EQUAL": "IS_NOT",
                }

                for filter_item in api_data["filters"]:
                    if isinstance(filter_item, dict) and "operator" in filter_item:
                        raw_operator = str(filter_item["operator"]).upper()
                        filter_item["operator"] = operator_mapping.get(raw_operator, raw_operator)

            # Ensure required API fields are present
            if "label" not in api_data and "name" in validated_data:
                api_data["label"] = validated_data["name"]
            if "teamId" not in api_data:
                api_data["teamId"] = client.team_id

            # Set defaults for optional fields if not provided
            api_data.setdefault("enabled", True)
            api_data.setdefault("isPercentage", False)
            api_data.setdefault("notificationAddresses", [])
            api_data.setdefault("slackConfigurations", [])
            api_data.setdefault("triggerAfterPersistsDuration", "")
            api_data.setdefault("filters", [])

            # CRITICAL FIX: Ensure periodDuration is set (required by API)
            if "periodDuration" not in api_data:
                # Set a sensible default based on alert type
                if api_data.get("alertType") == "THRESHOLD":
                    api_data["periodDuration"] = "FIFTEEN_MINUTES"  # Default for threshold alerts
                elif api_data.get("alertType") == "CUMULATIVE_USAGE":
                    api_data["periodDuration"] = "DAILY"  # Default for cumulative usage
                else:
                    api_data["periodDuration"] = "FIFTEEN_MINUTES"  # Safe default

        # DEBUG: Log the final API data before sending to help troubleshoot JSON issues
        logger.debug(f"Final API data type: {type(api_data)}")
        logger.debug(f"Final API data keys: {list(api_data.keys()) if isinstance(api_data, dict) else 'Not a dict'}")
        logger.debug(f"Final API data being sent to create_anomaly: {json.dumps(api_data, indent=2, default=str)}")

        # Call the API client method
        try:
            created_anomaly = await client.create_anomaly(api_data)
        except Exception as e:
            logger.error(f"Failed to create anomaly: {e}")
            # DEBUG: Log additional context for JSON format errors
            if "json" in str(e).lower() or "format" in str(e).lower():
                logger.error(f"JSON format error context - API data was: {json.dumps(api_data, indent=2, default=str)}")

                # Create a proper ToolError following the error handling architecture
                raise ToolError(
                    message="Alert creation failed due to data format issues",
                    error_code=ErrorCodes.VALIDATION_ERROR,
                    field="anomaly_data",
                    value="See debug logs for details",
                    suggestions=[
                        "Use convenience methods for easier setup:",
                        "• create_threshold_alert(name='Alert', threshold=100, period_minutes=5)",
                        "• create_cumulative_usage_alert(name='Budget', threshold=1000, period='monthly')",
                        "Or ensure all required fields are provided:",
                        "• name (string): Descriptive alert name",
                        "• alertType (string): 'THRESHOLD' or 'CUMULATIVE_USAGE'",
                        "• metricType (string): 'TOTAL_COST', 'TOKEN_COUNT', etc.",
                        "• operatorType (string): 'GREATER_THAN', 'LESS_THAN', etc.",
                        "• threshold (number): Alert threshold value"
                    ],
                    examples={
                        "Basic threshold alert": 'create_threshold_alert(name="Cost Alert", threshold=100, period_minutes=15)',
                        "Monthly budget alert": 'create_cumulative_usage_alert(name="Monthly Budget", threshold=5000, period="monthly")'
                    }
                )
            raise

        # Format the response
        result_text = (
            f"**AI Anomaly Created Successfully**\n\n"
            f"**Name:** {created_anomaly.get('name', 'Unnamed')}\n"
            f"**ID:** `{created_anomaly.get('id', 'N/A')}`\n"
            f"**Alert Type:** {created_anomaly.get('alertType', 'N/A')}\n"
            f"**Metric Type:** {created_anomaly.get('metricType', 'N/A')}\n"
            f"**Operator:** {created_anomaly.get('operatorType', 'N/A')}\n"
            f"**Threshold:** {created_anomaly.get('threshold', 'N/A')}\n"
            f"**Check Frequency:** {created_anomaly.get('periodDuration', 'N/A')}\n"
            f"**Enabled:** {'Yes' if created_anomaly.get('enabled', True) else 'No'}\n"
            f"**Created:** {created_anomaly.get('createdAt', created_anomaly.get('created', 'N/A'))}"
        )

        # Add frequency information if available
        period_duration = created_anomaly.get("periodDuration")
        if period_duration:
            frequency_info = self._format_frequency_info(str(period_duration))
            result_text += f"\n\n**Frequency Details:**\n{frequency_info}"

        # Add trigger duration if available
        trigger_duration = created_anomaly.get("triggerAfterPersistsDuration")
        if trigger_duration:
            trigger_info = self._format_trigger_duration_info(str(trigger_duration))
            result_text += f"\n**Trigger Duration:** {trigger_info}"

        # Add complete notification configuration display
        notification_text = await self._format_notification_configuration(client, created_anomaly)
        result_text += notification_text

        # Add filter information if available
        filters = created_anomaly.get("filters", [])
        if filters:
            result_text += f"\n\n**Filters Applied:**"
            for filter_item in filters:
                dimension = filter_item.get("dimension", "N/A")
                operator = filter_item.get("operator", "N/A")
                value = filter_item.get("value", "N/A")
                result_text += f"\n  • {dimension} {operator} '{value}'"

        return [TextContent(type="text", text=result_text)]

    @handle_alert_tool_errors("update_anomaly")
    async def update_anomaly(
        self, client: ReveniumClient, anomaly_id: str, update_data: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Update an existing AI anomaly.

        Args:
            client: Revenium API client
            anomaly_id: ID of the anomaly to update
            update_data: Data to update

        Returns:
            Formatted response with updated anomaly details
        """
        # Validate anomaly ID
        anomaly_id = validate_anomaly_id(anomaly_id)

        if not isinstance(update_data, dict):
            raise ValidationError(
                message="update_data must be a dictionary",
                field="update_data",
                value=type(update_data).__name__,
                expected="Dictionary with update fields",
            )

        logger.info(f"Updating anomaly: {anomaly_id}")

        # Get current anomaly data first (like enable/disable operations do)
        current_anomaly = await client.get_anomaly_by_id(str(anomaly_id))

        # Start with current data and apply updates
        merged_data = current_anomaly.copy()

        # Handle field name conversions for user-friendly field names
        converted_updates = {}
        for key, value in update_data.items():
            if key == "email":
                # Convert 'email' to 'notificationAddresses'
                if isinstance(value, str):
                    converted_updates["notificationAddresses"] = [value]
                elif isinstance(value, list):
                    converted_updates["notificationAddresses"] = value
                else:
                    converted_updates["notificationAddresses"] = [str(value)]
            elif key == "notification_addresses":
                # Convert 'notification_addresses' to 'notificationAddresses'
                converted_updates["notificationAddresses"] = value
            elif key == "slackConfigId" or key == "slack_config_id":
                # Convert 'slackConfigId' or 'slack_config_id' to 'slackConfigurations' array
                if isinstance(value, str):
                    converted_updates["slackConfigurations"] = [value]
                elif isinstance(value, list):
                    converted_updates["slackConfigurations"] = value
                else:
                    converted_updates["slackConfigurations"] = [str(value)]
            elif key == "slack_configurations":
                # Convert 'slack_configurations' to 'slackConfigurations'
                converted_updates["slackConfigurations"] = value
            elif key == "filters":
                # Handle filter updates with proper validation and conversion
                if value is None:
                    # Allow clearing filters
                    converted_updates["filters"] = []
                elif isinstance(value, list):
                    # Validate and convert filters to API format
                    try:
                        from ..validators import InputValidator

                        # Check if filters are already in API format (have 'dimension' field)
                        if value and isinstance(value[0], dict) and "dimension" in value[0]:
                            # Already in API format, validate structure
                            validated_filters = []
                            for filter_item in value:
                                if not isinstance(filter_item, dict):
                                    raise ValidationError(
                                        message="Each filter must be a dictionary",
                                        field="filters",
                                        value=type(filter_item).__name__,
                                        expected="Dictionary with dimension, operator, and value fields",
                                    )

                                required_fields = ["dimension", "operator", "value"]
                                for field in required_fields:
                                    if field not in filter_item:
                                        raise ValidationError(
                                            message=f"Filter missing required field: {field}",
                                            field="filters",
                                            value=filter_item,
                                            expected=f"Dictionary with {', '.join(required_fields)} fields",
                                        )

                                # Map operator to API format (handle common aliases)
                                operator_mapping = {
                                    "EQUALS": "IS",
                                    "NOT_EQUALS": "IS_NOT",
                                    "EQUAL": "IS",
                                    "NOT_EQUAL": "IS_NOT",
                                }

                                raw_operator = str(filter_item["operator"]).upper()
                                mapped_operator = operator_mapping.get(raw_operator, raw_operator)

                                validated_filters.append(
                                    {
                                        "dimension": str(filter_item["dimension"]).upper(),
                                        "operator": mapped_operator,
                                        "value": str(filter_item["value"]),
                                    }
                                )
                            converted_updates["filters"] = validated_filters
                        else:
                            # User-friendly format, convert to API format
                            converted_updates["filters"] = (
                                InputValidator._convert_filters_to_api_format(value)
                            )
                    except Exception as e:
                        raise ValidationError(
                            message=f"Invalid filter format: {str(e)}",
                            field="filters",
                            value=value,
                            expected="List of filter dictionaries with dimension/operator/value or field/operator/value",
                            suggestion="Use format: [{'dimension': 'PROVIDER', 'operator': 'CONTAINS', 'value': 'openai'}] or [{'field': 'provider', 'operator': 'contains', 'value': 'openai'}]",
                        )
                else:
                    raise ValidationError(
                        message="Filters must be a list or null",
                        field="filters",
                        value=type(value).__name__,
                        expected="List of filter dictionaries or null to clear filters",
                    )
            elif key == "alert_type":
                # Convert 'alert_type' to 'alertType'
                converted_updates["alertType"] = str(value).upper()
            elif key == "metric_type":
                # Convert 'metric_type' to 'metricType'
                converted_updates["metricType"] = str(value).upper()
            elif key == "operator_type":
                # Convert 'operator_type' to 'operatorType'
                converted_updates["operatorType"] = str(value).upper()
            elif key == "period_minutes":
                # Convert 'period_minutes' to 'periodDuration' with proper mapping
                period_mapping = {
                    1: "ONE_MINUTE",
                    5: "FIVE_MINUTES",
                    15: "FIFTEEN_MINUTES",
                    30: "THIRTY_MINUTES",
                    60: "ONE_HOUR",
                    720: "TWELVE_HOURS",
                    1440: "TWENTY_FOUR_HOURS",
                }
                try:
                    minutes = int(float(value))
                    if minutes in period_mapping:
                        converted_updates["periodDuration"] = period_mapping[minutes]
                    else:
                        raise ValidationError(
                            message=f"Invalid period_minutes value: {minutes}",
                            field="period_minutes",
                            value=value,
                            expected=f"One of: {list(period_mapping.keys())} minutes",
                            suggestion="Use standard intervals: 1, 5, 15, 30, 60, 720, 1440 minutes",
                        )
                except (ValueError, TypeError):
                    raise ValidationError(
                        message="period_minutes must be a numeric value",
                        field="period_minutes",
                        value=value,
                        expected="Numeric value in minutes",
                    )
            elif key == "is_percentage":
                # Convert 'is_percentage' to 'isPercentage'
                if isinstance(value, bool):
                    converted_updates["isPercentage"] = value
                else:
                    converted_updates["isPercentage"] = str(value).lower() in ["true", "1", "yes"]
            elif key == "trigger_after_persists_duration":
                # Convert 'trigger_after_persists_duration' to 'triggerAfterPersistsDuration'
                converted_updates["triggerAfterPersistsDuration"] = str(value)
            elif key == "tracking_period":
                # Convert 'tracking_period' to 'periodDuration' for CUMULATIVE_USAGE alerts
                # Map user-friendly period names to API format
                period_mapping = {
                    "daily": "DAILY",
                    "weekly": "WEEKLY",
                    "monthly": "MONTHLY",
                    "quarterly": "QUARTERLY",
                }
                period_value = str(value).lower()
                if period_value in period_mapping:
                    converted_updates["periodDuration"] = period_mapping[period_value]
                else:
                    # Pass through as-is if already in API format
                    converted_updates["periodDuration"] = str(value)
            elif key == "webhook_configurations":
                # Convert 'webhook_configurations' to 'webhookConfigurations'
                converted_updates["webhookConfigurations"] = (
                    value if isinstance(value, list) else [value]
                )
            else:
                # Pass through other fields as-is
                converted_updates[key] = value

        # Apply the converted updates to the current data
        merged_data.update(converted_updates)

        # Call the API client method with merged data
        updated_anomaly = await client.update_anomaly(anomaly_id, merged_data)

        result_text = (
            f"**AI Anomaly Updated Successfully**\n\n"
            f"**Name:** {updated_anomaly.get('name', 'Unnamed')}\n"
            f"**ID:** `{updated_anomaly.get('id', 'N/A')}`\n"
            f"**Status:** {updated_anomaly.get('enabled', True) and 'Enabled' or 'Disabled'}\n"
            f"**Updated:** {updated_anomaly.get('updatedAt', updated_anomaly.get('updated', 'N/A'))}"
        )

        # Always show current notification configuration (not conditional)
        notification_text = await self._format_notification_configuration(client, updated_anomaly)
        result_text += notification_text

        return [TextContent(type="text", text=result_text)]

    @handle_alert_tool_errors("delete_anomaly")
    async def delete_anomaly(
        self, client: ReveniumClient, anomaly_id: str
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Delete an AI anomaly.

        Args:
            client: Revenium API client
            anomaly_id: ID of the anomaly to delete

        Returns:
            Formatted response confirming deletion
        """
        # Validate anomaly ID
        anomaly_id = validate_anomaly_id(anomaly_id)

        logger.info(f"Deleting anomaly: {anomaly_id}")

        # Call the API client method
        await client.delete_anomaly(anomaly_id)

        result_text = (
            f"**AI Anomaly Deleted Successfully**\n\n"
            f"**ID:** `{anomaly_id}`\n"
            f"The anomaly has been permanently removed."
        )

        return [TextContent(type="text", text=result_text)]

    @handle_alert_tool_errors("clear_all_anomalies")
    async def clear_all_anomalies(
        self, client: ReveniumClient
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Clear all AI anomalies.

        Args:
            client: Revenium API client

        Returns:
            Formatted response confirming clearing
        """
        logger.info("Clearing all anomalies")

        # Get all anomalies first
        response = await client.get_anomalies(page=0, size=1000)
        anomalies = client._extract_embedded_data(response)

        if not anomalies:
            return [
                TextContent(
                    type="text",
                    text="**No anomalies to clear**\n\nThere are no anomalies in the system.",
                )
            ]

        # Delete each anomaly
        deleted_count = 0
        for anomaly in anomalies:
            try:
                anomaly_id = anomaly.get("id")
                if anomaly_id:
                    await client.delete_anomaly(anomaly_id)
                    deleted_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete anomaly {anomaly.get('id')}: {e}")

        result_text = (
            f"✅ **Anomalies Cleared Successfully**\n\n"
            f"**Deleted:** {deleted_count} anomalies\n"
            f"**Total Found:** {len(anomalies)}"
        )

        if deleted_count < len(anomalies):
            result_text += f"\n\n⚠️ **Warning:** {len(anomalies) - deleted_count} anomalies could not be deleted."

        return [TextContent(type="text", text=result_text)]

    @handle_alert_tool_errors("get_anomaly_metrics")
    async def get_anomaly_metrics(
        self, client: ReveniumClient, anomaly_id: str
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get metrics for a specific anomaly.

        Args:
            client: Revenium API client
            anomaly_id: ID of the anomaly

        Returns:
            Formatted response with anomaly metrics
        """
        # Validate anomaly ID
        anomaly_id = validate_anomaly_id(anomaly_id)

        logger.info(f"Getting metrics for anomaly: {anomaly_id}")

        # Call the API client method
        metrics = await client.get_anomaly_metrics(anomaly_id)

        result_text = (
            f"📊 **Anomaly Metrics**\n\n"
            f"**Anomaly ID:** `{anomaly_id}`\n"
            f"**Metrics:** {json.dumps(metrics, indent=2) if metrics else 'No metrics available'}"
        )

        return [TextContent(type="text", text=result_text)]

    def _format_notification_summary(self, anomaly_data: Dict[str, Any]) -> str:
        """Format a concise notification summary for list views.

        Args:
            anomaly_data: Anomaly data containing notification configuration

        Returns:
            Concise notification summary string
        """
        summary_parts = []

        # Count email notifications
        email_addresses = anomaly_data.get("notificationAddresses", [])
        if email_addresses:
            email_count = len(email_addresses)
            summary_parts.append(f"{email_count} email{'s' if email_count != 1 else ''}")

        # Count Slack configurations
        slack_config_ids = anomaly_data.get("slackConfigurations", [])
        if slack_config_ids:
            slack_count = len(slack_config_ids)
            summary_parts.append(f"{slack_count} Slack")

        # Return summary or "No notifications"
        if summary_parts:
            return ", ".join(summary_parts)
        else:
            return "No notifications"

    async def _format_notification_configuration(
        self, client: ReveniumClient, anomaly_data: Dict[str, Any]
    ) -> str:
        """Format notification configuration display for anomaly responses.

        Args:
            client: Revenium API client for fetching Slack configuration details
            anomaly_data: Anomaly data containing notification configuration

        Returns:
            Formatted notification configuration text
        """
        notification_parts = []

        # Extract email notifications
        email_addresses = anomaly_data.get("notificationAddresses", [])
        if email_addresses:
            email_list = ", ".join(email_addresses)
            notification_parts.append(f"• **Email Notifications:** {email_list}")

        # Extract and format Slack configurations
        slack_config_ids = anomaly_data.get("slackConfigurations", [])
        if slack_config_ids:
            slack_details = []
            for config_id in slack_config_ids:
                try:
                    # Fetch detailed Slack configuration information
                    slack_config = await client.get_slack_configuration_by_id(config_id)

                    # Extract human-readable details
                    name = slack_config.get("name", "Unnamed Configuration")
                    channel_name = slack_config.get("channelName", "N/A")
                    team_name = slack_config.get("teamName") or slack_config.get("team", {}).get(
                        "label", "Unknown Workspace"
                    )

                    # Format as: "Name (#channel) - Workspace: Team"
                    slack_detail = f"  - {name} (#{channel_name}) - Workspace: {team_name}"
                    slack_details.append(slack_detail)

                except Exception as e:
                    # Handle cases where Slack configuration might not exist or API call fails
                    logger.warning(f"Failed to fetch Slack configuration {config_id}: {e}")
                    slack_details.append(f"  - Configuration ID: {config_id} (Details unavailable)")

            if slack_details:
                notification_parts.append("• **Slack Notifications:**")
                notification_parts.extend(slack_details)

        # Handle case where no notifications are configured
        if not notification_parts:
            return "\n\n**Notification Configuration:** No notifications configured"

        # Combine all notification information
        notification_text = "\n\n**Notification Configuration:**\n" + "\n".join(notification_parts)
        return notification_text

    def _has_direct_api_format(self, anomaly_data: Dict[str, Any]) -> bool:
        """Check if anomaly data is in direct API format."""
        required_api_fields = ["alertType", "metricType", "operatorType", "threshold"]
        return all(field in anomaly_data for field in required_api_fields)

    def _validate_direct_api_format(self, anomaly_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and sanitize direct API format data."""
        validated_data = {}

        # CRITICAL FIX: Process convenience notification fields before validation
        processed_data = self._process_convenience_notification_fields(anomaly_data.copy())

        # Validate required API fields - CORRECTED: Only 3 supported alert types
        required_fields = {
            "alertType": ["THRESHOLD", "CUMULATIVE_USAGE", "RELATIVE_CHANGE"],
            "metricType": [
                "TOTAL_COST",
                "COST_PER_TRANSACTION",
                "TOKEN_COUNT",
                "INPUT_TOKEN_COUNT",
                "OUTPUT_TOKEN_COUNT",
                "ERROR_RATE",
                "REQUESTS_PER_MINUTE",
                "TOKENS_PER_MINUTE",
            ],
            "operatorType": [
                "GREATER_THAN",
                "LESS_THAN",
                "GREATER_THAN_OR_EQUAL",
                "LESS_THAN_OR_EQUAL",
                "EQUAL",
                "NOT_EQUAL",
            ],
            "threshold": "numeric",
        }

        for field, valid_values in required_fields.items():
            if field not in processed_data:
                raise ValidationError(
                    message=f"Required field '{field}' is missing",
                    field=field,
                    expected=(
                        f"One of: {valid_values}"
                        if isinstance(valid_values, list)
                        else "Numeric value"
                    ),
                )

            value = processed_data[field]

            if field == "threshold":
                # Validate numeric threshold
                try:
                    validated_data[field] = float(value)
                except (ValueError, TypeError):
                    raise ValidationError(
                        message=f"Invalid threshold value",
                        field=field,
                        value=value,
                        expected="Numeric value",
                    )
            elif isinstance(valid_values, list):
                # Validate enum values
                if value not in valid_values:
                    raise ValidationError(
                        message=f"Invalid {field} value",
                        field=field,
                        value=value,
                        expected=f"One of: {', '.join(valid_values)}",
                    )
                validated_data[field] = value
            else:
                validated_data[field] = value

        # Validate optional fields
        optional_fields = {
            "periodDuration": [
                "ONE_MINUTE",
                "FIVE_MINUTES",
                "FIFTEEN_MINUTES",
                "THIRTY_MINUTES",
                "ONE_HOUR",
                "TWELVE_HOURS",
                "TWENTY_FOUR_HOURS",
                "DAILY",
                "WEEKLY",
                "MONTHLY",
                "QUARTERLY",
            ],
            "isPercentage": "boolean",
            "enabled": "boolean",
            "notificationAddresses": "list",
            "slackConfigurations": "list",
            "triggerAfterPersistsDuration": "string",
            "filters": "list",
        }

        for field, field_type in optional_fields.items():
            if field in processed_data:
                value = processed_data[field]

                if (
                    field == "periodDuration"
                    and isinstance(field_type, list)
                    and value not in field_type
                ):
                    raise ValidationError(
                        message=f"Invalid periodDuration value",
                        field=field,
                        value=value,
                        expected=f"One of: {', '.join(field_type)}",
                    )
                elif field_type == "boolean" and not isinstance(value, bool):
                    raise ValidationError(
                        message=f"Invalid {field} value",
                        field=field,
                        value=value,
                        expected="Boolean (true/false)",
                    )
                elif field_type == "list" and not isinstance(value, list):
                    raise ValidationError(
                        message=f"Invalid {field} value",
                        field=field,
                        value=type(value).__name__,
                        expected="List/array",
                    )

                validated_data[field] = value

        return validated_data

    def _process_convenience_notification_fields(self, anomaly_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process convenience notification fields (email, slackConfigId) and convert to API format.

        This method handles the conversion of user-friendly notification fields to the proper
        API format that the Revenium API expects.

        Args:
            anomaly_data: Raw anomaly data that may contain convenience fields

        Returns:
            Processed anomaly data with convenience fields converted to API format
        """
        processed_data = anomaly_data.copy()

        # Handle email convenience field
        if "email" in processed_data:
            email = processed_data.pop("email")  # Remove convenience field
            if email and email.strip():
                # Add to notificationAddresses if not already present
                if "notificationAddresses" not in processed_data:
                    processed_data["notificationAddresses"] = []
                if email not in processed_data["notificationAddresses"]:
                    processed_data["notificationAddresses"].append(email)

        # Handle slackConfigId convenience field
        if "slackConfigId" in processed_data:
            slack_config_id = processed_data.pop("slackConfigId")  # Remove convenience field
            if slack_config_id and slack_config_id.strip():
                # Add to slackConfigurations if not already present
                if "slackConfigurations" not in processed_data:
                    processed_data["slackConfigurations"] = []
                # Check if this config ID is already present (API expects array of strings, not objects)
                if slack_config_id not in processed_data["slackConfigurations"]:
                    processed_data["slackConfigurations"].append(slack_config_id)

        # Handle trackingPeriod convenience field for CUMULATIVE_USAGE alerts
        if "trackingPeriod" in processed_data:
            tracking_period = processed_data.pop("trackingPeriod")  # Remove convenience field
            if tracking_period:
                # Map user-friendly period names to API format
                period_mapping = {
                    "daily": "DAILY",
                    "weekly": "WEEKLY",
                    "monthly": "MONTHLY",
                    "quarterly": "QUARTERLY",
                    # Also handle already-formatted values
                    "DAILY": "DAILY",
                    "WEEKLY": "WEEKLY",
                    "MONTHLY": "MONTHLY",
                    "QUARTERLY": "QUARTERLY",
                }
                period_value = str(tracking_period).lower()
                if period_value in period_mapping:
                    processed_data["periodDuration"] = period_mapping[period_value]
                else:
                    # Pass through as-is if not in mapping (let validation catch invalid values)
                    processed_data["periodDuration"] = str(tracking_period)

        return processed_data
