"""Advanced input validation and sanitization for Alert & Anomaly Management Tools.

This module provides comprehensive validation and sanitization functions
for ensuring data integrity and security across all alert and anomaly operations.
"""

import html
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

from .exceptions import InvalidInputError, ValidationError


class InputValidator:
    """Comprehensive input validation and sanitization utilities."""

    # Regex patterns for common validations
    UUID_PATTERN = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
    )
    EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    ALPHANUMERIC_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
    SAFE_STRING_PATTERN = re.compile(r"^[a-zA-Z0-9\s\-_.,!?()]+$")

    # Common string length limits
    MAX_NAME_LENGTH = 255
    MAX_DESCRIPTION_LENGTH = 2000
    MAX_ID_LENGTH = 100
    MAX_TAG_LENGTH = 50
    MAX_TAGS_COUNT = 20

    @staticmethod
    def sanitize_string(
        value: Any, max_length: Optional[int] = None, allow_html: bool = False
    ) -> str:
        """Sanitize string input by removing dangerous content and normalizing.

        Args:
            value: Input value to sanitize
            max_length: Maximum allowed length
            allow_html: Whether to allow HTML content

        Returns:
            Sanitized string

        Raises:
            InvalidInputError: If input is invalid
        """
        if value is None:
            return ""

        # Convert to string
        str_value = str(value).strip()

        # Remove null bytes and control characters
        str_value = "".join(char for char in str_value if ord(char) >= 32 or char in "\t\n\r")

        # Handle HTML content
        if not allow_html:
            # Escape HTML entities
            str_value = html.escape(str_value)
            # Remove any remaining HTML-like tags
            str_value = re.sub(r"<[^>]*>", "", str_value)

        # Normalize whitespace
        str_value = re.sub(r"\s+", " ", str_value).strip()

        # Check length
        if max_length and len(str_value) > max_length:
            raise InvalidInputError(
                parameter="string_input",
                value=str_value[:50] + "..." if len(str_value) > 50 else str_value,
                reason=f"String length {len(str_value)} exceeds maximum {max_length}",
            )

        return str_value

    @staticmethod
    def validate_anomaly_name(name: Any) -> str:
        """Validate and sanitize anomaly name.

        Args:
            name: Anomaly name to validate

        Returns:
            Validated and sanitized name

        Raises:
            ValidationError: If name is invalid
        """
        if not name:
            raise ValidationError(
                message="Anomaly name is required", field="name", expected="Non-empty string"
            )

        sanitized_name = InputValidator.sanitize_string(name, InputValidator.MAX_NAME_LENGTH)

        if not sanitized_name:
            raise ValidationError(
                message="Anomaly name cannot be empty after sanitization",
                field="name",
                value=name,
                expected="Valid string with content",
            )

        if len(sanitized_name) < 2:
            raise ValidationError(
                message="Anomaly name must be at least 2 characters long",
                field="name",
                value=sanitized_name,
                expected="String with at least 2 characters",
            )

        return sanitized_name

    @staticmethod
    def validate_description(description: Any) -> Optional[str]:
        """Validate and sanitize description text.

        Args:
            description: Description to validate

        Returns:
            Validated description or None if empty

        Raises:
            ValidationError: If description is invalid
        """
        if not description:
            return None

        sanitized_desc = InputValidator.sanitize_string(
            description, InputValidator.MAX_DESCRIPTION_LENGTH, allow_html=False
        )

        return sanitized_desc if sanitized_desc else None

    @staticmethod
    def validate_uuid(value: Any, field_name: str = "id") -> str:
        """Validate UUID format.

        Args:
            value: Value to validate as UUID
            field_name: Name of the field for error messages

        Returns:
            Validated UUID string

        Raises:
            ValidationError: If UUID is invalid
        """
        if not value:
            raise ValidationError(
                message=f"{field_name} is required", field=field_name, expected="Valid UUID format"
            )

        str_value = str(value).strip().lower()

        if not InputValidator.UUID_PATTERN.match(str_value):
            raise ValidationError(
                message=f"Invalid {field_name} format",
                field=field_name,
                value=str_value,
                expected="UUID format (e.g., 123e4567-e89b-12d3-a456-426614174000)",
            )

        return str_value

    @staticmethod
    def validate_email(email: Any) -> str:
        """Validate email address format.

        Args:
            email: Email to validate

        Returns:
            Validated email address

        Raises:
            ValidationError: If email is invalid
        """
        if not email:
            raise ValidationError(
                message="Email address is required", field="email", expected="Valid email format"
            )

        sanitized_email = InputValidator.sanitize_string(email, 320).lower()

        if not InputValidator.EMAIL_PATTERN.match(sanitized_email):
            raise ValidationError(
                message="Invalid email address format",
                field="email",
                value=sanitized_email,
                expected="Valid email format (e.g., user@example.com)",
            )

        return sanitized_email

    @staticmethod
    def validate_tags(tags: Any) -> List[str]:
        """Validate and sanitize tags list.

        Args:
            tags: Tags to validate

        Returns:
            List of validated tags

        Raises:
            ValidationError: If tags are invalid
        """
        if not tags:
            return []

        if not isinstance(tags, (list, tuple)):
            raise ValidationError(
                message="Tags must be a list",
                field="tags",
                value=type(tags).__name__,
                expected="List of strings",
            )

        if len(tags) > InputValidator.MAX_TAGS_COUNT:
            raise ValidationError(
                message=f"Too many tags (maximum {InputValidator.MAX_TAGS_COUNT})",
                field="tags",
                value=len(tags),
                expected=f"List with at most {InputValidator.MAX_TAGS_COUNT} items",
            )

        validated_tags = []
        for i, tag in enumerate(tags):
            if not tag:
                continue

            sanitized_tag = InputValidator.sanitize_string(tag, InputValidator.MAX_TAG_LENGTH)

            if not sanitized_tag:
                continue

            if not InputValidator.ALPHANUMERIC_PATTERN.match(sanitized_tag.replace(" ", "_")):
                raise ValidationError(
                    message=f"Invalid tag format at position {i}",
                    field="tags",
                    value=sanitized_tag,
                    expected="Alphanumeric characters, spaces, hyphens, and underscores only",
                )

            if sanitized_tag not in validated_tags:  # Remove duplicates
                validated_tags.append(sanitized_tag)

        return validated_tags

    @staticmethod
    def validate_numeric_range(
        value: Any,
        field_name: str,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        allow_zero: bool = True,
    ) -> Union[int, float]:
        """Validate numeric value within specified range.

        Args:
            value: Value to validate
            field_name: Name of the field
            min_value: Minimum allowed value
            max_value: Maximum allowed value
            allow_zero: Whether zero is allowed

        Returns:
            Validated numeric value

        Raises:
            ValidationError: If value is invalid
        """
        if value is None:
            raise ValidationError(
                message=f"{field_name} is required", field=field_name, expected="Numeric value"
            )

        try:
            if isinstance(value, str):
                # Try to parse as int first, then float
                if "." in value:
                    numeric_value = float(value)
                else:
                    numeric_value = int(value)
            else:
                numeric_value = float(value)
        except (ValueError, TypeError):
            raise ValidationError(
                message=f"Invalid {field_name} format",
                field=field_name,
                value=str(value),
                expected="Numeric value",
            )

        if not allow_zero and numeric_value == 0:
            raise ValidationError(
                message=f"{field_name} cannot be zero",
                field=field_name,
                value=numeric_value,
                expected="Non-zero numeric value",
            )

        if min_value is not None and numeric_value < min_value:
            raise ValidationError(
                message=f"{field_name} is below minimum value",
                field=field_name,
                value=numeric_value,
                expected=f"Value >= {min_value}",
            )

        if max_value is not None and numeric_value > max_value:
            raise ValidationError(
                message=f"{field_name} exceeds maximum value",
                field=field_name,
                value=numeric_value,
                expected=f"Value <= {max_value}",
            )

        return numeric_value

    @staticmethod
    def validate_datetime_string(value: Any, field_name: str = "datetime") -> datetime:
        """Validate and parse datetime string.

        Args:
            value: Datetime string to validate
            field_name: Name of the field

        Returns:
            Parsed datetime object

        Raises:
            ValidationError: If datetime is invalid
        """
        if not value:
            raise ValidationError(
                message=f"{field_name} is required",
                field=field_name,
                expected="ISO format datetime string",
            )

        str_value = str(value).strip()

        # Common datetime formats to try
        formats = [
            "%Y-%m-%dT%H:%M:%S.%fZ",  # ISO with microseconds and Z
            "%Y-%m-%dT%H:%M:%SZ",  # ISO with Z
            "%Y-%m-%dT%H:%M:%S.%f",  # ISO with microseconds
            "%Y-%m-%dT%H:%M:%S",  # ISO basic
            "%Y-%m-%d %H:%M:%S",  # Space separated
            "%Y-%m-%d",  # Date only
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(str_value, fmt)
                # Ensure timezone awareness
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue

        raise ValidationError(
            message=f"Invalid {field_name} format",
            field=field_name,
            value=str_value,
            expected="ISO format datetime (e.g., 2024-01-01T12:00:00Z)",
        )

    @staticmethod
    def validate_url(url: Any, field_name: str = "url") -> str:
        """Validate URL format.

        Args:
            url: URL to validate
            field_name: Name of the field

        Returns:
            Validated URL

        Raises:
            ValidationError: If URL is invalid
        """
        if not url:
            raise ValidationError(
                message=f"{field_name} is required", field=field_name, expected="Valid URL"
            )

        str_url = str(url).strip()

        try:
            parsed = urlparse(str_url)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError("Invalid URL structure")

            if parsed.scheme not in ["http", "https"]:
                raise ValueError("Only HTTP and HTTPS URLs are allowed")

        except Exception:
            raise ValidationError(
                message=f"Invalid {field_name} format",
                field=field_name,
                value=str_url,
                expected="Valid HTTP/HTTPS URL (e.g., https://example.com)",
            )

        return str_url

    @staticmethod
    def validate_detection_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
        """Validate detection rule structure and content.

        Args:
            rule: Detection rule dictionary to validate

        Returns:
            Validated detection rule

        Raises:
            ValidationError: If rule is invalid
        """
        if not isinstance(rule, dict):
            raise ValidationError(
                message="Detection rule must be a dictionary",
                field="detection_rule",
                value=type(rule).__name__,
                expected="Dictionary with rule_type, metric, operator, and value",
            )

        # Required fields
        required_fields = ["rule_type", "metric", "operator", "value"]
        for field in required_fields:
            if field not in rule:
                raise ValidationError(
                    message=f"Missing required field in detection rule: {field}",
                    field="detection_rule",
                    expected=f"Dictionary with {', '.join(required_fields)}",
                )

        validated_rule = {}

        # Validate rule_type (special handling - preserve case for API compatibility)
        rule_type = str(rule["rule_type"]).strip()  # Simple string conversion without HTML escaping

        # Normalize to uppercase for API compatibility
        rule_type_upper = rule_type.upper()
        if rule_type_upper not in [
            "THRESHOLD",
            "STATISTICAL",
            "PATTERN",
            "ANOMALY",
            "TREND",
            "CUMULATIVE_USAGE",
        ]:
            raise ValidationError(
                message="Invalid detection rule type",
                field="rule_type",
                value=rule_type,
                expected="One of: THRESHOLD, STATISTICAL, PATTERN, ANOMALY, TREND, CUMULATIVE_USAGE",
            )
        validated_rule["rule_type"] = rule_type_upper

        # Validate metric
        metric = InputValidator.sanitize_string(rule["metric"], 100)
        if not metric:
            raise ValidationError(
                message="Metric name cannot be empty", field="metric", expected="Non-empty string"
            )
        validated_rule["metric"] = metric

        # Validate operator (special handling - no HTML escaping for operators)
        valid_operators = [">", "<", ">=", "<=", "==", "!=", "contains", "not_contains"]
        operator = str(rule["operator"]).strip()  # Simple string conversion without HTML escaping
        if operator not in valid_operators:
            raise ValidationError(
                message="Invalid operator",
                field="operator",
                value=operator,
                expected=f"One of: {', '.join(valid_operators)}",
            )
        validated_rule["operator"] = operator

        # Validate value (can be numeric or string depending on operator)
        if operator in [">", "<", ">=", "<=", "==", "!="]:
            # Numeric operators
            validated_rule["value"] = InputValidator.validate_numeric_range(
                rule["value"], "value", allow_zero=True
            )
        else:
            # String operators
            validated_rule["value"] = InputValidator.sanitize_string(rule["value"], 500)

        # Optional fields
        if "time_window" in rule:
            time_window = InputValidator.sanitize_string(rule["time_window"], 20)
            if time_window:
                # For CUMULATIVE_USAGE alerts, allow calendar periods
                if rule_type_upper == "CUMULATIVE_USAGE":
                    calendar_periods = ["daily", "weekly", "monthly", "quarterly"]
                    if time_window.lower() not in calendar_periods:
                        raise ValidationError(
                            message="Invalid time window for CUMULATIVE_USAGE alert",
                            field="time_window",
                            value=time_window,
                            expected="One of: daily, weekly, monthly, quarterly",
                        )
                else:
                    # For other alert types, use time-based format
                    if not re.match(r"^\d+[smhd]$", time_window):
                        raise ValidationError(
                            message="Invalid time window format",
                            field="time_window",
                            value=time_window,
                            expected="Format like '5m', '1h', '2d' (number + s/m/h/d)",
                        )
            validated_rule["time_window"] = time_window

        if "aggregation" in rule:
            valid_aggregations = ["avg", "sum", "max", "min", "count", "median"]
            aggregation = InputValidator.sanitize_string(rule["aggregation"], 20).lower()
            if aggregation and aggregation not in valid_aggregations:
                raise ValidationError(
                    message="Invalid aggregation method",
                    field="aggregation",
                    value=aggregation,
                    expected=f"One of: {', '.join(valid_aggregations)}",
                )
            validated_rule["aggregation"] = aggregation

        if "conditions" in rule and rule["conditions"]:
            if not isinstance(rule["conditions"], list):
                raise ValidationError(
                    message="Conditions must be a list",
                    field="conditions",
                    expected="List of condition strings",
                )
            validated_conditions = []
            for condition in rule["conditions"]:
                sanitized_condition = InputValidator.sanitize_string(condition, 200)
                if sanitized_condition:
                    validated_conditions.append(sanitized_condition)
            validated_rule["conditions"] = validated_conditions

        return validated_rule

    @staticmethod
    def validate_thresholds(thresholds: Dict[str, Any]) -> Dict[str, Union[int, float]]:
        """Validate threshold values dictionary.

        Args:
            thresholds: Dictionary of threshold values

        Returns:
            Validated thresholds dictionary

        Raises:
            ValidationError: If thresholds are invalid
        """
        if not isinstance(thresholds, dict):
            raise ValidationError(
                message="Thresholds must be a dictionary",
                field="thresholds",
                value=type(thresholds).__name__,
                expected="Dictionary with metric names as keys and numeric values",
            )

        if not thresholds:
            raise ValidationError(
                message="At least one threshold must be defined",
                field="thresholds",
                expected="Dictionary with at least one threshold",
            )

        validated_thresholds = {}

        for metric, value in thresholds.items():
            # Validate metric name
            sanitized_metric = InputValidator.sanitize_string(metric, 100)
            if not sanitized_metric:
                raise ValidationError(
                    message="Threshold metric name cannot be empty",
                    field="thresholds",
                    expected="Non-empty metric names",
                )

            # Validate threshold value
            validated_value = InputValidator.validate_numeric_range(
                value, f"threshold[{sanitized_metric}]", allow_zero=True
            )

            validated_thresholds[sanitized_metric] = validated_value

        return validated_thresholds

    @staticmethod
    def _convert_filters_to_api_format(filters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert user-friendly filters to API format.

        Args:
            filters: List of user-friendly filter dictionaries

        Returns:
            List of API-compatible filter dictionaries

        Expected user format:
            {"field": "organization", "operator": "contains", "value": "acme"}

        API format:
            {"dimension": "ORGANIZATION", "operator": "CONTAINS", "value": "acme"}
        """
        if not filters:
            return []

        api_filters = []

        # Mapping for filter dimensions
        dimension_mapping = {
            "organization": "ORGANIZATION",
            "credential": "CREDENTIAL",
            "product": "PRODUCT",
            "model": "MODEL",
            "provider": "PROVIDER",
            "agent": "AGENT",
            "subscriber": "SUBSCRIBER",
        }

        # Mapping for filter operators (user input -> API format)
        filter_operator_mapping = {
            "contains": "CONTAINS",
            "starts_with": "STARTS_WITH",
            "ends_with": "ENDS_WITH",
            "equals": "IS",
            "is": "IS",
            "not_equals": "IS_NOT",
            "is_not": "IS_NOT",
        }

        for filter_data in filters:
            if not isinstance(filter_data, dict):
                continue

            field = filter_data.get("field", "").lower()
            operator = filter_data.get("operator", "").lower()
            value = filter_data.get("value", "")

            # Convert field to dimension
            dimension = dimension_mapping.get(field, field.upper())

            # Convert operator
            api_operator = filter_operator_mapping.get(operator, operator.upper())

            api_filter = {"dimension": dimension, "operator": api_operator, "value": str(value)}

            api_filters.append(api_filter)

        return api_filters

    @staticmethod
    def convert_to_api_format(user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert user-friendly anomaly data to Revenium API format.

        Args:
            user_data: User-friendly anomaly data

        Returns:
            API-compatible anomaly data

        Raises:
            ValidationError: If conversion fails
        """
        # Mapping from user-friendly to API format
        operator_mapping = {
            ">": "GREATER_THAN",
            "<": "LESS_THAN",
            ">=": "GREATER_THAN_OR_EQUAL_TO",
            "<=": "LESS_THAN_OR_EQUAL_TO",
        }

        metric_mapping = {
            # Complete list of valid metrics from MetricType enum
            "total_cost": "TOTAL_COST",
            "cost_per_transaction": "COST_PER_TRANSACTION",
            "tokens_per_second": "TOKENS_PER_SECOND",
            "requests_per_second": "REQUESTS_PER_SECOND",
            "token_count": "TOKEN_COUNT",
            "input_token_count": "INPUT_TOKEN_COUNT",
            "output_token_count": "OUTPUT_TOKEN_COUNT",
            "cached_token_count": "CACHED_TOKEN_COUNT",
            "error_rate": "ERROR_RATE",
            "error_count": "ERROR_COUNT",
        }

        period_mapping = {
            # Time-based periods (for THRESHOLD alerts)
            "1m": "ONE_MINUTE",
            "5m": "FIVE_MINUTES",
            "10m": "TEN_MINUTES",
            "15m": "FIFTEEN_MINUTES",
            "30m": "THIRTY_MINUTES",
            "1h": "ONE_HOUR",
            "2h": "TWO_HOURS",
            "4h": "FOUR_HOURS",
            "8h": "EIGHT_HOURS",
            "12h": "TWELVE_HOURS",
            "1d": "ONE_DAY",
            # Calendar periods (for CUMULATIVE_USAGE alerts)
            "daily": "DAILY",
            "weekly": "WEEKLY",
            "monthly": "MONTHLY",
            "quarterly": "QUARTERLY",
        }

        # Extract detection rule (assume first rule for now)
        if not user_data.get("detection_rules"):
            raise ValidationError(
                message="Detection rules are required for convert_to_api_format",
                field="detection_rules",
                expected="List with at least one detection rule",
                suggestion="This method is for converting detection_rules format to API format. For direct API format, use the data as-is.",
            )

        rule = user_data["detection_rules"][0]
        alert_type = rule.get("rule_type", "THRESHOLD")

        # Convert to API format - ensure all required fields are present
        api_data = {
            "name": user_data.get("name", ""),
            "label": user_data.get("name", ""),  # API requires both name and label
            "enabled": user_data.get("enabled", True),
            "alertType": rule.get("rule_type", "THRESHOLD").upper(),
            "threshold": rule.get("value", 0),
            "notificationAddresses": (
                user_data.get("notificationAddresses")
                or user_data.get("notification_addresses")
                or []
            ),
            "slackConfigurations": user_data.get("slack_configurations", []),
            "webhookConfigurations": user_data.get(
                "webhook_configurations", []
            ),  # Correct field name
            "filters": InputValidator._convert_filters_to_api_format(user_data.get("filters", [])),
            "isPercentage": user_data.get("is_percentage", False),
            "triggerAfterPersistsDuration": user_data.get("trigger_after_persists_duration", ""),
        }

        # Add optional fields only if present
        if "description" in user_data:
            api_data["description"] = user_data["description"]
        if "group_by" in user_data:
            api_data["groupBy"] = user_data["group_by"]

        # Convert operator - API expects "operatorType" field, not "operator"
        operator = rule.get("operator", ">")
        if operator in operator_mapping:
            api_data["operatorType"] = operator_mapping[operator]
        else:
            raise ValidationError(
                message="Invalid operator",
                field="operator",
                value=operator,
                expected=f"One of: {', '.join(operator_mapping.keys())}",
            )

        # Convert metric - strict validation, no guessing
        metric = rule.get("metric", "").lower()
        if metric in metric_mapping:
            api_data["metricType"] = metric_mapping[metric]
        else:
            # Provide helpful suggestions based on the invalid metric
            suggestions = []
            if "cost" in metric:
                suggestions = ["total_cost", "cost_per_transaction"]
            elif "token" in metric:
                suggestions = ["token_count", "input_token_count", "output_token_count"]
            elif "error" in metric:
                suggestions = ["error_rate", "error_count"]
            elif "time" in metric or "speed" in metric:
                suggestions = ["tokens_per_second", "requests_per_second"]
            else:
                suggestions = ["total_cost", "token_count", "error_rate", "tokens_per_second"]

            raise ValidationError(
                message=f"Invalid metric type: '{metric}'",
                field="metric",
                value=metric,
                expected=f"Valid metrics: {', '.join(metric_mapping.keys())}",
                suggestion=f"Try: {', '.join(suggestions[:3])}",
                example={
                    "detection_rules": [
                        {
                            "rule_type": "THRESHOLD",
                            "metric": suggestions[0] if suggestions else "total_cost",
                            "operator": ">=",
                            "value": 100,
                        }
                    ]
                },
            )

        # Convert period duration - handle CUMULATIVE_USAGE differently
        # Use appropriate defaults based on alert type
        if alert_type == "CUMULATIVE_USAGE":
            period = rule.get("time_window", "daily")  # Default to daily for CUMULATIVE_USAGE
        else:
            period = rule.get("time_window", "5m")  # Default to 5m for THRESHOLD alerts

        # Debug logging for period conversion
        logger.debug(
            f"Converting period for {alert_type}: rule.time_window='{period}', user_data keys: {list(user_data.keys())}"
        )

        if alert_type == "CUMULATIVE_USAGE":
            # For CUMULATIVE_USAGE, if time_window is missing, check user_data for period
            if "time_window" not in rule:
                logger.info(
                    f"CUMULATIVE_USAGE alert missing time_window, checking user_data for period"
                )
                period = (
                    user_data.get("period")
                    or user_data.get("trackingPeriod")
                    or user_data.get("periodDuration")
                    or "daily"  # Final fallback to daily (valid for CUMULATIVE_USAGE)
                )
                logger.debug(
                    f"CUMULATIVE_USAGE: Using period from user_data or fallback: '{period}'"
                )
            # For CUMULATIVE_USAGE, also check for period in user_data directly
            if period == "5m":  # Default value, check if user specified period elsewhere
                period = (
                    user_data.get("period")
                    or user_data.get("trackingPeriod")
                    or user_data.get("periodDuration")
                    or "monthly"
                )
                logger.debug(f"CUMULATIVE_USAGE: Using period from user_data: '{period}'")

            # For CUMULATIVE_USAGE, use calendar periods directly
            # Handle both lowercase and uppercase period values
            period_lower = period.lower() if isinstance(period, str) else str(period).lower()
            cumulative_period_mapping = {
                "daily": "DAILY",
                "weekly": "WEEKLY",
                "monthly": "MONTHLY",
                "quarterly": "QUARTERLY",
            }

            if period_lower in cumulative_period_mapping:
                api_data["periodDuration"] = cumulative_period_mapping[period_lower]
                logger.debug(
                    f"CUMULATIVE_USAGE: Mapped '{period}' to '{cumulative_period_mapping[period_lower]}'"
                )
            else:
                # Default to DAILY for CUMULATIVE_USAGE if period not recognized (changed from MONTHLY)
                api_data["periodDuration"] = "DAILY"
                logger.warning(
                    f"CUMULATIVE_USAGE: Unrecognized period '{period}', defaulting to DAILY"
                )
        else:
            # For THRESHOLD alerts, use time-based periods
            if period in period_mapping:
                api_data["periodDuration"] = period_mapping[period]
            else:
                api_data["periodDuration"] = "FIVE_MINUTES"  # Default for THRESHOLD

        return api_data


class AdvancedConfigurationBuilder:
    """Builder class for creating advanced alert configurations."""

    @staticmethod
    def create_filter(
        field: str, operator: str, value: Union[str, int, float, bool]
    ) -> Dict[str, Any]:
        """Create a filter configuration.

        Args:
            field: Field name to filter on
            operator: Filter operator
            value: Filter value

        Returns:
            Filter configuration dictionary
        """
        from .models import AlertFilter

        filter_obj = AlertFilter(field=field, operator=operator, value=value)
        return {
            "field": filter_obj.field,
            "operator": filter_obj.operator,
            "value": filter_obj.value,
        }

    @staticmethod
    def create_slack_config(
        webhook_url: str,
        channel: Optional[str] = None,
        username: Optional[str] = None,
        icon_emoji: Optional[str] = None,
    ) -> str:
        """Create a Slack configuration.

        Args:
            webhook_url: Slack webhook URL
            channel: Slack channel name
            username: Bot username
            icon_emoji: Bot icon emoji

        Returns:
            Slack webhook URL (API expects just the URL)
        """
        from .models import SlackConfiguration

        slack_config = SlackConfiguration(
            webhook_url=webhook_url, channel=channel, username=username, icon_emoji=icon_emoji
        )
        return slack_config.webhook_url

    @staticmethod
    def create_webhook_config(
        url: str,
        method: str = "POST",
        headers: Optional[Dict[str, str]] = None,
        auth_token: Optional[str] = None,
    ) -> str:
        """Create a webhook configuration.

        Args:
            url: Webhook URL
            method: HTTP method
            headers: Custom headers
            auth_token: Authentication token

        Returns:
            Webhook URL (API expects just the URL)
        """
        from .models import WebhookConfiguration

        webhook_config = WebhookConfiguration(
            url=url, method=method, headers=headers or {}, auth_token=auth_token
        )
        return webhook_config.url

    @staticmethod
    def build_advanced_config(
        filters: Optional[List[Dict[str, Any]]] = None,
        group_by: Optional[str] = None,
        slack_configs: Optional[List[str]] = None,
        webhook_configs: Optional[List[str]] = None,
        trigger_duration: Optional[str] = None,
        is_percentage: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Build advanced configuration for API request.

        Args:
            filters: List of filter configurations
            group_by: Grouping dimension
            slack_configs: List of Slack webhook URLs
            webhook_configs: List of webhook URLs
            trigger_duration: Trigger persistence duration
            is_percentage: Whether threshold is a percentage

        Returns:
            Advanced configuration dictionary for API
        """
        config = {}

        if filters:
            config["filters"] = filters
        else:
            config["filters"] = []

        if group_by:
            config["groupBy"] = group_by

        if slack_configs:
            config["slackConfigurations"] = slack_configs
        else:
            config["slackConfigurations"] = []

        if webhook_configs:
            config["webhook_enabled"] = webhook_configs
        else:
            config["webhook_enabled"] = []

        if trigger_duration:
            config["triggerAfterPersistsDuration"] = trigger_duration

        if is_percentage is not None:
            config["isPercentage"] = is_percentage

        return config


def validate_input(validation_rules: Dict[str, Any]):
    """Decorate function for input validation using specified rules.

    Args:
        validation_rules: Dictionary mapping parameter names to validation functions

    Returns:
        Decorator function
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Extract arguments dictionary (usually the last argument)
            if args and isinstance(args[-1], dict):
                arguments = args[-1]

                # Apply validation rules
                for param_name, validator in validation_rules.items():
                    if param_name in arguments:
                        try:
                            if callable(validator):
                                arguments[param_name] = validator(arguments[param_name])
                            elif isinstance(validator, dict):
                                # Complex validation with options
                                validator_func = validator.get("func")
                                validator_args = validator.get("args", [])
                                validator_kwargs = validator.get("kwargs", {})

                                if validator_func:
                                    arguments[param_name] = validator_func(
                                        arguments[param_name], *validator_args, **validator_kwargs
                                    )
                        except (ValidationError, InvalidInputError):
                            # Re-raise validation errors as-is
                            raise
                        except Exception as e:
                            # Convert other exceptions to validation errors
                            raise ValidationError(
                                message=f"Validation failed for {param_name}: {str(e)}",
                                field=param_name,
                                value=str(arguments[param_name]),
                            )

            return await func(*args, **kwargs)

        return wrapper

    return decorator


# Common validation rule sets for reuse
ANOMALY_VALIDATION_RULES = {
    "name": InputValidator.validate_anomaly_name,
    "description": InputValidator.validate_description,
    "tags": InputValidator.validate_tags,
    "detection_rules": lambda rules: (
        [InputValidator.validate_detection_rule(rule) for rule in rules] if rules else []
    ),
    "thresholds": InputValidator.validate_thresholds,
}

ALERT_VALIDATION_RULES = {
    "alert_id": lambda x: InputValidator.validate_uuid(x, "alert_id"),
    "anomaly_id": lambda x: InputValidator.validate_uuid(x, "anomaly_id"),
}

PAGINATION_VALIDATION_RULES = {
    "page": lambda x: InputValidator.validate_numeric_range(
        x, "page", min_value=0, allow_zero=True
    ),
    "size": lambda x: InputValidator.validate_numeric_range(
        x, "size", min_value=1, max_value=1000, allow_zero=False
    ),
}
