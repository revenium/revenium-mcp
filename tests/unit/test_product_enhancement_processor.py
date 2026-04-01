"""Unit tests for ProductEnhancementProcessor and ProductValidator.get_examples.

Covers:
- ProductEnhancementProcessor.create_from_description (NLP fallback, setup fee, source assignment)
- ProductEnhancementProcessor._validate_setup_fee_configuration (fee types, amount bounds)
- ProductEnhancementProcessor._generate_setup_fee_suggestions (high/low fee detection)
- ProductEnhancementProcessor._handle_ambiguous_pricing (clarification response)
- ProductEnhancementProcessor._handle_single_value_pricing (setup mention vs plain)
- ProductEnhancementProcessor._handle_no_values_detected (no amounts)
- ProductValidator.get_examples (template examples, create_with_subscription cases)
"""

import pytest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed.product_management import (
    ProductEnhancementProcessor,
    ProductValidator,
)
from src.revenium_mcp_server.common.error_handling import ToolError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(**overrides):
    client = MagicMock()
    client.team_id = "team_test"
    client.get_sources = AsyncMock(return_value={})
    client._extract_embedded_data = MagicMock(return_value=[])
    client.create_product = AsyncMock(return_value={"id": "p_new", "name": "Created"})
    for k, v in overrides.items():
        setattr(client, k, v)
    return client


def _make_processor(client=None, nlp_processor=None, has_nlp=True):
    """Build a ProductEnhancementProcessor with mocked internals."""
    if client is None:
        client = _make_client()
    proc = object.__new__(ProductEnhancementProcessor)
    proc.client = client
    proc.ucm_helper = None
    if has_nlp:
        proc.nlp_processor = nlp_processor or MagicMock()
        proc.template_library = MagicMock()
        proc.error_handler = MagicMock()
        proc.clarification_engine = MagicMock()
    else:
        proc.nlp_processor = None
        proc.template_library = None
        proc.error_handler = None
        proc.clarification_engine = None
    return proc


def _detected_value(amount):
    """Create a simple namespace that mimics a detected pricing value."""
    return SimpleNamespace(amount=amount)


# ===========================================================================
# ProductValidator.get_examples
# ===========================================================================


class TestProductValidatorGetExamples:
    """Tests for ProductValidator.get_examples."""

    def _make_validator(self):
        v = object.__new__(ProductValidator)
        return v

    @patch(
        "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
    )
    def test_get_examples_default_returns_three_templates(self, mock_engine_cls):
        mock_engine_cls.get_working_example.return_value = {"name": "example"}
        v = self._make_validator()
        result = v.get_examples()
        assert "basic_tier_example" in result
        assert "flat_fee_example" in result
        assert "hybrid_pricing_example" in result

    @patch(
        "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
    )
    def test_get_examples_basic_tier_uses_working_example(self, mock_engine_cls):
        working = {"name": "Working Example", "plan": {"type": "SUBSCRIPTION"}}
        mock_engine_cls.get_working_example.return_value = working
        v = self._make_validator()
        result = v.get_examples()
        assert result["basic_tier_example"]["template"]["product_data"] == working

    @patch(
        "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
    )
    def test_get_examples_flat_fee_has_correct_structure(self, mock_engine_cls):
        mock_engine_cls.get_working_example.return_value = {}
        v = self._make_validator()
        result = v.get_examples()
        flat = result["flat_fee_example"]
        assert flat["type"] == "flat_pricing"
        assert flat["copy_paste_ready"] is True
        tiers = flat["template"]["product_data"]["plan"]["tiers"]
        assert len(tiers) == 1
        assert tiers[0]["up_to"] is None
        assert tiers[0]["flat_amount"] == "79.99"

    @patch(
        "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
    )
    def test_get_examples_hybrid_has_unit_and_flat_amount(self, mock_engine_cls):
        mock_engine_cls.get_working_example.return_value = {}
        v = self._make_validator()
        result = v.get_examples()
        hybrid = result["hybrid_pricing_example"]
        tier = hybrid["template"]["product_data"]["plan"]["tiers"][0]
        assert "unit_amount" in tier
        assert "flat_amount" in tier

    @patch(
        "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
    )
    def test_get_examples_create_with_subscription_type(self, mock_engine_cls):
        mock_engine_cls.get_working_example.return_value = {}
        v = self._make_validator()
        result = v.get_examples(example_type="create_with_subscription")
        assert "coordinated_workflow_example" in result
        assert "troubleshooting_example" in result

    @patch(
        "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
    )
    def test_get_examples_subscription_has_prerequisites(self, mock_engine_cls):
        mock_engine_cls.get_working_example.return_value = {}
        v = self._make_validator()
        result = v.get_examples(example_type="create_with_subscription")
        workflow = result["coordinated_workflow_example"]
        assert "prerequisites" in workflow
        assert "step_1" in workflow["prerequisites"]
        assert workflow["prerequisites"]["step_1"]["required"] is True

    @patch(
        "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
    )
    def test_get_examples_subscription_template_has_plan(self, mock_engine_cls):
        mock_engine_cls.get_working_example.return_value = {}
        v = self._make_validator()
        result = v.get_examples(example_type="create_with_subscription")
        template = result["coordinated_workflow_example"]["template"]
        assert template["action"] == "create_with_subscription"
        assert "plan" in template["product_data"]

    @patch(
        "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
    )
    def test_get_examples_subscription_has_troubleshooting_errors(self, mock_engine_cls):
        mock_engine_cls.get_working_example.return_value = {}
        v = self._make_validator()
        result = v.get_examples(example_type="create_with_subscription")
        errors = result["troubleshooting_example"]["common_errors"]
        assert "no_sources_available" in errors
        assert "list_is_empty" in errors
        assert "validation_failed" in errors

    @patch(
        "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
    )
    def test_get_examples_subscription_automatic_enhancements(self, mock_engine_cls):
        mock_engine_cls.get_working_example.return_value = {}
        v = self._make_validator()
        result = v.get_examples(example_type="create_with_subscription")
        enhancements = result["coordinated_workflow_example"]["automatic_enhancements"]
        assert "sources" in enhancements
        assert "metering" in enhancements

    @patch(
        "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
    )
    def test_get_examples_unknown_type_returns_default(self, mock_engine_cls):
        mock_engine_cls.get_working_example.return_value = {"name": "ex"}
        v = self._make_validator()
        result = v.get_examples(example_type="unknown_type")
        # Unknown types fall through to default branch
        assert "basic_tier_example" in result


