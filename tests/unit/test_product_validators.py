"""Unit tests for product validation system.

Tests behavioral correctness of ProductValidator, TierValidator,
ElementValidator, SetupFeeValidator, RatingAggregationValidator,
PlanValidator, and ProductValidationEngine.
"""

import pytest
from decimal import Decimal

from src.revenium_mcp_server.product_validators import (
    ProductValidator,
    TierValidator,
    ElementValidator,
    SetupFeeValidator,
    RatingAggregationValidator,
    PlanValidator,
    ProductValidationEngine,
)
from src.revenium_mcp_server.exceptions import ValidationError
from src.revenium_mcp_server.models import (
    AggregationType,
    BillingPeriod,
    Currency,
    PlanType,
    RatingAggregationType,
)


# ---------- ProductValidator ----------

class TestValidateProductName:
    """Tests for validate_product_name."""

    def test_valid_name(self):
        assert ProductValidator.validate_product_name("My API") == "My API"

    def test_strips_whitespace(self):
        assert ProductValidator.validate_product_name("  Trimmed  ") == "Trimmed"

    def test_empty_name_raises(self):
        with pytest.raises(ValidationError, match="required"):
            ProductValidator.validate_product_name("")

    def test_none_name_raises(self):
        with pytest.raises(ValidationError, match="required"):
            ProductValidator.validate_product_name(None)

    def test_too_short_raises(self):
        with pytest.raises(ValidationError, match="at least 2"):
            ProductValidator.validate_product_name("X")

    def test_too_long_raises(self):
        with pytest.raises(ValidationError, match="exceeds"):
            ProductValidator.validate_product_name("A" * 300)

    def test_numeric_coerced_to_string(self):
        result = ProductValidator.validate_product_name(12345)
        assert result == "12345"


class TestValidateProductVersion:
    """Tests for validate_product_version."""

    def test_valid_semver(self):
        assert ProductValidator.validate_product_version("1.0.0") == "1.0.0"

    def test_valid_semver_with_prerelease(self):
        assert ProductValidator.validate_product_version("2.1.3-beta") == "2.1.3-beta"

    def test_empty_raises(self):
        with pytest.raises(ValidationError, match="required"):
            ProductValidator.validate_product_version("")

    def test_invalid_format_raises(self):
        with pytest.raises(ValidationError, match="Invalid version"):
            ProductValidator.validate_product_version("not-a-version")

    def test_partial_version_raises(self):
        with pytest.raises(ValidationError, match="Invalid version"):
            ProductValidator.validate_product_version("1.0")


class TestValidateEmailList:
    """Tests for validate_email_list."""

    def test_valid_emails(self):
        result = ProductValidator.validate_email_list(["user@example.com", "admin@test.org"])
        assert result == ["user@example.com", "admin@test.org"]

    def test_empty_list(self):
        assert ProductValidator.validate_email_list([]) == []

    def test_none_returns_empty(self):
        assert ProductValidator.validate_email_list(None) == []

    def test_invalid_email_raises(self):
        with pytest.raises(ValidationError, match="Invalid email"):
            ProductValidator.validate_email_list(["not-an-email"])

    def test_deduplicates(self):
        result = ProductValidator.validate_email_list(["a@b.com", "A@B.COM"])
        assert len(result) == 1

    def test_skips_empty_entries(self):
        result = ProductValidator.validate_email_list(["", "a@b.com", None])
        assert result == ["a@b.com"]

    def test_non_list_raises(self):
        with pytest.raises(ValidationError, match="must be a list"):
            ProductValidator.validate_email_list("not-a-list")


class TestValidateIdList:
    """Tests for validate_id_list."""

    def test_valid_ids(self):
        result = ProductValidator.validate_id_list(["abc-123", "def_456"], "test_ids")
        assert result == ["abc-123", "def_456"]

    def test_empty_returns_empty(self):
        assert ProductValidator.validate_id_list([], "test") == []

    def test_invalid_id_raises(self):
        with pytest.raises(ValidationError, match="Invalid ID"):
            ProductValidator.validate_id_list(["valid", "inv@lid!"], "test")

    def test_deduplicates(self):
        result = ProductValidator.validate_id_list(["abc", "abc"], "test")
        assert len(result) == 1

    def test_non_list_raises(self):
        with pytest.raises(ValidationError, match="must be a list"):
            ProductValidator.validate_id_list("not-a-list", "test")


