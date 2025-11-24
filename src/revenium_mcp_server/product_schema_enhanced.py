"""Enhanced Product Schema Discovery for Revenium MCP Server.

This module provides comprehensive schema discovery, documentation, and guidance
for Revenium product creation with agent-friendly features.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


@dataclass
class FieldDocumentation:
    """Documentation for a single field in the product schema."""

    name: str
    type: str
    required: bool
    description: str
    business_context: str
    examples: List[Any]
    validation_rules: List[str]
    related_fields: List[str]
    common_mistakes: List[str]


@dataclass
class SchemaTemplate:
    """Template for creating products with specific patterns."""

    name: str
    description: str
    use_cases: List[str]
    template_data: Dict[str, Any]
    required_customizations: List[str]
    optional_customizations: List[str]


class ProductComplexity(str, Enum):
    """Product complexity levels for guidance."""

    SIMPLE = "simple"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    ENTERPRISE = "enterprise"


class EnhancedProductSchemaDiscovery:
    """Enhanced schema discovery system for Revenium products."""

    def __init__(self):
        """Initialize the enhanced schema discovery system."""
        self.field_docs = self._build_field_documentation()
        self.templates = self._build_product_templates()
        self.business_concepts = self._build_business_concepts()
        self.validation_rules = self._build_validation_rules()

    def get_complete_schema(self) -> Dict[str, Any]:
        """Get complete product schema with full documentation."""
        return {
            "schema_version": "2.0",
            "description": "Complete Revenium product schema with business context",
            "complexity_levels": [level.value for level in ProductComplexity],
            "core_concepts": self.business_concepts,
            "fields": {field.name: self._field_to_dict(field) for field in self.field_docs},
            "templates": {
                template.name: self._template_to_dict(template) for template in self.templates
            },
            "validation_rules": self.validation_rules,
            "workflow_guidance": self._get_workflow_guidance(),
        }

    def get_field_documentation(self, field_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed documentation for a specific field."""
        for field in self.field_docs:
            if field.name == field_name:
                return self._field_to_dict(field)
        return None

    def get_template(self, template_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific product template."""
        for template in self.templates:
            if template.name == template_name:
                return self._template_to_dict(template)
        return None

    def get_templates_by_complexity(self, complexity: ProductComplexity) -> List[Dict[str, Any]]:
        """Get templates filtered by complexity level."""
        complexity_mapping = {
            ProductComplexity.SIMPLE: ["simple_charge", "basic_subscription"],
            ProductComplexity.INTERMEDIATE: ["usage_based", "tiered_pricing"],
            ProductComplexity.ADVANCED: ["hybrid_pricing", "multi_component"],
            ProductComplexity.ENTERPRISE: ["enterprise_saas", "complex_billing"],
        }

        template_names = complexity_mapping.get(complexity, [])
        templates = []
        for name in template_names:
            template = self.get_template(name)
            if template:
                templates.append(template)
        return templates

    def suggest_template(self, requirements: Dict[str, Any]) -> Dict[str, Any]:
        """Suggest the best template based on requirements."""
        # Analyze requirements to suggest appropriate template
        has_usage = any(
            keyword in str(requirements).lower()
            for keyword in ["usage", "per", "based on", "metered"]
        )
        has_subscription = any(
            keyword in str(requirements).lower()
            for keyword in ["monthly", "yearly", "subscription", "recurring"]
        )
        has_tiers = any(
            keyword in str(requirements).lower()
            for keyword in ["tier", "volume", "bulk", "graduated"]
        )

        # Map requirements to actual template names from ProductTemplateLibrary
        if has_usage and has_subscription:
            template_name = "hybrid_saas"
        elif has_usage and has_tiers:
            template_name = "tiered_api"
        elif has_usage:
            template_name = "simple_api_service"
        elif has_subscription:
            template_name = "monthly_saas"
        elif has_tiers:
            template_name = "tiered_api"
        else:
            template_name = "monthly_saas"  # Default to simple subscription

        # Get template from the actual template library
        try:
            from .product_templates import ProductTemplateLibrary

            template_lib = ProductTemplateLibrary()
            template_info = template_lib.get_template(template_name)

            if template_info and "template" in template_info:
                return {
                    "suggested_template": {
                        "name": template_name,
                        "description": template_info.get("description", ""),
                        "template_data": template_info["template"],
                        "customization_guide": template_info.get("customization_guide", []),
                    },
                    "reasoning": self._explain_template_choice(requirements, template_name),
                    "customization_guidance": self._get_customization_guidance(
                        template_name, requirements
                    ),
                }
        except (ImportError, KeyError) as e:
            # Fallback if import fails or template structure is wrong
            pass

        return {"error": "No suitable template found"}

    def validate_product_structure(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate product structure with detailed feedback."""
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "suggestions": [],
            "completeness_score": 0.0,
            "complexity_assessment": ProductComplexity.SIMPLE,
        }

        # Check required fields
        required_fields = ["name", "version", "plan"]
        for field in required_fields:
            if field not in product_data:
                validation_result["errors"].append(
                    {
                        "field": field,
                        "message": f"Required field '{field}' is missing",
                        "fix": f"Add the '{field}' field to your product definition",
                        "example": self._get_field_example(field),
                    }
                )
                validation_result["valid"] = False

        # Validate plan structure
        if "plan" in product_data:
            plan_validation = self._validate_plan_structure(product_data["plan"])
            validation_result["errors"].extend(plan_validation["errors"])
            validation_result["warnings"].extend(plan_validation["warnings"])
            validation_result["suggestions"].extend(plan_validation["suggestions"])

        # Calculate completeness score
        validation_result["completeness_score"] = self._calculate_completeness_score(product_data)

        # Assess complexity
        validation_result["complexity_assessment"] = self._assess_complexity(product_data)

        return validation_result

    def get_business_guidance(self, domain: Optional[str] = None) -> Dict[str, Any]:
        """Get business-specific guidance for product creation."""
        guidance = {
            "general_principles": [
                "Start with a simple structure and add complexity as needed",
                "Clearly define what you're billing for (usage, time, features)",
                "Consider your customer's billing preferences",
                "Plan for future pricing model changes",
            ],
            "common_patterns": {
                "SaaS Products": "Use subscription billing with usage-based overages",
                "API Services": "Use usage-based billing per API call or data transfer",
                "Physical Products": "Use simple charge or tiered volume pricing",
                "Professional Services": "Use time-based billing or project-based charges",
            },
            "pricing_psychology": [
                "Round numbers ($10, $50) are easier to understand",
                "Tiered pricing encourages higher usage",
                "Free tiers can drive adoption",
                "Annual discounts improve cash flow",
            ],
        }

        if domain:
            domain_specific = self._get_domain_specific_guidance(domain)
            guidance["domain_specific"] = domain_specific

        return guidance

    def _field_to_dict(self, field: FieldDocumentation) -> Dict[str, Any]:
        """Convert field documentation to dictionary."""
        return {
            "type": field.type,
            "required": field.required,
            "description": field.description,
            "business_context": field.business_context,
            "examples": field.examples,
            "validation_rules": field.validation_rules,
            "related_fields": field.related_fields,
            "common_mistakes": field.common_mistakes,
        }

    def _template_to_dict(self, template: SchemaTemplate) -> Dict[str, Any]:
        """Convert template to dictionary."""
        return {
            "description": template.description,
            "use_cases": template.use_cases,
            "template_data": template.template_data,
            "required_customizations": template.required_customizations,
            "optional_customizations": template.optional_customizations,
        }

    def _build_field_documentation(self) -> List[FieldDocumentation]:
        """Build comprehensive field documentation."""
        return [
            FieldDocumentation(
                name="name",
                type="string",
                required=True,
                description="The product name that customers will see",
                business_context="This appears on invoices, billing statements, and customer portals. Choose a clear, descriptive name.",
                examples=["API Pro Plan", "Shipping Service", "Premium Analytics"],
                validation_rules=[
                    "2-255 characters",
                    "No special characters except spaces, hyphens, underscores",
                ],
                related_fields=["description", "plan.name"],
                common_mistakes=["Using internal code names", "Too generic names like 'Product 1'"],
            ),
            FieldDocumentation(
                name="plan.type",
                type="enum",
                required=True,
                description="The billing model for this product",
                business_context="SUBSCRIPTION = recurring billing (CHARGE deprecated as of 2024)",
                examples=["SUBSCRIPTION"],
                validation_rules=["Must be 'SUBSCRIPTION' (CHARGE deprecated)"],
                related_fields=["plan.period", "plan.tiers", "plan.rating_aggregations"],
                common_mistakes=[
                    "Using deprecated CHARGE type",
                    "Using SUBSCRIPTION without setting period",
                ],
            ),
        ]

    def _build_product_templates(self) -> List[SchemaTemplate]:
        """Build product templates for common use cases."""
        return [
            SchemaTemplate(
                name="basic_subscription",
                description="Simple monthly subscription",
                use_cases=["SaaS products", "Membership services", "Regular services"],
                template_data={
                    "name": "Monthly Subscription",
                    "version": "1.0.0",
                    "plan": {
                        "type": "SUBSCRIPTION",
                        "name": "Monthly Plan",
                        "currency": "USD",
                        "period": "MONTH",
                        "period_count": 1,
                        "tiers": [
                            {
                                "name": "Monthly Tier",
                                "starting_from": 0,
                                "up_to": None,
                                "unit_amount": "29.99",
                                "flat_amount": "29.99",
                            }
                        ],
                    },
                },
                required_customizations=["name", "plan.name", "plan.tiers[0].unit_amount"],
                optional_customizations=["plan.period", "plan.period_count", "description"],
            ),
            SchemaTemplate(
                name="usage_based_subscription",
                description="Usage-based subscription with metering",
                use_cases=["API services", "Cloud computing", "Utility services"],
                template_data={
                    "name": "Usage-Based Service",
                    "version": "1.0.0",
                    "plan": {
                        "type": "SUBSCRIPTION",
                        "name": "Pay-as-you-go Plan",
                        "currency": "USD",
                        "period": "MONTH",
                        "period_count": 1,
                        "tiers": [
                            {
                                "name": "Usage Tier",
                                "starting_from": 0,
                                "up_to": None,
                                "unit_amount": "0.10",
                            }
                        ],
                        "rating_aggregations": [
                            {
                                "name": "Usage Aggregation",
                                "aggregation_type": "COUNT",
                                "description": "Tracks usage units for billing",
                            }
                        ],
                    },
                },
                required_customizations=[
                    "name",
                    "plan.rating_aggregations[0].name",
                    "plan.tiers[0].unit_amount",
                ],
                optional_customizations=[
                    "plan.rating_aggregations[0].aggregation_type",
                    "description",
                    "plan.period",
                ],
            ),
        ]

    def _build_business_concepts(self) -> Dict[str, str]:
        """Build business concept explanations based on Revenium documentation."""
        return {
            "products": "Top-level billing entities that customers subscribe to or purchase. Products contain plans that define pricing structure.",
            "plans": "Define the billing model (CHARGE vs SUBSCRIPTION) and contain tiers, aggregations, and elements. Plans are the core pricing configuration.",
            "metering_elements": "Objects in Revenium that represent what gets measured for billing (API calls, storage, etc.). REQUIRED for usage-based billing, NOT needed for simple products (one-time charges, basic subscriptions). NOTE: Metering elements management tool needs to be built.",
            "rating_aggregations": "Define HOW usage data gets aggregated (COUNT, SUM, MAX, etc.) for billing calculations. For usage-based billing, they must reference existing metering elements. Simple products don't need these.",
            "tiers": "Volume-based pricing levels within aggregations. Example: first 100 API calls at $0.01 each, next 900 at $0.008 each. Final tier must have up_to: null.",
            "elements": "Additional billable components within a plan, often used for included allowances or base fees in hybrid models.",
            "setup_fees": "One-time charges applied when a customer first subscribes to a product.",
            "billing_periods": "For SUBSCRIPTION plans: MONTH, YEAR, WEEK, DAY. Determines how often customers are charged.",
            "plan_types": "SUBSCRIPTION = recurring billing at regular intervals (CHARGE deprecated as of 2024)",
            "aggregation_types": "SUM (total amount/volume), COUNT (number of discrete items), MAXIMUM (peak usage), AVERAGE (typical usage), UNIQUE (distinct items), DISTINCT (unique values)",
            "workflow_dependency": "Simple products: Products → Plans → Tiers (no metering needed). Usage-based products: Products → Plans → Rating Aggregations → Metering Elements (metering elements must exist first).",
            "when_metering_needed": "Metering elements are ONLY required for usage-based billing (per API call, per GB, etc.). Simple one-time charges and basic subscriptions work without any metering.",
        }

    def _build_validation_rules(self) -> Dict[str, List[str]]:
        """Build validation rules for product creation."""
        return {
            "product_level": [
                "Product name must be 2-255 characters",
                "Version must follow semantic versioning (e.g., 1.0.0)",
                "At least one plan is required",
            ],
            "plan_level": [
                "Plan type must be CHARGE or SUBSCRIPTION",
                "SUBSCRIPTION plans must have a billing period",
                "At least one tier is required",
                "Currency must be a valid ISO code",
            ],
            "tier_level": [
                "Final tier must have up_to: null",
                "Non-final tiers must have up_to values",
                "Tier ranges cannot overlap",
                "Unit amounts must be non-negative",
            ],
            "aggregation_level": [
                "Aggregation names must be unique within a plan",
                "Aggregation type must be valid (SUM, COUNT, etc.)",
                "Each usage-based component needs an aggregation",
            ],
        }

    def _get_workflow_guidance(self) -> Dict[str, Any]:
        """Get step-by-step workflow guidance based on Revenium architecture."""
        return {
            "basic_workflow": [
                "1. Choose a product template based on your business model",
                "2. Customize the product name and description",
                "3. Configure basic pricing (tiers, amounts, currency)",
                "4. For usage-based billing: FIRST create/identify metering elements",
                "5. Create rating aggregations that reference the metering elements",
                "6. Set up billing period for subscriptions",
                "7. Validate the complete configuration",
                "8. Test with dry-run before creating",
            ],
            "simple_product_workflow": [
                "✅ Simple products (one-time charges, basic subscriptions) - NO metering needed",
                "1. Choose appropriate template (simple_charge or basic_subscription)",
                "2. Set product name and description",
                "3. Configure pricing in tiers",
                "4. Set billing period (for subscriptions)",
                "5. Create the product - ready to use!",
            ],
            "usage_based_workflow": [
                "⚠️  Usage-based products REQUIRE metering elements for practical use",
                "1. Identify what you want to measure (API calls, storage, etc.)",
                "2. Create metering elements for each measurable component",
                "3. Create rating aggregations that reference these elements",
                "4. Set up pricing tiers for the aggregations",
                "5. Test the complete billing flow",
            ],
            "current_limitations": {
                "metering_elements": "⚠️  Metering elements management tool not yet implemented. Simple products work fine without metering. For usage-based products, rating aggregations can be created but won't function until metering elements are set up.",
                "workaround": "Simple products work immediately. For usage-based products, create the product structure now, but metering elements must be added separately for actual usage tracking.",
            },
            "decision_points": {
                "charge_vs_subscription": "Use CHARGE for one-time or usage-based billing, SUBSCRIPTION for recurring billing",
                "simple_vs_tiered": "Use simple pricing for straightforward billing, tiered for volume discounts",
                "aggregation_types": "COUNT for discrete items (API calls, users), SUM for measurable quantities (GB, hours), MAXIMUM for capacity-based billing",
                "metering_strategy": "Each billable component needs its own metering element and corresponding rating aggregation",
            },
            "common_workflows": {
                "simple_saas_subscription": [
                    "✅ No metering needed for basic subscriptions",
                    "Use basic_subscription template",
                    "Set monthly/yearly pricing",
                    "Add trial period if desired",
                    "Ready to use immediately!",
                ],
                "usage_based_api_service": [
                    "⚠️  Requires metering elements for actual usage tracking",
                    "Use usage_based template",
                    "Create metering element for API calls (future step)",
                    "Create COUNT aggregation for API calls",
                    "Set per-call pricing in tiers",
                ],
                "one_time_service": [
                    "✅ No metering needed for one-time charges",
                    "Use simple_charge template",
                    "Set fixed price",
                    "Ready to use immediately!",
                ],
                "hybrid_saas_with_overages": [
                    "⚠️  Base subscription works immediately, overages need metering",
                    "Start with basic subscription",
                    "Add usage aggregations for overages",
                    "Metering elements needed for overage tracking (future step)",
                ],
            },
            "best_practices": [
                "Start simple and add complexity gradually",
                "Always validate tier ranges don't overlap",
                "Ensure final tier has up_to: null",
                "For usage-based billing, plan your metering strategy first",
                "Test with small amounts before full deployment",
            ],
        }

    def _explain_template_choice(
        self, requirements: Optional[Dict[str, Any]], template_name: str
    ) -> str:
        """Explain why a specific template was chosen."""
        explanations = {
            "simple_api_service": "Chosen for API services with per-call pricing based on usage",
            "monthly_saas": "Chosen for recurring subscription billing with regular intervals",
            "shipping_service": "Chosen for weight-based or package-based pricing",
            "tiered_api": "Chosen for API services with volume discounts at different usage levels",
            "hybrid_saas": "Chosen for combining subscription base with usage-based overages",
        }
        return explanations.get(template_name, "Template chosen based on detected requirements")

    def _get_customization_guidance(
        self, template_name: str, requirements: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """Get specific guidance for customizing a template."""
        base_guidance = [
            "Update the product name to match your service",
            "Adjust pricing amounts to match your business model",
            "Customize tier names to be customer-friendly",
        ]

        template_specific = {
            "simple_api_service": [
                "Define what usage metric you're tracking (API calls, requests, etc.)",
                "Set appropriate per-unit pricing",
                "Consider adding free tier allowances",
            ],
            "monthly_saas": [
                "Choose appropriate billing period (monthly/yearly)",
                "Consider offering annual discounts",
                "Set trial period if applicable",
            ],
            "tiered_api": [
                "Define volume breakpoints that make business sense",
                "Ensure tier ranges don't overlap",
                "Consider graduated vs. flat tier pricing",
            ],
            "hybrid_saas": [
                "Set base subscription price appropriately",
                "Define what usage is included vs. overage",
                "Balance base price with overage rates",
            ],
            "shipping_service": [
                "Adjust weight or size breakpoints",
                "Set competitive shipping rates",
                "Consider distance-based pricing",
            ],
        }

        return base_guidance + template_specific.get(template_name, [])

    def _validate_plan_structure(self, plan_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate plan structure with detailed feedback."""
        result = {"errors": [], "warnings": [], "suggestions": []}

        # Check required plan fields
        if "type" not in plan_data:
            result["errors"].append(
                {
                    "field": "plan.type",
                    "message": "Plan type is required",
                    "fix": "Add 'type' field with value 'SUBSCRIPTION' (CHARGE deprecated)",
                    "example": {"type": "SUBSCRIPTION"},
                }
            )

        # Validate subscription-specific requirements
        if plan_data.get("type") == "SUBSCRIPTION":
            if "period" not in plan_data:
                result["errors"].append(
                    {
                        "field": "plan.period",
                        "message": "Subscription plans must specify billing period",
                        "fix": "Add 'period' field with value like 'MONTH', 'YEAR', etc.",
                        "example": {"period": "MONTH"},
                    }
                )

        # Validate tiers
        if "tiers" not in plan_data or not plan_data["tiers"]:
            result["errors"].append(
                {
                    "field": "plan.tiers",
                    "message": "At least one pricing tier is required",
                    "fix": "Add a tiers array with at least one tier definition",
                    "example": {
                        "tiers": [{"name": "Basic Tier", "up_to": None, "unit_amount": "10.00"}]
                    },
                }
            )

        return result

    def _calculate_completeness_score(self, product_data: Dict[str, Any]) -> float:
        """Calculate how complete the product definition is."""
        total_points = 0
        earned_points = 0

        # Core fields (40 points)
        core_fields = ["name", "version", "plan"]
        for field in core_fields:
            total_points += 10
            if field in product_data and product_data[field]:
                earned_points += 10

        # Plan completeness (30 points)
        if "plan" in product_data:
            plan = product_data["plan"]
            plan_fields = ["type", "name", "currency", "tiers"]
            for field in plan_fields:
                total_points += 7.5
                if field in plan and plan[field]:
                    earned_points += 7.5

        # Optional but valuable fields (30 points)
        optional_fields = ["description", "tags", "notification_addresses_on_invoice"]
        for field in optional_fields:
            total_points += 10
            if field in product_data and product_data[field]:
                earned_points += 10

        return round(earned_points / total_points, 2) if total_points > 0 else 0.0

    def _assess_complexity(self, product_data: Dict[str, Any]) -> ProductComplexity:
        """Assess the complexity level of a product definition."""
        complexity_score = 0

        # Check for complex features
        if "plan" in product_data:
            plan = product_data["plan"]

            # Multiple tiers add complexity
            if "tiers" in plan and len(plan["tiers"]) > 1:
                complexity_score += 1

            # Usage-based billing adds complexity
            if "rating_aggregations" in plan and plan["rating_aggregations"]:
                complexity_score += 2

            # Multiple elements add complexity
            if "elements" in plan and len(plan["elements"]) > 1:
                complexity_score += 1

            # Setup fees add complexity
            if "setup_fees" in plan and plan["setup_fees"]:
                complexity_score += 1

        # Multiple notification addresses suggest enterprise use
        if "notification_addresses_on_invoice" in product_data:
            if len(product_data["notification_addresses_on_invoice"]) > 2:
                complexity_score += 1

        # Map score to complexity level
        if complexity_score >= 4:
            return ProductComplexity.ENTERPRISE
        elif complexity_score >= 2:
            return ProductComplexity.ADVANCED
        elif complexity_score >= 1:
            return ProductComplexity.INTERMEDIATE
        else:
            return ProductComplexity.SIMPLE

    def _get_field_example(self, field_name: str) -> Any:
        """Get an example value for a field."""
        examples = {
            "name": "My API Service",
            "version": "1.0.0",
            "description": "A comprehensive API service for developers",
            "plan": {
                "type": "SUBSCRIPTION",
                "name": "Standard Plan",
                "currency": "USD",
                "period": "MONTH",
                "tiers": [{"name": "Basic Tier", "up_to": None, "unit_amount": "10.00"}],
            },
        }
        return examples.get(field_name, "Example value")

    def _get_domain_specific_guidance(self, domain: str) -> Dict[str, Any]:
        """Get domain-specific guidance for product creation."""
        domain_guidance = {
            "saas": {
                "recommended_model": "Subscription with usage overages",
                "typical_periods": ["MONTH", "YEAR"],
                "common_metrics": ["active_users", "storage_used", "api_calls"],
                "pricing_tips": ["Offer annual discounts", "Include free tier", "Tier by features"],
            },
            "api": {
                "recommended_model": "Usage-based per API call",
                "typical_aggregations": ["COUNT", "SUM"],
                "common_metrics": ["requests_per_month", "data_transferred", "compute_time"],
                "pricing_tips": ["Rate limit free tier", "Volume discounts", "Overage protection"],
            },
            "shipping": {
                "recommended_model": "Per-shipment with weight/distance tiers",
                "typical_aggregations": ["COUNT", "SUM"],
                "common_metrics": ["packages_shipped", "total_weight", "delivery_distance"],
                "pricing_tips": ["Zone-based pricing", "Weight tiers", "Express options"],
            },
        }

        return domain_guidance.get(
            domain,
            {
                "recommended_model": "Start simple and add complexity as needed",
                "pricing_tips": [
                    "Keep pricing transparent",
                    "Align with customer value",
                    "Test different models",
                ],
            },
        )
