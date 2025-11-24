"""Subscription-related data models for Revenium MCP server.

This module contains all data models related to subscriptions
and subscription management in the Revenium platform.
"""

from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import Field, field_validator

from .base import (
    BaseReveniumModel,
    IdentifierMixin,
    MetadataMixin,
    TimestampMixin,
    validate_non_empty_string,
)

# Subscription-specific enumerations


class SubscriptionStatus(str, Enum):
    """Subscription status enumeration."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


# Subscription models


class Subscription(BaseReveniumModel, TimestampMixin, IdentifierMixin, MetadataMixin):
    """Subscription model representing a Revenium subscription."""

    product_id: str = Field(..., description="Associated product ID")
    name: str = Field(..., description="Subscription name")
    description: Optional[str] = Field(None, description="Subscription description")
    status: SubscriptionStatus = Field(SubscriptionStatus.ACTIVE, description="Subscription status")
    start_date: Optional[datetime] = Field(None, description="Subscription start date")
    end_date: Optional[datetime] = Field(None, description="Subscription end date")

    @field_validator("product_id")
    @classmethod
    def validate_product_id(cls, v):
        """Validate product ID is not empty."""
        return validate_non_empty_string(v, "product_id")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        """Validate name is not empty."""
        return validate_non_empty_string(v, "name")

    @field_validator("end_date")
    @classmethod
    def validate_end_date(cls, v, info):
        """Validate end date is after start date if both are provided."""
        if v is not None and "start_date" in info.data:
            start_date = info.data["start_date"]
            if start_date and v <= start_date:
                raise ValueError("end_date must be after start_date")
        return v

    def is_active(self) -> bool:
        """Check if subscription is currently active."""
        if self.status != SubscriptionStatus.ACTIVE:
            return False

        now = datetime.now()

        # Check if subscription has started
        if self.start_date and self.start_date > now:
            return False

        # Check if subscription has expired
        if self.end_date and self.end_date <= now:
            return False

        return True

    def days_remaining(self) -> Optional[int]:
        """Get number of days remaining in subscription."""
        if not self.end_date:
            return None

        now = datetime.now()
        if self.end_date <= now:
            return 0

        return (self.end_date - now).days

    def is_trial(self) -> bool:
        """Check if this is a trial subscription."""
        # This is a simple heuristic - in practice you might have a dedicated trial field
        if not self.end_date or not self.start_date:
            return False

        duration_days = (self.end_date - self.start_date).days
        return duration_days <= 30  # Consider subscriptions <= 30 days as trials

    @classmethod
    def create_trial_subscription(
        cls, product_id: str, name: str, trial_days: int = 30, description: Optional[str] = None
    ) -> "Subscription":
        """Create a trial subscription.

        Args:
            product_id: ID of the product to subscribe to
            name: Name of the subscription
            trial_days: Number of trial days (default: 30)
            description: Optional description

        Returns:
            New trial subscription instance
        """
        now = datetime.now()
        end_date = now + timedelta(days=trial_days)

        return cls(
            product_id=product_id,
            name=name,
            description=description or f"Trial subscription for {name}",
            status=SubscriptionStatus.ACTIVE,
            start_date=now,
            end_date=end_date,
        )

    @classmethod
    def create_monthly_subscription(
        cls,
        product_id: str,
        name: str,
        description: Optional[str] = None,
        start_date: Optional[datetime] = None,
    ) -> "Subscription":
        """Create a monthly subscription.

        Args:
            product_id: ID of the product to subscribe to
            name: Name of the subscription
            description: Optional description
            start_date: Optional start date (defaults to now)

        Returns:
            New monthly subscription instance
        """
        start = start_date or datetime.now()

        return cls(
            product_id=product_id,
            name=name,
            description=description or f"Monthly subscription for {name}",
            status=SubscriptionStatus.ACTIVE,
            start_date=start,
            end_date=None,  # Monthly subscriptions typically don't have end dates
        )

    @classmethod
    def create_annual_subscription(
        cls,
        product_id: str,
        name: str,
        description: Optional[str] = None,
        start_date: Optional[datetime] = None,
    ) -> "Subscription":
        """Create an annual subscription.

        Args:
            product_id: ID of the product to subscribe to
            name: Name of the subscription
            description: Optional description
            start_date: Optional start date (defaults to now)

        Returns:
            New annual subscription instance
        """
        start = start_date or datetime.now()
        end = start + timedelta(days=365)

        return cls(
            product_id=product_id,
            name=name,
            description=description or f"Annual subscription for {name}",
            status=SubscriptionStatus.ACTIVE,
            start_date=start,
            end_date=end,
        )


# Subscription analytics and metrics


class SubscriptionMetrics(BaseReveniumModel):
    """Subscription metrics and analytics model."""

    total_subscriptions: int = Field(0, description="Total number of subscriptions")
    active_subscriptions: int = Field(0, description="Number of active subscriptions")
    trial_subscriptions: int = Field(0, description="Number of trial subscriptions")
    expired_subscriptions: int = Field(0, description="Number of expired subscriptions")
    cancelled_subscriptions: int = Field(0, description="Number of cancelled subscriptions")

    # Revenue metrics
    monthly_recurring_revenue: Optional[float] = Field(
        None, description="Monthly recurring revenue"
    )
    annual_recurring_revenue: Optional[float] = Field(None, description="Annual recurring revenue")
    average_revenue_per_user: Optional[float] = Field(None, description="Average revenue per user")

    # Growth metrics
    new_subscriptions_this_month: int = Field(0, description="New subscriptions this month")
    churn_rate: Optional[float] = Field(None, description="Churn rate percentage")
    growth_rate: Optional[float] = Field(None, description="Growth rate percentage")

    # Engagement metrics
    average_subscription_duration: Optional[int] = Field(
        None, description="Average subscription duration in days"
    )
    trial_conversion_rate: Optional[float] = Field(
        None, description="Trial to paid conversion rate"
    )

    def calculate_churn_rate(self, total_at_start: int, cancelled: int) -> float:
        """Calculate churn rate.

        Args:
            total_at_start: Total subscriptions at start of period
            cancelled: Number of cancellations in period

        Returns:
            Churn rate as percentage
        """
        if total_at_start == 0:
            return 0.0
        return (cancelled / total_at_start) * 100

    def calculate_growth_rate(self, previous_total: int, current_total: int) -> float:
        """Calculate growth rate.

        Args:
            previous_total: Total subscriptions in previous period
            current_total: Total subscriptions in current period

        Returns:
            Growth rate as percentage
        """
        if previous_total == 0:
            return 100.0 if current_total > 0 else 0.0
        return ((current_total - previous_total) / previous_total) * 100


class SubscriptionEvent(BaseReveniumModel, TimestampMixin):
    """Subscription event model for tracking subscription lifecycle events."""

    subscription_id: str = Field(..., description="Associated subscription ID")
    event_type: str = Field(..., description="Type of event")
    event_data: Optional[Dict[str, Any]] = Field(None, description="Event-specific data")
    user_id: Optional[str] = Field(None, description="User who triggered the event")

    @field_validator("subscription_id")
    @classmethod
    def validate_subscription_id(cls, v):
        """Validate subscription ID is not empty."""
        return validate_non_empty_string(v, "subscription_id")

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v):
        """Validate event type is not empty."""
        return validate_non_empty_string(v, "event_type")


# Common subscription event types
class SubscriptionEventType:
    """Common subscription event types."""

    CREATED = "subscription.created"
    ACTIVATED = "subscription.activated"
    CANCELLED = "subscription.cancelled"
    EXPIRED = "subscription.expired"
    RENEWED = "subscription.renewed"
    UPGRADED = "subscription.upgraded"
    DOWNGRADED = "subscription.downgraded"
    TRIAL_STARTED = "subscription.trial_started"
    TRIAL_ENDED = "subscription.trial_ended"
    TRIAL_CONVERTED = "subscription.trial_converted"
    PAYMENT_SUCCEEDED = "subscription.payment_succeeded"
    PAYMENT_FAILED = "subscription.payment_failed"