class TestValidateTags:
    """Tests for validate_tags."""

    def test_valid_tags(self):
        result = ProductValidator.validate_tags(["api", "premium"])
        assert result == ["api", "premium"]

    def test_empty_returns_empty(self):
        assert ProductValidator.validate_tags([]) == []

    def test_too_many_tags_raises(self):
        with pytest.raises(ValidationError, match="Too many tags"):
            ProductValidator.validate_tags(["tag"] * 51)

    def test_too_long_tag_raises(self):
        with pytest.raises(ValidationError, match="exceeds maximum"):
            ProductValidator.validate_tags(["x" * 101])

    def test_deduplicates(self):
        result = ProductValidator.validate_tags(["a", "a", "b"])
        assert result == ["a", "b"]

    def test_non_list_raises(self):
        with pytest.raises(ValidationError, match="must be a list"):
            ProductValidator.validate_tags("not-a-list")


class TestValidateDecimalAmount:
    """Tests for validate_decimal_amount."""

    def test_valid_integer(self):
        result = ProductValidator.validate_decimal_amount(10, "amount")
        assert result == Decimal("10.00")

    def test_valid_float(self):
        result = ProductValidator.validate_decimal_amount(9.99, "amount")
        assert result == Decimal("9.99")

    def test_valid_decimal(self):
        result = ProductValidator.validate_decimal_amount(Decimal("5.50"), "amount")
        assert result == Decimal("5.50")

    def test_valid_string_number(self):
        result = ProductValidator.validate_decimal_amount("19.99", "amount")
        assert result == Decimal("19.99")

    def test_none_raises(self):
        with pytest.raises(ValidationError, match="required"):
            ProductValidator.validate_decimal_amount(None, "amount")

    def test_negative_raises(self):
        with pytest.raises(ValidationError, match="negative"):
            ProductValidator.validate_decimal_amount(-5, "amount")

    def test_invalid_string_raises(self):
        with pytest.raises(ValidationError, match="Invalid"):
            ProductValidator.validate_decimal_amount("abc", "amount")

    def test_rounds_to_two_decimals(self):
        result = ProductValidator.validate_decimal_amount(1.999, "amount")
        assert result == Decimal("2.00")


class TestValidatePositiveInteger:
    """Tests for validate_positive_integer."""

    def test_valid(self):
        assert ProductValidator.validate_positive_integer(5, "qty") == 5

    def test_none_raises(self):
        with pytest.raises(ValidationError, match="required"):
            ProductValidator.validate_positive_integer(None, "qty")

    def test_zero_raises(self):
        with pytest.raises(ValidationError, match="must be positive"):
            ProductValidator.validate_positive_integer(0, "qty")

    def test_negative_raises(self):
        with pytest.raises(ValidationError, match="must be positive"):
            ProductValidator.validate_positive_integer(-1, "qty")

    def test_non_numeric_raises(self):
        with pytest.raises(ValidationError, match="Invalid"):
            ProductValidator.validate_positive_integer("abc", "qty")


class TestValidateEnumValue:
    """Tests for validate_enum_value."""

    def test_valid_string_value(self):
        result = ProductValidator.validate_enum_value("USD", Currency, "currency")
        assert result == Currency.USD

    def test_valid_enum_instance(self):
        result = ProductValidator.validate_enum_value(Currency.EUR, Currency, "currency")
        assert result == Currency.EUR

    def test_case_insensitive(self):
        result = ProductValidator.validate_enum_value("usd", Currency, "currency")
        assert result == Currency.USD

    def test_none_raises_with_valid_values(self):
        with pytest.raises(ValidationError, match="required"):
            ProductValidator.validate_enum_value(None, Currency, "currency")

    def test_invalid_value_raises(self):
        with pytest.raises(ValidationError, match="Invalid"):
            ProductValidator.validate_enum_value("INVALID", Currency, "currency")


# ---------- TierValidator ----------

class TestValidateTierRange:
    """Tests for TierValidator.validate_tier_range."""

    def test_valid_range(self):
        result = TierValidator.validate_tier_range(1000)
        assert result == Decimal("1000.00")

    def test_none_returns_none(self):
        assert TierValidator.validate_tier_range(None) is None


