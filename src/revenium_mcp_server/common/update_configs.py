"""Update configurations for different resource types.

This module defines the configuration objects used by PartialUpdateHandler
for each resource type in the Revenium Platform API.
"""

from typing import Dict

from ..client import ReveniumClient
from .partial_update_handler import FieldTransformers, UpdateConfig


class UpdateConfigs:
    """Factory class for creating update configurations for different resource types."""

    @staticmethod
    def create_subscriber_credentials_config(client: ReveniumClient) -> UpdateConfig:
        """Create update configuration for subscriber credentials.

        Args:
            client: ReveniumClient instance

        Returns:
            UpdateConfig for subscriber credentials
        """
        return UpdateConfig(
            resource_type="credential",
            get_method=client.get_credential_by_id,
            update_method=client.update_credential,
            id_field="id",
            required_fields=[
                "label",
                "name",
                "subscriberId",
                "teamId",
                "externalId",
                "externalSecret",
                "organizationId",
            ],
            default_fields={"teamId": client.team_id},
            preserve_fields=[
                "id",
                "createdAt",
                "updatedAt",
                "version",
                # Preserve relationship and association fields (fixes FINDING #4)
                "subscriptionIds",
                "tags",
                "metadata",
            ],
        )

    @staticmethod
    def create_products_config(client: ReveniumClient) -> UpdateConfig:
        """Create update configuration for products.

        Args:
            client: ReveniumClient instance

        Returns:
            UpdateConfig for products
        """
        from ..config_store import get_config_value

        # Build default fields
        default_fields = {"teamId": client.team_id}

        # Add ownerId if available (consistent with product creation)
        owner_id = get_config_value("REVENIUM_OWNER_ID")
        if owner_id:
            default_fields["ownerId"] = owner_id

        return UpdateConfig(
            resource_type="product",
            get_method=client.get_product_by_id,
            update_method=client.update_product,
            id_field="id",
            required_fields=["name", "version", "plan", "paymentSource"],
            default_fields=default_fields,
            preserve_fields=[
                "id",
                "createdAt",
                "updatedAt",
                "ownerId",
                # Preserve relationship and association fields
                "source_ids",
                "sla_ids",
                "custom_pricing_rule_ids",
                "notification_addresses_on_invoice",
                "tags",
                "terms",
            ],
        )

    @staticmethod
    def create_subscriptions_config(client: ReveniumClient) -> UpdateConfig:
        """Create update configuration for subscriptions.

        Args:
            client: ReveniumClient instance

        Returns:
            UpdateConfig for subscriptions
        """
        from ..config_store import get_config_value

        # Build default fields
        default_fields = {"teamId": client.team_id}

        # Add ownerId if available (consistent with subscription creation)
        owner_id = get_config_value("REVENIUM_OWNER_ID")
        if owner_id:
            default_fields["ownerId"] = owner_id

        return UpdateConfig(
            resource_type="subscription",
            get_method=client.get_subscription_by_id,
            update_method=client.update_subscription,
            id_field="id",
            required_fields=["name"],
            default_fields=default_fields,
            preserve_fields=[
                "id",
                "createdAt",
                "updatedAt",
                "productId",
                "ownerId",
                "teamId",
                "subscriberId",
                "organizationId",
            ],
            field_transformations={
                "owner": {"ownerId": FieldTransformers.extract_owner_id},
                "client": {"subscriberId": FieldTransformers.object_to_id},
                "organization": {"organizationId": FieldTransformers.object_to_id},
                "product": {"productId": FieldTransformers.object_to_id},
            },
        )

    @staticmethod
    def create_sources_config(client: ReveniumClient) -> UpdateConfig:
        """Create update configuration for sources.

        Args:
            client: ReveniumClient instance

        Returns:
            UpdateConfig for sources
        """
        from ..config_store import get_config_value

        # Build default fields
        default_fields = {
            "teamId": client.team_id,
            "code": "",
            "assetUsageIdentifier": "API_ENDPOINT",
            "planId": "",
            "sourceType": "",
        }

        # Add ownerId if available (consistent with source creation)
        owner_id = get_config_value("REVENIUM_OWNER_ID")
        if owner_id:
            default_fields["ownerId"] = owner_id

        return UpdateConfig(
            resource_type="source",
            get_method=client.get_source_by_id,
            update_method=client.update_source,
            id_field="id",
            required_fields=["name", "description", "version", "type"],
            default_fields=default_fields,
            preserve_fields=[
                "createdAt",
                "updatedAt",
                "ownerId",
                "teamId",
                "meteringElementDefinitionIds",
                "code",
                "assetUsageIdentifier",
                "planId",
                "identityProviderConfigurationId",
                "environmentId",
                "tags",
                "sourceClassifications",
                # "method" removed - should be updatable, not preserved
                "syncedWithApiGateway",
                "autoDiscoveryEnabled",
                "resource",
                "logoURL",
                "devPortalLink",
                "sourceType",
                "externalId",
                "externalUsagePlanId",
            ],
            field_transformations={
                "owner": {"ownerId": FieldTransformers.extract_owner_id},
                "team": {"teamId": FieldTransformers.object_to_id},
            },
            field_mappings={"externalUsagePlanId": "externalPlanId"},
        )

    @staticmethod
    def create_customers_config(
        client: ReveniumClient, resource_type: str = "user"
    ) -> UpdateConfig:
        """Create update configuration for customer resources.

        Args:
            client: ReveniumClient instance
            resource_type: Type of customer resource (user, subscriber, organization, team)

        Returns:
            UpdateConfig for customer resources
        """
        # Map resource types to their respective client methods
        method_mapping = {
            "user": {
                "get_method": client.get_user_by_id,
                "update_method": client.update_user,
                "required_fields": ["email"],
            },
            "subscriber": {
                "get_method": client.get_subscriber_by_id,
                "update_method": client.update_subscriber,
                "required_fields": ["email"],
            },
            "organization": {
                "get_method": client.get_organization_by_id,
                "update_method": client.update_organization,
                "required_fields": ["name"],
            },
            "team": {
                "get_method": client.get_team_by_id,
                "update_method": client.update_team,
                "required_fields": ["name"],
            },
        }

        if resource_type not in method_mapping:
            raise ValueError(f"Unsupported customer resource type: {resource_type}")

        mapping = method_mapping[resource_type]

        # Define preserve fields based on resource type
        preserve_fields = ["id", "createdAt", "updatedAt"]

        # Add resource-specific relationship fields and transformations
        field_transformations = {}
        if resource_type == "user":
            # Note: "roles" removed from preserve_fields to allow role updates via partial updates
            preserve_fields.extend(
                ["organization_id", "team_id", "teamIds", "permissions", "role", "tenant"]
            )
            field_transformations = {"teams": {"teamIds": FieldTransformers.extract_team_ids}}
        elif resource_type == "subscriber":
            # Only preserve fields that should never be updated by users
            # Remove firstName, lastName, email from preserve_fields to allow updates
            # Note: "roles" removed from preserve_fields to allow role updates via partial updates
            preserve_fields.extend(
                [
                    "subscription_ids",
                    "organization_id",
                    "user_id",
                    "billing_address",
                    "payment_method",
                    "subscriberId",
                    "tenant",
                ]
            )
            field_transformations = {
                "organizations": {"organizationIds": FieldTransformers.objects_array_to_ids}
            }
        elif resource_type == "organization":
            preserve_fields.extend(["parent_organization_id", "contact_info", "address"])
        elif resource_type == "team":
            preserve_fields.extend(
                ["organization_id", "parent_team_id", "owner_id", "members", "permissions"]
            )

        return UpdateConfig(
            resource_type=resource_type,
            get_method=mapping["get_method"],
            update_method=mapping["update_method"],
            id_field="id",
            required_fields=mapping["required_fields"],
            default_fields={
                "teamId": client.team_id if resource_type in ["user", "subscriber"] else None
            },
            preserve_fields=preserve_fields,
            field_transformations=field_transformations,
        )

    @staticmethod
    def create_metering_elements_config(client: ReveniumClient) -> UpdateConfig:
        """Create update configuration for metering elements.

        Args:
            client: ReveniumClient instance

        Returns:
            UpdateConfig for metering elements
        """
        return UpdateConfig(
            resource_type="metering_element",
            get_method=client.get_metering_element_definition_by_id,
            update_method=client.update_metering_element_definition,
            id_field="id",
            required_fields=["name"],
            default_fields={},
            preserve_fields=["id", "createdAt", "updatedAt"],
        )


