"""Enhanced Error Handling for Product Management.

This module provides comprehensive error handling with business context,
examples, and step-by-step guidance for fixing product creation issues.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


class ErrorSeverity(str, Enum):
    """Error severity levels."""

    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ProductError:
    """Enhanced error with business context and guidance."""

    code: str
    severity: ErrorSeverity
    field: Optional[str]
    message: str
    business_context: str
    fix_steps: List[str]
    examples: List[Dict[str, Any]]
    related_concepts: List[str]
    common_causes: List[str]


class ProductErrorHandler:
    """Enhanced error handler for product creation with business guidance."""

    def __init__(self):
        """Initialize the error handler."""
        self.error_patterns = self._build_error_patterns()
        self.business_concepts = self._build_business_concepts()
        self.fix_templates = self._build_fix_templates()

    def enhance_api_error(self, api_error: str, product_data: Dict[str, Any]) -> ProductError:
        """Enhance a raw API error with business context and guidance."""
        logger.info(f"Enhancing API error: {api_error}")

        # Try to match error patterns
        for pattern, error_info in self.error_patterns.items():
            if re.search(pattern, api_error, re.IGNORECASE):
                return self._create_enhanced_error(error_info, api_error, product_data)

        # Fallback for unrecognized errors
        return self._create_generic_error(api_error, product_data)

    def validate_product_business_logic(self, product_data: Dict[str, Any]) -> List[ProductError]:
        """Validate product against business logic rules."""
        errors = []

        # Validate product name business rules
        name_errors = self._validate_product_name_business(product_data.get("name"))
        errors.extend(name_errors)

        # Validate plan business logic
        if "plan" in product_data:
            plan_errors = self._validate_plan_business_logic(product_data["plan"])
            errors.extend(plan_errors)

        # Validate pricing consistency
        pricing_errors = self._validate_pricing_consistency(product_data)
        errors.extend(pricing_errors)

        return errors

    def get_field_guidance(self, field_name: str) -> Dict[str, Any]:
        """Get comprehensive guidance for a specific field."""
        field_guidance = {
            "name": {
                "description": "The product name that appears on customer invoices and billing statements",
                "business_importance": "This is what customers see - make it clear and professional",
                "best_practices": [
                    "Use descriptive names that explain the value",
                    "Avoid internal code names or abbreviations",
                    "Keep it under 50 characters for better display",
                    "Use title case for professional appearance",
                ],
                "examples": {
                    "good": ["API Pro Plan", "Premium Analytics", "Shipping Express"],
                    "bad": ["PROD_001", "Plan A", "Service"],
                },
                "common_mistakes": [
                    "Using technical internal names",
                    "Making names too generic",
                    "Including version numbers in the name",
                ],
            },
            "plan.type": {
                "description": "Determines how customers are billed for this product",
                "business_importance": "This fundamentally changes how revenue is recognized and collected",
                "options": {
                    "CHARGE": "One-time or usage-based billing - customer pays when they use",
                    "SUBSCRIPTION": "Recurring billing - customer pays regularly (monthly, yearly, etc.)",
                },
                "decision_guide": [
                    "Use CHARGE for: One-time services, usage-based APIs, per-transaction fees",
                    "Use SUBSCRIPTION for: SaaS platforms, memberships, regular services",
                ],
                "examples": {
                    "CHARGE": "API calls, shipping fees, consulting hours",
                    "SUBSCRIPTION": "Software licenses, gym memberships, hosting plans",
                },
            },
            "plan.tiers": {
                "description": "Pricing levels that determine how much customers pay",
                "business_importance": "Tiers enable volume discounts and complex pricing strategies",
                "structure": {
                    "starting_from": "The minimum quantity for this tier (inclusive)",
                    "up_to": "The maximum quantity for this tier (exclusive, null for final tier)",
                    "unit_amount": "Price per unit in this tier",
                },
                "examples": {
                    "simple": [{"starting_from": 0, "up_to": None, "unit_amount": "10.00"}],
                    "tiered": [
                        {"starting_from": 0, "up_to": 100, "unit_amount": "1.00"},
                        {"starting_from": 100, "up_to": None, "unit_amount": "0.80"},
                    ],
                },
                "common_mistakes": [
                    "Overlapping tier ranges",
                    "Forgetting to set final tier up_to as null",
                    "Inconsistent pricing progression",
                ],
            },
        }

        return field_guidance.get(
            field_name,
            {
                "description": f"Field '{field_name}' configuration",
                "guidance": "Refer to Revenium documentation for detailed field information",
            },
        )

    def suggest_fixes(self, errors: List[ProductError]) -> Dict[str, Any]:
        """Suggest comprehensive fixes for multiple errors."""
        if not errors:
            return {"status": "no_errors", "message": "Product configuration looks good!"}

        # Group errors by severity
        critical_errors = [e for e in errors if e.severity == ErrorSeverity.CRITICAL]
        regular_errors = [e for e in errors if e.severity == ErrorSeverity.ERROR]
        warnings = [e for e in errors if e.severity == ErrorSeverity.WARNING]

        # Create fix plan
        fix_plan = {
            "priority": "high" if critical_errors else "medium" if regular_errors else "low",
            "summary": f"Found {len(errors)} issues to address",
            "immediate_actions": [],
            "recommended_improvements": [],
            "learning_resources": [],
        }

        # Add immediate actions for critical/error issues
        for error in critical_errors + regular_errors:
            fix_plan["immediate_actions"].extend(error.fix_steps)

        # Add recommendations for warnings
        for warning in warnings:
            fix_plan["recommended_improvements"].extend(warning.fix_steps)

        # Add learning resources based on error types
        error_fields = [e.field for e in errors if e.field]
        for field in set(error_fields):
            if field in ["plan.tiers", "plan.rating_aggregations"]:
                fix_plan["learning_resources"].append(
                    f"Learn about {field}: {self.business_concepts.get(field, 'Advanced pricing concepts')}"
                )

        return fix_plan

    def _create_enhanced_error(
        self, error_info: Dict[str, Any], api_error: str, product_data: Dict[str, Any]
    ) -> ProductError:
        """Create an enhanced error from pattern match."""
        return ProductError(
            code=error_info["code"],
            severity=ErrorSeverity(error_info["severity"]),
            field=error_info.get("field"),
            message=error_info["message"],
            business_context=error_info["business_context"],
            fix_steps=error_info["fix_steps"],
            examples=error_info.get("examples", []),
            related_concepts=error_info.get("related_concepts", []),
            common_causes=error_info.get("common_causes", []),
        )

    def _create_generic_error(self, api_error: str, product_data: Dict[str, Any]) -> ProductError:
        """Create a generic enhanced error for unrecognized API errors."""
        return ProductError(
            code="UNKNOWN_API_ERROR",
            severity=ErrorSeverity.ERROR,
            field=None,
            message=f"API Error: {api_error}",
            business_context="An unexpected error occurred during product creation",
            fix_steps=[
                "Check that all required fields are provided",
                "Verify that field values are in the correct format",
                "Review the product structure against Revenium documentation",
                "Try creating a simpler product first to isolate the issue",
            ],
            examples=[],
            related_concepts=["product_validation", "api_requirements"],
            common_causes=[
                "Missing required fields",
                "Invalid field values",
                "API connectivity issues",
            ],
        )

    def _validate_product_name_business(self, name: Optional[str]) -> List[ProductError]:
        """Validate product name against business rules."""
        errors = []

        if not name:
            errors.append(
                ProductError(
                    code="MISSING_PRODUCT_NAME",
                    severity=ErrorSeverity.CRITICAL,
                    field="name",
                    message="Product name is required",
                    business_context="The product name appears on customer invoices and billing statements",
                    fix_steps=[
                        "Add a 'name' field to your product",
                        "Choose a customer-friendly name that describes your service",
                        "Avoid internal code names or technical abbreviations",
                    ],
                    examples=[
                        {"good": "API Pro Plan"},
                        {"good": "Premium Analytics"},
                        {"bad": "PROD_001"},
                    ],
                    related_concepts=["customer_experience", "billing_display"],
                    common_causes=["Forgot to include name field", "Using placeholder values"],
                )
            )
        elif len(name.strip()) < 2:
            errors.append(
                ProductError(
                    code="PRODUCT_NAME_TOO_SHORT",
                    severity=ErrorSeverity.ERROR,
                    field="name",
                    message="Product name must be at least 2 characters",
                    business_context="Very short names are confusing to customers and may not display properly",
                    fix_steps=[
                        "Expand the product name to be more descriptive",
                        "Include the type of service or product",
                        "Consider what customers would understand",
                    ],
                    examples=[{"current": name, "suggested": f"{name} Service"}],
                    related_concepts=["customer_clarity", "billing_display"],
                    common_causes=["Using abbreviations", "Minimal naming"],
                )
            )

        return errors

    def _validate_plan_business_logic(self, plan_data: Dict[str, Any]) -> List[ProductError]:
        """Validate plan structure against business logic."""
        errors = []

        # Check subscription-specific requirements
        if plan_data.get("type") == "SUBSCRIPTION":
            if not plan_data.get("period"):
                errors.append(
                    ProductError(
                        code="SUBSCRIPTION_MISSING_PERIOD",
                        severity=ErrorSeverity.CRITICAL,
                        field="plan.period",
                        message="Subscription plans must specify a billing period",
                        business_context="Customers need to know how often they'll be charged",
                        fix_steps=[
                            "Add a 'period' field to your plan",
                            "Choose from: MONTH, YEAR, WEEK, DAY",
                            "MONTH is most common for SaaS products",
                        ],
                        examples=[
                            {"field": "period", "value": "MONTH", "description": "Monthly billing"},
                            {"field": "period", "value": "YEAR", "description": "Annual billing"},
                        ],
                        related_concepts=["subscription_billing", "customer_expectations"],
                        common_causes=["Copied from CHARGE template", "Forgot billing frequency"],
                    )
                )

        return errors

    def _validate_pricing_consistency(self, product_data: Dict[str, Any]) -> List[ProductError]:
        """Validate pricing consistency across the product."""
        errors = []

        if "plan" not in product_data:
            return errors

        plan = product_data["plan"]

        # Check for zero pricing in paid products
        if "tiers" in plan:
            all_zero = all(float(tier.get("unit_amount", 0)) == 0 for tier in plan["tiers"])

            if all_zero and not any(
                keyword in product_data.get("name", "").lower()
                for keyword in ["free", "trial", "demo"]
            ):
                errors.append(
                    ProductError(
                        code="UNEXPECTED_ZERO_PRICING",
                        severity=ErrorSeverity.WARNING,
                        field="plan.tiers",
                        message="All tiers have zero pricing - is this intentional?",
                        business_context="Zero pricing is fine for free products, but may be unintentional for paid services",
                        fix_steps=[
                            "If this is a free product, consider adding 'Free' to the name",
                            "If this should be paid, update the unit_amount values",
                            "Consider if this is a trial version of a paid product",
                        ],
                        examples=[
                            {"free_product": "Free API Tier"},
                            {"paid_product": {"unit_amount": "9.99"}},
                        ],
                        related_concepts=["pricing_strategy", "product_positioning"],
                        common_causes=["Placeholder pricing", "Forgot to set real prices"],
                    )
                )

        return errors

    def _build_error_patterns(self) -> Dict[str, Dict[str, Any]]:
        """Build patterns for matching API errors to enhanced errors."""
        return {
            r"required.*name": {
                "code": "MISSING_REQUIRED_NAME",
                "severity": "critical",
                "field": "name",
                "message": "Product name is required",
                "business_context": "Every product needs a name for customer billing and identification",
                "fix_steps": [
                    "Add a 'name' field to your product data",
                    "Choose a customer-friendly name",
                    "Avoid technical codes or abbreviations",
                ],
            },
            r"invalid.*currency": {
                "code": "INVALID_CURRENCY",
                "severity": "error",
                "field": "plan.currency",
                "message": "Invalid currency code",
                "business_context": "Currency must be a valid ISO 4217 code for international billing",
                "fix_steps": [
                    "Use a valid 3-letter currency code (USD, EUR, GBP, etc.)",
                    "Check the ISO 4217 standard for valid codes",
                    "Ensure the currency matches your business location",
                ],
                "examples": [{"valid": "USD"}, {"valid": "EUR"}, {"invalid": "US"}],
            },
        }

    def _build_business_concepts(self) -> Dict[str, str]:
        """Build business concept explanations."""
        return {
            "plan.tiers": "Pricing levels that enable volume discounts and complex pricing strategies",
            "plan.rating_aggregations": "Usage tracking mechanisms that measure what customers consume",
            "plan.type": "Billing model that determines when and how customers are charged",
            "subscription_billing": "Regular recurring charges at fixed intervals",
            "usage_based_billing": "Variable charges based on actual consumption or usage",
        }

    def _build_fix_templates(self) -> Dict[str, Dict[str, Any]]:
        """Build templates for common fixes."""
        return {
            "add_basic_tier": {
                "description": "Add a basic pricing tier",
                "template": {
                    "tiers": [
                        {
                            "name": "Standard Tier",
                            "starting_from": 0,
                            "up_to": None,
                            "unit_amount": "10.00",
                        }
                    ]
                },
            },
            "fix_subscription_period": {
                "description": "Add billing period to subscription",
                "template": {"period": "MONTH", "period_count": 1},
            },
        }
