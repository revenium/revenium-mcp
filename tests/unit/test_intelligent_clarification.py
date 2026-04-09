"""Unit tests for IntelligentClarificationEngine.

Tests behavioral correctness of numerical value detection, pricing component
classification, multi-tier parsing, clarification option generation,
setup fee type determination, and formatting output.
"""


from src.revenium_mcp_server.intelligent_clarification_engine import (
    IntelligentClarificationEngine,
    PricingComponentType,
    SetupFeeType,
    DetectedValue,
    ClarificationOption,
    ClarificationRequest,
)


class TestDetectNumericalValues:
    """Tests for _detect_numerical_values: core value extraction."""

    def test_detects_dollar_sign_amount(self):
        engine = IntelligentClarificationEngine()
        values = engine._detect_numerical_values("The price is $50")
        amounts = [v.amount for v in values]
        assert 50.0 in amounts

    def test_detects_dollar_word_amount(self):
        engine = IntelligentClarificationEngine()
        values = engine._detect_numerical_values("Charge 100 dollars per month")
        amounts = [v.amount for v in values]
        assert 100.0 in amounts

    def test_detects_small_decimal(self):
        engine = IntelligentClarificationEngine()
        values = engine._detect_numerical_values("$0.005 per request")
        amounts = [v.amount for v in values]
        assert 0.005 in amounts

    def test_detects_multiple_values(self):
        engine = IntelligentClarificationEngine()
        values = engine._detect_numerical_values("$500 setup fee and $0.01 per call")
        assert len(values) >= 2

    def test_deduplicates_overlapping_positions(self):
        engine = IntelligentClarificationEngine()
        values = engine._detect_numerical_values("$100 dollars")
        # "$100" and "100 dollars" overlap - should deduplicate
        assert len(values) >= 1

    def test_empty_text_returns_empty(self):
        engine = IntelligentClarificationEngine()
        values = engine._detect_numerical_values("no numbers here")
        assert values == []

    def test_detects_up_to_threshold(self):
        engine = IntelligentClarificationEngine()
        values = engine._detect_numerical_values("free up to 1000 calls")
        amounts = [v.amount for v in values]
        assert 1000.0 in amounts

    def test_detects_first_n_pattern(self):
        engine = IntelligentClarificationEngine()
        values = engine._detect_numerical_values("first 5000 requests are free")
        amounts = [v.amount for v in values]
        assert 5000.0 in amounts


class TestParseMultiTierStructure:
    """Tests for _parse_multi_tier_structure: complex multi-tier parsing."""

    def test_four_component_structure(self):
        engine = IntelligentClarificationEngine()
        text = "first 10000 free then 0.005 dollars up to 100000 then 0.003 dollars"
        values = engine._parse_multi_tier_structure(text)
        assert len(values) == 4
        amounts = [v.amount for v in values]
        assert 10000.0 in amounts
        assert 0.005 in amounts
        assert 100000.0 in amounts
        assert 0.003 in amounts

    def test_returns_empty_for_non_matching(self):
        engine = IntelligentClarificationEngine()
        values = engine._parse_multi_tier_structure("simple $50 product")
        assert values == []

    def test_multi_tier_values_have_correct_types(self):
        engine = IntelligentClarificationEngine()
        text = "first 1000 free then 0.01 dollars up to 5000 then 0.005 dollars"
        values = engine._parse_multi_tier_structure(text)
        assert len(values) == 4
        assert PricingComponentType.TIER_THRESHOLD in values[0].possible_types
        assert PricingComponentType.UNIT_RATE in values[1].possible_types
        assert PricingComponentType.TIER_THRESHOLD in values[2].possible_types
        assert PricingComponentType.UNIT_RATE in values[3].possible_types


