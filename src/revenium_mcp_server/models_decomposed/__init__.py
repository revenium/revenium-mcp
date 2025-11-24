"""Data Models Package.

This package contains all Pydantic data models organized by domain.
Each module contains models for a specific resource type (products, customers, etc.).
"""

# Temporary backward compatibility - import from original models.py
from ..models import *

# Import alert models
from .alerts import (
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

# Import base classes and common utilities
from .base import (
    APIResponse,
    BaseReveniumModel,
    IdentifierMixin,
    ListResponse,
    MetadataMixin,
    RatingAggregationType,
    StatusMixin,
    TimestampMixin,
    validate_email_address,
    validate_non_empty_string,
    validate_positive_number,
)

# Import customer models
from .customers import (
    CustomerAnalytics,
    CustomerRelationship,
    Organization,
    OrganizationStatus,
    OrganizationType,
    Subscriber,
    SubscriberStatus,
    Team,
    TeamMember,
    TeamRole,
    TeamStatus,
    User,
    UserRole,
    UserStatus,
)

# Import metering element models
from .metering_elements import (
    STANDARD_AI_METERING_ELEMENTS,
    MeteringElementDefinition,
    MeteringElementStatus,
    MeteringElementTemplate,
    MeteringElementType,
    MeteringElementUsage,
    get_all_template_categories,
    get_template_by_name,
    get_templates_by_category,
)

# Import product models
from .products import (
    Element,
    Plan,
    PlanType,
    Product,
    ProductStatus,
    RatingAggregation,
    SetupFee,
    Tier,
)

# Import source models
from .sources import Source, SourceType

# Import subscription models
from .subscriptions import (
    Subscription,
    SubscriptionEvent,
    SubscriptionEventType,
    SubscriptionMetrics,
    SubscriptionStatus,
)

__all__ = [
    # Base classes and mixins
    "BaseReveniumModel",
    "TimestampMixin",
    "IdentifierMixin",
    "MetadataMixin",
    "StatusMixin",
    # Common response models
    "APIResponse",
    "ListResponse",
    # Common enumerations
    "RatingAggregationType",
    # Validation utilities
    "validate_email_address",
    "validate_positive_number",
    "validate_non_empty_string",
    # Product models
    "ProductStatus",
    "PlanType",
    "SetupFee",
    "Element",
    "RatingAggregation",
    "Tier",
    "Plan",
    "Product",
    # Customer models
    "UserStatus",
    "UserRole",
    "SubscriberStatus",
    "OrganizationType",
    "OrganizationStatus",
    "TeamStatus",
    "TeamRole",
    "User",
    "Subscriber",
    "Organization",
    "TeamMember",
    "Team",
    "CustomerAnalytics",
    "CustomerRelationship",
    # Alert models
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
    "AlertFilter",
    "SlackConfiguration",
    "WebhookConfiguration",
    "AdvancedAlertConfiguration",
    "DetectionRule",
    "ThresholdViolation",
    "AIAnomalyRequest",
    "AIAnomaly",
    "AIAnomalyLegacy",
    "AIAlert",
    # Subscription models
    "SubscriptionStatus",
    "Subscription",
    "SubscriptionMetrics",
    "SubscriptionEvent",
    "SubscriptionEventType",
    # Source models
    "SourceType",
    "Source",  # Note: SourceStatus removed - API doesn't support status field
    # Metering element models
    "MeteringElementType",
    "MeteringElementStatus",
    "MeteringElementDefinition",
    "MeteringElementUsage",
    "MeteringElementTemplate",
    "STANDARD_AI_METERING_ELEMENTS",
    "get_templates_by_category",
    "get_template_by_name",
    "get_all_template_categories",
    # Pagination and filtering models (from original models.py)
    "SortOrder",
    "SortField",
    "PaginationParams",
    "FilterCondition",
    "FilterParams",
    "PaginationMetadata",
    "PaginatedResponse",
]
