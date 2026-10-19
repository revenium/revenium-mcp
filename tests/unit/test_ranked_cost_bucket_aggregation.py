"""BACK-4639: the ranked cost reports combine half-day buckets by the aggregation asked for.

The legacy over-time reports answer one value per entity per bucket, already
combined inside the bucket by ``group``. Summing them is right for TOTAL only.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.revenium_mcp_server.analytics.bucket_aggregation import combine_bucket_values
from src.revenium_mcp_server.analytics.simple_cost_analyzer import SimpleCostAnalyzer


def _bucket(start: str, values: dict) -> dict:
    return {
        "startTimestamp": start,
        "groups": [
            {"groupName": name, "metrics": [{"metricResult": value}]}
            for name, value in values.items()
        ],
    }


# Three half-day buckets: ClaudeCode is steady, anthropic has one large bucket.
# Sums rank ClaudeCode first; the largest single bucket belongs to anthropic.
LEGACY_BUCKETS = [
    _bucket("2026-10-09T02:42:00Z", {"ClaudeCode": 18.0, "anthropic": 2.0}),
    _bucket("2026-10-09T14:42:00Z", {"ClaudeCode": 16.0, "anthropic": 29.0}),
    _bucket("2026-10-10T02:42:00Z", {"ClaudeCode": 14.0}),
]


def _legacy_analyzer(response) -> SimpleCostAnalyzer:
    client = MagicMock()
    client.team_id = "team-1"
    client.get = AsyncMock(return_value=response)
    return SimpleCostAnalyzer(client)


@pytest.fixture(autouse=True)
def _legacy_route(monkeypatch):
    monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)


def _figures(rows, key):
    return {row[key]: row["cost"] for row in rows}


class TestProviderBuckets:
    def setup_method(self):
        self.analyzer = _legacy_analyzer(LEGACY_BUCKETS)

    def test_total_sums_every_bucket(self):
        rows = self.analyzer._process_provider_data(LEGACY_BUCKETS, "TOTAL")
        assert _figures(rows, "provider") == {"ClaudeCode": 48.0, "Anthropic": 31.0}
        assert [row["provider"] for row in rows] == ["ClaudeCode", "Anthropic"]

    def test_maximum_is_the_largest_bucket_and_ranks_by_it(self):
        rows = self.analyzer._process_provider_data(LEGACY_BUCKETS, "MAXIMUM")
        assert _figures(rows, "provider") == {"Anthropic": 29.0, "ClaudeCode": 18.0}
        assert [row["provider"] for row in rows] == ["Anthropic", "ClaudeCode"]

    def test_minimum_is_the_smallest_bucket_with_a_value(self):
        rows = self.analyzer._process_provider_data(LEGACY_BUCKETS, "MINIMUM")
        assert _figures(rows, "provider") == {"ClaudeCode": 14.0, "Anthropic": 2.0}

    def test_mean_is_over_the_buckets_with_a_value(self):
        rows = self.analyzer._process_provider_data(LEGACY_BUCKETS, "MEAN")
        assert _figures(rows, "provider") == pytest.approx({"ClaudeCode": 16.0, "Anthropic": 15.5})

    def test_mean_does_not_grow_with_the_number_of_buckets(self):
        doubled = LEGACY_BUCKETS + LEGACY_BUCKETS
        single = _figures(self.analyzer._process_provider_data(LEGACY_BUCKETS, "MEAN"), "provider")
        twice = _figures(self.analyzer._process_provider_data(doubled, "MEAN"), "provider")
        assert twice == pytest.approx(single)

    @pytest.mark.asyncio
    async def test_get_provider_costs_maximum_over_the_legacy_route(self):
        rows = await self.analyzer.get_provider_costs("SEVEN_DAYS", "MAXIMUM")
        assert rows[0] == pytest.approx({"provider": "Anthropic", "cost": 29.0, "percentage": 29 / 47 * 100})
        _, kwargs = self.analyzer.client.get.call_args
        assert kwargs["params"]["group"] == "MAXIMUM"


class TestAgentBuckets:
    def setup_method(self):
        self.analyzer = _legacy_analyzer(LEGACY_BUCKETS)

    def test_total_sums_every_bucket(self):
        rows = self.analyzer._process_agent_data(LEGACY_BUCKETS, "TOTAL")
        assert _figures(rows, "agent") == {"ClaudeCode": 48.0, "anthropic": 31.0}

    def test_maximum_is_the_largest_bucket(self):
        rows = self.analyzer._process_agent_data(LEGACY_BUCKETS, "MAXIMUM")
        assert [row["agent"] for row in rows] == ["anthropic", "ClaudeCode"]
        assert _figures(rows, "agent") == {"anthropic": 29.0, "ClaudeCode": 18.0}

    def test_mean_is_over_the_buckets_with_a_value(self):
        rows = self.analyzer._process_agent_data(LEGACY_BUCKETS, "MEAN")
        assert _figures(rows, "agent") == pytest.approx({"ClaudeCode": 16.0, "anthropic": 15.5})

    @pytest.mark.asyncio
    async def test_get_agent_costs_maximum_over_the_legacy_route(self):
        rows = await self.analyzer.get_agent_costs("SEVEN_DAYS", "MAXIMUM")
        assert _figures(rows, "agent") == {"anthropic": 29.0, "ClaudeCode": 18.0}


@pytest.mark.asyncio
async def test_cost_summary_top_providers_and_agents_follow_the_aggregation():
    analyzer = _legacy_analyzer(LEGACY_BUCKETS)
    summary = await analyzer.get_cost_summary("SEVEN_DAYS", "MAXIMUM")
    assert summary["top_providers"][0]["provider"] == "Anthropic"
    assert summary["top_providers"][0]["cost"] == 29.0
    assert summary["top_agents"][0]["cost"] == 29.0


def test_a_group_entry_without_a_numeric_metric_is_no_value_not_zero():
    analyzer = _legacy_analyzer([])
    buckets = LEGACY_BUCKETS + [
        {"groups": [{"groupName": "ClaudeCode", "metrics": [{"metricResult": None}]}]}
    ]
    rows = analyzer._process_provider_data(buckets, "MINIMUM")
    assert _figures(rows, "provider")["ClaudeCode"] == 14.0


@pytest.mark.parametrize(
    "aggregation, expected", [("TOTAL", 6.0), ("MEAN", 2.0), ("MAXIMUM", 3.0), ("MINIMUM", 1.0)]
)
def test_combine_bucket_values(aggregation, expected):
    assert combine_bucket_values([1.0, 2.0, 3.0], aggregation) == expected


def test_an_idle_bucket_keeps_the_entity_listed_at_a_minimum_of_zero():
    analyzer = _legacy_analyzer([])
    buckets = [
        _bucket("2026-10-09T02:42:00Z", {"anthropic": 10.0}),
        _bucket("2026-10-09T14:42:00Z", {"anthropic": 0.0}),
    ]
    assert _figures(analyzer._process_provider_data(buckets, "MINIMUM"), "provider") == {
        "Anthropic": 0.0
    }
    assert _figures(analyzer._process_provider_data(buckets, "MEAN"), "provider") == {
        "Anthropic": 5.0
    }


def test_an_agent_with_no_spend_in_any_bucket_is_listed_without_a_share():
    """BACK-4809: an agent the platform lists at $0 stays a row."""
    analyzer = _legacy_analyzer([])
    buckets = [
        _bucket("2026-10-09T02:42:00Z", {"support-bot": 10.0, "idle-bot": 0.0}),
        _bucket("2026-10-09T14:42:00Z", {"support-bot": 0.0, "idle-bot": 0.0}),
    ]
    rows = analyzer._process_agent_data(buckets, "TOTAL")
    assert _figures(rows, "agent") == {"support-bot": 10.0, "idle-bot": 0.0}
    idle = next(row for row in rows if row["agent"] == "idle-bot")
    assert "percentage" not in idle


def test_a_provider_at_zero_in_every_bucket_is_listed_without_a_share():
    """BACK-4690: a provider the platform reports at $0 stays a row."""
    analyzer = _legacy_analyzer([])
    buckets = [
        _bucket("2026-10-09T02:42:00Z", {"anthropic": 10.0, "openai": 0.0}),
        _bucket("2026-10-09T14:42:00Z", {"anthropic": 0.0, "openai": 0.0}),
    ]
    rows = analyzer._process_provider_data(buckets, "TOTAL")
    assert _figures(rows, "provider") == {"Anthropic": 10.0, "OpenAI": 0.0}
    assert [row["provider"] for row in rows] == ["Anthropic", "OpenAI"]
    assert rows[0]["percentage"] == 100.0
    assert "percentage" not in rows[1]


def test_groups_naming_one_entity_in_a_bucket_count_as_one_bucket_value():
    analyzer = _legacy_analyzer([])
    buckets = [
        _bucket("2026-10-09T02:42:00Z", {"openai": 50.0, "OPENAI": 50.0}),
        _bucket("2026-10-09T14:42:00Z", {"OpenAI": 30.0}),
    ]
    assert _figures(analyzer._process_provider_data(buckets, "MAXIMUM"), "provider") == {
        "OpenAI": 100.0
    }
    assert _figures(analyzer._process_provider_data(buckets, "MEAN"), "provider") == {
        "OpenAI": 65.0
    }


def test_unnamed_groups_in_one_bucket_add_up_under_the_default_name():
    analyzer = _legacy_analyzer([])
    buckets = [
        {"groups": [{"metrics": [{"metricResult": 4.0}]}, {"metrics": [{"metricResult": 6.0}]}]},
        {"groups": [{"metrics": [{"metricResult": 2.0}]}]},
    ]
    rows = analyzer._process_agent_data(buckets, "MAXIMUM")
    assert _figures(rows, "agent") == {"Unknown Agent": 10.0}


def test_bare_group_entries_are_each_their_own_bucket():
    analyzer = _legacy_analyzer([])
    entries = [
        {"groupName": "ClaudeCode", "metrics": [{"metricResult": 4.0}]},
        {"groupName": "ClaudeCode", "metrics": [{"metricResult": 6.0}]},
    ]
    assert _figures(analyzer._process_agent_data(entries, "MAXIMUM"), "agent") == {
        "ClaudeCode": 6.0
    }


class TestModelBuckets:
    def setup_method(self):
        self.analyzer = _legacy_analyzer(LEGACY_BUCKETS)

    @pytest.mark.asyncio
    async def test_total_sums_every_bucket(self):
        rows = await self.analyzer.get_model_costs("SEVEN_DAYS", "TOTAL")
        assert _figures(rows, "model") == {"ClaudeCode": 48.0, "anthropic": 31.0}

    @pytest.mark.asyncio
    async def test_maximum_is_the_largest_bucket_and_ranks_by_it(self):
        rows = await self.analyzer.get_model_costs("SEVEN_DAYS", "MAXIMUM")
        assert [row["model"] for row in rows] == ["anthropic", "ClaudeCode"]
        assert _figures(rows, "model") == {"anthropic": 29.0, "ClaudeCode": 18.0}

    @pytest.mark.asyncio
    async def test_mean_is_over_the_buckets_with_a_value(self):
        rows = await self.analyzer.get_model_costs("SEVEN_DAYS", "MEAN")
        assert _figures(rows, "model") == pytest.approx({"ClaudeCode": 16.0, "anthropic": 15.5})


class TestCustomerBuckets:
    def setup_method(self):
        self.analyzer = _legacy_analyzer(LEGACY_BUCKETS)

    @pytest.mark.asyncio
    async def test_total_sums_every_bucket(self):
        rows = await self.analyzer.get_customer_costs("SEVEN_DAYS", "TOTAL")
        assert _figures(rows, "customer") == {"ClaudeCode": 48.0, "anthropic": 31.0}

    @pytest.mark.asyncio
    async def test_maximum_is_the_largest_bucket_and_ranks_by_it(self):
        rows = await self.analyzer.get_customer_costs("SEVEN_DAYS", "MAXIMUM")
        assert [row["customer"] for row in rows] == ["anthropic", "ClaudeCode"]
        assert _figures(rows, "customer") == {"anthropic": 29.0, "ClaudeCode": 18.0}

    @pytest.mark.asyncio
    async def test_mean_is_over_the_buckets_with_a_value(self):
        rows = await self.analyzer.get_customer_costs("SEVEN_DAYS", "MEAN")
        assert _figures(rows, "customer") == pytest.approx(
            {"ClaudeCode": 16.0, "anthropic": 15.5}
        )
