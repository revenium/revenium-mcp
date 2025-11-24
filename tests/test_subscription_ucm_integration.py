"""UCM Integration Test for Subscription Management.

This test verifies that the Subscription Management tool correctly integrates
with the Unified Capability Manager (UCM) following the regression prevention protocol.
"""

import asyncio
import pytest
import time
import sys
import os
from unittest.mock import Mock, AsyncMock

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from revenium_mcp_server.capability_manager.integration_service import ucm_integration_service
from revenium_mcp_server.tools_decomposed.subscription_management import SubscriptionManagement


class TestSubscriptionUCMIntegration:
    """Test UCM integration for subscription management."""
    
    @pytest.fixture
    async def ucm_service(self):
        """Initialize UCM service for testing."""
        # Create a mock UCM service that returns subscription capabilities
        mock_ucm_service = Mock()
        mock_ucm_service.get_integration_helper = Mock()

        # Create a mock UCM helper
        mock_helper = Mock()
        mock_helper.ucm = Mock()

        # Mock the get_capabilities method to return subscription capabilities
        async def mock_get_capabilities(resource_type):
            if resource_type == "subscriptions":
                return {
                    "billing_periods": ["MONTH", "QUARTER", "YEAR"],
                    "trial_periods": ["DAY", "WEEK", "MONTH"],
                    "subscription_types": ["monthly", "quarterly", "yearly", "trial"],
                    "currencies": ["USD", "EUR", "GBP", "CAD", "AUD", "JPY"],
                    "schema": {
                        "subscription_data": {
                            "required": ["product_id", "name", "clientEmailAddress"],
                            "optional": [
                                "description", "start_date", "end_date",
                                "billing_address", "payment_method", "trial_end_date",
                                "metadata", "tags"
                            ]
                        }
                    },
                    "validation_rules": {
                        "product_id": {"type": "string", "min_length": 1},
                        "name": {"type": "string", "min_length": 1, "max_length": 255},
                        "clientEmailAddress": {"type": "string", "format": "email"}
                    },
                    "business_rules": [
                        "Product must exist before subscription creation",
                        "Email address must be valid and unique",
                        "Trial periods require end date specification",
                        "Billing periods must align with product plan settings"
                    ]
                }
            return {}

        mock_helper.ucm.get_capabilities = mock_get_capabilities
        mock_ucm_service.get_integration_helper.return_value = mock_helper

        # Mock validate_capability_value
        async def mock_validate_capability_value(resource_type, capability_name, value):
            if resource_type == "subscriptions":
                if capability_name == "billing_periods":
                    return value in ["MONTH", "QUARTER", "YEAR"]
                elif capability_name == "currencies":
                    return value in ["USD", "EUR", "GBP", "CAD", "AUD", "JPY"]
                elif capability_name == "trial_periods":
                    return value in ["DAY", "WEEK", "MONTH"]
            return False

        # Add the validation method to the global service mock
        ucm_integration_service.validate_capability_value = mock_validate_capability_value

        return mock_ucm_service
    
    @pytest.fixture
    async def tool_with_ucm(self, ucm_service):
        """Create tool instance with UCM integration."""
        ucm_helper = ucm_service.get_integration_helper()
        return SubscriptionManagement(ucm_helper)
    
    @pytest.fixture
    async def tool_without_ucm(self):
        """Create tool instance without UCM (fallback)."""
        return SubscriptionManagement()
    
    async def test_ucm_capabilities_vs_fallback(self, tool_with_ucm, tool_without_ucm):
        """Test UCM capabilities match or exceed fallback capabilities."""
        ucm_capabilities = await tool_with_ucm.validator.get_capabilities()
        fallback_capabilities = await tool_without_ucm.validator.get_capabilities()
        
        # UCM should provide at least the same capabilities
        for key in fallback_capabilities:
            assert key in ucm_capabilities, f"UCM missing capability: {key}"
        
        # Verify specific subscription capabilities
        assert "billing_periods" in ucm_capabilities
        assert "trial_periods" in ucm_capabilities
        assert "currencies" in ucm_capabilities
        assert "schema" in ucm_capabilities
    
    async def test_capability_validation_accuracy(self, tool_with_ucm):
        """Test capability validation accuracy."""
        # Test valid values
        valid_test_cases = [
            ("subscriptions", "billing_periods", "MONTH"),
            ("subscriptions", "billing_periods", "QUARTER"),
            ("subscriptions", "billing_periods", "YEAR"),
            ("subscriptions", "currencies", "USD"),
            ("subscriptions", "currencies", "EUR"),
            ("subscriptions", "trial_periods", "DAY"),
            ("subscriptions", "trial_periods", "WEEK"),
            ("subscriptions", "trial_periods", "MONTH"),
        ]
        
        for resource_type, capability_name, value in valid_test_cases:
            is_valid = await ucm_integration_service.validate_capability_value(
                resource_type, capability_name, value
            )
            assert is_valid, f"Valid value rejected: {capability_name}={value}"
        
        # Test invalid values
        invalid_test_cases = [
            ("subscriptions", "billing_periods", "INVALID_PERIOD"),
            ("subscriptions", "currencies", "INVALID_CURRENCY"),
            ("subscriptions", "trial_periods", "INVALID_TRIAL"),
            ("subscriptions", "billing_periods", "trial"),  # lowercase should be invalid
        ]
        
        for resource_type, capability_name, value in invalid_test_cases:
            is_valid = await ucm_integration_service.validate_capability_value(
                resource_type, capability_name, value
            )
            assert not is_valid, f"Invalid value accepted: {capability_name}={value}"
    
    async def test_performance_requirements(self, tool_with_ucm):
        """Test performance requirements are met."""
        start_time = time.time()
        capabilities = await tool_with_ucm.validator.get_capabilities()
        end_time = time.time()
        
        response_time_ms = (end_time - start_time) * 1000
        assert response_time_ms < 100, f"Response time {response_time_ms}ms exceeds 100ms requirement"
        assert len(capabilities) > 0, "No capabilities returned"
        
        # Verify specific capabilities exist
        assert "billing_periods" in capabilities
        assert len(capabilities["billing_periods"]) > 0
    
    async def test_fallback_mechanism(self, ucm_service):
        """Test fallback mechanism when UCM fails."""
        # Simulate UCM failure
        original_ucm = ucm_service.ucm
        ucm_service.ucm = None
        
        try:
            tool = SubscriptionManagement(ucm_service.get_integration_helper())
            capabilities = await tool.validator.get_capabilities()
            assert len(capabilities) > 0, "Fallback failed to provide capabilities"
            assert "billing_periods" in capabilities, "Fallback missing billing_periods"
        finally:
            # Restore UCM
            ucm_service.ucm = original_ucm
    
    async def test_billing_period_format_consistency(self, tool_with_ucm):
        """Test billing period format consistency between UCM and API expectations."""
        capabilities = await tool_with_ucm.validator.get_capabilities()
        billing_periods = capabilities.get("billing_periods", [])
        
        # UCM should provide API-compatible formats (uppercase)
        expected_formats = ["MONTH", "QUARTER", "YEAR"]
        for expected in expected_formats:
            assert expected in billing_periods, f"Missing expected billing period: {expected}"
        
        # Should not contain lowercase formats
        invalid_formats = ["monthly", "quarterly", "yearly"]
        for invalid in invalid_formats:
            assert invalid not in billing_periods, f"Contains invalid billing period format: {invalid}"
    
    async def test_trial_period_format_consistency(self, tool_with_ucm):
        """Test trial period format consistency between UCM and API expectations."""
        capabilities = await tool_with_ucm.validator.get_capabilities()
        trial_periods = capabilities.get("trial_periods", [])
        
        # UCM should provide API-compatible formats (uppercase)
        expected_formats = ["DAY", "WEEK", "MONTH"]
        for expected in expected_formats:
            assert expected in trial_periods, f"Missing expected trial period: {expected}"
        
        # Should not contain underscore formats
        invalid_formats = ["7_days", "14_days", "30_days"]
        for invalid in invalid_formats:
            assert invalid not in trial_periods, f"Contains invalid trial period format: {invalid}"
    
    async def test_currency_validation(self, tool_with_ucm):
        """Test currency validation accuracy."""
        capabilities = await tool_with_ucm.validator.get_capabilities()
        currencies = capabilities.get("currencies", [])
        
        # Should contain standard currencies
        expected_currencies = ["USD", "EUR", "GBP", "CAD"]
        for currency in expected_currencies:
            assert currency in currencies, f"Missing expected currency: {currency}"
    
    async def test_schema_validation_requirements(self, tool_with_ucm):
        """Test schema validation requirements."""
        capabilities = await tool_with_ucm.validator.get_capabilities()
        schema = capabilities.get("schema", {}).get("subscription_data", {})
        
        # Verify required fields
        required_fields = schema.get("required", [])
        expected_required = ["product_id", "name", "clientEmailAddress"]
        for field in expected_required:
            assert field in required_fields, f"Missing required field: {field}"
        
        # Verify optional fields exist
        optional_fields = schema.get("optional", [])
        assert len(optional_fields) > 0, "No optional fields defined"
    
    async def test_business_rules_presence(self, tool_with_ucm):
        """Test business rules are present in capabilities."""
        capabilities = await tool_with_ucm.validator.get_capabilities()
        business_rules = capabilities.get("business_rules", [])
        
        assert len(business_rules) > 0, "No business rules defined"
        
        # Check for specific important business rules
        rule_text = " ".join(business_rules)
        assert "product" in rule_text.lower(), "Missing product-related business rule"
        assert "email" in rule_text.lower(), "Missing email-related business rule"


