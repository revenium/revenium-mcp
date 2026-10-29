"""A product create is checked against the platform's plan contract before anything is sent.

BACK-5090: the plan currency is checked against the platform's list in the
preview and the real create, and every place that advertises currencies reads
that one list. BACK-5095: aggregation tiers are validated and sent the same way
under either plan key spelling, so a usage price is never stored as 0.
"""

import copy
import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.plan_contract import platform_plan_currencies
from src.revenium_mcp_server.product_validation_engine import ProductValidationEngine
from src.revenium_mcp_server.tools_decomposed.product_management import (
    ProductManagement,
    ProductValidator,
)
from tests.unit.test_openapi_contract import HYPERCURRENT

SNAPSHOT_PLAN_CURRENCIES: List[str] = list(
    HYPERCURRENT["components"]["schemas"]["Plan"]["properties"]["currency"]["enum"]
)


def _usage_product(plan_key: str = "ratingAggregations", **tier: Any) -> Dict[str, Any]:
    """The 15-SE-39 audit payload: a flat top-level tier plus one priced aggregation."""
    aggregation_tier = tier or {
        "name": "agg tier",
        "up_to": None,
        "unit_amount": "0.001",
    }
    return {
        "name": "mcp-test-se39-dry",
        "description": "d",
        "version": "1.0.0",
        "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
        "sourceIds": ["QOjdKkd"],
        "plan": {
            "type": "SUBSCRIPTION",
            "name": "p",
            "currency": "USD",
            "period": "MONTH",
            "tiers": [{"name": "t1", "up_to": 1000, "unit_amount": "0.01"}],
            plan_key: [
                {
                    "name": "agg",
                    "elementDefinitionId": "MrVQzgJ",
                    "aggregationType": "COUNT",
                    "tiers": [aggregation_tier],
                }
            ],
        },
    }


def _flat_product(currency: str) -> Dict[str, Any]:
    """The 9a audit payload: valid in every field but the currency under test."""
    return {
        "name": "mcp-test-dryrun-prod3",
        "description": "d",
        "version": "1.0.0",
        "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
        "plan": {
            "type": "SUBSCRIPTION",
            "name": "p",
            "currency": currency,
            "period": "MONTH",
            "tiers": [{"name": "t", "up_to": None, "unit_amount": "0.01"}],
        },
    }


def _management():
    client = MagicMock()
    client.team_id = "team_test"
    client.create_product = AsyncMock(
        return_value={"id": "p_new", "name": "New Product"}
    )
    management = ProductManagement()
    management.get_client = AsyncMock(return_value=client)
    return management, client


async def _create(product_data: Dict[str, Any], *, dry_run: bool):
    management, client = _management()
    with patch(
        "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
        return_value=None,
    ):
        result = await management.handle_action(
            "create", {"product_data": copy.deepcopy(product_data), "dry_run": dry_run}
        )
    return result[0].text, client


def _previewed_plan(text: str) -> Dict[str, Any]:
    return json.loads(text.split("```json\n", 1)[1].split("\n```", 1)[0])["plan"]


class TestUnsupportedCurrencyIsRefused:
    """BACK-5090: the preview said "valid and ready for creation" for currency XXX."""

    @pytest.mark.asyncio
    async def test_the_preview_refuses_a_currency_the_platform_does_not_have(self):
        with pytest.raises(ToolError) as refused:
            await _create(_flat_product("XXX"), dry_run=True)

        message = str(refused.value.message)
        assert "Invalid Currency: XXX" in message
        assert ", ".join(SNAPSHOT_PLAN_CURRENCIES) in message

    @pytest.mark.asyncio
    async def test_the_real_create_refuses_it_before_any_request(self):
        management, client = _management()
        with (
            patch(
                "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
                return_value=None,
            ),
            pytest.raises(ToolError) as refused,
        ):
            await management.handle_action(
                "create", {"product_data": _flat_product("XXX")}
            )

        client.create_product.assert_not_awaited()
        assert "Invalid Currency: XXX" in str(refused.value.message)

    @pytest.mark.asyncio
    async def test_zwg_passes_the_preview(self):
        text, client = await _create(_flat_product("ZWG"), dry_run=True)

        assert "Validation Successful" in text
        assert _previewed_plan(text)["currency"] == "ZWG"
        client.create_product.assert_not_awaited()

    def test_the_validate_action_refuses_it_too(self):
        result = ProductValidator().validate_configuration(_flat_product("XXX"))

        assert result["valid"] is False
        assert "Invalid Currency: XXX" in result["errors"][0]["error"]


