"""Tests for api_field_mapper.py — field mapping between internal and API formats."""


from src.revenium_mcp_server.api_field_mapper import APIFieldMapper


class TestMapTierFields:
    def test_maps_snake_case_to_camel_case(self):
        tier = {"starting_from": 0, "up_to": 100, "unit_amount": 5.0, "flat_amount": 10}
        result = APIFieldMapper.map_tier_fields(tier)
        assert result["startingFrom"] == 0
        assert result["upTo"] == 100
        assert result["unitAmount"] == 5.0
        assert result["flatAmount"] == 10

    def test_preserves_unmapped_fields(self):
        tier = {"name": "basic", "custom_field": "val"}
        result = APIFieldMapper.map_tier_fields(tier)
        assert result["name"] == "basic"
        assert result["custom_field"] == "val"


class TestMapRatingAggregationFields:
    def test_maps_basic_fields(self):
        ra = {"type": "SUM", "metering_element_id": "elem-1", "name": "Total"}
        result = APIFieldMapper.map_rating_aggregation_fields(ra)
        assert result["aggregationType"] == "SUM"
        assert result["elementDefinitionId"] == "elem-1"
        assert result["name"] == "Total"

    def test_maps_nested_tiers(self):
        ra = {
            "name": "Tiered",
            "tiers": [
                {"starting_from": 0, "up_to": 100, "unit_amount": 1.0},
            ],
        }
        result = APIFieldMapper.map_rating_aggregation_fields(ra)
        assert result["tiers"][0]["startingFrom"] == 0
        assert result["tiers"][0]["unitAmount"] == 1.0


class TestMapSetupFeeFields:
    def test_maps_amount_to_flat_amount(self):
        fee = {"amount": 99.99, "name": "Setup"}
        result = APIFieldMapper.map_setup_fee_fields(fee)
        assert result["flatAmount"] == 99.99
        assert result["name"] == "Setup"

    def test_skips_currency_and_description(self):
        fee = {"amount": 10, "currency": "USD", "description": "desc", "one_time": True}
        result = APIFieldMapper.map_setup_fee_fields(fee)
        assert "currency" not in result
        assert "description" not in result
        assert "one_time" not in result

    def test_default_type_added(self):
        fee = {"amount": 10, "name": "Setup"}
        result = APIFieldMapper.map_setup_fee_fields(fee)
        assert result["type"] == "ORGANIZATION"

    def test_backward_compatible_type_conversion(self):
        fee = {"amount": 10, "name": "Setup", "type": "PRODUCT_LICENSE"}
        result = APIFieldMapper.map_setup_fee_fields(fee)
        assert result["type"] == "SUBSCRIPTION"

    def test_customer_type_converts_to_organization(self):
        assert APIFieldMapper._convert_setup_fee_type("CUSTOMER") == "ORGANIZATION"

    def test_unknown_type_passes_through(self):
        assert APIFieldMapper._convert_setup_fee_type("CUSTOM") == "CUSTOM"


class TestMapElementFields:
    def test_maps_element_fields(self):
        elem = {
            "metering_element_definition_id": "def-1",
            "name": "API Calls",
            "unit_of_measure": "calls",
        }
        result = APIFieldMapper.map_element_fields(elem)
        assert result["elementDefinitionId"] == "def-1"
        assert result["unitOfMeasure"] == "calls"


