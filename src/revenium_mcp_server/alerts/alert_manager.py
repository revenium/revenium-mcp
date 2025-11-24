"""Alert management functionality for Revenium MCP server.

This module provides management functionality for triggered alerts
in the Revenium platform.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from loguru import logger

try:
    import dateutil.parser
except ImportError:
    dateutil = None

from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..client import ReveniumClient
from ..date_parser import DateRangeParser
from ..exceptions import ValidationError
from ..models import MetricType



# Import error handlers with fallback
try:
    from ..error_handlers import (
        handle_alert_tool_errors,
        validate_alert_id,
    )
except ImportError:
    # Fallback decorators and validators
    def handle_alert_tool_errors(operation_name: str):
        def decorator(func):
            # Use operation_name to satisfy linter
            _ = operation_name
            return func

        return decorator

    def validate_alert_id(alert_id):
        if not alert_id or not isinstance(alert_id, str):
            raise ValidationError("Invalid alert ID", field="alert_id", value=alert_id)
        return alert_id.strip()



class AlertManager:
    """Manages AI alert operations and investigation functionality."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the alert manager.

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        self.date_parser = DateRangeParser()

    def _get_severity_emoji(self, severity: str) -> str:
        """Get emoji for alert severity."""
        if not severity or not isinstance(severity, str):
            severity = "unknown"

        # Return empty string - no decorative emojis for severity
        return ""

    def _get_status_emoji(self, status: str) -> str:
        """Get emoji for alert status."""
        if not status or not isinstance(status, str):
            status = "unknown"

        # Return empty string - no decorative emojis for status
        return ""

    def _parse_natural_language_query(self, query: str) -> Dict[str, Any]:
        """Parse natural language query into API parameters.

        Supports common phrases for alert history retrieval:
        - "alert history", "show alerts", "list alerts"
        - "firing alerts", "active alerts", "triggered alerts"
        - "recent alerts", "latest alerts"
        - Date ranges: "last 24 hours", "yesterday", "this week"
        """
        filters = {}
        query_lower = query.lower()

        # Parse date ranges first (most specific)
        date_range = self.date_parser.parse_natural_language_date_range(query)
        if date_range:
            filters.update(date_range)

        # Parse common alert history phrases
        # These phrases indicate the user wants to see alert/anomaly data
        alert_history_phrases = [
            "alert history",
            "show alerts",
            "list alerts",
            "get alerts",
            "alert events",
            "triggered alerts",
            "alert activity",
            "anomaly history",
            "show anomalies",
            "list anomalies",
            "recent alerts",
            "latest alerts",
            "current alerts",
        ]

        # Check if query contains alert history phrases
        is_alert_history_query = any(phrase in query_lower for phrase in alert_history_phrases)
        if is_alert_history_query:
            # For alert history queries, we want to show all alerts by default
            # The API endpoint change to /anomaly already handles this
            pass

        # Parse firing/active status keywords
        if any(word in query_lower for word in ["firing", "active", "triggered", "live"]):
            # Note: The API uses 'firing' boolean field, but we'll let the display logic handle this
            # since we can't filter by firing status in the API parameters
            pass
        elif any(word in query_lower for word in ["resolved", "closed", "completed"]):
            # Similarly, resolved alerts would be those with 'updated' timestamps
            pass
        elif any(word in query_lower for word in ["disabled", "paused", "inactive"]):
            # Disabled alerts would have 'enabled': false
            pass

        # Parse severity keywords (though API doesn't have severity, keep for future)
        if "critical" in query_lower:
            filters["severity"] = "critical"
        elif "high" in query_lower:
            filters["severity"] = "high"
        elif "medium" in query_lower:
            filters["severity"] = "medium"
        elif "low" in query_lower:
            filters["severity"] = "low"

        # Parse traditional status keywords (for backward compatibility)
        if "open" in query_lower:
            filters["status"] = "open"
        elif "acknowledged" in query_lower:
            filters["status"] = "acknowledged"
        elif "investigating" in query_lower:
            filters["status"] = "investigating"

        # Parse metric type keywords using user-validated metrics
        all_metrics = [metric.value for metric in MetricType]
        metric_keywords = {
            "cost": [m for m in all_metrics if "COST" in m],
            "token": [m for m in all_metrics if "TOKEN" in m],
            "error": [m for m in all_metrics if "ERROR" in m],
            "request": [m for m in all_metrics if "REQUEST" in m],
            "performance": [
                m for m in all_metrics if any(perf in m for perf in ["PER_MINUTE", "RATE"])
            ],
        }

        for keyword, _ in metric_keywords.items():
            if keyword in query_lower:
                # Could add metric filtering in the future
                break

        return filters

    @handle_alert_tool_errors("list_alerts")
    async def list_alerts(
        self,
        client: ReveniumClient,
        page: int = 0,
        size: int = 20,
        filters: Optional[Dict[str, Any]] = None,
        query: Optional[str] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """List AI alerts with pagination and filtering.

        Args:
            client: Revenium API client
            page: Page number (0-based)
            size: Page size
            filters: Optional filters
            query: Optional natural language query

        Returns:
            Formatted response with alert list
        """
        logger.info(f"Listing alerts: page={page}, size={size}")

        # Parse natural language query if provided
        if query:
            parsed_filters = self._parse_natural_language_query(query)
            if filters:
                filters.update(parsed_filters)
            else:
                filters = parsed_filters

        # Call the client method
        response = await client.get_alerts(page=page, size=size, **(filters or {}))

        # Extract alerts from response
        alerts = client._extract_embedded_data(response)
        page_info = client._extract_pagination_info(response)

        if not alerts:
            return [
                TextContent(
                    type="text", text="📋 **No alerts found**\n\nNo alerts match your criteria."
                )
            ]

        # Format the response with enhanced field mapping
        alert_list = []
        for alert in alerts:
            # Enhanced field mapping for alert history
            alert_name = self._extract_alert_name(alert)
            triggered_time = self._format_timestamp(self._extract_triggered_time(alert))
            resolved_time = self._format_timestamp(self._extract_resolved_time(alert))
            state = self._extract_alert_state(alert)
            condition = self._extract_threshold_condition(alert)
            metric_type = self._extract_metric_type(alert)
            alert_type = self._extract_alert_type(alert)
            period_duration = self._extract_period_duration(alert)
            triggered_value = self._extract_triggered_value(alert)
            team_info = self._extract_team_info(alert)
            duration = self._calculate_duration(alert)

            # Use resolved status for display (for alert history events)
            resolved = alert.get("resolved", False)
            status_text = "Resolved" if resolved else "Active"

            alert_text = (
                f"**{alert_name}** ({status_text})\n"
                f"  • ID: `{alert.get('id', 'N/A')}`\n"
                f"  • State: {state}\n"
                f"  • Type: {alert_type}\n"
                f"  • Metric: {metric_type}\n"
                f"  • Condition: {condition}\n"
                f"  • Triggered Value: {triggered_value}\n"
                f"  • Period: {period_duration}\n"
                f"  • Team: {team_info}\n"
                f"  • Detected: {triggered_time}\n"
                f"  • Resolved: {resolved_time or 'Still Active'}\n"
                f"  • Duration: {duration}"
            )
            alert_list.append(alert_text)

        # Create pagination info
        total_pages = page_info.get("totalPages", 1)
        current_page = page + 1
        total_elements = page_info.get("totalElements", len(alerts))

        result_text = (
            f"**AI Alerts** (Page {current_page} of {total_pages})\n\n"
            f'**Note**: These are a history of triggered alerts. To see alert definitions/rules, use `resource_type="anomalies"` with `action="list"`\n\n'
            f"Found {len(alerts)} alerts (Total: {total_elements})\n\n" + "\n\n".join(alert_list)
        )

        if query:
            result_text = f'🔍 **Query:** "{query}"\n\n{result_text}'

        return [TextContent(type="text", text=result_text)]

    @handle_alert_tool_errors("get_alert")
    async def get_alert(
        self, client: ReveniumClient, alert_id: str
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get a specific alert by ID.

        Args:
            client: Revenium API client
            alert_id: ID of the alert to retrieve

        Returns:
            Formatted response with alert details
        """
        # Validate alert ID
        alert_id = validate_alert_id(alert_id)

        logger.info(f"Getting alert: {alert_id}")

        # Call the API client method
        alert = await client.get_alert_by_id(alert_id)

        # Enhanced field extraction for alert history
        alert_name = self._extract_alert_name(alert)
        triggered_time = self._format_timestamp(self._extract_triggered_time(alert))
        resolved_time = self._format_timestamp(self._extract_resolved_time(alert))
        state = self._extract_alert_state(alert)
        condition = self._extract_threshold_condition(alert)
        metric_type = self._extract_metric_type(alert)
        alert_type = self._extract_alert_type(alert)
        period_duration = self._extract_period_duration(alert)
        triggered_value = self._extract_triggered_value(alert)
        team_info = self._extract_team_info(alert)
        duration = self._calculate_duration(alert)

        # Use resolved status for display (for alert history events)
        resolved = alert.get("resolved", False)

        # Get description from nested anomaly object
        anomaly = alert.get("anomaly", {})
        description = (
            anomaly.get("description", "No description")
            if isinstance(anomaly, dict)
            else "No description"
        )

        result_text = (
            f"**Alert Event Details**\n\n"
            f"**Alert Name:** {alert_name}\n"
            f"**Event ID:** `{alert.get('id', 'N/A')}`\n"
            f"**State:** {state}\n"
            f"**Type:** {alert_type}\n"
            f"**Metric:** {metric_type}\n"
            f"**Condition:** {condition}\n"
            f"**Triggered Value:** {triggered_value}\n"
            f"**Period:** {period_duration}\n"
            f"**Team:** {team_info}\n"
            f"**Description:** {description}\n"
            f"**Detected:** {triggered_time}\n"
            f"**Resolved:** {resolved_time or 'Still Active'}\n"
            f"**Duration:** {duration}\n"
            f"**Resolved Status:** {'Yes' if resolved else 'No'}"
        )

        # Add additional API response details
        filters = alert.get("filters", [])
        if filters:
            result_text += f"\n\n**Filters:** {len(filters)} configured"
            for i, filter_item in enumerate(filters):
                if isinstance(filter_item, dict):
                    result_text += f"\n  {i+1}. {filter_item}"

        slack_configs = alert.get("slackConfigurations", [])
        webhook_configs = alert.get("webhookConfigurations", [])
        if slack_configs or webhook_configs:
            result_text += f"\n\n**Integrations:**"
            if slack_configs:
                result_text += f"\n  • Slack: {len(slack_configs)} configured"
            if webhook_configs:
                result_text += f"\n  • Webhooks: {len(webhook_configs)} configured"

        # Add percentage flag if relevant
        is_percentage = alert.get("isPercentage", False)
        if is_percentage:
            result_text += f"\n\n**Note:** Threshold is configured as a percentage value"

        # Add trigger persistence duration if available
        trigger_duration = alert.get("triggerAfterPersistsDuration")
        if trigger_duration:
            result_text += f"\n**Trigger Persistence:** {trigger_duration}"

        # Add group by information if available
        group_by = alert.get("groupBy")
        if group_by:
            result_text += f"\n**Grouped By:** {group_by}"

        # Add resource type and links
        resource_type = alert.get("resourceType")
        if resource_type:
            result_text += f"\n**Resource Type:** {resource_type}"

        links = alert.get("_links", {})
        if links and isinstance(links, dict):
            self_link = links.get("self", {}).get("href")
            if self_link:
                result_text += f"\n**API Link:** {self_link}"

        return [TextContent(type="text", text=result_text)]

    @handle_alert_tool_errors("update_alert")
    async def update_alert(
        self, client: ReveniumClient, alert_id: str, update_data: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Update an existing alert.

        Args:
            client: Revenium API client
            alert_id: ID of the alert to update
            update_data: Data to update

        Returns:
            Formatted response with updated alert details
        """
        # Validate alert ID
        alert_id = validate_alert_id(alert_id)

        if not isinstance(update_data, dict):
            raise ValidationError(
                message="update_data must be a dictionary",
                field="update_data",
                value=type(update_data).__name__,
                expected="Dictionary with update fields",
            )

        logger.info(f"Updating alert: {alert_id}")

        # Call the API client method
        updated_alert = await client.update_alert(alert_id, update_data)

        # Enhanced field extraction for updated alert
        alert_name = self._extract_alert_name(updated_alert)
        state = self._extract_alert_state(updated_alert)

        result_text = (
            f"**Alert Updated Successfully**\n\n"
            f"**Name:** {alert_name}\n"
            f"**ID:** `{updated_alert.get('id', 'N/A')}`\n"
            f"**State:** {state}\n"
            f"**Updated:** {updated_alert.get('updated_at', 'N/A')}"
        )

        return [TextContent(type="text", text=result_text)]

    @handle_alert_tool_errors("delete_alert")
    async def delete_alert(
        self, client: ReveniumClient, alert_id: str
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Delete an alert.

        Args:
            client: Revenium API client
            alert_id: ID of the alert to delete

        Returns:
            Formatted response confirming deletion
        """
        # Validate alert ID
        alert_id = validate_alert_id(alert_id)

        logger.info(f"Deleting alert: {alert_id}")

        # Call the API client method
        await client.delete_alert(alert_id)

        result_text = (
            f"**Alert Deleted Successfully**\n\n"
            f"**ID:** `{alert_id}`\n"
            f"The alert has been permanently removed."
        )

        return [TextContent(type="text", text=result_text)]

    @handle_alert_tool_errors("acknowledge_alert")
    async def acknowledge_alert(
        self, client: ReveniumClient, alert_id: str, acknowledged_by: Optional[str] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Acknowledge an alert.

        Args:
            client: Revenium API client
            alert_id: ID of the alert to acknowledge
            acknowledged_by: Who acknowledged the alert

        Returns:
            Formatted response confirming acknowledgment
        """
        # Validate alert ID
        alert_id = validate_alert_id(alert_id)

        logger.info(f"Acknowledging alert: {alert_id}")

        # Prepare update data
        update_data = {
            "status": "acknowledged",
            "acknowledged_at": datetime.now(timezone.utc).isoformat(),
        }

        if acknowledged_by:
            update_data["acknowledged_by"] = acknowledged_by

        # Call the API client method
        updated_alert = await client.update_alert(alert_id, update_data)

        # Enhanced field extraction
        alert_name = self._extract_alert_name(updated_alert)

        result_text = (
            f"**Alert Acknowledged Successfully**\n\n"
            f"**Name:** {alert_name}\n"
            f"**ID:** `{alert_id}`\n"
            f"**Status:** Acknowledged\n"
            f"**Acknowledged By:** {acknowledged_by or 'System'}\n"
            f"**Acknowledged At:** {update_data['acknowledged_at']}"
        )

        return [TextContent(type="text", text=result_text)]

    def _extract_alert_name(self, alert: Dict[str, Any]) -> str:
        """Extract alert name from alert history response."""
        # For alert history, the name comes from the nested anomaly object
        anomaly = alert.get("anomaly", {})
        if isinstance(anomaly, dict):
            # Try name and label from the anomaly definition
            for field in ["name", "label"]:
                value = anomaly.get(field)
                if value and isinstance(value, str) and value.strip():
                    return value.strip()

        # Fallback to alert event fields
        for field in ["name", "label", "description", "title"]:
            value = alert.get(field)
            if value and isinstance(value, str) and value.strip():
                return value.strip()

        # If no name found, construct from alert event ID
        alert_id = alert.get("id")
        if alert_id:
            return f"Alert Event {alert_id}"

        return "Untitled Alert"

    def _extract_triggered_time(self, alert: Dict[str, Any]) -> Optional[str]:
        """Extract triggered timestamp from alert history response."""
        # For alert history, use the triggeredTimestamp field
        triggered_timestamp = alert.get("triggeredTimestamp")
        if triggered_timestamp:
            if isinstance(triggered_timestamp, str):
                return triggered_timestamp
            elif hasattr(triggered_timestamp, "isoformat"):
                return triggered_timestamp.isoformat()
            else:
                return str(triggered_timestamp)

        # Fallback to other timestamp fields
        for field in ["created", "triggered_at", "trigger_timestamp", "detectedTime"]:
            value = alert.get(field)
            if value:
                if isinstance(value, str):
                    return value
                elif hasattr(value, "isoformat"):
                    return value.isoformat()
                else:
                    return str(value)
        return None

    def _extract_resolved_time(self, alert: Dict[str, Any]) -> Optional[str]:
        """Extract resolved timestamp from alert history response."""
        # For alert history, use the resolvedTimestamp field
        resolved_timestamp = alert.get("resolvedTimestamp")
        if resolved_timestamp:
            if isinstance(resolved_timestamp, str):
                return resolved_timestamp
            elif hasattr(resolved_timestamp, "isoformat"):
                return resolved_timestamp.isoformat()
            else:
                return str(resolved_timestamp)

        # Fallback to other resolution timestamp fields
        for field in ["updated", "resolved_at", "resolvedTime", "resolved_timestamp"]:
            value = alert.get(field)
            if value:
                if isinstance(value, str):
                    return value
                elif hasattr(value, "isoformat"):
                    return value.isoformat()
                else:
                    return str(value)
        return None

    def _extract_alert_state(self, alert: Dict[str, Any]) -> str:
        """Extract alert state from alert history response."""
        # For alert history, use the resolved boolean field first
        resolved = alert.get("resolved")
        if resolved is not None:
            return "Resolved" if resolved else "Firing"

        # Check if we have resolvedTimestamp to determine state
        resolved_timestamp = alert.get("resolvedTimestamp")
        if resolved_timestamp is not None:
            return "Resolved"  # Has resolution timestamp

        # Check for triggeredTimestamp - if present but no resolution, it's firing
        triggered_timestamp = alert.get("triggeredTimestamp")
        if triggered_timestamp is not None:
            return "Firing"  # Triggered but not resolved

        # Fallback: check the nested anomaly firing status
        anomaly = alert.get("anomaly", {})
        if isinstance(anomaly, dict):
            firing = anomaly.get("firing")
            enabled = anomaly.get("enabled")

            if enabled is False:
                return "Disabled"
            elif firing:
                return "Firing"
            else:
                return "Ready"

        # Final fallback to traditional state/status fields
        state = alert.get("state") or alert.get("status", "unknown")
        if not isinstance(state, str):
            state = str(state) if state is not None else "unknown"

        state_mapping = {
            "open": "Firing",
            "active": "Firing",
            "firing": "Firing",
            "resolved": "Resolved",
            "closed": "Resolved",
            "acknowledged": "Acknowledged",
            "acked": "Acknowledged",
        }

        return state_mapping.get(state.lower(), state.title())

    def _calculate_duration(self, alert: Dict[str, Any]) -> str:
        """Calculate alert duration if timestamps are available."""
        triggered = self._extract_triggered_time(alert)
        resolved = self._extract_resolved_time(alert)

        if not triggered:
            return "N/A"

        try:
            if dateutil is None:
                return "N/A (dateutil not available)"

            triggered_dt = dateutil.parser.parse(triggered)

            if resolved:
                resolved_dt = dateutil.parser.parse(resolved)
                duration = resolved_dt - triggered_dt

                # Format duration in a human-readable way
                total_seconds = int(duration.total_seconds())
                if total_seconds < 60:
                    return f"{total_seconds}s"
                elif total_seconds < 3600:
                    minutes = total_seconds // 60
                    seconds = total_seconds % 60
                    return f"{minutes}m {seconds}s"
                else:
                    hours = total_seconds // 3600
                    minutes = (total_seconds % 3600) // 60
                    return f"{hours}h {minutes}m"
            else:
                # Alert is still active, calculate time since triggered
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc)
                if triggered_dt.tzinfo is None:
                    triggered_dt = triggered_dt.replace(tzinfo=timezone.utc)
                duration = now - triggered_dt

                total_seconds = int(duration.total_seconds())
                if total_seconds < 60:
                    return f"{total_seconds}s (ongoing)"
                elif total_seconds < 3600:
                    minutes = total_seconds // 60
                    return f"{minutes}m (ongoing)"
                else:
                    hours = total_seconds // 3600
                    minutes = (total_seconds % 3600) // 60
                    return f"{hours}h {minutes}m (ongoing)"

        except Exception as e:
            logger.debug(f"Error calculating duration: {e}")
            return "N/A"

    def _extract_threshold_condition(self, alert: Dict[str, Any]) -> str:
        """Extract threshold condition from alert history response."""
        # For alert history, get threshold info from the nested anomaly object
        anomaly = alert.get("anomaly", {})
        if isinstance(anomaly, dict):
            operator_type = anomaly.get("operatorType")
            threshold = anomaly.get("threshold")
            is_percentage = anomaly.get("isPercentage", False)

            if operator_type and threshold is not None:
                # Map operator types to readable symbols
                operator_mapping = {
                    "GREATER_THAN": ">",
                    "GREATER_THAN_OR_EQUAL_TO": "≥",
                    "LESS_THAN": "<",
                    "LESS_THAN_OR_EQUAL_TO": "≤",
                    "EQUALS": "=",
                    "NOT_EQUALS": "≠",
                }

                operator_symbol = operator_mapping.get(operator_type, operator_type)

                # Format threshold value
                if is_percentage:
                    threshold_str = f"{threshold}%"
                else:
                    # Format large numbers nicely
                    if threshold >= 1000000:
                        threshold_str = f"{threshold/1000000:.1f}M"
                    elif threshold >= 1000:
                        threshold_str = f"{threshold/1000:.1f}K"
                    else:
                        threshold_str = str(threshold)

                return f"{operator_symbol} {threshold_str}"

        # Fallback to direct alert fields
        operator_type = alert.get("operatorType")
        threshold = alert.get("threshold")
        is_percentage = alert.get("isPercentage", False)

        if operator_type and threshold is not None:
            operator_mapping = {
                "GREATER_THAN": ">",
                "GREATER_THAN_OR_EQUAL_TO": "≥",
                "LESS_THAN": "<",
                "LESS_THAN_OR_EQUAL_TO": "≤",
                "EQUALS": "=",
                "NOT_EQUALS": "≠",
            }

            operator_symbol = operator_mapping.get(operator_type, operator_type)
            threshold_str = f"{threshold}%" if is_percentage else str(threshold)
            return f"{operator_symbol} {threshold_str}"

        return "N/A"

    def _extract_metric_type(self, alert: Dict[str, Any]) -> str:
        """Extract metric type from alert history response."""
        # For alert history, get metric type from the nested anomaly object
        anomaly = alert.get("anomaly", {})
        if isinstance(anomaly, dict):
            metric_type = anomaly.get("metricType")
            if metric_type and isinstance(metric_type, str):
                return metric_type.strip()

        # Fallback to direct alert fields
        metric_type = alert.get("metricType")
        if metric_type and isinstance(metric_type, str):
            return metric_type.strip()

        # Try other field names as fallback
        for field in ["metric_type", "metric", "metric_name"]:
            value = alert.get(field)
            if value and isinstance(value, str) and value.strip():
                return value.strip()

        return "N/A"

    def _extract_anomaly_name(self, alert: Dict[str, Any]) -> str:
        """Extract anomaly name from alert data."""
        # Based on the actual API response structure:
        # The alert itself IS the anomaly, so use the alert name
        # This is different from our original assumption

        # Try the alert's own name/label first
        for field in ["name", "label"]:
            value = alert.get(field)
            if value and isinstance(value, str) and value.strip():
                return value.strip()

        # Try other anomaly-specific field names as fallback
        for field in ["anomaly_name", "anomalyName", "anomaly_title"]:
            value = alert.get(field)
            if value and isinstance(value, str) and value.strip():
                return value.strip()

        # Fall back to anomaly ID if name not available
        anomaly_id = alert.get("id") or alert.get("anomaly_id") or alert.get("anomalyId")
        if anomaly_id:
            return f"ID: {anomaly_id}"

        return "N/A"

    def _extract_triggered_value(self, alert: Dict[str, Any]) -> str:
        """Extract the triggered value from alert history response."""
        # For alert history, get the actual value that triggered the alert
        triggered_value = alert.get("triggeredValue")
        if triggered_value is not None:
            # Format large numbers nicely
            if isinstance(triggered_value, (int, float)):
                if triggered_value >= 1000000:
                    return f"{triggered_value/1000000:.1f}M"
                elif triggered_value >= 1000:
                    return f"{triggered_value/1000:.1f}K"
                else:
                    return str(triggered_value)
            else:
                return str(triggered_value)
        return "N/A"

    def _extract_alert_type(self, alert: Dict[str, Any]) -> str:
        """Extract alert type from alert history response."""
        # For alert history, get alert type from the nested anomaly object
        anomaly = alert.get("anomaly", {})
        if isinstance(anomaly, dict):
            alert_type = anomaly.get("alertType")
            if alert_type and isinstance(alert_type, str):
                # Make it more readable
                type_mapping = {
                    "CUMULATIVE_USAGE": "Cumulative Usage",
                    "THRESHOLD": "Threshold",
                    "RELATIVE_CHANGE": "Relative Change",
                }
                return type_mapping.get(alert_type, alert_type.replace("_", " ").title())

        # Fallback to direct alert fields
        alert_type = alert.get("alertType")
        if alert_type and isinstance(alert_type, str):
            type_mapping = {
                "CUMULATIVE_USAGE": "Cumulative Usage",
                "THRESHOLD": "Threshold",
                "RELATIVE_CHANGE": "Relative Change",
            }
            return type_mapping.get(alert_type, alert_type.replace("_", " ").title())
        return "N/A"

    def _extract_period_duration(self, alert: Dict[str, Any]) -> str:
        """Extract period duration from alert history response."""
        # For alert history, get period duration from the nested anomaly object
        anomaly = alert.get("anomaly", {})
        if isinstance(anomaly, dict):
            period = anomaly.get("periodDuration")
            if period and isinstance(period, str):
                # Make it more readable
                period_mapping = {
                    "ONE_MINUTE": "1 minute",
                    "FIVE_MINUTES": "5 minutes",
                    "FIFTEEN_MINUTES": "15 minutes",
                    "THIRTY_MINUTES": "30 minutes",
                    "HOURLY": "Hourly",
                    "DAILY": "Daily",
                    "WEEKLY": "Weekly",
                    "MONTHLY": "Monthly",
                }
                return period_mapping.get(period, period.replace("_", " ").title())

        # Fallback to direct alert fields
        period = alert.get("periodDuration")
        if period and isinstance(period, str):
            period_mapping = {
                "ONE_MINUTE": "1 minute",
                "FIVE_MINUTES": "5 minutes",
                "FIFTEEN_MINUTES": "15 minutes",
                "THIRTY_MINUTES": "30 minutes",
                "HOURLY": "Hourly",
                "DAILY": "Daily",
                "WEEKLY": "Weekly",
                "MONTHLY": "Monthly",
            }
            return period_mapping.get(period, period.replace("_", " ").title())
        return "N/A"

    def _extract_notification_addresses(self, alert: Dict[str, Any]) -> str:
        """Extract notification addresses from alert data."""
        # Based on the actual API response structure:
        # 'notificationAddresses' - array of email addresses
        addresses = alert.get("notificationAddresses", [])
        if addresses and isinstance(addresses, list):
            return ", ".join(addresses)
        return "None"

    def _extract_team_info(self, alert: Dict[str, Any]) -> str:
        """Extract team information from alert data."""
        # Based on the actual API response structure:
        # 'team' - nested object with team details
        team = alert.get("team", {})
        if isinstance(team, dict):
            team_label = team.get("label", team.get("name", ""))
            team_id = team.get("id", "")
            if team_label:
                return f"{team_label} ({team_id})" if team_id else team_label
            elif team_id:
                return team_id
        return "N/A"

    def _extract_severity(self, alert: Dict[str, Any]) -> str:
        """Extract severity from alert data."""
        # Try different field names for severity
        for field in ["severity", "priority", "level"]:
            value = alert.get(field)
            if value and isinstance(value, str) and value.strip():
                return value.strip().title()

        # Try to get from threshold violation
        threshold_violation = alert.get("threshold_violation")
        if threshold_violation and isinstance(threshold_violation, dict):
            severity = threshold_violation.get("severity")
            if severity and isinstance(severity, str):
                return severity.strip().title()

        # Default severity
        return "Medium"

    def _format_timestamp(self, timestamp: Optional[str]) -> str:
        """Format timestamp for display."""
        if not timestamp:
            return "N/A"

        try:
            if dateutil is None:
                # Fallback: return first 19 characters if dateutil not available
                return timestamp[:19] if len(timestamp) >= 19 else timestamp

            dt = dateutil.parser.parse(timestamp)
            # Format as readable datetime
            return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except Exception as e:
            logger.debug(f"Error formatting timestamp {timestamp}: {e}")
            # Return first 19 characters (YYYY-MM-DD HH:MM:SS) if parsing fails
            return timestamp[:19] if len(timestamp) >= 19 else timestamp