# ===========================================================================
# _validate_setup_fee_configuration
# ===========================================================================


class TestValidateSetupFeeConfiguration:
    """Tests for ProductEnhancementProcessor._validate_setup_fee_configuration."""

    def test_valid_subscription_type(self):
        proc = _make_processor()
        result = proc._validate_setup_fee_configuration(
            {"type": "SUBSCRIPTION", "flatAmount": 50.0, "name": "Setup"}
        )
        assert result["valid"] is True
        assert result["errors"] == []
        assert "per subscription" in result["enhanced_data"]["description"].lower()

    def test_valid_organization_type(self):
        proc = _make_processor()
        result = proc._validate_setup_fee_configuration(
            {"type": "ORGANIZATION", "flatAmount": 100.0, "name": "Org Setup"}
        )
        assert result["valid"] is True
        assert "per customer organization" in result["enhanced_data"]["description"].lower()
        assert result["enhanced_data"]["business_rule"] == "One-time fee per customer organization"

    def test_invalid_type_fails(self):
        proc = _make_processor()
        result = proc._validate_setup_fee_configuration(
            {"type": "INVALID", "flatAmount": 50.0}
        )
        assert result["valid"] is False
        assert any("Invalid setup fee type" in e for e in result["errors"])

    def test_none_type_fails(self):
        proc = _make_processor()
        result = proc._validate_setup_fee_configuration(
            {"type": None, "flatAmount": 50.0}
        )
        assert result["valid"] is False

    def test_zero_amount_fails(self):
        proc = _make_processor()
        result = proc._validate_setup_fee_configuration(
            {"type": "SUBSCRIPTION", "flatAmount": 0}
        )
        assert result["valid"] is False
        assert any("greater than 0" in e for e in result["errors"])

    def test_negative_amount_fails(self):
        proc = _make_processor()
        result = proc._validate_setup_fee_configuration(
            {"type": "SUBSCRIPTION", "flatAmount": -10}
        )
        assert result["valid"] is False

    def test_very_high_amount_warns(self):
        proc = _make_processor()
        result = proc._validate_setup_fee_configuration(
            {"type": "SUBSCRIPTION", "flatAmount": 150000}
        )
        assert result["valid"] is True
        assert any(">$100,000" in w for w in result["warnings"])

    def test_very_low_amount_warns(self):
        proc = _make_processor()
        result = proc._validate_setup_fee_configuration(
            {"type": "SUBSCRIPTION", "flatAmount": 0.50}
        )
        assert result["valid"] is True
        assert any("<$1" in w for w in result["warnings"])

    def test_non_numeric_amount_fails(self):
        proc = _make_processor()
        result = proc._validate_setup_fee_configuration(
            {"type": "SUBSCRIPTION", "flatAmount": "not_a_number"}
        )
        assert result["valid"] is False
        assert any("Invalid setup fee amount" in e for e in result["errors"])

    def test_missing_flat_amount_uses_default_zero(self):
        proc = _make_processor()
        result = proc._validate_setup_fee_configuration({"type": "SUBSCRIPTION"})
        assert result["valid"] is False
        assert any("greater than 0" in e for e in result["errors"])

    def test_enhanced_data_has_validation_timestamp(self):
        proc = _make_processor()
        result = proc._validate_setup_fee_configuration(
            {"type": "SUBSCRIPTION", "flatAmount": 25.0}
        )
        assert "validation_timestamp" in result["enhanced_data"]
        assert result["enhanced_data"]["validation_status"] == "valid"

    def test_invalid_result_has_invalid_status(self):
        proc = _make_processor()
        result = proc._validate_setup_fee_configuration(
            {"type": "BAD", "flatAmount": -5}
        )
        assert result["enhanced_data"]["validation_status"] == "invalid"

    def test_subscription_type_business_rule(self):
        proc = _make_processor()
        result = proc._validate_setup_fee_configuration(
            {"type": "SUBSCRIPTION", "flatAmount": 10.0}
        )
        assert result["enhanced_data"]["business_rule"] == "Fee charged for each subscription"

    def test_existing_description_preserved(self):
        proc = _make_processor()
        result = proc._validate_setup_fee_configuration(
            {"type": "ORGANIZATION", "flatAmount": 50.0, "description": "Onboarding fee"}
        )
        assert "Onboarding fee" in result["enhanced_data"]["description"]
        assert "per customer organization" in result["enhanced_data"]["description"].lower()

    def test_amount_exactly_one_no_warning(self):
        proc = _make_processor()
        result = proc._validate_setup_fee_configuration(
            {"type": "SUBSCRIPTION", "flatAmount": 1.0}
        )
        assert result["valid"] is True
        assert len(result["warnings"]) == 0

    def test_amount_exactly_100000_no_warning(self):
        proc = _make_processor()
        result = proc._validate_setup_fee_configuration(
            {"type": "SUBSCRIPTION", "flatAmount": 100000}
        )
        assert result["valid"] is True
        assert len(result["warnings"]) == 0

    def test_both_type_and_amount_invalid(self):
        proc = _make_processor()
        result = proc._validate_setup_fee_configuration(
            {"type": "WRONG", "flatAmount": "abc"}
        )
        assert result["valid"] is False
        assert len(result["errors"]) == 2


