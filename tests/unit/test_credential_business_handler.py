"""Unit tests for CredentialBusinessHandler.

Tests the business context handler which provides business guidance,
onboarding checklists, troubleshooting guides, and billing impact
analysis for credential operations.
"""

import pytest
from unittest.mock import patch, MagicMock

from src.revenium_mcp_server.tools_decomposed.credential_business_handler import (
    CredentialBusinessHandler,
)


@pytest.fixture
def handler():
    """Create a CredentialBusinessHandler instance."""
    return CredentialBusinessHandler()


class TestGetBusinessGuidance:
    """Test get_business_guidance with valid and invalid scenarios."""

    @pytest.mark.asyncio
    async def test_invalid_scenario_returns_error_with_available(self, handler):
        """Invalid scenario name returns error with list of available scenarios."""
        result = await handler.get_business_guidance({"scenario": "totally_made_up"})
        assert result["action"] == "get_business_guidance"
        assert "error" in result
        assert "totally_made_up" in result["error"]
        assert "available_scenarios" in result
        assert len(result["available_scenarios"]) > 0

    @pytest.mark.asyncio
    async def test_valid_scenario_returns_guidance(self, handler):
        """Valid scenario returns structured guidance with related actions."""
        result = await handler.get_business_guidance(
            {"scenario": "new_customer_onboarding"}
        )
        assert result["action"] == "get_business_guidance"
        assert result["scenario"] == "new_customer_onboarding"
        assert "guidance" in result
        assert "related_actions" in result

    @pytest.mark.asyncio
    async def test_default_scenario_is_onboarding(self, handler):
        """Missing scenario defaults to new_customer_onboarding."""
        result = await handler.get_business_guidance({})
        assert result["scenario"] == "new_customer_onboarding"


class TestGetOnboardingChecklist:
    """Test get_onboarding_checklist."""

    @pytest.mark.asyncio
    async def test_returns_checklist_structure(self, handler):
        """Returns checklist with usage tips and next steps."""
        result = await handler.get_onboarding_checklist({})
        assert result["action"] == "get_onboarding_checklist"
        assert "checklist" in result
        assert "usage_tip" in result
        assert "next_steps" in result
        assert isinstance(result["next_steps"], list)



class TestGetTroubleshootingGuide:
    """Test get_troubleshooting_guide."""

    @pytest.mark.asyncio
    async def test_missing_description_returns_error(self, handler):
        """Missing issue_description returns error with examples."""
        result = await handler.get_troubleshooting_guide({})
        assert "error" in result
        assert "examples" in result
        assert len(result["examples"]) > 0

    @pytest.mark.asyncio
    async def test_with_description_returns_guide(self, handler):
        """Valid issue description returns troubleshooting guide."""
        result = await handler.get_troubleshooting_guide(
            {"issue_description": "Customer billing is missing for last week"}
        )
        assert result["action"] == "get_troubleshooting_guide"
        assert result["issue"] == "Customer billing is missing for last week"
        assert "troubleshooting_guide" in result
        assert "immediate_actions" in result
        assert "key_questions" in result


class TestAnalyzeBillingImpact:
    """Test analyze_billing_impact."""

    @pytest.mark.asyncio
    async def test_returns_impact_analysis(self, handler):
        """Returns billing impact analysis with recommendations."""
        result = await handler.analyze_billing_impact(
            {"operation": "create", "credential_data": {"label": "Test Key"}}
        )
        assert result["action"] == "analyze_billing_impact"
        assert result["operation"] == "create"
        assert "impact_analysis" in result
        assert "billing_relationships" in result
        assert "recommendations" in result

    @pytest.mark.asyncio
    async def test_billing_relationships_populated(self, handler):
        """Billing relationships include expected relationship types."""
        result = await handler.analyze_billing_impact({})
        relationships = result["billing_relationships"]
        assert "credential_to_subscription" in relationships
        assert "organization_hierarchy" in relationships
        assert "subscription_metering" in relationships

    @pytest.mark.asyncio
    async def test_default_operation_is_create(self, handler):
        """Default operation is 'create' when not specified."""
        result = await handler.analyze_billing_impact({})
        assert result["operation"] == "create"
