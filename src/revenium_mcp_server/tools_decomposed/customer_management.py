"""Consolidated customer management tool following MCP best practices.

This module consolidates enhanced_customer_tools.py + customer_tools.py into a single
tool with internal composition, following the proven alert/source management template.
"""

import json
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
from ..introspection.metadata import (
    DependencyType,
    ResourceRelationship,
    ToolCapability,
    ToolDependency,
    ToolType,
    UsagePattern,
)
from .unified_tool_base import ToolBase


class BaseManager:
    """Base class for customer resource managers with shared functionality."""

    def __init__(self, client: ReveniumClient) -> None:
        """Initialize base manager with client and common components."""
        self.client = client
        # Initialize partial update handler and config factory
        self.update_handler = PartialUpdateHandler()
        self.update_config_factory = UpdateConfigFactory(self.client)

    def _populate_call_count_element_definition(self, resource: Dict[str, Any]) -> None:
        """Populate undefined fields in callCountElementDefinition structure.

        Args:
            resource: Customer resource dictionary (organization, user, etc.)
        """
        if "callCountElementDefinition" in resource:
            call_count_def = resource["callCountElementDefinition"]
            if isinstance(call_count_def, dict):
                # Fix undefined resourceType
                if call_count_def.get("resourceType") == "undefined" or not call_count_def.get(
                    "resourceType"
                ):
                    call_count_def["resourceType"] = "meteringElementDefinition"

                # Fix undefined label
                if call_count_def.get("label") == "undefined" or not call_count_def.get("label"):
                    # Try to create a meaningful label from available data
                    element_id = call_count_def.get("id", "Unknown")
                    resource_name = resource.get(
                        "name", resource.get("label", resource.get("email", "Unknown"))
                    )
                    call_count_def["label"] = f"Call Count for {resource_name} ({element_id})"

    def _populate_call_count_definitions_in_list(self, resources: List[Dict[str, Any]]) -> None:
        """Populate undefined fields in callCountElementDefinition for a list of resources.

        Args:
            resources: List of customer resource dictionaries
        """
        for resource in resources:
            if isinstance(resource, dict):
                self._populate_call_count_element_definition(resource)


