"""Customer-related data models for Revenium MCP server.

This module contains all data models related to customers, users, subscribers,
organizations, teams, and customer analytics in the Revenium platform.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import Field, field_validator

from .base import (
    BaseReveniumModel,
    IdentifierMixin,
    MetadataMixin,
    TimestampMixin,
    validate_email_address,
    validate_non_empty_string,
)

# Customer-specific enumerations


class UserStatus(str, Enum):
    """User status enumeration."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class UserRole(str, Enum):
    """User role enumeration for Revenium API."""

    ROLE_TENANT_ADMIN = "ROLE_TENANT_ADMIN"
    ROLE_API_CONSUMER = "ROLE_API_CONSUMER"


class SubscriberStatus(str, Enum):
    """Subscriber status enumeration."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    TRIAL = "trial"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class OrganizationType(str, Enum):
    """Organization type enumeration."""

    ENTERPRISE = "enterprise"
    BUSINESS = "business"
    STARTUP = "startup"
    INDIVIDUAL = "individual"
    NON_PROFIT = "non_profit"
    GOVERNMENT = "government"


class OrganizationStatus(str, Enum):
    """Organization status enumeration."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class TeamStatus(str, Enum):
    """Team status enumeration."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"
    DELETED = "deleted"


class TeamRole(str, Enum):
    """Team role enumeration."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"
    GUEST = "guest"


# Customer models


class User(BaseReveniumModel, TimestampMixin, IdentifierMixin, MetadataMixin):
    """User model representing a customer user account."""

    email: str = Field(..., description="User email address")
    first_name: Optional[str] = Field(None, description="User first name")
    last_name: Optional[str] = Field(None, description="User last name")
    full_name: Optional[str] = Field(None, description="User full name")
    status: UserStatus = Field(UserStatus.ACTIVE, description="User status")
    organization_id: Optional[str] = Field(None, description="Associated organization ID")
    team_id: Optional[str] = Field(None, description="Associated team ID")
    role: Optional[str] = Field(None, description="User role")
    permissions: Optional[List[str]] = Field(default_factory=list, description="User permissions")
    last_login: Optional[datetime] = Field(None, description="Last login timestamp")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        """Validate email address format."""
        return validate_email_address(v)


class Subscriber(BaseReveniumModel, TimestampMixin, IdentifierMixin, MetadataMixin):
    """Subscriber model representing an active subscription holder."""

    user_id: Optional[str] = Field(None, description="Associated user ID")
    email: str = Field(..., description="Subscriber email address")
    name: Optional[str] = Field(None, description="Subscriber name")
    status: SubscriberStatus = Field(SubscriberStatus.ACTIVE, description="Subscriber status")
    subscription_ids: Optional[List[str]] = Field(
        default_factory=list, description="Associated subscription IDs"
    )
    organization_id: Optional[str] = Field(None, description="Associated organization ID")
    billing_address: Optional[Dict[str, Any]] = Field(
        None, description="Billing address information"
    )
    payment_method: Optional[Dict[str, Any]] = Field(None, description="Payment method information")
    trial_end_date: Optional[datetime] = Field(None, description="Trial end date")
    subscription_start_date: Optional[datetime] = Field(None, description="Subscription start date")
    last_billing_date: Optional[datetime] = Field(None, description="Last billing date")
    next_billing_date: Optional[datetime] = Field(None, description="Next billing date")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        """Validate email address format."""
        return validate_email_address(v)


class Organization(BaseReveniumModel, TimestampMixin, IdentifierMixin, MetadataMixin):
    """Organization model representing a customer organization."""

    name: str = Field(..., description="Organization name")
    display_name: Optional[str] = Field(None, description="Organization display name")
    description: Optional[str] = Field(None, description="Organization description")
    type: OrganizationType = Field(OrganizationType.BUSINESS, description="Organization type")
    status: OrganizationStatus = Field(OrganizationStatus.ACTIVE, description="Organization status")
    parent_organization_id: Optional[str] = Field(
        None, description="Parent organization ID for hierarchies"
    )
    website: Optional[str] = Field(None, description="Organization website")
    industry: Optional[str] = Field(None, description="Organization industry")
    size: Optional[str] = Field(None, description="Organization size (e.g., '1-10', '11-50')")
    address: Optional[Dict[str, Any]] = Field(None, description="Organization address")
    contact_info: Optional[Dict[str, Any]] = Field(None, description="Contact information")
    billing_info: Optional[Dict[str, Any]] = Field(None, description="Billing information")
    tags: Optional[List[str]] = Field(default_factory=list, description="Organization tags")
    user_count: Optional[int] = Field(None, description="Number of users in organization")
    team_count: Optional[int] = Field(None, description="Number of teams in organization")
    subscription_count: Optional[int] = Field(None, description="Number of active subscriptions")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        """Validate name is not empty."""
        return validate_non_empty_string(v, "name")


