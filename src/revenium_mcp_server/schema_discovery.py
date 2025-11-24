"""Schema Discovery and Capabilities for Agent-Friendly MCP Design.

This module provides comprehensive schema discovery, examples, and validation
capabilities to make the MCP server much more agent-friendly.
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from .models import (  # REMOVED: SourceStatus - API doesn't support status field for sources; REMOVED: UserStatus, SubscriberStatus, OrganizationStatus, TeamStatus, TeamRole - NOT FOUND in actual API; REMOVED: OrganizationType - Only CONSUMER type found in actual API, hardcoded instead
    AggregationType,
    BillingPeriod,
    Currency,
    MetricType,
    PlanType,
    RatingAggregationType,
    SourceType,
    SubscriptionStatus,
    TrialPeriod,
    UserRole,
)
from .product_validators import ProductValidationEngine


class SchemaDiscoveryEngine:
    """Provides comprehensive schema discovery and capabilities for agents."""

    def __init__(self):
        """Initialize the schema discovery engine."""
        self.capabilities = self._build_capabilities()
        self.examples = self._build_examples()
        self.validation_rules = self._build_validation_rules()

    def get_capabilities(self, resource_type: str = "anomalies") -> Dict[str, Any]:
        """Get comprehensive capabilities and schema information.

        Args:
            resource_type: Type of resource (anomalies, alerts)

        Returns:
            Complete capabilities schema
        """
        logger.info(f"Getting capabilities for resource type: {resource_type}")

        if resource_type == "anomalies":
            return self.capabilities["anomalies"]
        elif resource_type == "alerts":
            return self.capabilities["alerts"]
        else:
            return {
                "error": f"Unknown resource type: {resource_type}",
                "available_types": list(self.capabilities.keys()),
            }

    def get_examples(
        self, resource_type: str = "anomalies", example_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get examples and templates for creating resources.

        Args:
            resource_type: Type of resource (anomalies, alerts)
            example_type: Optional filter for specific example types

        Returns:
            Examples and templates
        """
        logger.info(f"Getting examples for {resource_type}, type: {example_type}")

        if resource_type not in self.examples:
            return {
                "error": f"No examples available for resource type: {resource_type}",
                "available_types": list(self.examples.keys()),
            }

        examples = self.examples[resource_type]

        if example_type:
            filtered_examples = [ex for ex in examples if ex.get("type") == example_type]
            return {"examples": filtered_examples}

        return {"examples": examples}

    def validate_configuration(
        self, resource_type: str, config_data: Dict[str, Any], dry_run: bool = True
    ) -> Dict[str, Any]:
        """Validate configuration against schema with detailed feedback.

        Args:
            resource_type: Type of resource to validate
            config_data: Configuration data to validate
            dry_run: Whether this is a dry run validation

        Returns:
            Validation results with detailed feedback
        """
        logger.info(f"Validating {resource_type} configuration (dry_run: {dry_run})")

        if resource_type not in self.validation_rules:
            return {
                "valid": False,
                "error": f"No validation rules for resource type: {resource_type}",
                "available_types": list(self.validation_rules.keys()),
            }

        rules = self.validation_rules[resource_type]
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "suggestions": [],
            "dry_run": dry_run,
        }

        # Validate required fields
        for field in rules.get("required", []):
            if field not in config_data:
                validation_result["valid"] = False
                validation_result["errors"].append(
                    {
                        "field": field,
                        "error": f"Required field '{field}' is missing",
                        "suggestion": f"Add '{field}' field to your configuration",
                    }
                )

        # Validate detection rules if present
        if "detection_rules" in config_data:
            for i, rule in enumerate(config_data["detection_rules"]):
                rule_validation = self._validate_detection_rule(rule, i)
                if not rule_validation["valid"]:
                    validation_result["valid"] = False
                    validation_result["errors"].extend(rule_validation["errors"])
                validation_result["warnings"].extend(rule_validation.get("warnings", []))
                validation_result["suggestions"].extend(rule_validation.get("suggestions", []))

        # Add suggestions for improvement
        if validation_result["valid"]:
            validation_result["suggestions"].append(
                {
                    "type": "optimization",
                    "message": "Configuration is valid and ready for creation",
                    "next_steps": [
                        "Use 'create' action to create this anomaly",
                        "Consider adding filters for more specific monitoring",
                    ],
                }
            )

        return validation_result

    def get_agent_friendly_summary(self, resource_type: str = "anomalies") -> Dict[str, Any]:
        """Get a comprehensive, agent-friendly summary of all available options.

        This method provides everything an agent needs to know to create alerts
        without trial and error.

        Args:
            resource_type: Type of resource (anomalies, alerts)

        Returns:
            Complete summary with all valid options and examples
        """
        logger.info(f"Getting agent-friendly summary for {resource_type}")

        if resource_type not in self.capabilities:
            return {
                "error": f"Unknown resource type: {resource_type}",
                "available_types": list(self.capabilities.keys()),
            }

        caps = self.capabilities[resource_type]

        return {
            "resource_type": resource_type,
            "quick_reference": {
                "alert_types": caps.get("alert_types", []),
                "available_metrics": {
                    "cost": caps["metrics"]["cost_metrics"],
                    "tokens": caps["metrics"]["token_metrics"],
                    "performance": caps["metrics"]["performance_metrics"],
                    "quality": caps["metrics"]["quality_metrics"],
                },
                "operators": {
                    "threshold": caps["operators"]["threshold_operators"],
                    "relative_change": caps["operators"]["relative_change_operators"],
                    "string": caps["operators"]["string_operators"],
                },
                "time_periods": {
                    "check_every": caps["time_periods"]["period_duration"],
                    "trigger_after": caps["time_periods"]["trigger_after_persists_duration"],
                    "compare_to": caps["time_periods"]["comparison_period"],
                },
                "filter_dimensions": list(caps.get("filter_dimensions", {}).keys()),
            },
            "common_patterns": self._build_dynamic_patterns(caps),
            "natural_language_examples": [
                "Alert when cost per transaction exceeds $0.50",
                "Notify when error rate is above 5% for 10 minutes",
                "Alert when total daily cost reaches $1000",
                "Notify when tokens per second drops below 100",
                "Alert when OpenAI model costs exceed $50 per hour",
                "Alert when monthly spending exceeds $5000",
                "Notify when weekly token usage reaches 1 million",
                "Alert when daily API calls exceed 10,000",
                "Notify when quarterly costs approach $25,000",
                "Alert when cumulative usage in period exceeds threshold",
                "Monitor weekly spending for customer Acme",
                "Track monthly token consumption for GPT-4",
                "Alert when daily costs for production exceed $500",
            ],
        }

    def _validate_detection_rule(self, rule: Dict[str, Any], rule_index: int) -> Dict[str, Any]:
        """Validate a single detection rule."""
        result = {"valid": True, "errors": [], "warnings": [], "suggestions": []}

        # Check required fields
        required_fields = ["rule_type", "metric", "operator", "value"]
        for field in required_fields:
            if field not in rule:
                result["valid"] = False
                result["errors"].append(
                    {
                        "field": f"detection_rules[{rule_index}].{field}",
                        "error": f"Required field '{field}' is missing in detection rule {rule_index}",
                        "valid_values": self._get_valid_values_for_field(field),
                    }
                )

        # Validate specific field values
        if "rule_type" in rule:
            valid_types = ["THRESHOLD", "CUMULATIVE_USAGE", "RELATIVE_CHANGE"]
            if rule["rule_type"] not in valid_types:
                result["valid"] = False
                result["errors"].append(
                    {
                        "field": f"detection_rules[{rule_index}].rule_type",
                        "error": f"Invalid rule type: {rule['rule_type']}",
                        "valid_values": valid_types,
                        "suggestion": f"Use one of: {', '.join(valid_types)}",
                    }
                )

        if "metric" in rule:
            valid_metrics = self.capabilities["anomalies"]["metrics"]["all"]
            if rule["metric"] not in valid_metrics:
                result["valid"] = False
                result["errors"].append(
                    {
                        "field": f"detection_rules[{rule_index}].metric",
                        "error": f"Invalid metric: {rule['metric']}",
                        "valid_values": valid_metrics,
                        "suggestion": "See capabilities for categorized metric options",
                    }
                )

        if "operator" in rule:
            valid_operators = self.capabilities["anomalies"]["operators"]["all"]
            if rule["operator"] not in valid_operators:
                result["valid"] = False
                result["errors"].append(
                    {
                        "field": f"detection_rules[{rule_index}].operator",
                        "error": f"Invalid operator: {rule['operator']}",
                        "valid_values": valid_operators,
                        "suggestion": "Use operators like 'GREATER_THAN', 'LESS_THAN', 'CONTAINS', etc. See capabilities for categorized options",
                    }
                )

        return result

    def _get_valid_values_for_field(self, field: str) -> List[str]:
        """Get valid values for a specific field."""
        field_mappings = {
            "rule_type": ["THRESHOLD", "CUMULATIVE_USAGE", "RELATIVE_CHANGE"],
            "metric": self.capabilities["anomalies"]["metrics"]["all"],
            "operator": self.capabilities["anomalies"]["operators"]["all"],
        }
        return field_mappings.get(field, [])

    def _build_dynamic_patterns(self, caps: Dict[str, Any]) -> Dict[str, Any]:
        """Build dynamic patterns using MetricType enum."""
        # Get metrics dynamically
        all_metrics = caps.get("metrics", {}).get("all", [metric.value for metric in MetricType])
        cost_metrics = [m for m in all_metrics if "COST" in m]
        token_metrics = [m for m in all_metrics if "TOKEN" in m]
        performance_metrics = [
            m for m in all_metrics if any(perf in m for perf in ["PER_MINUTE", "RATE"])
        ]

        return {
            "cost_monitoring": {
                "metrics": cost_metrics,
                "operators": ["GREATER_THAN", "GREATER_THAN_OR_EQUAL_TO"],
                "typical_values": "0.01 to 100.00 (dollars)",
            },
            "performance_monitoring": {
                "metrics": performance_metrics,
                "operators": ["GREATER_THAN", "LESS_THAN"],
                "typical_values": "Depends on metric (rates: 1-1000, error_rate: 1-10%)",
            },
            "usage_monitoring": {
                "metrics": token_metrics,
                "operators": ["GREATER_THAN", "GREATER_THAN_OR_EQUAL_TO"],
                "typical_values": "100 to 100000 (tokens)",
            },
            "cumulative_usage_monitoring": {
                "metrics": cost_metrics + token_metrics,  # Dynamic combination
                "operators": ["GREATER_THAN_OR_EQUAL_TO", "GREATER_THAN"],
                "typical_values": "Budget limits: $100-$50000, Tokens: 100K-10M, Requests: 1K-100K",
                "time_periods": ["daily", "weekly", "monthly", "quarterly"],
                "description": "Monitor cumulative usage over calendar periods",
            },
        }

    def _build_capabilities(self) -> Dict[str, Any]:
        """Build comprehensive capabilities schema using single source of truth."""
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
            "anomalies": {
                "alert_types": ["THRESHOLD", "CUMULATIVE_USAGE", "RELATIVE_CHANGE"],
                "metrics": {
                    "cost_metrics": cost_metrics,
                    "token_metrics": token_metrics,
                    "performance_metrics": performance_metrics,
                    "quality_metrics": quality_metrics,
                    "all": all_metrics,
                },
                "operators": {
                    "threshold_operators": [
                        "GREATER_THAN",
                        "GREATER_THAN_OR_EQUAL_TO",
                        "LESS_THAN",
                        "LESS_THAN_OR_EQUAL_TO",
                    ],
                    "relative_change_operators": ["INCREASES_BY", "DECREASES_BY"],
                    "string_operators": ["CONTAINS", "STARTS_WITH", "ENDS_WITH"],
                    "equality_operators": ["EQUALS", "NOT_EQUALS"],
                    "all": [
                        "GREATER_THAN",
                        "GREATER_THAN_OR_EQUAL_TO",
                        "LESS_THAN",
                        "LESS_THAN_OR_EQUAL_TO",
                        "INCREASES_BY",
                        "DECREASES_BY",
                        "CONTAINS",
                        "STARTS_WITH",
                        "ENDS_WITH",
                        "EQUALS",
                        "NOT_EQUALS",
                    ],
                },
                "time_periods": {
                    "period_duration": [
                        "ONE_MINUTE",
                        "FIVE_MINUTES",
                        "TEN_MINUTES",
                        "FIFTEEN_MINUTES",
                        "THIRTY_MINUTES",
                        "ONE_HOUR",
                        "TWO_HOURS",
                        "SIX_HOURS",
                        "TWELVE_HOURS",
                        "ONE_DAY",
                        "THREE_DAYS",
                        "SEVEN_DAYS",
                        "FOURTEEN_DAYS",
                        "THIRTY_DAYS",
                    ],
                    "trigger_after_persists_duration": [
                        "FIVE_MINUTES",
                        "TEN_MINUTES",
                        "FIFTEEN_MINUTES",
                        "THIRTY_MINUTES",
                        "ONE_HOUR",
                        "TWO_HOURS",
                        "SIX_HOURS",
                        "TWELVE_HOURS",
                        "ONE_DAY",
                        "THREE_DAYS",
                        "SEVEN_DAYS",
                        "FOURTEEN_DAYS",
                        "THIRTY_DAYS",
                    ],
                    "comparison_period": [
                        "ONE_DAY",
                        "THREE_DAYS",
                        "SEVEN_DAYS",
                        "FOURTEEN_DAYS",
                        "THIRTY_DAYS",
                    ],
                    "tracking_period": ["DAILY", "WEEKLY", "MONTHLY", "QUARTERLY"],
                },
                "filter_dimensions": {
                    "ORGANIZATION": {
                        "description": "Filter by customer/business organization",
                        "operators": ["CONTAINS", "EQUALS", "NOT_EQUALS"],
                        "example": "acme corp",
                    },
                    "CREDENTIAL": {
                        "description": "Filter by API key/credential name",
                        "operators": ["CONTAINS", "EQUALS", "NOT_EQUALS"],
                        "example": "production-api-key",
                    },
                    "PRODUCT": {
                        "description": "Filter by product name",
                        "operators": ["CONTAINS", "EQUALS", "NOT_EQUALS"],
                        "example": "AI API Service",
                    },
                    "MODEL": {
                        "description": "Filter by AI model name",
                        "operators": ["CONTAINS", "EQUALS", "NOT_EQUALS"],
                        "example": "gpt-4",
                    },
                    "PROVIDER": {
                        "description": "Filter by AI provider",
                        "operators": ["CONTAINS", "EQUALS", "NOT_EQUALS"],
                        "example": "openai",
                    },
                    "AGENT": {
                        "description": "Filter by agent/user",
                        "operators": ["CONTAINS", "EQUALS", "NOT_EQUALS"],
                        "example": "support-agent",
                    },
                    "SUBSCRIBER": {
                        "description": "Filter by subscriber name or email",
                        "operators": ["CONTAINS", "EQUALS", "NOT_EQUALS"],
                        "example": "john.doe@company.com",
                    },
                },
                "schema": {
                    "anomaly_data": {
                        "required": ["name", "alertType", "detection_rules"],
                        "optional": ["description", "enabled", "notificationAddresses", "filters"],
                        "detection_rule_schema": {
                            "required": ["rule_type", "metric", "operator", "value"],
                            "optional": ["time_window", "filters", "group_by", "isPercentage"],
                        },
                    }
                },
            },
            "alerts": {
                "statuses": ["open", "acknowledged", "resolved", "closed"],
                "severities": ["low", "medium", "high", "critical"],
                "query_parameters": {
                    "date_filters": ["start", "end", "created_after", "created_before"],
                    "status_filters": ["status", "severity", "anomaly_id"],
                    "pagination": ["page", "size"],
                },
            },
        }

    def _build_examples(self) -> Dict[str, List[Dict[str, Any]]]:
        """Build comprehensive examples and templates."""
        return {
            "anomalies": [
                {
                    "name": "High Cost Per Transaction Alert",
                    "type": "threshold_cost",
                    "description": "Triggers when cost per transaction exceeds threshold",
                    "use_case": "Monitor API costs to prevent budget overruns",
                    "template": {
                        "name": "High Cost Alert",
                        "alertType": "THRESHOLD",
                        "description": "Alert when cost per transaction is too high",
                        "enabled": True,
                        "detection_rules": [
                            {
                                "rule_type": "THRESHOLD",
                                "metric": "COST_PER_TRANSACTION",
                                "operator": ">=",
                                "value": 0.50,
                                "time_window": "5m",
                            }
                        ],
                        "notificationAddresses": ["admin@company.com"],
                    },
                },
                {
                    "name": "Token Usage Monitoring",
                    "type": "threshold_tokens",
                    "description": "Monitor token consumption rates",
                    "use_case": "Prevent excessive token usage",
                    "template": {
                        "name": "High Token Usage",
                        "alertType": "THRESHOLD",
                        "description": "Alert when token usage is high",
                        "enabled": True,
                        "detection_rules": [
                            {
                                "rule_type": "THRESHOLD",
                                "metric": "TOKENS_PER_MINUTE",
                                "operator": ">",
                                "value": 1000,
                                "time_window": "1m",
                            }
                        ],
                    },
                },
                {
                    "name": "Monthly Budget Alert",
                    "type": "cumulative_cost",
                    "description": "Track cumulative spending over time periods",
                    "use_case": "Monthly budget monitoring",
                    "template": {
                        "name": "Monthly Budget Alert",
                        "alertType": "CUMULATIVE_USAGE",
                        "description": "Alert when monthly spending exceeds budget",
                        "enabled": True,
                        "detection_rules": [
                            {
                                "rule_type": "CUMULATIVE_USAGE",
                                "metric": "TOTAL_COST",
                                "operator": ">=",
                                "value": 1000.00,
                                "time_window": "monthly",
                            }
                        ],
                        "notificationAddresses": ["billing@company.com"],
                    },
                },
                {
                    "name": "Weekly Token Usage Alert",
                    "type": "cumulative_tokens",
                    "description": "Monitor cumulative token consumption per week",
                    "use_case": "Weekly token budget management",
                    "template": {
                        "name": "Weekly Token Budget",
                        "alertType": "CUMULATIVE_USAGE",
                        "description": "Alert when weekly token usage exceeds limit",
                        "enabled": True,
                        "detection_rules": [
                            {
                                "rule_type": "CUMULATIVE_USAGE",
                                "metric": "TOKEN_COUNT",
                                "operator": ">=",
                                "value": 1000000,
                                "time_window": "weekly",
                            }
                        ],
                        "notificationAddresses": ["ops@company.com"],
                    },
                },
                {
                    "name": "Daily API Call Limit",
                    "type": "cumulative_requests",
                    "description": "Track daily API request volume",
                    "use_case": "Daily API usage monitoring",
                    "template": {
                        "name": "Daily API Limit",
                        "alertType": "CUMULATIVE_USAGE",
                        "description": "Alert when daily API calls exceed quota",
                        "enabled": True,
                        "detection_rules": [
                            {
                                "rule_type": "CUMULATIVE_USAGE",
                                "metric": "REQUEST_COUNT",
                                "operator": ">=",
                                "value": 10000,
                                "time_window": "daily",
                            }
                        ],
                        "notificationAddresses": ["api-team@company.com"],
                    },
                },
                {
                    "name": "Quarterly Cost Control",
                    "type": "cumulative_quarterly",
                    "description": "Monitor quarterly spending limits",
                    "use_case": "Quarterly budget enforcement",
                    "template": {
                        "name": "Quarterly Budget Control",
                        "alertType": "CUMULATIVE_USAGE",
                        "description": "Alert when quarterly costs approach budget limit",
                        "enabled": True,
                        "detection_rules": [
                            {
                                "rule_type": "CUMULATIVE_USAGE",
                                "metric": "TOTAL_COST",
                                "operator": ">=",
                                "value": 25000.00,
                                "time_window": "quarterly",
                            }
                        ],
                        "notificationAddresses": ["finance@company.com"],
                        "filters": [
                            {
                                "dimension": "ORGANIZATION",
                                "operator": "CONTAINS",
                                "value": "production",
                            }
                        ],
                    },
                },
                {
                    "name": "Error Rate Monitoring",
                    "type": "threshold_quality",
                    "description": "Monitor API error rates",
                    "use_case": "Service quality monitoring",
                    "template": {
                        "name": "High Error Rate",
                        "alertType": "THRESHOLD",
                        "description": "Alert when error rate exceeds threshold",
                        "enabled": True,
                        "detection_rules": [
                            {
                                "rule_type": "THRESHOLD",
                                "metric": "ERROR_RATE",
                                "operator": ">",
                                "value": 5.0,
                                "time_window": "5m",
                                "isPercentage": True,
                            }
                        ],
                    },
                },
            ]
        }

    def _build_validation_rules(self) -> Dict[str, Dict[str, Any]]:
        """Build validation rules for different resource types."""
        return {
            "anomalies": {
                "required": ["name", "alertType"],
                "optional": ["description", "enabled", "notificationAddresses", "filters"],
                "detection_rules_required": True,
            },
            "alerts": {"required": ["query"], "optional": ["page", "size", "filters"]},
            "products": {
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
                ],
                "plan_required": True,
                "tier_structure_validation": True,
            },
        }