class TestValidateTierStructureRules:
    """Tests for validate_tier_structure_rules."""

    def test_single_tier_null_up_to(self):
        TierValidator.validate_tier_structure_rules([{"up_to": None}])

    def test_single_tier_with_value_raises(self):
        with pytest.raises(ValidationError, match="Final tier must have up_to: null"):
            TierValidator.validate_tier_structure_rules([{"up_to": 100}])

    def test_multi_tier_valid(self):
        tiers = [{"up_to": 100}, {"up_to": 500}, {"up_to": None}]
        TierValidator.validate_tier_structure_rules(tiers)

    def test_multi_tier_non_final_null_raises(self):
        tiers = [{"up_to": None}, {"up_to": None}]
        with pytest.raises(ValidationError, match="Non-final tiers"):
            TierValidator.validate_tier_structure_rules(tiers)

    def test_empty_tiers_passes(self):
        TierValidator.validate_tier_structure_rules([])


class TestRangesOverlap:
    """Tests for TierValidator._ranges_overlap."""

    def test_no_overlap(self):
        assert TierValidator._ranges_overlap(Decimal(0), Decimal(10), Decimal(10), Decimal(20)) is False

    def test_overlap(self):
        assert TierValidator._ranges_overlap(Decimal(0), Decimal(15), Decimal(10), Decimal(20)) is True

    def test_both_open_ended_same_start(self):
        assert TierValidator._ranges_overlap(Decimal(0), None, Decimal(0), None) is True

    def test_both_open_ended_different_start(self):
        assert TierValidator._ranges_overlap(Decimal(0), None, Decimal(5), None) is False

    def test_one_open_ended(self):
        assert TierValidator._ranges_overlap(Decimal(0), None, Decimal(5), Decimal(10)) is True


class TestValidateTiersList:
    """Tests for validate_tiers_list."""

    def test_valid_single_tier(self):
        tiers = [{"name": "Standard", "up_to": None, "unit_amount": 0.01}]
        result = TierValidator.validate_tiers_list(tiers)
        assert len(result) == 1

    def test_missing_pricing_raises(self):
        tiers = [{"name": "Bad Tier", "up_to": None}]
        with pytest.raises(ValidationError, match="unit_amount or flat_amount"):
            TierValidator.validate_tiers_list(tiers)

    def test_too_many_tiers_raises(self):
        tiers = [{"name": f"Tier {i}", "up_to": None, "unit_amount": 0.01} for i in range(25)]
        with pytest.raises(ValidationError, match="Too many tiers"):
            TierValidator.validate_tiers_list(tiers)


# ---------- ElementValidator ----------

class TestValidateElementStructure:
    """Tests for ElementValidator.validate_element_structure."""

    def test_valid_element(self):
        result = ElementValidator.validate_element_structure({
            "metering_element_definition_id": "elem-1",
            "name": "API Calls",
        })
        assert result["name"] == "API Calls"

    def test_missing_id_raises(self):
        with pytest.raises(ValidationError, match="definition ID"):
            ElementValidator.validate_element_structure({"name": "Test"})

    def test_missing_name_raises(self):
        with pytest.raises(ValidationError, match="name is required"):
            ElementValidator.validate_element_structure({"metering_element_definition_id": "x"})

    def test_with_aggregation_type(self):
        result = ElementValidator.validate_element_structure({
            "metering_element_definition_id": "elem-1",
            "name": "API Calls",
            "aggregation_type": "SUM",
        })
        assert result["aggregation_type"] == "SUM"


class TestValidateElementsList:
    """Tests for validate_elements_list."""

    def test_duplicate_ids_raises(self):
        elements = [
            {"metering_element_definition_id": "same-id", "name": "Elem A"},
            {"metering_element_definition_id": "same-id", "name": "Elem B"},
        ]
        with pytest.raises(ValidationError, match="Duplicate"):
            ElementValidator.validate_elements_list(elements)

    def test_too_many_elements_raises(self):
        elements = [
            {"metering_element_definition_id": f"id-{i}", "name": f"Element {i}"}
            for i in range(55)
        ]
        with pytest.raises(ValidationError, match="Too many elements"):
            ElementValidator.validate_elements_list(elements)


