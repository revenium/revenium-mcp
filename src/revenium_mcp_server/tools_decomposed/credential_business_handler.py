"""Business context handler for subscriber credentials management.

This module handles business guidance, onboarding checklists, troubleshooting guides,
and billing impact analysis for credential operations.
"""

from typing import Any, Dict

from ..business_context.credential_business_context import (
    BusinessScenario,
    CredentialBusinessContext,
)


class CredentialBusinessHandler:
    """Handler for business context operations in credential management."""

    def __init__(self):
        """Initialize business context handler."""
        self.business_context = CredentialBusinessContext()

    async def get_business_guidance(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get business guidance for credential management scenarios."""
        scenario_name = arguments.get("scenario", "new_customer_onboarding")

        try:
            scenario = BusinessScenario(scenario_name)
        except ValueError:
            return {
                "action": "get_business_guidance",
                "error": f"Unknown scenario: {scenario_name}",
                "available_scenarios": [s.value for s in BusinessScenario],
                "suggestion": "Use one of the available scenarios",
            }

        guidance = self.business_context.get_business_guidance(scenario)

        # Convert guidance to dictionary if it exists
        guidance_dict = {}
        if guidance:
            guidance_dict = {
                "description": guidance.description,
                "key_considerations": guidance.key_considerations,
                "step_by_step_process": guidance.step_by_step_process,
                "common_pitfalls": guidance.common_pitfalls,
                "success_metrics": guidance.success_metrics,
                "troubleshooting_tips": guidance.troubleshooting_tips,
            }

        return {
            "action": "get_business_guidance",
            "scenario": scenario_name,
            "guidance": guidance_dict,
            "related_actions": [
                "get_onboarding_checklist - for new customer setup",
                "get_troubleshooting_guide - for issue resolution",
                "analyze_billing_impact - for understanding billing implications",
            ],
        }

    async def get_onboarding_checklist(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get customer onboarding checklist."""
        customer_info = arguments.get("customer_info", {})

        checklist = self.business_context.generate_onboarding_checklist(customer_info)

        return {
            "action": "get_onboarding_checklist",
            "checklist": checklist,
            "usage_tip": "Use this checklist to ensure proper credential setup for new customers",
            "next_steps": [
                "Follow each checklist item in order",
                "Use dry_run=true for credential creation to validate setup",
                "Test billing flow with minimal usage before full deployment",
            ],
        }

    async def get_troubleshooting_guide(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get troubleshooting guide for credential issues."""
        issue_description = arguments.get("issue_description", "")

        if not issue_description:
            return {
                "action": "get_troubleshooting_guide",
                "error": "Please provide an issue description",
                "examples": [
                    "Customer billing is missing for last week",
                    "Authentication errors for credential XYZ",
                    "Need to audit all credential-subscription relationships",
                ],
            }

        guide = self.business_context.generate_troubleshooting_guide(issue_description)

        return {
            "action": "get_troubleshooting_guide",
            "issue": issue_description,
            "troubleshooting_guide": guide,
            "immediate_actions": guide["immediate_actions"],
            "key_questions": guide["key_questions"],
        }

    async def analyze_billing_impact(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze billing impact of credential operations."""
        operation = arguments.get("operation", "create")
        credential_data = arguments.get("credential_data", {})

        impact_analysis = self.business_context.get_billing_impact_explanation(
            operation, credential_data
        )

        # Get billing relationship explanations
        relationships = {
            "credential_to_subscription": self.business_context.get_billing_relationship_explanation(
                "credential_to_subscription"
            ),
            "organization_hierarchy": self.business_context.get_billing_relationship_explanation(
                "organization_hierarchy"
            ),
            "subscription_metering": self.business_context.get_billing_relationship_explanation(
                "subscription_metering"
            ),
        }

        return {
            "action": "analyze_billing_impact",
            "operation": operation,
            "impact_analysis": impact_analysis,
            "billing_relationships": relationships,
            "recommendations": [
                "Use dry_run=true to preview changes before applying",
                "Monitor billing automation for 24-48 hours after changes",
                "Coordinate with customers for any credential secret updates",
                "Maintain audit trail of all credential changes",
            ],
        }