# ===========================================================================
# _generate_setup_fee_suggestions
# ===========================================================================


class TestGenerateSetupFeeSuggestions:
    """Tests for ProductEnhancementProcessor._generate_setup_fee_suggestions."""

    def test_high_amount_suggestion(self):
        proc = _make_processor()
        result = proc._generate_setup_fee_suggestions("some text", detected_amount=5000.0)
        assert any("High setup fee" in s for s in result)

    def test_low_amount_suggestion(self):
        proc = _make_processor()
        result = proc._generate_setup_fee_suggestions("some text", detected_amount=10.0)
        assert any("Low setup fee" in s for s in result)

    def test_no_amount_no_amount_suggestions(self):
        proc = _make_processor()
        result = proc._generate_setup_fee_suggestions("some text")
        assert not any("High setup fee" in s or "Low setup fee" in s for s in result)

    def test_customer_keyword_triggers_org_suggestion(self):
        proc = _make_processor()
        result = proc._generate_setup_fee_suggestions("setup for each customer account")
        assert any("ORGANIZATION" in s for s in result)

    def test_organization_keyword_triggers_org_suggestion(self):
        proc = _make_processor()
        result = proc._generate_setup_fee_suggestions("fee per organization")
        assert any("ORGANIZATION" in s for s in result)

    def test_subscription_keyword_triggers_sub_suggestion(self):
        proc = _make_processor()
        result = proc._generate_setup_fee_suggestions("fee per subscription plan")
        assert any("SUBSCRIPTION type setup fee" in s or "subscriptions/plans" in s for s in result)

    def test_service_keyword_triggers_sub_suggestion(self):
        proc = _make_processor()
        result = proc._generate_setup_fee_suggestions("activation fee for the service")
        assert any("subscriptions/plans" in s for s in result)

    def test_always_includes_general_guidance(self):
        proc = _make_processor()
        result = proc._generate_setup_fee_suggestions("random text")
        assert any("SUBSCRIPTION type" in s and "most common" in s for s in result)
        assert any("ORGANIZATION type" in s for s in result)
        assert any("clarify_pricing" in s for s in result)

    def test_amount_boundary_1001_is_high(self):
        proc = _make_processor()
        result = proc._generate_setup_fee_suggestions("text", detected_amount=1001.0)
        assert any("High setup fee" in s for s in result)

    def test_amount_boundary_49_is_low(self):
        proc = _make_processor()
        result = proc._generate_setup_fee_suggestions("text", detected_amount=49.0)
        assert any("Low setup fee" in s for s in result)

    def test_amount_50_is_neither_high_nor_low(self):
        proc = _make_processor()
        result = proc._generate_setup_fee_suggestions("text", detected_amount=50.0)
        assert not any("High setup fee" in s or "Low setup fee" in s for s in result)

    def test_amount_1000_is_neither_high_nor_low(self):
        proc = _make_processor()
        result = proc._generate_setup_fee_suggestions("text", detected_amount=1000.0)
        assert not any("High setup fee" in s or "Low setup fee" in s for s in result)

    def test_client_keyword_triggers_org_suggestion(self):
        proc = _make_processor()
        result = proc._generate_setup_fee_suggestions("setup fee for the client")
        assert any("ORGANIZATION" in s for s in result)

    def test_company_keyword_triggers_org_suggestion(self):
        proc = _make_processor()
        result = proc._generate_setup_fee_suggestions("per company activation")
        assert any("ORGANIZATION" in s for s in result)


