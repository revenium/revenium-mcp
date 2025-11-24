"""Shared parameter objects for enterprise compliance (≤3 parameters per function).

This module contains parameter objects that reduce function complexity by
consolidating multiple parameters into structured objects, ensuring all
functions maintain ≤3 parameters for enterprise compliance.
"""

from dataclasses import dataclass
from typing import Optional, Union

# ============================================================================
# BUSINESS DOMAIN PARAMETER OBJECTS
# ============================================================================


@dataclass
class ProductRequest:
    """Parameter object for manage_products function following Phase 1 pattern."""

    action: str
    product_id: Optional[str] = None
    product_data: Optional[dict] = None
    subscription_data: Optional[dict] = None
    page: int = 0
    size: int = 20
    filters: Optional[dict] = None
    description: Optional[str] = None
    text: Optional[str] = None
    field: Optional[str] = None
    template: Optional[str] = None
    name: Optional[str] = None
    requirements: Optional[Union[str, dict]] = None
    domain: Optional[str] = None
    business_domain: Optional[str] = None
    dry_run: Optional[bool] = None
    example_type: Optional[str] = None
    search_query: Optional[str] = None
    data_type: Optional[str] = None
    customer_name: Optional[str] = None
    product_name: Optional[str] = None
    pricing_model: Optional[str] = None
    per_unit_price: Optional[float] = None
    monthly_price: Optional[float] = None
    setup_fee: Optional[float] = None
    type: Optional[str] = None


@dataclass
class CustomerRequest:
    """Parameter object for manage_customers function following Team B's parameter object pattern.

    This dataclass consolidates all 15 parameters from the original manage_customers
    function into a single parameter object, reducing parameter count from 15 to 1
    and establishing compliance with enterprise refactoring standards.
    """

    action: str
    resource_type: Optional[str] = None
    user_id: Optional[str] = None
    subscriber_id: Optional[str] = None
    organization_id: Optional[str] = None
    team_id: Optional[str] = None
    email: Optional[str] = None
    user_data: Optional[dict] = None
    subscriber_data: Optional[dict] = None
    organization_data: Optional[dict] = None
    team_data: Optional[dict] = None
    page: int = 0
    size: int = 20
    filters: Optional[dict] = None
    dry_run: Optional[bool] = None


@dataclass
class SubscriptionRequest:
    """Parameter object for manage_subscriptions function following Phase 1 pattern."""

    action: str
    subscription_id: Optional[str] = None
    subscription_data: Optional[dict] = None
    credentials_data: Optional[dict] = None
    page: int = 0
    size: int = 20
    filters: Optional[dict] = None
    text: Optional[str] = None
    product_id: Optional[str] = None
    clientEmailAddress: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    subscription_type: Optional[str] = None
    example_type: Optional[str] = None
    search_query: Optional[str] = None
    data_type: Optional[str] = None
    customer_name: Optional[str] = None
    product_name: Optional[str] = None
    subscriber_email: Optional[str] = None
    query: Optional[str] = None
    dry_run: Optional[bool] = None


@dataclass
class SourceRequest:
    """Parameter object for manage_sources function following Phase 1 pattern."""

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
