"""Business context and guidance for subscriber credentials management.

This module provides comprehensive business context, explanations, and guidance
for product managers and business users working with credential-subscription
relationships in the Revenium billing automation system.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class BusinessScenario(Enum):
    """Common business scenarios for credential management."""

    NEW_CUSTOMER_ONBOARDING = "new_customer_onboarding"
    BILLING_TROUBLESHOOTING = "billing_troubleshooting"
    CREDENTIAL_AUDIT = "credential_audit"
    SUBSCRIPTION_MIGRATION = "subscription_migration"
    SECURITY_ROTATION = "security_rotation"
    COST_OPTIMIZATION = "cost_optimization"


@dataclass
class BusinessGuidance:
    """Business guidance for credential operations."""

    scenario: BusinessScenario
    description: str
    key_considerations: List[str]
    step_by_step_process: List[str]
    common_pitfalls: List[str]
    success_metrics: List[str]
    troubleshooting_tips: List[str]


class CredentialBusinessContext:
    """Comprehensive business context provider for credential management."""

    def __init__(self):
        """Initialize business context with scenarios and guidance."""
        self._initialize_business_scenarios()
        self._initialize_billing_relationships()

    def _initialize_business_scenarios(self):
        """Initialize business scenario guidance."""
        self.business_scenarios = {
            BusinessScenario.NEW_CUSTOMER_ONBOARDING: BusinessGuidance(
                scenario=BusinessScenario.NEW_CUSTOMER_ONBOARDING,
                description="Setting up credentials for new customers to enable proper billing automation",
                key_considerations=[
                    "Credentials must be linked to active subscriptions for billing to work",
                    "Organization and subscriber relationships affect billing hierarchy",
                    "External ID uniqueness prevents authentication conflicts",
                    "Proper tagging enables better cost tracking and management",
                ],
                step_by_step_process=[
                    "1. Verify customer organization exists in Revenium",
                    "2. Confirm subscriber email is registered and active",
                    "3. Create credential with unique external ID",
                    "4. Link credential to appropriate subscription(s)",
                    "5. Test billing automation with small usage",
                    "6. Monitor for 24-48 hours to ensure proper metering",
                ],
                common_pitfalls=[
                    "Forgetting to link credentials to subscriptions (billing won't work)",
                    "Using duplicate external IDs (causes authentication conflicts)",
                    "Incorrect organization assignment (affects billing hierarchy)",
                    "Missing or weak external secrets (security vulnerabilities)",
                ],
                success_metrics=[
                    "Billing automation captures usage within 1 hour",
                    "Costs are properly attributed to correct subscription",
                    "No authentication errors in system logs",
                    "Customer can view usage in their dashboard",
                ],
                troubleshooting_tips=[
                    "Check credential-subscription linkage if billing is missing",
                    "Verify external ID matches customer's API configuration",
                    "Confirm organization hierarchy for multi-tenant customers",
                    "Test with minimal usage before full deployment",
                ],
            ),
            BusinessScenario.BILLING_TROUBLESHOOTING: BusinessGuidance(
                scenario=BusinessScenario.BILLING_TROUBLESHOOTING,
                description="Diagnosing and fixing billing issues related to credential configuration",
                key_considerations=[
                    "Missing usage often indicates credential-subscription disconnection",
                    "Incorrect costs may result from wrong subscription associations",
                    "Authentication failures prevent usage tracking entirely",
                    "Timing issues can cause delayed or missing billing data",
                ],
                step_by_step_process=[
                    "1. Identify the affected customer and time period",
                    "2. Check credential-subscription associations",
                    "3. Verify external ID matches customer's configuration",
                    "4. Review authentication logs for errors",
                    "5. Test credential with known API calls",
                    "6. Validate subscription pricing and metering rules",
                ],
                common_pitfalls=[
                    "Assuming the issue is with pricing when it's credential linkage",
                    "Not checking for recent credential or subscription changes",
                    "Overlooking organization-level billing configurations",
                    "Missing authentication errors in system monitoring",
                ],
                success_metrics=[
                    "Usage data appears correctly in billing system",
                    "Costs match expected pricing calculations",
                    "No authentication errors for the credential",
                    "Customer confirms usage matches their expectations",
                ],
                troubleshooting_tips=[
                    "Start with credential-subscription linkage verification",
                    "Use audit trail to identify recent configuration changes",
                    "Test with customer's actual API calls when possible",
                    "Check both current and historical billing data",
                ],
            ),
            BusinessScenario.CREDENTIAL_AUDIT: BusinessGuidance(
                scenario=BusinessScenario.CREDENTIAL_AUDIT,
                description="Auditing credential-subscription relationships for compliance and optimization",
                key_considerations=[
                    "Orphaned credentials (not linked to subscriptions) waste resources",
                    "Duplicate external IDs create security and billing risks",
                    "Inactive subscriptions with active credentials may cause confusion",
                    "Missing credentials for active subscriptions prevent billing",
                ],
                step_by_step_process=[
                    "1. Generate report of all credentials and their subscription links",
                    "2. Identify orphaned credentials (no subscription associations)",
                    "3. Find active subscriptions without credentials",
                    "4. Check for duplicate external IDs across credentials",
                    "5. Verify organization and subscriber relationships",
                    "6. Create action plan for identified issues",
                ],
                common_pitfalls=[
                    "Deleting credentials that appear orphaned but are actually needed",
                    "Not considering test/development credentials in audit",
                    "Missing inactive but important credential relationships",
                    "Focusing only on current state without historical context",
                ],
                success_metrics=[
                    "All active subscriptions have associated credentials",
                    "No duplicate external IDs in the system",
                    "Orphaned credentials are properly documented or removed",
                    "Billing coverage is 100% for active customers",
                ],
                troubleshooting_tips=[
                    "Use dry_run mode to test changes before applying",
                    "Coordinate with customers before making credential changes",
                    "Maintain audit trail of all changes made",
                    "Schedule regular audits to prevent issues from accumulating",
                ],
            ),
        }

    def _initialize_billing_relationships(self):
        """Initialize billing relationship explanations."""
        self.billing_relationships = {
            "credential_to_subscription": {
                "description": "How credentials enable billing for subscriptions",
                "explanation": """
                Credentials serve as the authentication bridge between customer API usage and Revenium's billing system:
                
                1. Customer makes API calls using their external ID and secret
                2. Revenium authenticates the request using the credential
                3. Usage is attributed to the credential's associated subscription(s)
                4. Billing calculations are applied based on subscription pricing
                5. Costs are allocated to the customer's organization
                
                Without proper credential-subscription linkage, usage cannot be billed.
                """,
                "critical_fields": [
                    "subscriberId",
                    "organizationId",
                    "subscriptionIds",
                    "externalId",
                ],
                "business_impact": "Broken linkage results in lost revenue and customer billing disputes",
            },
            "organization_hierarchy": {
                "description": "How organization structure affects billing",
                "explanation": """
                Organizations in Revenium represent billing entities and can have hierarchical structures:
                
                1. Parent organizations can have multiple child organizations
                2. Billing can be consolidated at parent level or separated by child
                3. Credentials inherit organization context for proper cost allocation
                4. Subscription pricing may vary by organization tier or relationship
                
                Incorrect organization assignment can lead to billing to wrong entity.
                """,
                "critical_fields": ["organizationId"],
                "business_impact": "Wrong organization assignment causes billing disputes and revenue recognition issues",
            },
            "subscription_metering": {
                "description": "How subscriptions control metering and pricing",
                "explanation": """
                Subscriptions define the billing rules and pricing for customer usage:
                
                1. Each subscription has specific pricing tiers and metering rules
                2. Usage is measured according to subscription's metering configuration
                3. Multiple credentials can share a subscription for consolidated billing
                4. Subscription status (active/inactive) affects billing processing
                
                Credentials without subscription associations cannot generate billable usage.
                """,
                "critical_fields": ["subscriptionIds"],
                "business_impact": "Missing subscription links result in unbilled usage and revenue loss",
            },
        }

    def get_business_guidance(self, scenario: BusinessScenario) -> BusinessGuidance:
        """Get business guidance for a specific scenario."""
        return self.business_scenarios.get(scenario)

    def get_billing_relationship_explanation(self, relationship_type: str) -> Dict[str, Any]:
        """Get explanation of billing relationships."""
        return self.billing_relationships.get(relationship_type, {})

    def generate_onboarding_checklist(self, customer_info: Dict[str, Any]) -> Dict[str, Any]:
        """Generate customer onboarding checklist."""
        return {
            "customer": customer_info.get("name", "Unknown"),
            "checklist": [
                {
                    "step": "Verify Organization Setup",
                    "description": "Confirm customer organization exists and is properly configured",
                    "validation": f"Organization '{customer_info.get('organization', 'TBD')}' is active",
                    "business_impact": "Ensures billing goes to correct entity",
                },
                {
                    "step": "Validate Subscriber Information",
                    "description": "Verify subscriber email and permissions",
                    "validation": f"Subscriber '{customer_info.get('email', 'TBD')}' has appropriate access",
                    "business_impact": "Enables proper user attribution and access control",
                },
                {
                    "step": "Create Unique Credential",
                    "description": "Generate credential with unique external ID",
                    "validation": "External ID is unique across all credentials",
                    "business_impact": "Prevents authentication conflicts and security issues",
                },
                {
                    "step": "Link to Subscription",
                    "description": "Associate credential with appropriate subscription(s)",
                    "validation": "Credential is linked to active subscription with proper pricing",
                    "business_impact": "Enables billing automation and revenue recognition",
                },
                {
                    "step": "Test Billing Flow",
                    "description": "Verify end-to-end billing with test usage",
                    "validation": "Test API calls generate expected billing data",
                    "business_impact": "Confirms billing automation is working correctly",
                },
            ],
            "success_criteria": [
                "Customer can authenticate successfully",
                "Usage appears in billing system within 1 hour",
                "Costs are calculated correctly",
                "Customer can view usage in dashboard",
            ],
            "common_issues": [
                "Credential not linked to subscription",
                "External ID conflicts with existing credentials",
                "Organization hierarchy misconfiguration",
                "Subscription pricing not properly configured",
            ],
        }

    def generate_troubleshooting_guide(self, issue_description: str) -> Dict[str, Any]:
        """Generate troubleshooting guide based on issue description."""
        # Simple keyword-based routing - could be enhanced with NLP
        issue_lower = issue_description.lower()

        if "billing" in issue_lower or "cost" in issue_lower or "usage" in issue_lower:
            scenario = BusinessScenario.BILLING_TROUBLESHOOTING
        elif "audit" in issue_lower or "review" in issue_lower:
            scenario = BusinessScenario.CREDENTIAL_AUDIT
        elif "new" in issue_lower or "onboard" in issue_lower:
            scenario = BusinessScenario.NEW_CUSTOMER_ONBOARDING
        else:
            scenario = BusinessScenario.BILLING_TROUBLESHOOTING  # Default

        guidance = self.get_business_guidance(scenario)

        return {
            "issue": issue_description,
            "recommended_scenario": scenario.value,
            "guidance": guidance,
            "immediate_actions": guidance.step_by_step_process[:3] if guidance else [],
            "key_questions": [
                "Is the credential linked to an active subscription?",
                "Does the external ID match the customer's configuration?",
                "Are there any authentication errors in the logs?",
                "Has anything changed recently in the credential or subscription setup?",
            ],
        }

    def get_billing_impact_explanation(
        self, operation: str, credential_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get detailed explanation of billing impact for an operation."""
        impact = {
            "operation": operation,
            "immediate_impact": "",
            "long_term_impact": "",
            "risk_level": "low",
            "mitigation_steps": [],
        }

        if operation == "create":
            impact["immediate_impact"] = (
                "New credential will enable billing automation for associated subscriptions"
            )
            impact["long_term_impact"] = "Ongoing usage will be properly tracked and billed"
            impact["risk_level"] = "low"
            impact["mitigation_steps"] = [
                "Verify subscription associations are correct",
                "Test with small usage before full deployment",
                "Monitor billing data for first 24-48 hours",
            ]

        elif operation == "update":
            if "subscriptionIds" in credential_data:
                impact["immediate_impact"] = (
                    "Subscription associations will change, affecting billing attribution"
                )
                impact["risk_level"] = "medium"
            if "externalSecret" in credential_data:
                impact["immediate_impact"] = (
                    "Secret change may temporarily disrupt billing until systems are updated"
                )
                impact["risk_level"] = "medium"

            impact["long_term_impact"] = (
                "Updated configuration will affect ongoing billing calculations"
            )
            impact["mitigation_steps"] = [
                "Use dry_run to preview changes",
                "Coordinate with customer for secret updates",
                "Monitor billing automation after changes",
            ]

        elif operation == "delete":
            impact["immediate_impact"] = (
                "Billing automation will stop for this credential immediately"
            )
            impact["long_term_impact"] = (
                "Historical billing data remains, but no new usage will be tracked"
            )
            impact["risk_level"] = "high"
            impact["mitigation_steps"] = [
                "Ensure customer has alternative credentials if needed",
                "Verify no active subscriptions depend solely on this credential",
                "Document reason for deletion for audit trail",
            ]

        return impact