# ===========================================================================
# _handle_ambiguous_pricing
# ===========================================================================


class TestHandleAmbiguousPricing:
    """Tests for ProductEnhancementProcessor._handle_ambiguous_pricing."""

    @pytest.mark.asyncio
    async def test_returns_clarification_with_amounts(self):
        proc = _make_processor()
        values = [_detected_value(500), _detected_value(99)]
        result = await proc._handle_ambiguous_pricing("service with $500 and $99", values, {})
        assert "clarification" in result
        assert "$500" in result["analysis"]["detected_amounts"]
        assert "$99" in result["analysis"]["detected_amounts"]

    @pytest.mark.asyncio
    async def test_total_values_count(self):
        proc = _make_processor()
        values = [_detected_value(100), _detected_value(200), _detected_value(300)]
        result = await proc._handle_ambiguous_pricing("text", values, {})
        assert result["analysis"]["total_values"] == 3

    @pytest.mark.asyncio
    async def test_original_input_preserved(self):
        proc = _make_processor()
        text = "my special pricing text"
        result = await proc._handle_ambiguous_pricing(text, [_detected_value(10)], {})
        assert result["analysis"]["original_input"] == text

    @pytest.mark.asyncio
    async def test_guidance_has_required_clarification(self):
        proc = _make_processor()
        result = await proc._handle_ambiguous_pricing("text", [_detected_value(50)], {})
        assert len(result["guidance"]["required_clarification"]) == 3

    @pytest.mark.asyncio
    async def test_setup_fee_options_present(self):
        proc = _make_processor()
        result = await proc._handle_ambiguous_pricing("text", [_detected_value(50)], {})
        assert "per_subscription" in result["setup_fee_options"]
        assert "per_customer" in result["setup_fee_options"]

    @pytest.mark.asyncio
    async def test_per_subscription_has_api_format(self):
        proc = _make_processor()
        result = await proc._handle_ambiguous_pricing("text", [_detected_value(50)], {})
        api_format = result["setup_fee_options"]["per_subscription"]["api_format"]
        assert api_format["type"] == "SUBSCRIPTION"

    @pytest.mark.asyncio
    async def test_per_customer_has_api_format(self):
        proc = _make_processor()
        result = await proc._handle_ambiguous_pricing("text", [_detected_value(50)], {})
        api_format = result["setup_fee_options"]["per_customer"]["api_format"]
        assert api_format["type"] == "ORGANIZATION"

    @pytest.mark.asyncio
    async def test_ucm_capabilities_ignored(self):
        proc = _make_processor()
        # ucm_capabilities param is suppressed; should still work
        result = await proc._handle_ambiguous_pricing("t", [_detected_value(1)], {"foo": "bar"})
        assert result["ucm_status"] == "UCM Integration: Active"

    @pytest.mark.asyncio
    async def test_next_steps_populated(self):
        proc = _make_processor()
        result = await proc._handle_ambiguous_pricing("text", [_detected_value(50)], {})
        assert len(result["next_steps"]) >= 3

    @pytest.mark.asyncio
    async def test_guidance_examples_present(self):
        proc = _make_processor()
        result = await proc._handle_ambiguous_pricing("text", [_detected_value(50)], {})
        assert len(result["guidance"]["examples"]) == 4


