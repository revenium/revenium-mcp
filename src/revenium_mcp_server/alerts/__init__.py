"""Alert System Package.

This package contains all alert and anomaly management functionality.
Includes anomaly CRUD operations, alert querying, semantic processing, and analytics.
"""

# Import models for convenience from original models.py file
from ..models import (  # Enumerations; Configuration models; Main models
    AdvancedAlertConfiguration,
    AIAlert,
    AIAnomaly,
    AIAnomalyLegacy,
    AIAnomalyRequest,
    AlertFilter,
    AlertSeverity,
    AlertStatus,
    AlertType,
    AnomalyStatus,
    DetectionRule,
    FilterOperator,
    GroupByDimension,
    MetricType,
    OperatorType,
    PeriodDuration,
    SlackConfiguration,
    ThresholdViolation,
    TriggerDuration,
    WebhookConfiguration,
)
from .alert_manager import AlertManager
from .analytics_engine import AnalyticsEngine, TimeRange
from .analytics_formatter import AnalyticsFormatter

# Import core managers
from .anomaly_manager import AnomalyManager

# Import advanced features
from .semantic_processor import AlertSemanticProcessor

__all__ = [
    # Core managers
    "AnomalyManager",
    "AlertManager",
    # Advanced features
    "AlertSemanticProcessor",
    "AnalyticsEngine",
    "TimeRange",
    "AnalyticsFormatter",
    # Enumerations
    "AnomalyStatus",
    "AlertSeverity",
    "AlertStatus",
    "AlertType",
    "MetricType",
    "OperatorType",
    "PeriodDuration",
    "GroupByDimension",
    "TriggerDuration",
    "FilterOperator",
    # Configuration models
    "AlertFilter",
    "SlackConfiguration",
    "WebhookConfiguration",
    "AdvancedAlertConfiguration",
    "DetectionRule",
    "ThresholdViolation",
    # Main models
    "AIAnomalyRequest",
    "AIAnomaly",
    "AIAnomalyLegacy",
    "AIAlert",
]
