"""Hierarchy Navigation Service for Revenium MCP Server.

This service provides bidirectional navigation and relationship traversal
across the three-tier hierarchy: Products → Subscriptions → Subscriber Credentials.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from ..client import ReveniumClient


@dataclass
class NavigationResult:
    """Result of a hierarchy navigation operation."""

    success: bool
    entity_type: str
    entity_id: str
    related_entities: List[Dict[str, Any]]
    navigation_path: List[str]
    metadata: Dict[str, Any]
    error_message: Optional[str] = None


@dataclass
class HierarchyPath:
    """Represents a path through the hierarchy."""

    start_entity: Tuple[str, str]  # (entity_type, entity_id)
    end_entity: Tuple[str, str]  # (entity_type, entity_id)
    path_steps: List[Dict[str, Any]]
    total_hops: int
    path_valid: bool


class HierarchyNavigationService:
    """Service for navigating relationships in the Products → Subscriptions → Credentials hierarchy."""

    def __init__(self, client: Optional[ReveniumClient] = None):
        """Initialize the hierarchy navigation service.

        Args:
            client: ReveniumClient instance for API calls
        """
        self.client = client or ReveniumClient()
        self._cache = {}
        self._cache_ttl = timedelta(minutes=2)  # Cache for 2 minutes
        self._last_cache_clear = datetime.now()

        # Hierarchy relationship mappings
        self.hierarchy_levels = {"products": 1, "subscriptions": 2, "credentials": 3}

        self.relationship_fields = {
            "subscriptions": {"parent_field": "product_id", "parent_type": "products"},
            "credentials": {"parent_field": "subscriptionIds", "parent_type": "subscriptions"},
        }

    async def initialize(self) -> None:
        """Initialize the service."""
        logger.info("Initializing HierarchyNavigationService")
        await self._clear_expired_cache()
        logger.info("HierarchyNavigationService initialized successfully")

    # Downward Navigation (Parent → Children)

    async def get_subscriptions_for_product(self, product_id: str) -> NavigationResult:
        """Get all subscriptions for a given product.

        Args:
            product_id: Product ID to find subscriptions for

        Returns:
            NavigationResult with subscriptions data
        """
        try:
            cache_key = f"product_subscriptions_{product_id}"
            cached_result = await self._get_cached_result(cache_key)
            if cached_result:
                return cached_result

            # Validate product exists
            try:
                product = await self.client.get_product_by_id(product_id)
                if not product:
                    return NavigationResult(
                        success=False,
                        entity_type="products",
                        entity_id=product_id,
                        related_entities=[],
                        navigation_path=[],
                        metadata={},
                        error_message=f"Product {product_id} not found",
                    )
            except Exception as e:
                logger.error(f"Error validating product {product_id}: {e}")
                return NavigationResult(
                    success=False,
                    entity_type="products",
                    entity_id=product_id,
                    related_entities=[],
                    navigation_path=[],
                    metadata={},
                    error_message=f"Error accessing product: {str(e)}",
                )

            # Get subscriptions for this product
            subscriptions = []
            page = 0
            page_size = 50

            while True:
                try:
                    response = await self.client.get_subscriptions(page=page, size=page_size)
                    page_subscriptions = self.client._extract_embedded_data(response)

                    # Filter subscriptions for this product
                    product_subscriptions = [
                        sub
                        for sub in page_subscriptions
                        if (
                            sub.get("product_id") == product_id
                            or sub.get("productId") == product_id
                            or (
                                sub.get("product")
                                and sub.get("product", {}).get("id") == product_id
                            )
                        )
                    ]
                    subscriptions.extend(product_subscriptions)

                    # Check if we have more pages
                    if len(page_subscriptions) < page_size:
                        break
                    page += 1

                except Exception as e:
                    logger.error(f"Error fetching subscriptions page {page}: {e}")
                    break

            result = NavigationResult(
                success=True,
                entity_type="products",
                entity_id=product_id,
                related_entities=subscriptions,
                navigation_path=["products", "subscriptions"],
                metadata={
                    "product_name": product.get("name"),
                    "subscription_count": len(subscriptions),
                    "navigation_direction": "downward",
                },
            )

            await self._cache_result(cache_key, result)
            return result

        except Exception as e:
            logger.error(f"Error getting subscriptions for product {product_id}: {e}")
            return NavigationResult(
                success=False,
                entity_type="products",
                entity_id=product_id,
                related_entities=[],
                navigation_path=[],
                metadata={},
                error_message=f"Navigation error: {str(e)}",
            )

    async def get_credentials_for_subscription(self, subscription_id: str) -> NavigationResult:
        """Get all credentials for a given subscription.

        Args:
            subscription_id: Subscription ID to find credentials for

        Returns:
            NavigationResult with credentials data
        """
        try:
            cache_key = f"subscription_credentials_{subscription_id}"
            cached_result = await self._get_cached_result(cache_key)
            if cached_result:
                return cached_result

            # Validate subscription exists
            try:
                subscription = await self.client.get_subscription_by_id(subscription_id)
                if not subscription:
                    return NavigationResult(
                        success=False,
                        entity_type="subscriptions",
                        entity_id=subscription_id,
                        related_entities=[],
                        navigation_path=[],
                        metadata={},
                        error_message=f"Subscription {subscription_id} not found",
                    )
            except Exception as e:
                logger.error(f"Error validating subscription {subscription_id}: {e}")
                return NavigationResult(
                    success=False,
                    entity_type="subscriptions",
                    entity_id=subscription_id,
                    related_entities=[],
                    navigation_path=[],
                    metadata={},
                    error_message=f"Error accessing subscription: {str(e)}",
                )

            # Get credentials from the subscription's credentials array
            # The subscription object already contains the credentials array
            credentials = subscription.get("credentials", [])

            # If we need full credential objects, fetch them
            full_credentials = []
            for cred_ref in credentials:
                cred_id = cred_ref.get("id")
                if cred_id:
                    try:
                        full_cred = await self.client.get_credential_by_id(cred_id)
                        if full_cred:
                            full_credentials.append(full_cred)
                    except Exception as e:
                        logger.warning(f"Could not fetch credential {cred_id}: {e}")
                        # Use the reference object if we can't get the full object
                        full_credentials.append(cred_ref)
                else:
                    # Use the reference object if no ID
                    full_credentials.append(cred_ref)

            credentials = full_credentials

            result = NavigationResult(
                success=True,
                entity_type="subscriptions",
                entity_id=subscription_id,
                related_entities=credentials,
                navigation_path=["subscriptions", "credentials"],
                metadata={
                    "subscription_name": subscription.get("name"),
                    "credential_count": len(credentials),
                    "navigation_direction": "downward",
                },
            )

            await self._cache_result(cache_key, result)
            return result

        except Exception as e:
            logger.error(f"Error getting credentials for subscription {subscription_id}: {e}")
            return NavigationResult(
                success=False,
                entity_type="subscriptions",
                entity_id=subscription_id,
                related_entities=[],
                navigation_path=[],
                metadata={},
                error_message=f"Navigation error: {str(e)}",
            )

    # Upward Navigation (Child → Parent)

    async def get_product_for_subscription(self, subscription_id: str) -> NavigationResult:
        """Get the product for a given subscription.

        Args:
            subscription_id: Subscription ID to find product for

        Returns:
            NavigationResult with product data
        """
        try:
            cache_key = f"subscription_product_{subscription_id}"
            cached_result = await self._get_cached_result(cache_key)
            if cached_result:
                return cached_result

            # Get subscription to find product_id
            subscription = await self.client.get_subscription_by_id(subscription_id)
            if not subscription:
                return NavigationResult(
                    success=False,
                    entity_type="subscriptions",
                    entity_id=subscription_id,
                    related_entities=[],
                    navigation_path=[],
                    metadata={},
                    error_message=f"Subscription {subscription_id} not found",
                )

            # Try multiple ways to get product_id
            product_id = (
                subscription.get("product_id")
                or subscription.get("productId")
                or (subscription.get("product") and subscription.get("product", {}).get("id"))
            )

            if not product_id:
                return NavigationResult(
                    success=False,
                    entity_type="subscriptions",
                    entity_id=subscription_id,
                    related_entities=[],
                    navigation_path=[],
                    metadata={},
                    error_message="Subscription has no associated product_id",
                )

            # Get the product
            product = await self.client.get_product_by_id(product_id)
            if not product:
                return NavigationResult(
                    success=False,
                    entity_type="subscriptions",
                    entity_id=subscription_id,
                    related_entities=[],
                    navigation_path=[],
                    metadata={},
                    error_message=f"Product {product_id} not found",
                )

            result = NavigationResult(
                success=True,
                entity_type="subscriptions",
                entity_id=subscription_id,
                related_entities=[product],
                navigation_path=["subscriptions", "products"],
                metadata={
                    "subscription_name": subscription.get("name"),
                    "product_id": product_id,
                    "product_name": product.get("name"),
                    "navigation_direction": "upward",
                },
            )

            await self._cache_result(cache_key, result)
            return result

        except Exception as e:
            logger.error(f"Error getting product for subscription {subscription_id}: {e}")
            return NavigationResult(
                success=False,
                entity_type="subscriptions",
                entity_id=subscription_id,
                related_entities=[],
                navigation_path=[],
                metadata={},
                error_message=f"Navigation error: {str(e)}",
            )

    # Cache Management

    async def _get_cached_result(self, cache_key: str) -> Optional[NavigationResult]:
        """Get cached result if still valid."""
        await self._clear_expired_cache()

        if cache_key in self._cache:
            cached_data = self._cache[cache_key]
            if datetime.now() - cached_data["timestamp"] < self._cache_ttl:
                return cached_data["result"]
            else:
                del self._cache[cache_key]

        return None

    async def _cache_result(self, cache_key: str, result: NavigationResult) -> None:
        """Cache a navigation result."""
        self._cache[cache_key] = {"result": result, "timestamp": datetime.now()}

    async def _clear_expired_cache(self) -> None:
        """Clear expired cache entries."""
        now = datetime.now()
        if now - self._last_cache_clear > timedelta(minutes=5):
            expired_keys = [
                key
                for key, data in self._cache.items()
                if now - data["timestamp"] > self._cache_ttl
            ]
            for key in expired_keys:
                del self._cache[key]
            self._last_cache_clear = now

    async def get_subscription_for_credential(self, credential_id: str) -> NavigationResult:
        """Get the subscription for a given credential.

        Args:
            credential_id: Credential ID to find subscription for

        Returns:
            NavigationResult with subscription data
        """
        try:
            cache_key = f"credential_subscription_{credential_id}"
            cached_result = await self._get_cached_result(cache_key)
            if cached_result:
                return cached_result

            # Get credential to validate it exists
            credential = await self.client.get_credential_by_id(credential_id)
            if not credential:
                return NavigationResult(
                    success=False,
                    entity_type="credentials",
                    entity_id=credential_id,
                    related_entities=[],
                    navigation_path=[],
                    metadata={},
                    error_message=f"Credential {credential_id} not found",
                )

            # Find subscriptions that reference this credential (reverse lookup)
            # Since credentials don't have subscriptionIds, we need to search subscriptions
            # that have this credential in their credentials array
            subscriptions = []
            page = 0
            page_size = 50

            while True:
                try:
                    response = await self.client.get_subscriptions(page=page, size=page_size)
                    page_subscriptions = self.client._extract_embedded_data(response)

                    # Filter subscriptions that reference this credential
                    credential_subscriptions = []
                    for sub in page_subscriptions:
                        sub_credentials = sub.get("credentials", [])
                        # Check if this credential is in the subscription's credentials array
                        for cred in sub_credentials:
                            if cred.get("id") == credential_id:
                                credential_subscriptions.append(sub)
                                break

                    subscriptions.extend(credential_subscriptions)

                    # Check if we have more pages
                    if len(page_subscriptions) < page_size:
                        break
                    page += 1

                except Exception as e:
                    logger.error(f"Error fetching subscriptions page {page}: {e}")
                    break

            if not subscriptions:
                return NavigationResult(
                    success=False,
                    entity_type="credentials",
                    entity_id=credential_id,
                    related_entities=[],
                    navigation_path=[],
                    metadata={},
                    error_message="No subscriptions found that reference this credential",
                )

            result = NavigationResult(
                success=True,
                entity_type="credentials",
                entity_id=credential_id,
                related_entities=subscriptions,
                navigation_path=["credentials", "subscriptions"],
                metadata={
                    "credential_label": credential.get("label"),
                    "subscription_count": len(subscriptions),
                    "subscription_ids": [sub.get("id") for sub in subscriptions],
                    "navigation_direction": "upward",
                },
            )

            await self._cache_result(cache_key, result)
            return result

        except Exception as e:
            logger.error(f"Error getting subscription for credential {credential_id}: {e}")
            return NavigationResult(
                success=False,
                entity_type="credentials",
                entity_id=credential_id,
                related_entities=[],
                navigation_path=[],
                metadata={},
                error_message=f"Navigation error: {str(e)}",
            )

    async def get_product_for_credential(self, credential_id: str) -> NavigationResult:
        """Get the product for a given credential (through subscription).

        Args:
            credential_id: Credential ID to find product for

        Returns:
            NavigationResult with product data
        """
        try:
            cache_key = f"credential_product_{credential_id}"
            cached_result = await self._get_cached_result(cache_key)
            if cached_result:
                return cached_result

            # First get subscription for credential
            subscription_result = await self.get_subscription_for_credential(credential_id)
            if not subscription_result.success or not subscription_result.related_entities:
                return NavigationResult(
                    success=False,
                    entity_type="credentials",
                    entity_id=credential_id,
                    related_entities=[],
                    navigation_path=[],
                    metadata={},
                    error_message=f"Could not find subscription for credential: {subscription_result.error_message}",
                )

            # Get product for the first subscription (credentials typically have one primary subscription)
            subscription = subscription_result.related_entities[0]
            subscription_id = subscription.get("id")

            if not subscription_id:
                return NavigationResult(
                    success=False,
                    entity_type="credentials",
                    entity_id=credential_id,
                    related_entities=[],
                    navigation_path=[],
                    metadata={},
                    error_message="Subscription has no ID",
                )

            product_result = await self.get_product_for_subscription(subscription_id)
            if not product_result.success:
                return NavigationResult(
                    success=False,
                    entity_type="credentials",
                    entity_id=credential_id,
                    related_entities=[],
                    navigation_path=[],
                    metadata={},
                    error_message=f"Could not find product for subscription: {product_result.error_message}",
                )

            result = NavigationResult(
                success=True,
                entity_type="credentials",
                entity_id=credential_id,
                related_entities=product_result.related_entities,
                navigation_path=["credentials", "subscriptions", "products"],
                metadata={
                    "credential_label": subscription_result.metadata.get("credential_label"),
                    "subscription_id": subscription_id,
                    "subscription_name": subscription.get("name"),
                    "product_id": product_result.metadata.get("product_id"),
                    "product_name": product_result.metadata.get("product_name"),
                    "navigation_direction": "upward",
                    "hops": 2,
                },
            )

            await self._cache_result(cache_key, result)
            return result

        except Exception as e:
            logger.error(f"Error getting product for credential {credential_id}: {e}")
            return NavigationResult(
                success=False,
                entity_type="credentials",
                entity_id=credential_id,
                related_entities=[],
                navigation_path=[],
                metadata={},
                error_message=f"Navigation error: {str(e)}",
            )

    async def get_full_hierarchy(self, entity_type: str, entity_id: str) -> NavigationResult:
        """Get the complete hierarchy for a given entity.

        Args:
            entity_type: Type of entity (products, subscriptions, credentials)
            entity_id: Entity ID

        Returns:
            NavigationResult with complete hierarchy data
        """
        try:
            cache_key = f"full_hierarchy_{entity_type}_{entity_id}"
            cached_result = await self._get_cached_result(cache_key)
            if cached_result:
                return cached_result

            hierarchy_data = {"products": [], "subscriptions": [], "credentials": []}

            if entity_type == "products":
                # Start with product, get subscriptions and their credentials
                try:
                    product = await self.client.get_product_by_id(entity_id)
                    if product:
                        hierarchy_data["products"] = [product]

                        # Get subscriptions for product
                        sub_result = await self.get_subscriptions_for_product(entity_id)
                        if sub_result.success:
                            hierarchy_data["subscriptions"] = sub_result.related_entities

                            # Get credentials for each subscription
                            for subscription in sub_result.related_entities:
                                sub_id = subscription.get("id")
                                if sub_id:  # Only process if subscription has valid ID
                                    cred_result = await self.get_credentials_for_subscription(
                                        sub_id
                                    )
                                    if cred_result.success:
                                        hierarchy_data["credentials"].extend(
                                            cred_result.related_entities
                                        )
                except Exception as e:
                    logger.error(f"Error building hierarchy from product {entity_id}: {e}")

            elif entity_type == "subscriptions":
                # Start with subscription, get product and credentials
                try:
                    subscription = await self.client.get_subscription_by_id(entity_id)
                    if subscription:
                        hierarchy_data["subscriptions"] = [subscription]

                        # Get product for subscription
                        prod_result = await self.get_product_for_subscription(entity_id)
                        if prod_result.success:
                            hierarchy_data["products"] = prod_result.related_entities

                        # Get credentials for subscription
                        cred_result = await self.get_credentials_for_subscription(entity_id)
                        if cred_result.success:
                            hierarchy_data["credentials"] = cred_result.related_entities
                except Exception as e:
                    logger.error(f"Error building hierarchy from subscription {entity_id}: {e}")

            elif entity_type == "credentials":
                # Start with credential, get subscription and product
                try:
                    credential = await self.client.get_credential_by_id(entity_id)
                    if credential:
                        hierarchy_data["credentials"] = [credential]

                        # Get subscription for credential
                        sub_result = await self.get_subscription_for_credential(entity_id)
                        if sub_result.success:
                            hierarchy_data["subscriptions"] = sub_result.related_entities

                            # Get product for credential
                            prod_result = await self.get_product_for_credential(entity_id)
                            if prod_result.success:
                                hierarchy_data["products"] = prod_result.related_entities
                except Exception as e:
                    logger.error(f"Error building hierarchy from credential {entity_id}: {e}")

            result = NavigationResult(
                success=True,
                entity_type=entity_type,
                entity_id=entity_id,
                related_entities=[hierarchy_data],
                navigation_path=["products", "subscriptions", "credentials"],
                metadata={
                    "hierarchy_complete": True,
                    "product_count": len(hierarchy_data["products"]),
                    "subscription_count": len(hierarchy_data["subscriptions"]),
                    "credential_count": len(hierarchy_data["credentials"]),
                    "starting_entity": entity_type,
                },
            )

            await self._cache_result(cache_key, result)
            return result

        except Exception as e:
            logger.error(f"Error getting full hierarchy for {entity_type} {entity_id}: {e}")
            return NavigationResult(
                success=False,
                entity_type=entity_type,
                entity_id=entity_id,
                related_entities=[],
                navigation_path=[],
                metadata={},
                error_message=f"Hierarchy navigation error: {str(e)}",
            )

    async def clear_cache(self) -> None:
        """Clear all cached data."""
        self._cache.clear()
        logger.info("HierarchyNavigationService cache cleared")


# Global service instance (lazy initialization)
_hierarchy_navigation_service = None


def get_hierarchy_navigation_service() -> HierarchyNavigationService:
    """Get the global hierarchy navigation service instance (lazy initialization)."""
    global _hierarchy_navigation_service
    if _hierarchy_navigation_service is None:
        _hierarchy_navigation_service = HierarchyNavigationService()
    return _hierarchy_navigation_service


# For backward compatibility - use function instead of property
def hierarchy_navigation_service() -> HierarchyNavigationService:
    """Backward compatibility function."""
    return get_hierarchy_navigation_service()


# Remove the old global instance that was causing import-time initialization
