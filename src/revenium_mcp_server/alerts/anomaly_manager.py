"""Anomaly management functionality for Revenium MCP server.

This module provides CRUD operations and management functionality
for AI anomalies in the Revenium platform.
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..client import ReveniumAPIError, ReveniumClient
from ..common.error_handling import (
    ToolError,
    ErrorCodes,
    create_structured_validation_error,
    raise_refusal,
)
from ..error_handlers import (
    handle_alert_tool_errors,
    validate_anomaly_id,
)
from ..exceptions import AnomalyNotFoundError, ValidationError
from ..alert_metrics import check_metric_rules
from ..alert_operators import (
    ACCEPTED_OPERATORS,
    CHANGE_OPERATORS,
    FILTER_LIST_OPERATOR,
    OPERATOR_LABELS,
    accepted_operators_for,
    is_rejected_operator,
    rejected_operator_message,
    threshold_is_percentage,
    validate_filter_rows,
)
from .alert_manager import format_alert_value
from ..validators import InputValidator
from .anomaly_inventory import read_every_anomaly
from .notification_recipients import RECIPIENT_FIELDS, update_recipients
from .update_fidelity import (
    ordered_periods_for,
    refuse_platform_rule_breach,
    refuse_unknown_data_source,
    refuse_update_rule_breach,
    refuse_unsupported_update_fields,
    resolve_update_period,
    threshold_number,
    verify_update_applied,
)

_RESOLVED_AFTER_CONVERSION = frozenset(RECIPIENT_FIELDS) | {"period"}

# Fields every stored alert carries; an update may change them but never empty them.
_REQUIRED_UPDATE_FIELDS = frozenset(
    {
        "alert_type", "metric_type", "operator_type", "tracking_period",
        "name", "alertType", "metricType", "operatorType", "periodDuration", "enabled",
    }
)

# A null here means no change. AIAnomalyService.update keeps the stored dataSource,
# isPercentage and minSampleCount when sent null (dev check, 2026-10-18).
_NO_CHANGE_WHEN_NULL = frozenset(
    {"dataSource", "isPercentage", "minSampleCount", "is_percentage", "webhook_configurations"}
)
_NO_CHANGE_WHEN_BLANK = frozenset({"is_percentage", "webhook_configurations"})


def _changes_nothing(key: str, value: Any) -> bool:
    """Whether an update value leaves the stored field as it is."""
    if key in _NO_CHANGE_WHEN_BLANK and isinstance(value, str):
        return not value.strip()
    return value is None and key in _NO_CHANGE_WHEN_NULL


@dataclass(frozen=True)
class UpdatePlan:
    """The body an update would send, after every check the live update runs."""

    anomaly_id: str
    body: Dict[str, Any]
    changes: Dict[str, Any]


def _as_number(threshold: Any) -> Any:
    """A threshold string in number form, sent as the number create sends; anything else as given."""
    number = threshold_number(threshold)
    return number if isinstance(threshold, str) and number is not None else threshold


def format_filter_row(filter_item: Dict[str, Any]) -> str:
    """Render one stored filter row as the comparison it expresses.

    An IN row keeps its set in ``values`` and its ``value`` comes back null, so
    rendering ``value`` alone showed the reader ``MODEL IN 'None'`` for a row
    that matches several models.
    """
    dimension = filter_item.get("dimension", "N/A")
    operator = filter_item.get("operator", "N/A")
    values = filter_item.get("values")
    if str(operator).upper() == FILTER_LIST_OPERATOR and isinstance(values, list) and values:
        rendered = ", ".join(f"'{entry}'" for entry in values)
        return f"{dimension} {operator} [{rendered}]"
    return f"{dimension} {operator} '{filter_item.get('value', 'N/A')}'"


def alert_label(name: Any, anomaly_id: Any) -> str:
    """How an answer names an alert: name and id, or the id alone when the platform sent no name."""
    named = isinstance(name, str) and bool(name.strip())
    if anomaly_id is None:
        return f"Alert with no id ({name})" if named else "Alert with no id"
    return f"{name} ({anomaly_id})" if named else f"{anomaly_id} (no name)"


def refuse_clearing_required_field(field_name: str, value: Any) -> None:
    """Refuse a null or blank value for a field every stored alert must carry, before the update is sent."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise create_structured_validation_error(
            message=f"{field_name} is required; send a value, or leave it out to keep the stored one",
            field=field_name,
            value=value,
            suggestions=[
                f"Send a value for {field_name}, or leave it out to keep the stored one"
            ],
        )