class TestMapPlanFields:
    def test_maps_simple_plan_fields(self):
        plan = {"period_count": 1, "trial_period": "MONTH", "name": "Basic"}
        result = APIFieldMapper.map_plan_fields(plan)
        assert result["periodCount"] == 1
        assert result["trialPeriod"] == "MONTH"

    def test_maps_nested_tiers_in_plan(self):
        plan = {"name": "Tiered", "tiers": [{"starting_from": 0}]}
        result = APIFieldMapper.map_plan_fields(plan)
        assert result["tiers"][0]["startingFrom"] == 0

    def test_maps_nested_rating_aggregations(self):
        plan = {
            "name": "Rated",
            "rating_aggregations": [
                {"type": "COUNT", "metering_element_id": "e1"},
            ],
        }
        result = APIFieldMapper.map_plan_fields(plan)
        assert result["ratingAggregations"][0]["aggregationType"] == "COUNT"

    def test_maps_nested_setup_fees(self):
        plan = {
            "name": "WithSetup",
            "setup_fees": [{"amount": 50, "name": "Onboarding"}],
        }
        result = APIFieldMapper.map_plan_fields(plan)
        assert result.get("setupFees") == [
            {"flatAmount": 50, "name": "Onboarding", "type": "ORGANIZATION"}
        ]
        assert "setups" not in result

    def test_camel_case_setup_fees_still_pass_through(self):
        fees = [{"name": "x", "type": "SUBSCRIPTION", "flatAmount": 50}]
        result = APIFieldMapper.map_plan_fields({"name": "P", "setupFees": fees})
        assert result["setupFees"] == [{"name": "x", "type": "SUBSCRIPTION", "flatAmount": 50}]
        assert "setups" not in result

    def test_create_product_body_carries_snake_case_setup_fee(self):
        product = {
            "name": "P",
            "version": "1",
            "plan": {
                "name": "PP",
                "setup_fees": [{"name": "s", "type": "SUBSCRIPTION", "flatAmount": 50}],
            },
        }
        plan = APIFieldMapper.map_product_fields(product)["plan"]
        assert plan.get("setupFees") == [{"name": "s", "type": "SUBSCRIPTION", "flatAmount": 50}]
        assert "setups" not in plan

    def test_both_setup_fee_spellings_are_combined(self):
        camel = {"name": "camel", "type": "SUBSCRIPTION", "flatAmount": 75}
        snake = {"name": "snake", "type": "SUBSCRIPTION", "flatAmount": 50}
        # The snake key comes first in the dict; the camel fees still lead.
        plan = {"name": "P", "setup_fees": [snake], "setupFees": [camel]}
        result = APIFieldMapper.map_plan_fields(plan)
        assert result.get("setupFees") == [camel, snake]
        assert "setups" not in result

    def test_maps_nested_elements(self):
        plan = {
            "name": "WithElements",
            "elements": [{"metering_element_definition_id": "d1", "name": "Calls"}],
        }
        result = APIFieldMapper.map_plan_fields(plan)
        assert result["elements"][0]["elementDefinitionId"] == "d1"


class TestMapProductFields:
    def test_maps_product_level_fields(self):
        product = {
            "source_ids": ["s1"],
            "coming_soon": True,
            "name": "My Product",
            "version": "1.0",
        }
        result = APIFieldMapper.map_product_fields(product)
        assert result["sourceIds"] == ["s1"]
        assert result["comingSoon"] is True

    def test_adds_default_fields(self):
        product = {"name": "P", "version": "1.0"}
        result = APIFieldMapper.map_product_fields(product)
        assert result["notifyClientOnInvoice"] is False
        assert result["paymentSource"] == "INVOICE_ONLY_NO_PAYMENT"
        assert result["subscriptionAllowMidPeriodCancellation"] is False

    def test_does_not_override_existing_defaults(self):
        product = {"name": "P", "version": "1.0", "published": False}
        result = APIFieldMapper.map_product_fields(product)
        assert result["published"] is False

    def test_does_not_invent_published(self):
        """BACK-4662: create and update share this mapper, so it must not publish."""
        result = APIFieldMapper.map_product_fields({"name": "P", "version": "1.0"})
        assert "published" not in result

    def test_explicit_published_true_is_kept(self):
        product = {"name": "P", "version": "1.0", "published": True}
        result = APIFieldMapper.map_product_fields(product)
        assert result["published"] is True

    def test_maps_nested_plan(self):
        product = {
            "name": "P",
            "version": "1.0",
            "plan": {"period_count": 1, "name": "Monthly"},
        }
        result = APIFieldMapper.map_product_fields(product)
        assert result["plan"]["periodCount"] == 1


class TestValidateRequiredApiFields:
    def test_product_missing_fields(self):
        missing = APIFieldMapper.validate_required_api_fields({}, "product")
        assert "name" in missing
        assert "version" in missing
        assert "plan" in missing

    def test_product_all_present(self):
        data = {"name": "P", "version": "1.0", "plan": {"name": "Basic"}}
        assert APIFieldMapper.validate_required_api_fields(data, "product") == []

    def test_plan_missing_fields(self):
        missing = APIFieldMapper.validate_required_api_fields({}, "plan")
        assert "name" in missing
        assert "currency" in missing

    def test_tier_missing_fields(self):
        missing = APIFieldMapper.validate_required_api_fields({}, "tier")
        assert "name" in missing

    def test_rating_aggregation_missing_fields(self):
        missing = APIFieldMapper.validate_required_api_fields({}, "rating_aggregation")
        assert "aggregationType" in missing

    def test_setup_fee_missing_fields(self):
        missing = APIFieldMapper.validate_required_api_fields({}, "setup_fee")
        assert "flatAmount" in missing

    def test_unknown_type_returns_empty(self):
        assert APIFieldMapper.validate_required_api_fields({}, "unknown") == []


class TestMapTransactionFields:
    def test_returns_copy(self):
        data = {"model": "gpt-4", "tokens": 100}
        result = APIFieldMapper.map_transaction_fields(data)
        assert result == data
        assert result is not data