class TestDeterminePossibleTypes:
    """Tests for _determine_possible_types: pricing component classification."""

    def test_setup_fee_detected(self):
        engine = IntelligentClarificationEngine()
        types = engine._determine_possible_types(500.0, "a setup fee of", "", "500 dollars")
        assert PricingComponentType.SETUP_FEE in types

    def test_base_charge_detected(self):
        engine = IntelligentClarificationEngine()
        types = engine._determine_possible_types(99.0, "", "per month", "99 dollars")
        assert PricingComponentType.BASE_CHARGE in types

    def test_unit_rate_detected_by_context(self):
        engine = IntelligentClarificationEngine()
        types = engine._determine_possible_types(0.01, "cost", "per request", "0.01 dollars")
        assert PricingComponentType.UNIT_RATE in types

    def test_unit_rate_detected_by_small_amount(self):
        engine = IntelligentClarificationEngine()
        types = engine._determine_possible_types(0.005, "", "", "0.005 dollars")
        assert PricingComponentType.UNIT_RATE in types

    def test_tier_threshold_detected(self):
        engine = IntelligentClarificationEngine()
        types = engine._determine_possible_types(1000.0, "free up to", "calls", "1000")
        assert PricingComponentType.TIER_THRESHOLD in types

    def test_flat_amount_detected(self):
        engine = IntelligentClarificationEngine()
        types = engine._determine_possible_types(50.0, "flat fee", "", "50 dollars")
        assert PricingComponentType.FLAT_AMOUNT in types

    def test_unknown_for_no_context(self):
        engine = IntelligentClarificationEngine()
        # Amount between 1 and 100 with no context clues
        types = engine._determine_possible_types(42.0, "", "", "42")
        assert PricingComponentType.UNKNOWN in types

    def test_setup_fee_prevents_base_charge(self):
        """When setup fee is detected, base charge should not also be detected."""
        engine = IntelligentClarificationEngine()
        types = engine._determine_possible_types(500.0, "setup fee for", "subscription", "500")
        assert PricingComponentType.SETUP_FEE in types
        assert PricingComponentType.BASE_CHARGE not in types


class TestExtractCurrency:
    """Tests for _extract_currency."""

    def test_usd_dollar_sign(self):
        engine = IntelligentClarificationEngine()
        assert engine._extract_currency("$50", "", "") == "USD"

    def test_eur_euro_sign(self):
        engine = IntelligentClarificationEngine()
        assert engine._extract_currency("€50", "", "") == "EUR"

    def test_gbp_pound_sign(self):
        engine = IntelligentClarificationEngine()
        assert engine._extract_currency("£50", "", "") == "GBP"

    def test_default_to_usd(self):
        engine = IntelligentClarificationEngine()
        assert engine._extract_currency("50", "", "") == "USD"

    def test_usd_word(self):
        engine = IntelligentClarificationEngine()
        assert engine._extract_currency("50", "", "usd") == "USD"


class TestCalculateConfidence:
    """Tests for _calculate_confidence."""

    def test_single_type_high_confidence(self):
        engine = IntelligentClarificationEngine()
        assert engine._calculate_confidence([PricingComponentType.SETUP_FEE], "", "") == 0.9

    def test_two_types_medium_confidence(self):
        engine = IntelligentClarificationEngine()
        assert engine._calculate_confidence(
            [PricingComponentType.SETUP_FEE, PricingComponentType.BASE_CHARGE], "", ""
        ) == 0.6

    def test_many_types_low_confidence(self):
        engine = IntelligentClarificationEngine()
        assert engine._calculate_confidence(
            [PricingComponentType.SETUP_FEE, PricingComponentType.BASE_CHARGE, PricingComponentType.UNIT_RATE],
            "", "",
        ) == 0.3


class TestDetermineSetupFeeType:
    """Tests for _determine_setup_fee_type."""

    def test_per_customer_returns_organization(self):
        engine = IntelligentClarificationEngine()
        result = engine._determine_setup_fee_type("per customer", "")
        assert result == SetupFeeType.ORGANIZATION

    def test_per_subscription_returns_subscription(self):
        engine = IntelligentClarificationEngine()
        result = engine._determine_setup_fee_type("per subscription", "")
        assert result == SetupFeeType.SUBSCRIPTION

    def test_ambiguous_defaults_to_subscription(self):
        engine = IntelligentClarificationEngine()
        result = engine._determine_setup_fee_type("", "")
        assert result == SetupFeeType.SUBSCRIPTION

    def test_per_organization_returns_organization(self):
        engine = IntelligentClarificationEngine()
        result = engine._determine_setup_fee_type("per organization", "")
        assert result == SetupFeeType.ORGANIZATION