# ---------- SetupFeeValidator ----------

class TestValidateSetupFeeStructure:
    """Tests for SetupFeeValidator.validate_setup_fee_structure."""

    def test_valid_setup_fee(self):
        result = SetupFeeValidator.validate_setup_fee_structure({
            "name": "Onboarding Fee",
            "flatAmount": 500,
            "type": "SUBSCRIPTION",
        })
        assert result["name"] == "Onboarding Fee"

    def test_missing_name_raises(self):
        with pytest.raises(ValidationError, match="name is required"):
            SetupFeeValidator.validate_setup_fee_structure({"flatAmount": 100})

    def test_missing_amount_raises(self):
        with pytest.raises(ValidationError, match="amount is required"):
            SetupFeeValidator.validate_setup_fee_structure({"name": "Fee"})

    def test_backward_compat_amount_field(self):
        result = SetupFeeValidator.validate_setup_fee_structure({
            "name": "Legacy Fee",
            "amount": 200,
            "type": "ORGANIZATION",
        })
        assert result["name"] == "Legacy Fee"

    def test_invalid_type_raises(self):
        with pytest.raises(ValidationError, match="Invalid setup fee type"):
            SetupFeeValidator.validate_setup_fee_structure({
                "name": "Fee",
                "flatAmount": 100,
                "type": "BOGUS",
            })

    def test_deprecated_type_does_not_raise(self):
        # PRODUCT_LICENSE and CUSTOMER are deprecated but still accepted
        result = SetupFeeValidator.validate_setup_fee_structure({
            "name": "Old Fee",
            "flatAmount": 100,
            "type": "PRODUCT_LICENSE",
        })
        assert result is not None
        assert result.get("name") == "Old Fee"


class TestValidateSetupFeesList:
    """Tests for validate_setup_fees_list."""

    def test_duplicate_names_raises(self):
        fees = [
            {"name": "Same Name", "flatAmount": 100},
            {"name": "Same Name", "flatAmount": 200},
        ]
        with pytest.raises(ValidationError, match="Duplicate"):
            SetupFeeValidator.validate_setup_fees_list(fees)

    def test_too_many_fees_raises(self):
        fees = [{"name": f"Fee {i}", "flatAmount": 100} for i in range(15)]
        with pytest.raises(ValidationError, match="Too many setup fees"):
            SetupFeeValidator.validate_setup_fees_list(fees)


# ---------- RatingAggregationValidator ----------

class TestValidateRatingAggregationStructure:
    """Tests for RatingAggregationValidator.validate_rating_aggregation_structure."""

    def test_valid_rating_aggregation(self):
        result = RatingAggregationValidator.validate_rating_aggregation_structure({
            "name": "API Usage",
            "metering_element_id": "elem-1",
            "type": "SUM",
        })
        assert result["name"] == "API Usage"

    def test_missing_name_raises(self):
        with pytest.raises(ValidationError, match="name is required"):
            RatingAggregationValidator.validate_rating_aggregation_structure({
                "metering_element_id": "x",
                "type": "SUM",
            })

    def test_missing_metering_element_raises(self):
        with pytest.raises(ValidationError, match="Metering element ID"):
            RatingAggregationValidator.validate_rating_aggregation_structure({
                "name": "Test",
                "type": "SUM",
            })

    def test_missing_type_raises(self):
        with pytest.raises(ValidationError, match="required"):
            RatingAggregationValidator.validate_rating_aggregation_structure({
                "name": "Test",
                "metering_element_id": "x",
            })


class TestValidateRatingAggregationsList:
    """Tests for validate_rating_aggregations_list."""

    def test_duplicate_names_raises(self):
        aggs = [
            {"name": "Same", "metering_element_id": "e1", "type": "SUM"},
            {"name": "Same", "metering_element_id": "e2", "type": "COUNT"},
        ]
        with pytest.raises(ValidationError, match="Duplicate"):
            RatingAggregationValidator.validate_rating_aggregations_list(aggs)

    def test_too_many_raises(self):
        aggs = [
            {"name": f"Agg {i}", "metering_element_id": f"e-{i}", "type": "SUM"}
            for i in range(25)
        ]
        with pytest.raises(ValidationError, match="Too many rating"):
            RatingAggregationValidator.validate_rating_aggregations_list(aggs)


