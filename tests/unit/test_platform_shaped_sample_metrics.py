"""BACK-4630: subscription metrics and customer analysis count only fields the
platform returns, over the page they read, and say which page that is."""

import inspect
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from src.revenium_mcp_server.client import ReveniumClient
from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.registry import ToolConfigurationRegistry
from src.revenium_mcp_server.tools_decomposed.customer_management import CustomerAnalytics
from src.revenium_mcp_server.tools_decomposed.subscription_management import (
    SubscriptionAnalytics,
)

NOW = datetime.now(timezone.utc)


def _iso(delta_days: float) -> str:
    return (NOW + timedelta(days=delta_days)).isoformat().replace("+00:00", "Z")


def _ref(resource_id: str, resource_type: str) -> dict:
    return {
        "_links": {"self": {"href": f"/profitstream/v2/api/{resource_type}s/{resource_id}"}},
        "id": resource_id,
        "label": resource_id,
        "resourceType": resource_type,
    }


def _subscription(sub_id, product, start, expiration=None, trial_end=None) -> dict:
    return {
        "id": sub_id,
        "resourceType": "subscription",
        "product": _ref(product, "product") if product else None,
        "start": start,
        "expiration": expiration,
        "trialEnd": trial_end,
        "periodEnd": _iso(20),
    }


def _page(key: str, rows: list, total: int, page: int = 0) -> dict:
    return {
        "_embedded": {key: rows},
        "page": {"number": page, "size": len(rows), "totalElements": total, "totalPages": 99},
    }


class FakePlatformClient:
    """Answers every list read with one platform-shaped HAL page."""

    _extract_embedded_data = ReveniumClient._extract_embedded_data
    _extract_pagination_info = ReveniumClient._extract_pagination_info

    def __init__(self, response: dict):
        self.team_id = "team-1"
        self.response = response
        self.calls: list = []

    async def _answer(self, **kwargs):
        self.calls.append(kwargs)
        return self.response

    get_subscriptions = get_organizations = get_users = get_subscribers = get_teams = _answer


SUBSCRIPTION_ROWS = [
    _subscription("s1", "pA", _iso(-30)),
    _subscription("s2", "pA", _iso(-30), expiration=_iso(30)),
    _subscription("s3", "pB", _iso(-5), trial_end=_iso(5)),
    _subscription("s4", "pB", _iso(-60), expiration=_iso(-1)),
    _subscription("s5", None, _iso(3)),
]


class TestSubscriptionMetrics:
    @pytest.mark.asyncio
    async def test_states_come_from_dates_not_a_status_field(self):
        client = FakePlatformClient(_page("subscriptionResourceList", SUBSCRIPTION_ROWS, 49408))
        metrics = await SubscriptionAnalytics(client).get_metrics({})

        assert metrics["total_subscriptions"] == 49408
        assert metrics["active_subscriptions"] == 3
        assert metrics["trial_subscriptions"] == 1
        assert metrics["expired_subscriptions"] == 1
        assert metrics["not_started_subscriptions"] == 1
        assert metrics["products_represented"] == 2

    @pytest.mark.asyncio
    async def test_rates_are_shares_of_the_covered_records(self):
        client = FakePlatformClient(_page("subscriptionResourceList", SUBSCRIPTION_ROWS, 49408))
        metrics = await SubscriptionAnalytics(client).get_metrics({})

        assert metrics["active_rate_in_sample"] == 60.0
        assert metrics["trial_rate_in_sample"] == 20.0
        assert metrics["expired_rate_in_sample"] == 20.0
        assert metrics["sample"]["records_covered"] == 5
        assert metrics["sample"]["total_records"] == 49408
        assert metrics["sample"]["covers_all_records"] is False
        assert "only the 5 records on page 0 of 49408" in metrics["sample"]["note"]

    @pytest.mark.asyncio
    async def test_figures_without_a_backing_field_are_not_reported(self):
        client = FakePlatformClient(_page("subscriptionResourceList", SUBSCRIPTION_ROWS, 5))
        metrics = await SubscriptionAnalytics(client).get_metrics({})

        for unbacked in ("conversion_rate", "churn_rate", "billing_distribution",
                         "cancelled_subscriptions"):
            assert unbacked not in metrics
        assert "no status field" in metrics["lifecycle_basis"]

    @pytest.mark.asyncio
    async def test_unreadable_start_is_counted_apart_and_not_as_active(self):
        rows = [_subscription("s1", "pA", None), _subscription("s2", "pA", "not a date")]
        client = FakePlatformClient(_page("subscriptionResourceList", rows, 2))
        metrics = await SubscriptionAnalytics(client).get_metrics({})

        assert metrics["active_subscriptions"] == 0
        assert metrics["subscriptions_without_readable_start"] == 2

    @pytest.mark.asyncio
    async def test_an_empty_page_reports_no_rate(self):
        client = FakePlatformClient(_page("subscriptionResourceList", [], 0))
        metrics = await SubscriptionAnalytics(client).get_metrics({})

        assert metrics["active_rate_in_sample"] is None
        assert metrics["sample"]["covers_all_records"] is True

    @pytest.mark.asyncio
    async def test_a_page_without_a_total_reports_coverage_as_unknown(self):
        client = FakePlatformClient({"_embedded": {"subscriptionResourceList": SUBSCRIPTION_ROWS}})
        metrics = await SubscriptionAnalytics(client).get_metrics({})

        assert metrics["total_subscriptions"] is None
        assert metrics["sample"]["records_covered"] == 5
        assert metrics["sample"]["total_records"] is None
        assert metrics["sample"]["covers_all_records"] is None
        assert "reported no total" in metrics["sample"]["note"]
        assert "cover all" not in metrics["sample"]["note"]

    @pytest.mark.asyncio
    async def test_a_call_without_size_reads_a_page_of_100(self):
        client = FakePlatformClient(_page("subscriptionResourceList", [], 0))
        await SubscriptionAnalytics(client).get_metrics({})

        assert client.calls[0]["size"] == 100