class TeamMember(BaseReveniumModel):
    """Team member model."""

    user_id: str = Field(..., description="User ID")
    email: Optional[str] = Field(None, description="User email")
    name: Optional[str] = Field(None, description="User name")
    role: TeamRole = Field(TeamRole.MEMBER, description="Team role")
    joined_at: Optional[datetime] = Field(None, description="Date joined team")
    last_active: Optional[datetime] = Field(None, description="Last activity timestamp")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        """Validate email address format if provided."""
        if v:
            return validate_email_address(v)
        return v


class Team(BaseReveniumModel, TimestampMixin, IdentifierMixin, MetadataMixin):
    """Team model representing a team within an organization."""

    name: str = Field(..., description="Team name")
    display_name: Optional[str] = Field(None, description="Team display name")
    description: Optional[str] = Field(None, description="Team description")
    status: TeamStatus = Field(TeamStatus.ACTIVE, description="Team status")
    organization_id: str = Field(..., description="Associated organization ID")
    parent_team_id: Optional[str] = Field(None, description="Parent team ID for hierarchies")
    owner_id: Optional[str] = Field(None, description="Team owner user ID")
    members: Optional[List[TeamMember]] = Field(default_factory=list, description="Team members")
    member_count: Optional[int] = Field(None, description="Number of team members")
    permissions: Optional[List[str]] = Field(default_factory=list, description="Team permissions")
    settings: Optional[Dict[str, Any]] = Field(None, description="Team settings")
    tags: Optional[List[str]] = Field(default_factory=list, description="Team tags")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        """Validate name is not empty."""
        return validate_non_empty_string(v, "name")


# Customer analytics models


class CustomerAnalytics(BaseReveniumModel):
    """Customer analytics aggregation model."""

    total_users: int = Field(0, description="Total number of users")
    active_users: int = Field(0, description="Number of active users")
    total_subscribers: int = Field(0, description="Total number of subscribers")
    active_subscribers: int = Field(0, description="Number of active subscribers")
    total_organizations: int = Field(0, description="Total number of organizations")
    active_organizations: int = Field(0, description="Number of active organizations")
    total_teams: int = Field(0, description="Total number of teams")
    active_teams: int = Field(0, description="Number of active teams")
    growth_metrics: Optional[Dict[str, Any]] = Field(None, description="Growth metrics")
    engagement_metrics: Optional[Dict[str, Any]] = Field(None, description="Engagement metrics")
    revenue_metrics: Optional[Dict[str, Any]] = Field(None, description="Revenue metrics")


class CustomerRelationship(BaseReveniumModel, TimestampMixin):
    """Model representing relationships between customer entities."""

    user_id: Optional[str] = Field(None, description="User ID")
    subscriber_id: Optional[str] = Field(None, description="Subscriber ID")
    organization_id: Optional[str] = Field(None, description="Organization ID")
    team_id: Optional[str] = Field(None, description="Team ID")
    subscription_ids: Optional[List[str]] = Field(
        default_factory=list, description="Related subscription IDs"
    )
    product_ids: Optional[List[str]] = Field(
        default_factory=list, description="Related product IDs"
    )
    source_ids: Optional[List[str]] = Field(default_factory=list, description="Related source IDs")
    relationship_type: str = Field(..., description="Type of relationship")
    strength: Optional[float] = Field(None, description="Relationship strength score")

    @field_validator("relationship_type")
    @classmethod
    def validate_relationship_type(cls, v):
        """Validate relationship type is not empty."""
        return validate_non_empty_string(v, "relationship_type")

    @field_validator("strength")
    @classmethod
    def validate_strength(cls, v):
        """Validate strength is between 0 and 1 if provided."""
        if v is not None and (v < 0 or v > 1):
            raise ValueError("strength must be between 0 and 1")
        return v