class ProductSchemaDiscovery(SchemaDiscoveryEngine):
    """Product-specific schema discovery and validation capabilities."""

    def __init__(self):
        """Initialize the product schema discovery engine."""
        super().__init__()
        # Add product-specific capabilities to the base capabilities
        self.capabilities["products"] = self._build_product_capabilities()
        self.examples["products"] = self._build_product_examples()
        self.validation_rules["products"] = self._build_product_validation_rules()

    def get_product_capabilities(self) -> Dict[str, Any]:
        """Get comprehensive product schema capabilities."""
        return self.capabilities["products"]

    def get_product_examples(self, example_type: Optional[str] = None) -> Dict[str, Any]:
        """Get product creation examples and templates."""
        return self.get_examples("products", example_type)

    def validate_product_configuration(
        self, config_data: Dict[str, Any], dry_run: bool = True
    ) -> Dict[str, Any]:
        """Validate product configuration with detailed feedback."""
        logger.info(f"Validating product configuration (dry_run: {dry_run})")

        # Use the existing ProductValidationEngine for comprehensive validation
        try:
            if dry_run:
                # For dry run, just validate structure without API submission
                validated_data = ProductValidationEngine.validate_complete_product(config_data)
                return {
                    "valid": True,
                    "errors": [],
                    "warnings": [],
                    "suggestions": [
                        {
                            "type": "success",
                            "message": "Product configuration is valid and ready for creation",
                            "next_steps": [
                                "Use 'create' action to create this product",
                                "Consider adding source_ids for data source integration",
                                "Review tier structure for optimal pricing",
                            ],
                        }
                    ],
                    "dry_run": True,
                    "validated_data": validated_data,
                }
            else:
                # For actual creation, use API validation
                validated_data = ProductValidationEngine.validate_product_for_api(config_data)
                return {
                    "valid": True,
                    "errors": [],
                    "warnings": [],
                    "suggestions": [],
                    "dry_run": False,
                    "validated_data": validated_data,
                }
        except Exception as e:
            # Convert validation errors to structured format
            error_details = {
                "field": getattr(e, "field", "unknown"),
                "error": str(e),
                "suggestion": getattr(
                    e, "suggestion", "Please check the field value and try again"
                ),
            }

            return {
                "valid": False,
                "errors": [error_details],
                "warnings": [],
                "suggestions": [
                    {
                        "type": "fix",
                        "message": "Fix the validation errors above",
                        "next_steps": [
                            "Check field values against schema",
                            "Use get_examples for working templates",
                        ],
                    }
                ],
                "dry_run": dry_run,
            }

    def _build_product_capabilities(self) -> Dict[str, Any]:
        """Build comprehensive product capabilities schema."""
        return {
            "plan_types": [plan_type.value for plan_type in PlanType],
            "currencies": [currency.value for currency in Currency],
            "billing_periods": [period.value for period in BillingPeriod],
            "trial_periods": [trial.value for trial in TrialPeriod],
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
                        "published",
                        "payment_source",
                    ],
                    "plan_schema": {
                        "required": ["type", "name", "currency"],
                        "optional": [
                            "period",
                            "trial_period",
                            "tiers",
                            "rating_aggregations",
                            "setup_fees",
                        ],
                        "tier_schema": {
                            "required": ["name", "starting_from", "unit_amount"],
                            "optional": ["up_to", "flat_amount"],
                        },
                        "rating_aggregation_schema": {
                            "required": ["element_definition_id", "aggregation_type"],
                            "optional": ["tiers", "graduated"],
                        },
                    },
                }
            },
            "field_constraints": {
                "name": {"min_length": 2, "max_length": 255},
                "version": {"pattern": r"^\d+\.\d+\.\d+$", "example": "1.0.0"},
                "unit_amount": {"type": "decimal", "min": 0},
                "starting_from": {"type": "decimal", "min": 0},
                "up_to": {
                    "type": "decimal",
                    "min": 0,
                    "note": "Must be greater than starting_from, null for final tier",
                },
            },
            "business_rules": {
                "tier_structure": [
                    "Final tier must have up_to: null (unlimited)",
                    "All non-final tiers must have up_to values",
                    "Single-tier products: only tier has up_to: null",
                    "Multi-tier products: all tiers except last must have up_to values",
                ],
                "subscription_plans": [
                    "Must specify billing period",
                    "Can optionally include trial period",
                ],
                "pricing_validation": [
                    "At least one tier required (in plan.tiers or rating_aggregations)",
                    "Tier ranges cannot overlap",
                    "Unit amounts must be non-negative",
                ],
                "ui_fields": [
                    "Tags: Array of strings for product categorization (WORKING)",
                    "Setup Fees: Array with type SUBSCRIPTION or ORGANIZATION (API fix pending)",
                    "Trial Period: trialPeriod and trialPeriodCount for free trials (WORKING)",
                    "Trial Notifications: notifyClientTrialAboutToExpire flag (WORKING)",
                ],
                "setup_fee_types": [
                    "SUBSCRIPTION: Charged for each new subscription (per subscription billing)",
                    "ORGANIZATION: Charged once per customer organization (multiple subscriptions = one fee)",
                ],
            },
        }

    def _build_product_examples(self) -> List[Dict[str, Any]]:
        """Build comprehensive product examples and templates."""
        return [
            {
                "name": "Simple API Service Product",
                "type": "simple_charge",
                "description": "Basic API service with fixed pricing",
                "use_case": "Simple API monetization with per-request pricing",
                "template": {
                    "name": "API Service Basic",
                    "description": "Basic API service with per-request billing",
                    "version": "1.0.0",
                    "plan": {
                        "type": "SUBSCRIPTION",
                        "name": "API Service Plan",
                        "currency": "USD",
                        "period": "MONTH",
                        "tiers": [{"name": "Standard Tier", "up_to": None, "unit_amount": "0.01"}],
                    },
                    "source_ids": [],
                    "tags": ["api", "basic"],
                },
            },
            {
                "name": "Monthly Subscription Product",
                "type": "subscription",
                "description": "Monthly subscription with free tier",
                "use_case": "SaaS subscription with usage-based pricing",
                "template": {
                    "name": "Premium API Subscription",
                    "description": "Monthly subscription with generous free tier",
                    "version": "1.0.0",
                    "plan": {
                        "type": "SUBSCRIPTION",
                        "name": "Premium Plan",
                        "currency": "USD",
                        "period": "MONTHLY",
                        "tiers": [
                            {
                                "name": "Free Tier",
                                "starting_from": 0,
                                "up_to": "1000",
                                "unit_amount": "0.00",
                            },
                            {
                                "name": "Paid Tier",
                                "starting_from": 1000,
                                "up_to": None,
                                "unit_amount": "0.02",
                            },
                        ],
                    },
                    "source_ids": [],
                    "tags": ["subscription", "freemium"],
                },
            },
            {
                "name": "Usage-Based Product with Rating Aggregations",
                "type": "usage_based",
                "description": "Complex usage-based pricing with metering",
                "use_case": "Advanced API monetization with multiple pricing tiers",
                "template": {
                    "name": "Enterprise API Service",
                    "description": "Enterprise-grade API with usage-based billing",
                    "version": "1.0.0",
                    "plan": {
                        "type": "CHARGE",
                        "name": "Enterprise Plan",
                        "currency": "USD",
                        "rating_aggregations": [
                            {
                                "element_definition_id": "api_calls",
                                "aggregation_type": "SUM",
                                "graduated": True,
                                "tiers": [
                                    {
                                        "name": "Starter",
                                        "starting_from": 0,
                                        "up_to": "10000",
                                        "unit_amount": "0.001",
                                    },
                                    {
                                        "name": "Professional",
                                        "starting_from": 10000,
                                        "up_to": "100000",
                                        "unit_amount": "0.0008",
                                    },
                                    {
                                        "name": "Enterprise",
                                        "starting_from": 100000,
                                        "up_to": None,
                                        "unit_amount": "0.0005",
                                    },
                                ],
                            }
                        ],
                    },
                    "source_ids": [],
                    "tags": ["enterprise", "usage-based", "graduated"],
                },
            },
        ]

    def _build_product_validation_rules(self) -> Dict[str, Any]:
        """Build product-specific validation rules."""
        return {
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
            ],
            "plan_validation": {
                "required": ["type", "name", "currency"],
                "conditional_required": {
                    "SUBSCRIPTION": ["period"]  # Subscription plans require period
                },
                "tier_validation": True,
                "rating_aggregation_validation": True,
            },
            "business_rules": [
                "At least one pricing tier required",
                "Final tier must have up_to: null",
                "Non-final tiers must have up_to values",
                "Tier ranges cannot overlap",
                "Unit amounts must be non-negative",
            ],
        }