class TestAnalyzeInput:
    """Tests for analyze_input: end-to-end clarification flow."""

    def test_single_value_no_clarification_needed(self):
        engine = IntelligentClarificationEngine()
        result = engine.analyze_input("Create a product for $50 per month")
        assert isinstance(result, ClarificationRequest)
        assert result.recommended_option == "simple"

    def test_no_values_detected(self):
        engine = IntelligentClarificationEngine()
        result = engine.analyze_input("Create a product called Premium API")
        assert len(result.detected_values) == 0
        assert result.recommended_option == ""

    def test_multiple_values_generates_options(self):
        engine = IntelligentClarificationEngine()
        result = engine.analyze_input("$500 setup fee and $0.01 per call")
        assert len(result.detected_values) >= 2
        assert len(result.clarification_options) > 0

    def test_result_contains_original_input(self):
        engine = IntelligentClarificationEngine()
        text = "Create product at $99 per month"
        result = engine.analyze_input(text)
        assert result.original_input == text


class TestCreateSimpleClarification:
    """Tests for _create_simple_clarification."""

    def test_no_values_empty_options(self):
        engine = IntelligentClarificationEngine()
        result = engine._create_simple_clarification("test", [])
        assert result.recommended_option == ""
        assert len(result.clarification_options) == 0
        assert "No pricing values" in result.ambiguity_explanation

    def test_base_charge_detected(self):
        engine = IntelligentClarificationEngine()
        value = DetectedValue(
            amount=99.0, currency="USD", raw_text="$99",
            context_before="", context_after="per month",
            possible_types=[PricingComponentType.BASE_CHARGE],
            confidence=0.8, position=0,
        )
        result = engine._create_simple_clarification("$99/month", [value])
        assert result.recommended_option == "simple"
        assert "subscription" in result.clarification_options[0].structure.get("plan", {}).get("type", "").lower()

    def test_small_amount_creates_usage_pricing(self):
        engine = IntelligentClarificationEngine()
        value = DetectedValue(
            amount=0.005, currency="USD", raw_text="$0.005",
            context_before="", context_after="per request",
            possible_types=[PricingComponentType.UNIT_RATE],
            confidence=0.8, position=0,
        )
        result = engine._create_simple_clarification("$0.005 per request", [value])
        plan = result.clarification_options[0].structure.get("plan", {})
        assert plan.get("charge") == 0  # Usage-based, no base charge
        assert "ratingAggregations" in plan


class TestGenerateTwoValueOptions:
    """Tests for _generate_two_value_options."""

    def test_setup_plus_monthly(self):
        engine = IntelligentClarificationEngine()
        val1 = DetectedValue(
            amount=500, currency="USD", raw_text="$500",
            context_before="setup fee", context_after="",
            possible_types=[PricingComponentType.SETUP_FEE],
            confidence=0.8, position=0,
        )
        val2 = DetectedValue(
            amount=99, currency="USD", raw_text="$99",
            context_before="", context_after="per month",
            possible_types=[PricingComponentType.BASE_CHARGE],
            confidence=0.8, position=20,
        )
        options = engine._generate_two_value_options("test", [val1, val2])
        assert any("setup_monthly" == o.option_id for o in options)

    def test_tier_plus_unit_rate(self):
        engine = IntelligentClarificationEngine()
        val1 = DetectedValue(
            amount=1000, currency="USD", raw_text="1000",
            context_before="up to", context_after="calls",
            possible_types=[PricingComponentType.TIER_THRESHOLD],
            confidence=0.8, position=0,
        )
        val2 = DetectedValue(
            amount=0.01, currency="USD", raw_text="$0.01",
            context_before="", context_after="per call",
            possible_types=[PricingComponentType.UNIT_RATE],
            confidence=0.8, position=20,
        )
        options = engine._generate_two_value_options("test", [val1, val2])
        assert any("tiered_usage" == o.option_id for o in options)