class UserManager(BaseManager):
    """Internal manager for user operations."""

    async def list_users(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List users with pagination."""
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters = arguments.get("filters", {})

        response = await self.client.get_users(page=page, size=size, **filters)
        users = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)

        # Fix undefined values in callCountElementDefinition structures
        self._populate_call_count_definitions_in_list(users)

        return {
            "action": "list",
            "resource_type": "users",
            "users": users,
            "pagination": page_info,
            "total_found": len(users),
        }

    async def get_user(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get specific user by ID or email."""
        user_id = arguments.get("user_id")
        email = arguments.get("email")

        try:
            if user_id:
                user = await self.client.get_user_by_id(user_id)
                # Fix undefined values in callCountElementDefinition structure
                self._populate_call_count_element_definition(user)
                return user
            elif email:
                user = await self.client.get_user_by_email(email)
                # Fix undefined values in callCountElementDefinition structure
                self._populate_call_count_element_definition(user)
                return user
        except ReveniumAPIError as e:
            if e.status_code == 404:
                identifier = user_id or email
                raise ToolError(
                    message=f"User not found for {'id' if user_id else 'email'}: {identifier}",
                    error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                    field="user_id" if user_id else "email",
                    value=identifier,
                    suggestions=[
                        "Verify the user ID/email exists using list(resource_type='users')",
                        "Check if the user was recently deleted",
                        "Use get_examples() to see valid user ID/email formats",
                    ],
                )
            elif e.status_code == 400:
                identifier = user_id or email
                field_type = "id" if user_id else "email"
                raise ToolError(
                    message=f"Invalid user {field_type} format: {identifier}",
                    error_code=ErrorCodes.VALIDATION_ERROR,
                    field="user_id" if user_id else "email",
                    value=identifier,
                    suggestions=[
                        "User IDs should be 6-character alphanumeric strings (e.g., 'XLnk1P')" if user_id else "Email should be a valid email address format",
                        "Use list(resource_type='users') to see valid user IDs/emails",
                        "Check the format - IDs should not contain special characters" if user_id else "Check the email format",
                    ],
                )
            else:
                # Re-raise other API errors as-is
                raise
        else:
            raise create_structured_missing_parameter_error(
                parameter_name="user_id or email",
                action="get user",
                examples={
                    "usage": "get(resource_type='users', user_id='user_123') or get(resource_type='users', email='user@company.com')",
                    "valid_formats": [
                        "user_id should be a string identifier",
                        "email should be a valid email address",
                    ],
                    "example_values": ["user_123", "admin@company.com"],
                },
            )

    async def create_user(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create new user with Context7 auto-generation support."""
        user_data = arguments.get("user_data")
        name = arguments.get("name")

        # Context7 auto-generation: Handle case where user provides only name
        if not user_data and name:
            # Auto-generate user_data from minimal user input
            # Parse name into firstName and lastName
            name_parts = name.split(" ", 1)
            first_name = name_parts[0]
            last_name = name_parts[1] if len(name_parts) > 1 else ""

            # Generate email from name (basic implementation)
            email_name = name.lower().replace(" ", ".").replace("@", "").replace(".", "")
            generated_email = f"{email_name}@example.com"

            user_data = {
                "email": generated_email,
                "firstName": first_name,
                "lastName": last_name,
                "roles": ["ROLE_API_CONSUMER"],
            }

        elif not user_data:
            raise create_structured_missing_parameter_error(
                parameter_name="user_data",
                action="create user",
                examples={
                    "usage": "create(resource_type='users', user_data={'email': 'user@company.com', 'firstName': 'John', 'lastName': 'Doe'})",
                    "required_fields": ["email", "firstName", "lastName", "roles"],
                    "example_data": {
                        "email": "user@company.com",
                        "firstName": "John",
                        "lastName": "Doe",
                        "roles": ["ROLE_API_CONSUMER"],
                    },
                    "billing_safety": "🔒 BILLING SAFETY: User creation establishes billing relationships and access permissions",
                    "role_requirement": "roles field is required - ROLE_API_CONSUMER is the only valid role for subscribers/users",
                },
            )

        # Add required fields from client environment
        if "teamIds" not in user_data:
            user_data["teamIds"] = [self.client.team_id]
        if "ownerId" not in user_data:
            owner_id = get_config_value("REVENIUM_OWNER_ID")
            if owner_id:
                user_data["ownerId"] = owner_id
            else:
                # Skip ownerId if not available - let API handle default
                logger.warning(
                    "REVENIUM_OWNER_ID not available from configuration store, API will use default owner"
                )

        result = await self.client.create_user(user_data)
        # Fix undefined values in callCountElementDefinition structure
        self._populate_call_count_element_definition(result)
        return result

    async def update_user(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Update existing user using PartialUpdateHandler."""
        user_id = arguments.get("user_id")
        user_data = arguments.get("user_data")

        # Basic parameter validation (PartialUpdateHandler will provide detailed errors)
        if not user_id:
            raise create_structured_missing_parameter_error(
                parameter_name="user_id",
                action="update user",
                examples={
                    "usage": "update(resource_type='users', user_id='user_123', user_data={'firstName': 'Updated', 'lastName': 'Name'})",
                    "note": "Now supports partial updates - only provide fields you want to change",
                    "billing_safety": "🔒 BILLING SAFETY: User updates can affect billing relationships",
                },
            )

        if not user_data:
            raise create_structured_missing_parameter_error(
                parameter_name="user_data",
                action="update user",
                examples={
                    "usage": "update(resource_type='users', user_id='user_123', user_data={'firstName': 'Updated', 'lastName': 'Name'})",
                    "partial_update": "Only provide the fields you want to update",
                    "updatable_fields": ["firstName", "lastName", "email", "roles", "status"],
                    "billing_safety": "🔒 BILLING SAFETY: Partial updates preserve existing user configuration while changing specific fields",
                },
            )

        # Get update configuration for users
        config = self.update_config_factory.get_config("customers", customer_type="user")

        # Use PartialUpdateHandler for the update operation
        result = await self.update_handler.update_with_merge(
            resource_id=user_id, partial_data=user_data, config=config, action_context="update user"
        )

        # Fix undefined values in callCountElementDefinition structure
        self._populate_call_count_element_definition(result)
        return result

    async def delete_user(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Delete user."""
        user_id = arguments.get("user_id")
        if not user_id:
            raise create_structured_missing_parameter_error(
                parameter_name="user_id",
                action="delete user",
                examples={
                    "usage": "delete(resource_type='users', user_id='user_123')",
                    "valid_format": "User ID should be a string identifier",
                    "example_ids": ["user_123", "admin_456", "employee_789"],
                    "warning": "This action permanently removes the user from the organization",
                    "billing_safety": "🔒 BILLING SAFETY: User deletion affects billing relationships permanently",
                },
            )

        result = await self.client.delete_user(user_id)
        return result


class SubscriberManager(BaseManager):
    """Internal manager for subscriber operations."""

    async def list_subscribers(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List subscribers with pagination."""
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters = arguments.get("filters", {})

        response = await self.client.get_subscribers(page=page, size=size, **filters)
        subscribers = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)

        # Fix undefined values in callCountElementDefinition structures
        self._populate_call_count_definitions_in_list(subscribers)

        # Enhance all subscriber responses to show enforced roles
        enhanced_subscribers = [self._enhance_subscriber_response(sub) for sub in subscribers]

        return {
            "action": "list",
            "resource_type": "subscribers",
            "subscribers": enhanced_subscribers,
            "pagination": page_info,
            "total_found": len(enhanced_subscribers),
        }

    async def get_subscriber(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get specific subscriber by ID or email."""
        subscriber_id = arguments.get("subscriber_id")
        email = arguments.get("email")

        try:
            if subscriber_id:
                subscriber = await self.client.get_subscriber_by_id(subscriber_id)
                # Fix undefined values in callCountElementDefinition structure
                self._populate_call_count_element_definition(subscriber)
                # Enhance response to show enforced role for transparency
                return self._enhance_subscriber_response(subscriber)
            elif email:
                subscriber = await self.client.get_subscriber_by_email(email)
                # Fix undefined values in callCountElementDefinition structure
                self._populate_call_count_element_definition(subscriber)
                # Enhance response to show enforced role for transparency
                return self._enhance_subscriber_response(subscriber)
        except ReveniumAPIError as e:
            if e.status_code == 404:
                identifier = subscriber_id or email
                raise ToolError(
                    message=f"Subscriber not found for {'id' if subscriber_id else 'email'}: {identifier}",
                    error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                    field="subscriber_id" if subscriber_id else "email",
                    value=identifier,
                    suggestions=[
                        "Verify the subscriber ID/email exists using list(resource_type='subscribers')",
                        "Check if the subscriber was recently deleted",
                        "Use get_examples() to see valid subscriber ID/email formats",
                    ],
                )
            elif e.status_code == 400:
                identifier = subscriber_id or email
                field_type = "id" if subscriber_id else "email"
                raise ToolError(
                    message=f"Invalid subscriber {field_type} format: {identifier}",
                    error_code=ErrorCodes.VALIDATION_ERROR,
                    field="subscriber_id" if subscriber_id else "email",
                    value=identifier,
                    suggestions=[
                        "Subscriber IDs should be 6-character alphanumeric strings (e.g., 'XLnk1P')" if subscriber_id else "Email should be a valid email address format",
                        "Use list(resource_type='subscribers') to see valid subscriber IDs/emails",
                        "Check the format - IDs should not contain special characters" if subscriber_id else "Check the email format",
                    ],
                )
            else:
                # Re-raise other API errors as-is
                raise
        else:
            raise create_structured_missing_parameter_error(
                parameter_name="subscriber_id or email",
                action="get subscriber",
                examples={
                    "usage": "get(resource_type='subscribers', subscriber_id='sub_123') or get(resource_type='subscribers', email='subscriber@company.com')",
                    "valid_formats": [
                        "subscriber_id should be a string identifier",
                        "email should be a valid email address",
                    ],
                    "example_values": ["sub_123", "subscriber@company.com"],
                },
            )

    async def create_subscriber(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create new subscriber."""
        subscriber_data = arguments.get("subscriber_data")
        if not subscriber_data:
            raise create_structured_missing_parameter_error(
                parameter_name="subscriber_data",
                action="create subscriber",
                examples={
                    "usage": "create(resource_type='subscribers', subscriber_data={'email': 'subscriber@company.com', 'firstName': 'John', 'lastName': 'Doe', 'organizationIds': ['org_id_123'], 'roles': ['ROLE_API_CONSUMER']})",
                    "required_fields": [
                        "email",
                        "firstName",
                        "lastName",
                        "organizationIds",
                        "roles",
                    ],
                    "example_data": {
                        "email": "subscriber@company.com",
                        "firstName": "John",
                        "lastName": "Doe",
                        "subscriberId": "unique_id_123",
                        "organizationIds": ["org_id_123"],
                        "roles": ["ROLE_API_CONSUMER"],
                    },
                    "role_requirement": "ROLE_API_CONSUMER must be explicitly provided in the roles field (API requirement)",
                    "helper": "Use resolve_organization_name_to_id() to get organization ID from name",
                    "billing_safety": "🔒 BILLING INTEGRATION: Subscriber creation establishes billing identity and subscription relationships",
                },
            )

        # Add required fields from client environment
        if "teamId" not in subscriber_data:
            subscriber_data["teamId"] = self.client.team_id
        if "ownerId" not in subscriber_data:
            owner_id = get_config_value("REVENIUM_OWNER_ID")
            if owner_id:
                subscriber_data["ownerId"] = owner_id
            else:
                # Skip ownerId if not available - let API handle default
                logger.warning(
                    "REVENIUM_OWNER_ID not available from configuration store, API will use default owner"
                )

        # Add required organizationIds field - API requires this as an array
        if "organizationIds" not in subscriber_data:
            # Try to get a default organization or create a minimal one
            try:
                # Get first available organization for this team
                orgs_response = await self.client.get_organizations(page=0, size=1)
                organizations = self.client._extract_embedded_data(orgs_response)
                if organizations:
                    subscriber_data["organizationIds"] = [organizations[0]["id"]]
                else:
                    # No organizations found - this is a critical issue
                    raise create_structured_missing_parameter_error(
                        parameter_name="organizationIds",
                        action="create subscriber",
                        examples={
                            "issue": "No organizations found in the system",
                            "solution": "Create an organization first, or provide organizationIds explicitly",
                            "usage": "create(resource_type='subscribers', subscriber_data={'email': '...', 'organizationIds': ['org_id_123']})",
                            "helper": "First use list action with resource_type='organizations' to get valid organization ID, then replace 'org_id_123' with actual ID",
                        },
                    )
            except Exception as e:
                # If organization lookup fails, require explicit organizationIds
                raise create_structured_missing_parameter_error(
                    parameter_name="organizationIds",
                    action="create subscriber",
                    examples={
                        "issue": f"Could not auto-resolve organizationIds: {e}",
                        "solution": "Provide organizationIds explicitly in subscriber_data",
                        "usage": "create(resource_type='subscribers', subscriber_data={'email': '...', 'organizationIds': ['org_id_123']})",
                        "helper": "First use list action with resource_type='organizations' to get valid organization ID, then replace 'org_id_123' with actual ID",
                    },
                )

        # MCP convenience: Add ROLE_API_CONSUMER if not provided (API requires this field)
        # Note: API requires roles field to be explicitly set, but MCP tool provides fallback for better UX
        if "roles" not in subscriber_data:
            subscriber_data["roles"] = ["ROLE_API_CONSUMER"]

        try:
            result = await self.client.create_subscriber(subscriber_data)
            # Fix undefined values in callCountElementDefinition structure
            self._populate_call_count_element_definition(result)
            # Enhance response to show enforced role for transparency
            return self._enhance_subscriber_response(result)
        except ReveniumAPIError as e:
            if e.status_code == 400:
                # Handle organization ID validation errors specifically
                if "Failed to decode hashed Id" in str(e):
                    # Extract the invalid organization ID
                    import re
                    id_match = re.search(r"Failed to decode hashed Id: \[([^\]]+)\]", str(e))
                    invalid_id = id_match.group(1) if id_match else "unknown"

                    raise ToolError(
                        message=f"Invalid organization ID format: {invalid_id}",
                        error_code=ErrorCodes.VALIDATION_ERROR,
                        field="organizationIds",
                        value=invalid_id,
                        suggestions=[
                            "First use list action with resource_type='organizations' to get valid organization ID",
                            "Organization IDs should be 6-character alphanumeric strings (e.g., '6PV2LR')",
                            "Replace placeholder values like 'org_id_123' with actual organization IDs",
                            "Check the ID format - it should not contain special characters",
                        ],
                        examples={
                            "get_valid_ids": "list(resource_type='organizations')",
                            "correct_format": "organizationIds: ['6PV2LR']",
                            "common_mistake": "Don't use placeholder values like 'org_id_123'",
                        }
                    )
                else:
                    # Handle other 400 errors
                    raise ToolError(
                        message=f"Invalid subscriber data: {str(e)}",
                        error_code=ErrorCodes.VALIDATION_ERROR,
                        field="subscriber_data",
                        suggestions=[
                            "Check all required fields are provided",
                            "Ensure organizationIds contains valid organization IDs",
                            "Verify email format is correct",
                            "Use get_examples() to see valid subscriber data format",
                        ],
                    )
            elif e.status_code == 404:
                raise ToolError(
                    message="Required resources not found for subscriber creation",
                    error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                    suggestions=[
                        "Ensure the organization exists before creating subscriber",
                        "Use list(resource_type='organizations') to verify organization IDs",
                    ],
                )
            else:
                # Re-raise other API errors as-is
                raise

    async def update_subscriber(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Update existing subscriber using PartialUpdateHandler."""
        subscriber_id = arguments.get("subscriber_id")
        subscriber_data = arguments.get("subscriber_data")

        # Basic parameter validation (PartialUpdateHandler will provide detailed errors)
        if not subscriber_id:
            raise create_structured_missing_parameter_error(
                parameter_name="subscriber_id",
                action="update subscriber",
                examples={
                    "usage": "update(resource_type='subscribers', subscriber_id='sub_123', subscriber_data={'name': 'Updated Name'})",
                    "note": "Now supports partial updates - only provide fields you want to change",
                    "billing_safety": "🔒 BILLING SAFETY: Subscriber updates can affect billing identity and subscription relationships",
                },
            )

        if not subscriber_data:
            raise create_structured_missing_parameter_error(
                parameter_name="subscriber_data",
                action="update subscriber",
                examples={
                    "usage": "update(resource_type='subscribers', subscriber_id='sub_123', subscriber_data={'name': 'Updated Name'})",
                    "partial_update": "Only provide the fields you want to update",
                    "updatable_fields": [
                        "firstName",
                        "lastName",
                        "email",
                        "status",
                        "organizationIds",
                    ],
                    "role_behavior": "roles field can be provided but backend enforces ROLE_API_CONSUMER only",
                    "billing_safety": "🔒 BILLING SAFETY: Partial updates preserve existing subscriber configuration while changing specific fields",
                    "backend_enforcement": "⚠️ BACKEND RULE: API will reject any roles other than ['ROLE_API_CONSUMER']",
                },
            )

        # Log role update attempts for debugging (backend will enforce validation)
        if "roles" in subscriber_data:
            provided_roles = subscriber_data.get("roles", [])
            logger.info(
                f"Subscriber {subscriber_id} role update requested: {provided_roles} (backend will validate)"
            )
            # Note: No MCP-level enforcement - let backend API handle role validation

        # Get update configuration for subscribers
        config = self.update_config_factory.get_config("customers", customer_type="subscriber")

        # Use PartialUpdateHandler for the update operation
        result = await self.update_handler.update_with_merge(
            resource_id=subscriber_id,
            partial_data=subscriber_data,
            config=config,
            action_context="update subscriber",
        )

        # Fix undefined values in callCountElementDefinition structure
        self._populate_call_count_element_definition(result)
        # Enhance response to show enforced role for transparency
        result = self._enhance_subscriber_response(result)
        return result

    def _enhance_subscriber_response(self, subscriber_data: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance subscriber response to show enforced role for transparency.

        Since the backend API doesn't return the roles field for subscribers,
        but we know all subscribers must have ROLE_API_CONSUMER, we add this
        field to the response for consistency and transparency.

        Args:
            subscriber_data: Raw subscriber data from API

        Returns:
            Enhanced subscriber data with roles field
        """
        if isinstance(subscriber_data, dict):
            # Check if this is a subscriber by looking for subscriberId field
            if "subscriberId" in subscriber_data and subscriber_data["subscriberId"] is not None:
                # Only add roles if not already present
                if "roles" not in subscriber_data:
                    subscriber_data = subscriber_data.copy()
                    subscriber_data["roles"] = ["ROLE_API_CONSUMER"]
        return subscriber_data

    async def delete_subscriber(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Delete subscriber."""
        subscriber_id = arguments.get("subscriber_id")
        if not subscriber_id:
            raise create_structured_missing_parameter_error(
                parameter_name="subscriber_id",
                action="delete subscriber",
                examples={
                    "usage": "delete(resource_type='subscribers', subscriber_id='sub_123')",
                    "valid_format": "Subscriber ID should be a string identifier",
                    "example_ids": ["sub_123", "subscriber_456", "customer_789"],
                    "warning": "This action permanently removes the subscriber from the organization",
                    "billing_safety": "🔒 BILLING SAFETY: Subscriber deletion permanently affects billing identity and subscription relationships",
                },
            )

        result = await self.client.delete_subscriber(subscriber_id)
        return result


class OrganizationManager(BaseManager):
    """Internal manager for organization operations."""

    async def list_organizations(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List organizations with pagination."""
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters = arguments.get("filters", {})

        response = await self.client.get_organizations(page=page, size=size, **filters)
        organizations = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)

        # Fix undefined values in callCountElementDefinition structures
        self._populate_call_count_definitions_in_list(organizations)

        return {
            "action": "list",
            "resource_type": "organizations",
            "organizations": organizations,
            "pagination": page_info,
            "total_found": len(organizations),
        }

    async def get_organization(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get specific organization by ID."""
        organization_id = arguments.get("organization_id")
        if not organization_id:
            raise create_structured_missing_parameter_error(
                parameter_name="organization_id",
                action="get organization",
                examples={
                    "usage": "get(resource_type='organizations', organization_id='org_123')",
                    "valid_format": "Organization ID should be a string identifier",
                    "example_ids": ["org_123", "company_456", "enterprise_789"],
                },
            )

        try:
            organization = await self.client.get_organization_by_id(organization_id)
        except ReveniumAPIError as e:
            if e.status_code == 404:
                raise ToolError(
                    message=f"Organization not found for id: {organization_id}",
                    error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                    field="organization_id",
                    value=organization_id,
                    suggestions=[
                        "Verify the organization ID exists using list(resource_type='organizations')",
                        "Check if the organization was recently deleted",
                        "Use get_examples() to see valid organization ID formats",
                    ],
                )
            elif e.status_code == 400:
                raise ToolError(
                    message=f"Invalid organization ID format: {organization_id}",
                    error_code=ErrorCodes.VALIDATION_ERROR,
                    field="organization_id",
                    value=organization_id,
                    suggestions=[
                        "Organization IDs should be 6-character alphanumeric strings (e.g., '6PV2LR')",
                        "Use list(resource_type='organizations') to see valid organization IDs",
                        "Check the ID format - it should not contain special characters",
                    ],
                )
            else:
                # Re-raise other API errors as-is
                raise

        # Fix undefined values in callCountElementDefinition structure
        self._populate_call_count_element_definition(organization)

        return organization

    async def create_organization(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create new organization."""
        organization_data = arguments.get("organization_data")
        if not organization_data:
            raise create_structured_missing_parameter_error(
                parameter_name="organization_data",
                action="create organization",
                examples={
                    "usage": "create(resource_type='organizations', organization_data={'name': 'Acme Corp'})",
                    "required_fields": ["name"],
                    "example_data": {
                        "name": "Acme Corp",
                        "description": "Technology company",
                        "status": "active",
                    },
                    "billing_safety": "🔒 BILLING SAFETY: Organization creation establishes primary billing entity and customer hierarchy",
                    "api_requirements": "API requires tenantId, parentId, and metadata fields - these are auto-populated from environment",
                },
            )

        # Add required API fields from client environment
        # The organization API requires these specific fields in the request body
        if "tenantId" not in organization_data:
            organization_data["tenantId"] = (
                self.client.auth_config.tenant_id or self.client.auth_config.team_id
            )

        if "parentId" not in organization_data:
            # Use the team_id as the parent organization ID (this is the standard pattern)
            organization_data["parentId"] = self.client.team_id

        if "metadata" not in organization_data:
            # API requires metadata field, even if empty
            organization_data["metadata"] = ""

        result = await self.client.create_organization(organization_data)
        # Fix undefined values in callCountElementDefinition structure
        self._populate_call_count_element_definition(result)
        return result

    async def update_organization(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Update existing organization using PartialUpdateHandler."""
        organization_id = arguments.get("organization_id")
        organization_data = arguments.get("organization_data")

        # Basic parameter validation (PartialUpdateHandler will provide detailed errors)
        if not organization_id:
            raise create_structured_missing_parameter_error(
                parameter_name="organization_id",
                action="update organization",
                examples={
                    "usage": "update(resource_type='organizations', organization_id='org_123', organization_data={'name': 'Updated Corp'})",
                    "note": "Now supports partial updates - only provide fields you want to change",
                    "billing_safety": "🔒 BILLING SAFETY: Organization updates can affect billing entity configuration and customer hierarchy",
                },
            )

        if not organization_data:
            raise create_structured_missing_parameter_error(
                parameter_name="organization_data",
                action="update organization",
                examples={
                    "usage": "update(resource_type='organizations', organization_id='org_123', organization_data={'name': 'Updated Corp'})",
                    "partial_update": "Only provide the fields you want to update",
                    "updatable_fields": ["name", "domain", "type", "status"],
                    "billing_safety": "🔒 BILLING SAFETY: Partial updates preserve existing organization configuration while changing specific fields",
                },
            )

        # Get update configuration for organizations
        config = self.update_config_factory.get_config("customers", customer_type="organization")

        # Use PartialUpdateHandler for the update operation
        result = await self.update_handler.update_with_merge(
            resource_id=organization_id,
            partial_data=organization_data,
            config=config,
            action_context="update organization",
        )

        # Fix undefined values in callCountElementDefinition structure
        self._populate_call_count_element_definition(result)
        return result

    async def delete_organization(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Delete organization."""
        organization_id = arguments.get("organization_id")
        if not organization_id:
            raise create_structured_missing_parameter_error(
                parameter_name="organization_id",
                action="delete organization",
                examples={
                    "usage": "delete(resource_type='organizations', organization_id='org_123')",
                    "valid_format": "Organization ID should be a string identifier",
                    "example_ids": ["org_123", "company_456", "enterprise_789"],
                    "warning": "This action permanently removes the organization and all associated data",
                    "billing_safety": "🔒 BILLING SAFETY: Organization deletion permanently removes billing entity and all customer relationships",
                },
            )

        result = await self.client.delete_organization(organization_id)
        return result


class TeamManager(BaseManager):
    """Internal manager for team operations."""

    async def list_teams(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List teams with pagination."""
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters = arguments.get("filters", {})

        response = await self.client.get_teams(page=page, size=size, **filters)
        teams = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)

        # Fix undefined values in callCountElementDefinition structures
        self._populate_call_count_definitions_in_list(teams)

        return {
            "action": "list",
            "resource_type": "teams",
            "teams": teams,
            "pagination": page_info,
            "total_found": len(teams),
        }

    async def get_team(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get specific team by ID."""
        team_id = arguments.get("team_id")
        if not team_id:
            raise create_structured_missing_parameter_error(
                parameter_name="team_id",
                action="get team",
                examples={
                    "usage": "get(resource_type='teams', team_id='team_123')",
                    "valid_format": "Team ID should be a string identifier",
                    "example_ids": ["team_123", "dev_team_456", "support_789"],
                },
            )

        try:
            team = await self.client.get_team_by_id(team_id)
        except ReveniumAPIError as e:
            if e.status_code == 404:
                raise ToolError(
                    message=f"Team not found for id: {team_id}",
                    error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                    field="team_id",
                    value=team_id,
                    suggestions=[
                        "Verify the team ID exists using list(resource_type='teams')",
                        "Check if the team was recently deleted",
                        "Use get_examples() to see valid team ID formats",
                    ],
                )
            elif e.status_code == 400:
                raise ToolError(
                    message=f"Invalid team ID format: {team_id}",
                    error_code=ErrorCodes.VALIDATION_ERROR,
                    field="team_id",
                    value=team_id,
                    suggestions=[
                        "Team IDs should be 6-character alphanumeric strings (e.g., 'XLnk1P')",
                        "Use list(resource_type='teams') to see valid team IDs",
                        "Check the ID format - it should not contain special characters",
                    ],
                )
            else:
                # Re-raise other API errors as-is
                raise

        # Fix undefined values in callCountElementDefinition structure
        self._populate_call_count_element_definition(team)

        return team

    async def create_team(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create new team."""
        team_data = arguments.get("team_data")
        if not team_data:
            raise create_structured_missing_parameter_error(
                parameter_name="team_data",
                action="create team",
                examples={
                    "usage": "create(resource_type='teams', team_data={'name': 'Development Team', 'organization_id': 'org_123'})",
                    "required_fields": ["name", "organization_id"],
                    "example_data": {
                        "name": "Development Team",
                        "organization_id": "org_123",
                        "description": "Main dev team",
                    },
                    "billing_safety": "🔒 BILLING SAFETY: Team creation affects organizational structure and access control for billing",
                },
            )

        # Add required fields from client environment
        if "teamId" not in team_data:
            team_data["teamId"] = self.client.team_id
        if "ownerId" not in team_data:
            owner_id = get_config_value("REVENIUM_OWNER_ID")
            if owner_id:
                team_data["ownerId"] = owner_id
            else:
                # Skip ownerId if not available - let API handle default
                logger.warning(
                    "REVENIUM_OWNER_ID not available from configuration store, API will use default owner"
                )

        result = await self.client.create_team(team_data)
        # Fix undefined values in callCountElementDefinition structure
        self._populate_call_count_element_definition(result)
        return result

    async def update_team(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Update existing team using PartialUpdateHandler."""
        team_id = arguments.get("team_id")
        team_data = arguments.get("team_data")

        # Basic parameter validation (PartialUpdateHandler will provide detailed errors)
        if not team_id:
            raise create_structured_missing_parameter_error(
                parameter_name="team_id",
                action="update team",
                examples={
                    "usage": "update(resource_type='teams', team_id='team_123', team_data={'name': 'Updated Team'})",
                    "note": "Now supports partial updates - only provide fields you want to change",
                    "billing_safety": "🔒 BILLING SAFETY: Team updates can affect organizational structure and access control",
                },
            )

        if not team_data:
            raise create_structured_missing_parameter_error(
                parameter_name="team_data",
                action="update team",
                examples={
                    "usage": "update(resource_type='teams', team_id='team_123', team_data={'name': 'Updated Team'})",
                    "partial_update": "Only provide the fields you want to update",
                    "updatable_fields": ["name", "description", "status"],
                    "billing_safety": "🔒 BILLING SAFETY: Partial updates preserve existing team configuration while changing specific fields",
                },
            )

        # Get update configuration for teams
        config = self.update_config_factory.get_config("customers", customer_type="team")

        # Use PartialUpdateHandler for the update operation
        result = await self.update_handler.update_with_merge(
            resource_id=team_id, partial_data=team_data, config=config, action_context="update team"
        )

        # Fix undefined values in callCountElementDefinition structure
        self._populate_call_count_element_definition(result)
        return result

    async def delete_team(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Delete team."""
        team_id = arguments.get("team_id")
        if not team_id:
            raise create_structured_missing_parameter_error(
                parameter_name="team_id",
                action="delete team",
                examples={
                    "usage": "delete(resource_type='teams', team_id='team_123')",
                    "valid_format": "Team ID should be a string identifier",
                    "example_ids": ["team_123", "dev_team_456", "support_789"],
                    "warning": "This action permanently removes the team and all associated data",
                    "billing_safety": "🔒 BILLING SAFETY: Team deletion permanently affects organizational structure and access control",
                },
            )

        result = await self.client.delete_team(team_id)
        return result


class CustomerValidator:
    """Internal manager for customer validation and schema discovery with UCM integration."""

    def __init__(self, ucm_integration_helper=None) -> None:
        """Initialize customer validator.

        Args:
            ucm_integration_helper: UCM integration helper for capability management
        """
        self.ucm_helper = ucm_integration_helper

        try:
            from ..schema_discovery import CustomerSchemaDiscovery

            self.schema_discovery = CustomerSchemaDiscovery()
        except ImportError:
            logger.warning("CustomerSchemaDiscovery not available, using fallback")
            self.schema_discovery = None

    async def get_capabilities(self) -> Dict[str, Any]:
        """Get customer capabilities using UCM or fallback."""
        if self.ucm_helper:
            try:
                ucm_capabilities = await self.ucm_helper.ucm.get_capabilities("customers")
                # Override UCM subscriber fields with correct API requirements
                if "schemas" in ucm_capabilities and "subscribers" in ucm_capabilities["schemas"]:
                    ucm_capabilities["schemas"]["subscribers"] = {
                        "required": ["email", "firstName", "lastName", "organizationIds", "roles"],
                        "optional": ["status"],
                    }
                return ucm_capabilities
            except Exception as e:
                logger.warning(f"UCM capabilities failed, using fallback: {e}")

        # Fallback to schema discovery or hardcoded values
        if self.schema_discovery:
            schema_capabilities = self.schema_discovery.get_customer_capabilities()
            # Override schema discovery subscriber fields with correct API requirements
            if "schemas" in schema_capabilities and "subscribers" in schema_capabilities["schemas"]:
                schema_capabilities["schemas"]["subscribers"] = {
                    "required": ["email", "firstName", "lastName", "organizationIds", "roles"],
                    "optional": ["status"],
                }
            return schema_capabilities

        # Final fallback to conservative hardcoded values
        return {
            "resource_types": ["organizations", "subscribers", "users", "teams"],
            "user_roles": ["ROLE_API_CONSUMER"],  # Only valid role for subscribers/users
            "organization_types": ["ENTERPRISE", "STANDARD", "TRIAL"],  # UCM-compatible format
            "user_statuses": ["ACTIVE", "INACTIVE", "PENDING"],  # UCM-compatible format
            "user_fields": {
                "required": ["email", "firstName", "lastName", "roles"],
                "optional": ["status", "organizationId", "teamId"],
            },
            "subscriber_fields": {
                "required": ["email", "firstName", "lastName", "organizationIds", "roles"],
                "optional": ["status"],
            },
            "organization_fields": {
                "required": ["name"],
                "optional": ["description", "status"],
                "auto_populated": ["tenantId", "parentId", "metadata"],
                "note": "✅ FIXED: API-required fields (tenantId, parentId, metadata) are automatically populated from environment",
            },
            "team_fields": {
                "required": ["name", "organizationId"],
                "optional": ["description", "status"],
            },
            "validation_rules": {
                "email": {"type": "string", "format": "email"},
                "firstName": {"type": "string", "min_length": 1, "max_length": 255},
                "lastName": {"type": "string", "min_length": 1, "max_length": 255},
                "organizationId": {"type": "string", "format": "uuid"},
            },
            "id_parameter_requirements": {
                "CRITICAL": "Customer management uses DIFFERENT ID parameters than other tools",
                "organizations": "Uses REVENIUM_TENANT_ID (tenantId parameter)",
                "subscribers": "Uses REVENIUM_TENANT_ID (tenantId parameter)",
                "teams": "Uses REVENIUM_TENANT_ID (tenantId parameter)",
                "users": "Uses REVENIUM_TEAM_ID (teamId parameter)",
                "troubleshooting": {
                    "404_tenant_not_found": "Check REVENIUM_TENANT_ID environment variable",
                    "403_forbidden": "Check REVENIUM_API_KEY environment variable",
                    "parameter_confusion": "Customer management requires BOTH REVENIUM_TEAM_ID and REVENIUM_TENANT_ID",
                },
            },
            "business_rules": [
                "Email addresses must be unique within the system",
                "Organization names should be unique within the team",
                "When created, subscribers should use the parent_organization_id of the organization they belong to properly associate users to their parent organization",
                "Users can belong to multiple teams within an organization",
                "Organizations can have hierarchical structures with parent-child relationships",
                "Teams can have hierarchical structures within a Revenium tenant (Enterprise accounts only)",
            ],
        }

    def get_examples(self, resource_type: Optional[str] = None) -> Dict[str, Any]:
        """Get customer examples."""
        # Define static examples as fallback
        static_examples = {
            "users": {
                "name": "Create User",
                "description": "Create a new user account with required roles field",
                "template": {
                    "email": "user@example.com",
                    "firstName": "John",
                    "lastName": "Doe",
                    "roles": ["ROLE_API_CONSUMER"],
                },
                "note": "⚠️ CRITICAL: roles field is required - ROLE_API_CONSUMER is the only valid role for users/subscribers",
            },
            "subscribers": {
                "name": "Create Subscriber",
                "description": "Create a new subscriber with required roles and organizationIds fields",
                "template": {
                    "email": "subscriber@example.com",
                    "firstName": "Jane",
                    "lastName": "Smith",
                    "subscriberId": "unique_subscriber_id_123",
                    "organizationIds": ["org_id_123"],
                    "roles": ["ROLE_API_CONSUMER"],
                },
                "note": "⚠️ REQUIRED: First use list action with resource_type='organizations' to get valid organization ID, then replace 'org_id_123' with actual ID",
            },
            "organizations": {
                "name": "Create Organization",
                "description": "Create a new organization (tenantId, parentId, and metadata are auto-populated)",
                "template": {
                    "name": "Acme Corporation",
                    "description": "Technology company",
                    "status": "active",
                },
                "note": "✅ FIXED: Required API fields (tenantId, parentId, metadata) are automatically added from environment",
            },
            "teams": {
                "name": "Create Team",
                "description": "Create a new team within an organization",
                "template": {
                    "name": "Development Team",
                    "description": "Software development team",
                    "organizationId": "org_123",
                    "status": "active",
                },
            },
        }

        # Try schema discovery first if available
        if self.schema_discovery:
            try:
                schema_examples = self.schema_discovery.get_customer_examples(resource_type)
                # Check if schema discovery returned useful examples
                if (
                    schema_examples
                    and schema_examples.get("examples")
                    and len(schema_examples["examples"]) > 0
                ):
                    # If requesting all examples or subscribers specifically, ensure subscriber examples are included
                    if not resource_type or resource_type == "subscribers":
                        # Add our static subscriber example to ensure organizationIds is shown
                        if "examples" not in schema_examples:
                            schema_examples["examples"] = []
                        # Check if subscriber example with organizationIds already exists
                        has_proper_subscriber = any(
                            "organizationIds" in str(ex.get("template", {}))
                            for ex in schema_examples["examples"]
                        )
                        if not has_proper_subscriber:
                            # Insert our subscriber example at the beginning for visibility
                            schema_examples["examples"].insert(0, static_examples["subscribers"])
                    return schema_examples
            except Exception:
                # Fall back to static examples if schema discovery fails
                pass

        # Use static examples as fallback
        if resource_type and resource_type in static_examples:
            return {"examples": [static_examples[resource_type]]}

        return {"examples": list(static_examples.values())}

    async def validate_configuration(
        self, resource_type: str, resource_data: Dict[str, Any], dry_run: bool = True
    ) -> Dict[str, Any]:
        """Validate customer configuration using UCM-only validation."""
        if not self.schema_discovery:
            # No fallbacks - force proper UCM integration
            raise ToolError(
                message="Customer validation unavailable - no schema discovery integration",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="schema_discovery",
                value="missing",
                suggestions=[
                    "Ensure customer management is initialized with proper schema discovery",
                    "Use customer management validation to check your configuration",
                    "Check that the customer management service is properly configured",
                    "Verify API connectivity and authentication",
                ],
                examples={
                    "validation_commands": "Get validation rules: manage_customers(action='get_capabilities')",
                    "validate_config": "Validate configuration: manage_customers(action='validate', resource_type='organizations', resource_data={...})",
                    "alternative": "Use API validation during create/update operations",
                },
            )

        return self.schema_discovery.validate_customer_configuration(
            resource_data, resource_type, dry_run
        )

    def get_roles(self) -> Dict[str, Any]:
        """Get available roles by resource type."""
        return {
            "roles_by_resource_type": {
                "users": {
                    "available_roles": [
                        {
                            "name": "ROLE_TENANT_ADMIN",
                            "description": "Tenant administrator with full access to tenant resources",
                            "permissions": [
                                "Full tenant management",
                                "User management",
                                "Resource creation/modification",
                            ],
                            "usage": "For administrative users who need full control over the tenant",
                        },
                        {
                            "name": "ROLE_API_CONSUMER",
                            "description": "API consumer role for programmatic access",
                            "permissions": ["API access", "Resource consumption"],
                            "usage": "For users or services that consume APIs programmatically",
                        },
                    ],
                    "role_requirements": [
                        "At least one role must be specified when creating users",
                        "Multiple roles can be assigned to a single user",
                        "Role names are case-sensitive and must match exactly",
                    ],
                },
                "subscribers": {
                    "available_roles": [
                        {
                            "name": "ROLE_API_CONSUMER",
                            "description": "API consumer role for programmatic access (ONLY role allowed for subscribers)",
                            "permissions": ["API access", "Resource consumption"],
                            "usage": "Required field that must be explicitly provided - no other roles permitted",
                        }
                    ],
                    "role_requirements": [
                        "ROLE_API_CONSUMER must be explicitly provided in the roles field (API requirement)",
                        "No other roles are permitted for subscribers",
                        "Agents MUST specify roles: ['ROLE_API_CONSUMER'] when creating subscribers",
                    ],
                },
            },
            "examples": {
                "admin_user": {
                    "resource_type": "users",
                    "roles": ["ROLE_TENANT_ADMIN"],
                    "use_case": "Administrative user with full tenant access",
                },
                "api_user": {
                    "resource_type": "users",
                    "roles": ["ROLE_API_CONSUMER"],
                    "use_case": "Service account for API access",
                },
                "power_user": {
                    "resource_type": "users",
                    "roles": ["ROLE_TENANT_ADMIN", "ROLE_API_CONSUMER"],
                    "use_case": "User with both administrative and API access",
                },
                "subscriber": {
                    "resource_type": "subscribers",
                    "roles": ["ROLE_API_CONSUMER"],
                    "use_case": "Subscriber for billing and API access (roles field required)",
                },
            },
            "important_note": "⚠️ SUBSCRIBERS can only have ROLE_API_CONSUMER - this must be explicitly provided in the roles field",
        }


class CustomerAnalytics:
    """Internal processor for customer analytics and relationships."""

    def __init__(self, client: ReveniumClient) -> None:
        """Initialize analytics processor."""
        self.client = client

    async def analyze_customers(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze customer data and relationships."""
        resource_type = arguments.get("resource_type", "organizations")
        page = arguments.get("page", 0)
        size = arguments.get("size", 100)  # Get more for analysis
        filters = arguments.get("filters", {})

        if resource_type == "users":
            response = await self.client.get_users(page=page, size=size, **filters)
            resources = self.client._extract_embedded_data(response)
            page_info = self.client._extract_pagination_info(response)

            total_resources = page_info.get("totalElements", len(resources))
            active_resources = len([r for r in resources if r.get("status") == "active"])

            analytics = {
                "resource_type": resource_type,
                "total_users": total_resources,
                "active_users": active_resources,
                "inactive_users": total_resources - active_resources,
                "activity_rate": (
                    (active_resources / total_resources * 100) if total_resources > 0 else 0
                ),
                "sample_size": len(resources),
                "organizations_represented": len(
                    set(r.get("organizationId") for r in resources if r.get("organizationId"))
                ),
                "teams_represented": len(
                    set(r.get("teamId") for r in resources if r.get("teamId"))
                ),
            }

        elif resource_type == "subscribers":
            response = await self.client.get_subscribers(page=page, size=size, **filters)
            resources = self.client._extract_embedded_data(response)
            page_info = self.client._extract_pagination_info(response)

            total_resources = page_info.get("totalElements", len(resources))
            active_resources = len([r for r in resources if r.get("status") == "active"])
            trial_resources = len([r for r in resources if r.get("status") == "trial"])

            analytics = {
                "resource_type": resource_type,
                "total_subscribers": total_resources,
                "active_subscribers": active_resources,
                "trial_subscribers": trial_resources,
                "inactive_subscribers": total_resources - active_resources - trial_resources,
                "conversion_rate": (
                    (active_resources / total_resources * 100) if total_resources > 0 else 0
                ),
                "trial_rate": (
                    (trial_resources / total_resources * 100) if total_resources > 0 else 0
                ),
                "sample_size": len(resources),
                "organizations_represented": len(
                    set(r.get("organizationId") for r in resources if r.get("organizationId"))
                ),
            }

        elif resource_type == "organizations":
            response = await self.client.get_organizations(page=page, size=size, **filters)
            resources = self.client._extract_embedded_data(response)
            page_info = self.client._extract_pagination_info(response)

            total_resources = page_info.get("totalElements", len(resources))
            active_resources = len([r for r in resources if r.get("status") == "active"])

            analytics = {
                "resource_type": resource_type,
                "total_organizations": total_resources,
                "active_organizations": active_resources,
                "inactive_organizations": total_resources - active_resources,
                "activity_rate": (
                    (active_resources / total_resources * 100) if total_resources > 0 else 0
                ),
                "sample_size": len(resources),
                "hierarchical_organizations": len(
                    [r for r in resources if r.get("parentOrganizationId")]
                ),
            }

        elif resource_type == "teams":
            response = await self.client.get_teams(page=page, size=size, **filters)
            resources = self.client._extract_embedded_data(response)
            page_info = self.client._extract_pagination_info(response)

            total_resources = page_info.get("totalElements", len(resources))
            active_resources = len([r for r in resources if r.get("status") == "active"])

            analytics = {
                "resource_type": resource_type,
                "total_teams": total_resources,
                "active_teams": active_resources,
                "inactive_teams": total_resources - active_resources,
                "activity_rate": (
                    (active_resources / total_resources * 100) if total_resources > 0 else 0
                ),
                "sample_size": len(resources),
                "organizations_represented": len(
                    set(r.get("organizationId") for r in resources if r.get("organizationId"))
                ),
            }

        else:
            raise create_structured_validation_error(
                message=f"Unknown resource type for analysis: {resource_type}",
                field="resource_type",
                value=resource_type,
                suggestions=[
                    "Use one of the supported resource types for analytics",
                    "Check the resource_type parameter for typos",
                    "Ensure the resource type is valid for customer analytics",
                ],
                examples={
                    "valid_resource_types": ["users", "subscribers", "organizations", "teams"],
                    "usage": "get_analytics(resource_type='users', ...)",
                    "analytics_types": [
                        "user_activity",
                        "subscription_metrics",
                        "organization_growth",
                    ],
                },
            )

        return analytics

    async def get_relationships(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get customer relationships and hierarchies."""
        resource_type = arguments.get("resource_type")
        resource_id = (
            arguments.get("resource_id")
            or arguments.get("user_id")
            or arguments.get("subscriber_id")
            or arguments.get("organization_id")
            or arguments.get("team_id")
        )

        if not resource_type or not resource_id:
            missing_params = []
            if not resource_type:
                missing_params.append("resource_type")
            if not resource_id:
                missing_params.append("resource_id")

            raise create_structured_missing_parameter_error(
                parameter_name=" and ".join(missing_params),
                action="get_relationships",
                examples={
                    "usage": "get_relationships(resource_type='users', resource_id='user_123')",
                    "valid_resource_types": ["users", "subscribers", "organizations", "teams"],
                    "example_calls": [
                        "get_relationships(resource_type='users', resource_id='user_123')",
                        "get_relationships(resource_type='organizations', resource_id='org_456')",
                    ],
                },
            )

        relationships = {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "relationships": [],
        }

        # This is a placeholder implementation
        # In a real implementation, this would query the API for related resources
        relationships["relationships"].append(
            {
                "type": "placeholder",
                "message": "Relationship mapping functionality is not yet implemented",
                "suggestion": "Use list operations to explore related resources manually",
            }
        )

        return relationships


class CustomerManagement(ToolBase):
    """Consolidated customer management tool with internal composition."""

    tool_name = "manage_customers"
    tool_description = "Customer lifecycle management: organizations (customers), subscribers (API consumers), users (platform admins), teams (groups). Key actions: list, get, create, update, delete. Use get_capabilities() for complete action list."
    business_category = "Core Business Management Tools"
    tool_type = ToolType.CRUD
    tool_version = "2.0.0"

    def __init__(self, ucm_helper=None) -> None:
        """Initialize consolidated customer management.

        Args:
            ucm_helper: UCM integration helper for capability management
        """
        super().__init__(ucm_helper)
        self.formatter = UnifiedResponseFormatter("manage_customers")
        self.validator = CustomerValidator(ucm_helper)

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle customer management actions with intelligent routing."""
        try:
            # Get client and initialize managers
            client = await self.get_client()
            user_manager = UserManager(client)
            subscriber_manager = SubscriberManager(client)
            organization_manager = OrganizationManager(client)
            team_manager = TeamManager(client)
            analytics_processor = CustomerAnalytics(client)

            # Handle introspection actions
            if action == "get_tool_metadata":
                metadata = await self.get_tool_metadata()
                return [TextContent(type="text", text=json.dumps(metadata.to_dict(), indent=2))]

            # Get resource type for routing
            resource_type = arguments.get("resource_type", "organizations")

            # Route to appropriate manager based on resource type and action
            if action == "list":
                if resource_type == "users":
                    result = await user_manager.list_users(arguments)
                elif resource_type == "subscribers":
                    result = await subscriber_manager.list_subscribers(arguments)
                elif resource_type == "organizations":
                    result = await organization_manager.list_organizations(arguments)
                elif resource_type == "teams":
                    result = await team_manager.list_teams(arguments)
                else:
                    raise create_structured_validation_error(
                        message=f"Unknown resource type: {resource_type}",
                        field="resource_type",
                        value=resource_type,
                        suggestions=[
                            "Use one of the supported resource types",
                            "Check the resource_type parameter for typos",
                            "Ensure the resource type is valid for customer management",
                        ],
                        examples={
                            "valid_resource_types": [
                                "organizations",
                                "subscribers",
                                "users",
                                "teams",
                            ],
                            "usage": "list(resource_type='organizations')",
                            "example_calls": [
                                "list(resource_type='organizations')",
                                "list(resource_type='subscribers')",
                            ],
                            "billing_safety": "🔒 BILLING SAFETY: Correct resource type ensures proper customer data management",
                        },
                    )

                return [
                    TextContent(
                        type="text",
                        text=f"Found {result['total_found']} {resource_type} (page {arguments.get('page', 0) + 1}):\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "get":
                if resource_type == "users":
                    result = await user_manager.get_user(arguments)
                    identifier = arguments.get("user_id") or arguments.get("email")
                elif resource_type == "subscribers":
                    result = await subscriber_manager.get_subscriber(arguments)
                    identifier = arguments.get("subscriber_id") or arguments.get("email")
                elif resource_type == "organizations":
                    result = await organization_manager.get_organization(arguments)
                    identifier = arguments.get("organization_id")
                elif resource_type == "teams":
                    result = await team_manager.get_team(arguments)
                    identifier = arguments.get("team_id")
                else:
                    raise create_structured_validation_error(
                        message=f"Unknown resource type: {resource_type}",
                        field="resource_type",
                        value=resource_type,
                        suggestions=[
                            "Use one of the supported resource types",
                            "Check the resource_type parameter for typos",
                            "Ensure the resource type is valid for customer management",
                        ],
                        examples={
                            "valid_resource_types": [
                                "organizations",
                                "subscribers",
                                "users",
                                "teams",
                            ],
                            "usage": "get(resource_type='organizations', organization_id='org_123')",
                            "example_calls": [
                                "get(resource_type='organizations', organization_id='org_123')",
                                "get(resource_type='subscribers', subscriber_id='sub_456')",
                            ],
                            "billing_safety": "🔒 BILLING SAFETY: Correct resource type ensures proper customer data retrieval",
                        },
                    )

                return [
                    TextContent(
                        type="text",
                        text=f"{resource_type.title()} details for {identifier}:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "create":
                # Handle unified resource_data container pattern
                resource_data = arguments.get("resource_data", {})
                auto_generate = arguments.get("auto_generate", True)
                dry_run = arguments.get("dry_run", False)

                # Legacy data fallback (deprecated)
                if not resource_data:
                    resource_data = (
                        arguments.get("user_data")
                        or arguments.get("subscriber_data")
                        or arguments.get("organization_data")
                        or arguments.get("team_data")
                        or {}
                    )

                # PROGRESSIVE COMPLEXITY: Auto-generate missing fields based on mode
                if auto_generate and resource_data:
                    resource_data = self._apply_auto_generation(
                        resource_data, resource_type, arguments
                    )

                # Handle dry_run mode for create operations
                if dry_run:
                    return [
                        TextContent(
                            type="text",
                            text="🧪 **DRY RUN MODE - Customer Creation**\n\n"
                            f"✅ **Would create {resource_type.rstrip('s')}:**\n"
                            f"**Auto-Generate Mode:** {auto_generate}\n"
                            f"**Resource Data:** {json.dumps(resource_data, indent=2)}\n\n"
                            "**Dry Run:** True (no actual creation performed)\n\n"
                            f"**Tip:** Remove dry_run parameter to perform actual creation",
                        )
                    ]

                # Map resource_data to legacy format for managers
                legacy_arguments = arguments.copy()
                if resource_type == "users":
                    legacy_arguments["user_data"] = resource_data
                    result = await user_manager.create_user(legacy_arguments)
                elif resource_type == "subscribers":
                    legacy_arguments["subscriber_data"] = resource_data
                    result = await subscriber_manager.create_subscriber(legacy_arguments)
                elif resource_type == "organizations":
                    legacy_arguments["organization_data"] = resource_data
                    result = await organization_manager.create_organization(legacy_arguments)
                elif resource_type == "teams":
                    legacy_arguments["team_data"] = resource_data
                    result = await team_manager.create_team(legacy_arguments)
                else:
                    raise create_structured_validation_error(
                        message=f"Unknown resource type: {resource_type}",
                        field="resource_type",
                        value=resource_type,
                        suggestions=[
                            "Use one of the supported resource types",
                            "Check the resource_type parameter for typos",
                            "Ensure the resource type is valid for customer management",
                        ],
                        examples={
                            "valid_resource_types": [
                                "organizations",
                                "subscribers",
                                "users",
                                "teams",
                            ],
                            "usage": '{"action": "create", "resource_type": "organizations", "resource_data": {"name": "Company"}}',
                            "example_calls": [
                                '{"action": "create", "resource_type": "organizations", "resource_data": {"name": "Company"}}',
                                '{"action": "create", "resource_type": "subscribers", "resource_data": {"email": "user@company.com"}}',
                            ],
                            "billing_safety": "🔒 BILLING SAFETY: Correct resource type ensures proper customer creation and billing setup",
                        },
                    )

                return [
                    TextContent(
                        type="text",
                        text=f"{resource_type.title()} created successfully:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "update":
                # Handle dry_run mode for update operations
                dry_run = arguments.get("dry_run", False)
                if dry_run:
                    resource_data = (
                        arguments.get("user_data")
                        or arguments.get("subscriber_data")
                        or arguments.get("organization_data")
                        or arguments.get("team_data")
                    )
                    identifier = (
                        arguments.get("user_id")
                        or arguments.get("subscriber_id")
                        or arguments.get("organization_id")
                        or arguments.get("team_id")
                    )
                    return [
                        TextContent(
                            type="text",
                            text="🧪 **DRY RUN MODE - Customer Update**\n\n"
                            f"✅ **Would update {resource_type.rstrip('s')}:** {identifier}\n"
                            f"**Changes:** {json.dumps(resource_data, indent=2)}\n\n"
                            f"**Dry Run:** True (no actual update performed)",
                        )
                    ]

                if resource_type == "users":
                    result = await user_manager.update_user(arguments)
                    identifier = arguments.get("user_id")
                elif resource_type == "subscribers":
                    result = await subscriber_manager.update_subscriber(arguments)
                    identifier = arguments.get("subscriber_id")
                elif resource_type == "organizations":
                    result = await organization_manager.update_organization(arguments)
                    identifier = arguments.get("organization_id")
                elif resource_type == "teams":
                    result = await team_manager.update_team(arguments)
                    identifier = arguments.get("team_id")
                else:
                    raise create_structured_validation_error(
                        message=f"Unknown resource type: {resource_type}",
                        field="resource_type",
                        value=resource_type,
                        suggestions=[
                            "Use one of the supported resource types",
                            "Check the resource_type parameter for typos",
                            "Ensure the resource type is valid for customer management",
                        ],
                        examples={
                            "valid_resource_types": [
                                "users",
                                "subscribers",
                                "organizations",
                                "teams",
                            ],
                            "usage": "update(resource_type='users', user_id='user_123', user_data={...})",
                            "example_calls": [
                                "update(resource_type='users', user_id='user_123', user_data={...})",
                                "update(resource_type='organizations', organization_id='org_456', organization_data={...})",
                            ],
                            "billing_safety": "🔒 BILLING SAFETY: Correct resource type ensures proper customer updates and billing integrity",
                        },
                    )

                return [
                    TextContent(
                        type="text",
                        text=f"{resource_type.title()} {identifier} updated successfully:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "delete":
                # Handle dry_run mode for delete operations
                dry_run = arguments.get("dry_run", False)
                if dry_run:
                    identifier = (
                        arguments.get("user_id")
                        or arguments.get("subscriber_id")
                        or arguments.get("organization_id")
                        or arguments.get("team_id")
                    )
                    return [
                        TextContent(
                            type="text",
                            text="🧪 **DRY RUN MODE - Customer Deletion**\n\n"
                            f"⚠️ **Would delete {resource_type.rstrip('s')}:** {identifier}\n\n"
                            "**Dry Run:** True (no actual deletion performed)\n\n"
                            f"⚠️ **Warning:** This action cannot be undone in real mode",
                        )
                    ]

                if resource_type == "users":
                    result = await user_manager.delete_user(arguments)
                    identifier = arguments.get("user_id")
                elif resource_type == "subscribers":
                    result = await subscriber_manager.delete_subscriber(arguments)
                    identifier = arguments.get("subscriber_id")
                elif resource_type == "organizations":
                    result = await organization_manager.delete_organization(arguments)
                    identifier = arguments.get("organization_id")
                elif resource_type == "teams":
                    result = await team_manager.delete_team(arguments)
                    identifier = arguments.get("team_id")
                else:
                    raise create_structured_validation_error(
                        message=f"Unknown resource type: {resource_type}",
                        field="resource_type",
                        value=resource_type,
                        suggestions=[
                            "Use one of the supported resource types",
                            "Check the resource_type parameter for typos",
                            "Ensure the resource type is valid for customer management",
                        ],
                        examples={
                            "valid_resource_types": [
                                "organizations",
                                "subscribers",
                                "users",
                                "teams",
                            ],
                            "usage": "delete(resource_type='organizations', organization_id='org_123')",
                            "example_calls": [
                                "delete(resource_type='organizations', organization_id='org_123')",
                                "delete(resource_type='subscribers', subscriber_id='sub_456')",
                            ],
                            "billing_safety": "🔒 BILLING SAFETY: Correct resource type ensures proper customer deletion and billing cleanup",
                        },
                    )

                return [
                    TextContent(
                        type="text",
                        text=f"{resource_type.title()} {identifier} deleted successfully:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            # Analytics and relationship operations
            elif action == "analyze":
                result = await analytics_processor.analyze_customers(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"**Customer Analytics for {resource_type.title()}**\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "get_relationships":
                result = await analytics_processor.get_relationships(arguments)
                return [
                    TextContent(
                        type="text",
                        text="**Customer Relationships**\n\n" + json.dumps(result, indent=2),
                    )
                ]

            # Validation and discovery operations
            elif action == "get_capabilities":
                capabilities = await self.validator.get_capabilities()
                return self._format_capabilities_response(capabilities)

            elif action == "get_examples":
                examples = self.validator.get_examples(arguments.get("resource_type"))
                return self._format_examples_response(examples)

            elif action == "validate":
                resource_type = arguments.get("resource_type", "organizations")
                resource_data = (
                    arguments.get("user_data")
                    or arguments.get("subscriber_data")
                    or arguments.get("organization_data")
                    or arguments.get("team_data")
                )

                if not resource_data:
                    raise create_structured_missing_parameter_error(
                        parameter_name="resource_data",
                        action="validate",
                        examples={
                            "usage": "validate(resource_type='organizations', resource_data={'name': 'Acme Corp', 'domain': 'acme.com'})",
                            "valid_resource_types": [
                                "organizations",
                                "subscribers",
                                "users",
                                "teams",
                            ],
                            "example_data": {
                                "organizations": {"name": "Acme Corp", "domain": "acme.com"},
                                "subscribers": {
                                    "email": "subscriber@company.com",
                                    "firstName": "John",
                                    "lastName": "Doe",
                                },
                            },
                            "billing_safety": "🔒 BILLING SAFETY: Validation ensures customer data integrity for billing operations",
                        },
                    )

                dry_run = arguments.get("dry_run", True)
                result = await self.validator.validate_configuration(
                    resource_type, resource_data, dry_run
                )
                return self._format_validation_response(result)

            elif action == "get_roles":
                roles = self.validator.get_roles()
                return self._format_roles_response(roles)

            elif action == "get_agent_summary":
                return await self._handle_get_agent_summary()

            else:
                # Use structured error for unknown action
                raise ToolError(
                    message=f"Unknown action '{action}' is not supported",
                    error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
                    field="action",
                    value=action,
                    suggestions=[
                        "Use get_capabilities() to see all available actions and requirements",
                        "Check the action name for typos",
                        "Use get_examples() to see working examples",
                        "For customer management, specify both action and resource_type",
                    ],
                    examples={
                        "basic_actions": ["list", "get", "create", "update", "delete"],
                        "analysis_actions": ["analyze", "get_relationships"],
                        "discovery_actions": [
                            "get_capabilities",
                            "get_examples",
                            "get_agent_summary",
                        ],
                        "validation_actions": ["validate", "get_roles"],
                        "metadata_actions": ["get_tool_metadata"],
                        "resource_types": ["organizations", "subscribers", "users", "teams"],
                        "example_usage": {
                            "list_organizations": "list(resource_type='organizations')",
                            "create_organization": "create(resource_type='organizations', organization_data={...})",
                            "get_subscriber": "get(resource_type='subscribers', subscriber_id='sub_123')",
                        },
                    },
                )

        except ToolError as e:
            logger.error(f"Tool error in manage_customers: {e}")
            # Re-raise ToolError to be handled by standardized_tool_execution
            raise e
        except ReveniumAPIError as e:
            logger.error(f"Revenium API error in manage_customers: {e}")
            # Re-raise ReveniumAPIError to be handled by standardized_tool_execution
            raise e
        except Exception as e:
            logger.error(f"Unexpected error in manage_customers: {e}")
            return self.format_error_response(e, "manage_customers")

    def _format_capabilities_response(
        self, capabilities: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format capabilities response."""
        result_text = "# **Customer Management Capabilities**\n\n"

        # CRITICAL: Parameter Organization (prevents agent confusion)
        result_text += "## **🔧 Parameter Organization** \n\n"
        result_text += "**Creation fields** must be nested in `resource_data` container:\n"
        result_text += "```json\n"
        result_text += '{"action": "create", "resource_type": "organizations", "resource_data": {"name": "Company Name"}}\n'
        result_text += "```\n\n"
        result_text += "**Top-level parameters** for tool behavior:\n"
        result_text += "- `action` - What operation to perform (default: get_capabilities)\n"
        result_text += "- `resource_type` - Type of customer resource (users, organizations, subscribers, teams)\n"
        result_text += "- `resource_id` - For get/update/delete operations\n"
        result_text += "- `auto_generate` - Enable smart defaults (default: true)\n"
        result_text += "- `dry_run` - Preview without creating (optional)\n"
        result_text += "- `page`, `size` - For list operations\n\n"

        result_text += "## **Resource Types**\n"
        for resource_type in capabilities.get("resource_types", []):
            result_text += f"- `{resource_type}`\n"

        # Add role information with resource-specific restrictions
        if capabilities.get("user_roles"):
            result_text += "\n## **Roles by Resource Type** (VERIFIED API CAPABILITIES)\n"
            result_text += "### Users\n"
            for role in capabilities.get("user_roles", []):
                if role == "ROLE_TENANT_ADMIN":
                    result_text += (
                        f"- `{role}` (returned by API, but not valid or available for customers)\n"
                    )
                else:
                    result_text += f"- `{role}`\n"
            result_text += "### Subscribers\n"
            result_text += (
                "- `ROLE_API_CONSUMER` (required field - only role allowed for subscribers)\n"
            )

        # Add organization types if available (VERIFIED API CAPABILITIES)
        if capabilities.get("organization_types"):
            result_text += "\n## **Organization Types** (VERIFIED API CAPABILITIES)\n"
            for org_type in capabilities.get("organization_types", []):
                result_text += f"- `{org_type}`\n"

        # REMOVED: user_statuses - NOT FOUND in actual Revenium API responses
        # REMOVED: team_roles - NOT FOUND in actual Revenium API responses

        result_text += "\n## **Field Requirements by Resource Type**\n"

        # Use UCM schema format instead of legacy {resource_type}_fields format
        schemas = capabilities.get("schemas", {})
        if schemas:
            for resource_type in capabilities.get("resource_types", []):
                schema = schemas.get(resource_type, {})
                if schema:
                    if resource_type == "organizations":
                        result_text += f"### {resource_type.title()} (the names of customeres or internal business units)\n"
                    elif resource_type == "teams":
                        result_text += f"### {resource_type.title()} (a concept for a group of users within a Revenium tenant)\n  Note: non-enterprise accounts (the majority, can have only a single team)\n"
                    else:
                        result_text += f"### {resource_type.title()}\n"
                    result_text += "**Required Fields**:\n"
                    for field in schema.get("required", []):
                        result_text += f"- `{field}`\n"
                    result_text += "**Optional Fields**:\n"
                    for field in schema.get("optional", []):
                        result_text += f"- `{field}`\n"
                    result_text += "\n"
        else:
            # Fallback to legacy format if UCM schemas not available
            for resource_type in capabilities.get("resource_types", []):
                field_config = capabilities.get(f"{resource_type}_fields", {})
                if field_config:
                    if resource_type == "organizations":
                        result_text += f"### {resource_type.title()} (the names of customeres or internal business units)\n"
                    elif resource_type == "teams":
                        result_text += f"### {resource_type.title()} (a concept for a group of users within a Revenium tenant)\n  Note: non-enterprise accounts (the majority, can have only a single team)\n"
                    else:
                        result_text += f"### {resource_type.title()}\n"
                    result_text += "**Required Fields**:\n"
                    for field in field_config.get("required", []):
                        result_text += f"- `{field}`\n"
                    result_text += "**Optional Fields**:\n"
                    for field in field_config.get("optional", []):
                        result_text += f"- `{field}`\n"
                    result_text += "\n"

        result_text += "## **Business Rules**\n"
        for rule in capabilities.get("business_rules", []):
            result_text += f"- {rule}\n"

        result_text += "\n## **Next Steps**\n"
        result_text += "1. Use `get_roles()` to see detailed user role information\n"
        result_text += "2. Use `get_examples(resource_type='...')` to see working templates\n"
        result_text += (
            "3. Use `validate(resource_type='...', ...data={...})` to test configurations\n"
        )
        result_text += "4. Use `create(resource_type='...', ...data={...})` to create resources\n"

        return [TextContent(type="text", text=result_text)]

    def _format_examples_response(
        self, examples: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format examples response."""
        result_text = "# **Customer Management Examples**\n\n"

        if "error" in examples:
            # Handle error case by raising proper exception instead of string formatting
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
                    "Verify the example type is supported for customer management",
                    "Check the spelling of the example type parameter",
                ],
                examples={
                    "available_types": available_types,
                    "usage": "get_examples(example_type='basic')",
                    "common_types": ["basic", "advanced", "validation", "relationships"],
                },
            )

        for i, example in enumerate(examples.get("examples", []), 1):
            result_text += f"## **Example {i}: {example['name']}**\n\n"
            result_text += f"**Description**: {example['description']}\n\n"

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
        result_text = "# **Customer Validation Results**\n\n"

        if validation_result["valid"]:
            result_text += "✅ **Validation Successful**\n\n"
            result_text += "Your customer configuration is valid and ready for creation!\n\n"
        else:
            # Handle validation failure by raising proper exception instead of string formatting
            errors = validation_result.get("errors", [])
            if errors:
                first_error = errors[0]
                raise create_structured_validation_error(
                    message=first_error.get("error", "Validation failed"),
                    field=first_error.get("field", "unknown"),
                    value=first_error.get("value", "validation_error"),
                    suggestions=[
                        first_error.get("suggestion", "Check input parameters"),
                        "Verify all required fields are provided",
                        "Check data types and formats",
                        "Ensure resource type and data compatibility",
                    ],
                    examples={
                        "common_issues": [
                            "Missing required fields",
                            "Invalid data format",
                            "Type mismatch",
                        ],
                        "validation_tips": [
                            "Check field requirements",
                            "Verify data types",
                            "Ensure proper formatting",
                        ],
                        "retry_guidance": "Fix the identified issues and retry the operation",
                        "billing_safety": "🔒 BILLING SAFETY: Validation prevents customer data corruption that could affect billing",
                    },
                )
            else:
                raise create_structured_validation_error(
                    message="Validation failed",
                    field="validation",
                    value="validation_failed",
                    suggestions=[
                        "Check input parameters for correct format and values",
                        "Ensure all required fields are provided",
                        "Verify resource type and data compatibility",
                        "Use get_capabilities() to see validation requirements",
                    ],
                    examples={
                        "common_issues": [
                            "Missing required fields",
                            "Invalid data format",
                            "Unsupported resource type",
                        ],
                        "validation_tips": [
                            "Check field types",
                            "Verify required vs optional fields",
                            "Ensure data consistency",
                        ],
                        "retry_guidance": "Fix the identified issues and try the validation again",
                        "billing_safety": "🔒 BILLING SAFETY: Validation ensures customer data integrity for billing operations",
                    },
                )

        if validation_result.get("warnings"):
            result_text += "⚠️ **Warnings**:\n"
            for warning in validation_result["warnings"]:
                result_text += f"- {warning}\n"
            result_text += "\n"

        if validation_result.get("suggestions"):
            result_text += "**Suggestions**:\n"
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

    def _format_roles_response(
        self, roles: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format roles response."""
        result_text = "# 👤 **Roles by Resource Type**\n\n"

        if roles.get("important_note"):
            result_text += f"## **⚠️ IMPORTANT**\n{roles['important_note']}\n\n"

        roles_by_type = roles.get("roles_by_resource_type", {})

        for resource_type, type_info in roles_by_type.items():
            result_text += f"## **{resource_type.title()} Roles**\n"

            result_text += "### Available Roles\n"
            for role in type_info.get("available_roles", []):
                result_text += f"#### `{role['name']}`\n"
                result_text += f"**Description**: {role['description']}\n\n"
                result_text += "**Permissions**:\n"
                for permission in role.get("permissions", []):
                    result_text += f"- {permission}\n"
                result_text += f"\n**Usage**: {role['usage']}\n\n"

            result_text += "### Requirements\n"
            for requirement in type_info.get("role_requirements", []):
                result_text += f"- {requirement}\n"
            result_text += "\n"

        result_text += "## **Examples by Resource Type**\n"
        for example_name, example_data in roles.get("examples", {}).items():
            result_text += f"### {example_name.replace('_', ' ').title()}\n"
            result_text += f"**Resource Type**: `{example_data['resource_type']}`\n"
            result_text += f"**Roles**: `{example_data['roles']}`\n"
            result_text += f"**Use Case**: {example_data['use_case']}\n\n"

        result_text += "## **Usage Examples**\n"
        result_text += "### User Creation (with roles)\n"
        result_text += "```json\n"
        result_text += "{\n"
        result_text += '  "email": "user@example.com",\n'
        result_text += '  "firstName": "John",\n'
        result_text += '  "lastName": "Doe",\n'
        result_text += '  "roles": ["ROLE_TENANT_ADMIN"]\n'
        result_text += "}\n"
        result_text += "```\n\n"

        result_text += "### Subscriber Creation (roles field required)\n"
        result_text += "```json\n"
        result_text += "{\n"
        result_text += '  "email": "subscriber@example.com",\n'
        result_text += '  "firstName": "Jane",\n'
        result_text += '  "lastName": "Doe",\n'
        result_text += '  "organizationIds": ["org_id_123"],  // First use list action to get valid org ID\n'
        result_text += '  "roles": ["ROLE_API_CONSUMER"]  // Required field\n'
        result_text += "}\n"
        result_text += "```\n\n"

        result_text += "## **Next Steps**\n"
        result_text += "1. Choose appropriate roles based on user access needs\n"
        result_text += (
            "2. Use `get_examples(resource_type='users')` to see complete user templates\n"
        )
        result_text += "3. Use `validate(resource_type='users', user_data={...})` to test user configurations\n"
        result_text += (
            "4. Use `create(resource_type='users', user_data={...})` to create users with roles\n"
        )

        return [TextContent(type="text", text=result_text)]

    async def _handle_get_agent_summary(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle getting agent summary for customer management."""
        logger.info("Getting agent summary for customer management")
        self.formatter.start_timing()

        # Define key capabilities
        key_capabilities = [
            "Manage multiple customer resource types (users, subscribers, organizations, teams)",
            "Hierarchical customer structures with organizations containing teams and users",
            "Customer analytics and relationship mapping",
            "Cross-resource validation and business rule enforcement",
            "Bulk customer operations and data management",
            "Integration with subscriptions, products, and alerts",
        ]

        # Define common use cases with examples
        common_use_cases = [
            {
                "title": "List Users",
                "description": "View all user accounts with pagination",
                "example": "list(resource_type='users', page=0, size=10)",
            },
            {
                "title": "Create Organization",
                "description": "Set up a new customer organization",
                "example": "create(resource_type='organizations', organization_data={'name': 'Acme Corp', 'description': 'Technology company'})",
            },
            {
                "title": "Manage Teams",
                "description": "Create and manage teams within organizations",
                "example": "create(resource_type='teams', team_data={'name': 'Dev Team', 'organizationId': 'org_123'})",
            },
            {
                "title": "Customer Analytics",
                "description": "Analyze customer data and activity patterns",
                "example": "analyze(resource_type='users', filters={'status': 'active'})",
            },
            {
                "title": "Update Customer Data",
                "description": "Modify customer information and settings",
                "example": "update(resource_type='users', user_id='user_123', user_data={'status': 'active'})",
            },
        ]

        # Define quick start steps
        quick_start_steps = [
            "Call get_capabilities() to understand customer resource types and field requirements",
            "Use get_roles() to discover available user roles for proper user creation",
            "Use get_examples(resource_type='...') to see working customer templates",
            "Validate configurations with validate(resource_type='...', ...data={...}, dry_run=True)",
            "Create customers with create(resource_type='...', ...data={...})",
            "Analyze customer data with analyze(resource_type='...') and get_relationships(...)",
            "Manage hierarchies through organizations and teams",
        ]

        # Define next actions
        next_actions = [
            "Try: get_capabilities() - See all customer resource types and field requirements",
            "Try: get_roles() - Discover available user roles to avoid trial-and-error",
            "Try: get_examples(resource_type='users') - Get working user templates",
            "Try: list(resource_type='organizations', page=0, size=5) - View existing organizations",
            "Try: analyze(resource_type='users') - Get customer analytics",
        ]

        return self.formatter.format_agent_summary_response(
            description="Comprehensive customer lifecycle management for the Revenium platform including users, subscribers, organizations, and teams with hierarchical structures and analytics",
            key_capabilities=key_capabilities,
            common_use_cases=common_use_cases,
            quick_start_steps=quick_start_steps,
            next_actions=next_actions,
        )

    # Metadata Provider Implementation
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get customer tool capabilities."""
        return [
            ToolCapability(
                name="Multi-Resource Customer Management",
                description="Manage users, subscribers, organizations, and teams",
                parameters={
                    "resource_type": "str (users, subscribers, organizations, teams)",
                    "list": {"page": "int", "size": "int", "filters": "dict"},
                    "get": {
                        "user_id": "str",
                        "subscriber_id": "str",
                        "organization_id": "str",
                        "team_id": "str",
                    },
                    "create": {
                        "user_data": "dict",
                        "subscriber_data": "dict",
                        "organization_data": "dict",
                        "team_data": "dict",
                    },
                    "update": {"resource_id": "str", "resource_data": "dict"},
                    "delete": {"resource_id": "str"},
                },
                examples=[
                    "list(resource_type='users', page=0, size=10)",
                    "get(resource_type='organizations', organization_id='org_123')",
                    "create(resource_type='users', user_data={'email': 'user@example.com', 'name': 'John Doe'})",
                ],
                limitations=[
                    "Requires valid API authentication",
                    "Some operations require specific roles",
                    "Deletion may affect related resources",
                ],
            ),
            ToolCapability(
                name="Customer Analytics",
                description="Analyze customer data and relationships",
                parameters={
                    "analyze": {"resource_type": "str", "filters": "dict"},
                    "get_relationships": {"resource_type": "str", "resource_id": "str"},
                },
                examples=[
                    "analyze(resource_type='users', filters={'status': 'active'})",
                    "get_relationships(resource_type='organizations', resource_id='org_123')",
                ],
            ),
            ToolCapability(
                name="Hierarchical Management",
                description="Manage organizational hierarchies and team structures",
                parameters={
                    "organization_id": "str",
                    "team_id": "str",
                    "parent_organization_id": "str",
                },
                examples=[
                    "Organizations contain teams and users",
                    "Teams manage users and resources",
                    "Hierarchical permission inheritance",
                ],
            ),
        ]

    def _apply_auto_generation(
        self, resource_data: Dict[str, Any], resource_type: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply auto-generation to fill in missing required fields and assist with complex product creation.

        Args:
            resource_data: User-provided resource data
            resource_type: Type of resource being created
            arguments: Full arguments dict for context

        Returns:
            Enhanced resource data with auto-generated fields
        """
        result = resource_data.copy()

        # Organizations auto-generation
        if resource_type == "organizations":
            if "name" in result and not result.get("currency"):
                result["currency"] = "USD"
            if "name" in result and not result.get("types"):
                result["types"] = ["CONSUMER"]
            if "name" in result and not result.get("elementDefinitionAutoDiscoveryEnabled"):
                result["elementDefinitionAutoDiscoveryEnabled"] = True

        # Users auto-generation
        elif resource_type == "users":
            if "email" in result:
                email_parts = result["email"].split("@")
                if len(email_parts) == 2 and not result.get("firstName"):
                    # Generate firstName from email prefix
                    name_part = email_parts[0].replace(".", " ").replace("_", " ").title()
                    result["firstName"] = name_part.split()[0] if name_part else "User"
                if len(email_parts) == 2 and not result.get("lastName"):
                    # Generate lastName from email prefix or domain
                    name_part = email_parts[0].replace(".", " ").replace("_", " ").title()
                    parts = name_part.split()
                    result["lastName"] = parts[-1] if len(parts) > 1 else "Name"
            if not result.get("roles"):
                result["roles"] = ["ROLE_API_CONSUMER"]

        # Subscribers auto-generation
        elif resource_type == "subscribers":
            if "email" in result:
                email_parts = result["email"].split("@")
                if len(email_parts) == 2 and not result.get("firstName"):
                    name_part = email_parts[0].replace(".", " ").replace("_", " ").title()
                    result["firstName"] = name_part.split()[0] if name_part else "User"
                if len(email_parts) == 2 and not result.get("lastName"):
                    name_part = email_parts[0].replace(".", " ").replace("_", " ").title()
                    parts = name_part.split()
                    result["lastName"] = parts[-1] if len(parts) > 1 else "Name"
            if not result.get("roles"):
                result["roles"] = ["ROLE_API_CONSUMER"]
            if not result.get("organizationIds") and "email" in result:
                # Note: organizationIds still required, but we can indicate it needs to be provided
                pass

        # Teams auto-generation
        elif resource_type == "teams":
            if "name" in result and not result.get("description"):
                result["description"] = f"Team for {result['name']}"

        return result

    async def _get_supported_actions(self) -> List[str]:
        """Get supported actions."""
        return [
            "list",
            "get",
            "create",
            "update",
            "delete",
            "analyze",
            "get_capabilities",
            "get_examples",
            "get_roles",
            "validate",
            "get_agent_summary",
            "get_relationships",
            "get_tool_metadata",
        ]

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Context7 single source of truth for manage_customers schema."""
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": await self._get_supported_actions()},
                "name": {
                    "type": "string",
                    "description": "Customer name - the only field users need to provide",
                },
                # Note: email, firstName, lastName auto-generated from name
                # Note: ownerId, teamId system-managed
                # Note: resource_type determined from context
            },
            "required": ["action", "name"],  # Context7: User-centric only
        }

    async def _get_tool_dependencies(self) -> List[ToolDependency]:
        """Get tool dependencies."""
        # Removed circular dependencies - customers work independently
        # Business relationships are documented in resource_relationships instead
        # Only keep non-circular dependencies that represent actual technical needs
        return [
            ToolDependency(
                tool_name="manage_alerts",
                dependency_type=DependencyType.ENHANCES,
                description="Organizations and teams can configure alerts",
                conditional=True,
            )
        ]

    async def _get_resource_relationships(self) -> List[ResourceRelationship]:
        """Get resource relationships."""
        return [
            ResourceRelationship(
                resource_type="subscriptions",
                relationship_type="creates",
                description="Users and organizations can have subscriptions",
                cardinality="1:N",
                optional=True,
            ),
            ResourceRelationship(
                resource_type="products",
                relationship_type="creates",
                description="Organizations can own products",
                cardinality="1:N",
                optional=True,
            ),
            ResourceRelationship(
                resource_type="sources",
                relationship_type="manages",
                description="Teams can manage data sources",
                cardinality="1:N",
                optional=True,
            ),
            ResourceRelationship(
                resource_type="alerts",
                relationship_type="configures",
                description="Organizations and teams can configure alerts",
                cardinality="1:N",
                optional=True,
            ),
        ]

    async def _get_usage_patterns(self) -> List[UsagePattern]:
        """Get usage patterns."""
        return [
            UsagePattern(
                pattern_name="Customer Discovery",
                description="Explore customer data across different resource types",
                frequency=0.9,
                typical_sequence=["list", "get"],
                common_parameters={"resource_type": "users", "page": 0, "size": 20},
                success_indicators=["Customers listed successfully", "Customer details retrieved"],
            ),
            UsagePattern(
                pattern_name="Organization Setup",
                description="Create and configure organizational structures",
                frequency=0.6,
                typical_sequence=["create", "get", "analyze"],
                common_parameters={"resource_type": "organizations"},
                success_indicators=["Organization created", "Structure configured"],
            ),
            UsagePattern(
                pattern_name="User Management",
                description="Manage user accounts and roles",
                frequency=0.8,
                typical_sequence=["list", "get", "update"],
                common_parameters={"resource_type": "users"},
                success_indicators=["Users managed successfully", "Roles updated"],
            ),
            UsagePattern(
                pattern_name="Customer Analytics",
                description="Analyze customer relationships and metrics",
                frequency=0.5,
                typical_sequence=["analyze", "get_relationships"],
                common_parameters={"filters": {"status": "active"}},
                success_indicators=["Analytics generated", "Relationships mapped"],
            ),
        ]

    async def _get_agent_summary(self) -> str:
        """Get agent summary."""
        return """**Customer Management Tool**

Comprehensive customer lifecycle management for the Revenium platform. Handle users, subscribers, organizations, and teams with hierarchical structures, relationship mapping, and analytics capabilities.

**Key Features:**
• Multi-resource customer management (Users, Subscribers, Organizations, Teams)
• Hierarchical organizational structures
• Customer relationship mapping and analytics
• Integration with subscriptions, products, and alerts
• Agent-friendly error handling and guidance"""

    async def _get_quick_start_guide(self) -> List[str]:
        """Get quick start guide."""
        return [
            "Start with get_capabilities() to understand customer resource types",
            "Use get_examples(resource_type='...') to see working customer templates",
            "List customers with list(resource_type='users') or other resource types",
            "Create customers with create(resource_type='...', ...data={...})",
            "Analyze relationships with get_relationships() and analyze()",
            "Manage hierarchies through organizations and teams",
        ]


# Create consolidated instance
# Module-level instantiation removed to prevent UCM warnings during import
# customer_management = CustomerManagement(ucm_helper=None)