class UpdateConfigFactory:
    """Factory for creating and caching update configurations."""

    def __init__(self, client: ReveniumClient):
        """Initialize factory with client instance.

        Args:
            client: ReveniumClient instance
        """
        self.client = client
        self._configs: Dict[str, UpdateConfig] = {}

    def get_config(self, resource_type: str, **kwargs) -> UpdateConfig:
        """Get update configuration for a resource type.

        Args:
            resource_type: Type of resource
            **kwargs: Additional arguments for configuration creation

        Returns:
            UpdateConfig instance

        Raises:
            ValueError: If resource type is not supported
        """
        # Create cache key including kwargs for customer resources
        cache_key = f"{resource_type}_{hash(frozenset(kwargs.items()))}"

        if cache_key not in self._configs:
            if resource_type == "subscriber_credentials":
                self._configs[cache_key] = UpdateConfigs.create_subscriber_credentials_config(
                    self.client
                )
            elif resource_type == "products":
                self._configs[cache_key] = UpdateConfigs.create_products_config(self.client)
            elif resource_type == "subscriptions":
                self._configs[cache_key] = UpdateConfigs.create_subscriptions_config(self.client)
            elif resource_type == "sources":
                self._configs[cache_key] = UpdateConfigs.create_sources_config(self.client)
            elif resource_type == "customers":
                customer_type = kwargs.get("customer_type", "user")
                self._configs[cache_key] = UpdateConfigs.create_customers_config(
                    self.client, customer_type
                )
            elif resource_type == "metering_elements":
                self._configs[cache_key] = UpdateConfigs.create_metering_elements_config(
                    self.client
                )
            else:
                raise ValueError(f"Unsupported resource type: {resource_type}")

        return self._configs[cache_key]

    def clear_cache(self) -> None:
        """Clear the configuration cache."""
        self._configs.clear()


# Convenience function for creating update handler with config
def create_update_handler_with_config(client: ReveniumClient, resource_type: str, **kwargs):
    """Create a PartialUpdateHandler with appropriate configuration.

    Args:
        client: ReveniumClient instance
        resource_type: Type of resource
        **kwargs: Additional arguments for configuration

    Returns:
        Tuple of (PartialUpdateHandler, UpdateConfig)
    """
    from .partial_update_handler import PartialUpdateHandler

    factory = UpdateConfigFactory(client)
    config = factory.get_config(resource_type, **kwargs)
    handler = PartialUpdateHandler()

    return handler, config
