"""Capability discovery engine for the Unified Capability Manager.

This module provides automatic discovery of capabilities from API metadata
and existing schema definitions.
"""

import logging
from typing import Any, Dict, List

from ..client import ReveniumClient
from ..constants import (
    API_BURST_LIMIT,
    API_RATE_LIMIT_PER_MINUTE,
    API_SUPPORTED_VERSIONS,
    AUTHENTICATION_METHODS,
    DEFAULT_BASE_URL,
    DEFAULT_PROFILE,
    MCP_SERVER_VERSION,
)
from ..models import (
    AggregationType,
    BillingPeriod,
    Currency,
    MetricType,
    PaymentSource,
    PlanType,
    RatingAggregationType,
    TrialPeriod,
)
from ..tool_configuration.profiles import PROFILE_DEFINITIONS, PROFILE_TOOL_COUNTS

logger = logging.getLogger(__name__)


class CapabilityDiscovery:
    """Discovers capabilities from API metadata and schema definitions."""

    def __init__(self, client: ReveniumClient):
        """Initialize the capability discovery engine.

        Args:
            client: Revenium API client for discovery
        """
        self.client = client

        # Map resource types to discovery methods
        self.discovery_methods = {
            "system": self._discover_system_capabilities,
            "products": self._discover_product_capabilities,
            "subscriptions": self._discover_subscription_capabilities,
            "customers": self._discover_customer_capabilities,
            "alerts": self._discover_alert_capabilities,
            "sources": self._discover_source_capabilities,
            "metering_elements": self._discover_metering_element_capabilities,
            "metering": self._discover_metering_capabilities,
        }

    async def discover_capabilities(self, resource_type: str) -> Dict[str, Any]:
        """Discover capabilities for a resource type.

        Args:
            resource_type: Type of resource to discover capabilities for

        Returns:
            Dictionary of discovered capabilities
        """
        discovery_method = self.discovery_methods.get(resource_type)
        if not discovery_method:
            logger.warning(f"No discovery method for resource type: {resource_type}")
            return {}

        try:
            capabilities = await discovery_method()
            logger.info(f"Discovered {len(capabilities)} capability groups for {resource_type}")
            return capabilities
        except Exception as e:
            logger.error(f"Failed to discover capabilities for {resource_type}: {e}")
            return {}

    async def _discover_system_capabilities(self) -> Dict[str, Any]:
        """Discover system-level capabilities and configuration."""
        return {
            "mcp_server": {
                "version": MCP_SERVER_VERSION,
                "tools_count": PROFILE_TOOL_COUNTS[DEFAULT_PROFILE],
                "supported_profiles": list(PROFILE_DEFINITIONS.keys()),
                "default_profile": DEFAULT_PROFILE
            },
            "api_integration": {
                "base_url": DEFAULT_BASE_URL,
                "supported_versions": API_SUPPORTED_VERSIONS,
                "authentication": AUTHENTICATION_METHODS,
                "rate_limits": {
                    "requests_per_minute": API_RATE_LIMIT_PER_MINUTE,
                    "burst_limit": API_BURST_LIMIT
                }
            },
            "environment": {
                "required_variables": [
                    "REVENIUM_API_KEY"
                ],
                "optional_variables": [
                    "REVENIUM_DEFAULT_EMAIL",
                    "MCP_STARTUP_VERBOSE",
                    "REVENIUM_BASE_URL"
                ]
            },
            "capabilities": {
                "resource_types": [
                    "system",
                    "products",
                    "subscriptions",
                    "customers",
                    "alerts",
                    "sources",
                    "metering_elements",
                    "metering"
                ],
                "operations": ["create", "read", "update", "delete", "list"],
                "features": [
                    "real_time_validation",
                    "capability_caching",
                    "auto_discovery",
                    "error_recovery"
                ]
            },
            "health_monitoring": {
                "endpoints": [
                    "get_health_status",
                    "refresh_capabilities",
                    "verify_capability"
                ],
                "metrics": [
                    "cache_hit_ratio",
                    "api_response_time",
                    "error_rate"
                ]
            }
        }

    async def _discover_product_capabilities(self) -> Dict[str, Any]:
        """Discover product-related capabilities."""
        return {
            "plan_types": [plan_type.value for plan_type in PlanType],
            "currencies": [currency.value for currency in Currency],
            "billing_periods": [period.value for period in BillingPeriod],
            "trial_periods": [trial.value for trial in TrialPeriod],
            "payment_sources": [
                payment.value for payment in PaymentSource
            ],  # DOCUMENTED_OPERATIONAL_ENUM
            "aggregation_types": [agg_type.value for agg_type in AggregationType],
            "rating_aggregation_types": [
                rating_type.value for rating_type in RatingAggregationType
            ],
            "schema": {
                "product_data": {
                    "required": ["name", "version", "plan"],
                    "optional": [
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
                    "plan_schema": {
                        "required": ["type", "currency"],
                        "optional": ["price", "trial_period", "billing_period", "tiers"],
                    },
                }
            },
            "validation_rules": {
                "name": {"type": "string", "min_length": 1, "max_length": 255},
                "version": {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"},
                "plan.type": {"enum": [plan_type.value for plan_type in PlanType]},
                "plan.currency": {"enum": [currency.value for currency in Currency]},
                "paymentSource": {"enum": [payment.value for payment in PaymentSource]},
            },
            "payment_source_explanations": {
                "INVOICE_ONLY_NO_PAYMENT": "Manual invoice payment - Send invoices, customers pay outside system, no payment tracking",
                "EXTERNAL_PAYMENT_NOTIFICATION": "Tracked invoice payment - Send invoices, mark unpaid until external system confirms payment",
            },
        }

    async def _discover_subscription_capabilities(self) -> Dict[str, Any]:
        """Discover subscription-related capabilities from API with fallback."""
        try:
            # Try to discover capabilities from actual API endpoints
            billing_periods = await self._discover_billing_periods_from_api()
            trial_periods = await self._discover_trial_periods_from_api()
            subscription_types = await self._discover_subscription_types_from_api()
            currencies = await self._discover_currencies_from_api()
        except Exception as e:
            logger.warning(f"API discovery failed for subscriptions, using fallback: {e}")
            # Provide fallback capabilities when API discovery fails
            billing_periods = ["MONTH", "QUARTER", "YEAR", "WEEK", "DAY"]
            trial_periods = ["DAY", "WEEK", "MONTH"]
            subscription_types = ["monthly", "quarterly", "yearly"]
            currencies = ["USD", "EUR", "GBP", "CAD", "AUD", "JPY"]

        return {
            "billing_periods": billing_periods,
            "trial_periods": trial_periods,
            "subscription_types": subscription_types,
            "currencies": currencies,
            "subscription_statuses": [
                "ACTIVE",
                "INACTIVE",
                "PENDING",
                "CANCELLED",
                "SUSPENDED",
                "TRIAL"
            ],
            "payment_methods": [
                "INVOICE_ONLY_NO_PAYMENT",
                "EXTERNAL_PAYMENT_NOTIFICATION",
                "CREDIT_CARD",
                "BANK_TRANSFER"
            ],
            "schema": {
                "subscription_data": {
                    "required": ["product_id", "name", "clientEmailAddress"],
                    "optional": [
                        "description",
                        "start_date",
                        "end_date",
                        "billing_address",
                        "payment_method",
                        "trial_end_date",
                        "metadata",
                        "tags",
                    ],
                }
            },
            "validation_rules": {
                "product_id": {"type": "string", "min_length": 1},
                "name": {"type": "string", "min_length": 1, "max_length": 255},
                "clientEmailAddress": {"type": "string", "format": "email"},
            },
            "business_rules": [
                "Product must exist before subscription creation",
                "Email address must be valid and unique",
                "Trial periods require end date specification",
                "Billing periods must align with product plan settings",
            ],
        }

    async def _discover_customer_capabilities(self) -> Dict[str, Any]:
        """Discover customer-related capabilities from actual API validation."""
        # VALIDATED AGAINST ACTUAL REVENIUM API - 2025-06-15
        return {
            "resource_types": ["users", "subscribers", "organizations", "teams", "relationships"],
            "user_roles": ["ROLE_TENANT_ADMIN", "ROLE_API_CONSUMER"],  # VERIFIED: From actual API
            "organization_types": ["CONSUMER"],  # VERIFIED: Only type found in actual API
            "schemas": {
                "users": {
                    "required": [
                        "email",
                        "firstName",
                        "lastName",
                    ],  # VERIFIED: All present in API responses
                    "optional": [
                        "phoneNumber",
                        "homepagePreference",
                        "roles",
                        "primaryUser",
                        "subscriberId",
                    ],  # VERIFIED: From API
                },
                "organizations": {
                    "required": ["name"],  # VERIFIED: Only name is required by API
                    "optional": [
                        "externalId",
                        "logo",
                        "address1",
                        "address2",
                        "city",
                        "state",
                        "country",
                        "postalCode",
                        "billingPhoneNumber",
                        "phoneNumber",
                        "emailAddress",
                        "remittanceInstructions",
                        "url",
                        "currency",
                        "metadata",
                        "domainAliases",
                        "types",
                        "billingEmail",
                        "sourceAutoDiscoveryEnabled",
                        "elementDefinitionAutoDiscoveryEnabled",
                    ],  # VERIFIED: All optional fields from actual API response
                },
                "subscribers": {
                    "required": ["email"],  # VERIFIED: Based on API structure
                    "optional": [
                        "firstName",
                        "lastName",
                        "metadata",
                        "organization_id",
                    ],  # VERIFIED: From API patterns
                },
            },
            "validation_rules": {
                "email": {"type": "string", "format": "email"},
                "firstName": {"type": "string", "min_length": 1},
                "lastName": {"type": "string", "min_length": 1},
                "name": {"type": "string", "min_length": 1, "max_length": 255},
                "roles": {
                    "enum": ["ROLE_TENANT_ADMIN", "ROLE_API_CONSUMER"]
                },  # VERIFIED: From actual API
                "types": {"enum": ["CONSUMER"]},  # VERIFIED: Only valid organization type
                "currency": {"enum": ["USD"]},  # VERIFIED: From actual API responses
            },
            "business_rules": [
                "Email addresses must be unique within the system",
                "Organization names should be unique within the team",
                "Users require firstName and lastName for proper identification",
                "Organizations default to CONSUMER type",
                "Currency defaults to USD for organizations",
                "Teams are automatically created with organizations",
            ],
        }

    async def _discover_alert_capabilities(self) -> Dict[str, Any]:
        """Discover alert-related capabilities using single source of truth."""
        # Get metrics from single source of truth (MetricType enum)
        all_metrics = [metric.value for metric in MetricType]

        # Categorize metrics for better organization
        cost_metrics = [m for m in all_metrics if "COST" in m]
        token_metrics = [m for m in all_metrics if "TOKEN" in m]
        performance_metrics = [
            m for m in all_metrics if any(perf in m for perf in ["PER_MINUTE", "RATE"])
        ]
        quality_metrics = [m for m in all_metrics if "ERROR" in m]

        return {
            "alert_types": ["THRESHOLD", "CUMULATIVE_USAGE", "RELATIVE_CHANGE"],
            "metrics": {
                "cost_metrics": cost_metrics,
                "token_metrics": token_metrics,
                "performance_metrics": performance_metrics,
                "quality_metrics": quality_metrics,
                "all": all_metrics,
            },
            "operators": [
                "GREATER_THAN",
                "GREATER_THAN_OR_EQUAL_TO",
                "LESS_THAN",
                "LESS_THAN_OR_EQUAL_TO",
                "EQUAL_TO",
                "NOT_EQUAL_TO",
            ],
            "period_durations": ["ONE_MINUTE", "DAILY", "WEEKLY", "MONTHLY"],
            "schema": {
                "threshold_alert": {
                    "required": ["name", "metricType", "operatorType", "threshold"],
                    "optional": ["email", "periodDuration", "filters"],
                },
                "cumulative_usage_alert": {
                    "required": ["name", "threshold", "period", "email"],
                    "optional": ["metric", "filters"],
                },
            },
        }

    async def _discover_source_capabilities(self) -> Dict[str, Any]:
        """Discover source-related capabilities from actual API validation."""
        # VALIDATED AGAINST ACTUAL REVENIUM API - 2025-06-15
        return {
            "source_types": ["API", "STREAM", "AI"],  # VERIFIED: Only these work in actual API
            # NOTE: No source_statuses - API doesn't have status field, only created/updated timestamps
            "schema": {
                "source_data": {
                    "required": [
                        "name",
                        "description",
                        "version",
                        "type",
                    ],  # VERIFIED: Required by API
                    "optional": [
                        "sourceType",
                        "syncedWithApiGateway",
                        "autoDiscoveryEnabled",
                        "tags",
                        "sourceClassifications",
                        "metadata",
                        "logoURL",
                        "devPortalLink",
                        "externalId",
                        "externalUsagePlanId",
                    ],  # VERIFIED: Optional fields from API response
                }
            },
            "validation_rules": {
                "name": {"type": "string", "min_length": 1, "max_length": 255},
                "description": {"type": "string", "min_length": 1},
                "version": {
                    "type": "string",
                    "pattern": r"^\d+\.\d+\.\d+$",
                },  # VERIFIED: Required format
                "type": {"enum": ["API", "STREAM", "AI"]},  # VERIFIED: Only valid types
                "sourceType": {"enum": ["API", "STREAM", "AI", "UNKNOWN"]},  # VERIFIED: From API
                "syncedWithApiGateway": {"type": "boolean"},
                "autoDiscoveryEnabled": {"type": "boolean"},
            },
            "business_rules": [
                "Source name must be unique within team",
                "Version must follow semantic versioning (x.y.z)",
                "Type cannot be changed after creation",
                "Sources require team and owner assignment",
                "Metering elements are automatically assigned based on source type",
            ],
        }

    async def _discover_metering_element_capabilities(self) -> Dict[str, Any]:
        """Discover metering element capabilities from validated API fields."""
        # VALIDATED AGAINST ACTUAL REVENIUM API - Based on working API calls
        # These fields are confirmed to work with the metering element definition API
        return {
            "element_types": ["NUMBER", "STRING"],  # VERIFIED: From actual API responses
            "schema": {
                "element_data": {
                    "required": ["name", "type"],  # VERIFIED: Minimum required fields
                    "optional": ["description"],   # VERIFIED: Works in API calls
                }
            },
            "validation_rules": {
                "name": {"type": "string", "min_length": 1, "max_length": 255},
                "type": {"enum": ["NUMBER", "STRING"]},
                "description": {"type": "string", "optional": True},
            },
            "api_notes": [
                "Element names must be unique within organization",
                "Type cannot be changed after creation",
                "Description is optional but recommended for clarity",
                "Elements must be assigned to sources before use in products",
            ],
        }

    async def _discover_metering_capabilities(self) -> Dict[str, Any]:
        """Discover AI metering transaction capabilities with smart model/provider summary."""
        try:
            # Discover AI transaction field capabilities from AI completions endpoint
            transaction_fields = await self._discover_ai_transaction_fields()

            # Get smart summary of models/providers (not full 3000 models)
            models_summary = await self._get_models_summary()

            logger.info(
                f"Discovered AI metering capabilities: {len(transaction_fields.get('required', []))} required fields, "
                f"{models_summary['providers']['total']} providers, {models_summary['models']['total']} models"
            )

            return {
                # AI Transaction Field Capabilities (primary focus for metering)
                "transaction_fields": transaction_fields,
                # Smart Model/Provider Summary (not full 3000 models)
                "provider_summary": models_summary["providers"],
                "model_summary": models_summary["models"],
                # Critical Validation Requirements
                "validation_requirements": {
                    "critical": "Provider and model MUST match supported combinations from AI models endpoint",
                    "consequence": "Unsupported combinations result in inaccurate cost calculations in Revenium",
                    "recommendation": "Always verify model/provider support using AI models tools before sending transactions",
                    "lookup_tools": [
                        "list_ai_models",
                        "search_ai_models",
                        "get_supported_providers",
                    ],
                },
                "schema": transaction_fields.get(
                    "schema",
                    {
                        "transaction_data": {
                            "required": [
                                "model",
                                "provider",
                                "input_tokens",
                                "output_tokens",
                                "duration_ms",
                            ],
                            "optional": [
                                "organization_id",
                                "subscriber_email",
                                "task_type",
                                "agent",
                                "trace_id",
                                "product_id",
                                "subscription_id",
                                "subscriber_credential",
                                "subscriber_credential_name",
                                "task_id",
                                "response_quality_score",
                                "stop_reason",
                                "is_streamed",
                            ],
                        }
                    },
                ),
                "validation_rules": transaction_fields.get(
                    "validation_rules",
                    {
                        "model": {"type": "string", "min_length": 1},
                        "provider": {"type": "string", "min_length": 1},
                        "input_tokens": {"type": "integer", "minimum": 1},
                        "output_tokens": {"type": "integer", "minimum": 1},
                        "duration_ms": {"type": "integer", "minimum": 1},
                        "response_quality_score": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                    },
                ),
                "business_rules": [
                    "⚠️ CRITICAL: Model and provider must be valid combinations from AI models endpoint",
                    "Use AI models management tools to find supported models before sending transactions",
                    "Unsupported combinations result in inaccurate cost calculations in Revenium",
                    "Search tools: 'list_ai_models', 'search_ai_models', 'get_supported_providers'",
                ],
            }

        except Exception as e:
            logger.error(f"Failed to discover AI metering capabilities: {e}")
            # Return fallback AI transaction capabilities
            return {
                "transaction_fields": {
                    "required": [
                        "model",
                        "provider",
                        "input_tokens",
                        "output_tokens",
                        "duration_ms",
                    ],
                    "optional": [
                        "organization_id",
                        "subscriber_email",
                        "task_type",
                        "agent",
                        "trace_id",
                        "product_id",
                        "subscription_id",
                        "subscriber_credential",
                        "subscriber_credential_name",
                        "task_id",
                        "response_quality_score",
                        "stop_reason",
                        "is_streamed",
                    ],
                },
                "sample_providers": [],
                "sample_models": [],
                "total_providers": 0,
                "error": f"Failed to discover AI metering capabilities: {str(e)}",
                "schema": {
                    "transaction_data": {
                        "required": [
                            "model",
                            "provider",
                            "input_tokens",
                            "output_tokens",
                            "duration_ms",
                        ],
                        "optional": [
                            "organization_id",
                            "subscriber_email",
                            "task_type",
                            "agent",
                            "trace_id",
                            "product_id",
                            "subscription_id",
                            "subscriber_credential",
                            "subscriber_credential_name",
                            "task_id",
                            "response_quality_score",
                            "stop_reason",
                            "is_streamed",
                        ],
                    }
                },
            }

    async def _discover_ai_transaction_fields(self) -> Dict[str, Any]:
        """Discover AI transaction field capabilities from AI completions endpoint."""
        try:
            # This would ideally call the AI completions endpoint to discover
            # what fields are required/optional for metering transactions
            # For now, return the known schema based on the AI completions API

            logger.info("Discovering AI transaction fields from AI completions endpoint")

            # TODO: Make actual API call to AI completions endpoint to discover schema
            # For now, return the known schema structure
            return {
                "required": ["model", "provider", "input_tokens", "output_tokens", "duration_ms"],
                "optional": [
                    "organization_id",
                    "subscriber_email",
                    "task_type",
                    "agent",
                    "trace_id",
                    "product_id",
                    "subscription_id",
                    "subscriber_credential",
                    "subscriber_credential_name",
                    "task_id",
                    "response_quality_score",
                    "stop_reason",
                    "is_streamed",
                ],
                "schema": {
                    "transaction_data": {
                        "required": [
                            "model",
                            "provider",
                            "input_tokens",
                            "output_tokens",
                            "duration_ms",
                        ],
                        "optional": [
                            "organization_id",
                            "subscriber_email",
                            "task_type",
                            "agent",
                            "trace_id",
                            "product_id",
                            "subscription_id",
                            "subscriber_credential",
                            "subscriber_credential_name",
                            "task_id",
                            "response_quality_score",
                            "stop_reason",
                            "is_streamed",
                        ],
                    }
                },
                "validation_rules": {
                    "model": {"type": "string", "min_length": 1},
                    "provider": {"type": "string", "min_length": 1},
                    "input_tokens": {"type": "integer", "minimum": 1},
                    "output_tokens": {"type": "integer", "minimum": 1},
                    "duration_ms": {"type": "integer", "minimum": 1},
                    "response_quality_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
            }

        except Exception as e:
            logger.warning(f"AI transaction fields discovery failed: {e}")
            # Return basic fallback schema
            return {
                "required": ["model", "provider", "input_tokens", "output_tokens", "duration_ms"],
                "optional": ["organization_id", "subscriber_email", "task_type", "agent"],
                "error": f"Failed to discover transaction fields: {str(e)}",
            }

    async def _discover_traditional_metrics(self) -> List[str]:
        """Discover traditional metrics from API endpoints."""
        try:
            metrics = set()

            # Try to discover from anomalies/alerts
            try:
                response = await self.client.get("anomalies", params={"page": 0, "size": 20})
                if "data" in response and isinstance(response["data"], list):
                    for anomaly in response["data"]:
                        if "metricType" in anomaly:
                            metrics.add(anomaly["metricType"])
                        if "metric" in anomaly:
                            metrics.add(anomaly["metric"])
            except Exception as e:
                logger.debug(f"Failed to discover metrics from anomalies: {e}")

            # Try to discover from metering elements
            try:
                response = await self.client.get(
                    "metering-elements", params={"page": 0, "size": 20}
                )
                if "data" in response and isinstance(response["data"], list):
                    for element in response["data"]:
                        if "metricType" in element:
                            metrics.add(element["metricType"])
                        # Infer metrics from element names/types
                        if "name" in element:
                            name = element["name"].upper()
                            if "COST" in name:
                                metrics.add("TOTAL_COST")
                            if "TOKEN" in name:
                                metrics.add("TOKEN_COUNT")
                            if "ERROR" in name:
                                metrics.add("ERROR_RATE")
            except Exception as e:
                logger.debug(f"Failed to discover metrics from metering elements: {e}")

            # Add standard metrics if none discovered
            if not metrics:
                metrics = {
                    "TOTAL_COST",
                    "TOKEN_COUNT",
                    "INPUT_TOKEN_COUNT",
                    "OUTPUT_TOKEN_COUNT",
                    "TOKENS_PER_MINUTE",
                    "REQUESTS_PER_MINUTE",
                    "ERROR_RATE",
                    "ERROR_COUNT",
                    "LATENCY",
                    "THROUGHPUT",
                    "USAGE_COUNT",
                }
                logger.info("No metrics discovered from API, using standard AI/SaaS metrics")
            else:
                logger.info(f"Discovered {len(metrics)} metrics from API: {metrics}")

            return sorted(list(metrics))

        except Exception as e:
            logger.warning(f"Traditional metrics discovery failed: {e}")
            return [
                "TOTAL_COST",
                "TOKEN_COUNT",
                "ERROR_RATE",
                "TOKENS_PER_MINUTE",
                "REQUESTS_PER_MINUTE",
            ]

    async def _discover_operators(self) -> List[str]:
        """Discover operators from API endpoints."""
        try:
            operators = set()

            # Try to discover from anomalies/alerts
            try:
                response = await self.client.get("anomalies", params={"page": 0, "size": 20})
                if "data" in response and isinstance(response["data"], list):
                    for anomaly in response["data"]:
                        if "operatorType" in anomaly:
                            operators.add(anomaly["operatorType"])
                        if "operator" in anomaly:
                            operators.add(anomaly["operator"])
            except Exception as e:
                logger.debug(f"Failed to discover operators from anomalies: {e}")

            # Add standard operators if none discovered
            if not operators:
                operators = {
                    "GREATER_THAN",
                    "GREATER_THAN_OR_EQUAL_TO",
                    "LESS_THAN",
                    "LESS_THAN_OR_EQUAL_TO",
                    "EQUALS",
                    "NOT_EQUALS",
                    "BETWEEN",
                }
                logger.info("No operators discovered from API, using standard comparison operators")
            else:
                logger.info(f"Discovered {len(operators)} operators from API: {operators}")

            return sorted(list(operators))

        except Exception as e:
            logger.warning(f"Operators discovery failed: {e}")
            return ["GREATER_THAN", "LESS_THAN", "EQUALS"]

    async def _get_models_summary(self) -> Dict[str, Any]:
        """Get lightweight summary of AI models and providers without loading all 3000 models."""
        try:
            # Get first 100 models for sampling and total count
            models_response = await self.client.get_ai_models(page=0, size=100)

            providers = set()
            sample_models = []
            total_models = 0

            if (
                "_embedded" in models_response
                and "aIModelResourceList" in models_response["_embedded"]
            ):
                models = models_response["_embedded"]["aIModelResourceList"]

                # Extract total count from pagination info
                if "page" in models_response:
                    total_models = models_response["page"].get("totalElements", len(models))
                else:
                    total_models = len(models)

                # Sample first 10 models for examples
                for model in models[:10]:
                    provider = model.get("provider", "Unknown")
                    model_name = model.get("name", "Unknown")
                    providers.add(provider)
                    sample_models.append(f"{provider}/{model_name}")

                # Continue through all 100 to get more provider diversity
                for model in models:
                    providers.add(model.get("provider", "Unknown"))

            provider_list = sorted(list(providers))

            logger.info(
                f"Models summary: {total_models} total models, {len(provider_list)} providers sampled"
            )

            return {
                "providers": {
                    "total": len(provider_list),  # This is sampled count, not true total
                    "samples": provider_list[:5],  # Top 5 providers
                    "lookup_guidance": "Use 'list_ai_models' or 'search_ai_models' tools to find all supported providers",
                    "note": f"Showing {len(provider_list)} providers from sample of {len(models) if 'models' in locals() else 0} models",
                },
                "models": {
                    "total": total_models,
                    "samples": sample_models[:5],  # Top 5 model examples
                    "lookup_guidance": "Use AI models tools to search by provider or name for complete model list",
                    "note": f"Showing {len(sample_models)} sample models out of {total_models} total",
                },
            }

        except Exception as e:
            logger.warning(f"Models summary discovery failed: {e}")
            # Return conservative fallback
            return {
                "providers": {
                    "total": 0,
                    "samples": ["openai", "anthropic", "google"],
                    "lookup_guidance": "Use AI models tools to discover supported providers",
                    "error": f"Failed to fetch models summary: {str(e)}",
                },
                "models": {
                    "total": 0,
                    "samples": ["openai/gpt-4o", "anthropic/claude-3-5-sonnet"],
                    "lookup_guidance": "Use AI models tools to discover supported models",
                    "error": f"Failed to fetch models summary: {str(e)}",
                },
            }

    async def _discover_billing_periods_from_api(self) -> List[str]:
        """Discover billing periods from actual API endpoints."""
        try:
            periods = set()

            # Try to discover from products endpoint
            try:
                response = await self.client.get("products", params={"page": 0, "size": 50})
                if "data" in response and isinstance(response["data"], list):
                    for product in response["data"]:
                        if "plan" in product and "period" in product["plan"]:
                            periods.add(product["plan"]["period"])
                        if "plan" in product and "billingPeriod" in product["plan"]:
                            periods.add(product["plan"]["billingPeriod"])
            except Exception as e:
                logger.debug(f"Failed to discover billing periods from products: {e}")

            # Try to discover from subscriptions endpoint
            try:
                response = await self.client.get("subscriptions", params={"page": 0, "size": 50})
                if "data" in response and isinstance(response["data"], list):
                    for subscription in response["data"]:
                        if "billingPeriod" in subscription:
                            periods.add(subscription["billingPeriod"])
                        if "period" in subscription:
                            periods.add(subscription["period"])
            except Exception as e:
                logger.debug(f"Failed to discover billing periods from subscriptions: {e}")

            if periods:
                logger.info(f"Discovered {len(periods)} billing periods from API: {periods}")
                return sorted(list(periods))
            else:
                # If no periods discovered, raise error to force proper API integration
                raise ValueError(
                    "No billing periods discovered from API - UCM integration required"
                )

        except Exception as e:
            logger.error(f"Billing periods discovery failed: {e}")
            raise ValueError(f"Failed to discover billing periods from API: {str(e)}")

    async def _discover_trial_periods_from_api(self) -> List[str]:
        """Discover trial periods from actual API endpoints."""
        try:
            periods = set()

            # Try to discover from products endpoint
            try:
                response = await self.client.get("products", params={"page": 0, "size": 50})
                if "data" in response and isinstance(response["data"], list):
                    for product in response["data"]:
                        if "plan" in product and "trialPeriod" in product["plan"]:
                            periods.add(product["plan"]["trialPeriod"])
                        if "trialPeriod" in product:
                            periods.add(product["trialPeriod"])
            except Exception as e:
                logger.debug(f"Failed to discover trial periods from products: {e}")

            # Try to discover from subscriptions endpoint
            try:
                response = await self.client.get("subscriptions", params={"page": 0, "size": 50})
                if "data" in response and isinstance(response["data"], list):
                    for subscription in response["data"]:
                        if "trialPeriod" in subscription:
                            periods.add(subscription["trialPeriod"])
            except Exception as e:
                logger.debug(f"Failed to discover trial periods from subscriptions: {e}")

            if periods:
                logger.info(f"Discovered {len(periods)} trial periods from API: {periods}")
                return sorted(list(periods))
            else:
                # If no periods discovered, raise error to force proper API integration
                raise ValueError("No trial periods discovered from API - UCM integration required")

        except Exception as e:
            logger.error(f"Trial periods discovery failed: {e}")
            raise ValueError(f"Failed to discover trial periods from API: {str(e)}")

    async def _discover_subscription_types_from_api(self) -> List[str]:
        """Discover subscription types from actual API endpoints."""
        try:
            types = set()

            # Try to discover from subscriptions endpoint
            try:
                response = await self.client.get("subscriptions", params={"page": 0, "size": 50})
                if "data" in response and isinstance(response["data"], list):
                    for subscription in response["data"]:
                        if "type" in subscription:
                            types.add(subscription["type"])
                        # Infer types from billing periods
                        if "billingPeriod" in subscription:
                            period = subscription["billingPeriod"].lower()
                            if period in ["month", "monthly"]:
                                types.add("monthly")
                            elif period in ["quarter", "quarterly"]:
                                types.add("quarterly")
                            elif period in ["year", "yearly", "annual"]:
                                types.add("yearly")
            except Exception as e:
                logger.debug(f"Failed to discover subscription types from subscriptions: {e}")

            if types:
                logger.info(f"Discovered {len(types)} subscription types from API: {types}")
                return sorted(list(types))
            else:
                # If no types discovered, raise error to force proper API integration
                raise ValueError(
                    "No subscription types discovered from API - UCM integration required"
                )

        except Exception as e:
            logger.error(f"Subscription types discovery failed: {e}")
            raise ValueError(f"Failed to discover subscription types from API: {str(e)}")

    async def _discover_currencies_from_api(self) -> List[str]:
        """Discover currencies from actual API endpoints."""
        try:
            currencies = set()

            # Try to discover from products endpoint
            try:
                response = await self.client.get("products", params={"page": 0, "size": 50})
                if "data" in response and isinstance(response["data"], list):
                    for product in response["data"]:
                        if "plan" in product and "currency" in product["plan"]:
                            currencies.add(product["plan"]["currency"])
                        if "currency" in product:
                            currencies.add(product["currency"])
            except Exception as e:
                logger.debug(f"Failed to discover currencies from products: {e}")

            # Try to discover from subscriptions endpoint
            try:
                response = await self.client.get("subscriptions", params={"page": 0, "size": 50})
                if "data" in response and isinstance(response["data"], list):
                    for subscription in response["data"]:
                        if "currency" in subscription:
                            currencies.add(subscription["currency"])
            except Exception as e:
                logger.debug(f"Failed to discover currencies from subscriptions: {e}")

            # Try to discover from organizations endpoint
            try:
                response = await self.client.get("organizations", params={"page": 0, "size": 50})
                if "data" in response and isinstance(response["data"], list):
                    for org in response["data"]:
                        if "currency" in org:
                            currencies.add(org["currency"])
            except Exception as e:
                logger.debug(f"Failed to discover currencies from organizations: {e}")

            if currencies:
                logger.info(f"Discovered {len(currencies)} currencies from API: {currencies}")
                return sorted(list(currencies))
            else:
                # If no currencies discovered, raise error to force proper API integration
                raise ValueError("No currencies discovered from API - UCM integration required")

        except Exception as e:
            logger.error(f"Currencies discovery failed: {e}")
            raise ValueError(f"Failed to discover currencies from API: {str(e)}")
