"""Alert and anomaly data models for Revenium MCP server.

This module contains all data models related to alerts, anomalies,
and monitoring configurations in the Revenium platform.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import Field, field_validator

from .base import (
    BaseReveniumModel,
    IdentifierMixin,
    MetadataMixin,
    TimestampMixin,
    validate_non_empty_string,
)

# Alert and anomaly enumerations


class AnomalyStatus(str, Enum):
    """AI Anomaly status enumeration."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"
    DRAFT = "draft"


class AlertSeverity(str, Enum):
    """Alert severity enumeration."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertStatus(str, Enum):
    """Alert status enumeration."""

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    CLOSED = "closed"
    FALSE_POSITIVE = "false_positive"


class AlertType(str, Enum):
    """Alert type enumeration for Revenium API."""

    THRESHOLD = "THRESHOLD"
    CUMULATIVE_USAGE = "CUMULATIVE_USAGE"
    RELATIVE_CHANGE = "RELATIVE_CHANGE"


class MetricType(str, Enum):
    """Metric type enumeration for Revenium API - User validated metrics only.

    These metrics have been validated by users and confirmed to work with the Revenium API.
    This enum serves as the single source of truth for supported alert metrics.
    """

    TOTAL_COST = "TOTAL_COST"
    COST_PER_TRANSACTION = "COST_PER_TRANSACTION"
    TOKEN_COUNT = "TOKEN_COUNT"
    INPUT_TOKEN_COUNT = "INPUT_TOKEN_COUNT"
    OUTPUT_TOKEN_COUNT = "OUTPUT_TOKEN_COUNT"
    TOKENS_PER_MINUTE = "TOKENS_PER_MINUTE"
    REQUESTS_PER_MINUTE = "REQUESTS_PER_MINUTE"
    ERROR_RATE = "ERROR_RATE"
    ERROR_COUNT = "ERROR_COUNT"


class OperatorType(str, Enum):
    """Operator type enumeration for Revenium API."""

    GREATER_THAN = "GREATER_THAN"
    LESS_THAN = "LESS_THAN"
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"
    LESS_THAN_OR_EQUAL = "LESS_THAN_OR_EQUAL"
    EQUAL = "EQUAL"
    NOT_EQUAL = "NOT_EQUAL"
    CONTAINS = "CONTAINS"
    NOT_CONTAINS = "NOT_CONTAINS"


class PeriodDuration(str, Enum):
    """Period duration enumeration for Revenium API."""

    ONE_MINUTE = "ONE_MINUTE"
    FIVE_MINUTES = "FIVE_MINUTES"
    FIFTEEN_MINUTES = "FIFTEEN_MINUTES"
    THIRTY_MINUTES = "THIRTY_MINUTES"
    ONE_HOUR = "ONE_HOUR"
    TWELVE_HOURS = "TWELVE_HOURS"
    TWENTY_FOUR_HOURS = "TWENTY_FOUR_HOURS"
    SEVEN_DAYS = "SEVEN_DAYS"
    THIRTY_DAYS = "THIRTY_DAYS"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class GroupByDimension(str, Enum):
    """Group by dimension enumeration for Revenium API."""

    ORGANIZATION = "ORGANIZATION"
    CREDENTIAL = "CREDENTIAL"
    PRODUCT = "PRODUCT"
    MODEL = "MODEL"
    PROVIDER = "PROVIDER"
    AGENT = "AGENT"
    SUBSCRIBER = "SUBSCRIBER"


class TriggerDuration(str, Enum):
    """Trigger persistence duration enumeration for Revenium API."""

    ONE_MINUTE = "ONE_MINUTE"
    FIVE_MINUTES = "FIVE_MINUTES"
    FIFTEEN_MINUTES = "FIFTEEN_MINUTES"
    THIRTY_MINUTES = "THIRTY_MINUTES"
    ONE_HOUR = "ONE_HOUR"
    TWELVE_HOURS = "TWELVE_HOURS"
    TWENTY_FOUR_HOURS = "TWENTY_FOUR_HOURS"
    SEVEN_DAYS = "SEVEN_DAYS"
    THIRTY_DAYS = "THIRTY_DAYS"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class FilterOperator(str, Enum):
    """Filter operator enumeration."""

    EQUALS = "eq"
    NOT_EQUALS = "ne"
    GREATER_THAN = "gt"
    GREATER_THAN_OR_EQUAL = "gte"
    LESS_THAN = "lt"
    LESS_THAN_OR_EQUAL = "lte"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    IN = "in"
    NOT_IN = "not_in"


# Alert configuration models


class AlertFilter(BaseReveniumModel):
    """Model for alert filter configuration."""

    field: str = Field(..., description="Field name to filter on")
    operator: str = Field(..., description="Filter operator (equals, contains, etc.)")
    value: Union[str, int, float, bool] = Field(..., description="Filter value")

    @field_validator("field")
    @classmethod
    def validate_field(cls, v):
        """Validate field name is not empty."""
        return validate_non_empty_string(v, "field")

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, v):
        """Validate operator is not empty."""
        return validate_non_empty_string(v, "operator")


class SlackConfiguration(BaseReveniumModel):
    """Model for Slack notification configuration."""

    webhook_url: str = Field(..., description="Slack webhook URL")
    channel: Optional[str] = Field(None, description="Slack channel")
    username: Optional[str] = Field(None, description="Bot username")
    icon_emoji: Optional[str] = Field(None, description="Bot icon emoji")
    message_template: Optional[str] = Field(None, description="Custom message template")

    @field_validator("webhook_url")
    @classmethod
    def validate_webhook_url(cls, v):
        """Validate webhook URL format."""
        if not v.startswith("https://hooks.slack.com/"):
            raise ValueError("Invalid Slack webhook URL format")
        return v


class WebhookConfiguration(BaseReveniumModel):
    """Model for webhook notification configuration."""

    url: str = Field(..., description="Webhook URL")
    method: str = Field("POST", description="HTTP method")
    headers: Optional[Dict[str, str]] = Field(None, description="HTTP headers")
    payload_template: Optional[str] = Field(None, description="Custom payload template")
    timeout: int = Field(30, description="Request timeout in seconds")
    retry_count: int = Field(3, description="Number of retries")

    @field_validator("method")
    @classmethod
    def validate_method(cls, v):
        """Validate HTTP method."""
        allowed_methods = ["GET", "POST", "PUT", "PATCH"]
        if v.upper() not in allowed_methods:
            raise ValueError(f"Invalid HTTP method. Allowed: {', '.join(allowed_methods)}")
        return v.upper()

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, v):
        """Validate timeout is positive."""
        if v <= 0:
            raise ValueError("Timeout must be positive")
        return v

    @field_validator("retry_count")
    @classmethod
    def validate_retry_count(cls, v):
        """Validate retry count is non-negative."""
        if v < 0:
            raise ValueError("Retry count must be non-negative")
        return v


class AdvancedAlertConfiguration(BaseReveniumModel):
    """Model for advanced alert configuration options."""

    filters: List[AlertFilter] = Field(default_factory=list, description="Alert filters")
    group_by: Optional[GroupByDimension] = Field(None, description="Grouping dimension")
    slack_configs: List[SlackConfiguration] = Field(
        default_factory=list, description="Slack configurations"
    )
    webhook_configs: List[WebhookConfiguration] = Field(
        default_factory=list, description="Webhook configurations"
    )
    notification_frequency: Optional[str] = Field(None, description="Notification frequency")
    escalation_rules: Optional[Dict[str, Any]] = Field(None, description="Escalation rules")
    auto_resolve: bool = Field(False, description="Auto-resolve when condition clears")
    silence_duration: Optional[int] = Field(None, description="Silence duration in minutes")


# Detection rule models


class DetectionRule(BaseReveniumModel):
    """Model for anomaly detection rules."""

    rule_type: str = Field(..., description="Type of detection rule")
    metric: str = Field(..., description="Metric to monitor")
    operator: str = Field(..., description="Comparison operator")
    value: Union[int, float] = Field(..., description="Threshold value")
    time_window: Optional[str] = Field(None, description="Time window for evaluation")
    filters: Optional[List[AlertFilter]] = Field(None, description="Additional filters")
    group_by: Optional[str] = Field(None, description="Grouping dimension")
    is_percentage: Optional[bool] = Field(None, description="Whether value is a percentage")

    @field_validator("rule_type")
    @classmethod
    def validate_rule_type(cls, v):
        """Validate rule type is not empty."""
        return validate_non_empty_string(v, "rule_type")

    @field_validator("metric")
    @classmethod
    def validate_metric(cls, v):
        """Validate metric is not empty."""
        return validate_non_empty_string(v, "metric")

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, v):
        """Validate operator is not empty."""
        return validate_non_empty_string(v, "operator")


class ThresholdViolation(BaseReveniumModel):
    """Model for threshold violation details."""

    metric_name: str = Field(..., description="Name of the violated metric")
    threshold_value: Union[int, float] = Field(..., description="Threshold that was violated")
    actual_value: Union[int, float] = Field(
        ..., description="Actual value that triggered violation"
    )
    operator: str = Field(..., description="Comparison operator used")
    violation_time: datetime = Field(..., description="When the violation occurred")
    duration: Optional[str] = Field(None, description="How long the violation lasted")

    @field_validator("metric_name")
    @classmethod
    def validate_metric_name(cls, v):
        """Validate metric name is not empty."""
        return validate_non_empty_string(v, "metric_name")

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, v):
        """Validate operator is not empty."""
        return validate_non_empty_string(v, "operator")


# Main anomaly and alert models


class AIAnomalyRequest(BaseReveniumModel):
    """AI Anomaly request model for creating anomalies via Revenium API."""

    name: str = Field(..., min_length=1, max_length=255, description="Anomaly name")
    description: Optional[str] = Field(None, max_length=1000, description="Anomaly description")
    alert_type: str = Field(..., description="Type of alert (THRESHOLD, CUMULATIVE_USAGE, etc.)")
    enabled: bool = Field(True, description="Whether the anomaly is enabled")
    detection_rules: List[DetectionRule] = Field(..., description="Detection rules")
    notification_addresses: Optional[List[str]] = Field(
        None, description="Email addresses for notifications"
    )
    filters: Optional[List[AlertFilter]] = Field(None, description="Additional filters")
    advanced_config: Optional[AdvancedAlertConfiguration] = Field(
        None, description="Advanced configuration"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        """Validate name is not empty."""
        return validate_non_empty_string(v, "name")

    @field_validator("alert_type")
    @classmethod
    def validate_alert_type(cls, v):
        """Validate alert type is not empty."""
        return validate_non_empty_string(v, "alert_type")

    @field_validator("detection_rules")
    @classmethod
    def validate_detection_rules(cls, v):
        """Validate detection rules list."""
        if not isinstance(v, list) or len(v) == 0:
            raise ValueError("At least one detection rule is required")
        return v

    @field_validator("notification_addresses")
    @classmethod
    def validate_notification_addresses(cls, v):
        """Validate email addresses if provided."""
        if v:
            import re

            email_pattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
            for email in v:
                if not email_pattern.match(email):
                    raise ValueError(f"Invalid email address: {email}")
        return v

    @field_validator("filters")
    @classmethod
    def validate_filters(cls, v):
        """Validate filters list."""
        if v is not None and not isinstance(v, list):
            raise ValueError("Filters must be a list")
        return v


class AIAnomaly(BaseReveniumModel, TimestampMixin, IdentifierMixin, MetadataMixin):
    """AI Anomaly model representing the full anomaly response from Revenium API."""

    # Request fields
    name: str = Field(..., description="Anomaly name")
    description: Optional[str] = Field(None, description="Anomaly description")
    alert_type: str = Field(..., description="Type of alert")
    enabled: bool = Field(True, description="Whether the anomaly is enabled")
    detection_rules: List[DetectionRule] = Field(..., description="Detection rules")
    notification_addresses: Optional[List[str]] = Field(
        None, description="Email addresses for notifications"
    )
    filters: Optional[List[AlertFilter]] = Field(None, description="Additional filters")
    advanced_config: Optional[AdvancedAlertConfiguration] = Field(
        None, description="Advanced configuration"
    )

    # Response fields
    status: Optional[AnomalyStatus] = Field(None, description="Anomaly status")
    last_triggered: Optional[datetime] = Field(None, description="Last time anomaly was triggered")
    trigger_count: Optional[int] = Field(None, description="Number of times triggered")
    owner: Optional[Dict[str, Any]] = Field(None, description="Owner information")
    team: Optional[Dict[str, Any]] = Field(None, description="Associated team information")
    links: Optional[Dict[str, Any]] = Field(None, description="API links", alias="_links")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        """Validate name is not empty."""
        return validate_non_empty_string(v, "name")


class AIAnomalyLegacy(BaseReveniumModel, TimestampMixin, IdentifierMixin, MetadataMixin):
    """Legacy AI Anomaly model (kept for backward compatibility)."""

    name: str = Field(..., min_length=1, max_length=255, description="Anomaly name")
    description: Optional[str] = Field(None, max_length=1000, description="Anomaly description")
    status: AnomalyStatus = Field(AnomalyStatus.ACTIVE, description="Anomaly status")
    severity: AlertSeverity = Field(AlertSeverity.MEDIUM, description="Alert severity")
    threshold: Optional[float] = Field(None, description="Threshold value")
    metric_name: Optional[str] = Field(None, description="Monitored metric name")
    enabled: bool = Field(True, description="Whether anomaly detection is enabled")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        """Validate name is not empty."""
        return validate_non_empty_string(v, "name")


class AIAlert(BaseReveniumModel, TimestampMixin, IdentifierMixin, MetadataMixin):
    """AI Alert model representing a triggered alert from anomaly detection."""

    anomaly_id: str = Field(..., description="Associated anomaly ID")
    anomaly_name: Optional[str] = Field(None, description="Associated anomaly name")
    status: AlertStatus = Field(AlertStatus.OPEN, description="Alert status")
    severity: AlertSeverity = Field(AlertSeverity.MEDIUM, description="Alert severity")
    message: str = Field(..., description="Alert message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional alert details")
    threshold_violation: Optional[ThresholdViolation] = Field(
        None, description="Threshold violation details"
    )
    triggered_at: datetime = Field(..., description="When the alert was triggered")
    resolved_at: Optional[datetime] = Field(None, description="When the alert was resolved")
    acknowledged_at: Optional[datetime] = Field(None, description="When the alert was acknowledged")
    acknowledged_by: Optional[str] = Field(None, description="Who acknowledged the alert")
    resolution_notes: Optional[str] = Field(None, description="Notes about alert resolution")
    notification_sent: bool = Field(False, description="Whether notification was sent")
    escalated: bool = Field(False, description="Whether alert was escalated")

    @field_validator("anomaly_id")
    @classmethod
    def validate_anomaly_id(cls, v):
        """Validate anomaly ID is not empty."""
        return validate_non_empty_string(v, "anomaly_id")

    @field_validator("message")
    @classmethod
    def validate_message(cls, v):
        """Validate message is not empty."""
        return validate_non_empty_string(v, "message")
