"""BACK-4628: a partial plan on a product update keeps the stored plan fields."""

import pytest

from src.revenium_mcp_server.api_field_mapper import APIFieldMapper
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.common.partial_update_handler import PartialUpdateHandler
from src.revenium_mcp_server.common.update_configs import UpdateConfigs
from tests.unit.test_partial_update_caller_wins import RecordingClient

STORED_TIERS = [
    {"id": "t1", "name": "all usage", "startingFrom": 0, "upTo": None, "unitAmount": 0.01}
]
STORED_ELEMENTS = [{"id": "el_1", "name": "tokens"}]
STORED_SETUP_FEES = [{"name": "onboarding", "flatAmount": 50, "type": "SUBSCRIPTION"}]

STORED_PRODUCT = {
    "id": "prod_1",
    "name": "API plan",
    "version": "1.0.0",
    "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
    "plan": {
        "name": "fs plan a",
        "type": "SUBSCRIPTION",
        "currency": "USD",
        "period": "MONTH",
        "charge": 0,
        "tiers": STORED_TIERS,
        "elements": STORED_ELEMENTS,
        "setupFees": STORED_SETUP_FEES,
    },
}

AGGREGATION_ONLY_PRODUCT = {
    **STORED_PRODUCT,
    "plan": {
        **STORED_PRODUCT["plan"],
        "tiers": [],
        "ratingAggregations": [{"elementDefinitionId": "el_1", "tiers": STORED_TIERS}],
    },
}


async def _update_product(stored, caller_data) -> RecordingClient:
    client = RecordingClient(stored)
    config = UpdateConfigs.create_products_config(client)
    await PartialUpdateHandler().update_with_merge(stored["id"], caller_data, config)
    return client


class TestPartialPlanKeepsStoredFields:
    @pytest.mark.asyncio
    async def test_changing_only_the_charge_keeps_the_tiers(self):
        client = await _update_product(
            STORED_PRODUCT,
            {"plan": {"name": "fs plan b", "currency": "USD", "type": "SUBSCRIPTION", "charge": 10}},
        )
        plan = client.sent["plan"]
        assert plan["charge"] == 10
        assert plan["name"] == "fs plan b"
        assert plan["tiers"] == STORED_TIERS

    @pytest.mark.asyncio
    async def test_changing_one_plan_field_keeps_period_elements_and_setup_fees(self):
        client = await _update_product(STORED_PRODUCT, {"plan": {"charge": 25}})
        plan = client.sent["plan"]
        assert plan["period"] == "MONTH"
        assert plan["elements"] == STORED_ELEMENTS
        assert plan["setupFees"] == STORED_SETUP_FEES
        assert plan["tiers"] == STORED_TIERS

    @pytest.mark.asyncio
    async def test_sent_tiers_replace_the_stored_ones(self):
        new_tiers = [{"name": "flat", "upTo": None, "unitAmount": 0.02}]
        client = await _update_product(STORED_PRODUCT, {"plan": {"tiers": new_tiers}})
        assert client.sent["plan"]["tiers"] == new_tiers
        assert client.sent["plan"]["charge"] == 0

    @pytest.mark.asyncio
    async def test_aggregation_tiers_count_as_tiers(self):
        client = await _update_product(AGGREGATION_ONLY_PRODUCT, {"plan": {"charge": 5}})
        assert client.sent["plan"]["ratingAggregations"][0]["tiers"] == STORED_TIERS

    @pytest.mark.asyncio
    async def test_a_plan_without_top_level_tiers_keeps_its_aggregation_tiers(self):
        aggregation_plan = {
            key: value for key, value in AGGREGATION_ONLY_PRODUCT["plan"].items() if key != "tiers"
        }
        stored = {**AGGREGATION_ONLY_PRODUCT, "plan": aggregation_plan}
        client = await _update_product(stored, {"plan": {"charge": 5}})
        plan = client.sent["plan"]
        assert plan["charge"] == 5
        assert "tiers" not in plan
        assert plan["ratingAggregations"][0]["tiers"] == STORED_TIERS


class TestPlanWithoutTiersIsRefused:
    @pytest.mark.asyncio
    async def test_emptying_the_tiers_is_refused_before_any_put(self):
        client = RecordingClient(STORED_PRODUCT)
        config = UpdateConfigs.create_products_config(client)
        with pytest.raises(ToolError) as refusal:
            await PartialUpdateHandler().update_with_merge(
                "prod_1", {"plan": {"tiers": []}}, config
            )
        assert refusal.value.message == (
            "Required plan field 'tiers' is empty: the update would remove every pricing tier"
        )
        assert refusal.value.field == "plan.tiers"
        assert any("Leave 'tiers' out" in hint for hint in refusal.value.suggestions)
        assert client.put_bodies == []

    @pytest.mark.asyncio
    async def test_a_stored_plan_without_tiers_is_refused_when_the_plan_changes(self):
        stored = {**STORED_PRODUCT, "plan": {"name": "bare", "type": "SUBSCRIPTION"}}
        client = RecordingClient(stored)
        config = UpdateConfigs.create_products_config(client)
        with pytest.raises(ToolError) as refusal:
            await PartialUpdateHandler().update_with_merge(
                "prod_1", {"plan": {"charge": 10}}, config
            )
        assert "the product currently has no pricing tier" in refusal.value.message
        assert "would remove every pricing tier" not in refusal.value.message
        assert not any("Leave 'tiers' out" in hint for hint in refusal.value.suggestions)
        assert client.put_bodies == []

    @pytest.mark.asyncio
    async def test_empty_tiers_on_a_stored_tierless_plan_ask_for_a_tier(self):
        stored = {**STORED_PRODUCT, "plan": {"name": "bare", "type": "SUBSCRIPTION", "tiers": []}}
        client = RecordingClient(stored)
        config = UpdateConfigs.create_products_config(client)
        with pytest.raises(ToolError) as refusal:
            await PartialUpdateHandler().update_with_merge(
                "prod_1", {"plan": {"tiers": []}}, config
            )
        assert "the product currently has no pricing tier" in refusal.value.message
        assert not any("Leave 'tiers' out" in hint for hint in refusal.value.suggestions)
        assert client.put_bodies == []

    @pytest.mark.asyncio
    async def test_an_update_that_leaves_the_plan_alone_is_not_checked(self):
        stored = {**STORED_PRODUCT, "plan": {"name": "bare", "type": "SUBSCRIPTION"}}
        client = await _update_product(stored, {"name": "renamed"})
        assert client.sent["name"] == "renamed"


class TestPublicationIsNotInvented:
    """BACK-4662: an update sends the stored publication, never an invented one."""

    @pytest.mark.asyncio
    async def test_update_of_a_record_without_published_does_not_publish_it(self):
        client = await _update_product(STORED_PRODUCT, {"name": "renamed"})
        assert "published" not in APIFieldMapper.map_product_fields(client.sent)

    @pytest.mark.asyncio
    async def test_update_keeps_a_stored_published_product_published(self):
        client = await _update_product({**STORED_PRODUCT, "published": True}, {"name": "renamed"})
        assert APIFieldMapper.map_product_fields(client.sent)["published"] is True