class TestOneCurrencyList:
    """BACK-5090: the advertised currencies are the platform's, from one definition."""

    def test_the_list_is_the_platform_plan_contract(self):
        assert list(platform_plan_currencies()) == SNAPSHOT_PLAN_CURRENCIES

    def test_the_currency_model_holds_every_platform_currency(self):
        from src.revenium_mcp_server.models import Currency

        assert sorted(member.value for member in Currency) == sorted(
            SNAPSHOT_PLAN_CURRENCIES
        )

    @pytest.mark.asyncio
    async def test_product_capabilities_advertise_the_platform_list(self):
        from src.revenium_mcp_server.capability_manager.discovery import (
            CapabilityDiscovery,
        )

        capabilities = await CapabilityDiscovery(
            MagicMock()
        )._discover_product_capabilities()

        assert capabilities["currencies"] == SNAPSHOT_PLAN_CURRENCIES
        assert (
            capabilities["validation_rules"]["plan.currency"]["enum"]
            == SNAPSHOT_PLAN_CURRENCIES
        )

    def test_the_product_json_schema_advertises_the_platform_list(self):
        from src.revenium_mcp_server.json_schema_validator import json_schema_validator

        product_data = json_schema_validator.schemas["manage_products"]["properties"][
            "product_data"
        ]
        currency = product_data["properties"]["plan"]["properties"]["currency"]
        assert currency["enum"] == SNAPSHOT_PLAN_CURRENCIES

    @pytest.mark.asyncio
    async def test_the_static_capabilities_text_lists_every_platform_currency(self):
        text = await ProductManagement()._build_enhanced_capabilities_text(None)

        section = text.split("## **Supported Currencies**", 1)[1].split("##", 1)[0]
        assert [line.strip("- *") for line in section.split() if line.strip("- *")] == (
            SNAPSHOT_PLAN_CURRENCIES
        )


class TestAggregationTiersUnderEitherPlanKey:
    """BACK-5095 (SE-39): ratingAggregations stored its tier price as 0 behind a success."""

    @pytest.mark.parametrize("plan_key", ["ratingAggregations", "rating_aggregations"])
    @pytest.mark.asyncio
    async def test_the_preview_shows_the_aggregation_tier_as_it_will_be_sent(
        self, plan_key
    ):
        text, _ = await _create(_usage_product(plan_key), dry_run=True)

        tier = _previewed_plan(text)["ratingAggregations"][0]["tiers"][0]
        assert tier == {"name": "agg tier", "upTo": None, "unitAmount": "0.001"}

    @pytest.mark.parametrize("plan_key", ["ratingAggregations", "rating_aggregations"])
    def test_a_negative_aggregation_price_is_refused_under_either_key(self, plan_key):
        product = _usage_product(
            plan_key, name="agg tier", up_to=None, unit_amount="-1"
        )

        result = ProductValidationEngine.validate_product_data(product)

        assert not result.is_valid
        assert any("Unit amount cannot be negative" in e.error for e in result.errors)

    @pytest.mark.parametrize("plan_key", ["ratingAggregations", "rating_aggregations"])
    def test_camel_case_aggregation_tier_fields_are_accepted_and_checked(
        self, plan_key
    ):
        product = _usage_product(
            plan_key, name="agg tier", upTo=None, unitAmount="0.001"
        )

        result = ProductValidationEngine.validate_product_data(product)

        assert result.is_valid, [e.error for e in result.errors]

    @pytest.mark.parametrize("plan_key", ["ratingAggregations", "rating_aggregations"])
    def test_a_tier_whose_price_key_the_platform_ignores_is_refused(self, plan_key):
        product = _usage_product(plan_key, name="agg tier", up_to=None, price="0.001")

        result = ProductValidationEngine.validate_product_data(product)

        assert not result.is_valid
        assert any("missing unit_amount" in e.error for e in result.errors)

    def test_camel_case_top_level_tier_fields_are_accepted(self):
        product = _usage_product()
        product["plan"]["tiers"] = [{"name": "t1", "upTo": 1000, "unitAmount": "0.01"}]

        result = ProductValidationEngine.validate_product_data(product)

        assert result.is_valid, [e.error for e in result.errors]


