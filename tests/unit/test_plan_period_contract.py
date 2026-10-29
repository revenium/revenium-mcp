"""BACK-5146: a plan period the platform does not have is refused before any request.

The regression run on dev previewed manage_products create with plan.period
QUARTER and WEEK as "Validation Successful", then the live create came back as
HTTP 400 "Invalid Period: QUARTER; only these values are allowed: DAY, MONTH,
YEAR, TEST_MINUTE, TEST_MINUTE_WITH_SYNTHETIC_METERING, NONE". That is the
BACK-948 contract (every enum value the server accepts is one the platform
accepts) failing for plan.period.
"""

import copy
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.api_field_mapper import APIFieldMapper
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.models import BillingPeriod, TrialPeriod
from src.revenium_mcp_server.tools_decomposed.product_management import (
    ProductManagement,
)
from tests.unit.openapi_snapshot import hypercurrent_or_skip_module

HYPERCURRENT = hypercurrent_or_skip_module()

_PLAN_PROPERTIES = HYPERCURRENT["components"]["schemas"]["Plan"]["properties"]
SPEC_PLAN_PERIODS: List[str] = list(_PLAN_PROPERTIES["period"]["enum"])
SPEC_TRIAL_PERIODS: List[str] = list(_PLAN_PROPERTIES["trialPeriod"]["enum"])
PERIOD_REFUSAL_TAIL = f"only these values are allowed: {', '.join(SPEC_PLAN_PERIODS)}"

STORED_PRODUCT: Dict[str, Any] = {
    "id": "3ByoYab",
    "name": "mcp-test-prod",
    "description": "audit product",
    "version": "1.0.0",
    "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
    "plan": {
        "type": "SUBSCRIPTION",
        "name": "p",
        "currency": "USD",
        "period": "MONTH",
        "tiers": [{"name": "t", "upTo": None, "unitAmount": 0.01}],
    },
}


def _product(period: str) -> Dict[str, Any]:
    """The 15b BACK-948 p4/p6 payload: valid in every field but the period under test."""
    return {
        "name": "mcp-test-back948-period",
        "description": "d",
        "version": "1.0.0",
        "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
        "plan": {
            "type": "SUBSCRIPTION",
            "name": "p",
            "currency": "USD",
            "period": period,
            "tiers": [{"name": "t", "up_to": None, "unit_amount": "0.01"}],
        },
    }


def _management():
    client = MagicMock()
    client.team_id = "team_test"
    client.create_product = AsyncMock(
        return_value={"id": "p_new", "name": "New Product"}
    )
    client.get_product_by_id = AsyncMock(return_value=copy.deepcopy(STORED_PRODUCT))
    client.update_product = AsyncMock(
        side_effect=lambda product_id, body: {**body, "id": product_id}
    )
    client.prepare_product_update_body = APIFieldMapper.map_product_fields
    management = ProductManagement()
    management.get_client = AsyncMock(return_value=client)
    return management, client


async def _call(action: str, arguments: Dict[str, Any]):
    management, client = _management()
    with patch(
        "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
        return_value=None,
    ):
        result = await management.handle_action(action, copy.deepcopy(arguments))
    return result[0].text, client


async def _refusal(action: str, arguments: Dict[str, Any]):
    management, client = _management()
    with (
        patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ),
        pytest.raises(ToolError) as refused,
    ):
        await management.handle_action(action, copy.deepcopy(arguments))
    return str(refused.value.message), client


def _create(period: str, *, dry_run: bool) -> Dict[str, Any]:
    return {"product_data": _product(period), "dry_run": dry_run}


def _update(period: str, *, dry_run: bool) -> Dict[str, Any]:
    return {
        "product_id": "3ByoYab",
        "product_data": {"plan": {"period": period}},
        "dry_run": dry_run,
    }


def _section(text: str, heading: str) -> List[str]:
    body = text.split(f"## **{heading}**", 1)[1].split("##", 1)[0]
    return [word.strip("-*, ") for word in body.split() if word.strip("-*, ")]


class TestServerEnumsAreTheSpecEnums:
    def test_billing_period_is_the_plan_period_enum(self):
        assert [member.value for member in BillingPeriod] == SPEC_PLAN_PERIODS

    def test_trial_period_is_the_plan_trial_period_enum(self):
        assert [member.value for member in TrialPeriod] == SPEC_TRIAL_PERIODS