class SourceSchemaDiscovery(SchemaDiscoveryEngine):
    """Source-specific schema discovery and validation capabilities."""

    def __init__(self):
        """Initialize the source schema discovery engine."""
        super().__init__()
        # Add source-specific capabilities to the base capabilities
        self.capabilities["sources"] = self._build_source_capabilities()
        self.examples["sources"] = self._build_source_examples()
        self.validation_rules["sources"] = self._build_source_validation_rules()

    def get_source_capabilities(self) -> Dict[str, Any]:
        """Get comprehensive source schema capabilities."""
        return self.capabilities["sources"]

    def get_source_examples(self, example_type: Optional[str] = None) -> Dict[str, Any]:
        """Get source creation examples and templates."""
        return self.get_examples("sources", example_type)

    def validate_source_configuration(
        self, config_data: Dict[str, Any], dry_run: bool = True
    ) -> Dict[str, Any]:
        """Validate source configuration with detailed feedback."""
        logger.info(f"Validating source configuration (dry_run: {dry_run})")

        # Basic validation for source configuration
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "suggestions": [],
            "dry_run": dry_run,
        }

        # Check required fields
        required_fields = ["name", "type"]
        for field in required_fields:
            if field not in config_data:
                validation_result["valid"] = False
                validation_result["errors"].append(
                    {
                        "field": field,
                        "error": f"Required field '{field}' is missing",
                        "suggestion": f"Add '{field}' field to your configuration",
                    }
                )

        # Validate source type
        if "type" in config_data:
            valid_types = [source_type.value for source_type in SourceType]
            if config_data["type"] not in valid_types:
                validation_result["valid"] = False
                validation_result["errors"].append(
                    {
                        "field": "type",
                        "error": f"Invalid source type: {config_data['type']}",
                        "valid_values": valid_types,
                        "suggestion": f"Use one of: {', '.join(valid_types)}",
                    }
                )

        # Note: Status field validation removed - API doesn't support status field for sources

        # Add suggestions for improvement
        if validation_result["valid"]:
            validation_result["suggestions"].append(
                {
                    "type": "success",
                    "message": "Source configuration is valid and ready for creation",
                    "next_steps": [
                        "Use 'create' action to create this source",
                        "Consider adding configuration details for your source type",
                        "Review connection parameters for optimal performance",
                    ],
                }
            )

        return validation_result

    def _build_source_capabilities(self) -> Dict[str, Any]:
        """Build source capabilities schema based on actual API verification."""
        # VERIFIED: Only these source types work with the actual Revenium API
        verified_source_types = ["API", "STREAM", "AI"]

        return {
            "source_types": verified_source_types,
            # Note: source_statuses removed - API doesn't support status field
            "schema": {
                "source_data": {
                    # VERIFIED: Required fields from actual API implementation
                    "required": ["name", "description", "version", "type"],
                    # VERIFIED: Optional fields from actual source management implementation
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
                    ],
                }
            },
            "field_constraints": {
                "name": {"min_length": 1, "max_length": 255},
                "description": {"min_length": 1, "max_length": 1000},
                "version": {"pattern": r"^\d+\.\d+\.\d+$"},
                "type": {"enum": verified_source_types},
            },
            "business_rules": [
                "Source name must be unique within the team",
                "Type must be one of the verified types: API, STREAM, AI",
                "Version should follow semantic versioning (e.g., 1.0.0)",
                "Description should clearly explain source purpose",
                "Optional fields enhance source discoverability and management",
            ],
            "api_compatibility": {
                "verified_against": "Revenium API v2",
                "verified_source_types": verified_source_types,
                "note": "Only these source types are confirmed to work with the actual API",
            },
        }

    def _build_source_examples(self) -> List[Dict[str, Any]]:
        """Build source examples based on verified API capabilities."""
        return [
            {
                "name": "REST API Source",
                "type": "api_source",
                "description": "Connect to a REST API endpoint for data monitoring",
                "use_case": "Monitor external API usage and performance",
                "template": {
                    "name": "External API Service",
                    "description": "REST API source for monitoring external data integration",
                    "version": "1.0.0",
                    "type": "API",
                    "sourceType": "API",
                    "syncedWithApiGateway": False,
                    "autoDiscoveryEnabled": False,
                    "tags": ["external", "api"],
                    "sourceClassifications": ["third-party"],
                    "metadata": {
                        "endpoint": "https://api.example.com/v1/data",
                        "data_format": "json",
                        "monitoring_purpose": "usage_tracking",
                    },
                },
            },
            {
                "name": "Stream Source",
                "type": "stream_source",
                "description": "Connect to a real-time data stream for monitoring",
                "use_case": "Monitor real-time data streams and event flows",
                "template": {
                    "name": "Event Data Stream",
                    "description": "Real-time stream source for event monitoring",
                    "version": "1.0.0",
                    "type": "STREAM",
                    "sourceType": "STREAM",
                    "syncedWithApiGateway": False,
                    "autoDiscoveryEnabled": True,
                    "tags": ["streaming", "real-time"],
                    "sourceClassifications": ["internal"],
                    "metadata": {
                        "stream_type": "websocket",
                        "data_format": "json",
                        "monitoring_purpose": "real_time_analytics",
                    },
                },
            },
            {
                "name": "AI Source",
                "type": "ai_source",
                "description": "Connect to AI services for usage monitoring",
                "use_case": "Monitor AI model usage, costs, and performance",
                "template": {
                    "name": "AI Model Monitor",
                    "description": "AI source for monitoring model usage and costs",
                    "version": "1.0.0",
                    "type": "AI",
                    "sourceType": "AI",
                    "syncedWithApiGateway": False,
                    "autoDiscoveryEnabled": False,
                    "tags": ["ai", "monitoring"],
                    "sourceClassifications": ["ai-service"],
                    "metadata": {
                        "model_type": "language_model",
                        "provider": "openai",
                        "monitoring_purpose": "cost_and_usage_tracking",
                    },
                },
            },
        ]

    def _build_source_validation_rules(self) -> Dict[str, Any]:
        """Build source validation rules based on actual API requirements."""
        return {
            # VERIFIED: Required fields from actual API implementation
            "required": ["name", "description", "version", "type"],
            # VERIFIED: Optional fields from actual source management implementation
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
            ],
            "field_validation": {
                "name": {
                    "type": "string",
                    "min_length": 1,
                    "max_length": 255,
                    "description": "Source name must be unique and descriptive",
                },
                "description": {
                    "type": "string",
                    "min_length": 1,
                    "max_length": 1000,
                    "description": "Clear description of the source purpose",
                },
                "version": {
                    "type": "string",
                    "pattern": r"^\d+\.\d+\.\d+$",
                    "description": "Semantic version format (e.g., 1.0.0)",
                },
                "type": {
                    "type": "string",
                    "enum": ["API", "STREAM", "AI"],
                    "description": "Must be one of the verified source types",
                },
            },
            "business_rules": [
                "Source name must be unique within the team",
                "Type must be one of the verified types: API, STREAM, AI",
                "Version should follow semantic versioning",
                "Description should clearly explain source purpose",
                "Optional fields enhance source discoverability and management",
            ],
        }