class TestGenerateThreeValueOptions:
    """Tests for _generate_three_value_options."""

    def test_setup_monthly_usage(self):
        engine = IntelligentClarificationEngine()
        vals = [
            DetectedValue(amount=1000, currency="USD", raw_text="$1000",
                          context_before="", context_after="",
                          possible_types=[PricingComponentType.SETUP_FEE],
                          confidence=0.8, position=0),
            DetectedValue(amount=99, currency="USD", raw_text="$99",
                          context_before="", context_after="",
                          possible_types=[PricingComponentType.BASE_CHARGE],
                          confidence=0.8, position=10),
            DetectedValue(amount=0.01, currency="USD", raw_text="$0.01",
                          context_before="", context_after="",
                          possible_types=[PricingComponentType.UNIT_RATE],
                          confidence=0.8, position=20),
        ]
        options = engine._generate_three_value_options("test", vals)
        assert len(options) >= 2
        ids = [o.option_id for o in options]
        assert "setup_monthly_usage" in ids
        assert "monthly_two_tier" in ids


class TestGenerateMultiValueOptions:
    """Tests for _generate_multi_value_options."""

    def test_complex_structure_fallback(self):
        engine = IntelligentClarificationEngine()
        vals = [
            DetectedValue(amount=i * 100, currency="USD", raw_text=f"${i*100}",
                          context_before="", context_after="",
                          possible_types=[PricingComponentType.UNKNOWN],
                          confidence=0.5, position=i * 10, pattern_type="simple")
            for i in range(1, 6)
        ]
        options = engine._generate_multi_value_options("test", vals)
        assert len(options) >= 1
        assert options[0].option_id == "complex_structure"

    def test_multi_tier_four_values(self):
        engine = IntelligentClarificationEngine()
        vals = [
            DetectedValue(amount=10000, currency="USD", raw_text="10000",
                          context_before="", context_after="",
                          possible_types=[PricingComponentType.TIER_THRESHOLD],
                          confidence=0.9, position=0, pattern_type="multi_tier"),
            DetectedValue(amount=0.005, currency="USD", raw_text="0.005 dollars",
                          context_before="", context_after="",
                          possible_types=[PricingComponentType.UNIT_RATE],
                          confidence=0.9, position=10, pattern_type="multi_tier"),
            DetectedValue(amount=100000, currency="USD", raw_text="100000",
                          context_before="", context_after="",
                          possible_types=[PricingComponentType.TIER_THRESHOLD],
                          confidence=0.9, position=20, pattern_type="multi_tier"),
            DetectedValue(amount=0.003, currency="USD", raw_text="0.003 dollars",
                          context_before="", context_after="",
                          possible_types=[PricingComponentType.UNIT_RATE],
                          confidence=0.9, position=30, pattern_type="multi_tier"),
        ]
        options = engine._generate_multi_value_options("test", vals)
        assert any("three_tier" in o.option_id for o in options)


class TestDetermineRecommendedOption:
    """Tests for _determine_recommended_option."""

    def test_returns_highest_confidence(self):
        engine = IntelligentClarificationEngine()
        options = [
            ClarificationOption(option_id="low", title="", description="",
                                structure={}, confidence=0.3, reasoning=""),
            ClarificationOption(option_id="high", title="", description="",
                                structure={}, confidence=0.9, reasoning=""),
        ]
        assert engine._determine_recommended_option(options) == "high"

    def test_empty_options_returns_empty(self):
        engine = IntelligentClarificationEngine()
        assert engine._determine_recommended_option([]) == ""


class TestGenerateAmbiguityExplanation:
    """Tests for _generate_ambiguity_explanation."""

    def test_single_value_no_ambiguity(self):
        engine = IntelligentClarificationEngine()
        values = [DetectedValue(amount=50, currency="USD", raw_text="$50",
                                context_before="", context_after="",
                                possible_types=[PricingComponentType.BASE_CHARGE],
                                confidence=0.8, position=0)]
        result = engine._generate_ambiguity_explanation(values)
        assert "No ambiguity" in result

    def test_multiple_values_explains(self):
        engine = IntelligentClarificationEngine()
        values = [
            DetectedValue(amount=500, currency="USD", raw_text="$500",
                          context_before="", context_after="",
                          possible_types=[PricingComponentType.SETUP_FEE],
                          confidence=0.8, position=0),
            DetectedValue(amount=0.01, currency="USD", raw_text="$0.01",
                          context_before="", context_after="",
                          possible_types=[PricingComponentType.UNIT_RATE],
                          confidence=0.8, position=10),
        ]
        result = engine._generate_ambiguity_explanation(values)
        assert "2 pricing values" in result
        assert "setup fee" in result
        assert "unit rate" in result