# ---------- PlanValidator ----------

class TestValidatePlanStructure:
    """Tests for PlanValidator.validate_plan_structure."""

    def test_valid_subscription_plan(self):
        plan = {
            "type": "SUBSCRIPTION",
            "currency": "USD",
            "period": "MONTH",
            "tiers": [{"name": "Standard", "up_to": None, "unit_amount": 0.01}],
        }
        result = PlanValidator.validate_plan_structure(plan)
        assert result == plan

    def test_missing_tiers_and_rating_aggs_raises(self):
        plan = {"type": "SUBSCRIPTION", "currency": "USD"}
        with pytest.raises(ValidationError, match="at least one tier"):
            PlanValidator.validate_plan_structure(plan)

    def test_subscription_without_period_raises(self):
        plan = {
            "type": "SUBSCRIPTION",
            "currency": "USD",
            "tiers": [{"name": "Tier 1", "up_to": None, "unit_amount": 0.01}],
        }
        with pytest.raises(ValidationError, match="billing period"):
            PlanValidator.validate_plan_structure(plan)

    def test_rating_aggregation_tiers_satisfy_requirement(self):
        plan = {
            "type": "SUBSCRIPTION",
            "currency": "USD",
            "period": "MONTH",
            "rating_aggregations": [
                {
                    "name": "Usage",
                    "tiers": [{"name": "T1", "up_to": None, "unit_amount": 0.01}],
                }
            ],
        }
        result = PlanValidator.validate_plan_structure(plan)
        assert result is not None
        assert result.get("type") == "SUBSCRIPTION"


# ---------- ProductValidationEngine ----------

class TestValidateCompleteProduct:
    """Tests for ProductValidationEngine.validate_complete_product."""

    def _valid_product(self):
        return {
            "name": "Test Product",
            "version": "1.0.0",
            "plan": {
                "type": "SUBSCRIPTION",
                "currency": "USD",
                "period": "MONTH",
                "tiers": [{"name": "Standard", "up_to": None, "unit_amount": 0.01}],
            },
        }

    def test_valid_product_passes(self):
        product = self._valid_product()
        result = ProductValidationEngine.validate_complete_product(product)
        assert result["name"] == "Test Product"

    def test_missing_name_raises(self):
        product = self._valid_product()
        del product["name"]
        with pytest.raises(ValidationError, match="validation failed"):
            ProductValidationEngine.validate_complete_product(product)

    def test_missing_version_raises(self):
        product = self._valid_product()
        del product["version"]
        with pytest.raises(ValidationError, match="validation failed"):
            ProductValidationEngine.validate_complete_product(product)

    def test_missing_plan_raises(self):
        product = self._valid_product()
        del product["plan"]
        with pytest.raises(ValidationError, match="validation failed"):
            ProductValidationEngine.validate_complete_product(product)

    def test_invalid_email_in_product(self):
        product = self._valid_product()
        product["notification_addresses_on_invoice"] = ["bad-email"]
        with pytest.raises(ValidationError, match="validation failed"):
            ProductValidationEngine.validate_complete_product(product)

    def test_invalid_tags_in_product(self):
        product = self._valid_product()
        product["tags"] = "not-a-list"
        with pytest.raises(ValidationError, match="validation failed"):
            ProductValidationEngine.validate_complete_product(product)


class TestValidateProductForApi:
    """Tests for ProductValidationEngine.validate_product_for_api."""

    def _valid_product(self):
        return {
            "name": "API Product",
            "version": "2.0.0",
            "plan": {
                "type": "SUBSCRIPTION",
                "currency": "USD",
                "period": "MONTH",
                "tiers": [{"name": "Standard", "up_to": None, "unit_amount": 0.05}],
            },
        }

    def test_valid_api_product(self):
        result = ProductValidationEngine.validate_product_for_api(self._valid_product())
        assert result["name"] == "API Product"

    def test_subscription_without_period_raises(self):
        product = self._valid_product()
        del product["plan"]["period"]
        with pytest.raises(ValidationError):
            ProductValidationEngine.validate_product_for_api(product)