class TestUnsupportedPeriodIsRefused:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("period", ["QUARTER", "WEEK"])
    @pytest.mark.parametrize("dry_run", [True, False], ids=["dry_run", "live"])
    async def test_create_refuses_it_before_any_request(self, period, dry_run):
        message, client = await _refusal("create", _create(period, dry_run=dry_run))

        assert f"Invalid Plan period: {period}; {PERIOD_REFUSAL_TAIL}" in message
        client.create_product.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("period", ["QUARTER", "WEEK"])
    @pytest.mark.parametrize("dry_run", [True, False], ids=["dry_run", "live"])
    async def test_update_refuses_it_before_any_request(self, period, dry_run):
        message, client = await _refusal("update", _update(period, dry_run=dry_run))

        assert f"Invalid Plan period: {period}; {PERIOD_REFUSAL_TAIL}" in message
        client.get_product_by_id.assert_not_awaited()
        client.update_product.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_preview_and_the_live_create_refuse_with_the_same_text(self):
        preview, _ = await _refusal("create", _create("QUARTER", dry_run=True))
        live, _ = await _refusal("create", _create("QUARTER", dry_run=False))

        assert preview == live


class TestOtherCreatePathsRefuseIt:
    @pytest.mark.asyncio
    async def test_create_with_subscription_refuses_it_before_any_lookup(self):
        from tests.unit.test_product_hierarchy_routing import (
            _make_client,
            _make_hierarchy_manager,
            _valid_subscription_data,
        )

        client = _make_client()
        manager = _make_hierarchy_manager(client)
        manager.validator.validate_hierarchy_operation = AsyncMock()

        with pytest.raises(ToolError) as refused:
            await manager.create_with_subscription(
                {
                    "product_data": _product("QUARTER"),
                    "subscription_data": _valid_subscription_data(),
                }
            )

        assert f"Invalid Plan period: QUARTER; {PERIOD_REFUSAL_TAIL}" in str(
            refused.value.message
        )
        manager.validator.validate_hierarchy_operation.assert_not_awaited()
        client.get_sources.assert_not_awaited()
        client.create_product.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_weekly_description_is_refused_instead_of_sent(self):
        message, client = await _refusal(
            "create",
            {
                "description": "A weekly subscription for API access at $10 per week",
                "dry_run": False,
            },
        )

        assert f"Invalid Plan period: WEEK; {PERIOD_REFUSAL_TAIL}" in message
        client.create_product.assert_not_awaited()


class TestEverySpecPeriodIsAccepted:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("period", SPEC_PLAN_PERIODS)
    async def test_create_sends_it_unchanged(self, period):
        _, client = await _call("create", _create(period, dry_run=False))

        sent = client.create_product.await_args.args[0]
        assert sent["plan"]["period"] == period

    @pytest.mark.asyncio
    @pytest.mark.parametrize("period", SPEC_PLAN_PERIODS)
    async def test_update_sends_it_unchanged(self, period):
        _, client = await _call("update", _update(period, dry_run=False))

        sent = client.update_product.await_args.args[1]
        assert sent["plan"]["period"] == period


class TestAdvertisedPeriodsAreTheSpecPeriods:
    @pytest.mark.asyncio
    async def test_the_product_capabilities_text_lists_the_spec_periods(self):
        text = await ProductManagement()._build_enhanced_capabilities_text(None)

        assert _section(text, "Billing Periods") == SPEC_PLAN_PERIODS

    @pytest.mark.asyncio
    async def test_the_subscription_capabilities_text_lists_the_spec_periods(self):
        from src.revenium_mcp_server.tools_decomposed.subscription_management import (
            SubscriptionManagement,
        )

        text = await SubscriptionManagement()._build_enhanced_capabilities_text(None)

        assert _section(text, "Billing Periods") == SPEC_PLAN_PERIODS
        assert _section(text, "Trial Periods") == SPEC_TRIAL_PERIODS

    @pytest.mark.asyncio
    async def test_subscription_capabilities_list_the_spec_periods(self):
        from src.revenium_mcp_server.capability_manager.discovery import (
            CapabilityDiscovery,
        )

        discovery = CapabilityDiscovery(MagicMock())
        discovery._discover_subscription_types_from_api = AsyncMock(
            return_value=["monthly"]
        )
        discovery._discover_currencies_from_api = AsyncMock(return_value=["USD"])

        capabilities = await discovery._discover_subscription_capabilities()

        assert capabilities["billing_periods"] == SPEC_PLAN_PERIODS
        assert capabilities["trial_periods"] == SPEC_TRIAL_PERIODS