class SubscriptionSchemaDiscovery(SchemaDiscoveryEngine):
    """Subscription-specific schema discovery and validation capabilities."""

    def __init__(self):
        """Initialize the subscription schema discovery engine."""
        super().__init__()
        # Add subscription-specific capabilities to the base capabilities
        self.capabilities["subscriptions"] = self._build_subscription_capabilities()
        self.examples["subscriptions"] = self._build_subscription_examples()
        self.validation_rules["subscriptions"] = self._build_subscription_validation_rules()

    def get_subscription_capabilities(self) -> Dict[str, Any]:
        """Get comprehensive subscription schema capabilities."""
        return self.capabilities["subscriptions"]

    def get_subscription_examples(self, example_type: Optional[str] = None) -> Dict[str, Any]:
        """Get subscription creation examples and templates."""
        return self.get_examples("subscriptions", example_type)

    def validate_subscription_configuration(
        self, config_data: Dict[str, Any], dry_run: bool = True, client=None
    ) -> Dict[str, Any]:
        """Validate subscription configuration with detailed feedback."""
        logger.info(f"Validating subscription configuration (dry_run: {dry_run})")

        # Basic validation for subscription configuration
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "suggestions": [],
            "dry_run": dry_run,
        }

        # Check required fields
        required_fields = ["product_id", "name"]
        for field in required_fields:
            if field not in config_data:
                validation_result["valid"] = False
                validation_result["errors"].append(
                    {
                        "field": field,
                        "error": f"Required field '{field}' is missing",
                        "suggestion": f"Add '{field}' field to your configuration",
                    }
                )

        # Enhanced validation: Check if product exists (if client is provided)
        if client and "product_id" in config_data:
            try:
                import asyncio

                # Check if we're in an async context
                try:
                    loop = asyncio.get_running_loop()
                    # We're in an async context, but this is a sync method
                    # Add a warning instead of trying to make async call
                    validation_result["warnings"].append(
                        f"Product existence validation skipped - use async validation for complete checking"
                    )
                except RuntimeError:
                    # Not in async context, can't validate product existence
                    validation_result["warnings"].append(
                        f"Product existence validation requires async context"
                    )
            except Exception as e:
                logger.debug(f"Could not validate product existence: {e}")
                validation_result["warnings"].append(f"Product existence validation unavailable")

        # REMOVED: Subscription status validation - status field NOT FOUND in actual Revenium API responses
        # The API does not return or accept a status field for subscription objects

        # Validate date fields if provided
        date_fields = ["start_date", "end_date"]
        for field in date_fields:
            if field in config_data and config_data[field]:
                # Basic date format validation (could be enhanced)
                if not isinstance(config_data[field], str):
                    validation_result["warnings"].append(
                        f"Date field '{field}' should be a string in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"
                    )

        # Business rule validation
        if "start_date" in config_data and "end_date" in config_data:
            if config_data["start_date"] and config_data["end_date"]:
                # Note: This is a simplified check - in real implementation would parse dates
                validation_result["suggestions"].append(
                    {
                        "type": "info",
                        "message": "Ensure end_date is after start_date",
                        "next_steps": ["Validate date order before creation"],
                    }
                )

        # Add suggestions for improvement
        if validation_result["valid"]:
            validation_result["suggestions"].append(
                {
                    "type": "success",
                    "message": "Subscription configuration is valid and ready for creation",
                    "next_steps": [
                        "Use 'create' action to create this subscription",
                        "Ensure the product_id exists and is active",
                        "Consider setting start_date for future subscriptions",
                    ],
                }
            )

        return validation_result

    def _build_subscription_capabilities(self) -> Dict[str, Any]:
        """Build comprehensive subscription capabilities schema."""
        return {
            # REMOVED: "subscription_statuses" - NOT FOUND in actual Revenium API responses
            # The API does not return a status field for subscription objects
            "billing_periods": [period.value for period in BillingPeriod],
            "trial_periods": [trial.value for trial in TrialPeriod],
            "currencies": [currency.value for currency in Currency],
            "schema": {
                "subscription_data": {
                    "required": ["product_id", "name"],
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
                    # REMOVED: "status" - NOT FOUND in actual API
                    "date_fields": {
                        "start_date": "Subscription start date (ISO format)",
                        "end_date": "Subscription end date (ISO format)",
                        "trial_end_date": "Trial period end date (ISO format)",
                    },
                    "billing_info": {
                        "billing_address": {
                            "street": "Street address",
                            "city": "City",
                            "state": "State/Province",
                            "postal_code": "Postal/ZIP code",
                            "country": "Country code (ISO 3166-1)",
                        },
                        "payment_method": {
                            "type": "Payment method type (card, bank_transfer, etc.)",
                            "details": "Payment method specific details",
                        },
                    },
                }
            },
            "field_constraints": {
                "name": {"min_length": 1, "max_length": 255},
                "description": {"max_length": 1000},
                "product_id": {"format": "uuid", "required": True},
                "dates": {"format": "ISO 8601 (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"},
            },
            # REMOVED: lifecycle_states - status field NOT FOUND in actual API
            # The API manages subscription lifecycle through other fields like start/end dates
            "business_rules": [
                "Product must exist and be active before creating subscription",
                "Start date cannot be in the past (unless explicitly allowed)",
                "End date must be after start date if both are specified",
                "Trial period is optional and depends on product configuration",
                "Billing address is required for paid subscriptions",
                "Payment method is required for non-trial subscriptions",
                "Subscription name must be unique within the organization",
            ],
        }

    def _build_subscription_examples(self) -> List[Dict[str, Any]]:
        """Build comprehensive subscription examples and templates."""
        return [
            {
                "name": "Basic Monthly Subscription",
                "example_type": "monthly_billing",  # This is example metadata, not an API field
                "description": "Simple monthly subscription for a SaaS product",
                "use_case": "Standard monthly billing for software services",
                "template": {
                    "product_id": "prod_12345678-1234-1234-1234-123456789012",
                    "clientEmailAddress": "user@company.com",
                    "name": "Premium Plan Subscription",
                    "description": "Monthly subscription to Premium Plan",
                    # REMOVED: "status": "active" - NOT FOUND in actual API
                    "start_date": "2024-01-01T00:00:00Z",
                    "billing_address": {
                        "street": "123 Business St",
                        "city": "San Francisco",
                        "state": "CA",
                        "postal_code": "94105",
                        "country": "US",
                    },
                    "payment_method": {
                        "type": "card",
                        "details": {
                            "last_four": "4242",
                            "brand": "visa",
                            "exp_month": 12,
                            "exp_year": 2025,
                        },
                    },
                    "metadata": {"customer_tier": "premium", "sales_rep": "john.doe@company.com"},
                },
            },
            {
                "name": "Trial Subscription",
                "example_type": "trial_period",  # This is example metadata, not an API field
                "description": "Subscription with trial period",
                "use_case": "Free trial before paid subscription",
                "template": {
                    "product_id": "prod_12345678-1234-1234-1234-123456789012",
                    "clientEmailAddress": "trial@company.com",
                    "name": "Enterprise Trial",
                    "description": "30-day trial of Enterprise features",
                    # REMOVED: "status": "active" - NOT FOUND in actual API
                    "start_date": "2024-01-01T00:00:00Z",
                    "trial_end_date": "2024-01-31T23:59:59Z",
                    "billing_address": {
                        "street": "456 Enterprise Ave",
                        "city": "New York",
                        "state": "NY",
                        "postal_code": "10001",
                        "country": "US",
                    },
                    "metadata": {
                        "trial_type": "enterprise",
                        "conversion_goal": "full_subscription",
                    },
                },
            },
            {
                "name": "Annual Subscription",
                "example_type": "annual_billing",  # This is example metadata, not an API field
                "description": "Yearly subscription with discount",
                "use_case": "Annual billing for cost savings",
                "template": {
                    "product_id": "prod_12345678-1234-1234-1234-123456789012",
                    "clientEmailAddress": "billing@company.com",
                    "name": "Annual Premium Plan",
                    "description": "Yearly subscription with 20% discount",
                    # REMOVED: "status": "active" - NOT FOUND in actual API
                    "start_date": "2024-01-01T00:00:00Z",
                    "end_date": "2024-12-31T23:59:59Z",
                    "billing_address": {
                        "street": "789 Corporate Blvd",
                        "city": "Austin",
                        "state": "TX",
                        "postal_code": "73301",
                        "country": "US",
                    },
                    "payment_method": {
                        "type": "bank_transfer",
                        "details": {
                            "account_type": "business",
                            "routing_number": "021000021",
                            "account_last_four": "1234",
                        },
                    },
                    "metadata": {
                        "billing_cycle": "annual",
                        "discount_applied": "20_percent_annual",
                    },
                },
            },
            {
                "name": "Enterprise Subscription",
                "example_type": "enterprise_custom",  # This is example metadata, not an API field
                "description": "Custom enterprise subscription with special terms",
                "use_case": "Large organization with custom requirements",
                "template": {
                    "product_id": "prod_12345678-1234-1234-1234-123456789012",
                    "clientEmailAddress": "enterprise@company.com",
                    "name": "Enterprise Custom Plan",
                    "description": "Custom enterprise subscription with negotiated terms",
                    # REMOVED: "status": "active" - NOT FOUND in actual API
                    "start_date": "2024-01-01T00:00:00Z",
                    "end_date": "2026-12-31T23:59:59Z",
                    "billing_address": {
                        "street": "1000 Enterprise Way",
                        "city": "Seattle",
                        "state": "WA",
                        "postal_code": "98101",
                        "country": "US",
                    },
                    "payment_method": {
                        "type": "invoice",
                        "details": {
                            "payment_terms": "net_30",
                            "po_required": True,
                            "billing_contact": "billing@enterprise.com",
                        },
                    },
                    "metadata": {
                        "contract_type": "enterprise",
                        "account_manager": "enterprise.sales@company.com",
                        "custom_terms": True,
                        "volume_discount": "enterprise_tier",
                    },
                },
            },
        ]

    def _build_subscription_validation_rules(self) -> Dict[str, Any]:
        """Build subscription-specific validation rules."""
        return {
            "required": ["product_id", "clientEmailAddress", "name"],
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
            # REMOVED: "status" - NOT FOUND in actual API
            "field_validation": {
                "product_id": {
                    "type": "string",
                    "format": "uuid",
                    "description": "Must be a valid product ID that exists in the system",
                },
                "clientEmailAddress": {
                    "type": "string",
                    "format": "email",
                    "description": "Email address of the client for billing and subscription management",
                },
                "name": {
                    "type": "string",
                    "min_length": 1,
                    "max_length": 255,
                    "description": "Subscription name must be unique within organization",
                },
                # REMOVED: status validation - NOT FOUND in actual API
                "dates": {
                    "format": "ISO 8601",
                    "examples": ["2024-01-01", "2024-01-01T00:00:00Z"],
                    "validation": "end_date must be after start_date",
                },
            },
            # REMOVED: conditional_validation with status conditions - status field NOT FOUND in actual API
            # The API manages subscription lifecycle through other fields like start/end dates and trial_end_date
            "business_rules": [
                "Product must exist and be active",
                "Subscription name must be unique within organization",
                "Start date cannot be more than 1 year in the future",
                "End date must be after start date",
                "Trial period cannot exceed product's maximum trial duration",
                "Billing address required for paid subscriptions",
                "Payment method required for non-trial subscriptions",
            ],
        }