class TestManageSubscriptionsClosure:
    @pytest.mark.asyncio
    async def test_size_is_left_to_each_action(self):
        mcp = MagicMock()
        registry = ToolConfigurationRegistry(
            tool_config=ToolConfig.create_for_testing(profile="business")
        )
        await registry._register_manage_subscriptions(mcp)
        closure = mcp.tool.call_args_list[0][0][0].__wrapped__

        assert inspect.signature(closure).parameters["size"].default is None


ORGANIZATION_ROWS = [
    {"id": "o1", "resourceType": "organization", "parent": _ref("o9", "organization")},
    {"id": "o2", "resourceType": "organization", "parent": None, "parentId": "o9"},
    {"id": "o3", "resourceType": "organization", "parent": None},
    {"id": "o4", "resourceType": "organization"},
]


class TestCustomerAnalysis:
    @pytest.mark.asyncio
    async def test_organizations_with_a_parent_object_are_hierarchical(self):
        client = FakePlatformClient(_page("organizationResourceList", ORGANIZATION_ROWS, 146))
        result = await CustomerAnalytics(client).analyze_customers(
            {"resource_type": "organizations"}
        )

        assert result["total_organizations"] == 146
        assert result["hierarchical_organizations"] == 2
        assert result["hierarchical_rate_in_sample"] == 50.0
        assert result["sample"]["records_covered"] == 4
        for unbacked in ("active_organizations", "inactive_organizations", "activity_rate"):
            assert unbacked not in result

    @pytest.mark.asyncio
    async def test_users_count_teams_from_team_ids(self):
        rows = [
            {"id": "u1", "resourceType": "user", "teamIds": ["t1", "t2"]},
            {"id": "u2", "resourceType": "user", "teamIds": ["t2"]},
            {"id": "u3", "resourceType": "user", "teamIds": []},
        ]
        client = FakePlatformClient(_page("userResourceList", rows, 33))
        result = await CustomerAnalytics(client).analyze_customers({"resource_type": "users"})

        assert result["total_users"] == 33
        assert result["teams_represented"] == 2
        assert result["sample"]["records_covered"] == 3
        for unbacked in ("active_users", "inactive_users", "activity_rate",
                         "organizations_represented"):
            assert unbacked not in result

    @pytest.mark.asyncio
    async def test_subscribers_count_organizations_from_organization_ids(self):
        rows = [
            {"id": "b1", "resourceType": "subscriber", "organizationIds": ["o1"]},
            {"id": "b2", "resourceType": "subscriber", "organizationIds": ["o1", "o2"]},
        ]
        client = FakePlatformClient(_page("subscriberResourceList", rows, 2))
        result = await CustomerAnalytics(client).analyze_customers(
            {"resource_type": "subscribers"}
        )

        assert result["organizations_represented"] == 2
        assert result["sample"]["covers_all_records"] is True
        for unbacked in ("active_subscribers", "trial_subscribers", "conversion_rate"):
            assert unbacked not in result

    @pytest.mark.asyncio
    async def test_teams_with_a_parent_are_hierarchical(self):
        rows = [
            {"id": "t1", "resourceType": "team", "parent": _ref("t0", "team")},
            {"id": "t2", "resourceType": "team", "parent": None},
        ]
        client = FakePlatformClient(_page("teamResourceList", rows, 2))
        result = await CustomerAnalytics(client).analyze_customers({"resource_type": "teams"})

        assert result["hierarchical_teams"] == 1
        assert "active_teams" not in result

    @pytest.mark.asyncio
    async def test_a_page_without_a_total_reports_coverage_as_unknown(self):
        client = FakePlatformClient({"_embedded": {"organizationResourceList": ORGANIZATION_ROWS}})
        result = await CustomerAnalytics(client).analyze_customers(
            {"resource_type": "organizations"}
        )

        assert result["total_organizations"] is None
        assert result["sample"]["records_covered"] == 4
        assert result["sample"]["total_records"] is None
        assert result["sample"]["covers_all_records"] is None
        assert "reported no total" in result["sample"]["note"]