FIRING_STATE_LABELS = {
    "FIRING": "Firing",
    "NOT_FIRING": "Not firing",
    "UNKNOWN": "Unknown (could not be read just now)",
}


def _threshold_label(anomaly: Dict[str, Any]) -> str:
    threshold = anomaly.get("threshold", "N/A")
    if threshold_is_percentage(anomaly):
        return f"{threshold}% (percentage)"
    if isinstance(threshold, (int, float)) and not isinstance(threshold, bool):
        return format_alert_value(threshold, str(anomaly.get("metricType") or ""))
    return str(threshold)


def _operator_label(operator_type: Any) -> str:
    """The operator in words with the platform's name beside it, or the raw name."""
    label = OPERATOR_LABELS.get(operator_type)
    return f"{label} ({operator_type})" if label else str(operator_type)


def format_status(anomaly: Dict[str, Any]) -> str:
    """Render the enabled status, with the ``firingState`` the platform reports.

    A disabled rule can keep its last firing state, so for one that is
    disabled the state is labelled as the last one rather than the current.
    """
    enabled = anomaly.get("enabled", True)
    status = "Enabled" if enabled else "Disabled"
    firing_state = anomaly.get("firingState")
    if firing_state is None:
        return status
    label = FIRING_STATE_LABELS.get(firing_state, str(firing_state))
    if enabled:
        return f"{status}; firing state: {label}"
    return f"{status}; last firing state: {label}"


_REFUSAL_REASON_LIMIT = 200
_REFUSALS_LISTED = 10


def _refusal_reason(error: Exception) -> str:
    """The platform's reason for a refused delete, on one line and at most 200 characters."""
    reason = " ".join(str(error).split()) or type(error).__name__
    return reason[:_REFUSAL_REASON_LIMIT]


def _is_client_error(error: Exception) -> bool:
    return isinstance(error, ReveniumAPIError) and 400 <= (error.status_code or 0) < 500


def _names_a_missing_id(error: ReveniumAPIError) -> bool:
    if error.status_code == 404:
        return True
    return error.status_code == 400 and "failed to decode hashed id" in str(error.response_data).lower()


async def _slack_configuration_found(client: ReveniumClient, config_id: str) -> Optional[bool]:
    """True or False when the lookup settles it, None when it fails for another reason."""
    try:
        await client.get_slack_configuration_by_id(config_id)
    except ReveniumAPIError as lookup_error:
        return False if _names_a_missing_id(lookup_error) else None
    except Exception:
        return None
    return True


