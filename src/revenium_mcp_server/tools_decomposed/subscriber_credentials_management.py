"""Enhanced subscriber credentials management tool with comprehensive business context.

This module provides comprehensive subscriber credential management operations
including CRUD operations, enhanced NLP support, dry run capabilities, and
extensive business context for product managers managing billing automation.
"""

import time
from typing import Any, ClassVar, Dict, List, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..business_context.credential_business_context import CredentialBusinessContext
from ..client import ReveniumClient, ReveniumAPIError
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_resource_not_found_error,
    create_structured_missing_parameter_error,
    create_structured_validation_error,
)
from ..dry_run.credential_dry_run import CredentialDryRunValidator
from ..hierarchy import cross_tier_validator, entity_lookup_service, hierarchy_navigation_service
from ..introspection.metadata import ToolCapability, ToolType
from ..nlp.credential_nlp_processor import CredentialIntent, CredentialNLPProcessor
from ..common.security_utils import obfuscate_credentials_list, obfuscate_credential_data
from .credential_business_handler import CredentialBusinessHandler
from .credential_documentation_handler import CredentialDocumentationHandler
from .unified_tool_base import ToolBase


class CredentialsHierarchyManager:
    """Manager for credentials hierarchy operations using the hierarchy services."""

    def __init__(self, client: ReveniumClient):
        """Initialize hierarchy manager with client."""
        self.client = client
        self.formatter = UnifiedResponseFormatter("manage_subscriber_credentials")
        self.navigation_service = hierarchy_navigation_service
        self.lookup_service = entity_lookup_service
        self.validator = cross_tier_validator

    async def get_subscription_details(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get subscription details for a given credential."""
        start_time = time.time()

        credential_id = arguments.get("credential_id")
        if not credential_id:
            raise create_structured_missing_parameter_error(
                parameter_name="credential_id",
                action="get subscription details for credential",
                examples={
                    "usage": "get_subscription_details(credential_id='cred_123')",
                    "valid_format": "Credential ID should be a string identifier",
                    "example_ids": ["cred_123", "api_key_456", "secret_789"],
                    "hierarchy_context": "HIERARCHY: Find the subscription that owns this credential",
                },
            )

        # Use hierarchy navigation service to find the subscription
        navigation_result = await self.navigation_service.get_subscription_for_credential(
            credential_id
        )

        if not navigation_result.success:
            raise ToolError(
                message=f"Failed to get subscription for credential {credential_id}: {navigation_result.error_message}",
                error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                field="credential_id",
                value=credential_id,
                suggestions=[
                    "Verify the credential ID exists using get(credential_id='...')",
                    "Use list() to see all available credentials",
                    "Check if the credential has a valid subscription association",
                ],
            )

        timing_ms = round((time.time() - start_time) * 1000, 2)

        return {
            "action": "get_subscription_details",
            "credential_id": credential_id,
            "data": (
                navigation_result.related_entities[0] if navigation_result.related_entities else {}
            ),
            "navigation_path": navigation_result.navigation_path,
            "metadata": {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.%f"),
                "response_time_ms": timing_ms,
                "hierarchy_level": "credentials → subscriptions",
                "subscription_found": len(navigation_result.related_entities) > 0,
            },
        }

    async def get_product_details(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get product details for a given credential through its subscription."""
        start_time = time.time()

        credential_id = arguments.get("credential_id")
        if not credential_id:
            raise create_structured_missing_parameter_error(
                parameter_name="credential_id",
                action="get product details for credential",
                examples={
                    "usage": "get_product_details(credential_id='cred_123')",
                    "valid_format": "Credential ID should be a string identifier",
                    "example_ids": ["cred_123", "api_key_456", "secret_789"],
                    "hierarchy_context": "HIERARCHY: Find the product through credential → subscription → product",
                },
            )

        # Get the full hierarchy for this credential
        navigation_result = await self.navigation_service.get_full_hierarchy(
            "credentials", credential_id
        )

        if not navigation_result.success:
            raise ToolError(
                message=f"Failed to get hierarchy for credential {credential_id}: {navigation_result.error_message}",
                error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                field="credential_id",
                value=credential_id,
                suggestions=[
                    "Verify the credential ID exists using get(credential_id='...')",
                    "Use list() to see all available credentials",
                    "Check if the credential has a subscription with a valid product",
                ],
            )

        # Extract product from the hierarchy
        hierarchy_data = (
            navigation_result.related_entities[0] if navigation_result.related_entities else {}
        )
        products = hierarchy_data.get("products", [])
        product = products[0] if products else {}

        timing_ms = round((time.time() - start_time) * 1000, 2)

        return {
            "action": "get_product_details",
            "credential_id": credential_id,
            "data": product,
            "navigation_path": navigation_result.navigation_path,
            "metadata": {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.%f"),
                "response_time_ms": timing_ms,
                "hierarchy_level": "credentials → subscriptions → products",
                "product_found": bool(product),
                "subscription_found": bool(hierarchy_data.get("subscriptions", [])),
            },
        }


class SubscriberCredentialsManagement(ToolBase):
    """Enhanced subscriber credentials management with comprehensive business context and capabilities."""

    tool_name: ClassVar[str] = "manage_subscriber_credentials"
    tool_description: ClassVar[str] = (
        "Subscriber credential management for billing identity. Key actions: list, create, update, delete, validate. Use get_capabilities() for complete action list."
    )
    business_category: ClassVar[str] = "Core Business Management Tools"
    tool_type: ClassVar[ToolType] = ToolType.CRUD
    tool_version: ClassVar[str] = "1.0.0"

    def __init__(self, ucm_helper=None, client=None):
        """Initialize enhanced subscriber credentials management tool."""
        super().__init__(ucm_helper)
        self.client: ReveniumClient = client or ReveniumClient()
        self.formatter = UnifiedResponseFormatter("manage_subscriber_credentials")

        # Initialize enhanced capabilities
        self.nlp_processor = CredentialNLPProcessor()
        self.dry_run_validator = CredentialDryRunValidator(self.client)
        self.business_context = CredentialBusinessContext()

        # Initialize handlers for modular functionality
        self.business_handler = CredentialBusinessHandler()
        self.documentation_handler = CredentialDocumentationHandler()

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Context7 single source of truth for manage_subscriber_credentials schema."""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": await self._get_supported_actions(),
                    "description": "Action to perform - get_capabilities for full guidance, create for new credentials",
                },
                # Core credential fields (required for create)
                "label": {
                    "type": "string",
                    "description": "Display name for the credential - required for create",
                },
                "subscriberId": {
                    "type": "string",
                    "description": "ID of the subscriber - required for create",
                },
                "organizationId": {
                    "type": "string",
                    "description": "ID of the organization - required for create",
                },
                "externalId": {
                    "type": "string",
                    "description": "External credential identifier - required for create",
                },
                "externalSecret": {
                    "type": "string",
                    "description": "Secret/password for the credential - required for create",
                },
                # Optional credential fields
                "name": {
                    "type": "string",
                    "description": "Internal name (defaults to label if not provided)",
                },
                "tags": {"type": "array", "description": "List of tags for categorization"},
                "subscriptionIds": {
                    "type": "array",
                    "description": "List of subscription IDs to associate",
                },
                # Management fields
                "credential_id": {
                    "type": "string",
                    "description": "Credential ID for get/update/delete operations",
                },
                "credential_data": {
                    "type": "object",
                    "description": "Credential data object for create/update operations",
                },
                # Note: Full field list available in get_capabilities() and get_examples()
            },
            "required": [
                "action"
            ],  # Context7: User-centric - only action required, other fields depend on action
            "additionalProperties": True,  # Context7: Allow all supported fields for maximum flexibility
        }

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle subscriber credentials management actions."""
        try:
            logger.info(f"Handling subscriber credentials action: {action}")

            # Initialize hierarchy manager
            hierarchy_manager = CredentialsHierarchyManager(self.client)

            # Route to appropriate handler
            if action == "list":
                result = await self._list_credentials(arguments)
            elif action == "get":
                result = await self._get_credential(arguments)
            elif action == "create":
                result = await self._create_credential(arguments)
            elif action == "update":
                result = await self._update_credential(arguments)
            elif action == "delete":
                result = await self._delete_credential(arguments)
            elif action == "get_capabilities":
                result = await self.documentation_handler.get_capabilities(arguments)
                # Result is now formatted markdown text, wrap in TextContent
                from mcp.types import TextContent
                return [TextContent(type="text", text=result)]
            elif action == "get_examples":
                result = await self.documentation_handler.get_examples(arguments)
                # Result is now formatted markdown text, wrap in TextContent
                from mcp.types import TextContent
                return [TextContent(type="text", text=result)]
            elif action == "validate":
                # For validate action, determine operation type from context
                # If credential_id is provided, assume UPDATE validation, otherwise CREATE
                if arguments.get("credential_id"):
                    arguments["operation_type"] = "update"
                else:
                    arguments["operation_type"] = "create"
                result = await self.documentation_handler.validate_credential_data(arguments)
            elif action == "get_agent_summary":
                result = await self.documentation_handler.get_agent_summary(arguments)
            elif action == "parse_natural_language":
                result = await self.documentation_handler.parse_natural_language(arguments)
            elif action == "get_business_guidance":
                result = await self.business_handler.get_business_guidance(arguments)
            elif action == "get_onboarding_checklist":
                result = await self.business_handler.get_onboarding_checklist(arguments)
            elif action == "get_troubleshooting_guide":
                result = await self.business_handler.get_troubleshooting_guide(arguments)
            elif action == "analyze_billing_impact":
                result = await self.business_handler.analyze_billing_impact(arguments)
            # Handle hierarchy actions
            elif action == "get_subscription_details":
                result = await hierarchy_manager.get_subscription_details(arguments)
                import json

                from mcp.types import TextContent

                return [
                    TextContent(
                        type="text",
                        text=f"**Subscription Details for Credential {result['credential_id']}**\n\n{json.dumps(result, indent=2)}",
                    )
                ]
            elif action == "get_product_details":
                result = await hierarchy_manager.get_product_details(arguments)
                import json

                from mcp.types import TextContent

                return [
                    TextContent(
                        type="text",
                        text=f"**Product Details for Credential {result['credential_id']}**\n\n{json.dumps(result, indent=2)}",
                    )
                ]
            else:
                raise ToolError(
                    message=f"Unknown action '{action}' is not supported",
                    error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
                    field="action",
                    value=action,
                    suggestions=[
                        "Use one of the supported actions: list, get, create, update, delete",
                        "Use get_capabilities() to see all available actions",
                        "Use get_examples() to see usage examples",
                        "Check the action name for typos",
                    ],
                    examples={
                        "supported_actions": [
                            "list",
                            "get",
                            "create",
                            "update",
                            "delete",
                            "get_capabilities",
                            "get_examples",
                            "validate",
                            "get_subscription_details",
                            "get_product_details",
                        ],
                        "example_usage": {
                            "list": "list(page=0, size=20)",
                            "get": "get(credential_id='cred_123')",
                            "create": "create(credential_data={...})",
                            "update": "update(credential_id='cred_123', credential_data={...})",
                            "delete": "delete(credential_id='cred_123')",
                            "get_subscription_details": "get_subscription_details(credential_id='cred_123')",
                            "get_product_details": "get_product_details(credential_id='cred_123')",
                        },
                    },
                )

            # Format response using unified formatter based on action type
            if action == "list":
                return self.formatter.format_list_response(
                    items=result.get("credentials", []),
                    action="list",
                    page=result.get("pagination", {}).get("page", 0),
                    size=result.get("pagination", {}).get("size", 20),
                    total_pages=result.get("pagination", {}).get("totalPages", 1),
                    total_items=result.get("pagination", {}).get("totalElements"),
                )
            elif action == "get":
                return self.formatter.format_item_response(
                    item=result,
                    item_id=result.get("id", "unknown"),
                    action="get",
                    next_steps=[
                        "Use 'update' action to modify this credential",
                        "Use 'delete' action to remove this credential",
                        "Use 'list' action to see all credentials",
                    ],
                )
            elif action in ["create", "update", "delete"]:
                return self.formatter.format_success_response(
                    message=f"Credential {action} completed successfully",
                    data=result,
                    action=action,
                )
            else:
                # For other actions like validate, get_agent_summary, etc.
                # Convert dict responses to TextContent for MCP compatibility
                if isinstance(result, dict):
                    import json

                    from mcp.types import TextContent

                    text = json.dumps(result, indent=2)
                    return [TextContent(type="text", text=text)]
                else:
                    return result

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except ReveniumAPIError as e:
            # Convert API errors to proper ToolError format (Layer 4 -> Layer 1)
            logger.error(f"API error in subscriber credentials management: {e}")

            # Map specific API errors to appropriate error codes
            if e.status_code == 400:
                if "Failed to decode hashed Id" in str(e.message) or "Invalid Anomaly ID" in str(e.message):
                    # Extract the invalid ID from the arguments
                    invalid_id = arguments.get("credential_id", "INVALID_ID")
                    raise ToolError(
                        message=f"Invalid credential ID: '{invalid_id}' is not a valid credential identifier",
                        error_code=ErrorCodes.INVALID_PARAMETER,
                        field="credential_id",
                        value=invalid_id,
                        suggestions=[
                            "Use list() to see all available credential IDs",
                            "Copy the ID exactly from the list results",
                            "Credential IDs are short alphanumeric codes like 'X5oon5', 'mvMYRv', 'GlkRbv'",
                            "Check that you're using the correct ID for the credential you want to access",
                        ],
                    )
                else:
                    raise ToolError(
                        message=f"Invalid request: {e.message}",
                        error_code=ErrorCodes.INVALID_PARAMETER,
                        field="request_data",
                        value=action,
                        suggestions=[
                            "Check that all required parameters are provided",
                            "Verify parameter formats match expected values",
                            "Use get_examples() to see correct usage patterns",
                        ],
                    )
            elif e.status_code == 404:
                raise create_resource_not_found_error(
                    resource_type="credential",
                    resource_id=arguments.get("credential_id", "unknown"),
                    action=action,
                    examples={
                        "usage": "Use list() to find valid credential IDs",
                        "valid_format": "Credential IDs are short alphanumeric codes",
                        "example_ids": ["X5oon5", "mvMYRv", "GlkRbv"],
                    },
                )
            else:
                raise ToolError(
                    message=f"API error: {e.message}",
                    error_code=ErrorCodes.API_ERROR,
                    field="api_request",
                    value=f"HTTP {e.status_code}",
                    suggestions=[
                        "Check your API credentials and permissions",
                        "Verify the request parameters are correct",
                        "Try the operation again after a brief delay",
                    ],
                )
        except Exception as e:
            logger.error(f"Unexpected error in subscriber credentials management: {e}")
            raise ToolError(
                message=f"Unexpected error in {action} operation: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="operation",
                value=action,
                suggestions=[
                    f"Error type: {type(e).__name__}",
                    "Check that all required parameters are provided",
                    "Use get_examples() to see correct usage patterns",
                    "Try the operation again",
                ],
            )

    async def _list_credentials(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List subscriber credentials with pagination."""
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters = arguments.get("filters", {})

        response = await self.client.get_credentials(page=page, size=size, **filters)
        credentials = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)

        # SECURITY: Obfuscate sensitive fields in credentials before returning to user
        # This prevents API keys and secrets from being exposed in tool outputs
        obfuscated_credentials = obfuscate_credentials_list(credentials)

        return {
            "action": "list",
            "resource_type": "subscriber_credentials",
            "credentials": obfuscated_credentials,
            "pagination": page_info,
            "total_found": len(credentials),
        }

    async def _get_credential(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get specific credential by ID."""
        credential_id = arguments.get("credential_id")
        if not credential_id:
            raise create_structured_missing_parameter_error(
                parameter_name="credential_id",
                action="get credential",
                examples={
                    "usage": "get(credential_id='cred_123')",
                    "valid_format": "Credential ID should be a string identifier",
                    "example_ids": ["cred_123", "api_key_456", "secret_789"],
                },
            )

        credential = await self.client.get_credential_by_id(credential_id)

        # SECURITY: Obfuscate sensitive fields in credential before returning to user
        # This prevents API keys and secrets from being exposed in tool outputs
        obfuscated_credential = obfuscate_credential_data(credential)

        return obfuscated_credential

    async def _create_credential(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create new subscriber credential with enhanced NLP and dry run support."""
        # Check for natural language input first
        text_input = arguments.get("text") or arguments.get("description")
        dry_run = arguments.get("dry_run", False)

        if text_input:
            # Process natural language input
            nlp_result = await self.nlp_processor.process_natural_language(text_input)

            if nlp_result.intent != CredentialIntent.CREATE:
                return {
                    "action": "create",
                    "error": f"Natural language input suggests '{nlp_result.intent.value}' but create action was requested",
                    "suggestions": nlp_result.suggestions,
                    "extracted_data": self.nlp_processor.extract_credential_data(nlp_result),
                }

            # Extract credential data from NLP result
            credential_data = self.nlp_processor.extract_credential_data(nlp_result)

            # Merge with any explicitly provided credential_data
            if arguments.get("credential_data"):
                credential_data.update(arguments["credential_data"])
        else:
            credential_data = arguments.get("credential_data")

        # Context7 Fix: Build credential_data from individual parameters if credential_data not provided
        if not credential_data:
            # Check if individual parameters are provided (from MCP signature)
            individual_params = {}
            param_fields = [
                "label",
                "subscriberId",
                "organizationId",
                "externalId",
                "externalSecret",
                "name",
                "tags",
                "subscriptionIds",
            ]

            for field in param_fields:
                if field in arguments and arguments[field] is not None:
                    individual_params[field] = arguments[field]

            if individual_params:
                credential_data = individual_params
                logger.info(
                    f"Context7: Built credential_data from individual parameters: {list(individual_params.keys())}"
                )

        if not credential_data:
            raise create_structured_missing_parameter_error(
                parameter_name="credential_data or individual parameters",
                action="create credential",
                examples={
                    "usage_object": "create(credential_data={'label': 'API Key', 'subscriberId': 'sub_123', 'organizationId': 'org_456', 'externalId': '***YOUR_KEY***', 'externalSecret': '***YOUR_SECRET***'})",
                    "usage_individual": "create(label='API Key', subscriberId='sub_123', organizationId='org_456', externalId='***YOUR_KEY***', externalSecret='***YOUR_SECRET***')",
                    "nlp_usage": "create(text='Create API key for john@company.com at TechCorp with secret abc123')",
                    "required_fields": [
                        "label",
                        "subscriberId",
                        "organizationId",
                        "externalId",
                        "externalSecret",
                    ],
                    "example_data": {
                        "label": "Production API Key",
                        "name": "Production API Key",
                        "subscriberId": "sub_123",
                        "organizationId": "org_456",
                        "externalId": "***YOUR_API_KEY***",
                        "externalSecret": "***YOUR_SECRET***",
                        "tags": ["production", "api"],
                        "subscriptionIds": ["subscription_789"],
                    },
                    "field_mapping": {
                        "label": "Display name for the credential",
                        "name": "Internal name (typically same as label)",
                        "subscriberId": "ID of the subscriber (use resolve_subscriber_email_to_id if needed)",
                        "organizationId": "ID of the organization (use resolve_organization_name_to_id if needed)",
                        "externalId": "External credential identifier",
                        "externalSecret": "Secret/password for the credential",
                        "tags": "Optional array of tags for categorization",
                        "subscriptionIds": "Optional array of subscription IDs to associate",
                    },
                    "billing_safety": "🔒 BILLING SAFETY: Credential creation establishes authentication for billing and usage tracking",
                    "dry_run_option": "Use dry_run=true to validate without creating",
                },
            )

        # Resolve email and organization names if provided
        if "subscriber_email" in credential_data:
            try:
                subscriber_id = await self.client.resolve_subscriber_email_to_id(
                    credential_data["subscriber_email"]
                )
                credential_data["subscriberId"] = subscriber_id
                del credential_data["subscriber_email"]
            except Exception as e:
                logger.warning(f"Could not resolve subscriber email: {e}")

        if "organization_name" in credential_data:
            try:
                org_id = await self.client.resolve_organization_name_to_id(
                    credential_data["organization_name"]
                )
                credential_data["organizationId"] = org_id
                del credential_data["organization_name"]
            except Exception as e:
                logger.warning(f"Could not resolve organization name: {e}")

        # Perform dry run validation if requested
        if dry_run:
            dry_run_result = await self.dry_run_validator.validate_create_operation(credential_data)

            # Get business impact analysis
            business_impact = self.business_context.get_billing_impact_explanation(
                "create", credential_data
            )

            # Convert validation issues to dictionaries
            validation_issues = []
            for issue in dry_run_result.validation_issues:
                validation_issues.append(
                    {
                        "severity": issue.severity.value,
                        "field": issue.field,
                        "message": issue.message,
                        "suggestion": issue.suggestion,
                        "business_impact": issue.business_impact,
                    }
                )

            # Convert billing impact to dictionary
            billing_impact_dict = {
                "affected_subscriptions": dry_run_result.billing_impact.affected_subscriptions,
                "metering_impact": dry_run_result.billing_impact.metering_impact,
                "cost_implications": dry_run_result.billing_impact.cost_implications,
                "automation_risk": dry_run_result.billing_impact.automation_risk,
                "recommendations": dry_run_result.billing_impact.recommendations,
            }

            return {
                "action": "create",
                "dry_run": True,
                "validation_result": {
                    "operation": dry_run_result.operation,
                    "valid": dry_run_result.valid,
                    "validation_issues": validation_issues,
                    "billing_impact": billing_impact_dict,
                    "confidence_score": dry_run_result.confidence_score,
                    "next_steps": dry_run_result.next_steps,
                },
                "business_impact": business_impact,
                "preview_data": dry_run_result.preview_data,
                "ready_to_proceed": dry_run_result.valid,
                "next_steps": dry_run_result.next_steps,
            }

        # Validate required fields
        required_fields = [
            "label",
            "subscriberId",
            "organizationId",
            "externalId",
            "externalSecret",
        ]
        missing_fields = [
            field
            for field in required_fields
            if field not in credential_data or not credential_data[field]
        ]

        if missing_fields:
            raise create_structured_validation_error(
                message=f"Missing required fields for credential creation: {', '.join(missing_fields)}",
                field="credential_data",
                value=f"missing: {', '.join(missing_fields)}",
                suggestions=[
                    "Provide all required fields: label, subscriberId, organizationId, externalId, externalSecret",
                    "Use resolve_subscriber_email_to_id() to get subscriberId from email",
                    "Use resolve_organization_name_to_id() to get organizationId from name",
                    "Ensure all required fields have non-empty values",
                    "Use dry_run=true to validate before creating",
                ],
                examples={
                    "required_fields": required_fields,
                    "helper_methods": {
                        "resolve_subscriber": "await client.resolve_subscriber_email_to_id('user@company.com')",
                        "resolve_organization": "await client.resolve_organization_name_to_id('Company Name')",
                    },
                },
            )

        # Set name to label if not provided
        if "name" not in credential_data:
            credential_data["name"] = credential_data["label"]

        # Ensure teamId is set
        if "teamId" not in credential_data:
            credential_data["teamId"] = self.client.team_id

        # Create the credential
        result = await self.client.create_credential(credential_data)

        # SECURITY: Obfuscate sensitive fields in created credential before returning to user
        # This prevents API keys and secrets from being exposed in tool outputs
        obfuscated_result = obfuscate_credential_data(result)

        # Add business context to result
        obfuscated_result["business_context"] = self.business_context.get_billing_impact_explanation(
            "create", credential_data
        )

        return obfuscated_result

    async def _update_credential(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Update existing subscriber credential using custom merge logic.

        This implementation uses a custom read-modify-write pattern similar to the working
        alerts tool, bypassing PartialUpdateHandler to ensure reliable partial updates.
        """
        credential_id = arguments.get("credential_id")
        credential_data = arguments.get("credential_data")

        # Basic parameter validation
        if not credential_id:
            raise create_structured_missing_parameter_error(
                parameter_name="credential_id",
                action="update credential",
                examples={
                    "usage": "update(credential_id='cred_123', credential_data={'label': 'Updated API Key'})",
                    "note": "✅ Supports partial updates - only provide fields you want to change",
                    "partial_example": "Only the 'label' field will be updated, all other fields remain unchanged",
                },
            )

        if not credential_data:
            raise create_structured_missing_parameter_error(
                parameter_name="credential_data",
                action="update credential",
                examples={
                    "usage": "update(credential_id='cred_123', credential_data={'label': 'Updated API Key'})",
                    "partial_update": "✅ Only provide the fields you want to update",
                    "updatable_fields": [
                        "label",
                        "name",
                        "externalId",
                        "externalSecret",
                        "tags",
                        "subscriptionIds",
                    ],
                    "example_partial": {"label": "New Label"},
                    "example_multiple": {"label": "New Label", "externalId": "new_key_123"},
                },
            )

        logger.info(
            f"Updating credential: {credential_id} with partial data: {list(credential_data.keys())}"
        )

        try:
            # Step 1: Get current credential data (read-modify-write pattern)
            current_credential = await self.client.get_credential_by_id(credential_id)

            if not current_credential:
                raise create_resource_not_found_error(
                    resource_type="credential",
                    resource_id=credential_id,
                    suggestions=[
                        "Verify the credential ID is correct",
                        "Use list action to see available credentials",
                        "Check if the credential was deleted",
                    ],
                )

            # Step 2: Start with current data and apply updates (merge pattern)
            merged_data = current_credential.copy()

            # Step 3: Apply field transformations for user-friendly field names
            converted_updates = {}
            for key, value in credential_data.items():
                if key == "label":
                    # Always update both label and name when label is provided
                    converted_updates["label"] = value
                    if "name" not in credential_data:
                        converted_updates["name"] = value
                else:
                    # Pass through other fields as-is
                    converted_updates[key] = value

            # Step 4: Apply the converted updates to the current data
            merged_data.update(converted_updates)

            # Step 5: Ensure required fields have defaults if missing
            if "teamId" not in merged_data or not merged_data["teamId"]:
                merged_data["teamId"] = self.client.team_id

            # Step 5.5: Extract required IDs from nested objects if not already present
            # The API requires subscriberId and organizationId as direct fields, not nested objects
            if "subscriberId" not in merged_data and "subscriber" in current_credential:
                subscriber_id = current_credential["subscriber"].get("id")
                if subscriber_id:
                    merged_data["subscriberId"] = subscriber_id
                    logger.debug(f"Extracted subscriberId from nested object: {subscriber_id}")

            if "organizationId" not in merged_data and "organization" in current_credential:
                organization_id = current_credential["organization"].get("id")
                if organization_id:
                    merged_data["organizationId"] = organization_id
                    logger.debug(f"Extracted organizationId from nested object: {organization_id}")

            # Ensure critical fields are present for UPDATE operations
            # These fields are required by the API even for partial updates
            required_for_api = ["subscriberId", "organizationId", "externalId", "externalSecret"]
            for field in required_for_api:
                if field not in merged_data or merged_data[field] is None:
                    logger.warning(f"Required field '{field}' is missing or null in merged data")
                    # This should not happen if we got the current credential correctly
                    # but let's be defensive

            # Step 6: Preserve subscription associations and other relationship fields
            # The API requires explicit inclusion of subscription data to preserve associations
            if "subscriptions" in current_credential and current_credential["subscriptions"]:
                # Extract the full subscription objects from the current credential
                existing_subscriptions = current_credential["subscriptions"]

                # Only preserve subscriptions if they're not being explicitly updated
                if existing_subscriptions and "subscriptions" not in credential_data:
                    merged_data["subscriptions"] = existing_subscriptions
                    subscription_ids = [
                        sub.get("id", "unknown")
                        for sub in existing_subscriptions
                        if isinstance(sub, dict)
                    ]
                    logger.info(f"Preserving subscription associations: {subscription_ids}")
                else:
                    logger.info(
                        f"Not preserving subscriptions - existing: {len(existing_subscriptions)}, subscriptions in credential_data: {'subscriptions' in credential_data}"
                    )

            # Step 7: Remove fields that shouldn't be sent to the API
            # Include all read-only and relationship fields that the API doesn't accept for updates
            fields_to_remove = [
                "id",
                "createdAt",
                "updatedAt",
                "version",
                "created",
                "updated",
                "team",
                "organization",
                "subscriber",
                "_links",
                "resourceType",
                "identityProvider",
            ]
            final_payload = {k: v for k, v in merged_data.items() if k not in fields_to_remove}

            # Remove any fields with None values that might cause API issues
            # BUT preserve required fields and important relationship fields even if they are None
            required_fields = [
                "label",
                "name",
                "subscriberId",
                "organizationId",
                "externalId",
                "externalSecret",
                "teamId",
            ]
            relationship_fields = ["subscriptions", "tags"]  # Fields that preserve relationships
            preserve_fields = required_fields + relationship_fields
            final_payload = {
                k: v for k, v in final_payload.items() if v is not None or k in preserve_fields
            }

            # Step 8: Call the API with complete merged data
            logger.info(
                f"Updating credential {credential_id} with merged payload keys: {list(final_payload.keys())}"
            )
            logger.debug(f"Full payload: {final_payload}")
            updated_credential = await self.client.update_credential(credential_id, final_payload)

            logger.info(f"Successfully updated credential: {credential_id}")

            # Track what fields were actually updated (including auto-updated fields like name from label)
            updated_fields = list(converted_updates.keys())

            # SECURITY: Obfuscate sensitive fields in updated credential before returning to user
            # This prevents API keys and secrets from being exposed in tool outputs
            obfuscated_credential = obfuscate_credential_data(updated_credential)

            # Prepare result with business context
            result = {
                "action": "update",
                "resource_type": "subscriber_credentials",
                "credential_id": credential_id,
                "data": obfuscated_credential,
                "updated_fields": updated_fields,
                "business_context": self.business_context.get_billing_impact_explanation(
                    "update", credential_data
                ),
            }

            return result

        except Exception as e:
            logger.error(f"Failed to update credential {credential_id}: {e}")
            logger.error(f"Exception type: {type(e)}")
            logger.error(f"Exception details: {str(e)}")

            # Enhanced error handling with more specific information
            if hasattr(e, "error_code"):
                # Re-raise structured errors as-is
                raise
            elif hasattr(e, "status_code"):
                # Handle API errors with status codes
                raise ToolError(
                    message=f"API error updating credential: HTTP {e.status_code} - {str(e)}",
                    error_code=ErrorCodes.API_ERROR,
                    field="credential_update",
                    value=credential_id,
                    suggestions=[
                        f"API returned HTTP {e.status_code}",
                        "Check that the credential ID exists and is accessible",
                        "Verify the update data format is correct",
                        "Ensure you have permission to update this credential",
                    ],
                )
            else:
                # Handle other errors with more context
                raise ToolError(
                    message=f"Failed to update credential {credential_id}: {str(e)}",
                    error_code=ErrorCodes.PROCESSING_ERROR,
                    field="credential_update",
                    value=credential_id,
                    suggestions=[
                        f"Error type: {type(e).__name__}",
                        "Check that the credential ID exists",
                        "Verify the update data format is correct",
                        "Ensure you have permission to update this credential",
                        "Try the operation again",
                    ],
                )

    async def _delete_credential(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Delete subscriber credential."""
        credential_id = arguments.get("credential_id")
        if not credential_id:
            raise create_structured_missing_parameter_error(
                parameter_name="credential_id",
                action="delete credential",
                examples={
                    "usage": "delete(credential_id='cred_123')",
                    "valid_format": "Credential ID should be a string identifier",
                    "example_ids": ["cred_123", "api_key_456", "secret_789"],
                    "warning": "This action permanently removes the credential",
                    "billing_safety": "🔒 BILLING SAFETY: Credential deletion permanently affects authentication for billing and usage tracking",
                },
            )

        await self.client.delete_credential(credential_id)
        return {
            "action": "delete",
            "resource_type": "subscriber_credentials",
            "credential_id": credential_id,
            "status": "deleted",
            "message": "Credential deleted successfully",
        }

    # Metadata Provider Implementation (fixes FINDING #1: Tool Introspection Metadata Inconsistency)
    async def _get_supported_actions(self) -> List[str]:
        """Get supported actions for tool introspection."""
        return [
            "list",
            "get",
            "create",
            "update",
            "delete",
            "get_capabilities",
            "get_examples",
            "validate",
            "get_agent_summary",
            "parse_natural_language",
            "get_business_guidance",
            "get_onboarding_checklist",
            "get_troubleshooting_guide",
            "analyze_billing_impact",
            "get_subscription_details",
            "get_product_details",
        ]

    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get tool capabilities for tool introspection."""
        from ..introspection.metadata import ToolCapability

        return [
            ToolCapability(
                name="CRUD Operations",
                description="Full create, read, update, delete operations for subscriber credentials with partial update support",
                parameters={
                    "list": {"page": "int", "size": "int", "filters": "dict"},
                    "get": {"credential_id": "str"},
                    "create": {"credential_data": "dict", "dry_run": "bool"},
                    "update": {
                        "credential_id": "str",
                        "credential_data": "dict",
                        "dry_run": "bool",
                    },
                    "delete": {"credential_id": "str", "dry_run": "bool"},
                },
                examples=[
                    "list(page=0, size=20)",
                    "create(credential_data={'label': 'API Key', 'externalId': 'key123'})",
                    "update(credential_id='cred_123', credential_data={'label': 'Updated Key'})",
                    "update(credential_id='cred_123', credential_data={'externalId': 'new_key_456'})",
                    "update(credential_id='cred_123', credential_data={'label': 'New Label', 'externalSecret': 'new_secret'})",
                ],
            ),
            ToolCapability(
                name="Enhanced NLP Support",
                description="Natural language processing for credential operations",
                parameters={
                    "parse_natural_language": {"text": "str", "dry_run": "bool"},
                    "get_agent_summary": {},
                },
                examples=[
                    "parse_natural_language(text='Create API key for customer billing')",
                    "get_agent_summary()",
                ],
            ),
            ToolCapability(
                name="Business Context",
                description="Business guidance and billing impact analysis",
                parameters={
                    "get_business_guidance": {"scenario": "str"},
                    "get_onboarding_checklist": {"customer_info": "dict"},
                    "get_troubleshooting_guide": {"issue_description": "str"},
                    "analyze_billing_impact": {"operation": "str", "credential_data": "dict"},
                },
                examples=[
                    "get_business_guidance(scenario='new_customer_onboarding')",
                    "analyze_billing_impact(operation='create', credential_data={...})",
                ],
            ),
            ToolCapability(
                name="Hierarchy Navigation",
                description="Navigate billing hierarchy relationships",
                parameters={
                    "get_subscription_details": {"credential_id": "str"},
                    "get_product_details": {"credential_id": "str"},
                },
                examples=[
                    "get_subscription_details(credential_id='cred_123')",
                    "get_product_details(credential_id='cred_123')",
                ],
            ),
            ToolCapability(
                name="Validation and Testing",
                description="Comprehensive validation and dry-run capabilities",
                parameters={
                    "validate": {"credential_data": "dict"},
                    "get_capabilities": {},
                    "get_examples": {"example_type": "str"},
                },
                examples=[
                    "validate(credential_data={'label': 'Test', 'externalId': 'test123'})",
                    "get_examples(example_type='basic')",
                ],
            ),
        ]