# ===========================================================================
# _handle_single_value_pricing
# ===========================================================================


class TestHandleSingleValuePricing:
    """Tests for ProductEnhancementProcessor._handle_single_value_pricing."""

    @pytest.mark.asyncio
    async def test_setup_mentioned_returns_clarification(self):
        proc = _make_processor()
        val = _detected_value(100)
        result = await proc._handle_single_value_pricing("setup fee of $100", val, {})
        assert "Setup fee mentioned" in result["clarification"]
        assert result["analysis"]["setup_fee_mentioned"] is True

    @pytest.mark.asyncio
    async def test_initial_keyword_triggers_setup_path(self):
        proc = _make_processor()
        val = _detected_value(200)
        result = await proc._handle_single_value_pricing("initial payment of $200", val, {})
        assert result["analysis"]["setup_fee_mentioned"] is True

    @pytest.mark.asyncio
    async def test_onboarding_keyword_triggers_setup_path(self):
        proc = _make_processor()
        val = _detected_value(50)
        result = await proc._handle_single_value_pricing("onboarding cost $50", val, {})
        assert result["analysis"]["setup_fee_mentioned"] is True

    @pytest.mark.asyncio
    async def test_activation_keyword_triggers_setup_path(self):
        proc = _make_processor()
        val = _detected_value(75)
        result = await proc._handle_single_value_pricing("activation fee $75", val, {})
        assert result["analysis"]["setup_fee_mentioned"] is True

    @pytest.mark.asyncio
    async def test_implementation_keyword_triggers_setup_path(self):
        proc = _make_processor()
        val = _detected_value(300)
        result = await proc._handle_single_value_pricing("implementation cost $300", val, {})
        assert result["analysis"]["setup_fee_mentioned"] is True

    @pytest.mark.asyncio
    async def test_one_time_keyword_triggers_setup_path(self):
        proc = _make_processor()
        val = _detected_value(150)
        result = await proc._handle_single_value_pricing("one-time charge $150", val, {})
        assert result["analysis"]["setup_fee_mentioned"] is True

    @pytest.mark.asyncio
    async def test_no_setup_returns_subscription_interpretation(self):
        proc = _make_processor()
        val = _detected_value(29)
        result = await proc._handle_single_value_pricing("monthly plan for $29", val, {})
        assert result["clarification"] == "Single subscription fee detected"
        assert result["analysis"]["interpretation"] == "Recurring subscription fee"

    @pytest.mark.asyncio
    async def test_no_setup_detected_amount_formatted(self):
        proc = _make_processor()
        val = _detected_value(99)
        result = await proc._handle_single_value_pricing("service for $99", val, {})
        assert result["analysis"]["detected_amount"] == "$99"

    @pytest.mark.asyncio
    async def test_setup_path_has_setup_fee_options(self):
        proc = _make_processor()
        val = _detected_value(100)
        result = await proc._handle_single_value_pricing("setup fee $100", val, {})
        assert "per_subscription" in result["setup_fee_options"]
        assert "per_customer" in result["setup_fee_options"]

    @pytest.mark.asyncio
    async def test_setup_path_has_setup_fee_format(self):
        proc = _make_processor()
        val = _detected_value(100)
        result = await proc._handle_single_value_pricing("setup cost $100", val, {})
        assert "new_structure" in result["setup_fee_format"]
        assert "migration_note" in result["setup_fee_format"]

    @pytest.mark.asyncio
    async def test_no_setup_confirmation_needed(self):
        proc = _make_processor()
        val = _detected_value(50)
        result = await proc._handle_single_value_pricing("just $50", val, {})
        assert "confirmation_needed" in result

    @pytest.mark.asyncio
    async def test_ucm_capabilities_suppressed(self):
        proc = _make_processor()
        val = _detected_value(10)
        # Should not raise even with non-empty ucm_capabilities
        result = await proc._handle_single_value_pricing("$10 plan", val, {"key": "val"})
        assert isinstance(result, dict)
        assert "confirmation_needed" in result or "price" in result or "value" in result


# ===========================================================================
# _handle_no_values_detected
# ===========================================================================