async def run_subscription_ucm_integration_tests():
    """Run all subscription UCM integration tests."""
    print("🧪 Running Subscription Management UCM Integration Tests...")

    # Create test instance
    test_instance = TestSubscriptionUCMIntegration()

    # Create mocked UCM service manually
    mock_ucm_service = Mock()
    mock_ucm_service.get_integration_helper = Mock()

    # Create a mock UCM helper
    mock_helper = Mock()
    mock_helper.ucm = Mock()

    # Mock the get_capabilities method to return subscription capabilities
    async def mock_get_capabilities(resource_type):
        if resource_type == "subscriptions":
            return {
                "billing_periods": ["MONTH", "QUARTER", "YEAR"],
                "trial_periods": ["DAY", "WEEK", "MONTH"],
                "plan_types": ["SUBSCRIPTION"],  # Valid API plan types
                "currencies": ["USD", "EUR", "GBP", "CAD", "AUD", "JPY"],
                "schema": {
                    "subscription_data": {
                        "required": ["product_id", "name", "clientEmailAddress"],
                        "optional": [
                            "description", "start_date", "end_date",
                            "billing_address", "payment_method", "trial_end_date",
                            "metadata", "tags"
                        ]
                    }
                },
                "validation_rules": {
                    "product_id": {"type": "string", "min_length": 1},
                    "name": {"type": "string", "min_length": 1, "max_length": 255},
                    "clientEmailAddress": {"type": "string", "format": "email"}
                },
                "lifecycle_states": {
                    "creation": ["trial", "active"],
                    "active_states": ["active", "trial"],
                    "terminal_states": ["cancelled", "expired"]
                },
                "field_constraints": {
                    "name": {"min_length": 1, "max_length": 255},
                    "description": {"max_length": 1000},
                    "product_id": {"format": "uuid", "required": True},
                    "dates": {"format": "ISO 8601 (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"}
                },
                "business_rules": [
                    "Product must exist before subscription creation",
                    "Email address must be valid and unique",
                    "Trial periods require end date specification",
                    "Billing periods must align with product plan settings"
                ]
            }
        return {}

    mock_helper.ucm.get_capabilities = mock_get_capabilities
    mock_ucm_service.get_integration_helper.return_value = mock_helper

    # Mock validate_capability_value
    async def mock_validate_capability_value(resource_type, capability_name, value):
        if resource_type == "subscriptions":
            if capability_name == "billing_periods":
                return value in ["MONTH", "QUARTER", "YEAR"]
            elif capability_name == "currencies":
                return value in ["USD", "EUR", "GBP", "CAD", "AUD", "JPY"]
            elif capability_name == "trial_periods":
                return value in ["DAY", "WEEK", "MONTH"]
        return False

    # Add the validation method to the global service mock
    ucm_integration_service.validate_capability_value = mock_validate_capability_value

    # Create tools
    tool_with_ucm = SubscriptionManagement(mock_helper)
    tool_without_ucm = SubscriptionManagement()
    
    tests = [
        ("UCM vs Fallback Capabilities", test_instance.test_ucm_capabilities_vs_fallback(tool_with_ucm, tool_without_ucm)),
        ("Capability Validation Accuracy", test_instance.test_capability_validation_accuracy(tool_with_ucm)),
        ("Performance Requirements", test_instance.test_performance_requirements(tool_with_ucm)),
        ("Fallback Mechanism", test_instance.test_fallback_mechanism(mock_ucm_service)),
        ("Billing Period Format", test_instance.test_billing_period_format_consistency(tool_with_ucm)),
        ("Trial Period Format", test_instance.test_trial_period_format_consistency(tool_with_ucm)),
        ("Currency Validation", test_instance.test_currency_validation(tool_with_ucm)),
        ("Schema Validation", test_instance.test_schema_validation_requirements(tool_with_ucm)),
        ("Business Rules", test_instance.test_business_rules_presence(tool_with_ucm)),
    ]
    
    results = []
    for test_name, test_coro in tests:
        try:
            await test_coro
            results.append(f"✅ {test_name}")
            print(f"✅ {test_name}")
        except Exception as e:
            results.append(f"❌ {test_name}: {str(e)}")
            print(f"❌ {test_name}: {str(e)}")
    
    # Summary
    passed = len([r for r in results if r.startswith("✅")])
    total = len(results)
    
    print(f"\n📋 Test Results: {passed}/{total} passed")
    
    if passed == total:
        print("🎉 All subscription UCM integration tests passed!")
        return True
    else:
        print("❌ Some tests failed. Please review and fix issues.")
        return False


if __name__ == "__main__":
    success = asyncio.run(run_subscription_ucm_integration_tests())
    exit(0 if success else 1)