async def _refuse_unknown_slack_configuration(
    client: ReveniumClient, body: Dict[str, Any], error: Exception, verb: str
) -> None:
    """Name the Slack configuration a refused anomaly write carried that this organization lacks.

    The platform answers a bad id in slackConfigurations on the anomaly endpoint, so the
    client's message names the alert's id instead. Returns when the lookups cannot show
    a missing configuration, and the caller re-raises its original error.
    """
    slack_ids = body.get("slackConfigurations") or []
    if not slack_ids or not _is_client_error(error):
        return
    found = {config_id: await _slack_configuration_found(client, config_id) for config_id in slack_ids}
    missing = [config_id for config_id, exists in found.items() if exists is False]
    if not missing or None in found.values():
        return
    noun, was = ("Slack configuration", "was") if len(missing) == 1 else ("Slack configurations", "were")
    raise ValidationError(
        message=(
            f"{noun} {', '.join(missing)} {was} not found in this organization; "
            f"nothing was {verb}"
        ),
        field="slackConfigurations",
        value=missing,
        expected="The id of a Slack configuration this organization has",
        suggestion=(
            "Run slack_management(action='list_configurations') to see this "
            "organization's Slack configurations, then retry with one of those ids"
        ),
    )


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
                validated_data["filters"] = validate_filter_rows(filters)

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
            status = format_status(anomaly)

            # Generate notification summary
            notification_summary = self._format_notification_summary(anomaly)

            # Always show filter information - either specific filters or "No filters"
            anomaly_filters: List[Dict[str, Any]] = anomaly.get("filters", [])
            filter_summary = ""
            if anomaly_filters:
                filter_count = len(anomaly_filters)
                if filter_count == 1:
                    filter_summary = f"\n  • Filter: {format_filter_row(anomaly_filters[0])}"
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
                f"  • {status}\n"
                f"  • Threshold: {_threshold_label(anomaly)}\n"
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

        # Call the API client method. The anomalies service answers 403 for an
        # id that never existed and for one this key cannot read, and 404 for
        # the rest; both mean "no anomaly here" from the caller's POV, and the
        # raw "HTTP 403: Access Denied" that used to escape read as a
        # permissions problem instead. Fold those two into
        # AnomalyNotFoundError so @handle_alert_tool_errors renders the named
        # not-found envelope, the same shape AlertManager.get_alert produces
        # for resource_type="alerts" (BACK-2938).
        #
        # 500 is deliberately NOT folded: a backend outage is not evidence the
        # anomaly is missing, and reporting it as not-found would send the
        # caller looking for a deleted record instead of a broken service.
        # AlertManager.get_alert does not fold a 5xx either; it names it a
        # server error (BACK-4705).
        try:
            anomaly = await client.get_anomaly_by_id(anomaly_id)
        except ReveniumAPIError as e:
            if e.status_code in (403, 404):
                raise AnomalyNotFoundError(anomaly_id) from e
            raise

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
                filter_list.append(f"  • {format_filter_row(filter_item)}")
            filters_text = "\n\n**Filters Applied:**\n" + "\n".join(filter_list)

        result_text = (
            f"**AI Anomaly Details**\n\n"
            f"**Name:** {anomaly.get('name', 'Unnamed')}\n"
            f"**ID:** `{anomaly.get('id', 'N/A')}`\n"
            f"**Status:** {format_status(anomaly)}\n"
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
            result_text += "\n\n**Alert Configuration:**"
            result_text += f"\n  • **Type:** {alert_type}"
            if metric_type:
                result_text += f"\n  • **Metric:** {metric_type}"
            if threshold is not None:
                threshold_text = _threshold_label(anomaly)
                if operator_type:
                    operator_symbol = OPERATOR_LABELS.get(operator_type, operator_type)
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

    def validate_anomaly_payload(self, anomaly_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate the shape of anomaly_data, without converting or creating.

        This is only the first step of a create. Previews and validation must call
        prepare_create, which adds the detection_rules conversion and the short-period
        refusal the create runs; this method alone approves payloads the create refuses.

        Returns:
            The validated/sanitized data dict.

        Raises:
            ValidationError: on any rule the live create would reject.
        """
        if not isinstance(anomaly_data, dict):
            raise ValidationError(
                message="anomaly_data must be a dictionary",
                field="anomaly_data",
                value=type(anomaly_data).__name__,
                expected="Dictionary with anomaly fields",
            )

        validated_data: Dict[str, Any] = {}

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
            if "is_percentage" in anomaly_data:
                validated_data["is_percentage"] = self._percentage_flag(anomaly_data["is_percentage"])
            validated_data.update(self._detection_rules_notification_targets(anomaly_data))
        elif self._has_direct_api_format(anomaly_data):
            # User provided direct API format - validate and use as-is
            validated_data.update(self._validate_direct_api_format(anomaly_data))
        else:
            raise ValidationError(
                message="Either detection_rules or direct API format (alertType, metricType, operatorType, threshold) is required",
                field="anomaly_data",
                expected="Detection rules list OR direct API format fields",
                suggestion="• For real-time monitoring: `create_threshold_alert(name='Alert', threshold=100, period_minutes=15)`\n"
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
        for field in ["status", "enabled", "team_id", "notification_settings", "metadata", "dataSource"]:
            if field in anomaly_data:
                if field == "team_id" and not anomaly_data[field]:
                    raise ValidationError(
                        message="Team ID is required", field="team_id", expected="Non-empty string"
                    )
                validated_data[field] = anomaly_data[field]

        return validated_data

    @staticmethod
    def _detection_rules_notification_targets(anomaly_data: Dict[str, Any]) -> Dict[str, Any]:
        """The recipients and Slack channels a detection_rules payload names, as lists."""
        for field in ("notificationAddresses", "slackConfigurations", "slack_configurations"):
            if field in anomaly_data and not isinstance(anomaly_data[field], list):
                raise ValidationError(
                    message=f"Invalid {field} value",
                    field=field,
                    value=type(anomaly_data[field]).__name__,
                    expected="List/array",
                )
        targets: Dict[str, Any] = {}
        if "notificationAddresses" in anomaly_data:
            targets["notificationAddresses"] = anomaly_data["notificationAddresses"]
        slack_configurations = [
            *anomaly_data.get("slackConfigurations", []),
            *anomaly_data.get("slack_configurations", []),
        ]
        slack_config_id = anomaly_data.get("slackConfigId")
        if isinstance(slack_config_id, str) and slack_config_id.strip():
            slack_configurations.append(slack_config_id.strip())
        if slack_configurations:
            targets["slackConfigurations"] = list(dict.fromkeys(slack_configurations))
        return targets

    @staticmethod
    def _percentage_flag(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true"
        raise ValidationError(
            message=f"is_percentage must be true or false, got {value!r}",
            field="is_percentage",
            value=value,
            expected="true or false",
        )

    def prepare_create(self, anomaly_data: Dict[str, Any], team_id: Optional[str]) -> Dict[str, Any]:
        """The body a create would send, after every check and conversion the create runs.

        Shared by create_anomaly and the validate / create dry-run preview, so a preview
        cannot approve what the create refuses. Undecorated: refusals reach the caller as raised.
        """
        # Before the shape check, whose periodDuration list would otherwise answer
        # TEN_MINUTES with an unflagged "invalid value" instead of the period rule.
        if isinstance(anomaly_data, dict):
            refuse_platform_rule_breach(anomaly_data)
        validated_data = self.validate_anomaly_payload(anomaly_data)

        # Convert to API format (only if we have detection_rules, otherwise use direct format)
        if "detection_rules" in validated_data:
            try:
                api_data = InputValidator.convert_to_api_format(validated_data)
            except ToolError:
                raise
            except Exception as e:
                raise ValidationError(
                    message=f"Failed to convert to API format: {str(e)}",
                    field="anomaly_data",
                    expected="Valid anomaly data structure",
                )
        else:
            # Direct API format - use validated data as-is, just add required fields
            api_data = validated_data.copy()

            # Operator aliases, the IN/values exclusivity and the row shape are all
            # resolved by validate_filter_rows during payload validation.
            if "filters" in api_data and isinstance(api_data["filters"], list):
                api_data["filters"] = validate_filter_rows(api_data["filters"])

            # Ensure required API fields are present
            if "label" not in api_data and "name" in validated_data:
                api_data["label"] = validated_data["name"]
            if "teamId" not in api_data:
                api_data["teamId"] = team_id

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
                elif api_data.get("alertType") in ("CUMULATIVE_USAGE", "RELATIVE_CHANGE"):
                    api_data["periodDuration"] = "DAILY"  # Default for cumulative/relative change
                else:
                    api_data["periodDuration"] = "FIFTEEN_MINUTES"  # Safe default

        # The detection_rules conversion picks the period from time_window (15m when blank).
        refuse_platform_rule_breach(api_data)
        return api_data

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
        logger.info(f"Creating anomaly: {anomaly_data.get('name', 'Unnamed') if isinstance(anomaly_data, dict) else 'Unnamed'}")

        api_data = self.prepare_create(anomaly_data, client.team_id)

        # DEBUG: Log the final API data before sending to help troubleshoot JSON issues
        logger.debug(f"Final API data type: {type(api_data)}")
        logger.debug(f"Final API data keys: {list(api_data.keys()) if isinstance(api_data, dict) else 'Not a dict'}")
        logger.debug(f"Final API data being sent to create_anomaly: {json.dumps(api_data, indent=2, default=str)}")

        # Call the API client method
        try:
            created_anomaly = await client.create_anomaly(api_data)
        except Exception as e:
            logger.error(f"Failed to create anomaly: {e}")
            await _refuse_unknown_slack_configuration(client, api_data, e, "created")
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
                        "• create_threshold_alert(name='Alert', threshold=100, period_minutes=15)",
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
            f"**Operator:** {_operator_label(created_anomaly.get('operatorType', 'N/A'))}\n"
            f"**Threshold:** {_threshold_label(created_anomaly)}\n"
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
            result_text += "\n\n**Filters Applied:**"
            for filter_item in filters:
                result_text += f"\n  • {format_filter_row(filter_item)}"

        return [TextContent(type="text", text=result_text)]

    async def prepare_update(
        self, client: ReveniumClient, anomaly_id: str, update_data: Dict[str, Any]
    ) -> UpdatePlan:
        """Read the stored alert and build the update body, running every check the update runs.

        Shared by update_anomaly and preview_update, so a preview cannot approve what the
        update refuses. Left undecorated: refusals reach the caller's decorator unchanged.
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

        refuse_unsupported_update_fields(update_data)
        refuse_unknown_data_source(update_data)

        logger.info(f"Updating anomaly: {anomaly_id}")

        # Get current anomaly data first (like enable/disable operations do)
        current_anomaly = await client.get_anomaly_by_id(str(anomaly_id))

        # Start with current data and apply updates
        merged_data = current_anomaly.copy()

        # Handle field name conversions for user-friendly field names
        converted_updates: Dict[str, Any] = {}
        for key, value in update_data.items():
            if key in _RESOLVED_AFTER_CONVERSION or _changes_nothing(key, value):
                continue
            if key in _REQUIRED_UPDATE_FIELDS:
                refuse_clearing_required_field(key, value)
            if key == "slackConfigId" or key == "slack_config_id":
                # Convert 'slackConfigId' or 'slack_config_id' to 'slackConfigurations' array
                if value is None:
                    converted_updates["slackConfigurations"] = []
                elif isinstance(value, str):
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
                            # Already in API format: the same row check the create
                            # path runs, so an IN row keeps its values list here
                            # instead of being rebuilt as a value-only row.
                            converted_updates["filters"] = validate_filter_rows(value)
                        else:
                            # User-friendly format, convert to API format
                            converted_updates["filters"] = (
                                InputValidator._convert_filters_to_api_format(value)
                            )
                    except ValidationError:
                        # validate_filter_rows already names the offending field
                        # (values, operator, filters); re-wrapping it here would
                        # bury that behind a generic "Invalid filter format".
                        raise
                    except Exception as e:
                        raise ValidationError(
                            message=f"Invalid filter format: {str(e)}",
                            field="filters",
                            value=value,
                            expected="List of filter dictionaries with dimension/operator/value or field/operator/value",
                            suggestion="Use format: [{'dimension': 'PROVIDER', 'operator': 'CONTAINS', 'value': 'openai'}] or [{'field': 'provider', 'operator': 'contains', 'value': 'openai'}], or [{'dimension': 'MODEL', 'operator': 'IN', 'values': ['gpt-4', 'claude-sonnet-4-5']}]",
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
                    15: "FIFTEEN_MINUTES",
                    30: "THIRTY_MINUTES",
                    60: "ONE_HOUR",
                    720: "TWELVE_HOURS",
                    1440: "DAILY",  # as create_threshold_alert maps it
                }
                try:
                    minutes = int(float(value))
                    alert_type = str(
                        update_data.get("alertType")
                        or update_data.get("alert_type")
                        or current_anomaly.get("alertType")
                        or ""
                    ).upper()
                    if minutes in period_mapping:
                        converted_updates["periodDuration"] = period_mapping[minutes]
                    elif alert_type == "CUMULATIVE_USAGE":
                        budget_periods = ", ".join(ordered_periods_for("CUMULATIVE_USAGE", None))
                        raise ValidationError(
                            message=(
                                f"Invalid period_minutes value: {minutes}; a CUMULATIVE_USAGE "
                                f"(budget) alert takes only {budget_periods}"
                            ),
                            field="period_minutes",
                            value=value,
                            expected=f"period as one of: {budget_periods.lower()}",
                            suggestion="Send period (daily, weekly, monthly or quarterly) instead of period_minutes",
                        )
                    else:
                        raise ValidationError(
                            message=(
                                f"Invalid period_minutes value: {minutes}; the platform "
                                "requires FIFTEEN_MINUTES or longer"
                            ),
                            field="period_minutes",
                            value=value,
                            expected="One of: 15, 30, 60, 720, 1440 minutes",
                            suggestion="Use standard intervals: 15, 30, 60, 720, 1440 minutes",
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
                converted_updates["triggerAfterPersistsDuration"] = (
                    None if value is None or value == "" else str(value)
                )
            elif key == "tracking_period":
                # Convert 'tracking_period' to 'periodDuration' for CUMULATIVE_USAGE alerts
                # Map user-friendly period names to API format
                tracking_period_mapping: Dict[str, str] = {
                    "daily": "DAILY",
                    "weekly": "WEEKLY",
                    "monthly": "MONTHLY",
                    "quarterly": "QUARTERLY",
                }
                period_value = str(value).lower()
                if period_value in tracking_period_mapping:
                    converted_updates["periodDuration"] = tracking_period_mapping[period_value]
                else:
                    # Pass through as-is if already in API format
                    converted_updates["periodDuration"] = str(value)
            elif key == "threshold":
                converted_updates["threshold"] = _as_number(value)
            elif key == "webhook_configurations":
                # Convert 'webhook_configurations' to 'webhookConfigurations'
                converted_updates["webhookConfigurations"] = (
                    value if isinstance(value, list) else [value]
                )
            else:
                # Pass through other fields as-is
                converted_updates[key] = value

        self._convert_recipients(update_data, converted_updates)
        self._convert_period(update_data, converted_updates, current_anomaly)

        # Apply the converted updates to the current data
        merged_data.update(converted_updates)

        self._check_update_operator(converted_updates, merged_data)

        # The platform checks the whole merged alert on every update, stored values included.
        refuse_update_rule_breach(merged_data, current_anomaly, converted_updates)

        return UpdatePlan(anomaly_id, merged_data, converted_updates)

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
        plan = await self.prepare_update(client, anomaly_id, update_data)
        anomaly_id = plan.anomaly_id

        try:
            updated_anomaly = await client.update_anomaly(anomaly_id, plan.body)
        except Exception as e:
            await _refuse_unknown_slack_configuration(client, plan.changes, e, "updated")
            raise

        await verify_update_applied(client, anomaly_id, plan.changes, updated_anomaly)

        result_text = (
            f"**AI Anomaly Updated Successfully**\n\n"
            f"**Name:** {updated_anomaly.get('name', 'Unnamed')}\n"
            f"**ID:** `{updated_anomaly.get('id', 'N/A')}`\n"
            f"**Status:** {updated_anomaly.get('enabled', True) and 'Enabled' or 'Disabled'}\n"
            f"**Updated:** {updated_anomaly.get('updatedAt', updated_anomaly.get('updated', 'N/A'))}"
        )
        if updated_anomaly.get("periodDuration"):
            result_text += f"\n**Check Frequency:** {updated_anomaly['periodDuration']}"

        # An update is the one call that can change the filters, so it confirms
        # them the way get and create do — through format_filter_row, or an IN row
        # reads back as its null scalar value.
        updated_filters = updated_anomaly.get("filters", [])
        if updated_filters:
            result_text += "\n\n**Filters Applied:**"
            for filter_item in updated_filters:
                result_text += f"\n  • {format_filter_row(filter_item)}"

        # Always show current notification configuration (not conditional)
        notification_text = await self._format_notification_configuration(client, updated_anomaly)
        result_text += notification_text

        return [TextContent(type="text", text=result_text)]

    @handle_alert_tool_errors("preview_update")
    async def preview_update(
        self, client: ReveniumClient, anomaly_id: str, update_data: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Answer what update_anomaly would do with the same arguments, without sending it."""
        plan = await self.prepare_update(client, anomaly_id, update_data)
        validation_result = {
            "dry_run": True,
            "operation": "update_anomaly",
            "valid": True,
            "message": "**Dry Run Successful**: Update data is valid and ready for application",
            "would_update": {"anomaly_id": plan.anomaly_id, "changes": plan.changes},
        }
        result_text = f"**DRY RUN MODE**\n\n{json.dumps(validation_result, indent=2)}"
        return [TextContent(type="text", text=result_text)]

    @staticmethod
    def _convert_recipients(update_data: Dict[str, Any], converted_updates: Dict[str, Any]) -> None:
        recipients = update_recipients(update_data)
        if recipients is not None:
            converted_updates["notificationAddresses"] = recipients

    @staticmethod
    def _convert_period(
        update_data: Dict[str, Any],
        converted_updates: Dict[str, Any],
        current_anomaly: Dict[str, Any],
    ) -> None:
        if "period" not in update_data:
            return
        period_duration = resolve_update_period(
            update_data["period"],
            converted_updates.get("alertType", current_anomaly.get("alertType")),
            converted_updates.get("dataSource", current_anomaly.get("dataSource")),
        )
        explicit = converted_updates.get("periodDuration")
        if explicit is not None and explicit != period_duration:
            raise create_structured_validation_error(
                message=(
                    f"period '{update_data['period']}' and periodDuration '{explicit}' disagree; "
                    "send one of them. Nothing was updated."
                ),
                field="period",
                value=update_data["period"],
            )
        converted_updates["periodDuration"] = period_duration

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

        # Read every page before deleting anything: deleting while paging shifts
        # later rows onto pages already read.
        inventory = await read_every_anomaly(client)
        anomalies = inventory.anomalies

        if not anomalies and inventory.complete:
            return [
                TextContent(
                    type="text",
                    text="**No anomalies to clear**\n\nThere are no anomalies in the system.",
                )
            ]

        # Delete each anomaly, keeping the platform's reason for every refusal
        deleted_count = 0
        refusals: List[str] = []
        for anomaly in anomalies:
            anomaly_id = anomaly.get("id")
            if not anomaly_id:
                refusals.append("Alert with no id: no id returned by the platform")
                continue
            try:
                await client.delete_anomaly(anomaly_id)
                deleted_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete anomaly {anomaly_id}: {e}")
                label = alert_label(anomaly.get("name"), anomaly_id)
                refusals.append(f"{label}: {_refusal_reason(e)}")

        cleared_everything = inventory.complete and deleted_count == len(anomalies)
        if deleted_count == 0:
            heading = "Anomalies Not Cleared"
        elif cleared_everything:
            heading = "Anomalies Cleared Successfully"
        else:
            heading = "Anomalies Partly Cleared"
        result_text = (
            f"**{heading}**\n\n"
            f"**Deleted:** {deleted_count} of {inventory.total} anomalies\n"
            f"**Total Found:** {len(anomalies)}"
        )
        result_text += inventory.coverage_note(
            "deletes were attempted" if deleted_count == 0 else "anomalies were deleted"
        )

        if deleted_count < len(anomalies):
            result_text += f"\n\n**Warning:** {len(anomalies) - deleted_count} anomalies could not be deleted."
        if refusals:
            result_text += "\n\n**Not deleted:**\n" + "\n".join(refusals[:_REFUSALS_LISTED])
            if len(refusals) > _REFUSALS_LISTED:
                result_text += f"\n... and {len(refusals) - _REFUSALS_LISTED} more"

        if deleted_count == 0 and anomalies:
            raise_refusal(result_text, error_code=ErrorCodes.API_ERROR)
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

    def _reject_unsupported_operator(self, operator: Any) -> None:
        """Refuse an operator the platform declares but no longer accepts on write.

        Mirrors AIAnomalyService.getOperator (BACK-2875), naming the alternative the
        platform's own error names instead of letting a generic enum error list the
        legal values without explaining the omission.
        """
        if is_rejected_operator(operator):
            raise ValidationError(
                message=rejected_operator_message(operator),
                field="operatorType",
                value=operator,
                expected=f"One of: {', '.join(ACCEPTED_OPERATORS)}",
            )

    def _check_update_operator(
        self, converted_updates: Dict[str, Any], merged_data: Dict[str, Any]
    ) -> None:
        """Apply the platform's write-time operator gates to an operator the caller moved.

        A stored operator the platform no longer accepts is refused by
        refuse_update_rule_breach, which names the stored value and the fix.
        """
        submitted = converted_updates.get("operatorType")
        if submitted is not None:
            self._reject_unsupported_operator(submitted)
            operator = str(submitted).upper()
            if operator not in ACCEPTED_OPERATORS:
                raise ValidationError(
                    message=f"Invalid operatorType value: {submitted}",
                    field="operatorType",
                    value=submitted,
                    expected=f"One of: {', '.join(ACCEPTED_OPERATORS)}",
                )
        else:
            stored = merged_data.get("operatorType")
            operator = str(stored).upper() if stored else ""

        if not operator or is_rejected_operator(operator):
            return
        if submitted is None and "alertType" not in converted_updates:
            return
        alert_type = str(merged_data.get("alertType") or "")
        allowed = accepted_operators_for(alert_type)
        if operator not in allowed:
            raise ValidationError(
                message=(
                    f"Operator '{operator}' is not accepted for "
                    f"{alert_type or 'this'} alerts"
                ),
                field="operatorType",
                value=operator,
                expected=f"One of: {', '.join(allowed)}",
            )

    def _validate_direct_api_format(self, anomaly_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and sanitize direct API format data."""
        validated_data: Dict[str, Any] = {}

        # CRITICAL FIX: Process convenience notification fields before validation
        processed_data = self._process_convenience_notification_fields(anomaly_data.copy())

        # The platform still declares EQUAL_TO and NOT_EQUAL_TO but refuses both on
        # create and update, so name the alternative it names rather than letting the
        # generic enum error list operators without explaining the omission.
        submitted_operator = processed_data.get("operatorType")
        if submitted_operator is not None:
            self._reject_unsupported_operator(submitted_operator)

        # Validate required API fields - CORRECTED: Only 3 supported alert types
        required_fields = {
            "alertType": ["THRESHOLD", "CUMULATIVE_USAGE", "RELATIVE_CHANGE"],
            # No client-side metric enum (BACK-3103). The hand-typed accept-list that
            # used to sit here refused QUALITY_RATE, a metric the platform publishes,
            # and would refuse the next metric the platform adds before anyone noticed.
            # The platform is the authority on the name; what the MCP validates is the
            # prerequisites a metric carries — see revenium_mcp_server.alert_metrics.
            "metricType": "non_empty_string",
            # Mirrors AIAnomalyService.ACCEPTED_OPERATORS. The previous list spelled
            # four of these without the platform's _TO suffix and added EQUAL /
            # NOT_EQUAL, which are not operatorType values at all: it refused the
            # real GREATER_THAN_OR_EQUAL_TO and let GREATER_THAN_OR_EQUAL through to
            # an HTTP 400 "No enum constant OperatorType.GREATER_THAN_OR_EQUAL".
            "operatorType": list(ACCEPTED_OPERATORS),
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
                        message="Invalid threshold value",
                        field=field,
                        value=value,
                        expected="Numeric value",
                    )
            elif valid_values == "non_empty_string":
                if not isinstance(value, str) or not value.strip():
                    raise ValidationError(
                        message=f"Invalid {field} value",
                        field=field,
                        value=value,
                        expected="Non-empty metric name, for example TOTAL_COST",
                    )
                validated_data[field] = value
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

        # Cross-field validation: operator must match alertType, the same narrowing
        # AIAnomalyService.acceptedOperatorsFor(alertType) applies after the
        # accepted-set check.
        relative_change_operators = set(CHANGE_OPERATORS)
        alert_type = validated_data.get("alertType")
        operator_type = validated_data.get("operatorType")

        if operator_type in relative_change_operators and alert_type != "RELATIVE_CHANGE":
            raise ValidationError(
                message=f"Operator '{operator_type}' is only valid for RELATIVE_CHANGE alerts",
                field="operatorType",
                value=operator_type,
                expected=(
                    f"{'/'.join(CHANGE_OPERATORS)} require alertType: RELATIVE_CHANGE"
                ),
            )
        if alert_type == "RELATIVE_CHANGE" and operator_type not in relative_change_operators:
            raise ValidationError(
                message="RELATIVE_CHANGE alerts require a relative operator",
                field="operatorType",
                value=operator_type,
                expected=f"One of: {', '.join(CHANGE_OPERATORS)}",
            )

        # Validate optional fields
        optional_fields = {
            "periodDuration": "platform_period",
            "isPercentage": "boolean",
            "enabled": "boolean",
            "notificationAddresses": "list",
            "slackConfigurations": "list",
            "triggerAfterPersistsDuration": "string",
            "filters": "list",
            # Both used to be dropped here rather than forwarded, so a caller that set
            # a coverage floor or a grouping got an alert without one and no way to
            # tell (BACK-3103). The prerequisite check below decides whether the pair
            # is coherent; these entries decide whether it reaches the platform at all.
            "minSampleCount": "passthrough",
            "groupBy": "passthrough",
            # Dropping it stored every alert as SDK, where an API_KEY or WORKSPACE row
            # is accepted and then cannot be evaluated (BACK-3942).
            "dataSource": "passthrough",
        }

        for field, field_type in optional_fields.items():
            if field in processed_data:
                value = processed_data[field]

                if field_type == "platform_period":
                    from .alert_periods import refuse_unaccepted_period  # noqa: PLC0415

                    refuse_platform_rule_breach(processed_data)
                    refuse_unaccepted_period(value)
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

                if field == "filters" and isinstance(value, list):
                    # Row shape is checked here as well as in
                    # _process_advanced_configuration: both write filters into the
                    # payload, and validate_filter_rows is idempotent.
                    value = validate_filter_rows(value)

                validated_data[field] = value

        # QUALITY_RATE carries prerequisites no other metric has, and minSampleCount
        # means something on QUALITY_RATE alone. AIAnomalyService.validateQualityRateRule
        # refuses a rule that breaks any of them; refusing it here names the whole rule
        # instead of one platform sentence, and names the prerequisite the platform
        # cannot check at all (the job type declaring quality_rate PER_JOB).
        self._reject_metric_rule_violation(validated_data)

        return validated_data

    def _reject_metric_rule_violation(self, payload: Dict[str, Any]) -> None:
        """Raise when ``payload`` breaks a metric prerequisite (see alert_metrics)."""
        violation = check_metric_rules(payload)
        if violation is None:
            return
        raise ValidationError(
            message=violation.message,
            field=violation.field,
            value=violation.value,
            expected=violation.expected,
            suggestion=violation.suggestion,
        )

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