class TestHandleNoValuesDetected:
    """Tests for ProductEnhancementProcessor._handle_no_values_detected."""

    @pytest.mark.asyncio
    async def test_returns_no_values_clarification(self):
        proc = _make_processor()
        result = await proc._handle_no_values_detected("some text", {})
        assert result["clarification"] == "No pricing values detected"

    @pytest.mark.asyncio
    async def test_original_input_in_analysis(self):
        proc = _make_processor()
        result = await proc._handle_no_values_detected("input text here", {})
        assert result["analysis"]["original_input"] == "input text here"

    @pytest.mark.asyncio
    async def test_detected_amounts_empty(self):
        proc = _make_processor()
        result = await proc._handle_no_values_detected("text", {})
        assert result["analysis"]["detected_amounts"] == []

    @pytest.mark.asyncio
    async def test_guidance_has_examples(self):
        proc = _make_processor()
        result = await proc._handle_no_values_detected("text", {})
        assert len(result["guidance"]["examples"]) == 3

    @pytest.mark.asyncio
    async def test_supported_currencies_from_capabilities(self):
        proc = _make_processor()
        caps = {"currencies": ["USD", "EUR"], "billing_periods": ["MONTH"]}
        result = await proc._handle_no_values_detected("text", caps)
        assert result["supported_currencies"] == ["USD", "EUR"]
        assert result["supported_billing_periods"] == ["MONTH"]

    @pytest.mark.asyncio
    async def test_empty_capabilities_gives_empty_lists(self):
        proc = _make_processor()
        result = await proc._handle_no_values_detected("text", {})
        assert result["supported_currencies"] == []
        assert result["supported_billing_periods"] == []

    @pytest.mark.asyncio
    async def test_next_steps_populated(self):
        proc = _make_processor()
        result = await proc._handle_no_values_detected("text", {})
        assert len(result["next_steps"]) == 3

    @pytest.mark.asyncio
    async def test_required_information_in_guidance(self):
        proc = _make_processor()
        result = await proc._handle_no_values_detected("text", {})
        assert len(result["guidance"]["required_information"]) == 2


# ===========================================================================
# create_from_description
# ===========================================================================


