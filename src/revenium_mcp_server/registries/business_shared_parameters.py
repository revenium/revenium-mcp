"""Shared parameter objects for business management registry tools.

This module defines parameter objects for business management operations including
products, customers, subscriptions, and analytics to ensure enterprise compliance
and security patterns.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ProductRequest:
    """Parameter object for product management operations.

    Encapsulates product management parameters while maintaining security patterns
    and reducing parameter count for enterprise compliance.

    Args:
        action: Product action to perform (required)
        product_id: Product identifier
        name: Product name
        description: Product description
        sku: Product SKU
        pricing_model: Product pricing model
        metadata: Additional product metadata
        filters: Query filters for product searches
        pagination: Pagination settings
    """

    action: str
    product_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    sku: Optional[str] = None
    pricing_model: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    filters: Optional[Dict[str, Any]] = None
    pagination: Optional[Dict[str, Any]] = None


@dataclass
class CustomerRequest:
    """Parameter object for customer management operations.

    Encapsulates customer management parameters while maintaining security
    patterns and configuration management capabilities, with full compatibility
    to main branch interface.

    Args:
        action: Customer action to perform (required)
        resource_type: Resource type filter (optional)
        user_id: User identifier
        subscriber_id: Subscriber identifier
        organization_id: Organization identifier
        team_id: Team identifier
        email: Customer email address
        user_data: User creation/update data
        subscriber_data: Subscriber creation/update data
        organization_data: Organization creation/update data
        team_data: Team creation/update data
        page: Pagination page number
        size: Pagination page size
        filters: Query filters for customer searches
        dry_run: Dry run mode flag
    """

    action: str
    resource_type: Optional[str] = None
    user_id: Optional[str] = None
    subscriber_id: Optional[str] = None
    organization_id: Optional[str] = None
    team_id: Optional[str] = None
    email: Optional[str] = None
    user_data: Optional[Dict[str, Any]] = None
    subscriber_data: Optional[Dict[str, Any]] = None
    organization_data: Optional[Dict[str, Any]] = None
    team_data: Optional[Dict[str, Any]] = None
    page: Optional[int] = None
    size: Optional[int] = None
    filters: Optional[Dict[str, Any]] = None
    dry_run: Optional[bool] = None


@dataclass
class SubscriptionRequest:
    """Parameter object for subscription management operations.

    Encapsulates subscription management parameters while maintaining enterprise
    compliance and supporting complex subscription orchestration.

    Args:
        action: Subscription action to perform (required)
        subscription_id: Subscription identifier
        customer_id: Customer identifier
        product_id: Product identifier
        plan: Subscription plan
        status: Subscription status
        billing_period: Billing period
        metadata: Additional subscription metadata
        filters: Query filters for subscription searches
        pagination: Pagination settings
    """

    action: str
    subscription_id: Optional[str] = None
    customer_id: Optional[str] = None
    product_id: Optional[str] = None
    plan: Optional[str] = None
    status: Optional[str] = None
    billing_period: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    filters: Optional[Dict[str, Any]] = None
    pagination: Optional[Dict[str, Any]] = None


@dataclass
class SourceRequest:
    """Parameter object for source management operations.

    Encapsulates source management parameters while maintaining enterprise
    compliance and full compatibility with main branch interface.

    Args:
        action: Source action to perform (required)
        source_id: Source identifier
        source_data: Source data object
        page: Page number for pagination
        size: Page size for pagination
        filters: Query filters
        text: Text search parameter
        name: Source name
        type: Source type
        url: Source URL
        connection_string: Connection string
        example_type: Example type for get_examples action
        dry_run: Dry run mode
    """

    action: str
    source_id: Optional[str] = None
    source_data: Optional[dict] = None
    page: int = 0
    size: int = 20
    filters: Optional[dict] = None
    text: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    url: Optional[str] = None
    connection_string: Optional[str] = None
    example_type: Optional[str] = None
    dry_run: Optional[bool] = None


@dataclass
class AnalyticsRequest:
    """Parameter object for business analytics operations.

    Encapsulates analytics query parameters while maintaining enterprise
    compliance and supporting complex analytics workflows.

    Args:
        action: Analytics action to perform (required)
        query: Natural language query
        period: Time period for analysis
        group: Aggregation group
        threshold: Cost threshold for spike analysis
        filters: Analysis filters
        chart_type: Chart type for visualization
        include_visuals: Include chart visualizations
        session_id: Session identifier for context
    """

    action: str
    query: Optional[str] = None
    period: Optional[str] = None
    group: Optional[str] = None
    threshold: Optional[float] = None
    filters: Optional[Dict[str, Any]] = None
    chart_type: Optional[str] = None
    include_visuals: bool = False
    session_id: Optional[str] = None


def create_product_parameters(action: str, **kwargs) -> ProductRequest:
    """Create product management parameters with security validation.

    Args:
        action: Product action to perform
        **kwargs: Additional product parameters

    Returns:
        Validated product management parameters

    Raises:
        ValueError: If action is invalid
    """
    if not action or not isinstance(action, str):
        raise ValueError("Product action must be a non-empty string")

    product_params = {
        "action": action,
        "product_id": kwargs.get("product_id"),
        "name": kwargs.get("name"),
        "description": kwargs.get("description"),
        "sku": kwargs.get("sku"),
        "pricing_model": kwargs.get("pricing_model"),
        "metadata": kwargs.get("metadata"),
        "filters": kwargs.get("filters"),
        "pagination": kwargs.get("pagination"),
    }

    return ProductRequest(**product_params)


def create_customer_parameters(action: str, **kwargs) -> CustomerRequest:
    """Create customer management parameters with validation.

    Args:
        action: Customer action to perform
        **kwargs: Additional customer parameters

    Returns:
        Validated customer management parameters

    Raises:
        ValueError: If action is invalid
    """
    if not action or not isinstance(action, str):
        raise ValueError("Customer action must be a non-empty string")

    customer_params = {
        "action": action,
        "customer_id": kwargs.get("customer_id"),
        "email": kwargs.get("email"),
        "name": kwargs.get("name"),
        "organization": kwargs.get("organization"),
        "metadata": kwargs.get("metadata"),
        "filters": kwargs.get("filters"),
        "pagination": kwargs.get("pagination"),
    }

    return CustomerRequest(**customer_params)


def create_subscription_parameters(action: str, **kwargs) -> SubscriptionRequest:
    """Create subscription management parameters with validation.

    Args:
        action: Subscription action to perform
        **kwargs: Additional subscription parameters

    Returns:
        Validated subscription management parameters

    Raises:
        ValueError: If action is invalid
    """
    if not action or not isinstance(action, str):
        raise ValueError("Subscription action must be a non-empty string")

    subscription_params = {
        "action": action,
        "subscription_id": kwargs.get("subscription_id"),
        "customer_id": kwargs.get("customer_id"),
        "product_id": kwargs.get("product_id"),
        "plan": kwargs.get("plan"),
        "status": kwargs.get("status"),
        "billing_period": kwargs.get("billing_period"),
        "metadata": kwargs.get("metadata"),
        "filters": kwargs.get("filters"),
        "pagination": kwargs.get("pagination"),
    }

    return SubscriptionRequest(**subscription_params)


def create_analytics_parameters(action: str, **kwargs) -> AnalyticsRequest:
    """Create analytics parameters with validation.

    Args:
        action: Analytics action to perform
        **kwargs: Additional analytics parameters

    Returns:
        Validated analytics parameters

    Raises:
        ValueError: If action is invalid
    """
    if not action or not isinstance(action, str):
        raise ValueError("Analytics action must be a non-empty string")

    analytics_params = {
        "action": action,
        "query": kwargs.get("query"),
        "period": kwargs.get("period"),
        "group": kwargs.get("group"),
        "threshold": kwargs.get("threshold"),
        "filters": kwargs.get("filters"),
        "chart_type": kwargs.get("chart_type"),
        "include_visuals": kwargs.get("include_visuals", False),
        "session_id": kwargs.get("session_id"),
    }

    return AnalyticsRequest(**analytics_params)
