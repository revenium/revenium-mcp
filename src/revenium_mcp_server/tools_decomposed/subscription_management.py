"""Consolidated subscription management tool following MCP best practices.

This module consolidates enhanced_subscription_tools.py + subscription_tools.py into a single
tool with internal composition, following the proven alert/source/customer management template.
"""

import json
import os
import time
from typing import Any, Dict, List, Optional, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..client import ReveniumAPIError, ReveniumClient
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_structured_missing_parameter_error,
    create_structured_validation_error,
)
from ..common.partial_update_handler import PartialUpdateHandler
from ..common.update_configs import UpdateConfigFactory
from ..config_store import get_config_value
from ..exceptions import ValidationError
from ..hierarchy import (
    cross_tier_validator,
    entity_lookup_service,
    hierarchy_navigation_service,
)
from ..introspection.metadata import (
    DependencyType,
    ResourceRelationship,
    ToolCapability,
    ToolDependency,
    ToolType,
    UsagePattern,
)
from .unified_tool_base import ToolBase


class SubscriptionManager:
    """Internal manager for subscription CRUD operations."""

    def __init__(self, client: ReveniumClient) -> None:
        """Initialize subscription manager with client."""
        self.client = client

        # Initialize partial update handler and config factory
        self.update_handler = PartialUpdateHandler()
        self.update_config_factory = UpdateConfigFactory(self.client)

    async def discover_products(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Discover available products for subscription creation."""
        search_query = arguments.get("search_query", "")
        page = arguments.get("page", 0)
        size = arguments.get("size", 10)

        try:
            # Get products from the manage_products tool
            response = await self.client.get_products(page=page, size=size)
            products = self.client._extract_embedded_data(response)
            page_info = self.client._extract_pagination_info(response)

            # Filter products if search query provided
            if search_query:
                filtered_products = []
                search_lower = search_query.lower()
                for product in products:
                    name = (product.get("name") or "").lower()
                    description = (product.get("description") or "").lower()
                    if search_lower in name or search_lower in description:
                        filtered_products.append(product)
                products = filtered_products

            # Format products for agent consumption
            formatted_products = []
            for product in products:
                formatted_product = {
                    "id": product.get("id"),
                    "name": product.get("name"),
                    "description": product.get("description", "No description available"),
                    "published": product.get("published", False),
                    "status": (
                        "Available for subscriptions"
                        if product.get("published")
                        else "Not available (unpublished)"
                    ),
                    "billing_implications": {
                        "charges_apply": True,
                        "warning": "Creating subscriptions with this product will result in billing charges",
                        "recommendation": "Verify product details and pricing before creating subscriptions",
                    },
                }
                formatted_products.append(formatted_product)

            return {
                "action": "discover_products",
                "search_query": search_query,
                "products": formatted_products,
                "total_found": len(formatted_products),
                "pagination": page_info,
                "billing_warning": "⚠️ IMPORTANT: Product selection directly affects customer billing. Always verify product details before creating subscriptions.",
                "next_steps": [
                    "Review product details and billing implications",
                    "Use 'validate_product_for_subscription' to check product suitability",
                    "Specify exact product_id when creating subscriptions",
                ],
            }

        except Exception as e:
            logger.error(f"Error discovering products: {e}")
            return {
                "action": "discover_products",
                "error": f"Failed to discover products: {repr(e)}",
                "fallback_guidance": [
                    "Use 'manage_products' tool with action='list' to see available products",
                    "Ensure products are published before using in subscriptions",
                    "Always specify explicit product_id to avoid billing errors",
                ],
            }

    async def validate_product_for_subscription(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Validate if a product is suitable for subscription creation."""
        product_id = arguments.get("product_id")
        if not product_id:
            raise create_structured_missing_parameter_error(
                parameter_name="product_id",
                action="validate product for subscription",
                examples={
                    "usage": "validate_product(product_id='prod_123')",
                    "valid_format": "Product ID should be a string identifier",
                    "example_ids": ["prod_123", "product_456", "plan_789"],
                    "billing_safety": "🔒 BILLING SAFETY: Product validation prevents subscription creation with invalid products",
                },
            )

        try:
            # Get product details
            product = await self.client.get_product_by_id(product_id)
            if not product:
                return {
                    "valid": False,
                    "product_id": product_id,
                    "error": "Product not found",
                    "recommendation": "Use 'discover_products' to find available products",
                }

            # Check if product is published
            is_published = product.get("published", False)

            validation_result = {
                "valid": is_published,
                "product_id": product_id,
                "product_name": product.get("name"),
                "product_description": product.get("description"),
                "published": is_published,
                "billing_implications": {
                    "charges_will_apply": True,
                    "billing_model": "Based on product configuration",
                    "warning": "⚠️ Creating subscriptions with this product will result in customer billing",
                },
            }

            if not is_published:
                validation_result.update(
                    {
                        "error": "Product is not published and cannot be used for subscriptions",
                        "recommendation": "Contact administrator to publish the product or choose a different product",
                    }
                )
            else:
                validation_result.update(
                    {
                        "status": "✅ Product is valid for subscription creation",
                        "next_steps": [
                            "Proceed with subscription creation using this product_id",
                            "Ensure customer is aware of billing implications",
                            "Verify customer email and billing details",
                        ],
                    }
                )

            return validation_result

        except Exception as e:
            logger.error(f"Error validating product {product_id}: {e}")
            return {
                "valid": False,
                "product_id": product_id,
                "error": f"Validation failed: {repr(e)}",
                "recommendation": "Verify product_id is correct and try again",
            }

    async def list_subscriptions(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List subscriptions with pagination."""
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters = arguments.get("filters", {})

        response = await self.client.get_subscriptions(page=page, size=size, **filters)
        subscriptions = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)

        return {
            "action": "list",
            "subscriptions": subscriptions,
            "pagination": page_info,
            "total_found": len(subscriptions),
        }

    async def get_subscription(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get specific subscription by ID."""
        subscription_id = arguments.get("subscription_id")
        if not subscription_id:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_id",
                action="get subscription",
                examples={
                    "usage": "get(subscription_id='sub_123')",
                    "valid_format": "Subscription ID should be a string identifier",
                    "example_ids": ["sub_123", "subscription_456", "billing_789"],
                    "billing_safety": "🔒 BILLING SAFETY: Subscription retrieval helps verify billing status and usage",
                },
            )

        try:
            subscription = await self.client.get_subscription_by_id(subscription_id)
            return subscription
        except ReveniumAPIError as e:
            if e.status_code == 404:
                raise ToolError(
                    message=f"Subscription not found for id: {subscription_id}",
                    error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                    field="subscription_id",
                    value=subscription_id,
                    suggestions=[
                        "Verify the subscription ID exists using list()",
                        "Check if the subscription was recently deleted or cancelled",
                        "Use get_examples() to see valid subscription ID formats",
                        "🔒 BILLING SAFETY: Ensure subscription ID is correct to avoid billing errors",
                    ],
                )
            elif e.status_code == 400:
                raise ToolError(
                    message=f"Invalid subscription ID format: {subscription_id}",
                    error_code=ErrorCodes.VALIDATION_ERROR,
                    field="subscription_id",
                    value=subscription_id,
                    suggestions=[
                        "Subscription IDs should be 6-character alphanumeric strings (e.g., 'WwgyKa')",
                        "Use list() to see valid subscription IDs",
                        "Check the ID format - it should not contain special characters",
                        "🔒 BILLING SAFETY: Correct ID format prevents billing errors",
                    ],
                )
            else:
                # Re-raise other API errors as-is
                raise

    async def create_subscription(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create new subscription with Context7 auto-generation support."""
        subscription_data = arguments.get("subscription_data")
        name = arguments.get("name")

        # Context7 auto-generation: Handle case where user provides only name
        if not subscription_data and name:
            # Auto-generate subscription_data from minimal user input
            # First, get the first available product
            try:
                products_response = await self.client.get_products(page=0, size=1)
                products = self.client._extract_embedded_data(products_response)

                if not products:
                    raise create_structured_validation_error(
                        message="No products available for subscription creation",
                        field="product_id",
                        value="none_available",
                        suggestions=[
                            "Create a product first using manage_products tool",
                            "Use manage_products(action='list') to see available products",
                        ],
                    )

                first_product = products[0]
                product_id = first_product.get("id")

                # Generate email from name
                email_name = name.lower().replace(" ", ".").replace("@", "").replace(".", "")
                generated_email = f"{email_name}@example.com"

                subscription_data = {
                    "name": name,
                    "description": f"Subscription for {name}",
                    "productId": product_id,
                    "clientEmailAddress": generated_email,
                }

                logger.info(
                    f"Context7 auto-generation: Created subscription_data for '{name}' with product {product_id}"
                )

            except Exception as e:
                logger.error(f"Context7 auto-generation failed: {e}")
                raise create_structured_validation_error(
                    message="Unable to auto-generate subscription data",
                    field="name",
                    value=name,
                    suggestions=[
                        "Provide explicit subscription_data parameter",
                        "Ensure products exist using manage_products tool",
                        "Use get_examples() to see full subscription templates",
                    ],
                )

        elif not subscription_data:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_data",
                action="create subscription",
                examples={
                    "usage": "create(subscription_data={'product_id': 'prod_123', 'clientEmailAddress': 'customer@company.com'})",
                    "required_fields": ["product_id", "clientEmailAddress"],
                    "example_data": {
                        "product_id": "prod_123",
                        "clientEmailAddress": "customer@company.com",
                        "billing_cycle": "monthly",
                    },
                    "billing_safety": "⚠️ CRITICAL: Subscription creation initiates billing - ensure all data is correct",
                    "field_descriptions": {
                        "clientEmailAddress": "Owner of the subscription who will receive invoices at this address if that option is selected for the subscription and product"
                    },
                },
            )

        # REMOVED: Status validation - status field NOT FOUND in actual Revenium API responses
        # The API does not return or accept a status field for subscription objects

        # Add required API fields that were missing
        if "productId" not in subscription_data and "product_id" in subscription_data:
            subscription_data["productId"] = subscription_data["product_id"]

        # Handle email parameter mapping
        if "clientEmailAddress" not in subscription_data and arguments.get("clientEmailAddress"):
            subscription_data["clientEmailAddress"] = arguments["clientEmailAddress"]

        # Add required fields from client environment
        if "teamId" not in subscription_data:
            subscription_data["teamId"] = self.client.team_id
        if "ownerId" not in subscription_data:
            owner_id = get_config_value("REVENIUM_OWNER_ID")
            if owner_id:
                subscription_data["ownerId"] = owner_id
            else:
                # Skip ownerId if not available - let API handle default
                logger.warning(
                    "REVENIUM_OWNER_ID not available from configuration store, API will use default owner"
                )

        result = await self.client.create_subscription(subscription_data)
        return result

    async def update_subscription(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Update existing subscription using PartialUpdateHandler."""
        subscription_id = arguments.get("subscription_id")
        subscription_data = arguments.get("subscription_data")

        # Basic parameter validation (PartialUpdateHandler will provide detailed errors)
        if not subscription_id:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_id",
                action="update subscription",
                examples={
                    "usage": "update(subscription_id='sub_123', subscription_data={'name': 'Updated Subscription'})",
                    "note": "Now supports partial updates - only provide fields you want to change",
                    "billing_safety": "🔒 BILLING SAFETY: Subscription updates can affect billing - verify ID is correct",
                },
            )

        if not subscription_data:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_data",
                action="update subscription",
                examples={
                    "usage": "update(subscription_id='sub_123', subscription_data={'name': 'Updated Subscription'})",
                    "partial_update": "Only provide the fields you want to update",
                    "updatable_fields": ["name", "description", "metadata", "status"],
                    "billing_safety": "🔒 BILLING SAFETY: Partial updates preserve existing subscription configuration while changing specific fields",
                },
            )

        # Get update configuration for subscriptions
        config = self.update_config_factory.get_config("subscriptions")

        # Use PartialUpdateHandler for the update operation
        result = await self.update_handler.update_with_merge(
            resource_id=subscription_id,
            partial_data=subscription_data,
            config=config,
            action_context="update subscription",
        )

        return result

    async def cancel_subscription(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Cancel subscription."""
        subscription_id = arguments.get("subscription_id")
        if not subscription_id:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_id",
                action="cancel subscription",
                examples={
                    "usage": "cancel(subscription_id='sub_123')",
                    "valid_format": "Subscription ID should be a string identifier",
                    "example_ids": ["sub_123", "subscription_456", "billing_789"],
                    "billing_safety": "🔒 BILLING SAFETY: Subscription cancellation stops billing - ensure correct subscription ID",
                },
            )

        result = await self.client.cancel_subscription(subscription_id)
        return result

    async def delete_subscription(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Delete subscription permanently."""
        subscription_id = arguments.get("subscription_id")
        if not subscription_id:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_id",
                action="delete subscription",
                examples={
                    "usage": "delete(subscription_id='sub_123')",
                    "valid_format": "Subscription ID should be a string identifier",
                    "example_ids": ["sub_123", "subscription_456", "billing_789"],
                    "billing_safety": "🔒 BILLING SAFETY: Subscription deletion permanently removes subscription - ensure correct subscription ID",
                },
            )

        # Use the same cancel_subscription method since it uses DELETE endpoint
        result = await self.client.cancel_subscription(subscription_id)
        return result

    async def get_supporting_data(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get supporting data for subscription creation (organizations, products, subscribers, credentials)."""
        data_type = arguments.get("data_type", "all")
        page = arguments.get("page", 0)
        size = arguments.get("size", 100)
        search_query = arguments.get("search_query", "")

        result = {
            "action": "get_supporting_data",
            "data_type": data_type,
            "search_query": search_query,
        }

        try:
            if data_type in ["all", "organizations"]:
                orgs_response = await self.client.get_organizations(page=page, size=size)
                organizations = self.client._extract_embedded_data(orgs_response)

                # Filter organizations if search query provided
                if search_query:
                    filtered_orgs = []
                    search_lower = search_query.lower()
                    for org in organizations:
                        name = (org.get("name") or "").lower()
                        if search_lower in name:
                            filtered_orgs.append(org)
                    organizations = filtered_orgs

                result["organizations"] = organizations

            if data_type in ["all", "products"]:
                products_response = await self.client.get_products(page=page, size=size)
                products = self.client._extract_embedded_data(products_response)

                # Filter products if search query provided
                if search_query:
                    filtered_products = []
                    search_lower = search_query.lower()
                    for product in products:
                        name = (product.get("name") or "").lower()
                        description = (product.get("description") or "").lower()
                        if search_lower in name or search_lower in description:
                            filtered_products.append(product)
                    products = filtered_products

                result["products"] = products

            if data_type in ["all", "subscribers"]:
                subscribers_response = await self.client.get_subscribers(page=page, size=size)
                subscribers = self.client._extract_embedded_data(subscribers_response)

                # Filter subscribers if search query provided
                if search_query:
                    filtered_subscribers = []
                    search_lower = search_query.lower()
                    for subscriber in subscribers:
                        email = (subscriber.get("email") or "").lower()
                        name = (subscriber.get("name") or "").lower()
                        if search_lower in email or search_lower in name:
                            filtered_subscribers.append(subscriber)
                    subscribers = filtered_subscribers

                result["subscribers"] = subscribers

            if data_type in ["all", "credentials"]:
                credentials_response = await self.client.get_credentials(page=page, size=size)
                credentials = self.client._extract_embedded_data(credentials_response)

                # Filter credentials if search query provided
                if search_query:
                    filtered_credentials = []
                    search_lower = search_query.lower()
                    for credential in credentials:
                        name = (credential.get("name") or "").lower()
                        if search_lower in name:
                            filtered_credentials.append(credential)
                    credentials = filtered_credentials

                result["credentials"] = credentials

            return result

        except Exception as e:
            logger.error(f"Error getting supporting data: {e}")
            result["error"] = f"Failed to get supporting data: {repr(e)}"
            return result

    async def search_subscriptions(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Search subscriptions with advanced filtering."""
        search_query = arguments.get("search_query", "")
        customer_name = arguments.get("customer_name", "")
        product_name = arguments.get("product_name", "")
        subscriber_email = arguments.get("subscriber_email", "")
        page = arguments.get("page", 0)
        size = arguments.get("size", 50)  # Get more for filtering

        # Get all subscriptions first
        response = await self.client.get_subscriptions(page=page, size=size)
        subscriptions = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)

        # Apply client-side filtering
        filtered_subscriptions = []

        for subscription in subscriptions:
            matches = True

            # General search query filter
            if search_query:
                search_lower = search_query.lower()
                searchable_text = " ".join(
                    [
                        str(subscription.get("name", "")),
                        str(subscription.get("customer", "")),
                        str(subscription.get("product", "")),
                        str(subscription.get("subscriber", "")),
                        str(subscription.get("description", "")),
                    ]
                ).lower()

                if search_lower not in searchable_text:
                    matches = False

            # Specific field filters
            if customer_name and matches:
                customer_lower = customer_name.lower()
                sub_customer = str(subscription.get("customer", "")).lower()
                if customer_lower not in sub_customer:
                    matches = False

            if product_name and matches:
                product_lower = product_name.lower()
                sub_product = str(subscription.get("product", "")).lower()
                if product_lower not in sub_product:
                    matches = False

            if subscriber_email and matches:
                email_lower = subscriber_email.lower()
                sub_email = str(subscription.get("subscriber", "")).lower()
                if email_lower not in sub_email:
                    matches = False

            if matches:
                filtered_subscriptions.append(subscription)

        return {
            "action": "search_subscriptions",
            "search_criteria": {
                "search_query": search_query,
                "customer_name": customer_name,
                "product_name": product_name,
                "subscriber_email": subscriber_email,
            },
            "subscriptions": filtered_subscriptions,
            "total_found": len(filtered_subscriptions),
            "original_total": len(subscriptions),
            "pagination": page_info,
        }

    async def subscription_nlp(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Process natural language queries for subscription management."""
        query = arguments.get("query", "").lower()

        if not query:
            raise create_structured_missing_parameter_error(
                parameter_name="query",
                action="process natural language subscription query",
                examples={
                    "usage": "subscription_nlp(query='show me all subscriptions for globaltech')",
                    "valid_queries": [
                        "list all subscriptions",
                        "show subscriptions for customer X",
                        "find subscriptions with product Y",
                        "get subscription details for ID Z",
                        "create subscription for customer A with product B",
                    ],
                    "billing_safety": "🔒 BILLING SAFETY: NLP queries help ensure correct subscription operations",
                },
            )

        # Intent classification
        intent = self._classify_subscription_intent(query)
        entities = self._extract_subscription_entities(query)

        # Route to appropriate action based on intent
        if intent == "list_subscriptions":
            return await self.list_subscriptions(
                {
                    "page": entities.get("page", 0),
                    "size": entities.get("size", 20),
                    "filters": entities.get("filters", {}),
                }
            )

        elif intent == "search_subscriptions":
            return await self.search_subscriptions(
                {
                    "search_query": entities.get("search_query", ""),
                    "customer_name": entities.get("customer_name", ""),
                    "product_name": entities.get("product_name", ""),
                    "subscriber_email": entities.get("subscriber_email", ""),
                    "page": entities.get("page", 0),
                    "size": entities.get("size", 20),
                }
            )

        elif intent == "get_subscription":
            if entities.get("subscription_id"):
                return await self.get_subscription({"subscription_id": entities["subscription_id"]})
            else:
                return {
                    "error": "Subscription ID required for getting specific subscription",
                    "suggestion": "Please specify a subscription ID, e.g., 'get subscription sub_123'",
                }

        elif intent == "get_supporting_data":
            return await self.get_supporting_data(
                {
                    "data_type": entities.get("data_type", "all"),
                    "search_query": entities.get("search_query", ""),
                    "page": entities.get("page", 0),
                    "size": entities.get("size", 100),
                }
            )

        elif intent == "create_subscription":
            return {
                "intent": "create_subscription",
                "message": "🔒 BILLING SAFETY: Subscription creation requires explicit confirmation",
                "extracted_entities": entities,
                "next_steps": [
                    "Use discover_products() to find available products",
                    "Use validate_product_for_subscription() to verify product",
                    "Use create_simple() or create() with explicit parameters",
                ],
                "warning": "⚠️ Natural language subscription creation requires explicit product_id and clientEmailAddress for billing safety",
            }

        else:
            return {
                "intent": intent,
                "entities": entities,
                "message": f"Recognized intent '{intent}' but no direct action available",
                "suggestions": [
                    "Try: 'list all subscriptions'",
                    "Try: 'search subscriptions for customer X'",
                    "Try: 'get subscription details for ID Y'",
                    "Try: 'show me available products'",
                ],
            }

    def _classify_subscription_intent(self, query: str) -> str:
        """Classify the intent of a subscription-related query."""
        query_lower = query.lower()

        # List/show patterns
        if any(
            pattern in query_lower
            for pattern in ["list", "show", "display", "view all", "get all", "see all"]
        ):
            if any(pattern in query_lower for pattern in ["subscription", "subs"]):
                return "list_subscriptions"

        # Search patterns
        if any(
            pattern in query_lower for pattern in ["search", "find", "look for", "filter", "where"]
        ):
            return "search_subscriptions"

        # Get specific subscription patterns
        if any(
            pattern in query_lower
            for pattern in [
                "get subscription",
                "subscription details",
                "show subscription",
                "subscription info",
            ]
        ):
            return "get_subscription"

        # Supporting data patterns
        if any(
            pattern in query_lower
            for pattern in ["products", "customers", "organizations", "subscribers", "credentials"]
        ):
            return "get_supporting_data"

        # Create patterns
        if any(
            pattern in query_lower for pattern in ["create", "add", "new subscription", "subscribe"]
        ):
            return "create_subscription"

        # Default to search if unclear
        return "search_subscriptions"

    def _extract_subscription_entities(self, query: str) -> Dict[str, Any]:
        """Extract entities from a subscription-related query."""
        query_lower = query.lower()
        entities = {}

        # Extract customer/organization names
        customer_patterns = [
            r"customer\s+([a-zA-Z0-9\-_]+)",
            r"organization\s+([a-zA-Z0-9\-_]+)",
            r"for\s+([a-zA-Z0-9\-_]+)",
            r"globaltech",
            r"nexus-research",
            r"innovate",
            r"streamflow",
        ]

        for pattern in customer_patterns:
            import re

            match = re.search(pattern, query_lower)
            if match:
                if pattern in ["globaltech", "nexus-research", "innovate", "streamflow"]:
                    entities["customer_name"] = pattern
                else:
                    entities["customer_name"] = match.group(1)
                break

        # Extract product names
        product_patterns = [
            r"product\s+([a-zA-Z0-9\-_\s]+)",
            r"with\s+([a-zA-Z0-9\-_\s]+)\s+product",
            r"automated billing",
            r"default api product",
        ]

        for pattern in product_patterns:
            match = re.search(pattern, query_lower)
            if match:
                if pattern in ["automated billing", "default api product"]:
                    entities["product_name"] = pattern
                else:
                    entities["product_name"] = match.group(1).strip()
                break

        # Extract subscription IDs
        id_patterns = [
            r"subscription\s+([a-zA-Z0-9]+)",
            r"id\s+([a-zA-Z0-9]+)",
            r"sub_([a-zA-Z0-9]+)",
        ]

        for pattern in id_patterns:
            match = re.search(pattern, query_lower)
            if match:
                if pattern.startswith("sub_"):
                    entities["subscription_id"] = f"sub_{match.group(1)}"
                else:
                    entities["subscription_id"] = match.group(1)
                break

        # Extract email addresses
        email_pattern = r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"
        email_match = re.search(email_pattern, query_lower)
        if email_match:
            entities["subscriber_email"] = email_match.group(1)

        # Extract data type for supporting data queries
        if any(word in query_lower for word in ["product", "products"]):
            entities["data_type"] = "products"
        elif any(word in query_lower for word in ["customer", "organization", "organizations"]):
            entities["data_type"] = "organizations"
        elif any(word in query_lower for word in ["subscriber", "subscribers"]):
            entities["data_type"] = "subscribers"
        elif any(word in query_lower for word in ["credential", "credentials"]):
            entities["data_type"] = "credentials"

        # Extract general search query (remove intent words)
        search_query = query_lower
        for remove_word in [
            "list",
            "show",
            "display",
            "search",
            "find",
            "get",
            "subscription",
            "subscriptions",
        ]:
            search_query = search_query.replace(remove_word, "")
        search_query = search_query.strip()

        if search_query and len(search_query) > 2:
            entities["search_query"] = search_query

        return entities

    async def create_simple(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create simple subscription with smart defaults."""
        # Extract and validate parameters
        product_id, client_email, name, billing_frequency_hint = self._extract_simple_parameters(
            arguments
        )

        # Validate required parameters
        self._validate_simple_required_parameters(product_id, client_email)

        # Validate product existence and availability
        await self._validate_simple_product(product_id)

        # Build configuration and create subscription
        subscription_config = self._build_simple_subscription_config(
            product_id, client_email, name, billing_frequency_hint
        )

        # Create the subscription
        result = await self.client.create_subscription(subscription_config)
        return result

    def _extract_simple_parameters(self, arguments: Dict[str, Any]) -> tuple:
        """Extract parameters for simple subscription creation."""
        subscription_data = arguments.get("subscription_data", {})

        # Priority 1: Direct parameters
        product_id = arguments.get("product_id") or subscription_data.get("product_id")
        name = arguments.get("name") or subscription_data.get("name")
        client_email = arguments.get("clientEmailAddress") or subscription_data.get(
            "clientEmailAddress"
        )
        # Extract billing frequency hint for description purposes only
        billing_frequency_hint = (
            arguments.get("billing_frequency")
            or arguments.get("type")  # Legacy support
            or subscription_data.get("billing_frequency")
            or "monthly"
        )  # Default for description generation only

        return product_id, client_email, name, billing_frequency_hint

    def _validate_simple_required_parameters(self, product_id: str, client_email: str):
        """Validate required parameters for simple subscription creation."""
        if not product_id:
            raise create_structured_missing_parameter_error(
                parameter_name="product_id",
                action="create simple subscription",
                examples={
                    "format_1_direct": "action='create_simple', product_id='prod_123', clientEmailAddress='user@company.com'",
                    "format_2_data": "action='create_simple', subscription_data={'product_id': 'prod_123', 'clientEmailAddress': 'user@company.com'}",
                    "optional_params": "type='monthly' (or 'annual', 'trial'), name='Custom Name'",
                    "example_ids": ["prod_123", "product_456", "plan_789"],
                    "billing_safety": "🔒 BILLING SAFETY: Product ID is required to prevent billing errors and ensure correct subscription setup",
                },
            )

        if not client_email:
            raise create_structured_missing_parameter_error(
                parameter_name="clientEmailAddress",
                action="create simple subscription",
                examples={
                    "format_1": "clientEmailAddress='user@company.com'",
                    "format_2": "subscription_data={'clientEmailAddress': 'user@company.com'}",
                    "valid_format": "Email address of the customer for billing",
                    "example_emails": [
                        "user@company.com",
                        "customer@domain.com",
                        "billing@organization.com",
                    ],
                    "billing_safety": "🔒 BILLING SAFETY: Customer email is required for billing notifications and subscription management",
                },
            )

    async def _validate_simple_product(self, product_id: str):
        """Validate product existence and availability for simple subscription."""
        try:
            product = await self.client.get_product_by_id(product_id)
            if not product:
                raise create_structured_validation_error(
                    message=f"Product '{product_id}' does not exist",
                    field="product_id",
                    value=product_id,
                    suggestions=[
                        "Use manage_products with action='list' to see available products",
                        "Create the product first using manage_products with action='create_simple'",
                        "Verify the product_id is correct",
                        "Check for typos in the product ID",
                    ],
                    examples={
                        "discovery": "manage_products(action='list')",
                        "creation": "manage_products(action='create_simple', product_data={...})",
                        "verification": "manage_products(action='get', product_id='prod_123')",
                        "billing_safety": "🔒 BILLING SAFETY: Product must exist before creating subscriptions to prevent billing errors",
                    },
                )

            # Check if product is published and available for subscriptions
            if not product.get("published", False):
                raise create_structured_validation_error(
                    message=f"Product '{product_id}' is not published",
                    field="product_published",
                    value=product.get("published", False),
                    suggestions=[
                        "Publish the product first using manage_products with action='update'",
                        "Set published: true in the product configuration",
                        "Verify the product is ready for subscription creation",
                        "Check product status and configuration",
                    ],
                    examples={
                        "product_status": f"{product.get('name', 'Unknown')} (unpublished)",
                        "publish_command": "manage_products(action='update', product_id='prod_123', product_data={'published': True})",
                        "verification": "manage_products(action='get', product_id='prod_123')",
                        "billing_safety": "🔒 BILLING SAFETY: Only published products can be used for subscriptions to prevent billing errors",
                    },
                )

        except ReveniumAPIError:
            logger.warning(f"Could not validate product existence for {product_id}")
            # Continue with creation but add a warning in the response

    def _build_simple_subscription_config(
        self, product_id: str, client_email: str, name: str, billing_frequency_hint: str
    ) -> Dict[str, Any]:
        """Build subscription configuration for simple subscription creation."""
        # Apply smart defaults based on billing frequency hint
        if not name:
            name = f"{billing_frequency_hint.title()} Subscription"

        # Build subscription configuration with smart defaults
        subscription_config = {
            "productId": product_id,  # API expects productId, not product_id
            "clientEmailAddress": client_email,  # API expects clientEmailAddress
            "name": name,
            "description": f"{billing_frequency_hint.title()} subscription created via create_simple",
            "billing_address": {
                "street": "123 Default St",
                "city": "Default City",
                "state": "CA",
                "postal_code": "90210",
                "country": "US",
            },
            "metadata": {
                "created_via": "create_simple",
                "billing_frequency_hint": billing_frequency_hint,  # Descriptive metadata only
                "client_email": client_email,
            },
        }

        # Add required fields from client environment
        subscription_config["teamId"] = self.client.team_id
        owner_id = get_config_value("REVENIUM_OWNER_ID")
        if owner_id:
            subscription_config["ownerId"] = owner_id
        else:
            # Skip ownerId if not available - let API handle default
            logger.warning(
                "REVENIUM_OWNER_ID not available from configuration store, API will use default owner"
            )

        return subscription_config

    async def create_from_text(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create subscription from natural language description with enhanced safety."""
        text = self._validate_text_input(arguments)
        extracted_info = await self._analyze_subscription_text(text)

        # Extract and validate required parameters
        product_id, client_email = self._extract_and_validate_parameters(arguments, extracted_info)

        # Validate product before proceeding
        validation_result = await self._validate_product_safety(product_id)

        # Build and create subscription
        subscription_config = self._build_text_subscription_config(
            product_id, client_email, text, extracted_info
        )

        # Create subscription and add safety confirmation
        result = await self._create_subscription_with_safety_log(
            subscription_config, product_id, client_email
        )

        # Add safety confirmation to result
        result["safety_confirmation"] = {
            "product_validated": True,
            "client_email_confirmed": True,
            "billing_implications_acknowledged": True,
            "product_name": validation_result.get("product_name"),
            "warning": "⚠️ This subscription will result in billing charges to the customer",
        }

        return result

    def _validate_text_input(self, arguments: Dict[str, Any]) -> str:
        """Validate text input parameter for create_from_text."""
        text = arguments.get("text", "")
        if not text:
            raise create_structured_missing_parameter_error(
                parameter_name="text",
                action="create subscription from natural language",
                examples={
                    "usage": "create_from_text(text='Create monthly subscription for product ABC for customer@company.com')",
                    "valid_format": "Natural language description including product and customer information",
                    "example_descriptions": [
                        "Create monthly subscription for product ABC for customer@company.com",
                        "Set up annual billing for premium plan for user@domain.com",
                        "Subscribe customer@email.com to basic plan with monthly billing",
                    ],
                    "billing_safety": "🔒 BILLING SAFETY: Natural language subscription creation initiates billing - ensure description is clear and accurate",
                },
            )
        return text

    def _extract_and_validate_parameters(
        self, arguments: Dict[str, Any], extracted_info: Dict[str, Any]
    ) -> tuple:
        """Extract and validate product_id and client_email with safety checks."""
        # Check for explicit product_id and clientEmailAddress in arguments
        explicit_product_id = arguments.get("product_id")
        explicit_client_email = arguments.get("clientEmailAddress")

        # Determine product_id with safety checks
        product_id = None
        if explicit_product_id:
            product_id = explicit_product_id
        elif extracted_info.get("product_id"):
            product_id = extracted_info["product_id"]
        else:
            self._raise_product_safety_error()

        # Determine client email with safety checks
        client_email = None
        if explicit_client_email:
            client_email = explicit_client_email
        elif extracted_info.get("clientEmailAddress"):
            client_email = extracted_info["clientEmailAddress"]
        else:
            self._raise_client_email_safety_error()

        return product_id, client_email

    def _raise_product_safety_error(self):
        """Raise safety error for missing product specification."""
        raise ToolError(
            message="🚨 BILLING SAFETY ERROR: Cannot create subscription without explicit product specification",
            error_code=ErrorCodes.VALIDATION_ERROR,
            field="product_specification",
            value="missing",
            suggestions=[
                "You must specify a product_id to prevent billing errors",
                "Use discover_products() to see available products",
                "Use validate_product_for_subscription(product_id='...') to verify product",
                "Specify product_id explicitly: create_from_text(text='...', product_id='prod_123')",
            ],
            examples={
                "discovery": "discover_products()",
                "validation": "validate_product_for_subscription(product_id='prod_123')",
                "explicit_usage": "create_from_text(text='Monthly subscription for customer@company.com', product_id='prod_123')",
                "billing_safety": "🔒 BILLING SAFETY: Product selection directly affects customer billing and charges",
            },
        )

    def _raise_client_email_safety_error(self):
        """Raise safety error for missing client email specification."""
        raise ToolError(
            message="🚨 BILLING SAFETY ERROR: Cannot create subscription without explicit client email",
            error_code=ErrorCodes.VALIDATION_ERROR,
            field="clientEmailAddress_specification",
            value="missing",
            suggestions=[
                "You must specify a clientEmailAddress to prevent billing errors",
                "Specify clientEmailAddress explicitly: create_from_text(text='...', clientEmailAddress='user@company.com')",
                "Ensure the email belongs to the intended customer",
                "Verify the customer email is correct before proceeding",
            ],
            examples={
                "explicit_usage": "create_from_text(text='Monthly subscription', clientEmailAddress='user@company.com')",
                "verification": "Double-check client email for accuracy",
                "billing_safety": "🔒 BILLING SAFETY: Client email determines who gets billed for the subscription",
            },
        )

    async def _validate_product_safety(self, product_id: str) -> Dict[str, Any]:
        """Validate product before proceeding with subscription creation."""
        validation_result = await self.validate_product_for_subscription({"product_id": product_id})
        if not validation_result.get("valid"):
            raise create_structured_validation_error(
                message=f"🚨 PRODUCT VALIDATION ERROR: {validation_result.get('error')}",
                field="product_validation",
                value=product_id,
                suggestions=[
                    validation_result.get("recommendation", "Check product configuration"),
                    "Use discover_products() to find valid products",
                    "Verify the product is published and available for subscriptions",
                    "Check product configuration and status",
                ],
                examples={
                    "product_id": product_id,
                    "discovery": "discover_products()",
                    "validation": "validate_product_for_subscription(product_id='prod_123')",
                    "billing_safety": "🔒 BILLING SAFETY: Product validation prevents billing errors with invalid products",
                },
            )
        return validation_result

    def _build_text_subscription_config(
        self, product_id: str, client_email: str, text: str, extracted_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build subscription configuration from text analysis."""
        subscription_name = (
            extracted_info.get("subscription_name") or f"Subscription: {text[:50]}..."
        )

        subscription_config = {
            "productId": product_id,
            "clientEmailAddress": client_email,
            "name": subscription_name,
            "description": f"Subscription created from natural language: {text}",
            "billing_address": {
                "street": "123 Default St",
                "city": "Default City",
                "state": "CA",
                "postal_code": "90210",
                "country": "US",
            },
            "metadata": {
                "created_via": "create_from_text_enhanced",
                "original_text": text,
                "product_validation": "passed",
                "safety_checks": "completed",
                "extracted_info": extracted_info,
            },
        }

        # Add required fields from client environment
        subscription_config["teamId"] = self.client.team_id
        owner_id = get_config_value("REVENIUM_OWNER_ID")
        if owner_id:
            subscription_config["ownerId"] = owner_id
        else:
            # Skip ownerId if not available - let API handle default
            logger.warning(
                "REVENIUM_OWNER_ID not available from configuration store, API will use default owner"
            )

        return subscription_config

    async def _create_subscription_with_safety_log(
        self, subscription_config: Dict[str, Any], product_id: str, client_email: str
    ) -> Dict[str, Any]:
        """Create subscription with safety logging."""
        logger.info(
            f"SAFE SUBSCRIPTION CREATION: product_id={product_id}, client_email={client_email}"
        )
        return await self.client.create_subscription(subscription_config)

    async def _analyze_subscription_text(self, text: str) -> Dict[str, Any]:
        """Analyze natural language text to extract subscription information.

        Note: This function maps natural language terms to internal analysis results.
        These results are NOT direct API field values and should not be used as such.
        """
        text_lower = text.lower()

        # Simple keyword-based analysis (in production, would use NLP/LLM)
        # NOTE: These are internal analysis results, NOT API field values
        analysis = {
            "billing_frequency_hint": "monthly",  # Internal hint for description generation
            "subscription_name": None,
            "product_id": None,  # Never assume - must be explicit
            "clientEmailAddress": None,  # Never assume - must be explicit
            "suggested_billing_period": None,  # Maps to product plan billing period
            "features_mentioned": [],
            "subscription_category": "standard",  # For description purposes only
        }

        # Detect billing frequency hints (for description generation only)
        if any(word in text_lower for word in ["annual", "yearly", "year"]):
            analysis["billing_frequency_hint"] = "annual"
            analysis["suggested_billing_period"] = "YEAR"  # Proper API enum value
        elif any(word in text_lower for word in ["quarterly", "quarter"]):
            analysis["billing_frequency_hint"] = "quarterly"
            analysis["suggested_billing_period"] = "QUARTER"  # Proper API enum value
        elif any(word in text_lower for word in ["trial", "free"]):
            analysis["billing_frequency_hint"] = "trial"
            analysis["subscription_category"] = "trial"
            # Trial subscriptions use product trial_period configuration
        elif any(word in text_lower for word in ["monthly", "month"]):
            analysis["billing_frequency_hint"] = "monthly"
            analysis["suggested_billing_period"] = "MONTH"  # Proper API enum value

        # Detect feature keywords
        feature_keywords = ["premium", "enterprise", "basic", "pro", "standard", "advanced"]
        for keyword in feature_keywords:
            if keyword in text_lower:
                analysis["features_mentioned"].append(keyword)

        # Generate subscription name based on analysis
        if analysis["features_mentioned"]:
            feature_str = " ".join(analysis["features_mentioned"]).title()
            analysis["subscription_name"] = (
                f"{feature_str} {analysis['billing_frequency_hint'].title()} Subscription"
            )
        else:
            analysis["subscription_name"] = (
                f"{analysis['billing_frequency_hint'].title()} Subscription"
            )

        # IMPORTANT: Never extract product_id or clientEmailAddress from text
        # These must be explicitly provided to prevent billing errors

        return analysis


class SubscriptionValidator:
    """Internal manager for subscription validation and schema discovery with UCM integration."""

    def __init__(self, ucm_integration_helper=None) -> None:
        """Initialize subscription validator.

        Args:
            ucm_integration_helper: UCM integration helper for capability management
        """
        self.ucm_helper = ucm_integration_helper

        try:
            from ..schema_discovery import SubscriptionSchemaDiscovery

            self.schema_discovery = SubscriptionSchemaDiscovery()
        except ImportError:
            logger.warning("SubscriptionSchemaDiscovery not available, using fallback")
            self.schema_discovery = None

    async def get_capabilities(self) -> Dict[str, Any]:
        """Get subscription capabilities using UCM or fallback."""
        if self.ucm_helper:
            try:
                return await self.ucm_helper.ucm.get_capabilities("subscriptions")
            except ToolError:

                # Re-raise ToolError exceptions without modification

                # This preserves helpful error messages with specific suggestions

                raise

            except ToolError:

                # Re-raise ToolError exceptions without modification

                # This preserves helpful error messages with specific suggestions

                raise

            except ToolError:
                # Re-raise ToolError exceptions without modification
                # This preserves helpful error messages with specific suggestions
                raise
            except Exception as e:
                logger.error(f"UCM capabilities failed: {e}")
                raise ToolError(
                    message="Subscription capabilities unavailable - UCM service error",
                    error_code=ErrorCodes.UCM_ERROR,
                    field="ucm_service",
                    value="error",
                    suggestions=[
                        "Ensure UCM integration is working properly",
                        "Check UCM service connectivity and authentication",
                        "Verify UCM configuration is correct",
                        "Try again after UCM service is restored",
                    ],
                    examples={
                        "troubleshooting": [
                            "Check UCM service status",
                            "Verify authentication",
                            "Test connectivity",
                        ],
                        "alternative": "Use static capabilities if UCM is temporarily unavailable",
                        "billing_safety": "🔒 BILLING SAFETY: UCM provides real-time subscription capabilities",
                    },
                )

        # No fallbacks - force proper UCM integration
        raise ToolError(
            message="Subscription capabilities unavailable - no UCM integration",
            error_code=ErrorCodes.UCM_ERROR,
            field="ucm_helper",
            value="missing",
            suggestions=[
                "Ensure subscription management is initialized with UCM integration",
                "Check that UCM helper is properly configured",
                "Verify UCM integration is enabled in the system",
                "Contact system administrator to enable UCM integration",
            ],
            examples={
                "initialization": "SubscriptionManagement should be initialized with ucm_helper",
                "configuration": "Check UCM integration configuration",
                "billing_safety": "🔒 BILLING SAFETY: UCM integration provides real-time subscription capabilities",
            },
        )

    def get_examples(self, example_type: Optional[str] = None) -> Dict[str, Any]:
        """Get subscription examples with fallback support."""
        # Define fallback examples with proper subscription structure
        fallback_examples = {
            "monthly": {
                "name": "Monthly Subscription",
                "example_type": "monthly_billing",  # This is example metadata, not an API field
                "description": "Standard monthly billing subscription",
                "use_case": "Regular monthly billing for ongoing service",
                "note": "⚠️ REQUIRED: productId and clientEmailAddress are required fields - use discover_products() to find valid product IDs",
                "template": {
                    "productId": "prod_123",  # API expects productId
                    "clientEmailAddress": "customer@company.com",  # API expects clientEmailAddress
                    "name": "Monthly Subscription",
                    "description": "Monthly subscription with standard billing",
                    "billing_address": {
                        "street": "123 Main St",
                        "city": "San Francisco",
                        "state": "CA",
                        "postal_code": "94105",
                        "country": "US",
                    },
                    "metadata": {
                        "billing_frequency": "monthly",  # Descriptive metadata only
                        "example_type": "standard_monthly",
                    },
                },
            },
            "trial": {
                "name": "Trial Subscription",
                "example_type": "trial_period",  # This is example metadata, not an API field
                "description": "Trial subscription with automatic conversion",
                "use_case": "Allow customers to try service before committing",
                "note": "✅ TRIAL: trial_end_date field enables trial periods - use validate_product_for_subscription() to ensure product supports trials",
                "template": {
                    "productId": "prod_123",  # API expects productId
                    "clientEmailAddress": "customer@company.com",  # API expects clientEmailAddress
                    "name": "Trial Subscription",
                    "description": "Trial subscription with 14-day trial period",
                    "trial_end_date": "2024-12-31T23:59:59Z",  # Proper API field
                    "billing_address": {
                        "street": "123 Main St",
                        "city": "San Francisco",
                        "state": "CA",
                        "postal_code": "94105",
                        "country": "US",
                    },
                    "metadata": {
                        "subscription_category": "trial",  # Descriptive metadata only
                        "example_type": "trial_period",
                    },
                },
            },
        }

        # Try schema discovery first if available
        if self.schema_discovery:
            try:
                schema_examples = self.schema_discovery.get_subscription_examples(example_type)
                # Check if schema discovery returned meaningful examples
                if (
                    schema_examples
                    and schema_examples.get("examples")
                    and len(schema_examples["examples"]) > 0
                ):
                    return schema_examples
                # If schema discovery returns empty, fall back to static examples
                logger.info("Schema discovery returned empty examples, using fallback")
            except Exception as e:
                logger.warning(f"Schema discovery failed, using fallback examples: {e}")

        # Use fallback examples
        if example_type and example_type in fallback_examples:
            return {"examples": [fallback_examples[example_type]]}

        return {"examples": list(fallback_examples.values())}

    async def validate_configuration(
        self, subscription_data: Dict[str, Any], dry_run: bool = True
    ) -> Dict[str, Any]:
        """Validate subscription configuration using UCM-only validation."""
        if not self.schema_discovery:
            # No fallbacks - force proper UCM integration
            raise ToolError(
                message="Subscription validation unavailable - no schema discovery integration",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="schema_discovery",
                value="missing",
                suggestions=[
                    "Ensure subscription management is initialized with proper schema discovery",
                    "Check that schema discovery integration is enabled",
                    "Verify schema discovery configuration is correct",
                    "Use subscription management validation to check your configuration",
                ],
                examples={
                    "initialization": "SubscriptionManagement should be initialized with schema discovery",
                    "validation_commands": "Get validation rules: manage_subscriptions(action='get_capabilities')",
                    "validate_config": "Validate configuration: manage_subscriptions(action='validate', subscription_data={...}, dry_run=True)",
                    "billing_safety": "🔒 BILLING SAFETY: Schema discovery provides validation to prevent billing errors",
                },
            )

        return self.schema_discovery.validate_subscription_configuration(subscription_data, dry_run)


class SubscriptionAnalytics:
    """Internal processor for subscription analytics and metrics."""

    def __init__(self, client: ReveniumClient) -> None:
        """Initialize analytics processor."""
        self.client = client

    async def get_metrics(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get subscription metrics and analytics."""
        page = arguments.get("page", 0)
        size = arguments.get("size", 100)  # Get more for analysis
        filters = arguments.get("filters", {})

        response = await self.client.get_subscriptions(page=page, size=size, **filters)
        subscriptions = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)

        total_subscriptions = page_info.get("totalElements", len(subscriptions))
        active_subscriptions = len([s for s in subscriptions if s.get("status") == "active"])
        trial_subscriptions = len([s for s in subscriptions if s.get("status") == "trial"])
        cancelled_subscriptions = len([s for s in subscriptions if s.get("status") == "cancelled"])

        # Calculate revenue metrics (placeholder - would need actual billing data)
        monthly_subscriptions = len(
            [s for s in subscriptions if s.get("billing_period") == "monthly"]
        )
        yearly_subscriptions = len(
            [s for s in subscriptions if s.get("billing_period") == "yearly"]
        )

        metrics = {
            "total_subscriptions": total_subscriptions,
            "active_subscriptions": active_subscriptions,
            "trial_subscriptions": trial_subscriptions,
            "cancelled_subscriptions": cancelled_subscriptions,
            "conversion_rate": (
                (active_subscriptions / total_subscriptions * 100) if total_subscriptions > 0 else 0
            ),
            "trial_rate": (
                (trial_subscriptions / total_subscriptions * 100) if total_subscriptions > 0 else 0
            ),
            "churn_rate": (
                (cancelled_subscriptions / total_subscriptions * 100)
                if total_subscriptions > 0
                else 0
            ),
            "billing_distribution": {
                "monthly": monthly_subscriptions,
                "yearly": yearly_subscriptions,
                "other": total_subscriptions - monthly_subscriptions - yearly_subscriptions,
            },
            "sample_size": len(subscriptions),
            "products_represented": len(
                set(s.get("product_id") for s in subscriptions if s.get("product_id"))
            ),
        }

        return metrics


class SubscriptionHierarchyManager:
    """Manager for subscription hierarchy operations using the hierarchy services."""

    def __init__(self, client: ReveniumClient) -> None:
        """Initialize hierarchy manager with client."""
        self.client = client
        self.formatter = UnifiedResponseFormatter("manage_subscriptions")
        self.navigation_service = hierarchy_navigation_service
        self.lookup_service = entity_lookup_service
        self.validator = cross_tier_validator

    async def get_product_details(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get product details for a given subscription."""
        subscription_id = arguments.get("subscription_id")
        if not subscription_id:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_id",
                action="get product details for subscription",
                examples={
                    "usage": "get_product_details(subscription_id='sub_123')",
                    "valid_format": "Subscription ID should be a string identifier",
                    "example_ids": ["sub_123", "subscription_456", "billing_789"],
                    "hierarchy_context": "🔗 HIERARCHY: Find the product configuration used by this subscription",
                },
            )

        # Use hierarchy navigation service to find the product
        navigation_result = await self.navigation_service.get_product_for_subscription(
            subscription_id
        )

        if not navigation_result.success:
            raise ToolError(
                message=f"Failed to get product for subscription {subscription_id}: {navigation_result.error_message}",
                error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                field="subscription_id",
                value=subscription_id,
                suggestions=[
                    "Verify the subscription ID exists using get(subscription_id='...')",
                    "Use list() to see all available subscriptions",
                    "Check if the subscription has a valid product association",
                ],
            )

        return {
            "action": "get_product_details",
            "subscription_id": subscription_id,
            "data": (
                navigation_result.related_entities[0] if navigation_result.related_entities else {}
            ),
            "navigation_path": navigation_result.navigation_path,
            "metadata": {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.%f"),
                "hierarchy_level": "subscriptions → products",
                "product_found": len(navigation_result.related_entities) > 0,
            },
        }

    async def get_credentials(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get all credentials for a given subscription."""
        subscription_id = arguments.get("subscription_id")
        if not subscription_id:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_id",
                action="get credentials for subscription",
                examples={
                    "usage": "get_credentials(subscription_id='sub_123')",
                    "valid_format": "Subscription ID should be a string identifier",
                    "example_ids": ["sub_123", "subscription_456", "billing_789"],
                    "hierarchy_context": "🔗 HIERARCHY: Find all credentials associated with this subscription",
                },
            )

        # Use hierarchy navigation service to find credentials
        navigation_result = await self.navigation_service.get_credentials_for_subscription(
            subscription_id
        )

        if not navigation_result.success:
            raise ToolError(
                message=f"Failed to get credentials for subscription {subscription_id}: {navigation_result.error_message}",
                error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                field="subscription_id",
                value=subscription_id,
                suggestions=[
                    "Verify the subscription ID exists using get(subscription_id='...')",
                    "Use list() to see all available subscriptions",
                    "Check if the subscription has any credentials created",
                ],
            )

        return {
            "action": "get_credentials",
            "subscription_id": subscription_id,
            "data": navigation_result.related_entities,
            "navigation_path": navigation_result.navigation_path,
            "metadata": {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.%f"),
                "hierarchy_level": "subscriptions → credentials",
                "total_credentials": len(navigation_result.related_entities),
            },
        }

    async def create_with_credentials(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create a subscription and credentials together in a coordinated workflow."""
        # Extract and validate input data
        subscription_data, credentials_data = self._extract_credentials_data(arguments)

        # Validate hierarchy operation
        await self._validate_credentials_hierarchy(subscription_data, credentials_data)

        # Prepare subscription data for creation
        self._prepare_credentials_subscription_data(subscription_data, arguments)

        # Create subscription and credentials in sequence
        subscription_result, credentials_result = await self._create_subscription_and_credentials(
            subscription_data, credentials_data
        )

        # Build and return coordinated response
        return self._build_credentials_response(subscription_result, credentials_result)

    def _extract_credentials_data(self, arguments: Dict[str, Any]) -> tuple:
        """Extract and validate required data for credentials creation."""
        subscription_data = arguments.get("subscription_data")
        credentials_data = arguments.get("credentials_data")

        if not subscription_data:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_data",
                action="create subscription with credentials",
                examples={
                    "usage": "create_with_credentials(subscription_data={...}, credentials_data={...})",
                    "required_fields": ["subscription_data", "credentials_data"],
                    "hierarchy_context": "🔗 HIERARCHY: Creates subscription and credentials together with proper linking",
                },
            )

        if not credentials_data:
            raise create_structured_missing_parameter_error(
                parameter_name="credentials_data",
                action="create subscription with credentials",
                examples={
                    "usage": "create_with_credentials(subscription_data={...}, credentials_data={...})",
                    "required_fields": ["subscription_data", "credentials_data"],
                    "hierarchy_context": "🔗 HIERARCHY: Creates subscription and credentials together with proper linking",
                },
            )

        return subscription_data, credentials_data

    async def _validate_credentials_hierarchy(
        self, subscription_data: Dict[str, Any], credentials_data: Dict[str, Any]
    ):
        """Validate the hierarchy operation for credentials creation."""
        validation_result = await self.validator.validate_hierarchy_operation(
            {
                "type": "create",
                "entity_type": "subscriptions",
                "entity_data": subscription_data,
                "related_operations": [
                    {
                        "type": "create",
                        "entity_type": "credentials",
                        "entity_data": credentials_data,
                    }
                ],
            }
        )

        if not validation_result.valid:
            raise ToolError(
                message=f"Hierarchy validation failed: {'; '.join([issue.message for issue in validation_result.issues])}",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="hierarchy_validation",
                value="failed",
                suggestions=[
                    "Check that subscription_data contains all required fields",
                    "Verify credentials_data is properly formatted",
                    "Ensure no conflicting data between subscription and credentials",
                ],
            )

    def _prepare_credentials_subscription_data(
        self, subscription_data: Dict[str, Any], arguments: Dict[str, Any]
    ):
        """Prepare subscription data for credentials creation."""
        # Apply field mapping for subscription data
        if "productId" not in subscription_data and "product_id" in subscription_data:
            subscription_data["productId"] = subscription_data["product_id"]

        # Handle email parameter mapping
        if "clientEmailAddress" not in subscription_data and arguments.get("clientEmailAddress"):
            subscription_data["clientEmailAddress"] = arguments["clientEmailAddress"]

        # Add required fields from client environment
        if "teamId" not in subscription_data:
            subscription_data["teamId"] = self.client.team_id
        if "ownerId" not in subscription_data:
            owner_id = get_config_value("REVENIUM_OWNER_ID")
            if owner_id:
                subscription_data["ownerId"] = owner_id
            else:
                # Skip ownerId if not available - let API handle default
                logger.warning(
                    "REVENIUM_OWNER_ID not available from configuration store, API will use default owner"
                )

    async def _create_subscription_and_credentials(
        self, subscription_data: Dict[str, Any], credentials_data: Dict[str, Any]
    ) -> tuple:
        """Create subscription and credentials in coordinated sequence."""
        # Create subscription first
        logger.info(
            f"Creating subscription for customer: {subscription_data.get('clientEmailAddress')}"
        )
        subscription_result = await self.client.create_subscription(subscription_data)
        subscription_id = subscription_result.get("id")

        if not subscription_id:
            raise ToolError(
                message="Subscription creation succeeded but no ID returned",
                error_code=ErrorCodes.API_ERROR,
                field="subscription_creation",
                value="no_id",
            )

        # Link the credentials to the subscription (API expects subscriptionIds array)
        credentials_data["subscriptionIds"] = [subscription_id]

        # Create credentials
        logger.info(f"Creating credentials for subscription {subscription_id}")
        credentials_result = await self.client.create_credential(credentials_data)

        return subscription_result, credentials_result

    def _build_credentials_response(
        self,
        subscription_result: Dict[str, Any],
        credentials_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build coordinated response for credentials creation."""
        return {
            "action": "create_with_credentials",
            "data": {
                "subscription": subscription_result,
                "credentials": credentials_result,
                "hierarchy_link": {
                    "subscription_id": subscription_result.get("id"),
                    "credentials_id": credentials_result.get("id"),
                    "relationship": "subscription → credentials",
                },
            },
            "metadata": {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.%f"),
                "hierarchy_level": "subscriptions + credentials",
                "operation_type": "coordinated_creation",
            },
        }


class SubscriptionManagement(ToolBase):
    """Consolidated subscription management tool with internal composition."""

    tool_name = "manage_subscriptions"
    tool_description = "Subscription management connecting customers to products. Key actions: list, create, update, delete, search. Use get_capabilities() for complete action list."
    business_category = "Core Business Management Tools"
    tool_type = ToolType.CRUD
    tool_version = "2.0.0"

    def __init__(self, ucm_helper=None) -> None:
        """Initialize consolidated subscription management.

        Args:
            ucm_helper: UCM integration helper for capability management
        """
        super().__init__(ucm_helper)
        self.formatter = UnifiedResponseFormatter("manage_subscriptions")
        self.validator = SubscriptionValidator(ucm_helper)

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle subscription management actions with intelligent routing."""
        try:
            # Get client and initialize managers
            client = await self.get_client()
            subscription_manager = SubscriptionManager(client)
            analytics_processor = SubscriptionAnalytics(client)
            hierarchy_manager = SubscriptionHierarchyManager(client)

            # Handle introspection actions
            if action == "get_tool_metadata":
                metadata = await self.get_tool_metadata()
                return [TextContent(type="text", text=json.dumps(metadata.to_dict(), indent=2))]

            # Route to appropriate handler based on action category
            if action in ["list", "get", "create", "update", "cancel", "delete"]:
                return await self._handle_crud_actions(action, arguments, subscription_manager)
            elif action in ["discover_products", "validate_product_for_subscription"]:
                return await self._handle_creation_actions(action, arguments, subscription_manager)
            elif action in [
                "get_metrics",
                "get_supporting_data",
                "search_subscriptions",
                "subscription_nlp",
            ]:
                return await self._handle_analytics_actions(
                    action, arguments, subscription_manager, analytics_processor
                )
            elif action in ["get_capabilities", "get_examples", "validate", "get_agent_summary"]:
                return await self._handle_discovery_actions(action, arguments)
            elif action in ["get_product_details", "get_credentials", "create_with_credentials"]:
                return await self._handle_hierarchy_actions(action, arguments, hierarchy_manager)
            else:
                return self._handle_unknown_action(action)

        except ValidationError as e:
            logger.error(f"Validation error in manage_subscriptions: {e}")
            raise e
        except ReveniumAPIError as e:
            logger.error(f"Revenium API error in manage_subscriptions: {e}")
            raise e
        except Exception as e:
            logger.error(f"Unexpected error in manage_subscriptions: {e}")
            raise e

    async def _handle_crud_actions(
        self, action: str, arguments: Dict[str, Any], subscription_manager
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle basic CRUD actions for subscriptions."""
        if action == "list":
            result = await subscription_manager.list_subscriptions(arguments)
            return [
                TextContent(
                    type="text",
                    text=f"Found {result['total_found']} subscriptions (page {arguments.get('page', 0) + 1}):\n\n"
                    + json.dumps(result, indent=2),
                )
            ]
        elif action == "get":
            result = await subscription_manager.get_subscription(arguments)
            subscription_id = arguments.get("subscription_id")
            return [
                TextContent(
                    type="text",
                    text=f"Subscription details for ID {subscription_id}:\n\n"
                    + json.dumps(result, indent=2),
                )
            ]
        elif action == "create":
            # Unified creation action with progressive complexity support
            subscription_data = arguments.get("subscription_data", {})
            auto_generate = arguments.get("auto_generate", True)  # Default to Context7 simple mode
            dry_run = arguments.get("dry_run", False)

            # Auto-generation mode: Fill in missing required fields with smart defaults
            if auto_generate:
                name = subscription_data.get("name")
                if not name:
                    return [
                        TextContent(
                            type="text",
                            text="**Missing Required Field**\n\n"
                            "**Field**: `name` (required for all subscription creation)\n\n"
                            '**Example**: `{"action":"create","subscription_data":{"name":"Monthly Subscription"}}`\n\n'
                            "**Auto-Generation**: Enabled (will auto-generate product_id from available products, clientEmailAddress from defaults)",
                        )
                    ]

                # Apply smart auto-generation logic
                enhanced_subscription_data = {
                    "name": name,
                    "description": subscription_data.get("description")
                    or f"Subscription for {name}",
                }

                # Auto-generate product_id if not provided
                if not subscription_data.get("product_id") and not subscription_data.get(
                    "productId"
                ):
                    # Try to find a default or first available product
                    try:
                        products_result = await subscription_manager.client.get_paginated(
                            "products", page=0, size=1
                        )
                        if products_result and len(products_result) > 0:
                            enhanced_subscription_data["product_id"] = products_result[0]["id"]
                            logger.info(f"Auto-generated product_id: {products_result[0]['id']}")
                        else:
                            return [
                                TextContent(
                                    type="text",
                                    text="**Auto-Generation Failed**\n\n"
                                    f"**Issue**: No products available for auto-generation\n\n"
                                    f"**Solution**: Create a product first using `manage_products` or provide explicit product_id:\n"
                                    f"```json\n"
                                    f'{{"action":"create","subscription_data":{{"name":"{name}","product_id":"your_product_id"}}}}\n'
                                    f"```\n\n"
                                    f"**Tip**: Use `manage_products(action='list')` to see available products",
                                )
                            ]
                    except Exception as e:
                        logger.warning(f"Failed to auto-generate product_id: {e}")
                        return [
                            TextContent(
                                type="text",
                                text=f"**Auto-Generation Error**\n\n"
                                f"**Issue**: Could not auto-generate product_id\n\n"
                                f"**Solution**: Provide explicit product_id:\n"
                                f"```json\n"
                                f'{{"action":"create","subscription_data":{{"name":"{name}","product_id":"your_product_id"}}}}\n'
                                f"```",
                            )
                        ]
                else:
                    enhanced_subscription_data["product_id"] = subscription_data.get(
                        "product_id"
                    ) or subscription_data.get("productId")

                # Auto-generate clientEmailAddress if not provided
                if not subscription_data.get("clientEmailAddress"):
                    # Try to get from environment or use a test default
                    default_email = os.getenv("REVENIUM_DEFAULT_EMAIL")
                    if default_email:
                        enhanced_subscription_data["clientEmailAddress"] = default_email
                        logger.info(
                            f"Auto-generated clientEmailAddress from REVENIUM_DEFAULT_EMAIL: {default_email}"
                        )
                    else:
                        enhanced_subscription_data["clientEmailAddress"] = (
                            f"user-{int(time.time())}@example.com"
                        )
                        logger.info(
                            f"Auto-generated test clientEmailAddress: {enhanced_subscription_data['clientEmailAddress']}"
                        )
                else:
                    enhanced_subscription_data["clientEmailAddress"] = subscription_data[
                        "clientEmailAddress"
                    ]

                # Copy any other user-provided fields
                for key, value in subscription_data.items():
                    if key not in enhanced_subscription_data:
                        enhanced_subscription_data[key] = value

                # Update arguments with enhanced data
                arguments = arguments.copy()
                arguments["subscription_data"] = enhanced_subscription_data

                if dry_run:
                    mode_text = "AUTO-GENERATION"
                    return [
                        TextContent(
                            type="text",
                            text=f"**🔍 Dry Run Preview - {mode_text} Mode**\n\n"
                            f"**Subscription Data:**\n"
                            f"```json\n"
                            f"{json.dumps(enhanced_subscription_data, indent=2)}\n"
                            f"```\n\n"
                            f"**Auto-Generation:** Enabled\n"
                            f"**Auto-Generated Fields:** product_id, clientEmailAddress, description\n\n"
                            f"**Next Step:** Remove `dry_run: true` to create the subscription",
                        )
                    ]
            else:
                # Expert mode: strict validation, no auto-generation
                if not subscription_data.get("product_id") and not subscription_data.get(
                    "productId"
                ):
                    return [
                        TextContent(
                            type="text",
                            text=f"**Missing Required Field**\n\n"
                            f"**Field**: `product_id` (required in expert mode)\n\n"
                            f"**Solution**: Provide product_id explicitly:\n"
                            f"```json\n"
                            f'{{"action":"create","subscription_data":{{"name":"{subscription_data.get("name", "Subscription")}","product_id":"your_product_id","clientEmailAddress":"user@company.com"}},"auto_generate":false}}\n'
                            f"```\n\n"
                            f"**Tip**: Use `auto_generate=true` for smart defaults, or use `manage_products(action='list')` to find product IDs",
                        )
                    ]

                if not subscription_data.get("clientEmailAddress"):
                    return [
                        TextContent(
                            type="text",
                            text=f"**Missing Required Field**\n\n"
                            f"**Field**: `clientEmailAddress` (required in expert mode)\n\n"
                            f"**Solution**: Provide clientEmailAddress explicitly:\n"
                            f"```json\n"
                            f'{{"action":"create","subscription_data":{{"name":"{subscription_data.get("name", "Subscription")}","product_id":"{subscription_data.get("product_id", "your_product_id")}","clientEmailAddress":"user@company.com"}},"auto_generate":false}}\n'
                            f"```\n\n"
                            f"**Tip**: Use `auto_generate=true` for smart defaults",
                        )
                    ]

                if dry_run:
                    mode_text = "EXPLICIT CONFIGURATION"
                    return [
                        TextContent(
                            type="text",
                            text=f"**🔍 Dry Run Preview - {mode_text} Mode**\n\n"
                            f"**Subscription Data:**\n"
                            f"```json\n"
                            f"{json.dumps(subscription_data, indent=2)}\n"
                            f"```\n\n"
                            f"**Auto-Generation:** Disabled\n"
                            f"**Validation:** Strict (all required fields must be provided)\n\n"
                            f"**Next Step:** Remove `dry_run: true` to create the subscription",
                        )
                    ]

            # Proceed with actual creation
            result = await subscription_manager.create_subscription(arguments)
            mode_text = "with auto-generation" if auto_generate else "with explicit configuration"
            return [
                TextContent(
                    type="text",
                    text=f"**✅ Subscription Created Successfully** ({mode_text})\n\n"
                    + json.dumps(result, indent=2),
                )
            ]
        elif action == "update":
            result = await subscription_manager.update_subscription(arguments)
            subscription_id = arguments.get("subscription_id")
            return [
                TextContent(
                    type="text",
                    text=f"Subscription {subscription_id} updated successfully:\n\n"
                    + json.dumps(result, indent=2),
                )
            ]
        elif action == "cancel":
            result = await subscription_manager.cancel_subscription(arguments)
            subscription_id = arguments.get("subscription_id")
            return [
                TextContent(
                    type="text",
                    text=f"Subscription {subscription_id} cancelled successfully:\n\n"
                    + json.dumps(result, indent=2),
                )
            ]
        elif action == "delete":
            result = await subscription_manager.delete_subscription(arguments)
            subscription_id = arguments.get("subscription_id")
            return [
                TextContent(
                    type="text",
                    text=f"Subscription {subscription_id} deleted successfully:\n\n"
                    + json.dumps(result, indent=2),
                )
            ]

    async def _handle_creation_actions(
        self, action: str, arguments: Dict[str, Any], subscription_manager
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle subscription creation actions."""
        if action == "create_simple":
            result = await subscription_manager.create_simple(arguments)
            return [
                TextContent(
                    type="text",
                    text="Simple subscription created successfully:\n\n"
                    + json.dumps(result, indent=2),
                )
            ]
        elif action == "create_from_text":
            result = await subscription_manager.create_from_text(arguments)
            return [
                TextContent(
                    type="text",
                    text="🔒 **Safe Subscription Created from Text**\n\n"
                    + json.dumps(result, indent=2),
                )
            ]
        elif action == "discover_products":
            result = await subscription_manager.discover_products(arguments)
            return [
                TextContent(
                    type="text",
                    text="🔍 **Product Discovery Results**\n\n" + json.dumps(result, indent=2),
                )
            ]
        elif action == "validate_product_for_subscription":
            result = await subscription_manager.validate_product_for_subscription(arguments)
            return [
                TextContent(
                    type="text",
                    text="✅ **Product Validation Results**\n\n" + json.dumps(result, indent=2),
                )
            ]

    async def _handle_analytics_actions(
        self, action: str, arguments: Dict[str, Any], subscription_manager, analytics_processor
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle analytics and search actions."""
        if action == "get_metrics":
            result = await analytics_processor.get_metrics(arguments)
            return [
                TextContent(
                    type="text",
                    text="📊 **Subscription Metrics**\n\n" + json.dumps(result, indent=2),
                )
            ]
        elif action == "get_supporting_data":
            result = await subscription_manager.get_supporting_data(arguments)
            return [
                TextContent(
                    type="text", text="**Supporting Data**\n\n" + json.dumps(result, indent=2)
                )
            ]
        elif action == "search_subscriptions":
            result = await subscription_manager.search_subscriptions(arguments)
            return [
                TextContent(
                    type="text",
                    text="**Subscription Search Results**\n\n" + json.dumps(result, indent=2),
                )
            ]
        elif action == "subscription_nlp":
            result = await subscription_manager.subscription_nlp(arguments)
            return [
                TextContent(
                    type="text",
                    text="**Natural Language Processing Results**\n\n"
                    + json.dumps(result, indent=2),
                )
            ]

    async def _handle_discovery_actions(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle discovery and validation actions."""
        if action == "get_capabilities":
            return await self._handle_get_capabilities()
        elif action == "get_examples":
            examples = self.validator.get_examples(arguments.get("example_type"))
            return self._format_examples_response(examples)
        elif action == "validate":
            return await self._handle_validate_action(arguments)
        elif action == "get_agent_summary":
            return await self._handle_get_agent_summary()

    async def _handle_hierarchy_actions(
        self, action: str, arguments: Dict[str, Any], hierarchy_manager
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle hierarchy navigation actions."""
        if action == "get_product_details":
            result = await hierarchy_manager.get_product_details(arguments)
            return [
                TextContent(
                    type="text",
                    text=f"🔗 **Product Details for Subscription {result['subscription_id']}**\n\n"
                    + json.dumps(result, indent=2),
                )
            ]
        elif action == "get_credentials":
            result = await hierarchy_manager.get_credentials(arguments)
            return [
                TextContent(
                    type="text",
                    text=f"🔗 **Credentials for Subscription {result['subscription_id']}**\n\n"
                    + json.dumps(result, indent=2),
                )
            ]
        elif action == "create_with_credentials":
            result = await hierarchy_manager.create_with_credentials(arguments)
            return [
                TextContent(
                    type="text",
                    text="🔗 **Subscription and Credentials Created Successfully**\n\n"
                    + json.dumps(result, indent=2),
                )
            ]

    async def _handle_validate_action(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle subscription validation action."""
        subscription_data = arguments.get("subscription_data")
        if not subscription_data:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_data",
                action="validate subscription",
                examples={
                    "usage": "validate(subscription_data={'product_id': 'prod_123', 'clientEmailAddress': 'customer@company.com'})",
                    "required_fields": ["product_id", "clientEmailAddress"],
                    "example_data": {
                        "product_id": "prod_123",
                        "clientEmailAddress": "customer@company.com",
                        "billing_cycle": "monthly",
                    },
                    "billing_safety": "🔒 BILLING SAFETY: Subscription validation prevents billing errors - ensure all data is correct",
                    "field_descriptions": {
                        "clientEmailAddress": "Owner of the subscription who will receive invoices at this address if that option is selected for the subscription and product"
                    },
                },
            )

        dry_run = arguments.get("dry_run", True)
        result = await self.validator.validate_configuration(subscription_data, dry_run)
        return self._format_validation_response(result)

    def _handle_unknown_action(
        self, action: str
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle unknown action with structured error."""
        raise ToolError(
            message=f"Unknown action '{action}' is not supported",
            error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
            field="action",
            value=action,
            suggestions=[
                "🔒 BILLING SAFETY: Always start with discover_products() to find available products safely",
                "Use get_capabilities() to see all available actions and their requirements",
                "Check the action name for typos",
                "Use get_examples() to see working examples",
                "For subscription creation, use 'create' with auto-generation for simple subscriptions or auto_generate=false for expert mode",
            ],
            examples={
                "basic_actions": ["list", "get", "create", "update", "cancel", "delete"],
                "creation_actions": ["create"],
                "discovery_actions": [
                    "get_capabilities",
                    "get_examples",
                    "get_agent_summary",
                    "get_supporting_data",
                ],
                "search_actions": ["search_subscriptions", "subscription_nlp"],
                "validation_actions": [
                    "validate",
                    "discover_products",
                    "validate_product_for_subscription",
                ],
                "analytics_actions": ["get_metrics", "get_tool_metadata"],
                "hierarchy_actions": [
                    "get_product_details",
                    "get_credentials",
                    "create_with_credentials",
                ],
                "billing_safety_actions": {
                    "discover_products": "Find available products safely",
                    "validate_product_for_subscription": "Verify product before subscription creation",
                    "create_from_text": "Enhanced with billing safety checks",
                },
            },
        )

    async def _handle_get_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Enhanced capabilities with UCM integration and preserved semantic guidance."""
        # Get UCM capabilities if available for API-verified data
        ucm_capabilities = None
        if self.ucm_helper:
            try:
                logger.info(
                    "Subscription Management: UCM helper available, fetching capabilities..."
                )
                ucm_capabilities = await self.ucm_helper.ucm.get_capabilities("subscriptions")
                logger.info(
                    f"Subscription Management: Got UCM capabilities with {len(ucm_capabilities.get('billing_periods', []))} billing periods"
                )
            except ToolError:
                # Re-raise ToolError exceptions without modification
                # This preserves helpful error messages with specific suggestions
                raise
            except Exception as e:
                logger.warning(
                    f"Failed to get UCM subscription capabilities, using static data: {e}"
                )
        else:
            logger.info(
                "⚠️ Subscription Management: No UCM helper available, using static capabilities"
            )

        # Build enhanced capabilities with UCM data
        return [
            TextContent(
                type="text", text=await self._build_enhanced_capabilities_text(ucm_capabilities)
            )
        ]

    async def _build_enhanced_capabilities_text(
        self, ucm_capabilities: Optional[Dict[str, Any]]
    ) -> str:
        """Build enhanced capabilities text combining semantic guidance with UCM data."""
        text = """# **Subscription Management Capabilities**

## **🔧 Parameter Organization**

**Creation fields** must be nested in `subscription_data` container:
```json
{"action": "create", "subscription_data": {"name": "Monthly Subscription", "product_id": "prod_123", "clientEmailAddress": "user@company.com"}}
```

**Top-level parameters** for tool behavior:
- `action` - What operation to perform
- `subscription_id` - For get/update/delete operations
- `auto_generate` - Enable smart defaults (default: true)
- `dry_run` - Preview without creating (optional)
- `page`, `size` - For list operations

## **SUBSCRIPTION MANAGEMENT OVERVIEW**

### **What Subscriptions Are**
- **Customer billing relationships** that define ongoing payment arrangements
- **Product-customer connections** that activate service access and billing
- **Lifecycle entities** with states from trial through active to cancelled
- **Revenue generators** that drive recurring business income

### **Key Concepts**
- **Subscriptions** connect customers to products with billing terms
- **Billing Periods** define payment frequency (monthly, yearly, etc.)
- **Trial Periods** allow customers to test before committing
- **Lifecycle States** track subscription status and transitions

## **Quick Start Commands**

### **Discover Subscriptions**
```bash
list()                                          # View all subscriptions
get(subscription_id="sub_123")                 # Get specific subscription details
get_examples()                                 # See working templates
```

### **Create Subscriptions**
```bash
get_capabilities()                             # Understand requirements
validate(subscription_data={...}, dry_run=True) # Test before creating
create(subscription_data={...})               # Create the subscription
create(subscription_data={"name": "Monthly Subscription"}) # Quick creation with auto-generation
```

### **Manage Subscriptions**
```bash
update(subscription_id="sub_123", subscription_data={...}) # Update existing
cancel(subscription_id="sub_123")                         # Cancel subscription
get_metrics()                                             # Analyze performance
```

### **Hierarchy Navigation**
```bash
get_product_details(subscription_id="sub_123")           # Find product for subscription
get_credentials(subscription_id="sub_123")               # Find all related credentials
create_with_credentials(subscription_data={...}, credentials_data={...})  # Create linked entities
```"""

        # Add UCM-enhanced billing periods if available
        if ucm_capabilities and "billing_periods" in ucm_capabilities:
            text += "\n\n## **Billing Periods**\n"
            for period in ucm_capabilities["billing_periods"]:
                text += f"- **{period}**\n"
        else:
            # Fallback to basic billing periods
            text += "\n\n## **Billing Periods**\n"
            text += "- **MONTH**, **YEAR**, **QUARTER**\n"

        # Add UCM-enhanced trial periods if available
        if ucm_capabilities and "trial_periods" in ucm_capabilities:
            text += "\n\n## **Trial Periods**\n"
            for trial in ucm_capabilities["trial_periods"]:
                text += f"- **{trial}**\n"
        else:
            # Fallback to basic trial periods
            text += "\n\n## **Trial Periods**\n"
            text += "- **DAY**, **WEEK**, **MONTH**\n"

        # Add UCM-enhanced currencies if available
        if ucm_capabilities and "currencies" in ucm_capabilities:
            text += "\n\n## **Supported Currencies**\n"
            for currency in ucm_capabilities["currencies"]:
                text += f"- **{currency}**\n"
        else:
            # Fallback to basic currencies
            text += "\n\n## **Supported Currencies**\n"
            text += "- **USD**, **EUR**, **GBP**, **CAD**, **AUD**, **JPY**, **CNY**, **MXN**, **COP**, **ARS**, **ZMW**\n"

        # Add schema information
        schema = ucm_capabilities.get("schema", {}) if ucm_capabilities else {}
        subscription_schema = schema.get("subscription_data", {})

        text += "\n\n## **Required Fields**\n"
        required_fields = subscription_schema.get("required", ["product_id", "clientEmailAddress"])
        for field in required_fields:
            if field == "clientEmailAddress":
                text += f"- `{field}` (required) - Owner of the subscription who will receive invoices at this address\n"
            else:
                text += f"- `{field}` (required)\n"

        text += "\n\n## **Optional Fields**\n"
        optional_fields = subscription_schema.get(
            "optional",
            [
                "description",
                "start_date",
                "end_date",
                "billing_address",
                "payment_method",
                "trial_end_date",
                "metadata",
                "tags",
            ],
        )
        for field in optional_fields:
            text += f"- `{field}` (optional)\n"

        # Add lifecycle states
        lifecycle = ucm_capabilities.get("lifecycle_states", {}) if ucm_capabilities else {}
        text += "\n\n## **Lifecycle States**\n"

        creation_states = lifecycle.get("creation", ["trial", "active"])
        text += "### Creation States\n"
        for state in creation_states:
            text += f"- **{state}**\n"

        active_states = lifecycle.get("active_states", ["active", "trial"])
        text += "### Active States\n"
        for state in active_states:
            text += f"- **{state}**\n"

        terminal_states = lifecycle.get("terminal_states", ["cancelled", "expired"])
        text += "### Terminal States\n"
        for state in terminal_states:
            text += f"- **{state}**\n"

        # Add business rules
        text += """

## **Business Rules**
- Product must exist and be active before creating subscription
- Start date cannot be in the past (unless explicitly allowed)
- End date must be after start date if both are specified
- If end date is not specified, the subscription will renew on a recurring basis based on the product's billing period configuration
- Trial period is optional and depends on product configuration
- If no payment method is assigned, customers receive invoices and pay manually
- If payment method is linked to a Revenium stored payment method, customers will be charged automatically via credit card
    - IMPORTANT NOTE:  payment method integration is not currently supported in the MCP. This must be managed manually within the Revenium application.

## **Next Steps**
1. Use `get_examples(example_type='...')` to see working templates
2. Use `validate(subscription_data={...})` to test configurations
3. Use `create(subscription_data={...})` to create subscriptions"""

        return text

    def _format_capabilities_response(
        self, capabilities: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format capabilities response."""
        result_text = "# **Subscription Management Capabilities**\n\n"

        # CRITICAL: Parameter Organization (prevents agent confusion)
        result_text += "## **🔧 Parameter Organization** \n\n"
        result_text += "**Creation fields** must be nested in `subscription_data` container:\n"
        result_text += "```json\n"
        result_text += '{"action": "create", "subscription_data": {"name": "Monthly Subscription", "product_id": "prod_123", "clientEmailAddress": "user@company.com"}}\n'
        result_text += "```\n\n"
        result_text += "**Top-level parameters** for tool behavior:\n"
        result_text += "- `action` - What operation to perform\n"
        result_text += "- `subscription_id` - For get/update/delete operations\n"
        result_text += "- `auto_generate` - Enable smart defaults (default: true)\n"
        result_text += "- `dry_run` - Preview without creating (optional)\n"
        result_text += "- `page`, `size` - For list operations\n\n"

        result_text += "## **Subscription Statuses**\n"
        for status in capabilities.get("subscription_statuses", []):
            result_text += f"- `{status}`\n"

        result_text += "\n## **Billing Periods**\n"
        for period in capabilities.get("billing_periods", []):
            result_text += f"- `{period}`\n"

        result_text += "\n## **Trial Periods**\n"
        for trial in capabilities.get("trial_periods", []):
            result_text += f"- `{trial}`\n"

        result_text += "\n## **Supported Currencies**\n"
        for currency in capabilities.get("currencies", []):
            result_text += f"- `{currency}`\n"

        result_text += "\n## **Required Fields**\n"
        schema = capabilities.get("schema", {}).get("subscription_data", {})
        for field in schema.get("required", []):
            result_text += f"- `{field}` (required)\n"

        result_text += "\n## **Optional Fields**\n"
        for field in schema.get("optional", []):
            result_text += f"- `{field}` (optional)\n"

        result_text += "\n## **Lifecycle States**\n"
        lifecycle = capabilities.get("lifecycle_states", {})
        result_text += "### Creation States\n"
        for state in lifecycle.get("creation", []):
            result_text += f"- `{state}`\n"
        result_text += "### Active States\n"
        for state in lifecycle.get("active_states", []):
            result_text += f"- `{state}`\n"
        result_text += "### Terminal States\n"
        for state in lifecycle.get("terminal_states", []):
            result_text += f"- `{state}`\n"

        result_text += "\n## **Business Rules**\n"
        for rule in capabilities.get("business_rules", []):
            result_text += f"- {rule}\n"

        result_text += "\n## **Next Steps**\n"
        result_text += "1. Use `get_examples(example_type='...')` to see working templates\n"
        result_text += "2. Use `validate(subscription_data={...})` to test configurations\n"
        result_text += "3. Use `create(subscription_data={...})` to create subscriptions\n"

        return [TextContent(type="text", text=result_text)]

    def _format_examples_response(
        self, examples: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format examples response."""
        result_text = "# **Subscription Management Examples**\n\n"

        if "error" in examples:
            available_types = examples.get("available_types", [])
            raise create_structured_validation_error(
                message=examples["error"],
                field="examples",
                value=examples.get("type", "unknown"),
                suggestions=[
                    (
                        f"Available types: {', '.join(available_types)}"
                        if available_types
                        else "Check input parameters"
                    ),
                    "Use get_examples() to see all available example types",
                    "Verify the example type is supported for subscription management",
                    "Check the spelling of the example type parameter",
                ],
                examples={
                    "available_types": available_types,
                    "usage": "get_examples(example_type='basic')",
                    "common_types": ["basic", "advanced", "validation", "billing_safety"],
                    "billing_safety": "BILLING SAFETY: Examples help ensure correct subscription configuration",
                },
            )

        for i, example in enumerate(examples.get("examples", []), 1):
            result_text += f"## **Example {i}: {example['name']}**\n\n"
            result_text += f"**Description**: {example['description']}\n"
            result_text += f"**Use Case**: {example['use_case']}\n\n"

            if example.get("note"):
                result_text += f"**⚠️ Important**: {example['note']}\n\n"

            result_text += "**Template**:\n```json\n"
            result_text += json.dumps(example["template"], indent=2)
            result_text += "\n```\n\n"

        result_text += "## **Usage**\n"
        result_text += "Copy any template above and modify it for your needs, then use the appropriate create action.\n"

        return [TextContent(type="text", text=result_text)]

    def _format_validation_response(
        self, validation_result: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format validation response."""
        result_text = "# **Subscription Validation Results**\n\n"

        if validation_result["valid"]:
            result_text += "**Validation Successful**\n\n"
            result_text += "Your subscription configuration is valid and ready for creation!\n\n"
        else:
            result_text += "**Validation Failed**\n\n"
            result_text += "**Errors Found**:\n"
            for error in validation_result.get("errors", []):
                result_text += f"- **{error.get('field', 'unknown')}**: {error.get('error', 'Unknown error')}\n"
                if error.get("suggestion"):
                    result_text += f"  *Suggestion*: {error['suggestion']}\n"
                if error.get("valid_values"):
                    result_text += f"  *Valid values*: {', '.join(error['valid_values'])}\n"
            result_text += "\n"

        if validation_result.get("warnings"):
            result_text += "⚠️ **Warnings**:\n"
            for warning in validation_result["warnings"]:
                result_text += f"- {warning}\n"
            result_text += "\n"

        if validation_result.get("suggestions"):
            result_text += "💡 **Suggestions**:\n"
            for suggestion in validation_result["suggestions"]:
                if isinstance(suggestion, dict):
                    result_text += (
                        f"- **{suggestion.get('type', 'info')}**: {suggestion.get('message', '')}\n"
                    )
                    if suggestion.get("next_steps"):
                        for step in suggestion["next_steps"]:
                            result_text += f"  - {step}\n"
                else:
                    result_text += f"- {suggestion}\n"
            result_text += "\n"

        result_text += f"**Dry Run**: {validation_result.get('dry_run', True)}\n"

        return [TextContent(type="text", text=result_text)]

    async def _handle_get_agent_summary(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle getting agent summary for subscription management."""
        logger.info("Getting agent summary for subscription management")
        self.formatter.start_timing()

        # Define key capabilities
        key_capabilities = [
            "Safe subscription creation with billing error prevention",
            "Product discovery and validation to prevent wrong product selection",
            "Enhanced natural language processing with explicit confirmation requirements",
            "Complete subscription lifecycle management with billing safety",
            "Comprehensive validation and warning systems for billing implications",
            "Integration with products, customers, and billing systems with safety checks",
        ]

        # Define common use cases with examples
        common_use_cases = [
            {
                "title": "Create Monthly Subscription",
                "description": "Set up a standard monthly subscription for a customer",
                "example": "create_simple(product_id='prod_123', clientEmailAddress='user@company.com')",
            },
            {
                "title": "List Active Subscriptions",
                "description": "View all active subscriptions with pagination",
                "example": "list(filters={'status': 'active'}, page=0, size=10)",
            },
            {
                "title": "Update Subscription Details",
                "description": "Modify subscription information like billing address",
                "example": "update(subscription_id='sub_123', subscription_data={...})",
            },
            {
                "title": "Cancel Subscription",
                "description": "Cancel an active subscription with proper lifecycle handling",
                "example": "cancel(subscription_id='sub_123')",
            },
            {
                "title": "Subscription Analytics",
                "description": "Analyze subscription metrics and performance",
                "example": "get_metrics(filters={'status': 'active'})",
            },
        ]

        # Define quick start steps
        quick_start_steps = [
            "FIRST: Use discover_products() to find available products and understand billing implications",
            "VALIDATE: Use validate_product_for_subscription(product_id='...') to verify product safety",
            "REVIEW: Call get_capabilities() to see subscription options and business rules",
            "CREATE SAFELY: Always specify explicit product_id and clientEmailAddress in subscription creation",
            "MONITOR: Use list(), get(), update(), cancel(), or get_metrics() for ongoing management",
        ]

        # Define next actions
        next_actions = [
            "Try: discover_products() - Find available products with billing safety info",
            "Try: validate_product_for_subscription(product_id='...') - Verify product before use",
            "Try: get_capabilities() - See all subscription options and safety requirements",
            "Try: list(page=0, size=5) - View existing subscriptions",
            "Try: get_metrics() - Analyze subscription performance",
        ]

        return self.formatter.format_agent_summary_response(
            description="Manage customer subscriptions with full lifecycle support including creation, updates, cancellation, and billing management",
            key_capabilities=key_capabilities,
            common_use_cases=common_use_cases,
            quick_start_steps=quick_start_steps,
            next_actions=next_actions,
        )

    # Metadata Provider Implementation
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get subscription tool capabilities."""
        return [
            ToolCapability(
                name="Subscription CRUD Operations",
                description="Complete lifecycle management for subscriptions",
                parameters={
                    "list": {"page": "int", "size": "int", "filters": "dict"},
                    "get": {"subscription_id": "str"},
                    "create": {"subscription_data": "dict"},
                    "update": {"subscription_id": "str", "subscription_data": "dict"},
                    "cancel": {"subscription_id": "str"},
                },
                examples=[
                    "list(page=0, size=10)",
                    "get(subscription_id='sub_123')",
                    "create(subscription_data={'product_id': 'prod_123', 'clientEmailAddress': 'user@company.com'})",
                ],
                limitations=[
                    "Requires valid API authentication",
                    "Subscription cancellation may have billing implications",
                    "Some fields are immutable after creation",
                ],
            ),
            ToolCapability(
                name="Subscription Analytics",
                description="Subscription metrics and performance analysis",
                parameters={"get_metrics": {"filters": "dict", "date_range": "dict"}},
                examples=[
                    "get_metrics(filters={'status': 'active'})",
                    "get_metrics(date_range={'start': '2024-01-01', 'end': '2024-12-31'})",
                ],
            ),
            ToolCapability(
                name="Enhanced Creation",
                description="Simplified subscription creation with smart defaults",
                parameters={
                    "create_simple": {
                        "product_id": "str",
                        "clientEmailAddress": "str",
                        "type": "str",
                    },
                    "create_from_text": {"text": "str"},
                },
                examples=[
                    "create_simple(product_id='prod_123', clientEmailAddress='user@company.com', type='monthly')",
                    "create_from_text(text='Create monthly subscription for premium service')",
                ],
            ),
        ]

    async def _get_supported_actions(self) -> List[str]:
        """Get supported actions."""
        return [
            "list",
            "get",
            "create",
            "update",
            "cancel",
            "delete",
            "create_simple",
            "create_from_text",
            "get_metrics",
            "discover_products",
            "validate_product_for_subscription",
            "get_supporting_data",
            "search_subscriptions",
            "subscription_nlp",
            "get_capabilities",
            "get_examples",
            "validate",
            "get_agent_summary",
            "get_tool_metadata",
            # Hierarchy actions
            "get_product_details",
            "get_credentials",
            "create_with_credentials",
        ]

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Context7 single source of truth for manage_subscriptions schema."""
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": await self._get_supported_actions()},
                "name": {
                    "type": "string",
                    "description": "Subscription name - the only field users need to provide",
                },
                # Note: product_id, clientEmailAddress auto-generated or prompted
                # Note: ownerId, teamId system-managed
                # Note: subscription_data handled in implementation
            },
            "required": ["action", "name"],  # Context7: User-centric only
        }

    async def _get_tool_dependencies(self) -> List[ToolDependency]:
        """Get tool dependencies."""
        # Removed circular dependencies - subscriptions work independently
        # Business relationships are documented in resource_relationships instead
        # Only keep non-circular dependencies that represent actual technical needs
        return [
            ToolDependency(
                tool_name="manage_alerts",
                dependency_type=DependencyType.ENHANCES,
                description="Subscriptions can have monitoring alerts configured",
                conditional=True,
            )
        ]

    async def _get_resource_relationships(self) -> List[ResourceRelationship]:
        """Get resource relationships."""
        return [
            ResourceRelationship(
                resource_type="products",
                relationship_type="requires",
                description="Subscriptions belong to products",
                cardinality="N:1",
                optional=False,
            ),
            ResourceRelationship(
                resource_type="users",
                relationship_type="requires",
                description="Subscriptions are owned by users",
                cardinality="N:1",
                optional=False,
            ),
            ResourceRelationship(
                resource_type="organizations",
                relationship_type="requires",
                description="Subscriptions belong to organizations",
                cardinality="N:1",
                optional=False,
            ),
            ResourceRelationship(
                resource_type="alerts",
                relationship_type="creates",
                description="Subscriptions can have monitoring alerts",
                cardinality="1:N",
                optional=True,
            ),
        ]

    async def _get_usage_patterns(self) -> List[UsagePattern]:
        """Get usage patterns."""
        return [
            UsagePattern(
                pattern_name="Subscription Discovery",
                description="Explore existing subscriptions and their status",
                frequency=0.9,
                typical_sequence=["list", "get"],
                common_parameters={"page": 0, "size": 20, "filters": {"status": "active"}},
                success_indicators=[
                    "Subscriptions listed successfully",
                    "Subscription details retrieved",
                ],
            ),
            UsagePattern(
                pattern_name="Subscription Creation",
                description="Create new subscriptions with validation",
                frequency=0.7,
                typical_sequence=["validate", "create", "get"],
                common_parameters={"dry_run": True},
                success_indicators=["Validation passed", "Subscription created successfully"],
            ),
            UsagePattern(
                pattern_name="Subscription Management",
                description="Update and manage existing subscriptions",
                frequency=0.5,
                typical_sequence=["get", "update", "get"],
                common_parameters={"subscription_id": "required"},
                success_indicators=["Subscription updated successfully", "Changes reflected"],
            ),
            UsagePattern(
                pattern_name="Subscription Analytics",
                description="Analyze subscription metrics and performance",
                frequency=0.6,
                typical_sequence=["get_metrics", "list"],
                common_parameters={"filters": {"status": "active"}},
                success_indicators=["Metrics retrieved successfully", "Analytics data available"],
            ),
        ]

    async def _get_agent_summary(self) -> str:
        """Get agent summary."""
        return """**Subscription Management Tool**

Comprehensive subscription lifecycle management for the Revenium platform. Handle creation, updates, cancellation, and analytics for customer subscriptions with intelligent validation and business rule enforcement.

**Key Features:**
• Complete CRUD operations with validation
• Subscription metrics and analytics
• Business rule validation and compliance
• Integration with products, users, and billing
• Agent-friendly error handling and guidance"""

    async def _get_quick_start_guide(self) -> List[str]:
        """Get quick start guide."""
        return [
            "Start with get_capabilities() to understand subscription requirements",
            "Use get_examples(example_type='...') to see working subscription templates",
            "Validate configurations with validate(subscription_data={...}, dry_run=True)",
            "Create subscriptions with create(subscription_data={...}) or create_simple(...)",
            "Monitor and manage with list(), get(), update(), and cancel() actions",
            "Analyze performance with get_metrics() for subscription analytics",
        ]


# Create consolidated instance
# Module-level instantiation removed to prevent UCM warnings during import
# subscription_management = SubscriptionManagement(ucm_helper=None)