class TestCreateFromDescription:
    """Tests for ProductEnhancementProcessor.create_from_description."""

    @pytest.mark.asyncio
    async def test_empty_description_raises(self):
        proc = _make_processor()
        with pytest.raises(ToolError):
            await proc.create_from_description({})

    @pytest.mark.asyncio
    async def test_empty_string_description_raises(self):
        proc = _make_processor()
        with pytest.raises(ToolError):
            await proc.create_from_description({"description": ""})

    @pytest.mark.asyncio
    async def test_nlp_fallback_when_no_nlp_processor(self):
        """When NLP processor is None, falls back to create_simple."""
        client = _make_client()
        client._extract_embedded_data.return_value = [{"id": "src_1"}]
        client.create_product.return_value = {"id": "p1", "name": "Fallback"}
        proc = _make_processor(client=client, has_nlp=False)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            result = await proc.create_from_description(
                {"description": "A premium API service"}
            )

        assert result["id"] == "p1"
        client.create_product.assert_called_once()

    @pytest.mark.asyncio
    async def test_nlp_fallback_uses_truncated_description_as_name(self):
        """Fallback path uses first 30 chars of description in product name."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product.return_value = {"id": "p1", "name": "test"}
        proc = _make_processor(client=client, has_nlp=False)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await proc.create_from_description(
                {"description": "A very long description that exceeds thirty characters easily"}
            )

        call_args = client.create_product.call_args[0][0]
        assert "A very long description that e" in call_args["name"]

    @pytest.mark.asyncio
    async def test_text_param_used_as_fallback_for_description(self):
        """'text' parameter is accepted as alternative to 'description'."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product.return_value = {"id": "p1"}
        proc = _make_processor(client=client, has_nlp=False)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            result = await proc.create_from_description({"text": "An API product"})

        assert result["id"] == "p1"

    @pytest.mark.asyncio
    async def test_nlp_parse_chatbot_name_extraction(self):
        """NLP parser returns empty name; 'chatbot' keyword extracts name."""
        client = _make_client()
        client._extract_embedded_data.return_value = [{"id": "src_1"}]
        client.create_product.return_value = {"id": "p2", "name": "chatbot"}
        nlp = MagicMock()
        nlp.parse_product_request.return_value = {"name": ""}
        proc = _make_processor(client=client, nlp_processor=nlp)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await proc.create_from_description(
                {"description": "A chatbot for customer support"}
            )

        call_args = client.create_product.call_args[0][0]
        assert "chatbot" in call_args["name"].lower()

    @pytest.mark.asyncio
    async def test_nlp_parse_api_name_extraction(self):
        """NLP parser returns empty name; 'api' keyword extracts name."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product.return_value = {"id": "p3"}
        nlp = MagicMock()
        nlp.parse_product_request.return_value = {"name": ""}
        proc = _make_processor(client=client, nlp_processor=nlp)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await proc.create_from_description(
                {"description": "An API gateway for data"}
            )

        call_args = client.create_product.call_args[0][0]
        assert call_args["name"] == "API Service"

    @pytest.mark.asyncio
    async def test_nlp_parse_subscription_name_extraction(self):
        """NLP parser returns empty name; 'subscription' keyword extracts name."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product.return_value = {"id": "p4"}
        nlp = MagicMock()
        nlp.parse_product_request.return_value = {"name": ""}
        proc = _make_processor(client=client, nlp_processor=nlp)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await proc.create_from_description(
                {"description": "A subscription for data analytics"}
            )

        call_args = client.create_product.call_args[0][0]
        assert call_args["name"] == "Subscription Plan"

    @pytest.mark.asyncio
    async def test_nlp_parse_plan_name_extraction(self):
        """NLP parser returns empty name; 'plan' keyword extracts name."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product.return_value = {"id": "p5"}
        nlp = MagicMock()
        nlp.parse_product_request.return_value = {"name": ""}
        proc = _make_processor(client=client, nlp_processor=nlp)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await proc.create_from_description(
                {"description": "A data plan for enterprise"}
            )

        call_args = client.create_product.call_args[0][0]
        assert call_args["name"] == "Subscription Plan"

    @pytest.mark.asyncio
    async def test_nlp_parse_fallback_word_extraction(self):
        """NLP parser returns empty name; no keywords, uses first words."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product.return_value = {"id": "p6"}
        nlp = MagicMock()
        nlp.parse_product_request.return_value = {"name": ""}
        proc = _make_processor(client=client, nlp_processor=nlp)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await proc.create_from_description(
                {"description": "Premium analytics dashboard"}
            )

        call_args = client.create_product.call_args[0][0]
        assert call_args["name"] == "Premium Analytics Dashboard"

    @pytest.mark.asyncio
    async def test_nlp_parse_single_word_fallback(self):
        """NLP parser returns empty name; single word falls to Custom Product."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product.return_value = {"id": "p7"}
        nlp = MagicMock()
        nlp.parse_product_request.return_value = {"name": ""}
        proc = _make_processor(client=client, nlp_processor=nlp)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await proc.create_from_description({"description": "x"})

        call_args = client.create_product.call_args[0][0]
        assert call_args["name"] == "Custom Product"

    @pytest.mark.asyncio
    async def test_plan_name_populated_when_empty(self):
        """Plan name auto-populated from product name when empty."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product.return_value = {"id": "p8"}
        nlp = MagicMock()
        nlp.parse_product_request.return_value = {
            "name": "My Product",
            "plan": {"name": "", "type": "SUBSCRIPTION"},
        }
        proc = _make_processor(client=client, nlp_processor=nlp)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await proc.create_from_description({"description": "My product plan"})

        call_args = client.create_product.call_args[0][0]
        assert call_args["plan"]["name"] == "My Product Plan"

    @pytest.mark.asyncio
    async def test_source_assigned_when_available(self):
        """Default source is assigned when sources exist."""
        client = _make_client()
        client._extract_embedded_data.return_value = [{"id": "src_42"}]
        client.create_product.return_value = {"id": "p9"}
        nlp = MagicMock()
        nlp.parse_product_request.return_value = {"name": "Product"}
        proc = _make_processor(client=client, nlp_processor=nlp)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await proc.create_from_description({"description": "a product"})

        call_args = client.create_product.call_args[0][0]
        assert call_args["sourceIds"] == ["src_42"]

    @pytest.mark.asyncio
    async def test_no_source_available_still_creates(self):
        """Product created even without available sources."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product.return_value = {"id": "p10"}
        nlp = MagicMock()
        nlp.parse_product_request.return_value = {"name": "Product"}
        proc = _make_processor(client=client, nlp_processor=nlp)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            result = await proc.create_from_description({"description": "a product"})

        assert result["id"] == "p10"

    @pytest.mark.asyncio
    async def test_source_fetch_exception_still_creates(self):
        """Product created even if source fetch throws."""
        client = _make_client()
        client.get_sources = AsyncMock(side_effect=Exception("network error"))
        client.create_product.return_value = {"id": "p11"}
        nlp = MagicMock()
        nlp.parse_product_request.return_value = {"name": "Product"}
        proc = _make_processor(client=client, nlp_processor=nlp)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            result = await proc.create_from_description({"description": "a product"})

        assert result["id"] == "p11"

    @pytest.mark.asyncio
    async def test_owner_id_added_when_configured(self):
        """ownerId added to product data when REVENIUM_OWNER_ID is set."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product.return_value = {"id": "p12"}
        nlp = MagicMock()
        nlp.parse_product_request.return_value = {"name": "Product"}
        proc = _make_processor(client=client, nlp_processor=nlp)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value="owner_123",
        ):
            await proc.create_from_description({"description": "a product"})

        call_args = client.create_product.call_args[0][0]
        assert call_args["ownerId"] == "owner_123"

    @pytest.mark.asyncio
    async def test_team_id_always_set(self):
        """teamId always set from client."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product.return_value = {"id": "p13"}
        nlp = MagicMock()
        nlp.parse_product_request.return_value = {"name": "Product"}
        proc = _make_processor(client=client, nlp_processor=nlp)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await proc.create_from_description({"description": "a product"})

        call_args = client.create_product.call_args[0][0]
        assert call_args["teamId"] == "team_test"

    @pytest.mark.asyncio
    async def test_internal_fields_stripped(self):
        """Fields starting with _ are removed before API call."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product.return_value = {"id": "p14"}
        nlp = MagicMock()
        nlp.parse_product_request.return_value = {
            "name": "Product",
            "_parsing_guidance": {"note": "internal"},
            "_internal": True,
        }
        proc = _make_processor(client=client, nlp_processor=nlp)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await proc.create_from_description({"description": "a product"})

        call_args = client.create_product.call_args[0][0]
        assert "_parsing_guidance" not in call_args
        assert "_internal" not in call_args

    @pytest.mark.asyncio
    async def test_setup_fee_validation_error_raises(self):
        """Invalid setup fee triggers ToolError."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        nlp = MagicMock()
        nlp.parse_product_request.return_value = {
            "name": "Product",
            "setupFees": [{"type": "INVALID", "flatAmount": -5}],
        }
        proc = _make_processor(client=client, nlp_processor=nlp)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            with pytest.raises(ToolError):
                await proc.create_from_description({"description": "product with setup"})

    @pytest.mark.asyncio
    async def test_valid_setup_fee_enhanced(self):
        """Valid setup fee data is enhanced and passed through."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product.return_value = {"id": "p15"}
        nlp = MagicMock()
        nlp.parse_product_request.return_value = {
            "name": "Product",
            "setupFees": [
                {"type": "SUBSCRIPTION", "flatAmount": 50.0, "name": "Setup"}
            ],
        }
        proc = _make_processor(client=client, nlp_processor=nlp)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await proc.create_from_description({"description": "product with setup fee"})

        call_args = client.create_product.call_args[0][0]
        assert "validation_timestamp" in call_args["setupFees"][0]

    @pytest.mark.asyncio
    async def test_setup_fee_warnings_added_to_result(self):
        """Setup fee warnings included in result when present."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product.return_value = {"id": "p16"}
        nlp = MagicMock()
        nlp.parse_product_request.return_value = {
            "name": "Product",
            "setupFees": [
                {"type": "SUBSCRIPTION", "flatAmount": 0.50, "name": "Tiny Fee"}
            ],
        }
        proc = _make_processor(client=client, nlp_processor=nlp)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            result = await proc.create_from_description(
                {"description": "product with tiny setup"}
            )

        assert "_setup_fee_validation" in result
        assert len(result["_setup_fee_validation"]["warnings"]) > 0

    @pytest.mark.asyncio
    async def test_setup_fee_warnings_stored_in_parsing_guidance(self):
        """Setup fee warnings stored in _parsing_guidance during processing."""
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client.create_product.return_value = {"id": "p17"}
        nlp = MagicMock()
        nlp.parse_product_request.return_value = {
            "name": "Product",
            "setupFees": [
                {"type": "SUBSCRIPTION", "flatAmount": 200000, "name": "Big Fee"}
            ],
        }
        proc = _make_processor(client=client, nlp_processor=nlp)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            result = await proc.create_from_description(
                {"description": "expensive product"}
            )

        # The warnings should be in the result
        assert "_setup_fee_validation" in result
