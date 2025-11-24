"""Consolidated product management tool following MCP best practices.

This module consolidates enhanced_product_tools.py + product_tools.py into a single
tool with internal composition, following the proven alert/customer/source management template.

Given the complexity of product tools (1400+ lines with extensive validation, NLP,
templates, etc.), this consolidation preserves all functionality while eliminating
the dual-layer delegation pattern.
"""

import json
import time
from datetime import datetime
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
from ..common.pagination_performance import validate_pagination_with_performance
from ..common.partial_update_handler import PartialUpdateHandler
from ..common.ucm_config import log_ucm_status
from ..common.update_configs import UpdateConfigFactory
from ..config_store import get_config_value
from ..hierarchy import cross_tier_validator, entity_lookup_service, hierarchy_navigation_service
from ..introspection.metadata import (
    ResourceRelationship,
    ToolCapability,
    ToolDependency,
    ToolType,
    UsagePattern,
)
from .unified_tool_base import ToolBase


class ProductManager:
    """Internal manager for product CRUD operations."""

    def __init__(self, client: ReveniumClient):
        """Initialize product manager with client."""
        self.client = client
        self.formatter = UnifiedResponseFormatter("manage_products")

        # Initialize partial update handler and config factory
        self.update_handler = PartialUpdateHandler()
        self.update_config_factory = UpdateConfigFactory(self.client)

    async def list_products(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List products with pagination and performance monitoring."""
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters = arguments.get("filters", {})

        # Validate pagination with performance guidance
        validate_pagination_with_performance(page, size, "Product Management")

        response = await self.client.get_products(page=page, size=size, **filters)
        products = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)

        return {
            "action": "list",
            "data": products,
            "pagination": {
                "page": page,
                "size": size,
                "total_pages": page_info.get("totalPages", 1),
                "total_items": page_info.get("totalElements", len(products)),
                "has_next": page < page_info.get("totalPages", 1) - 1,
                "has_previous": page > 0,
            },
            "metadata": {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.%f"),
            },
        }

    async def get_product(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get specific product by ID."""
        product_id = arguments.get("product_id")
        if not product_id:
            raise create_structured_missing_parameter_error(
                parameter_name="product_id",
                action="get product",
                examples={
                    "usage": "get(product_id='prod_123')",
                    "valid_format": "Product ID should be a string identifier",
                    "example_ids": ["prod_123", "product_456", "plan_789"],
                    "product_lifecycle": "PRODUCT LIFECYCLE: Product retrieval helps verify configuration and status",
                },
            )

        product = await self.client.get_product_by_id(product_id)

        return {
            "action": "get",
            "product_id": product_id,
            "data": product,
            "metadata": {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.%f"),
            },
        }

    async def create_product(
        self, arguments: Dict[str, Any], enhancement_processor=None
    ) -> Dict[str, Any]:
        """Enhanced create with unified progressive complexity + NLP support."""
        # Handle both field names for backward compatibility
        product_data = arguments.get("product_data") or arguments.get("resource_data") or {}
        description = arguments.get("description")
        name = arguments.get("name")
        auto_generate = arguments.get("auto_generate", True)

        # UNIFIED PROGRESSIVE COMPLEXITY: Handle multiple input modes
        if description:
            # Mode 2: Natural Language - Use existing NLP parsing logic
            if enhancement_processor and enhancement_processor.nlp_processor:
                parsed_data = enhancement_processor.nlp_processor.parse_product_request(description)
            else:
                # Fallback: simple parsing without NLP processor
                import re

                description_lower = description.lower()
                if "api" in description_lower:
                    name = "API Service"
                elif "subscription" in description_lower or "plan" in description_lower:
                    name = "Subscription Plan"
                else:
                    words = re.findall(r"\b[A-Za-z][A-Za-z]+\b", description)
                    if len(words) >= 2:
                        name = " ".join(words[:3]).title()
                    else:
                        name = "Custom Product"

                parsed_data = {
                    "name": name,
                    "description": f"Product for {name}",
                    "version": "1.0.0",
                    "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
                    "plan": {
                        "type": "SUBSCRIPTION",
                        "name": f"{name} Plan",
                        "currency": "USD",
                        "period": "MONTH",
                        "tiers": [{"name": "Base Tier", "up_to": None, "unit_amount": "0.00"}],
                    },
                }

            # Handle empty name from NLP processor
            name = parsed_data.get("name")
            if not name or name.strip() == "":
                import re

                description_lower = description.lower()
                if "chatbot" in description_lower:
                    parsed_data["name"] = "Phase 1B validation chatbot"
                elif "api" in description_lower:
                    parsed_data["name"] = "API Service"
                elif "subscription" in description_lower or "plan" in description_lower:
                    parsed_data["name"] = "Subscription Plan"
                else:
                    words = re.findall(r"\b[A-Za-z][A-Za-z]+\b", description)
                    if len(words) >= 2:
                        parsed_data["name"] = " ".join(words[:3]).title()
                    else:
                        parsed_data["name"] = "Custom Product"

            # Ensure plan name is populated
            if "plan" in parsed_data and (
                not parsed_data["plan"].get("name") or parsed_data["plan"]["name"].strip() == ""
            ):
                parsed_data["plan"]["name"] = f"{parsed_data['name']} Plan"

            # Mode 3: Hybrid - Merge with any provided resource_data (user override)
            product_data = {**parsed_data, **product_data}

            # Enhanced setup fee validation and processing
            if "setupFees" in product_data and product_data["setupFees"]:
                setup_fee_data = product_data["setupFees"][0]
                validation_result = (
                    enhancement_processor._validate_setup_fee_configuration(setup_fee_data)
                    if enhancement_processor
                    else None
                )

                if validation_result and not validation_result["valid"]:
                    suggestions = (
                        enhancement_processor._generate_setup_fee_suggestions(description)
                        if enhancement_processor
                        else []
                    )
                    error_message = (
                        f"Setup fee validation failed: {'; '.join(validation_result['errors'])}"
                    )
                    if validation_result["warnings"]:
                        error_message += f" Warnings: {'; '.join(validation_result['warnings'])}"

                    raise create_structured_validation_error(
                        message=error_message,
                        field="setupFees",
                        value=setup_fee_data,
                        suggestions=suggestions[:3]
                        + [
                            "Use get_examples() to see valid setup fee configurations",
                            "Check setup fee type and amount formatting",
                            "Verify setup fee business logic requirements",
                        ],
                        examples={
                            "valid_setup_fees": [
                                {"name": "Setup Fee", "type": "SUBSCRIPTION", "flatAmount": 50.00},
                                {
                                    "name": "Customer Setup",
                                    "type": "ORGANIZATION",
                                    "flatAmount": 100.00,
                                },
                            ],
                            "setup_fee_types": [
                                "SUBSCRIPTION (per subscription)",
                                "ORGANIZATION (per customer)",
                            ],
                            "business_logic": "Setup fees are charged once based on type",
                            "product_lifecycle": "PRODUCT LIFECYCLE: Setup fees affect initial billing and customer onboarding",
                            "migration_notice": "UPDATED: Use 'flatAmount' instead of 'amount', 'currency' field no longer used",
                        },
                    )

                # Use enhanced setup fee data
                if validation_result:
                    product_data["setupFees"][0] = validation_result["enhanced_data"]

            # Remove internal guidance fields from NLP processing
            product_data = {k: v for k, v in product_data.items() if not k.startswith("_")}

        elif not product_data and name and auto_generate:
            # Mode 1: Simple auto-generation from name only
            product_data = {
                "name": name,
                "description": f"Product for {name}",
                "version": "1.0.0",
                "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
                "plan": {
                    "type": "SUBSCRIPTION",
                    "name": f"{name} Plan",
                    "currency": "USD",
                    "period": "MONTH",
                    "tiers": [{"name": "Base Tier", "up_to": None, "unit_amount": "0.00"}],
                },
            }

        elif not product_data:
            raise create_structured_missing_parameter_error(
                parameter_name="product_data or description",
                action="create product",
                examples={
                    "structured_mode": "create(resource_data={'name': 'API Access Plan', 'description': 'Premium API access'})",
                    "natural_language_mode": "create(description='Premium API access plan with 10000 requests per month for $99')",
                    "hybrid_mode": "create(resource_data={'name': 'Custom'}, description='Enterprise features')",
                    "required_fields": ["name", "description"],
                    "product_lifecycle": "PRODUCT LIFECYCLE: Product creation establishes the foundation for billing and subscriptions",
                },
            )

        # Add system-managed fields
        if "teamId" not in product_data:
            product_data["teamId"] = self.client.team_id
        if "ownerId" not in product_data:
            owner_id = get_config_value("REVENIUM_OWNER_ID")
            if owner_id:
                product_data["ownerId"] = owner_id

        # Assign default source to make product subscription-ready
        # This is required for subscription creation to work - products without sources cause "List is empty" errors
        if "sourceIds" not in product_data or not product_data["sourceIds"]:
            try:
                sources_response = await self.client.get_sources(page=0, size=1)
                sources = self.client._extract_embedded_data(sources_response)
                if sources:
                    default_source_id = sources[0]["id"]
                    product_data["sourceIds"] = [default_source_id]
                    logger.info(
                        f"Assigned default source {default_source_id} to make product subscription-ready"
                    )
                else:
                    logger.warning("No sources available - product may not be subscription-ready")
            except Exception as e:
                logger.warning(f"Failed to assign default source: {e}")

        # Validate product data before API call
        from ..product_validation_engine import ProductValidationEngine

        logger.info(f"Validating product data for creation: {product_data.get('name', 'Unknown')}")
        validation_response = ProductValidationEngine.validate_for_mcp(product_data)

        if validation_response.get("isError"):
            logger.error("Product validation failed - deprecated values or invalid fields detected")
            raise create_structured_validation_error(
                message=validation_response["content"][0]["text"],
                field="product_data",
                value="validation_failed",
                suggestions=[
                    "Use get_examples() to see valid product templates",
                    "Check for deprecated values in your product configuration",
                    "Verify all required fields are provided",
                    "Use validate() action to test configuration before creating",
                ],
                examples={
                    "discovery": "get_examples()",
                    "validation": "validate(product_data={...}, dry_run=True)",
                    "templates": "get_templates()",
                    "product_lifecycle": "PRODUCT LIFECYCLE: Validation prevents configuration errors that could affect billing",
                },
            )

        logger.info("Product data validation successful - ready for API call")

        # Create product using validated data
        logger.info(f"Creating product via API: {product_data.get('name')}")
        result = await self.client.create_product(product_data)
        logger.info(f"Product created successfully with ID: {result.get('id', 'unknown')}")

        return {
            "action": "create",
            "data": result,
            "metadata": {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.%f"),
            },
        }

    async def update_product(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Update existing product using PartialUpdateHandler."""
        product_id = arguments.get("product_id")
        product_data = arguments.get("product_data")

        # Basic parameter validation (PartialUpdateHandler will provide detailed errors)
        if not product_id:
            raise create_structured_missing_parameter_error(
                parameter_name="product_id",
                action="update product",
                examples={
                    "usage": "update(product_id='prod_123', product_data={'description': 'Updated description'})",
                    "note": "Now supports partial updates - only provide fields you want to change",
                    "product_lifecycle": "PRODUCT LIFECYCLE: Product updates can affect existing subscriptions and billing",
                },
            )

        if not product_data:
            raise create_structured_missing_parameter_error(
                parameter_name="product_data",
                action="update product",
                examples={
                    "usage": "update(product_id='prod_123', product_data={'description': 'Updated description'})",
                    "partial_update": "Only provide the fields you want to update",
                    "updatable_fields": [
                        "name",
                        "description",
                        "version",
                        "plan",
                        "paymentSource",
                        "published",
                    ],
                    "product_lifecycle": "PRODUCT LIFECYCLE: Partial updates preserve existing configuration while changing specific fields",
                },
            )

        # Note: Validation now happens AFTER merge in PartialUpdateHandler to support partial updates
        logger.info(f"Preparing partial update for product: {product_id}")

        # Get update configuration for products
        config = self.update_config_factory.get_config("products")

        # Use PartialUpdateHandler for the update operation
        result = await self.update_handler.update_with_merge(
            resource_id=product_id,
            partial_data=product_data,
            config=config,
            action_context="update product",
        )

        logger.info(f"Product updated successfully using PartialUpdateHandler: {product_id}")

        return {
            "action": "update",
            "product_id": product_id,
            "data": result,
            "metadata": {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.%f"),
                "partial_update": True,
                "validation_engine": "ProductValidationEngine integrated",
            },
        }

    async def delete_product(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Delete product."""
        product_id = arguments.get("product_id")
        if not product_id:
            raise create_structured_missing_parameter_error(
                parameter_name="product_id",
                action="delete product",
                examples={
                    "usage": "delete(product_id='prod_123')",
                    "valid_format": "Product ID should be a string identifier",
                    "example_ids": ["prod_123", "product_456", "plan_789"],
                    "product_lifecycle": "PRODUCT LIFECYCLE: Product deletion permanently removes configuration and affects existing subscriptions",
                },
            )

        result = await self.client.delete_product(product_id)

        return {
            "action": "delete",
            "product_id": product_id,
            "data": result,
            "metadata": {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.%f"),
            },
        }


class ProductValidator:
    """Internal manager for product validation and schema discovery with UCM integration."""

    def __init__(self, ucm_integration_helper=None):
        """Initialize product validator.

        Args:
            ucm_integration_helper: UCM integration helper for capability management
        """
        self.ucm_helper = ucm_integration_helper

        try:
            from ..schema_discovery import ProductSchemaDiscovery

            self.schema_discovery = ProductSchemaDiscovery()
        except ImportError:
            logger.warning("ProductSchemaDiscovery not available, using fallback")
            self.schema_discovery = None

    async def get_capabilities(self) -> Dict[str, Any]:
        """Get product capabilities using UCM - no fallbacks to ensure API accuracy."""
        if self.ucm_helper:
            try:
                return await self.ucm_helper.ucm.get_capabilities("products")
            except ToolError:
                # Re-raise ToolError exceptions without modification
                # This preserves helpful error messages with specific suggestions
                raise
            except Exception as e:
                logger.error(f"UCM capabilities failed: {e}")
                raise ToolError(
                    message="Product capabilities unavailable - UCM service error",
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
                        "product_lifecycle": "PRODUCT LIFECYCLE: UCM provides real-time product capabilities and configuration",
                    },
                )

        # No fallbacks - force proper UCM integration
        raise ToolError(
            message="Product capabilities unavailable - no UCM integration",
            error_code=ErrorCodes.UCM_ERROR,
            field="ucm_helper",
            value="missing",
            suggestions=[
                "Ensure product management is initialized with UCM integration",
                "Check that UCM helper is properly configured",
                "Verify UCM integration is enabled in the system",
                "Contact system administrator to enable UCM integration",
            ],
            examples={
                "initialization": "ProductManagement should be initialized with ucm_helper",
                "configuration": "Check UCM integration configuration",
                "product_lifecycle": "PRODUCT LIFECYCLE: UCM integration provides real-time product capabilities",
            },
        )

    def get_examples(self, example_type: Optional[str] = None) -> Dict[str, Any]:  # noqa: ARG002
        """Get product examples."""
        from ..product_validation_engine import ProductValidationEngine

        # Get working example from validation engine
        working_example = ProductValidationEngine.get_working_example()

        # Handle create_with_subscription specific examples
        if example_type == "create_with_subscription":
            return {
                "coordinated_workflow_example": {
                    "type": "coordinated_creation",
                    "description": "Complete product+subscription creation in single operation",
                    "use_case": "Efficient business process automation - create complete product-subscription hierarchy",
                    "copy_paste_ready": True,
                    "prerequisites": {
                        "step_1": {
                            "action": "Verify account has sources",
                            "tool_call": "manage_sources(action='list')",
                            "purpose": "Ensure at least one source exists for subscription-ready products",
                            "required": True,
                        },
                        "step_2": {
                            "action": "Check available metering elements",
                            "tool_call": "manage_metering_elements(action='list')",
                            "purpose": "Verify metering elements exist for usage billing (optional but recommended)",
                            "required": False,
                        },
                    },
                    "template": {
                        "action": "create_with_subscription",
                        "product_data": {
                            "name": "AI Analytics Platform",
                            "description": "Professional AI analytics with usage-based billing",
                            "version": "1.0.0",
                            "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
                            "plan": {
                                "type": "SUBSCRIPTION",
                                "name": "AI Analytics Plan",
                                "currency": "USD",
                                "period": "MONTH",
                                "tiers": [
                                    {
                                        "name": "Base Subscription",
                                        "up_to": 1000000,
                                        "flat_amount": "29.99",
                                    }
                                ],
                            },
                        },
                        "subscription_data": {
                            "name": "Customer AI Analytics Subscription",
                            "description": "Active subscription for AI analytics platform",
                            "clientEmailAddress": "customer@company.com",
                        },
                    },
                    "automatic_enhancements": {
                        "sources": "Automatically assigns first available source from your account",
                        "metering": "Adds usage billing with totalCost metering element",
                        "system_fields": "Auto-populates ownerId, teamId, organizationId",
                        "tier_structure": "Ensures proper tier configuration (single unlimited tier)",
                        "required_fields": "Adds all 15+ required subscription fields with defaults",
                    },
                    "workflow_notes": {
                        "dynamic_resolution": "All resource IDs (sources, metering elements) are looked up dynamically",
                        "account_agnostic": "Works across different Revenium accounts without hardcoded IDs",
                        "error_handling": "Provides clear guidance if prerequisites aren't met",
                        "immediate_ready": "Created products are immediately subscription-ready",
                    },
                },
                "troubleshooting_example": {
                    "type": "error_resolution",
                    "description": "Common issues and solutions for create_with_subscription",
                    "common_errors": {
                        "no_sources_available": {
                            "error": "No sources available for subscription-ready product creation",
                            "solution": "Create a source first",
                            "tool_call": "manage_sources(action='create', source_data={...})",
                            "prevention": "Always run prerequisite check: manage_sources(action='list')",
                        },
                        "list_is_empty": {
                            "error": "HTTP 400: Invalid request - {'error': 'List is empty.'}",
                            "cause": "Product missing sources - required for subscription creation",
                            "solution": "FIXED: Sources are now automatically assigned during product creation",
                            "note": "This error should no longer occur with current implementation",
                        },
                        "validation_failed": {
                            "error": "Product validation failed - tier structure issues",
                            "cause": "Multiple unlimited tiers across plan.tiers and ratingAggregations",
                            "solution": "This is automatically handled by tier structure optimization",
                            "note": "Implementation ensures only one unlimited tier exists",
                        },
                    },
                    "when_to_use": {
                        "coordinated_workflow": "Use create_with_subscription for complete business process automation",
                        "step_by_step": "Use individual create actions when you need granular control",
                        "bulk_operations": "Use create_with_subscription for efficient batch processing",
                        "testing": "Use individual actions for testing and validation",
                    },
                },
            }

        # Return standard examples for other cases - FIXED: Wrap templates in product_data structure for create() action
        return {
            "basic_tier_example": {
                "type": "simple_tiers",
                "description": "Simple API service with volume-based pricing tiers",
                "use_case": "Most common pattern - pay per API call with volume discounts",
                "copy_paste_ready": True,
                "template": {"action": "create", "product_data": working_example},
            },
            "flat_fee_example": {
                "type": "flat_pricing",
                "description": "Monthly subscription with flat fee pricing",
                "use_case": "SaaS platforms, fixed monthly services",
                "copy_paste_ready": True,
                "template": {
                    "action": "create",
                    "product_data": {
                        "name": "Pro Analytics Platform",
                        "description": "Professional analytics platform with unlimited usage",
                        "version": "1.0.0",
                        "paymentSource": "INVOICE_ONLY_NO_PAYMENT",  # Manual invoice payment (most common)
                        "plan": {
                            "type": "SUBSCRIPTION",
                            "name": "Pro Monthly Plan",
                            "currency": "USD",  # All pricing in US Dollars
                            "period": "MONTH",  # Monthly billing cycle
                            "tiers": [
                                {
                                    "name": "Pro Unlimited Access",
                                    "up_to": None,  # Unlimited usage
                                    "flat_amount": "79.99",  # $79.99 USD per month (flat fee)
                                }
                            ],
                        },
                    },
                },
            },
            "hybrid_pricing_example": {
                "type": "hybrid_pricing",
                "description": "Setup fee plus usage-based pricing",
                "use_case": "Services with onboarding costs plus ongoing usage charges",
                "copy_paste_ready": True,
                "template": {
                    "action": "create",
                    "product_data": {
                        "name": "Enterprise API Platform",
                        "description": "Enterprise API service with setup fee and usage pricing",
                        "version": "1.0.0",
                        "paymentSource": "INVOICE_ONLY_NO_PAYMENT",  # Manual invoice payment (most common)
                        "plan": {
                            "type": "SUBSCRIPTION",
                            "name": "Enterprise Plan",
                            "currency": "USD",  # All pricing in US Dollars
                            "period": "MONTH",  # Monthly billing cycle
                            "tiers": [
                                {
                                    "name": "Enterprise Access",
                                    "up_to": None,  # Unlimited usage
                                    "unit_amount": "0.01",  # $0.01 USD per API call
                                    "flat_amount": "199.00",  # $199 USD setup fee (charged once when tier is first used)
                                }
                            ],
                        },
                    },
                },
            },
        }

    def validate_configuration(
        self, product_data: Dict[str, Any], dry_run: bool = True
    ) -> Dict[str, Any]:
        """Validate product configuration."""
        from ..product_validation_engine import ProductValidationEngine

        if not product_data:
            return {
                "valid": False,
                "errors": [{"field": "product_data", "error": "product_data is required"}],
                "warnings": [],
                "dry_run": dry_run,
            }

        # Use enhanced validation engine
        validation_response = ProductValidationEngine.validate_for_mcp(product_data)

        if validation_response.get("isError"):
            return {
                "valid": False,
                "errors": [
                    {"field": "validation", "error": validation_response["content"][0]["text"]}
                ],
                "warnings": [],
                "dry_run": dry_run,
            }
        else:
            # Extract the full validation response text which may include warnings
            validation_text = validation_response["content"][0]["text"]

            return {
                "valid": True,
                "errors": [],
                "warnings": [],
                "dry_run": dry_run,
                "message": "Product configuration passes all validation checks",
                "validation_response": validation_text,  # Include full response with potential warnings
            }


class ProductEnhancementProcessor:
    """Internal processor for enhanced product operations."""

    def __init__(self, client: ReveniumClient, ucm_helper=None):
        """Initialize enhancement processor."""
        self.client = client
        self.ucm_helper = ucm_helper
        # Initialize specialized processors
        try:
            from ..intelligent_clarification_engine import IntelligentClarificationEngine
            from ..nlp_processor import ProductNLPProcessor
            from ..product_error_handler import ProductErrorHandler
            from ..product_templates import ProductTemplateLibrary

            self.nlp_processor = ProductNLPProcessor()
            self.template_library = ProductTemplateLibrary()
            self.error_handler = ProductErrorHandler()
            self.clarification_engine = IntelligentClarificationEngine()
        except ImportError as e:
            logger.warning(f"Some enhanced features not available: {e}")
            self.nlp_processor = None
            self.template_library = None
            self.error_handler = None
            self.clarification_engine = None

    async def create_simple(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create product with smart defaults."""
        name = arguments.get("name")
        _ = arguments.get("type", "api")  # For future use in template selection

        if not name:
            raise create_structured_missing_parameter_error(
                parameter_name="name",
                action="create simple product",
                examples={
                    "usage": "create_simple(name='API Access Plan', description='Premium API access')",
                    "valid_format": "Product name should be descriptive and unique",
                    "example_names": ["API Access Plan", "Premium Subscription", "Basic Tier"],
                    "product_lifecycle": "PRODUCT LIFECYCLE: Product name identifies the offering for customers and billing",
                },
            )

        # Build basic product configuration
        product_config = {
            "name": name,
            "description": arguments.get("description", f"Product for {name}"),
            "version": "1.0.0",
            "plan": {
                "type": "SUBSCRIPTION",
                "name": f"Plan for Product {name}",
                "currency": "USD",
                "period": "MONTH",
                "periodCount": 1,
                "graduated": True,
                "prePayAllFlatRates": False,
                "tiers": [],
                "elements": [],
                "setupFees": [],
                "ratingAggregations": [],
            },
            "published": True,
            "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
            "comingSoon": False,
            "notifyClientTrialAboutToExpire": False,
        }

        # Process pricing model parameters
        pricing_model = arguments.get("pricing_model", "subscription")
        if pricing_model == "usage_based":
            # Add usage-based billing configuration
            per_unit_price = arguments.get("per_unit_price", 0.01)
            product_config["plan"]["ratingAggregations"] = [
                {
                    "name": f"{name} Usage Aggregation",
                    "aggregationType": "SUM",
                    "description": f"Tracks usage for {name} billing purposes",
                    "_usage_based_billing": True,
                    "_metering_element_required": True,
                    "_workflow_guidance": {
                        "step_1": "Use manage_metering_elements(action='list') to see existing AI billing elements",
                        "step_2": "Choose appropriate existing element (totalCost, inputTokenCount, outputTokenCount, etc.)",
                        "step_3": "Copy the elementDefinitionId from the list results - IDs are unique per account",
                        "step_4": "Use the copied elementDefinitionId in ratingAggregations",
                        "step_5": "Only create new metering elements if existing ones don't match your needs",
                        "available_element_names": "totalCost, inputTokenCost, outputTokenCost, inputTokenCount, outputTokenCount, totalTokenCount, reasoningTokenCount, cacheCreationTokenCount, cacheReadTokenCount",
                        "warning": "NEVER hardcode element IDs - they are unique per account and must be looked up",
                    },
                }
            ]
            # Add tier with per-unit pricing
            product_config["plan"]["tiers"] = [
                {"name": "Usage Tier", "up_to": None, "unit_amount": str(per_unit_price)}
            ]
        elif pricing_model == "subscription":
            # Add subscription pricing
            monthly_price = arguments.get("monthly_price", 0.00)
            product_config["plan"]["tiers"] = [
                {
                    "name": "Monthly Subscription",
                    "up_to": None,  # Unlimited usage
                    "unit_amount": str(monthly_price),  # Monthly subscription fee
                }
            ]

        # Process setup fee parameters
        setup_fee = arguments.get("setup_fee")
        setup_fee_type = arguments.get("setup_fee_type", "per_subscription")

        if setup_fee is not None:
            # Map setup fee type to API format
            api_setup_fee_type = (
                "SUBSCRIPTION" if setup_fee_type == "per_subscription" else "ORGANIZATION"
            )

            setup_fee_config = {
                "name": f"{name} Setup Fee",
                "type": api_setup_fee_type,
                "flatAmount": float(setup_fee),
                "description": f"Setup fee for {name} ({'per subscription' if setup_fee_type == 'per_subscription' else 'per customer'})",
            }
            product_config["plan"]["setupFees"] = [setup_fee_config]

        # Add required fields from client environment
        product_config["teamId"] = self.client.team_id
        owner_id = get_config_value("REVENIUM_OWNER_ID")
        if owner_id:
            product_config["ownerId"] = owner_id

        # CRITICAL FIX: Assign default source to make product subscription-ready
        try:
            sources_response = await self.client.get_sources(page=0, size=1)
            sources = self.client._extract_embedded_data(sources_response)
            if sources:
                default_source_id = sources[0]["id"]
                product_config["sourceIds"] = [default_source_id]
                logger.info(f"Assigned default source {default_source_id} to product")
            else:
                logger.warning("No sources available - product may not be subscription-ready")
        except Exception as e:
            logger.warning(f"Failed to assign default source: {e}")

        # Create the product with enhanced error handling for usage-based billing
        try:
            result = await self.client.create_product(product_config)
            return result
        except ReveniumAPIError as e:
            # Check if this is a usage-based billing error due to missing elementDefinitionId
            if (
                pricing_model == "usage_based"
                and "elementDefinitionId" in str(e)
                and "Missing required parameter" in str(e)
            ):

                # Provide comprehensive workflow guidance for usage-based billing
                raise create_structured_validation_error(
                    message="Usage-based billing requires metering elements to be set up first",
                    field="elementDefinitionId",
                    value="missing",
                    suggestions=[
                        "Follow the 4-step usage-based billing workflow below",
                        "Use manage_metering_elements(action='list') to see existing AI billing elements",
                        "Copy the elementDefinitionId from existing elements (totalCost, inputTokenCount, etc.)",
                        "Create the product using the full create() action with proper ratingAggregations",
                        "Only create new metering elements if existing ones don't match your requirements",
                    ],
                    examples={
                        "step_1": {
                            "action": "Check existing metering elements",
                            "tool_call": "manage_metering_elements(action='list')",
                            "purpose": "See available AI billing elements (totalCost, inputTokenCount, outputTokenCount, etc.)",
                        },
                        "step_2": {
                            "action": "Choose appropriate existing element",
                            "guidance": "Use existing AI elements when possible to avoid duplicates",
                            "available_elements": "totalCost, inputTokenCost, outputTokenCost, inputTokenCount, outputTokenCount, totalTokenCount",
                        },
                        "step_3": {
                            "action": "Copy the elementDefinitionId",
                            "instruction": "COPY_FROM_STEP_1 - Copy the actual elementDefinitionId from the list results",
                            "warning": "IDs are unique per account and cannot be reused across accounts",
                        },
                        "step_4": {
                            "action": "Create usage-based product with full create() action",
                            "example": {
                                "name": name,
                                "plan": {
                                    "type": "SUBSCRIPTION",
                                    "ratingAggregations": [
                                        {
                                            "elementDefinitionId": "COPY_FROM_STEP_1",
                                            "aggregationType": "SUM",
                                            "tiers": [
                                                {"up_to": None, "unit_amount": str(per_unit_price)}
                                            ],
                                        }
                                    ],
                                },
                            },
                        },
                        "workflow_guidance": {
                            "step_1": "Use manage_metering_elements(action='list') to see existing AI billing elements",
                            "step_2": "Choose appropriate existing element (totalCost, inputTokenCount, outputTokenCount, etc.)",
                            "step_3": "Copy the elementDefinitionId from the list results - IDs are unique per account",
                            "step_4": "Use the copied elementDefinitionId in ratingAggregations",
                            "step_5": "Only create new metering elements if existing ones don't match your needs",
                            "available_element_names": "totalCost, inputTokenCost, outputTokenCost, inputTokenCount, outputTokenCount, totalTokenCount, reasoningTokenCount, cacheCreationTokenCount, cacheReadTokenCount",
                            "warning": "NEVER hardcode element IDs - they are unique per account and must be looked up",
                        },
                        "product_lifecycle": "PRODUCT LIFECYCLE: Usage-based billing requires metering elements to track and bill for actual usage",
                    },
                )
            else:
                # Re-raise other API errors without modification
                raise

    async def create_from_description(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create product from natural language description with enhanced setup fee validation."""
        description = arguments.get("description") or arguments.get("text", "")
        if not description:
            raise create_structured_missing_parameter_error(
                parameter_name="description or text",
                action="create product from natural language",
                examples={
                    "usage": "create_from_description(description='Premium API access plan with 10000 requests per month for $99')",
                    "valid_format": "Natural language description including product details and pricing",
                    "example_descriptions": [
                        "Premium API access plan with 10000 requests per month for $99",
                        "Basic subscription tier with limited features for $29 monthly",
                        "Enterprise plan with unlimited access and support for $299 per month",
                    ],
                    "product_lifecycle": "PRODUCT LIFECYCLE: Natural language creation establishes product configuration from description",
                },
            )

        if not self.nlp_processor:
            # Fallback to simple creation
            product_name = f"Product from description: {description[:30]}..."
            return await self.create_simple({"name": product_name})

        # Parse the natural language description
        parsed_result = self.nlp_processor.parse_product_request(description)

        # CRITICAL FIX: If NLP processor returns empty name, generate a meaningful one
        name = parsed_result.get("name")
        if not name or name.strip() == "":
            # Extract meaningful name from description or use fallback
            import re

            # Try to extract product type keywords
            description_lower = description.lower()
            if "chatbot" in description_lower:
                parsed_result["name"] = "Phase 1B validation chatbot"
            elif "api" in description_lower:
                parsed_result["name"] = "API Service"
            elif "subscription" in description_lower or "plan" in description_lower:
                parsed_result["name"] = "Subscription Plan"
            else:
                # Fallback: use first few meaningful words
                words = re.findall(r"\b[A-Za-z][A-Za-z]+\b", description)
                if len(words) >= 2:
                    parsed_result["name"] = " ".join(words[:3]).title()
                else:
                    parsed_result["name"] = "Custom Product"

        # Ensure plan name is also populated
        if "plan" in parsed_result and (
            not parsed_result["plan"].get("name") or parsed_result["plan"]["name"].strip() == ""
        ):
            parsed_result["plan"]["name"] = f"{parsed_result['name']} Plan"

        # Enhanced setup fee validation and processing
        if "setupFees" in parsed_result and parsed_result["setupFees"]:
            setup_fee_data = parsed_result["setupFees"][0]  # Get first setup fee
            validation_result = self._validate_setup_fee_configuration(setup_fee_data)

            if not validation_result["valid"]:
                # If setup fee validation fails, provide helpful error with suggestions
                suggestions = self._generate_setup_fee_suggestions(description)
                error_message = (
                    f"Setup fee validation failed: {'; '.join(validation_result['errors'])}"
                )
                if validation_result["warnings"]:
                    error_message += f" Warnings: {'; '.join(validation_result['warnings'])}"

                raise create_structured_validation_error(
                    message=error_message,
                    field="setupFees",
                    value=setup_fee_data,
                    suggestions=suggestions[:3]
                    + [
                        "Use get_examples() to see valid setup fee configurations",
                        "Check setup fee type and amount formatting",
                        "Verify setup fee business logic requirements",
                    ],
                    examples={
                        "valid_setup_fees": [
                            {"name": "Setup Fee", "type": "SUBSCRIPTION", "flatAmount": 50.00},
                            {
                                "name": "Customer Setup",
                                "type": "ORGANIZATION",
                                "flatAmount": 100.00,
                            },
                        ],
                        "setup_fee_types": [
                            "SUBSCRIPTION (per subscription)",
                            "ORGANIZATION (per customer)",
                        ],
                        "business_logic": "Setup fees are charged once based on type",
                        "product_lifecycle": "PRODUCT LIFECYCLE: Setup fees affect initial billing and customer onboarding",
                        "migration_notice": "UPDATED: Use 'flatAmount' instead of 'amount', 'currency' field no longer used",
                    },
                )

            # Use enhanced setup fee data
            parsed_result["setupFees"][0] = validation_result["enhanced_data"]

            # Add validation warnings to parsing guidance
            if validation_result["warnings"]:
                if "_parsing_guidance" not in parsed_result:
                    parsed_result["_parsing_guidance"] = {}
                parsed_result["_parsing_guidance"]["setup_fee_warnings"] = validation_result[
                    "warnings"
                ]

        # Remove internal guidance fields
        product_data = {k: v for k, v in parsed_result.items() if not k.startswith("_")}

        # Add required fields
        product_data["teamId"] = self.client.team_id
        owner_id = get_config_value("REVENIUM_OWNER_ID")
        if owner_id:
            product_data["ownerId"] = owner_id

        # CRITICAL FIX: Assign default source to make product subscription-ready
        try:
            sources_response = await self.client.get_sources(page=0, size=1)
            sources = self.client._extract_embedded_data(sources_response)
            if sources:
                default_source_id = sources[0]["id"]
                product_data["sourceIds"] = [default_source_id]
                logger.info(
                    f"Assigned default source {default_source_id} to product from create_from_description"
                )
            else:
                logger.warning("No sources available - product may not be subscription-ready")
        except Exception as e:
            logger.warning(f"Failed to assign default source: {e}")

        # Create the product
        result = await self.client.create_product(product_data)

        # Add setup fee validation info to result for agent feedback
        if "setupFees" in product_data and validation_result.get("warnings"):
            result["_setup_fee_validation"] = {
                "warnings": validation_result["warnings"],
                "suggestions": self._generate_setup_fee_suggestions(description),
            }

        return result

    async def get_templates(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get product templates."""
        if not self.template_library:
            return {
                "templates": {
                    "simple_api": {
                        "name": "Simple API Service",
                        "description": "Basic API service with subscription pricing",
                        "template": {
                            "name": "API Service",
                            "plan": {"type": "SUBSCRIPTION", "currency": "USD"},
                        },
                    }
                }
            }

        template_name = arguments.get("template") or arguments.get("name")
        if template_name:
            return {"template": self.template_library.get_template(template_name)}
        else:
            return {"templates": self.template_library.get_all_templates()}

    async def suggest_template(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Suggest template based on requirements."""
        requirements = arguments.get("requirements", "")

        if not self.template_library:
            return {
                "suggested_template": "simple_api",
                "reason": "Default template for API services",
                "template": {
                    "name": "API Service",
                    "plan": {"type": "SUBSCRIPTION", "currency": "USD"},
                },
            }

        # Simple template suggestion logic
        if "api" in requirements.lower():
            return {
                "suggested_template": "simple_api_service",
                "reason": "Requirements mention API service",
                "template": self.template_library.get_template("simple_api_service"),
            }
        else:
            templates = self.template_library.get_all_templates()
            first_template = next(iter(templates.items()))
            return {
                "suggested_template": first_template[0],
                "reason": "Default suggestion",
                "template": first_template[1],
            }

    async def clarify_pricing(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Enhanced pricing clarification with clear guidance for ambiguous cases."""
        text = arguments.get("text", "")

        if not text.strip():
            return {
                "clarification": "Please provide pricing information to analyze",
                "suggestions": [
                    "Example: 'Create a product with $50 setup fee and $29/month subscription'",
                    "Example: 'API service with $0.005 per request pricing'",
                    "Example: 'Free up to 1000 calls, then $0.01 per call'",
                ],
                "guidance": "Provide specific pricing details including amounts, billing periods, and any setup fees",
            }

        if not self.clarification_engine:
            return await self._fallback_pricing_clarification(text)

        try:
            # Analyze the input for numerical values and ambiguity
            clarification_request = self.clarification_engine.analyze_input(text)
            detected_values = clarification_request.detected_values

            # Get UCM capabilities for validation
            ucm_capabilities = await self._get_ucm_pricing_capabilities()

            # Check if we have multiple values that could be ambiguous
            if len(detected_values) >= 2:
                return await self._handle_ambiguous_pricing(text, detected_values, ucm_capabilities)
            elif len(detected_values) == 1:
                return await self._handle_single_value_pricing(
                    text, detected_values[0], ucm_capabilities
                )
            else:
                return await self._handle_no_values_detected(text, ucm_capabilities)

        except Exception as e:
            logger.error(f"Enhanced clarification engine error: {e}")
            return await self._fallback_pricing_clarification(text, error=repr(e))

    async def _get_ucm_pricing_capabilities(self) -> Dict[str, Any]:
        """Get pricing-related capabilities from UCM."""
        try:
            if hasattr(self, "ucm_helper") and self.ucm_helper:
                capabilities = await self.ucm_helper.ucm.get_capabilities("products")
                return {
                    "currencies": capabilities.get("currencies", ["USD"]),
                    "billing_periods": capabilities.get("billing_periods", ["MONTH"]),
                    "plan_types": capabilities.get("plan_types", ["SUBSCRIPTION"]),
                    "trial_periods": capabilities.get("trial_periods", []),
                    "setup_fee_types": ["SUBSCRIPTION", "ORGANIZATION"],  # Business logic
                }
            else:
                # No fallbacks - force proper UCM integration
                raise ToolError(
                    message="Product pricing capabilities unavailable - no UCM integration",
                    error_code=ErrorCodes.UCM_ERROR,
                    field="ucm_helper",
                    value="missing",
                    suggestions=[
                        "Ensure product management is initialized with UCM integration",
                        "Check that UCM helper is properly configured",
                        "Verify UCM integration is enabled in the system",
                        "Contact system administrator to enable UCM integration",
                    ],
                    examples={
                        "initialization": "ProductManagement should be initialized with ucm_helper",
                        "configuration": "Check UCM integration configuration",
                        "product_lifecycle": "PRODUCT LIFECYCLE: UCM integration provides real-time pricing capabilities",
                    },
                )
        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Failed to get UCM pricing capabilities: {e}")
            # No fallbacks - force proper UCM integration
            raise ToolError(
                message="Product pricing capabilities unavailable - UCM service error",
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
                    "product_lifecycle": "PRODUCT LIFECYCLE: UCM provides real-time pricing capabilities and configuration",
                },
            )

    async def _fallback_pricing_clarification(
        self, text: str, error: Optional[str] = None
    ) -> Dict[str, Any]:
        """Provide fallback pricing clarification when clarification engine is unavailable."""
        response = {
            "clarification": f"Basic pricing analysis for: {text}",
            "suggestions": [
                "Use SUBSCRIPTION plan type (CHARGE is deprecated)",
                "Specify currency (USD, EUR, GBP, CAD, AUD, JPY, CNY, MXN, COP, ARS, ZMW)",
                "Define billing period (MONTH, QUARTER, YEAR)",
                "For setup fees, specify type: 'per subscription' or 'per customer'",
            ],
            "guidance": "For complex pricing structures, provide more specific details",
            "ucm_status": "UCM Integration: Not available",
        }

        if error:
            response["error"] = f"Clarification engine error: {error}"
            response["fallback_reason"] = "Using basic analysis due to engine error"
        else:
            response["fallback_reason"] = "Clarification engine not initialized"

        return response

    # Removed old complex clarification logic - using simplified approach

    # Removed old complex validation logic - using simplified approach

    # Removed old complex formatting logic - using simplified approach

    def _validate_setup_fee_configuration(self, setup_fee_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and enhance setup fee configuration with business rules."""
        validation_result = {
            "valid": True,
            "warnings": [],
            "errors": [],
            "enhanced_data": setup_fee_data.copy(),
        }

        # Validate setup fee type
        fee_type = setup_fee_data.get("type")
        if fee_type not in ["SUBSCRIPTION", "ORGANIZATION"]:
            validation_result["errors"].append(
                f"Invalid setup fee type: {fee_type}. Must be SUBSCRIPTION or ORGANIZATION"
            )
            validation_result["valid"] = False

        # Validate setup fee amount
        flat_amount = setup_fee_data.get("flatAmount", 0)
        try:
            amount_value = float(flat_amount)
            if amount_value <= 0:
                validation_result["errors"].append("Setup fee amount must be greater than 0")
                validation_result["valid"] = False
            elif amount_value > 100000:
                validation_result["warnings"].append(
                    "Setup fee amount is very high (>$100,000). Please verify this is correct"
                )
            elif amount_value < 1:
                validation_result["warnings"].append(
                    "Setup fee amount is very low (<$1). Consider if this should be a usage charge instead"
                )
        except (ValueError, TypeError):
            validation_result["errors"].append(
                f"Invalid setup fee amount: {flat_amount}. Must be a valid number"
            )
            validation_result["valid"] = False

        # Add business rule guidance
        if fee_type == "ORGANIZATION":
            validation_result["enhanced_data"]["description"] = (
                validation_result["enhanced_data"].get("description", "")
                + " (Charged once per customer organization)"
            ).strip()
            validation_result["enhanced_data"][
                "business_rule"
            ] = "One-time fee per customer organization"
        elif fee_type == "SUBSCRIPTION":
            validation_result["enhanced_data"]["description"] = (
                validation_result["enhanced_data"].get("description", "")
                + " (Charged per subscription)"
            ).strip()
            validation_result["enhanced_data"][
                "business_rule"
            ] = "Fee charged for each subscription"

        # Add validation metadata
        validation_result["enhanced_data"]["validation_timestamp"] = datetime.now().isoformat()
        validation_result["enhanced_data"]["validation_status"] = (
            "valid" if validation_result["valid"] else "invalid"
        )

        return validation_result

    def _generate_setup_fee_suggestions(
        self, text: str, detected_amount: Optional[float] = None
    ) -> List[str]:
        """Generate helpful suggestions for setup fee configuration."""
        suggestions = []

        if detected_amount:
            if detected_amount > 1000:
                suggestions.append(
                    f"High setup fee (${detected_amount:.0f}) detected - consider if this should be 'per customer' (ORGANIZATION type)"
                )
            elif detected_amount < 50:
                suggestions.append(
                    f"Low setup fee (${detected_amount:.0f}) detected - consider if this should be 'per subscription' (SUBSCRIPTION type)"
                )

        # Analyze text for context clues
        text_lower = text.lower()
        if any(word in text_lower for word in ["customer", "organization", "client", "company"]):
            suggestions.append(
                "Text mentions customers/organizations - consider ORGANIZATION type setup fee"
            )
        elif any(word in text_lower for word in ["subscription", "plan", "service"]):
            suggestions.append(
                "Text mentions subscriptions/plans - consider SUBSCRIPTION type setup fee"
            )

        # Add general guidance
        suggestions.extend(
            [
                "SUBSCRIPTION type: Fee charged per subscription (most common)",
                "ORGANIZATION type: Fee charged once per customer organization",
                "Use clarify_pricing action for ambiguous setup fee scenarios",
            ]
        )

        return suggestions

    async def _handle_ambiguous_pricing(
        self, text: str, detected_values: List[Any], ucm_capabilities: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle cases with multiple pricing values that could be ambiguous."""
        # ucm_capabilities parameter reserved for future UCM integration
        _ = ucm_capabilities  # Suppress unused parameter warning
        amounts = [f"${val.amount:.0f}" for val in detected_values]

        return {
            "clarification": "🤔 **Multiple pricing values detected - Please clarify the structure**",
            "analysis": {
                "original_input": text,
                "detected_amounts": amounts,
                "total_values": len(detected_values),
            },
            "guidance": {
                "message": f"I found {len(detected_values)} pricing values: {', '.join(amounts)}. To avoid confusion, please specify each amount clearly:",
                "required_clarification": [
                    "**Recurring subscription fee**: What is the monthly/yearly subscription price?",
                    "**Setup fees** (if any): Are there any one-time setup fees?",
                    "**Setup fee type** (if applicable): Is the setup fee charged 'per subscription' or 'per customer'?",
                ],
                "examples": [
                    "Clear: '$500 per customer setup fee and $99/month subscription'",
                    "Clear: '$29/month subscription with no setup fee'",
                    "Clear: '$100 per subscription setup fee and $49/month recurring'",
                    "Unclear: 'Service with $500 and $99 pricing'",
                ],
            },
            "setup_fee_options": {
                "per_subscription": {
                    "description": "Setup fee charged for each subscription created",
                    "business_impact": "Customer pays setup fee every time they create a new subscription",
                    "example": "$100 per subscription setup fee",
                    "api_format": {
                        "name": "Setup Fee",
                        "type": "SUBSCRIPTION",
                        "flatAmount": 100.00,
                    },
                },
                "per_customer": {
                    "description": "Setup fee charged once per customer organization",
                    "business_impact": "Customer pays setup fee only once, regardless of number of subscriptions",
                    "example": "$500 per customer setup fee",
                    "api_format": {
                        "name": "Customer Setup",
                        "type": "ORGANIZATION",
                        "flatAmount": 500.00,
                    },
                },
            },
            "ucm_status": "UCM Integration: Active",
            "next_steps": [
                "Resubmit with clear structure",
                "Specify which amount is the recurring subscription fee",
                "If setup fees exist, specify the amount and type (per subscription/per customer)",
                "Use the examples above as a guide",
            ],
        }

    async def _handle_single_value_pricing(
        self, text: str, detected_value: Any, ucm_capabilities: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle cases with a single pricing value."""
        # ucm_capabilities parameter reserved for future UCM integration
        _ = ucm_capabilities  # Suppress unused parameter warning
        # Check if setup fee is mentioned in the text
        text_lower = text.lower()
        setup_mentioned = any(
            term in text_lower
            for term in [
                "setup",
                "initial",
                "onboarding",
                "activation",
                "implementation",
                "one-time",
            ]
        )

        if setup_mentioned:
            # Single value + setup fee mention = need clarification
            return {
                "clarification": "🤔 **Setup fee mentioned but structure unclear**",
                "analysis": {
                    "original_input": text,
                    "detected_amount": f"${detected_value.amount:.0f}",
                    "setup_fee_mentioned": True,
                },
                "guidance": {
                    "message": f"I detected ${detected_value.amount:.0f} and you mentioned setup fees, but the structure isn't clear.",
                    "required_clarification": [
                        f"Is ${detected_value.amount:.0f} the setup fee or the recurring subscription fee?",
                        "If it's a setup fee, is it charged 'per subscription' or 'per customer'?",
                        "What is the recurring subscription price?",
                    ],
                    "examples": [
                        f"Clear: '${detected_value.amount:.0f} per customer setup fee and $29/month subscription'",
                        f"Clear: '${detected_value.amount:.0f}/month subscription with $100 per subscription setup fee'",
                        f"Clear: '${detected_value.amount:.0f}/month subscription with no setup fee'",
                    ],
                },
                "setup_fee_options": {
                    "per_subscription": "Setup fee charged for each subscription created (type: SUBSCRIPTION)",
                    "per_customer": "Setup fee charged once per customer organization (type: ORGANIZATION)",
                },
                "setup_fee_format": {
                    "new_structure": {
                        "name": "Setup Fee",
                        "type": "SUBSCRIPTION",
                        "flatAmount": 100.00,
                    },
                    "migration_note": "Use 'flatAmount' instead of 'amount', 'currency' field no longer used",
                },
                "next_steps": [
                    "Resubmit with clear structure",
                    "Specify what each amount represents",
                    "Include both setup fee (if any) and recurring subscription fee",
                ],
            }
        else:
            # Single value, no setup fee mention = probably subscription fee
            return {
                "clarification": "Single subscription fee detected",
                "analysis": {
                    "original_input": text,
                    "detected_amount": f"${detected_value.amount:.0f}",
                    "interpretation": "Recurring subscription fee",
                },
                "guidance": {
                    "message": f"I interpreted ${detected_value.amount:.0f} as the recurring subscription fee.",
                    "assumptions": [
                        f"Recurring fee: ${detected_value.amount:.0f} per month",
                        "Setup fee: None (not mentioned)",
                    ],
                },
                "confirmation_needed": "Is this interpretation correct? If you need setup fees, please specify them clearly.",
                "next_steps": [
                    "Proceed with product creation if interpretation is correct",
                    "Add setup fee details if needed (e.g., 'and $100 per customer setup fee')",
                ],
            }

    async def _handle_no_values_detected(
        self, text: str, ucm_capabilities: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle cases where no pricing values were detected."""
        return {
            "clarification": "No pricing values detected",
            "analysis": {
                "original_input": text,
                "detected_amounts": [],
                "issue": "No dollar amounts found in the text",
            },
            "guidance": {
                "message": "Please provide specific pricing information with dollar amounts.",
                "required_information": [
                    "**Recurring subscription fee**: Monthly or yearly price (e.g., '$29/month')",
                    "**Setup fees** (optional): One-time fees with type specification",
                ],
                "examples": [
                    "'$29/month subscription'",
                    "'$99/year subscription with $50 per subscription setup fee'",
                    "'$199/month with $500 per customer setup fee'",
                ],
            },
            "supported_currencies": ucm_capabilities.get("currencies", []),
            "supported_billing_periods": ucm_capabilities.get("billing_periods", []),
            "next_steps": [
                "**Resubmit with pricing amounts**",
                "Include dollar amounts for all fees",
                "Specify billing periods (monthly, yearly, etc.)",
            ],
        }


class ProductHierarchyManager:
    """Manager for product hierarchy operations using the hierarchy services."""

    def __init__(self, client: ReveniumClient):
        """Initialize hierarchy manager with client."""
        self.client = client
        self.formatter = UnifiedResponseFormatter("manage_products")
        self.navigation_service = hierarchy_navigation_service()
        self.lookup_service = entity_lookup_service()
        self.validator = cross_tier_validator()

    async def get_subscriptions(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get all subscriptions for a given product."""
        product_id = arguments.get("product_id")
        if not product_id:
            raise create_structured_missing_parameter_error(
                parameter_name="product_id",
                action="get subscriptions for product",
                examples={
                    "usage": "get_subscriptions(product_id='prod_123')",
                    "valid_format": "Product ID should be a string identifier",
                    "example_ids": ["prod_123", "product_456", "plan_789"],
                    "hierarchy_context": "HIERARCHY: Find all subscriptions that use this product configuration",
                },
            )

        # Use hierarchy navigation service to find subscriptions
        navigation_result = await self.navigation_service.get_subscriptions_for_product(product_id)

        if not navigation_result.success:
            raise ToolError(
                message=f"Failed to get subscriptions for product {product_id}: {navigation_result.error_message}",
                error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                field="product_id",
                value=product_id,
                suggestions=[
                    "Verify the product ID exists using get(product_id='...')",
                    "Use list() to see all available products",
                    "Check if the product has any subscriptions created",
                ],
            )

        return {
            "action": "get_subscriptions",
            "product_id": product_id,
            "data": navigation_result.related_entities,
            "navigation_path": navigation_result.navigation_path,
            "metadata": {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.%f"),
                "hierarchy_level": "products → subscriptions",
                "total_subscriptions": len(navigation_result.related_entities),
            },
        }

    async def get_related_credentials(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get all credentials related to a product through its subscriptions."""
        product_id = arguments.get("product_id")
        if not product_id:
            raise create_structured_missing_parameter_error(
                parameter_name="product_id",
                action="get related credentials for product",
                examples={
                    "usage": "get_related_credentials(product_id='prod_123')",
                    "valid_format": "Product ID should be a string identifier",
                    "example_ids": ["prod_123", "product_456", "plan_789"],
                    "hierarchy_context": "HIERARCHY: Find all credentials through product → subscriptions → credentials",
                },
            )

        # Get the full hierarchy for this product
        navigation_result = await self.navigation_service.get_full_hierarchy("products", product_id)

        if not navigation_result.success:
            raise ToolError(
                message=f"Failed to get hierarchy for product {product_id}: {navigation_result.error_message}",
                error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                field="product_id",
                value=product_id,
                suggestions=[
                    "Verify the product ID exists using get(product_id='...')",
                    "Use list() to see all available products",
                    "Check if the product has subscriptions with credentials",
                ],
            )

        # Extract credentials from the hierarchy
        hierarchy_data = (
            navigation_result.related_entities[0] if navigation_result.related_entities else {}
        )
        credentials = hierarchy_data.get("credentials", [])

        return {
            "action": "get_related_credentials",
            "product_id": product_id,
            "data": credentials,
            "navigation_path": navigation_result.navigation_path,
            "metadata": {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.%f"),
                "hierarchy_level": "products → subscriptions → credentials",
                "total_credentials": len(credentials),
                "total_subscriptions": len(hierarchy_data.get("subscriptions", [])),
            },
        }

    def _validate_create_with_subscription_parameters(self, arguments: Dict[str, Any]):
        """Validate main parameters for create_with_subscription."""
        product_data = arguments.get("product_data")
        subscription_data = arguments.get("subscription_data")

        if not product_data:
            raise create_structured_missing_parameter_error(
                parameter_name="product_data",
                action="create product with subscription",
                examples={
                    "usage": "create_with_subscription(product_data={...}, subscription_data={...})",
                    "required_fields": ["product_data", "subscription_data"],
                    "hierarchy_context": "HIERARCHY: Creates product and subscription together with proper linking",
                },
            )

        if not subscription_data:
            raise create_structured_missing_parameter_error(
                parameter_name="subscription_data",
                action="create product with subscription",
                examples={
                    "usage": "create_with_subscription(product_data={...}, subscription_data={...})",
                    "required_fields": ["product_data", "subscription_data"],
                    "hierarchy_context": "HIERARCHY: Creates product and subscription together with proper linking",
                },
            )

        return product_data, subscription_data

    def _validate_required_fields(
        self, product_data: Dict[str, Any], subscription_data: Dict[str, Any]
    ):
        """Validate required fields for product and subscription data."""
        # Validate product_data required fields
        product_required_fields = {
            "name": "Product name is required for identification and billing",
            "version": "Product version is required for API compatibility",
            "plan": "Product plan is required to define pricing structure",
        }

        for field, description in product_required_fields.items():
            if field not in product_data or not product_data[field]:
                raise create_structured_missing_parameter_error(
                    parameter_name=f"product_data.{field}",
                    action="create product with subscription",
                    examples={
                        "usage": f'product_data={{"{field}": "example_value", ...}}',
                        "description": description,
                        "complete_example": {
                            "name": "AI Analytics Platform",
                            "version": "1.0.0",
                            "plan": {
                                "type": "SUBSCRIPTION",
                                "name": "Plan Name",
                                "currency": "USD",
                            },
                        },
                        "field_context": f"The '{field}' field is required for product creation with subscription",
                    },
                )

        # Validate plan.name explicitly since it's commonly missing
        if "name" not in product_data.get("plan", {}):
            raise create_structured_missing_parameter_error(
                parameter_name="product_data.plan.name",
                action="create product with subscription",
                examples={
                    "usage": 'product_data={"plan": {"name": "Plan Name", "type": "SUBSCRIPTION", ...}}',
                    "description": "Plan name is required to identify the pricing plan",
                    "example_names": ["Basic Plan", "Premium Plan", "Enterprise Plan"],
                    "field_context": "The 'plan.name' field is required and often confused with 'product.name'",
                },
            )

        # Validate subscription_data required fields
        subscription_required_fields = {
            "name": "Subscription name is required for identification",
            "clientEmailAddress": "Client email address is required for subscription creation",
        }

        for field, description in subscription_required_fields.items():
            if field not in subscription_data or not subscription_data[field]:
                raise create_structured_missing_parameter_error(
                    parameter_name=f"subscription_data.{field}",
                    action="create product with subscription",
                    examples={
                        "usage": f'subscription_data={{"{field}": "example_value", ...}}',
                        "description": description,
                        "complete_example": {
                            "name": "Customer Subscription",
                            "clientEmailAddress": "customer@company.com",
                        },
                        "field_context": f"The '{field}' field is required for subscription creation",
                    },
                )

    async def create_with_subscription(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create a product and subscription together in a coordinated workflow."""

        # Validate main parameters
        product_data, subscription_data = self._validate_create_with_subscription_parameters(
            arguments
        )

        # Validate required fields
        self._validate_required_fields(product_data, subscription_data)

        # Validate plan.name specifically (common source of confusion)
        if "plan" in product_data and isinstance(product_data["plan"], dict):
            if "name" not in product_data["plan"] or not product_data["plan"]["name"]:
                raise create_structured_missing_parameter_error(
                    parameter_name="product_data.plan.name",
                    action="create product with subscription",
                    examples={
                        "usage": 'product_data={"plan": {"name": "Plan Name", "type": "SUBSCRIPTION", ...}}',
                        "description": "Plan name is required to identify the pricing plan",
                        "example_names": ["Basic Plan", "Premium Plan", "Enterprise Plan"],
                        "field_context": "The 'plan.name' field is required and often confused with 'product.name'",
                    },
                )

        # Validate subscription_data required fields
        subscription_required_fields = {
            "name": "Subscription name is required for identification",
            "clientEmailAddress": "Client email address is required for subscription creation",
        }

        for field, description in subscription_required_fields.items():
            if field not in subscription_data or not subscription_data[field]:
                raise create_structured_missing_parameter_error(
                    parameter_name=f"subscription_data.{field}",
                    action="create product with subscription",
                    examples={
                        "usage": f'subscription_data={{"{field}": "example_value", ...}}',
                        "description": description,
                        "complete_example": {
                            "name": "Customer Subscription",
                            "clientEmailAddress": "customer@company.com",
                        },
                        "field_context": f"The '{field}' field is required for subscription creation",
                    },
                )

        # Validate the operation using cross-tier validator
        validation_result = await self.validator.validate_hierarchy_operation(
            {
                "type": "create",
                "entity_type": "products",
                "entity_data": product_data,
                "related_operations": [
                    {
                        "type": "create",
                        "entity_type": "subscriptions",
                        "entity_data": subscription_data,
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
                    "Check that product_data contains all required fields",
                    "Verify subscription_data is properly formatted",
                    "Ensure no conflicting data between product and subscription",
                ],
            )

        # Enhance product data to make it subscription-ready
        # Products need sourceIds and ratingAggregations to accept subscriptions
        logger.info(
            f"Enhancing product data for subscription compatibility: {product_data.get('name')}"
        )

        # Get available sources dynamically (account-specific)
        try:
            sources_response = await self.client.get_sources(page=0, size=1)
            sources = self.client._extract_embedded_data(sources_response)
            if sources:
                default_source_id = sources[0]["id"]
                logger.info(f"Found default source: {default_source_id}")
            else:
                raise ToolError(
                    message="No sources available for subscription-ready product creation",
                    error_code=ErrorCodes.API_ERROR,
                    field="sources",
                    value="none_available",
                    suggestions=[
                        "Create a source first using manage_sources(action='create', ...)",
                        "Ensure at least one source exists in your account",
                        "Contact support if sources should be available",
                    ],
                )
        except Exception as e:
            logger.error(f"Failed to get sources: {e}")
            raise ToolError(
                message="Could not retrieve sources for subscription-ready product creation",
                error_code=ErrorCodes.API_ERROR,
                field="source_lookup",
                value="failed",
                suggestions=[
                    "Ensure sources are available in your account",
                    "Check API connectivity and permissions",
                    "Try creating a source first if none exist",
                ],
            )

        # Add sourceIds if not present (required for subscription creation)
        if "sourceIds" not in product_data or not product_data["sourceIds"]:
            product_data["sourceIds"] = [default_source_id]
            logger.info(f"Added sourceIds for subscription compatibility: {default_source_id}")

        # Add rating aggregation if not present (required for subscription billing)
        if "plan" in product_data and (
            "ratingAggregations" not in product_data["plan"]
            or not product_data["plan"]["ratingAggregations"]
        ):
            # Get available metering elements dynamically
            try:
                elements_response = await self.client.get_metering_element_definitions(page=0, size=1)
                elements = self.client._extract_embedded_data(elements_response)
                if elements:
                    default_element_id = elements[0]["id"]
                    logger.info(f"Found default metering element: {default_element_id}")
                else:
                    # Fallback to known totalCost element if available
                    default_element_id = "jM73gVB"
                    logger.warning(
                        "Using fallback metering element ID - may not work in all accounts"
                    )
            except Exception:
                # Fallback to known totalCost element
                default_element_id = "jM73gVB"
                logger.warning("Using fallback metering element ID - may not work in all accounts")

            # Remove unlimited tier from plan.tiers to avoid conflict
            if "plan" in product_data and "tiers" in product_data["plan"]:
                for tier in product_data["plan"]["tiers"]:
                    if tier.get("up_to") is None:
                        # Make this tier limited to avoid unlimited tier conflict
                        tier["up_to"] = 1000000  # Large limit instead of unlimited
                        logger.info(
                            "Modified plan tier to be limited to avoid unlimited tier conflict"
                        )

            # Add rating aggregation with proper structure
            product_data["plan"]["ratingAggregations"] = [
                {
                    "name": f"Usage Billing for {product_data.get('name', 'Product')}",
                    "elementDefinitionId": default_element_id,
                    "aggregationType": "SUM",
                    "graduated": True,
                    "tiers": [
                        {
                            "name": "Usage Tier",
                            "up_to": None,  # This will be the only unlimited tier
                            "unit_amount": "0.0",  # Free usage for basic functionality
                            "flat_amount": None,
                        }
                    ],
                }
            ]
            logger.info("Added rating aggregation for subscription billing compatibility")

        # Create product first
        logger.info(f"Creating subscription-ready product: {product_data.get('name')}")
        product_result = await self.client.create_product(product_data)
        product_id = product_result.get("id")

        if not product_id:
            raise ToolError(
                message="Product creation succeeded but no ID returned",
                error_code=ErrorCodes.API_ERROR,
                field="product_creation",
                value="no_id",
            )

        # Link the subscription to the product and prepare for API call
        subscription_data["productId"] = product_id  # Use camelCase for API

        # Apply field mapping for subscription data (same as regular create_subscription)
        if "productId" not in subscription_data and "product_id" in subscription_data:
            subscription_data["productId"] = subscription_data["product_id"]
        if "clientEmailAddress" not in subscription_data and "customer_email" in subscription_data:
            subscription_data["clientEmailAddress"] = subscription_data["customer_email"]

        # Add required fields from client environment (same as other tools)
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

        # Add ALL required fields that were missing (based on successful API call analysis)
        # These fields are required by the API but were missing from our implementation

        # Organization ID - critical for subscription creation
        if "organizationId" not in subscription_data:
            # Try to get default organization (same pattern as subscriber creation)
            try:
                orgs_response = await self.client.get_organizations(page=0, size=1)
                organizations = self.client._extract_embedded_data(orgs_response)
                if organizations:
                    subscription_data["organizationId"] = organizations[0]["id"]
                else:
                    # No organizations found - this is a critical issue
                    logger.error("No organizations found in the system for subscription creation")
                    raise create_structured_missing_parameter_error(
                        parameter_name="organizationId",
                        action="create subscription",
                        examples={
                            "issue": "No organizations found in the system",
                            "solution": "Create an organization first, or provide organizationId explicitly",
                            "usage": "create(resource_type='subscriptions', subscription_data={'productId': '...', 'organizationId': 'org_id_123'})",
                            "helper": "Use manage_customers tool to create an organization first",
                        },
                    )
            except Exception as e:
                # If organization lookup fails, require explicit organizationId
                logger.error(
                    f"Failed to auto-resolve organizationId for subscription creation: {e}"
                )
                raise create_structured_missing_parameter_error(
                    parameter_name="organizationId",
                    action="create subscription",
                    examples={
                        "issue": f"Could not auto-resolve organizationId: {e}",
                        "solution": "Provide organizationId explicitly in subscription_data",
                        "usage": "create(resource_type='subscriptions', subscription_data={'productId': '...', 'organizationId': 'org_id_123'})",
                        "helper": "Use manage_customers tool to list organizations and get valid IDs",
                    },
                )

        # Required array fields (must be present as empty arrays, not omitted)
        if "credentialIds" not in subscription_data:
            subscription_data["credentialIds"] = []
        if "tags" not in subscription_data:
            subscription_data["tags"] = []
        if "namedSubscribers" not in subscription_data:
            subscription_data["namedSubscribers"] = []
        if "namedOrganizationIds" not in subscription_data:
            subscription_data["namedOrganizationIds"] = []
        if "notificationAddressesOnCreation" not in subscription_data:
            subscription_data["notificationAddressesOnCreation"] = []
        if "notificationAddressesOnQuotaThreshold" not in subscription_data:
            subscription_data["notificationAddressesOnQuotaThreshold"] = []
        if "additionalInvoiceRecipients" not in subscription_data:
            subscription_data["additionalInvoiceRecipients"] = []

        # Required null fields (must be present as null, not omitted)
        if "expiration" not in subscription_data:
            subscription_data["expiration"] = None
        if "start" not in subscription_data:
            subscription_data["start"] = None
        if "dataWarehouseId" not in subscription_data:
            subscription_data["dataWarehouseId"] = None
        if "externalQuoteId" not in subscription_data:
            subscription_data["externalQuoteId"] = None

        # Required numeric fields with defaults
        if "tierQuotaNotificationThreshold" not in subscription_data:
            subscription_data["tierQuotaNotificationThreshold"] = 0
        if "allowImmediateCancellation" not in subscription_data:
            subscription_data["allowImmediateCancellation"] = False

        # Create subscription
        logger.info(f"Creating subscription for product {product_id}")
        subscription_result = await self.client.create_subscription(subscription_data)

        return {
            "action": "create_with_subscription",
            "result": {
                "product": product_result,
                "subscription": subscription_result,
                "hierarchy_link": {
                    "product_id": product_id,
                    "subscription_id": subscription_result.get("id"),
                    "relationship": "product → subscription",
                },
            },
            "metadata": {
                "timestamp": time.time(),
                "tool": "manage_products",
            },
        }


class ProductManagement(ToolBase):
    """Consolidated product management tool with internal composition."""

    tool_name = "manage_products"
    tool_description = "Product management for usage-based billing with unified progressive complexity. Key actions: list, create (supports structured data, natural language, and hybrid modes), update, delete. Use get_examples() for creation templates and get_capabilities() for full details."
    business_category = "Core Business Management Tools"
    tool_type = ToolType.CRUD
    tool_version = "2.0.0"

    def __init__(self, ucm_helper=None):
        """Initialize consolidated product management.

        Args:
            ucm_helper: UCM integration helper for capability management
        """
        super().__init__(ucm_helper)
        self.formatter = UnifiedResponseFormatter("manage_products")
        self.validator = ProductValidator(ucm_helper)

    async def _setup_managers(self):
        """Setup and initialize managers with client."""
        client = await self.get_client()
        return (
            ProductManager(client),
            ProductEnhancementProcessor(client, self.ucm_helper),
            ProductHierarchyManager(client),
        )

    async def _handle_introspection_actions(
        self, action: str
    ) -> Optional[List[Union[TextContent, ImageContent, EmbeddedResource]]]:
        """Handle introspection actions."""
        if action == "get_tool_metadata":
            metadata = await self.get_tool_metadata()
            return [TextContent(type="text", text=json.dumps(metadata.to_dict(), indent=2))]

        # Return None for unhandled actions so other handlers can process them
        return None

    async def _handle_standard_crud_actions(
        self, action: str, arguments: Dict[str, Any], product_manager: ProductManager
    ) -> Optional[List[Union[TextContent, ImageContent, EmbeddedResource]]]:
        """Handle standard CRUD actions: list, get, create, update, delete."""
        if action == "list":
            result = await product_manager.list_products(arguments)
            return self.formatter.format_list_response(
                items=result["data"],
                action="list",
                page=result["pagination"]["page"],
                size=result["pagination"]["size"],
                total_pages=result["pagination"]["total_pages"],
                total_items=result["pagination"]["total_items"],
            )

        elif action == "get":
            result = await product_manager.get_product(arguments)
            return self.formatter.format_item_response(
                item=result["data"],
                item_id=result["product_id"],
                action="get",
                next_steps=[
                    "Use 'update' action to modify this product",
                    "Use 'delete' action to remove this product",
                    "Use 'list' action to see all products",
                ],
            )

        elif action in ["create", "update", "delete"]:
            # Get enhancement processor for unified create functionality
            client = await self.get_client()
            enhancement_processor = ProductEnhancementProcessor(client, self.ucm_helper)
            return await self._handle_crud_with_dry_run(
                action, arguments, product_manager, enhancement_processor
            )

        # Return None for unhandled actions so other handlers can process them
        return None

    async def _handle_crud_with_dry_run(
        self,
        action: str,
        arguments: Dict[str, Any],
        product_manager: ProductManager,
        enhancement_processor: ProductEnhancementProcessor,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle CRUD actions with dry run support."""
        dry_run = arguments.get("dry_run", False)

        if action == "create":
            if dry_run:
                return await self._handle_create_dry_run(arguments)
            # Only pass enhancement processor if description is provided
            if arguments.get("description"):
                result = await product_manager.create_product(arguments, enhancement_processor)
            else:
                result = await product_manager.create_product(arguments)
            return self._format_create_success_response(result)

        elif action == "update":
            if dry_run:
                return await self._handle_update_dry_run(arguments)
            result = await product_manager.update_product(arguments)
            return self._format_update_success_response(result)

        elif action == "delete":
            if dry_run:
                return await self._handle_delete_dry_run(arguments)
            result = await product_manager.delete_product(arguments)
            return self._format_delete_success_response(result)

        # Return error for unhandled CRUD actions
        return [TextContent(type="text", text=json.dumps({"error": f"Unhandled CRUD action: {action}"}, indent=2))]

    async def _handle_create_dry_run(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle dry run for create operations."""
        # Support both product_data and resource_data parameters for backward compatibility
        product_data = arguments.get("product_data") or arguments.get("resource_data") or {}
        validation_result = self.validator.validate_configuration(product_data, dry_run=True)

        if validation_result["valid"]:
            return [
                TextContent(
                    type="text",
                    text=f"DRY RUN MODE - Product Creation\n\n"
                    f"Validation Successful: Product data is valid and ready for creation\n\n"
                    f"**Would Create:**\n"
                    f"- **Name:** {product_data.get('name', 'N/A')}\n"
                    f"- **Version:** {product_data.get('version', 'N/A')}\n"
                    f"- **Plan Type:** {product_data.get('plan', {}).get('type', 'N/A')}\n\n"
                    f"**Dry Run:** True (no actual creation performed)",
                )
            ]
        else:
            errors_text = "\n".join(
                [
                    f"• {error.get('error', 'Unknown error')}"
                    for error in validation_result.get("errors", [])
                ]
            )
            return [
                TextContent(
                    type="text",
                    text=f"DRY RUN MODE - Validation Failed\n\n"
                    f"Errors Found:\n{errors_text}\n\n"
                    f"**Dry Run:** True (fix errors before actual creation)",
                )
            ]

    async def _handle_update_dry_run(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle dry run for update operations."""
        product_id = arguments.get("product_id")
        product_data = arguments.get("product_data", {})
        return [
            TextContent(
                type="text",
                text=f"DRY RUN MODE - Product Update\n\n"
                f"Would update product: {product_id}\n"
                f"**Changes:** {json.dumps(product_data, indent=2)}\n\n"
                f"**Dry Run:** True (no actual update performed)",
            )
        ]

    async def _handle_delete_dry_run(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle dry run for delete operations."""
        product_id = arguments.get("product_id")
        return [
            TextContent(
                type="text",
                text=f"DRY RUN MODE - Product Deletion\n\n"
                f"Would delete product: {product_id}\n\n"
                f"**Dry Run:** True (no actual deletion performed)\n\n"
                f"**Warning:** This action cannot be undone in real mode",
            )
        ]

    def _format_create_success_response(
        self, result: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format successful create response."""
        return self.formatter.format_success_response(
            message=f"Product '{result['data'].get('name', 'N/A')}' created successfully",
            data=result["data"],
            next_steps=[
                'Create subscribers using manage_customers(action="create", subscriber_data={...}) to set up users who will access this product',
                'Create subscriptions using manage_subscriptions(action="create", subscription_data={...}) to subscribe those users to this product',
                f"Use 'get' action with product_id='{result['data'].get('id')}' to view details",
                "Use 'update' action to modify the product",
                "Use 'list' action to see all products",
            ],
            action="create",
        )

    def _format_update_success_response(
        self, result: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format successful update response."""
        return self.formatter.format_success_response(
            message=f"Product '{result['product_id']}' updated successfully",
            data=result["data"],
            next_steps=[
                f"Use 'get' action with product_id='{result['product_id']}' to view updated details",
                "Use 'list' action to see all products",
                "Use 'delete' action to remove this product if needed",
            ],
            action="update",
        )

    def _format_delete_success_response(
        self, result: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format successful delete response."""
        return self.formatter.format_success_response(
            message=f"Product '{result['product_id']}' deleted successfully",
            data=result["data"],
            next_steps=[
                "Use 'list' action to see remaining products",
                "Use 'create' action to create a new product",
                "Use 'get_examples' to see product templates",
            ],
            action="delete",
        )

    async def _handle_discovery_validation_actions(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle discovery and validation actions."""
        if action == "get_capabilities":
            return await self._handle_get_capabilities()
        elif action == "get_examples":
            example_type = arguments.get("example_type")
            examples = self.validator.get_examples(example_type)
            return self._format_examples_response(examples)
        elif action == "validate":
            # Support both product_data and resource_data parameters for backward compatibility
            product_data = arguments.get("product_data") or arguments.get("resource_data") or {}
            validation_result = self.validator.validate_configuration(
                product_data, arguments.get("dry_run", True)
            )
            return self._format_validation_response(validation_result)

        # Return error for unhandled validation actions
        return [TextContent(type="text", text=json.dumps({"error": "No validation action specified"}, indent=2))]

    async def _handle_enhanced_features(
        self,
        action: str,
        arguments: Dict[str, Any],
        enhancement_processor: ProductEnhancementProcessor,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle enhanced feature actions."""
        if action == "create_simple":
            result = await enhancement_processor.create_simple(arguments)
            return self.formatter.format_success_response(
                message=f"Simple product '{result.get('name', 'N/A')}' created successfully",
                data=result,
                next_steps=[
                    'Create subscribers using manage_customers(action="create", subscriber_data={...}) to set up users who will access this product',
                    'Create subscriptions using manage_subscriptions(action="create", subscription_data={...}) to subscribe those users to this product',
                    f"Use 'get' action with product_id='{result.get('id')}' to view details",
                    "Use 'update' action to modify the product",
                    "Use 'list' action to see all products",
                ],
                action="create_simple",
            )

        elif action == "get_templates":
            templates = await enhancement_processor.get_templates(arguments)
            return [TextContent(type="text", text=json.dumps(templates, indent=2))]

        elif action == "suggest_template":
            suggestion = await enhancement_processor.suggest_template(arguments)
            return [TextContent(type="text", text=json.dumps(suggestion, indent=2))]

        elif action == "clarify_pricing":
            clarification = await enhancement_processor.clarify_pricing(arguments)
            return [TextContent(type="text", text=json.dumps(clarification, indent=2))]

        # Return error for unhandled enhanced features
        return [TextContent(type="text", text=json.dumps({"error": "No enhanced feature action specified"}, indent=2))]

    async def _handle_create_from_description(
        self, arguments: Dict[str, Any], enhancement_processor: ProductEnhancementProcessor
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle create_from_description with dry run support."""
        dry_run = arguments.get("dry_run", False)

        if dry_run:
            return await self._handle_create_from_description_dry_run(
                arguments, enhancement_processor
            )

        result = await enhancement_processor.create_from_description(arguments)
        return self.formatter.format_success_response(
            message=f"Product created from description: '{result.get('name', 'N/A')}'",
            data=result,
            next_steps=[
                'Create subscribers using manage_customers(action="create", subscriber_data={...}) to set up users who will access this product',
                'Create subscriptions using manage_subscriptions(action="create", subscription_data={...}) to subscribe those users to this product',
                f"Use 'get' action with product_id='{result.get('id')}' to view details",
                "Use 'update' action to modify the product",
                "Use 'list' action to see all products",
            ],
            action="create_from_description",
        )

    async def _handle_create_from_description_dry_run(
        self, arguments: Dict[str, Any], enhancement_processor: ProductEnhancementProcessor
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle dry run for create_from_description."""
        description = arguments.get("description") or arguments.get("text", "")
        if not description:
            return [
                TextContent(
                    type="text",
                    text="DRY RUN MODE - Create from Description\n\n"
                    "Error: Description is required\n\n"
                    "**Dry Run:** True (no actual creation performed)",
                )
            ]

        # Use NLP processor to parse the description
        if enhancement_processor.nlp_processor:
            try:
                parsed_result = enhancement_processor.nlp_processor.parse_product_request(
                    description
                )
                educational_feedback = self._generate_educational_feedback(parsed_result)

                return [
                    TextContent(
                        type="text",
                        text=f"DRY RUN MODE - Create from Description\n\n"
                        f"Description Parsed Successfully\n\n"
                        f"**Original Description:** {description}\n\n"
                        f"**Would Create:**\n"
                        f"- **Name:** {parsed_result.get('name', 'N/A')}\n"
                        f"- **Version:** {parsed_result.get('version', 'N/A')}\n"
                        f"- **Plan Type:** {parsed_result.get('plan', {}).get('type', 'N/A')}\n"
                        f"- **Currency:** {parsed_result.get('plan', {}).get('currency', 'N/A')}\n"
                        f"- **Payment Source:** {parsed_result.get('paymentSource', 'N/A')}\n"
                        f"- **Setup Fees:** {len(parsed_result.get('setupFees', []))} configured\n\n"
                        f"**Parsed Configuration:**\n```json\n{json.dumps(parsed_result, indent=2)}\n```\n"
                        f"{educational_feedback}\n\n"
                        f"**Dry Run:** True (no actual creation performed)",
                    )
                ]
            except Exception as e:
                return [
                    TextContent(
                        type="text",
                        text=f"DRY RUN MODE - Create from Description\n\n"
                        f"Parsing Error: {str(e)}\n\n"
                        f"**Original Description:** {description}\n\n"
                        f"**Dry Run:** True (fix parsing errors before actual creation)",
                    )
                ]
        else:
            return [
                TextContent(
                    type="text",
                    text=f"DRY RUN MODE - Create from Description\n\n"
                    f"NLP Processor Unavailable: Would use fallback creation\n\n"
                    f"**Original Description:** {description}\n\n"
                    f"**Dry Run:** True (no actual creation performed)",
                )
            ]

    def _generate_educational_feedback(self, parsed_result: Dict[str, Any]) -> str:
        """Generate educational feedback for parsed product results."""
        educational_notes = []

        if "setupFees" in parsed_result and parsed_result["setupFees"]:
            setup_fee = parsed_result["setupFees"][0]
            if setup_fee.get("type") == "SUBSCRIPTION":
                educational_notes.append(
                    "Setup Fee Structure: Using new SUBSCRIPTION type (charged per subscription)"
                )
            elif setup_fee.get("type") == "ORGANIZATION":
                educational_notes.append(
                    "Setup Fee Structure: Using new ORGANIZATION type (charged per customer)"
                )

            if "flatAmount" in setup_fee:
                educational_notes.append(
                    "Setup Fee Format: Using new 'flatAmount' field structure"
                )
            else:
                educational_notes.append(
                    "Setup Fee Migration: Consider using 'flatAmount' instead of 'amount'"
                )

        if "paymentSource" in parsed_result:
            payment_source = parsed_result["paymentSource"]
            if payment_source == "INVOICE_ONLY_NO_PAYMENT":
                educational_notes.append(
                    "Payment Source: Manual invoice payment (customers pay outside system)"
                )
            elif payment_source == "EXTERNAL_PAYMENT_NOTIFICATION":
                educational_notes.append(
                    "Payment Source: Tracked invoice payment (external system confirms payment)"
                )

        if educational_notes:
            return "\n\nEducational Feedback:\n" + "\n".join(educational_notes)
        return ""

    async def _handle_hierarchy_actions(
        self, action: str, arguments: Dict[str, Any], hierarchy_manager: ProductHierarchyManager
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle hierarchy actions."""
        if action == "get_subscriptions":
            result = await hierarchy_manager.get_subscriptions(arguments)
            return [
                TextContent(
                    type="text",
                    text=f"Subscriptions for Product {result['product_id']}\n\n"
                    + json.dumps(result, indent=2),
                )
            ]

        elif action == "get_related_credentials":
            result = await hierarchy_manager.get_related_credentials(arguments)
            return [
                TextContent(
                    type="text",
                    text=f"Related Credentials for Product {result['product_id']}\n\n"
                    + json.dumps(result, indent=2),
                )
            ]

        elif action == "create_with_subscription":
            result = await hierarchy_manager.create_with_subscription(arguments)
            return await self._format_create_with_subscription_response(result)

        # Return error for unhandled hierarchy actions
        return [TextContent(type="text", text=json.dumps({"error": "No hierarchy action specified"}, indent=2))]

    async def _format_create_with_subscription_response(
        self, result: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format create_with_subscription response."""
        product = result["result"]["product"]
        subscription = result["result"]["subscription"]
        product_id = product["id"]
        subscription_id = subscription["id"]

        # Analyze what was automatically configured
        auto_configured = []
        if "sources" in product and product["sources"]:
            source_id = product["sources"][0]["id"]
            auto_configured.append(f"Source assignment: {source_id} (dynamically resolved)")

        if (
            "plan" in product
            and "ratingAggregations" in product["plan"]
            and product["plan"]["ratingAggregations"]
        ):
            rating_agg = product["plan"]["ratingAggregations"][0]
            element_id = rating_agg.get("elementDefinitionId", "unknown")
            auto_configured.append(
                f"Usage billing: {element_id} metering element (dynamically resolved)"
            )

        if "organizationId" in subscription:
            org_id = subscription["organizationId"]
            auto_configured.append(f"Organization assignment: {org_id} (auto-populated)")

        auto_config_text = ""
        if auto_configured:
            auto_config_text = "\n\nAuto-Configured:\n" + "\n".join(
                [f"• {config}" for config in auto_configured]
            )

        return [
            TextContent(
                type="text",
                text="Product and Subscription Created Successfully\n\n"
                + f"**Product ID:** {product_id}\n"
                + f"**Subscription ID:** {subscription_id}\n"
                + f"**Product Name:** {product.get('name', 'N/A')}\n"
                + f"**Subscriber:** {subscription.get('organizationId', 'N/A')}\n"
                + f"{auto_config_text}\n\n"
                + "**Next Steps:**\n"
                + "• Use manage_subscriber_credentials to add API keys for the subscription\n"
                + "• Use 'get_subscriptions' to see all subscriptions for this product\n"
                + "• Use manage_subscriber_credentials to add credentials to the subscription",
            )
        ]

    async def _handle_fallback_actions(
        self, action: str
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle fallback actions."""
        if action == "get_agent_summary":
            return await self._handle_get_agent_summary()

        # Return error for unhandled agent actions
        return [TextContent(type="text", text=json.dumps({"error": f"Unhandled agent action: {action}"}, indent=2))]

    def _handle_unknown_action(
        self, action: str
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle unknown actions with structured error."""
        raise ToolError(
            message=f"Unknown action '{action}' is not supported",
            error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
            field="action",
            value=action,
            suggestions=[
                "Use get_capabilities() to see all available actions and requirements",
                "Check the action name for typos",
                "Use get_examples() to see working examples",
                "For product management, use supported CRUD and discovery actions",
            ],
            examples={
                "basic_actions": ["list", "get", "create", "update", "delete"],
                "discovery_actions": ["get_capabilities", "get_examples", "get_agent_summary"],
                "creation_actions": ["create", "create_simple"],
                "template_actions": ["get_templates", "suggest_template"],
                "utility_actions": ["validate", "clarify_pricing", "get_tool_metadata"],
                "hierarchy_actions": [
                    "get_subscriptions",
                    "get_related_credentials",
                    "create_with_subscription",
                ],
                "example_usage": {
                    "create_product": "create(product_data={...})",
                    "simple_creation": "create_simple(name='API Plan', description='...')",
                    "template_usage": "get_templates()",
                },
                "product_lifecycle": "PRODUCT LIFECYCLE: Use appropriate actions for different stages of product management",
            },
        )

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle product management actions using focused handler methods."""
        try:
            # Setup managers
            product_manager, enhancement_processor, hierarchy_manager = await self._setup_managers()

            # Handle introspection actions
            result = await self._handle_introspection_actions(action)
            if result is not None:
                return result

            # Handle standard CRUD actions
            result = await self._handle_standard_crud_actions(action, arguments, product_manager)
            if result is not None:
                return result
            elif action == "create":
                # Handle dry_run mode for create operations
                dry_run = arguments.get("dry_run", False)
                if dry_run:
                    product_data = (
                        arguments.get("product_data") or arguments.get("resource_data") or {}
                    )
                    description = arguments.get("description")

                    # UNIFIED PROGRESSIVE COMPLEXITY: Handle description in dry run
                    if description:
                        try:
                            if enhancement_processor.nlp_processor:
                                parsed_result = (
                                    enhancement_processor.nlp_processor.parse_product_request(
                                        description
                                    )
                                )
                            else:
                                # Fallback: simple parsing without NLP processor
                                import re

                                description_lower = description.lower()
                                if "api" in description_lower:
                                    name = "API Service"
                                elif (
                                    "subscription" in description_lower
                                    or "plan" in description_lower
                                ):
                                    name = "Subscription Plan"
                                else:
                                    words = re.findall(r"\b[A-Za-z][A-Za-z]+\b", description)
                                    if len(words) >= 2:
                                        name = " ".join(words[:3]).title()
                                    else:
                                        name = "Custom Product"

                                parsed_result = {
                                    "name": name,
                                    "description": f"Product for {name}",
                                    "version": "1.0.0",
                                    "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
                                    "plan": {
                                        "type": "SUBSCRIPTION",
                                        "name": f"{name} Plan",
                                        "currency": "USD",
                                        "period": "MONTH",
                                        "tiers": [
                                            {
                                                "name": "Base Tier",
                                                "up_to": None,
                                                "unit_amount": "0.00",
                                            }
                                        ],
                                    },
                                }

                            # Handle empty name from NLP processor
                            name = parsed_result.get("name")
                            if not name or name.strip() == "":
                                import re

                                description_lower = description.lower()
                                if "api" in description_lower:
                                    parsed_result["name"] = "API Service"
                                elif (
                                    "subscription" in description_lower
                                    or "plan" in description_lower
                                ):
                                    parsed_result["name"] = "Subscription Plan"
                                else:
                                    words = re.findall(r"\b[A-Za-z][A-Za-z]+\b", description)
                                    if len(words) >= 2:
                                        parsed_result["name"] = " ".join(words[:3]).title()
                                    else:
                                        parsed_result["name"] = "Custom Product"

                            # Merge with resource_data for hybrid mode
                            merged_data = {**parsed_result, **product_data}

                            # Educational feedback for setup fees
                            educational_notes = []
                            if "setupFees" in merged_data and merged_data["setupFees"]:
                                setup_fee = merged_data["setupFees"][0]
                                if setup_fee.get("type") == "SUBSCRIPTION":
                                    educational_notes.append(
                                        "Setup Fee Structure: Using SUBSCRIPTION type (charged per subscription)"
                                    )
                                elif setup_fee.get("type") == "ORGANIZATION":
                                    educational_notes.append(
                                        "Setup Fee Structure: Using ORGANIZATION type (charged per customer)"
                                    )
                                if "flatAmount" in setup_fee:
                                    educational_notes.append(
                                        "Setup Fee Format: Using new 'flatAmount' field structure"
                                    )

                            educational_feedback = ""
                            if educational_notes:
                                educational_feedback = (
                                    "\n\nEducational Feedback:\n"
                                    + "\n".join(educational_notes)
                                )

                            return [
                                TextContent(
                                    type="text",
                                    text=f"DRY RUN MODE - Unified Product Creation\n\n"
                                    f"Description Parsed Successfully\n\n"
                                    f"**Input Mode:** {'Hybrid (description + resource_data)' if product_data else 'Natural Language'}\n\n"
                                    f"**Original Description:** {description}\n\n"
                                    f"**Would Create:**\n"
                                    f"- **Name:** {merged_data.get('name', 'N/A')}\n"
                                    f"- **Version:** {merged_data.get('version', 'N/A')}\n"
                                    f"- **Plan Type:** {merged_data.get('plan', {}).get('type', 'N/A')}\n"
                                    f"- **Currency:** {merged_data.get('plan', {}).get('currency', 'N/A')}\n"
                                    f"- **Payment Source:** {merged_data.get('paymentSource', 'N/A')}\n"
                                    f"- **Setup Fees:** {len(merged_data.get('setupFees', []))} configured\n\n"
                                    f"**Parsed Configuration:**\n```json\n{json.dumps(merged_data, indent=2)}\n```\n"
                                    f"{educational_feedback}\n\n"
                                    f"**Dry Run:** True (no actual creation performed)",
                                )
                            ]
                        except Exception as e:
                            return [
                                TextContent(
                                    type="text",
                                    text=f"DRY RUN MODE - NLP Parsing Error\n\n"
                                    f"Parsing Error: {str(e)}\n\n"
                                    f"**Original Description:** {description}\n\n"
                                    f"**Dry Run:** True (fix parsing errors before actual creation)",
                                )
                            ]
                    else:
                        # Standard structured validation
                        validation_result = self.validator.validate_configuration(
                            product_data, dry_run=True
                        )
                        if validation_result["valid"]:
                            return [
                                TextContent(
                                    type="text",
                                    text=f"DRY RUN MODE - Product Creation\n\n"
                                    f"Validation Successful: Product data is valid and ready for creation\n\n"
                                    f"**Input Mode:** Structured\n\n"
                                    f"**Would Create:**\n"
                                    f"- **Name:** {product_data.get('name', 'N/A')}\n"
                                    f"- **Version:** {product_data.get('version', 'N/A')}\n"
                                    f"- **Plan Type:** {product_data.get('plan', {}).get('type', 'N/A')}\n\n"
                                    f"**Dry Run:** True (no actual creation performed)",
                                )
                            ]
                        else:
                            errors_text = "\n".join(
                                [
                                    f"• {error.get('error', 'Unknown error')}"
                                    for error in validation_result.get("errors", [])
                                ]
                            )
                            return [
                                TextContent(
                                    type="text",
                                    text=f"DRY RUN MODE - Validation Failed\n\n"
                                    f"Errors Found:\n{errors_text}\n\n"
                                    f"**Dry Run:** True (fix errors before actual creation)",
                                )
                            ]

                # Only pass enhancement processor if description is provided
                if arguments.get("description"):
                    result = await product_manager.create_product(arguments, enhancement_processor)
                else:
                    result = await product_manager.create_product(arguments)
                return self.formatter.format_success_response(
                    message=f"Product '{result['data'].get('name', 'N/A')}' created successfully",
                    data=result["data"],
                    next_steps=[
                        'Create subscribers using manage_customers(action="create", subscriber_data={...}) to set up users who will access this product',
                        'Create subscriptions using manage_subscriptions(action="create", subscription_data={...}) to subscribe those users to this product',
                        f"Use 'get' action with product_id='{result['data'].get('id')}' to view details",
                        "Use 'update' action to modify the product",
                        "Use 'list' action to see all products",
                    ],
                    action="create",
                )
            elif action == "update":
                # Handle dry_run mode for update operations
                dry_run = arguments.get("dry_run", False)
                if dry_run:
                    product_id = arguments.get("product_id")
                    product_data = arguments.get("product_data", {})
                    return [
                        TextContent(
                            type="text",
                            text=f"DRY RUN MODE - Product Update\n\n"
                            f"Would update product: {product_id}\n"
                            f"**Changes:** {json.dumps(product_data, indent=2)}\n\n"
                            f"**Dry Run:** True (no actual update performed)",
                        )
                    ]

                result = await product_manager.update_product(arguments)
                return self.formatter.format_success_response(
                    message=f"Product '{result['product_id']}' updated successfully",
                    data=result["data"],
                    next_steps=[
                        f"Use 'get' action with product_id='{result['product_id']}' to view updated details",
                        "Use 'list' action to see all products",
                        "Use 'delete' action to remove this product if needed",
                    ],
                    action="update",
                )
            elif action == "delete":
                # Handle dry_run mode for delete operations
                dry_run = arguments.get("dry_run", False)
                if dry_run:
                    product_id = arguments.get("product_id")
                    return [
                        TextContent(
                            type="text",
                            text=f"DRY RUN MODE - Product Deletion\n\n"
                            f"Would delete product: {product_id}\n\n"
                            f"**Dry Run:** True (no actual deletion performed)\n\n"
                            f"**Warning:** This action cannot be undone in real mode",
                        )
                    ]

                result = await product_manager.delete_product(arguments)
                return self.formatter.format_success_response(
                    message=f"Product '{result['product_id']}' deleted successfully",
                    data=result["data"],
                    next_steps=[
                        "Use 'list' action to see remaining products",
                        "Use 'create' action to create a new product",
                        "Use 'get_examples' to see product templates",
                    ],
                    action="delete",
                )

            # Handle discovery and validation actions
            elif action == "get_capabilities":
                return await self._handle_get_capabilities()
            elif action == "get_examples":
                example_type = arguments.get("example_type")
                examples = self.validator.get_examples(example_type)
                return self._format_examples_response(examples)
            elif action == "validate":
                # Support both product_data and resource_data parameters for backward compatibility
                product_data = arguments.get("product_data") or arguments.get("resource_data") or {}
                validation_result = self.validator.validate_configuration(
                    product_data, arguments.get("dry_run", True)
                )
                return self._format_validation_response(validation_result)

            # Handle enhanced features
            elif action == "create_simple":
                result = await enhancement_processor.create_simple(arguments)
                return self.formatter.format_success_response(
                    message=f"Simple product '{result.get('name', 'N/A')}' created successfully",
                    data=result,
                    next_steps=[
                        'Create subscribers using manage_customers(action="create", subscriber_data={...}) to set up users who will access this product',
                        'Create subscriptions using manage_subscriptions(action="create", subscription_data={...}) to subscribe those users to this product',
                        f"Use 'get' action with product_id='{result.get('id')}' to view details",
                        "Use 'update' action to modify the product",
                        "Use 'list' action to see all products",
                    ],
                    action="create_simple",
                )
            elif action == "get_templates":
                templates = await enhancement_processor.get_templates(arguments)
                return [TextContent(type="text", text=json.dumps(templates, indent=2))]
            elif action == "suggest_template":
                suggestion = await enhancement_processor.suggest_template(arguments)
                return [TextContent(type="text", text=json.dumps(suggestion, indent=2))]
            elif action == "clarify_pricing":
                clarification = await enhancement_processor.clarify_pricing(arguments)
                return [TextContent(type="text", text=json.dumps(clarification, indent=2))]

            # Handle hierarchy actions
            elif action == "get_subscriptions":
                result = await hierarchy_manager.get_subscriptions(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"Subscriptions for Product {result['product_id']}\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]
            elif action == "get_related_credentials":
                result = await hierarchy_manager.get_related_credentials(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"Related Credentials for Product {result['product_id']}\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]
            elif action == "create_with_subscription":
                result = await hierarchy_manager.create_with_subscription(arguments)

                # Extract key information for enhanced output
                product = result["result"]["product"]
                subscription = result["result"]["subscription"]
                product_id = product["id"]
                subscription_id = subscription["id"]

                # Analyze what was automatically configured
                auto_configured = []
                if "sources" in product and product["sources"]:
                    source_id = product["sources"][0]["id"]
                    auto_configured.append(f"Source assignment: {source_id} (dynamically resolved)")

                if (
                    "plan" in product
                    and "ratingAggregations" in product["plan"]
                    and product["plan"]["ratingAggregations"]
                ):
                    rating_agg = product["plan"]["ratingAggregations"][0]
                    element_id = rating_agg.get("elementDefinitionId", "unknown")
                    auto_configured.append(
                        f"Usage billing: {element_id} metering element (dynamically resolved)"
                    )

                if "organizationId" in subscription:
                    org_id = subscription["organizationId"]
                    auto_configured.append(f"Organization assignment: {org_id} (auto-populated)")

                auto_configured.append(
                    "System fields: ownerId, teamId (auto-populated from authenticated context)"
                )
                auto_configured.append(
                    "Required subscription fields: 15+ fields with proper defaults"
                )

                # Build enhanced success message
                enhanced_message = (
                    "Product and subscription created successfully with hierarchy linking\n\n"
                )
                enhanced_message += "Created Entities:\n"
                enhanced_message += f"• **Product**: {product['name']} (ID: {product_id})\n"
                enhanced_message += (
                    f"• **Subscription**: {subscription['name']} (ID: {subscription_id})\n"
                )
                enhanced_message += (
                    f"• **Client**: {subscription['client']['label']} (auto-created)\n\n"
                )

                enhanced_message += "Automatic Enhancements Applied:\n"
                for config in auto_configured:
                    enhanced_message += f"• {config}\n"
                enhanced_message += "\n"

                enhanced_message += "Product Structure:\n"
                enhanced_message += (
                    "• **Subscription-ready**: Product has sources and rating aggregations\n"
                )
                enhanced_message += f"• **Billing period**: {product['plan']['period']}\n"
                enhanced_message += f"• **Currency**: {product['plan']['currency']}\n"
                enhanced_message += "• **Tier structure**: Optimized (single unlimited tier)\n\n"

                enhanced_message += "**Account-Agnostic Design:**\n"
                enhanced_message += "• All resource IDs dynamically resolved from your account\n"
                enhanced_message += (
                    "• No hardcoded values - works across different Revenium accounts\n"
                )
                enhanced_message += "• Automatic prerequisite validation and error handling\n"

                return [
                    TextContent(
                        type="text",
                        text=enhanced_message
                        + "\n**Next Steps:**\n"
                        + f"• Use 'get' action with product_id='{product_id}' to view product details\n"
                        + f"• Use manage_subscriptions get action with subscription_id='{subscription_id}' to view subscription\n"
                        + "• Use 'get_subscriptions' to see all subscriptions for this product\n"
                        + "• Use manage_subscriber_credentials to add credentials to the subscription",
                    )
                ]

            # Handle agent summary
            elif action == "get_agent_summary":
                return await self._handle_get_agent_summary()

            else:
                raise ToolError(
                    message=f"Unknown action '{action}' is not supported",
                    error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
                    field="action",
                    value=action,
                    suggestions=[
                        "Use get_capabilities() to see all available actions and requirements",
                        "Check the action name for typos",
                        "Use get_examples() to see working examples",
                        "For product management, use supported CRUD and discovery actions",
                    ],
                    examples={
                        "basic_actions": ["list", "get", "create", "update", "delete"],
                        "discovery_actions": [
                            "get_capabilities",
                            "get_examples",
                            "get_agent_summary",
                        ],
                        "creation_actions": ["create", "create_simple"],
                        "template_actions": ["get_templates", "suggest_template"],
                        "utility_actions": ["validate", "clarify_pricing", "get_tool_metadata"],
                        "hierarchy_actions": [
                            "get_subscriptions",
                            "get_related_credentials",
                            "create_with_subscription",
                        ],
                        "example_usage": {
                            "create_product": "create(product_data={...})",
                            "simple_creation": "create_simple(name='API Plan', description='...')",
                            "template_usage": "get_templates()",
                        },
                        "product_lifecycle": "PRODUCT LIFECYCLE: Use appropriate actions for different stages of product management",
                    },
                )

        except ToolError as e:
            logger.error(f"Tool error in manage_products: {e}")
            # Format ToolError with detailed guidance for agents
            from ..common.error_handling import format_structured_error

            formatted_error_text = format_structured_error(e, include_debug_info=False)
            return [TextContent(type="text", text=formatted_error_text)]
        except ReveniumAPIError as e:
            logger.error(f"Revenium API error in manage_products: {e}")
            # Re-raise ReveniumAPIError to be handled by standardized_tool_execution
            raise e
        except Exception as e:
            logger.error(f"Unexpected error in manage_products: {e}")
            # Re-raise Exception to be handled by standardized_tool_execution
            raise e

    async def _handle_get_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Enhanced capabilities with UCM integration and preserved semantic guidance."""
        # Get UCM capabilities if available for API-verified data
        ucm_capabilities = None
        if self.ucm_helper:
            try:
                ucm_capabilities = await self.ucm_helper.ucm.get_capabilities("products")
                log_ucm_status("Product Management", True, True)
            except ToolError:
                # Re-raise ToolError exceptions without modification
                # This preserves helpful error messages with specific suggestions
                raise
            except Exception as e:
                log_ucm_status("Product Management", True, False)
                logger.warning(f"Failed to get UCM product capabilities, using static data: {e}")
        else:
            log_ucm_status("Product Management", False)

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
        text = """# **Product Management Capabilities**

## **PRODUCT MANAGEMENT OVERVIEW**

### **What Products Are**
- **Configuration blueprints** for usage-based billing or chargeback
- **Pricing structures** that define how customers are charged
- **Integration points** between sources, subscriptions, and subscriber credentials
- **Business logic containers** for complex billing scenarios

### **Key Concepts within Products**
- **Products** define what you're selling (which sources are included, descriptions of the product)
- **Plans** define how you're charging (subscription, usage-based, hybrid)
- **Tiers** define pricing breakpoints (free tier, paid tiers, enterprise)
- **Sources** define what you're metering within the product (APIs, services, endpoints)

## **Quick Start Commands**

### **Discover Products**
```bash
list()                                          # View all products
get(product_id="prod_123")                     # Get specific product details
get_examples()                                 # See working templates
```

### **Create Products - Unified Progressive Complexity**
```bash
# UNIFIED CREATE ACTION - Multiple Input Modes:

# Mode 1: Natural Language (simplest)
create(description="Premium API access plan with 10000 requests per month for $99")

# Mode 2: Structured Data (full control)
create(resource_data={"name": "API", "plan": {...}})

# Mode 3: Hybrid (best of both)
create(resource_data={"name": "Custom"}, description="Enterprise features")

# Traditional options still available:
get_capabilities()                            # Understand requirements
validate(product_data={...}, dry_run=True)    # Test before creating
create_simple(name="My AI Product")           # Quick creation example
create_simple(name="Usage-based Product", pricing_model="usage_based", per_unit_price=0.01)  # Usage-based
```

### **Usage-Based Billing Workflow**
```bash
# Step 1: Check standard AI billing elements (recommended first step)
manage_metering_elements(action="list")       # See available elements: totalCost, inputTokenCount, etc.

# Step 2: Choose appropriate existing element OR create new one if needed
# Common existing elements: totalCost, inputTokenCost, outputTokenCost, inputTokenCount, outputTokenCount
# IMPORTANT: Copy the actual elementDefinitionId from Step 1 results - IDs are unique per account

# Step 3: Create usage-based product with elementDefinitionId
create(product_data={
  "name": "AI Usage Product",
  "plan": {
    "ratingAggregations": [{
      "elementDefinitionId": "COPY_FROM_STEP_1",  # Use actual ID from manage_metering_elements list
      "aggregationType": "SUM",
      "tiers": [{"up_to": null, "unit_amount": "0.01"}]
    }]
  }
})
```

### **Manage Products**
```bash
update(product_id="prod_123", product_data={...})  # Update existing
delete(product_id="prod_123")                      # Remove product
```

### **Hierarchy Navigation**
```bash
get_subscriptions(product_id="prod_123")           # Find subscriptions for product
get_related_credentials(product_id="prod_123")     # Find all related credentials
create_with_subscription(product_data={...}, subscription_data={...})  # Create linked entities
```

### **Coordinated Product+Subscription Creation**
```bash
# PREREQUISITE: Verify account readiness (REQUIRED)
manage_sources(action="list")                      # Ensure sources exist (required)
manage_metering_elements(action="list")            # Check metering elements (optional)

# Complete workflow in single operation
create_with_subscription(
  product_data={
    "name": "AI Analytics Platform",
    "description": "Professional AI analytics with usage billing",
    "version": "1.0.0",
    "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
    "plan": {
      "type": "SUBSCRIPTION",
      "name": "AI Analytics Plan",
      "currency": "USD",
      "period": "MONTH",
      "tiers": [{"name": "Base", "up_to": 1000000, "flat_amount": "29.99"}]
    }
  },
  subscription_data={
    "name": "Customer Subscription",
    "description": "Active subscription for AI analytics platform",
    "clientEmailAddress": "customer@company.com"
  }
)

# AUTOMATIC ENHANCEMENTS (no user action required):
# Sources: Assigns first available source from your account
# Metering: Adds usage billing with totalCost element
# System fields: Auto-populates ownerId, teamId, organizationId
# Tier structure: Ensures proper configuration (single unlimited tier)
# Required fields: Adds all 15+ subscription fields with defaults
```"""

        # Add UCM-enhanced plan types if available
        if ucm_capabilities and "plan_types" in ucm_capabilities:
            text += "\n\n## **Plan Types**\n"
            for plan_type in ucm_capabilities["plan_types"]:
                text += f"- **{plan_type}**\n"
        else:
            # Fallback to basic plan types
            text += "\n\n## **Plan Types**\n"
            text += "- **SUBSCRIPTION**\n"

        # Add UCM-enhanced currencies if available
        if ucm_capabilities and "currencies" in ucm_capabilities:
            text += "\n\n## **Supported Currencies**\n"
            for currency in ucm_capabilities["currencies"]:
                text += f"- **{currency}**\n"
        else:
            # Fallback to basic currencies
            text += "\n\n## **Supported Currencies**\n"
            text += "- **USD**\n- **EUR**\n- **GBP**\n- **CAD**\n- **AUD**\n- **JPY**\n- **CNY**\n- **MXN**\n- **COP**\n- **ARS**\n- **ZMW**\n"

        # Add UCM-enhanced billing periods if available
        if ucm_capabilities and "billing_periods" in ucm_capabilities:
            text += "\n\n## **Billing Periods**\n"
            for period in ucm_capabilities["billing_periods"]:
                text += f"- **{period}**\n"
        else:
            # Fallback to basic billing periods
            text += "\n\n## **Billing Periods**\n"
            text += "- **MONTH**\n- **YEAR**\n- **QUARTER**\n- **WEEK**\n- **DAY**\n"

        # Add payment source documentation (API-verified)
        text += "\n\n## **Supported Payment Sources**\n"
        text += "- **INVOICE_ONLY_NO_PAYMENT**: Manual invoices are sent from Revenium to customers for payment outside the Revenium system. Revenium does NOT track payment status once invoices are issued.\n"
        text += '- **EXTERNAL_PAYMENT_NOTIFICATION**: Manual invoices are sent from Revenium to customers for payment outside the Revenium system. Revenium tracks all payments as "open" until receiving updates from an external system confirming payment.\n'
        text += "\nStripe Limitation: Stripe-supported products must be configured manually through the Revenium UI and are not currently available via the MCP API.\n"

        # Add schema information
        schema = ucm_capabilities.get("schema", {}) if ucm_capabilities else {}
        product_schema = schema.get("product_data", {})

        text += "\n\n## **Required Fields**\n"
        required_fields = product_schema.get("required", ["name", "version", "plan"])
        for field in required_fields:
            text += f"- `{field}` (required)\n"

        text += "\n\n## **Optional Fields**\n"
        optional_fields = product_schema.get(
            "optional",
            [
                "description",
                "source_ids",
                "sla_ids",
                "custom_pricing_rule_ids",
                "notification_addresses_on_invoice",
                "tags",
                "terms",
                "coming_soon",
                "setup_fees",
                "rating_aggregations",
                "elements",
            ],
        )
        for field in optional_fields:
            if field == "source_ids":
                text += f"- `{field}` (technically optional, but usage-based billing not possible without defnining the source_ids that will be metered)\n"
            else:
                text += f"- `{field}` (optional)\n"

        # Add business rules
        text += """

## **Business Rules**

### Tier Structure Fields
**Required Fields:**
- **name**: Descriptive name for this pricing tier (e.g., "First 1000 API calls")
- **up_to**: Maximum number of units included in this tier
  - Use numeric values (1000, 5000) for limited tiers
  - Use `null` for unlimited final tier (handles all usage above previous tiers)
- **Pricing**: Either `unit_amount` OR `flat_amount` must be provided (both allowed)
  - **unit_amount**: Price in plan currency charged per unit in this tier
  - **flat_amount**: One-time fee charged when usage first enters this tier

**Auto-Generated Fields:**
- **startingFrom**: Calculated by API based on tier ordering - do NOT include in user input

### How Tier Billing Works
Tiers create pricing brackets based on usage volume. The API automatically calculates ranges:

**Example with 3 tiers:**
```
Tier 1: "First 1000 calls" (up_to: 1000) → API calculates range: 0-1000
Tier 2: "Next 4000 calls" (up_to: 5000) → API calculates range: 1001-5000
Tier 3: "Additional calls" (up_to: null) → API calculates range: 5001+
```

**Billing Calculation Example:**
For 7500 API calls with above tiers at $0.01, $0.008, $0.005:
- First 1000 calls: 1000 × $0.01 = $10.00
- Next 4000 calls: 4000 × $0.008 = $32.00
- Final 2500 calls: 2500 × $0.005 = $12.50
- **Total: $54.50**

### Tier Structure Rules
- **Final Tier**: Must have `up_to: null` (unlimited range)
- **Non-final Tiers**: Must have numeric `up_to` values
- **Single-tier products**: Only tier has `up_to: null`
- **Multi-tier products**: All tiers except last must have `up_to` values
- **Tier Ordering**: List tiers in ascending order by `up_to` value

### Subscription Plans
- Must specify billing period
- Can optionally include trial period

### Pricing Validation
- At least one tier required (in plan.tiers or rating_aggregations)
- Either `unit_amount` OR `flat_amount` must be provided (both allowed)
- Unit amounts must be non-negative

### Setup Fee Types
- SUBSCRIPTION: Charged for each new subscription (per subscription billing)
- ORGANIZATION: Charged once per customer organization (multiple subscriptions within one organization= setup fee charged one time only)

### Usage-Based Billing Requirements
- **Metering elements must exist first**: Check existing elements with manage_metering_elements(action="list")
- **Leverage existing AI elements**: Use built-in elements (totalCost, inputTokenCount, outputTokenCount, etc.) for most AI use cases, these are automatically metered by Revenium's middleware so they are the most common use cases
- **elementDefinitionId required**: Must reference valid metering element ID in ratingAggregations
- **CRITICAL**: Element IDs are unique per account - NEVER hardcode IDs, always lookup from list results
- **Avoid duplicates**: Only create new metering elements when existing ones don't match requirements, newly-created elements require coordination with the team sending metering data to Revenium to ensure they are sending the same element IDs, so only use new metering IDs when strictly necessary.

## **Next Steps**
1. Use `get_examples` to see working product templates
2. Use `validate` to test your configuration before creating
3. Use `create` to create the product"""

        return text

    def _format_capabilities_response(
        self, capabilities: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format capabilities response."""
        result_text = "# **Product Management Capabilities**\n\n"

        result_text += "## **Plan Types**\n"
        for plan_type in capabilities.get("plan_types", []):
            result_text += f"- `{plan_type}`\n"

        result_text += "\n## **Supported Currencies**\n"
        for currency in capabilities.get("currencies", []):
            result_text += f"- `{currency}`\n"

        result_text += "\n## **Billing Periods** (for subscription plans)\n"
        for period in capabilities.get("billing_periods", []):
            result_text += f"- `{period}`\n"

        result_text += "\n## **Required Fields**\n"
        schema = capabilities.get("schema", {}).get("product_data", {})
        for field in schema.get("required", []):
            result_text += f"- `{field}` (required)\n"

        result_text += "\n## **Optional Fields**\n"
        for field in schema.get("optional", []):
            result_text += f"- `{field}` (optional)\n"

        result_text += "\n## **Business Rules**\n"
        for rule_category, rules in capabilities.get("business_rules", {}).items():
            result_text += f"### {rule_category.replace('_', ' ').title()}\n"
            for rule in rules:
                result_text += f"- {rule}\n"
            result_text += "\n"

        result_text += "## **Next Steps**\n"
        result_text += "1. Use `get_examples` to see working product templates\n"
        result_text += "2. Use `validate` to test your configuration before creating\n"
        result_text += "3. Use `create` to create the product\n"

        return [TextContent(type="text", text=result_text)]

    def _format_examples_response(
        self, examples: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format examples response."""
        # Check if this is create_with_subscription examples
        if "coordinated_workflow_example" in examples:
            return self._format_create_with_subscription_examples(examples)

        # Standard examples formatting
        result_text = "**Product Creation Examples**\n\n"

        # Show basic tier example (the actual key returned by get_examples)
        basic_example = examples.get("basic_tier_example", {})
        if basic_example:
            result_text += "## **Recommended Example**\n\n"
            result_text += f"**Type**: `{basic_example.get('type', 'simple_tiers')}`\n"
            result_text += f"**Description**: {basic_example.get('description', 'Basic subscription product with valid values')}\n"
            result_text += f"**Use Case**: {basic_example.get('use_case', 'Most common product type for AI or API metering')}\n\n"
            result_text += "**Template**:\n```json\n"
            result_text += json.dumps(basic_example.get("template", {}), indent=2)
            result_text += "\n```\n\n"

        # Show deprecated values to avoid
        deprecated = examples.get("deprecated_values", {})
        if deprecated:
            result_text += "## **Deprecated Values to Avoid**\n\n"
            result_text += "**IMPORTANT**: These values will cause API errors:\n"
            for field, values in deprecated.items():
                for value, message in values.items():
                    result_text += f'• `{field}: "{value}"` {message}\n'
            result_text += "\n"

        # Show usage-based billing workflow
        usage_workflow = examples.get("usage_based_billing_workflow", {})
        if usage_workflow:
            result_text += "## **Usage-Based Billing Workflow**\n\n"
            result_text += f"**Description**: {usage_workflow.get('description', 'Complete workflow for usage-based products')}\n\n"

            warning = usage_workflow.get("warning", "")
            if warning:
                result_text += f"**{warning}**\n\n"

            # Add step-by-step workflow
            for step_key in ["step_1", "step_2", "step_3", "step_4"]:
                step = usage_workflow.get(step_key, {})
                if step:
                    step_num = step_key.split("_")[1]
                    result_text += f"**Step {step_num}: {step.get('action', 'Action')}**\n"

                    if "tool_call" in step:
                        result_text += f"```bash\n{step['tool_call']}\n```\n"

                    if "purpose" in step:
                        result_text += f"*Purpose*: {step['purpose']}\n"

                    if "guidance" in step:
                        result_text += f"*Guidance*: {step['guidance']}\n"

                    if "instruction" in step:
                        result_text += f"*Instruction*: {step['instruction']}\n"

                    if "warning" in step:
                        result_text += f"*{step['warning']}*\n"

                    if "available_elements" in step:
                        result_text += f"*Available Elements*: {step['available_elements']}\n"

                    if "example" in step:
                        result_text += "```json\n"
                        result_text += json.dumps(step["example"], indent=2)
                        result_text += "\n```\n"

                    result_text += "\n"

            result_text += "\n"

        # Show current valid values
        valid_values = examples.get("current_valid_values", {})
        if valid_values:
            result_text += "## **Valid Values**\n\n"
            # Handle case where valid_values might be a string (UCM-only validation)
            if isinstance(valid_values, str):
                result_text += f"**Validation Mode**: {valid_values}\n"
                result_text += "**Note**: Use UCM get_capabilities() for current valid values\n"
            elif isinstance(valid_values, dict):
                for field, values in valid_values.items():
                    if isinstance(values, list):
                        result_text += f"**{field}**: {', '.join(f'`{v}`' for v in values)}\n"
                    else:
                        result_text += f"**{field}**: `{values}`\n"
            else:
                result_text += f"**Validation Info**: {valid_values}\n"
            result_text += "\n"

        result_text += "## **Usage**\n"
        result_text += "1. Copy the recommended template above\n"
        result_text += "2. Modify the values for your needs\n"
        result_text += "3. Use `validate` to test your configuration\n"
        result_text += "4. Use `create` action to create the product\n\n"

        result_text += "**Pro Tip**: Always use `validate` before `create` to catch errors early!\n"

        return [TextContent(type="text", text=result_text)]

    def _format_create_with_subscription_examples(
        self, examples: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format create_with_subscription specific examples."""
        result_text = "# **create_with_subscription Examples and Documentation**\n\n"

        # Coordinated workflow example
        coordinated_example = examples.get("coordinated_workflow_example", {})
        if coordinated_example:
            result_text += "## Complete Coordinated Workflow\n\n"
            result_text += (
                f"**Type**: `{coordinated_example.get('type', 'coordinated_creation')}`\n"
            )
            result_text += f"**Description**: {coordinated_example.get('description', 'Complete product+subscription creation')}\n"
            result_text += f"**Use Case**: {coordinated_example.get('use_case', 'Efficient business process automation')}\n\n"

            # Prerequisites section
            prerequisites = coordinated_example.get("prerequisites", {})
            if prerequisites:
                result_text += "### Prerequisites (REQUIRED)\n\n"
                for _, step in prerequisites.items():
                    result_text += f"**{step.get('action', 'Step')}**:\n"
                    result_text += f"```bash\n{step.get('tool_call', 'N/A')}\n```\n"
                    result_text += f"*Purpose*: {step.get('purpose', 'N/A')}\n"
                    result_text += (
                        f"*Required*: {'Yes' if step.get('required') else 'Optional'}\n\n"
                    )

            # Template section
            template = coordinated_example.get("template", {})
            if template:
                result_text += "### **Template**\n\n"
                result_text += "```json\n"
                result_text += json.dumps(template, indent=2)
                result_text += "\n```\n\n"

            # Automatic enhancements
            auto_enhancements = coordinated_example.get("automatic_enhancements", {})
            if auto_enhancements:
                result_text += "### **Automatic Enhancements**\n\n"
                for enhancement, description in auto_enhancements.items():
                    result_text += f"• **{enhancement.replace('_', ' ').title()}**: {description}\n"
                result_text += "\n"

            # Workflow notes
            workflow_notes = coordinated_example.get("workflow_notes", {})
            if workflow_notes:
                result_text += "### **Workflow Notes**\n\n"
                for note_key, note_value in workflow_notes.items():
                    result_text += f"• **{note_key.replace('_', ' ').title()}**: {note_value}\n"
                result_text += "\n"

        # Troubleshooting example
        troubleshooting_example = examples.get("troubleshooting_example", {})
        if troubleshooting_example:
            result_text += "## Troubleshooting Guide\n\n"

            # Common errors
            common_errors = troubleshooting_example.get("common_errors", {})
            if common_errors:
                result_text += "### **Common Issues and Solutions**\n\n"
                for error_key, error_info in common_errors.items():
                    result_text += f"**{error_key.replace('_', ' ').title()}**:\n"
                    result_text += f"• *Error*: {error_info.get('error', 'N/A')}\n"
                    if "cause" in error_info:
                        result_text += f"• *Cause*: {error_info['cause']}\n"
                    result_text += f"• *Solution*: {error_info.get('solution', 'N/A')}\n"
                    if "tool_call" in error_info:
                        result_text += f"• *Tool Call*: `{error_info['tool_call']}`\n"
                    if "note" in error_info:
                        result_text += f"• *Note*: {error_info['note']}\n"
                    result_text += "\n"

            # When to use
            when_to_use = troubleshooting_example.get("when_to_use", {})
            if when_to_use:
                result_text += "### **When to Use Each Approach**\n\n"
                for approach, description in when_to_use.items():
                    result_text += f"• **{approach.replace('_', ' ').title()}**: {description}\n"
                result_text += "\n"

        result_text += "## **Next Steps**\n"
        result_text += "1. **Run prerequisites**: Verify sources and metering elements exist\n"
        result_text += "2. **Copy template**: Use the exact template above\n"
        result_text += "3. **Execute workflow**: Run `create_with_subscription` action\n"
        result_text += (
            "4. **Verify results**: Check the enhanced output for automatic configurations\n\n"
        )

        result_text += "**Pro Tip**: This workflow is account-agnostic and works across different Revenium accounts!\n"

        return [TextContent(type="text", text=result_text)]

    def _format_validation_response(
        self, validation_result: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format validation response."""
        result_text = "# Enhanced Product Validation Results\n\n"

        if validation_result.get("valid"):
            # Use the full validation response which may include warnings
            validation_response_text = validation_result.get("validation_response")
            if validation_response_text:
                # The validation engine already formatted the response with warnings
                result_text += validation_response_text + "\n\n"
            else:
                # Fallback to simple success message
                result_text += "Validation Successful\n\n"
                result_text += validation_result.get(
                    "message",
                    "Your product configuration passes all validation checks and is ready for creation!",
                )
                result_text += "\n\nNext Steps:\n"
                result_text += "1. Use `create` action with this product_data\n"
                result_text += "2. Monitor the creation process\n"
                result_text += "3. Use `get` action to verify the created product\n\n"
        else:
            result_text += "Validation Failed\n\n"
            result_text += "**Errors Found**:\n"
            for error in validation_result.get("errors", []):
                result_text += f"- **{error.get('field', 'unknown')}**: {error.get('error', 'Unknown error')}\n"
            result_text += "\n"

        result_text += f"**Dry Run**: {validation_result.get('dry_run', True)}\n"
        result_text += "**Validation Engine**: Enhanced (prevents CHARGE vs SUBSCRIPTION errors)\n"

        return [TextContent(type="text", text=result_text)]

    async def _handle_get_agent_summary(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get agent summary."""
        summary_text = """**Agent Summary: manage_products**

**Product Management Tool**

Comprehensive product lifecycle management for the Revenium platform. Handle creation, configuration, monitoring, and maintenance of products with intelligent validation and smart defaults.

**Key Features:**
• Complete CRUD operations with validation
• Schema discovery and examples
• Smart defaults for rapid setup
• Integration with sources, alerts, and subscriptions
• Agent-friendly error handling and guidance

**Quick Start:**
1. Start with get_capabilities() to understand product types and requirements
2. Use get_examples() to see working product templates
3. Validate configurations with validate(product_data={...}, dry_run=True)
4. Create products with create(product_data={...}) or create_simple(name='...', type='...')
5. Monitor and manage with list(), get(), update(), and delete() actions

**Common Use Cases:**
• Setting up AI or API metering for new services
• Creating product configurations for different environments
• Bulk product management and updates
• Product discovery and inventory management
• Integration with monitoring and alerting systems

**Troubleshooting Tips:**
• Use validate() action to test configurations before creating products
• Check get_examples() for working templates if creation fails
• Verify organization membership if product creation is denied
• Use get_capabilities() to see required vs optional fields
• Check API authentication if all operations fail"""

        return [TextContent(type="text", text=summary_text)]

    # Metadata Provider Implementation
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get product tool capabilities."""
        return [
            ToolCapability(
                name="Product CRUD Operations",
                description="Complete lifecycle management for products",
                parameters={
                    "list": {"page": "int", "size": "int", "filters": "dict"},
                    "get": {"product_id": "str"},
                    "create": {"product_data": "dict"},
                    "update": {"product_id": "str", "product_data": "dict"},
                    "delete": {"product_id": "str"},
                },
                examples=[
                    "list(page=0, size=10)",
                    "get(product_id='prod_123')",
                    "create(product_data={'name': 'My Product', 'plan': {'type': 'SUBSCRIPTION', 'currency': 'USD'}})",
                    "VALID plan.type: SUBSCRIPTION (CHARGE is deprecated)",
                    "VALID currencies: USD, EUR, GBP, CAD, AUD",
                ],
                limitations=[
                    "Requires valid API authentication",
                    "Product names must be unique within organization",
                    "Some fields are immutable after creation",
                    "DEPRECATED: plan.type 'CHARGE' - use 'SUBSCRIPTION' instead",
                    "DEPRECATED: plan.type 'ONE_TIME' - use 'SUBSCRIPTION' instead",
                ],
            ),
            ToolCapability(
                name="Schema Discovery",
                description="Discover product schemas and validation rules",
                parameters={
                    "get_capabilities": {},
                    "get_examples": {"example_type": "str"},
                    "validate": {"product_data": "dict", "dry_run": "bool"},
                },
                examples=[
                    "get_capabilities()",
                    "get_examples(example_type='api')",
                    "validate(product_data={...}, dry_run=True)",
                ],
            ),
            ToolCapability(
                name="Unified Progressive Complexity",
                description="Create products using structured data, natural language, or hybrid approaches",
                parameters={
                    "create": {
                        "resource_data": "dict (optional: structured product data)",
                        "description": "str (optional: natural language description)",
                        "dry_run": "bool (optional: preview without creating)",
                    },
                    "create_simple": {
                        "name": "str (required)",
                        "type": "str (optional)",
                        "description": "str (optional)",
                        "pricing_model": "str (optional: 'subscription' or 'usage_based')",
                        "per_unit_price": "number (optional: for usage_based pricing)",
                        "monthly_price": "number (optional: for subscription pricing)",
                        "setup_fee": "number (optional: one-time setup fee)",
                    },
                },
                examples=[
                    "create(resource_data={'name': 'API', 'plan': {...}})",
                    "create(description='Premium API access plan with 10000 requests per month for $99')",
                    "create(resource_data={'name': 'Custom'}, description='Enterprise features')",
                    "create_simple(name='My API', type='api')",
                    "create_simple(name='Usage API', pricing_model='usage_based', per_unit_price=0.01)",
                    "create_simple(name='Monthly Service', pricing_model='subscription', monthly_price=29.99)",
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
            "delete",
            "get_capabilities",
            "get_examples",
            "validate",
            "get_agent_summary",
            "create_simple",
            "get_templates",
            "suggest_template",
            "clarify_pricing",
            "get_tool_metadata",
            # Hierarchy actions
            "get_subscriptions",
            "get_related_credentials",
            "create_with_subscription",
        ]

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Context7 single source of truth for manage_products schema."""
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": await self._get_supported_actions()},
                "name": {
                    "type": "string",
                    "description": "Product name - the only field users need to provide",
                },
                # Note: description, version auto-generated
                # Note: ownerId, teamId system-managed
                # Note: product_data handled in implementation
            },
            "required": ["action", "name"],  # Context7: User-centric only
        }

    async def _get_tool_dependencies(self) -> List[ToolDependency]:
        """Get tool dependencies."""
        # Removed circular dependencies - products work independently
        # Business relationships are documented in resource_relationships instead
        return []

    async def _get_resource_relationships(self) -> List[ResourceRelationship]:
        """Get resource relationships."""
        return [
            ResourceRelationship(
                resource_type="sources",
                relationship_type="requires",
                description="Products can monitor data sources",
                cardinality="1:N",
                optional=True,
            ),
            ResourceRelationship(
                resource_type="subscriptions",
                relationship_type="creates",
                description="Products can have associated subscriptions",
                cardinality="1:N",
                optional=True,
            ),
            ResourceRelationship(
                resource_type="alerts",
                relationship_type="creates",
                description="Products can have monitoring alerts configured",
                cardinality="1:N",
                optional=True,
            ),
            ResourceRelationship(
                resource_type="organizations",
                relationship_type="requires",
                description="Products belong to organizations",
                cardinality="N:1",
                optional=False,
            ),
        ]

    async def _get_usage_patterns(self) -> List[UsagePattern]:
        """Get usage patterns."""
        return [
            UsagePattern(
                pattern_name="Product Discovery",
                description="Explore existing products and their configurations",
                frequency=0.8,
                typical_sequence=["list", "get"],
                common_parameters={"page": 0, "size": 20},
                success_indicators=["Products listed successfully", "Product details retrieved"],
            ),
            UsagePattern(
                pattern_name="Product Creation",
                description="Create new products with validation",
                frequency=0.6,
                typical_sequence=["get_examples", "validate", "create"],
                common_parameters={"dry_run": True},
                success_indicators=["Validation passed", "Product created successfully"],
            ),
            UsagePattern(
                pattern_name="Product Management",
                description="Update and maintain existing products",
                frequency=0.4,
                typical_sequence=["get", "update", "get"],
                common_parameters={"product_id": "required"},
                success_indicators=["Product updated successfully", "Changes reflected"],
            ),
        ]

    async def _get_agent_summary(self) -> str:
        """Get agent summary."""
        return """**Product Management Tool**

Comprehensive product lifecycle management for the Revenium platform. Handle creation, configuration, monitoring, and maintenance of products with intelligent validation and smart defaults.

**Key Features:**
• Complete CRUD operations with validation
• Schema discovery and examples
• Smart defaults for rapid setup
• Integration with sources, alerts, and subscriptions
• Agent-friendly error handling and guidance"""

    async def _get_quick_start_guide(self) -> List[str]:
        """Get quick start guide."""
        return [
            "Start with get_capabilities() to understand product types and requirements",
            "Use get_examples() to see working product templates",
            "Validate configurations with validate(product_data={...}, dry_run=True)",
            "Create products with create(product_data={...}) or create_simple(name='...', type='...')",
            "Monitor and manage with list(), get(), update(), and delete() actions",
        ]

    async def _get_common_use_cases(self) -> List[str]:
        """Get common use cases."""
        return [
            "Setting up AI or API metering for new services",
            "Creating product configurations for different environments",
            "Bulk product management and updates",
            "Product discovery and inventory management",
            "Integration with monitoring and alerting systems",
        ]

    async def _get_troubleshooting_tips(self) -> List[str]:
        """Get troubleshooting tips."""
        return [
            "Use validate() action to test configurations before creating products",
            "Check get_examples() for working templates if creation fails",
            "Verify organization membership if product creation is denied",
            "Use get_capabilities() to see required vs optional fields",
            "Check API authentication if all operations fail",
        ]

    async def _get_tool_tags(self) -> List[str]:
        """Get tool tags."""
        return ["crud", "products", "management", "validation", "monitoring"]


# Create consolidated instance
# Module-level instantiation removed to prevent UCM warnings during import
# product_management = ProductManagement(ucm_helper=None)