class CustomerSchemaDiscovery(SchemaDiscoveryEngine):
    """Customer-specific schema discovery and validation capabilities."""

    def __init__(self):
        """Initialize the customer schema discovery engine."""
        super().__init__()
        # Add customer-specific capabilities to the base capabilities
        self.capabilities["customers"] = self._build_customer_capabilities()
        self.examples["customers"] = self._build_customer_examples()
        self.validation_rules["customers"] = self._build_customer_validation_rules()

    def get_customer_capabilities(self) -> Dict[str, Any]:
        """Get comprehensive customer schema capabilities."""
        return self.capabilities["customers"]

    def get_customer_examples(self, example_type: Optional[str] = None) -> Dict[str, Any]:
        """Get customer creation examples and templates."""
        return self.get_examples("customers", example_type)

    def validate_customer_configuration(
        self, config_data: Dict[str, Any], resource_type: str = "users", dry_run: bool = True
    ) -> Dict[str, Any]:
        """Validate customer configuration with detailed feedback."""
        logger.info(f"Validating {resource_type} configuration (dry_run: {dry_run})")

        # Basic validation for customer configuration
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "suggestions": [],
            "dry_run": dry_run,
            "resource_type": resource_type,
        }

        # Resource-specific validation (VERIFIED API CAPABILITIES ONLY)
        if resource_type == "users":
            required_fields = ["email"]
            # REMOVED: status_enum = UserStatus - NOT FOUND in actual API
        elif resource_type == "subscribers":
            required_fields = ["email"]
            # REMOVED: status_enum = SubscriberStatus - NOT VERIFIED in actual API
        elif resource_type == "organizations":
            required_fields = ["name"]
            # REMOVED: status_enum = OrganizationStatus - NOT FOUND in actual API
        elif resource_type == "teams":
            required_fields = ["name", "organization_id"]
            # REMOVED: status_enum = TeamStatus - NOT VERIFIED in actual API
        else:
            validation_result["valid"] = False
            validation_result["errors"].append(
                {
                    "field": "resource_type",
                    "error": f"Unknown resource type: {resource_type}",
                    "valid_values": ["users", "subscribers", "organizations", "teams"],
                    "suggestion": "Use one of the supported resource types",
                }
            )
            return validation_result

        # Check required fields
        for field in required_fields:
            if field not in config_data:
                validation_result["valid"] = False
                validation_result["errors"].append(
                    {
                        "field": field,
                        "error": f"Required field '{field}' is missing",
                        "suggestion": f"Add '{field}' field to your configuration",
                    }
                )

        # REMOVED: Status validation - status enums NOT FOUND in actual Revenium API responses
        # REMOVED: Organization type validation - only CONSUMER type found in actual API

        # Resource-specific validation (VERIFIED API CAPABILITIES ONLY)
        if resource_type == "organizations" and "type" in config_data:
            # Only CONSUMER type confirmed to exist in actual API
            valid_types = ["CONSUMER"]
            if config_data["type"] not in valid_types:
                validation_result["valid"] = False
                validation_result["errors"].append(
                    {
                        "field": "type",
                        "error": f"Invalid organization type: {config_data['type']}",
                        "valid_values": valid_types,
                        "suggestion": f"Use one of: {', '.join(valid_types)} (only CONSUMER type confirmed in API)",
                    }
                )

        # Email validation for users and subscribers
        if resource_type in ["users", "subscribers"] and "email" in config_data:
            email = config_data["email"]
            if "@" not in email or "." not in email:
                validation_result["warnings"].append(
                    f"Email '{email}' may not be valid - ensure it follows standard email format"
                )

        # Add suggestions for improvement
        if validation_result["valid"]:
            validation_result["suggestions"].append(
                {
                    "type": "success",
                    "message": f"{resource_type.title()} configuration is valid and ready for creation",
                    "next_steps": [
                        f"Use 'create' action to create this {resource_type[:-1]}",
                        f"Consider adding optional fields for better {resource_type} management",
                        f"Review {resource_type} permissions and access controls",
                    ],
                }
            )

        return validation_result

    def _build_customer_capabilities(self) -> Dict[str, Any]:
        """Build comprehensive customer capabilities schema."""
        return {
            "resource_types": ["users", "subscribers", "organizations", "teams", "relationships"],
            "user_roles": [
                role.value for role in UserRole
            ],  # CONFIRMED: ROLE_TENANT_ADMIN, ROLE_API_CONSUMER exist
            # REMOVED: user_statuses - NOT FOUND in actual API responses
            # REMOVED: subscriber_statuses - NOT VERIFIED in actual API
            # REMOVED: organization_statuses - NOT FOUND in actual API responses
            # REMOVED: team_statuses - NOT VERIFIED in actual API
            # REMOVED: team_roles - NOT FOUND in actual API responses
            "organization_types": ["CONSUMER"],  # CONFIRMED: Only CONSUMER type found in actual API
            "schemas": {
                "users": {
                    "required": ["email"],
                    "optional": [
                        "firstName",
                        "lastName",
                        "full_name",
                        "status",
                        "organization_id",
                        "team_id",
                        "roles",
                        "permissions",
                        "metadata",
                    ],
                    "field_types": {
                        "email": "string (email format)",
                        "firstName": "string",
                        "lastName": "string",
                        "full_name": "string",
                        # REMOVED: "status": "enum (UserStatus)" - NOT FOUND in actual API
                        "organization_id": "string (UUID)",
                        "team_id": "string (UUID)",
                        "roles": "array of strings (ROLE_API_CONSUMER only)",
                        "permissions": "array of strings",
                        "metadata": "object",
                    },
                },
                "subscribers": {
                    "required": ["email"],
                    "optional": [
                        "user_id",
                        "name",
                        "status",
                        "subscription_ids",
                        "organization_id",
                        "billing_address",
                        "payment_method",
                        "trial_end_date",
                        "metadata",
                    ],
                    "field_types": {
                        "email": "string (email format)",
                        "user_id": "string (UUID)",
                        "name": "string",
                        # REMOVED: "status": "enum (SubscriberStatus)" - NOT VERIFIED in actual API
                        "subscription_ids": "array of strings (UUIDs)",
                        "organization_id": "string (UUID)",
                        "billing_address": "object",
                        "payment_method": "object",
                        "trial_end_date": "string (ISO date)",
                        "metadata": "object",
                    },
                },
                "organizations": {
                    "required": ["name"],
                    "optional": [
                        "display_name",
                        "description",
                        "type",
                        "status",
                        "parent_organization_id",
                        "website",
                        "industry",
                        "size",
                        "address",
                        "contact_info",
                        "billing_info",
                        "tags",
                        "metadata",
                    ],
                    "field_types": {
                        "name": "string",
                        "display_name": "string",
                        "description": "string",
                        "type": "enum (only CONSUMER confirmed in API)",
                        # REMOVED: "status": "enum (OrganizationStatus)" - NOT FOUND in actual API
                        "parent_organization_id": "string (UUID)",
                        "website": "string (URL)",
                        "industry": "string",
                        "size": "string (e.g., '1-10', '11-50')",
                        "address": "object",
                        "contact_info": "object",
                        "billing_info": "object",
                        "tags": "array of strings",
                        "metadata": "object",
                    },
                },
                "teams": {
                    "required": ["name", "organization_id"],
                    "optional": [
                        "display_name",
                        "description",
                        "status",
                        "parent_team_id",
                        "owner_id",
                        "members",
                        "permissions",
                        "settings",
                        "tags",
                        "metadata",
                    ],
                    "field_types": {
                        "name": "string",
                        "display_name": "string",
                        "description": "string",
                        # REMOVED: "status": "enum (TeamStatus)" - NOT VERIFIED in actual API
                        "organization_id": "string (UUID)",
                        "parent_team_id": "string (UUID)",
                        "owner_id": "string (UUID)",
                        "members": "array of TeamMember objects",
                        "permissions": "array of strings",
                        "settings": "object",
                        "tags": "array of strings",
                        "metadata": "object",
                    },
                },
            },
            "field_constraints": {
                "email": {"format": "email", "required": True},
                "name": {"min_length": 1, "max_length": 255},
                "description": {"max_length": 1000},
                "website": {"format": "url"},
                "organization_id": {"format": "uuid", "required_for": ["teams"]},
                "user_id": {"format": "uuid"},
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

    def _build_customer_examples(self) -> List[Dict[str, Any]]:
        """Build comprehensive customer examples and templates."""
        return [
            {
                "name": "Basic User Account",
                "type": "user_basic",
                "description": "Simple user account creation",
                "use_case": "Create a basic user account for platform access",
                "resource_type": "users",
                "template": {
                    "email": "john.doe@company.com",
                    "firstName": "John",
                    "lastName": "Doe",
                    "full_name": "John Doe",
                    # REMOVED: "status": "active" - NOT FOUND in actual API
                    "roles": ["ROLE_API_CONSUMER"],
                    "metadata": {"department": "engineering", "hire_date": "2024-01-15"},
                },
            },
            {
                "name": "Organization Admin User",
                "type": "user_admin",
                "description": "User with administrative privileges",
                "use_case": "Create an admin user for organization management",
                "resource_type": "users",
                "template": {
                    "email": "admin@company.com",
                    "firstName": "Jane",
                    "lastName": "Smith",
                    "full_name": "Jane Smith",
                    # REMOVED: "status": "active" - NOT FOUND in actual API
                    "organization_id": "org_12345678-1234-1234-1234-123456789012",
                    "roles": ["ROLE_TENANT_ADMIN"],
                    "permissions": [
                        "user_management",
                        "billing_access",
                        "organization_settings",
                        "team_management",
                    ],
                    "metadata": {"department": "operations", "access_level": "full"},
                },
            },
            {
                "name": "Active Subscriber",
                "type": "subscriber_active",
                "description": "Active subscription holder with billing info",
                "use_case": "Create a subscriber with active subscription",
                "resource_type": "subscribers",
                "template": {
                    "user_id": "user_12345678-1234-1234-1234-123456789012",
                    "email": "subscriber@company.com",
                    "name": "Premium Subscriber",
                    # REMOVED: "status": "active" - NOT VERIFIED in actual API
                    "subscription_ids": ["sub_12345678-1234-1234-1234-123456789012"],
                    "organization_id": "org_12345678-1234-1234-1234-123456789012",
                    "billing_address": {
                        "street": "123 Business St",
                        "city": "San Francisco",
                        "state": "CA",
                        "postal_code": "94105",
                        "country": "US",
                    },
                    "payment_method": {"type": "card", "last_four": "4242", "brand": "visa"},
                    "metadata": {"subscription_tier": "premium", "billing_cycle": "monthly"},
                },
            },
            {
                "name": "Trial Subscriber",
                "type": "subscriber_trial",
                "description": "Subscriber in trial period",
                "use_case": "Create a trial subscriber without payment method",
                "resource_type": "subscribers",
                "template": {
                    "email": "trial@startup.com",
                    "name": "Trial User",
                    # REMOVED: "status": "trial" - NOT VERIFIED in actual API
                    "trial_end_date": "2024-02-01T23:59:59Z",
                    "metadata": {"trial_type": "14_day_free", "conversion_target": "premium_plan"},
                },
            },
            {
                "name": "Business Organization",
                "type": "organization_business",
                "description": "Standard business organization",
                "use_case": "Create a business organization for customer management",
                "resource_type": "organizations",
                "template": {
                    "name": "Acme Corporation",
                    "externalId": "acme-corp-001",
                    "address1": "456 Corporate Blvd",
                    "city": "Austin",
                    "state": "TX",
                    "postalCode": "73301",
                    "country": "US",
                    "phoneNumber": "+1-555-123-4567",
                    "emailAddress": "contact@acme.com",
                    "url": "https://acme.com",
                    "currency": "USD",
                    "metadata": "Founded 2010, Technology company, 150 employees",
                    "types": ["CONSUMER"],
                },
            },
            {
                "name": "Enterprise Organization",
                "type": "organization_enterprise",
                "description": "Large enterprise organization with hierarchy",
                "use_case": "Create an enterprise organization with parent-child structure",
                "resource_type": "organizations",
                "template": {
                    "name": "Global Tech Solutions",
                    "externalId": "global-tech-001",
                    "address1": "1000 Enterprise Way",
                    "city": "Seattle",
                    "state": "WA",
                    "postalCode": "98101",
                    "country": "US",
                    "phoneNumber": "+1-555-987-6543",
                    "emailAddress": "enterprise@globaltech.com",
                    "url": "https://globaltech.com",
                    "currency": "USD",
                    "metadata": "Fortune 500 company, Technology sector, Global operations",
                    "types": ["CONSUMER"],
                },
            },
            {
                "name": "Development Team",
                "type": "team_development",
                "description": "Software development team",
                "use_case": "Create a development team within an organization",
                "resource_type": "teams",
                "template": {
                    "name": "Backend Development",
                    "display_name": "Backend Dev Team",
                    "description": "Responsible for backend services and APIs",
                    # REMOVED: "status": "active" - NOT VERIFIED in actual API
                    "organization_id": "org_12345678-1234-1234-1234-123456789012",
                    "owner_id": "user_12345678-1234-1234-1234-123456789012",
                    "members": [
                        {
                            "user_id": "user_12345678-1234-1234-1234-123456789012",
                            "email": "lead@company.com",
                            "name": "Tech Lead",
                            "role": "owner",
                        },
                        {
                            "user_id": "user_87654321-4321-4321-4321-210987654321",
                            "email": "dev1@company.com",
                            "name": "Senior Developer",
                            "role": "admin",
                        },
                    ],
                    "permissions": ["code_review", "deployment_staging", "database_read"],
                    "settings": {
                        "notification_preferences": "slack",
                        "code_review_required": True,
                        "deployment_approval": "lead_only",
                    },
                    "tags": ["development", "backend", "api"],
                    "metadata": {
                        "tech_stack": ["python", "postgresql", "redis"],
                        "sprint_length": "2_weeks",
                    },
                },
            },
        ]

    def _build_customer_validation_rules(self) -> Dict[str, Any]:
        """Build customer-specific validation rules."""
        return {
            "users": {
                "required": ["email"],
                "optional": [
                    "firstName",
                    "lastName",
                    "full_name",
                    "status",
                    "organization_id",
                    "team_id",
                    "roles",
                    "permissions",
                    "metadata",
                ],
                "field_validation": {
                    "email": {"format": "email", "unique": True},
                    # REMOVED: status enum - NOT FOUND in actual API
                    "organization_id": {"format": "uuid"},
                    "team_id": {"format": "uuid"},
                    "permissions": {"type": "array", "items": "string"},
                },
            },
            "subscribers": {
                "required": ["email"],
                "optional": [
                    "user_id",
                    "name",
                    "status",
                    "subscription_ids",
                    "organization_id",
                    "billing_address",
                    "payment_method",
                    "trial_end_date",
                    "metadata",
                ],
                "field_validation": {
                    "email": {"format": "email", "unique": True},
                    # REMOVED: status enum - NOT VERIFIED in actual API
                    "user_id": {"format": "uuid"},
                    "organization_id": {"format": "uuid"},
                    "subscription_ids": {"type": "array", "items": "uuid"},
                },
            },
            "organizations": {
                "required": ["name"],
                "optional": [
                    "display_name",
                    "description",
                    "type",
                    "status",
                    "parent_organization_id",
                    "website",
                    "industry",
                    "size",
                    "address",
                    "contact_info",
                    "billing_info",
                    "tags",
                    "metadata",
                ],
                "field_validation": {
                    "name": {"min_length": 1, "max_length": 255},
                    "type": {
                        "enum": ["CONSUMER"]
                    },  # CONFIRMED: Only CONSUMER type found in actual API
                    # REMOVED: status enum - NOT FOUND in actual API
                    "parent_organization_id": {"format": "uuid"},
                    "website": {"format": "url"},
                },
            },
            "teams": {
                "required": ["name", "organization_id"],
                "optional": [
                    "display_name",
                    "description",
                    "status",
                    "parent_team_id",
                    "owner_id",
                    "members",
                    "permissions",
                    "settings",
                    "tags",
                    "metadata",
                ],
                "field_validation": {
                    "name": {"min_length": 1, "max_length": 255},
                    # REMOVED: status enum - NOT VERIFIED in actual API
                    "organization_id": {"format": "uuid", "required": True},
                    "parent_team_id": {"format": "uuid"},
                    "owner_id": {"format": "uuid"},
                },
            },
            "business_rules": {
                "users": [
                    "Email must be unique across all users",
                    "Users can belong to one organization and multiple teams",
                    "Admin users require appropriate permissions",
                ],
                "subscribers": [
                    "Email must be unique across all subscribers",
                    "Active subscribers require billing information",
                    "Trial subscribers have limited access duration",
                ],
                "organizations": [
                    "Organization names should be unique within team",
                    "Parent organizations must exist before creating child organizations",
                    "Enterprise organizations can have complex hierarchies",
                ],
                "teams": [
                    "Team names must be unique within organization",
                    "Teams must belong to an existing organization",
                    "Team owners must be valid users within the organization",
                ],
            },
        }