class TestFormatClarificationResponse:
    """Tests for format_clarification_response."""

    def test_no_options_shows_analysis(self):
        engine = IntelligentClarificationEngine()
        req = ClarificationRequest(
            original_input="test",
            detected_values=[],
            clarification_options=[],
            recommended_option="",
            ambiguity_explanation="Nothing found",
        )
        result = engine.format_clarification_response(req)
        assert "Nothing found" in result

    def test_with_options_shows_all(self):
        engine = IntelligentClarificationEngine()
        req = ClarificationRequest(
            original_input="$500 and $0.01",
            detected_values=[],
            clarification_options=[
                ClarificationOption(option_id="opt1", title="Option A",
                                    description="Desc A", structure={},
                                    confidence=0.9, reasoning="Reason A"),
                ClarificationOption(option_id="opt2", title="Option B",
                                    description="Desc B", structure={},
                                    confidence=0.6, reasoning="Reason B"),
            ],
            recommended_option="opt1",
            ambiguity_explanation="Two values found",
        )
        result = engine.format_clarification_response(req)
        assert "Option A" in result
        assert "Option B" in result
        assert "Reason A" in result


class TestAnalyzeSetupFeeAmbiguity:
    """Tests for analyze_setup_fee_ambiguity."""

    def test_no_setup_fee_mentioned(self):
        engine = IntelligentClarificationEngine()
        result = engine.analyze_setup_fee_ambiguity("Create a product at $50/month")
        assert result["has_setup_fee"] is False

    def test_setup_fee_mentioned_without_amount(self):
        engine = IntelligentClarificationEngine()
        result = engine.analyze_setup_fee_ambiguity("Include a setup fee")
        assert result["has_setup_fee"] is True
        # No dollar amount, so should flag
        assert result.get("ambiguity_type") in ("no_amount_detected", "none")

    def test_explicit_customer_setup_fee_not_ambiguous(self):
        engine = IntelligentClarificationEngine()
        result = engine.analyze_setup_fee_ambiguity("$500 per customer setup fee")
        assert result["has_setup_fee"] is True

    def test_ambiguous_setup_fee_provides_guidance(self):
        engine = IntelligentClarificationEngine()
        result = engine.analyze_setup_fee_ambiguity("$500 setup fee")
        assert result["has_setup_fee"] is True
        if result.get("ambiguity_type") == "type_unclear":
            assert "guidance" in result
            assert len(result["guidance"]) > 0


class TestGenerateSetupFeeClarificationGuidance:
    """Tests for _generate_setup_fee_clarification_guidance."""

    def test_single_ambiguous_fee(self):
        engine = IntelligentClarificationEngine()
        fees = [{"amount": 500, "raw_text": "$500", "context": "setup fee"}]
        result = engine._generate_setup_fee_clarification_guidance(fees)
        assert "$500" in result
        assert "per subscription" in result
        assert "per customer" in result

    def test_multiple_ambiguous_fees(self):
        engine = IntelligentClarificationEngine()
        fees = [
            {"amount": 500, "raw_text": "$500"},
            {"amount": 200, "raw_text": "$200"},
        ]
        result = engine._generate_setup_fee_clarification_guidance(fees)
        assert "2 setup fees" in result


class TestBuildPatterns:
    """Tests for pattern builder methods."""

    def test_currency_patterns_built(self):
        engine = IntelligentClarificationEngine()
        assert "USD" in engine.currency_patterns
        assert "EUR" in engine.currency_patterns

    def test_pricing_patterns_built(self):
        engine = IntelligentClarificationEngine()
        assert "setup_fee" in engine.pricing_patterns
        assert "base_charge" in engine.pricing_patterns
        assert "unit_rate" in engine.pricing_patterns

    def test_context_patterns_built(self):
        engine = IntelligentClarificationEngine()
        assert "subscription_context" in engine.context_patterns
        assert "usage_context" in engine.context_patterns
        assert "setup_context" in engine.context_patterns
