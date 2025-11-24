"""Product Templates and Examples for Revenium MCP Server.

This module provides pre-built templates and comprehensive examples for
common product creation patterns in the Revenium platform.
"""

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class ProductExample:
    """Complete product example with explanation."""

    name: str
    description: str
    use_case: str
    complexity: str
    data: Dict[str, Any]
    explanation: str
    customization_points: List[str]


class ProductTemplateLibrary:
    """Library of product templates and examples."""

    def __init__(self):
        """Initialize the template library."""
        self.templates = self._build_templates()
        self.examples = self._build_examples()

    def get_all_templates(self) -> Dict[str, Dict[str, Any]]:
        """Get all available templates."""
        return self.templates

    def get_template(self, template_name: str) -> Dict[str, Any]:
        """Get a specific template by name."""
        return self.templates.get(template_name, {})

    def get_examples_by_category(self, category: str) -> List[ProductExample]:
        """Get examples filtered by category."""
        return [ex for ex in self.examples if ex.complexity == category]

    def get_example(self, example_name: str) -> ProductExample:
        """Get a specific example by name."""
        for example in self.examples:
            if example.name == example_name:
                return example
        return None

    def _build_templates(self) -> Dict[str, Dict[str, Any]]:
        """Build the template library."""
        return {
            "simple_api_service": {
                "name": "Simple API Service",
                "description": "Basic API service with per-call pricing",
                "template": {
                    "name": "API Service",
                    "description": "Pay-per-use API service",
                    "version": "1.0.0",
                    "plan": {
                        "type": "SUBSCRIPTION",  # FIXED: Use SUBSCRIPTION instead of deprecated CHARGE
                        "name": "API Usage Plan",
                        "currency": "USD",
                        "period": "MONTH",  # Required for SUBSCRIPTION plans
                        "periodCount": 1,
                        "tiers": [
                            {
                                "name": "Per-Call Tier",
                                "up_to": None,  # Unlimited usage
                                "unit_amount": "0.01",  # $0.01 USD per API call
                            }
                        ],
                        "rating_aggregations": [
                            {
                                "name": "API Calls",
                                "aggregation_type": "COUNT",
                                "description": "Counts API calls for billing",
                            }
                        ],
                    },
                },
                "customization_guide": [
                    "Update 'name' to match your API service",
                    "Adjust 'unit_amount' for your per-call pricing",
                    "Modify 'rating_aggregations[0].name' to describe your usage metric",
                ],
            },
            "monthly_saas": {
                "name": "Monthly SaaS Subscription",
                "description": "Standard monthly subscription for SaaS products",
                "template": {
                    "name": "SaaS Platform",
                    "description": "Monthly subscription to our platform",
                    "version": "1.0.0",
                    "plan": {
                        "type": "SUBSCRIPTION",
                        "name": "Monthly Plan",
                        "currency": "USD",
                        "period": "MONTH",
                        "period_count": 1,
                        "tiers": [
                            {
                                "name": "Monthly Subscription",
                                "starting_from": 0,
                                "up_to": None,
                                "unit_amount": "29.99",
                                "flat_amount": "29.99",
                            }
                        ],
                    },
                },
                "customization_guide": [
                    "Set your product 'name' and 'description'",
                    "Adjust 'unit_amount' and 'flat_amount' for your pricing",
                    "Consider adding trial period with 'trial_period' and 'trial_period_count'",
                ],
            },
            "shipping_service": {
                "name": "Shipping Service",
                "description": "Per-package shipping with weight-based pricing",
                "template": {
                    "name": "Shipping Service",
                    "description": "Package delivery service",
                    "version": "1.0.0",
                    "plan": {
                        "type": "SUBSCRIPTION",  # FIXED: Use SUBSCRIPTION instead of deprecated CHARGE
                        "name": "Shipping Plan",
                        "currency": "USD",
                        "period": "MONTH",  # Required for SUBSCRIPTION plans
                        "periodCount": 1,
                        "tiers": [
                            {
                                "name": "Light Packages",
                                "starting_from": 0,
                                "up_to": 5,
                                "unit_amount": "5.00",
                            },
                            {
                                "name": "Heavy Packages",
                                "starting_from": 5,
                                "up_to": None,
                                "unit_amount": "8.00",
                            },
                        ],
                        "rating_aggregations": [
                            {
                                "name": "Package Weight",
                                "aggregation_type": "SUM",
                                "description": "Total weight of packages shipped",
                            }
                        ],
                    },
                },
                "customization_guide": [
                    "Adjust weight breakpoints in 'tiers' (up_to values)",
                    "Set appropriate pricing for each weight tier",
                    "Consider adding distance-based aggregations",
                ],
            },
            "tiered_api": {
                "name": "Tiered API Service",
                "description": "API service with volume discounts",
                "template": {
                    "name": "Tiered API Service",
                    "description": "API service with volume pricing",
                    "version": "1.0.0",
                    "plan": {
                        "type": "SUBSCRIPTION",  # FIXED: Use SUBSCRIPTION instead of deprecated CHARGE
                        "name": "Volume API Plan",
                        "currency": "USD",
                        "period": "MONTH",  # Required for SUBSCRIPTION plans
                        "periodCount": 1,
                        "tiers": [
                            {
                                "name": "First 1000 API calls",
                                "up_to": 1000,  # Maximum API calls in this tier
                                "unit_amount": "0.02",  # $0.02 USD per API call
                            },
                            {
                                "name": "Next 9000 API calls",
                                "up_to": 10000,  # Covers calls 1001-10000
                                "unit_amount": "0.015",  # $0.015 USD per API call (volume discount)
                            },
                            {
                                "name": "Additional API calls",
                                "up_to": None,  # Unlimited tier - covers all calls above 10000
                                "unit_amount": "0.01",  # $0.01 USD per API call (best rate)
                            },
                        ],
                        "rating_aggregations": [
                            {
                                "name": "API Calls",
                                "aggregation_type": "COUNT",
                                "description": "Total API calls per billing period",
                            }
                        ],
                    },
                },
                "customization_guide": [
                    "Adjust volume breakpoints to match your business model",
                    "Set competitive pricing for each tier",
                    "Consider offering a free tier for the first N calls",
                ],
            },
            "hybrid_saas": {
                "name": "Hybrid SaaS with Overages",
                "description": "Base subscription with usage-based overages",
                "template": {
                    "name": "Hybrid SaaS Platform",
                    "description": "Base subscription with usage overages",
                    "version": "1.0.0",
                    "plan": {
                        "type": "SUBSCRIPTION",
                        "name": "Hybrid Plan",
                        "currency": "USD",
                        "period": "MONTH",
                        "period_count": 1,
                        "tiers": [
                            {
                                "name": "Base Subscription",
                                "starting_from": 0,
                                "up_to": None,
                                "unit_amount": "49.99",
                                "flat_amount": "49.99",
                            }
                        ],
                        "rating_aggregations": [
                            {
                                "name": "Overage Usage",
                                "aggregation_type": "COUNT",
                                "description": "Usage beyond included allowance",
                            }
                        ],
                        "elements": [
                            {
                                "name": "Included Allowance",
                                "description": "Monthly included usage",
                                "aggregation_type": "COUNT",
                            }
                        ],
                    },
                },
                "customization_guide": [
                    "Set base subscription price in 'flat_amount'",
                    "Define what usage is included vs. overage",
                    "Set overage pricing in separate tiers or elements",
                ],
            },
        }

    def _build_examples(self) -> List[ProductExample]:
        """Build comprehensive examples with explanations."""
        return [
            ProductExample(
                name="simple_charge_example",
                description="One-time charge for a service",
                use_case="Consulting service, one-time setup fee, or simple product sale",
                complexity="simple",
                data={
                    "name": "Website Setup Service",
                    "description": "One-time website setup and configuration",
                    "version": "1.0.0",
                    "plan": {
                        "type": "SUBSCRIPTION",  # FIXED: Use SUBSCRIPTION instead of deprecated CHARGE
                        "name": "Setup Service Plan",
                        "currency": "USD",
                        "period": "MONTH",  # Required for SUBSCRIPTION plans
                        "periodCount": 1,
                        "tiers": [
                            {
                                "name": "Standard Setup Service",
                                "up_to": None,  # Unlimited usage
                                "unit_amount": "299.00",  # $299.00 USD per setup
                            }
                        ],
                    },
                    "tags": ["setup", "website", "one-time"],
                    "coming_soon": False,
                },
                explanation="This is a simple product type - a subscription-based service. Perfect for services that are delivered once or products that are sold individually. The SUBSCRIPTION type with monthly billing means customers are billed monthly for the service.",
                customization_points=[
                    "Change the product name and description to match your service",
                    "Adjust the unit_amount to your desired price",
                    "Add relevant tags for organization",
                    "Consider adding a description of what's included",
                ],
            ),
            ProductExample(
                name="monthly_subscription_example",
                description="Standard monthly subscription",
                use_case="SaaS platform, membership site, or recurring service",
                complexity="simple",
                data={
                    "name": "Pro Analytics Platform",
                    "description": "Advanced analytics and reporting platform",
                    "version": "1.0.0",
                    "plan": {
                        "type": "SUBSCRIPTION",
                        "name": "Pro Monthly Plan",
                        "currency": "USD",
                        "period": "MONTH",
                        "period_count": 1,
                        "trial_period": "DAY",
                        "trial_period_count": 14,
                        "tiers": [
                            {
                                "name": "Pro Monthly Access",
                                "up_to": None,  # Unlimited usage
                                "unit_amount": "79.99",  # $79.99 USD per month (recurring)
                                "flat_amount": "79.99",  # $79.99 USD setup fee (one-time when tier first used)
                            }
                        ],
                    },
                    "tags": ["analytics", "saas", "monthly"],
                    "notification_addresses_on_invoice": ["billing@company.com"],
                },
                explanation="A subscription product charges customers regularly (monthly in this case). The flat_amount is what customers pay each billing period. This example includes a 14-day trial period.",
                customization_points=[
                    "Adjust the monthly price in unit_amount and flat_amount",
                    "Change trial period length or remove trial entirely",
                    "Consider annual plans with discounts",
                    "Add notification email for billing alerts",
                ],
            ),
        ]