class TestAggregationReviewFollowUps:
    """BACK-5095 review: every path that reads a plan's aggregations reads both keys."""

    @pytest.mark.parametrize("dry_run", [True, False])
    @pytest.mark.parametrize("plan_key", ["ratingAggregations", "rating_aggregations"])
    @pytest.mark.asyncio
    async def test_aggregation_tiers_that_are_not_a_list_are_refused(
        self, plan_key, dry_run
    ):
        product = _usage_product(plan_key)
        product["plan"][plan_key][0]["tiers"] = {"up_to": None, "unit_amount": "0.001"}

        management, client = _management()
        with (
            patch(
                "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
                return_value=None,
            ),
            pytest.raises(ToolError) as refused,
        ):
            await management.handle_action(
                "create", {"product_data": product, "dry_run": dry_run}
            )

        client.create_product.assert_not_awaited()
        assert f"plan.{plan_key}[0].tiers" in str(refused.value.message)

    def test_plan_tiers_that_are_not_a_list_are_refused(self):
        product = _flat_product("USD")
        product["plan"]["tiers"] = {"name": "t", "up_to": None, "unit_amount": "0.01"}

        result = ProductValidationEngine.validate_product_data(product)

        assert any(e.field == "plan.tiers" for e in result.errors)

    @pytest.mark.asyncio
    async def test_an_update_with_the_snake_key_replaces_the_stored_aggregations(self):
        from src.revenium_mcp_server.api_field_mapper import APIFieldMapper
        from src.revenium_mcp_server.tools_decomposed.product_management import (
            ProductManager,
        )

        stored_aggregation = {
            "name": "old",
            "elementDefinitionId": "el",
            "aggregationType": "COUNT",
            "tiers": [{"name": "old tier", "upTo": None, "unitAmount": 0.5}],
        }
        client = MagicMock()
        client.team_id = "team_abc"
        client.get_product_by_id = AsyncMock(
            return_value={
                "id": "p1",
                "name": "Stored",
                "version": "1.0.0",
                "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
                "plan": {
                    "type": "SUBSCRIPTION",
                    "tiers": [{"name": "t1", "unitAmount": 0}],
                    "ratingAggregations": [stored_aggregation],
                },
            }
        )
        client.prepare_product_update_body = APIFieldMapper.map_product_fields
        new_aggregation = _usage_product("rating_aggregations")["plan"][
            "rating_aggregations"
        ][0]

        preview = await ProductManager(client).preview_update(
            {
                "product_id": "p1",
                "product_data": {"plan": {"rating_aggregations": [new_aggregation]}},
            }
        )

        sent = preview["body"]["plan"]["ratingAggregations"]
        assert [aggregation["name"] for aggregation in sent] == ["agg"]
        assert sent[0]["tiers"][0]["unitAmount"] == "0.001"

    @pytest.mark.asyncio
    async def test_create_with_subscription_keeps_snake_key_aggregations_as_sent(self):
        from tests.unit.test_product_hierarchy_routing import (
            TestCreateWithSubscription,
            _valid_product_data,
        )

        product = _valid_product_data()
        product["plan"]["tiers"] = [
            {"name": "t1", "up_to": None, "unit_amount": "0.01"}
        ]
        product["plan"]["rating_aggregations"] = _usage_product("rating_aggregations")[
            "plan"
        ]["rating_aggregations"]

        sent = await TestCreateWithSubscription()._create_with(product)

        assert "ratingAggregations" not in sent["plan"]
        assert sent["plan"]["tiers"][0]["up_to"] is None

    @pytest.mark.asyncio
    async def test_create_with_subscription_leaves_a_limited_camel_tier_alone(self):
        from tests.unit.test_product_hierarchy_routing import (
            TestCreateWithSubscription,
            _valid_product_data,
        )

        product = _valid_product_data()
        product["plan"]["tiers"] = [{"name": "t1", "upTo": 1000, "unitAmount": "0.01"}]

        sent = await TestCreateWithSubscription()._create_with(product)

        from src.revenium_mcp_server.api_field_mapper import APIFieldMapper

        assert APIFieldMapper.map_plan_fields(sent["plan"])["tiers"][0]["upTo"] == 1000

    @pytest.mark.asyncio
    async def test_the_subscription_capabilities_text_lists_every_platform_currency(
        self,
    ):
        from src.revenium_mcp_server.tools_decomposed.subscription_management import (
            SubscriptionManagement,
        )

        text = await SubscriptionManagement()._build_enhanced_capabilities_text(None)

        section = text.split("## **Supported Currencies**", 1)[1].split("##", 1)[0]
        assert [c.strip("-*, ") for c in section.split() if c.strip("-*, ")] == (
            SNAPSHOT_PLAN_CURRENCIES
        )
