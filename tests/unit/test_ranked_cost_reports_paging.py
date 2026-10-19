"""The ranked cost reports add up every page of time buckets (FRONT-3512).

A calendar range reaches the analytics API, which pages its daily buckets 20 at
a time. Reading only the first page made get_provider_costs for September 1-30
answer the September 1-20 total on the hosted MCP (tenant l3382l, 2026-10-15).
"""

from datetime import date
from unittest.mock import AsyncMock

import pytest

from src.revenium_mcp_server.analytics.envelope_reads import (
    ENVELOPE_MAX_PAGES,
    ENVELOPE_PAGE_SIZE,
)
from src.revenium_mcp_server.analytics.simple_cost_analyzer import SimpleCostAnalyzer
from src.revenium_mcp_server.analytics_window import CalendarRange
from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    BusinessAnalyticsManagement,
)

SEPTEMBER = CalendarRange(date(2026, 9, 1), date(2026, 9, 30))
TIMESERIES_REPORTS = [
    "get_provider_costs",
    "get_customer_costs",
    "get_api_key_costs",
    "get_agent_costs",
]
RANKED_REPORTS = [*TIMESERIES_REPORTS, "get_model_costs"]


def _bucket(day):
    return {
        "startTimestamp": f"2026-09-{day:02d}T00:00:00.000Z",
        "groups": [{"groupName": "ClaudeCode", "metrics": [{"metricResult": float(day)}]}],
    }


def _model_group(name, cost):
    return {"groupName": name, "metrics": [{"metricResult": cost}]}


def _envelope(items, number, total_pages):
    return {
        "_embedded": {"items": items},
        "page": {
            "number": number,
            "size": ENVELOPE_PAGE_SIZE,
            "totalPages": total_pages,
            "totalElements": len(items) * total_pages,
        },
    }


def _page(days, number, total_pages):
    return _envelope([_bucket(day) for day in days], number, total_pages)


class FakePagedClient:
    """Answers each request with the page its ``page`` parameter names."""

    def __init__(self, pages):
        self.team_id = "team-1"
        self.pages = pages
        self.calls = []
        self.paths = []

    async def get(self, path, params=None, **kwargs):
        self.paths.append(path)
        self.calls.append(dict(params or {}))
        return self.pages[(params or {}).get("page", 0)]


def _total(rows):
    return sum(row["cost"] for row in rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("report", TIMESERIES_REPORTS)
async def test_two_pages_of_daily_buckets_add_up_to_the_whole_month(report):
    client = FakePagedClient({0: _page(range(1, 21), 0, 2), 1: _page(range(21, 31), 1, 2)})

    rows = await getattr(SimpleCostAnalyzer(client), report)(SEPTEMBER, "TOTAL")

    assert _total(rows) == sum(range(1, 31))
    assert rows.unread is None
    assert [call.get("page") for call in client.calls] == [None, 1]
    assert all(call["size"] == ENVELOPE_PAGE_SIZE for call in client.calls)


@pytest.mark.asyncio
async def test_model_groups_on_two_pages_are_all_ranked_with_shares_of_the_whole():
    client = FakePagedClient(
        {
            0: _envelope([_model_group("claude-sonnet", 500.0), _model_group("gpt-4o", 300.0)], 0, 2),
            1: _envelope([_model_group("gemini-pro", 150.0), _model_group("claude-haiku", 50.0)], 1, 2),
        }
    )

    rows = await SimpleCostAnalyzer(client).get_model_costs(SEPTEMBER, "TOTAL")

    assert [(row["model"], row["cost"], row["percentage"]) for row in rows] == [
        ("claude-sonnet", 500.0, 50.0),
        ("gpt-4o", 300.0, 30.0),
        ("gemini-pro", 150.0, 15.0),
        ("claude-haiku", 50.0, 5.0),
    ]
    assert rows.unread is None
    assert [call.get("page") for call in client.calls] == [None, 1]
    assert all(call["size"] == ENVELOPE_PAGE_SIZE for call in client.calls)


@pytest.mark.asyncio
async def test_the_model_report_reads_the_aggregated_endpoint():
    client = FakePagedClient({0: _envelope([_model_group("gpt-4o", 1.0)], 0, 1)})

    await SimpleCostAnalyzer(client).get_model_costs(SEPTEMBER, "TOTAL")

    assert client.paths == ["/api/v2/analytics/cost-by-model-aggregated"]


@pytest.mark.asyncio
@pytest.mark.parametrize("report", TIMESERIES_REPORTS)
async def test_a_single_page_is_read_once(report):
    client = FakePagedClient({0: _page(range(1, 31), 0, 1)})

    rows = await getattr(SimpleCostAnalyzer(client), report)(SEPTEMBER, "TOTAL")

    assert _total(rows) == sum(range(1, 31))
    assert len(client.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("report", RANKED_REPORTS)
async def test_the_legacy_list_is_read_unpaged(report, monkeypatch):
    monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)
    client = FakePagedClient({0: [_bucket(day) for day in range(1, 31)]})

    rows = await getattr(SimpleCostAnalyzer(client), report)("THIRTY_DAYS", "TOTAL")

    assert _total(rows) == sum(range(1, 31))
    assert len(client.calls) == 1
    assert client.calls[0]["group"] == "TOTAL"
    assert "size" not in client.calls[0]
    assert "page" not in client.calls[0]


@pytest.mark.asyncio
async def test_a_read_stopped_at_the_page_cap_says_so():
    total_pages = ENVELOPE_MAX_PAGES + 1
    client = FakePagedClient({number: _page([1], number, total_pages) for number in range(total_pages)})
    tool = BusinessAnalyticsManagement()
    tool.get_client = AsyncMock(return_value=client)

    result = await tool.handle_action(
        "get_provider_costs", {"start_date": "2026-09-01", "end_date": "2026-09-30"}
    )
    text = result[0].text

    assert len(client.calls) == ENVELOPE_MAX_PAGES
    assert f"the platform holds {total_pages} pages" in text
    assert f"stops after {ENVELOPE_MAX_PAGES} pages of {ENVELOPE_PAGE_SIZE}" in text


@pytest.mark.asyncio
async def test_a_complete_read_carries_no_notice():
    client = FakePagedClient({0: _page(range(1, 21), 0, 2), 1: _page(range(21, 31), 1, 2)})
    tool = BusinessAnalyticsManagement()
    tool.get_client = AsyncMock(return_value=client)

    result = await tool.handle_action(
        "get_provider_costs", {"start_date": "2026-09-01", "end_date": "2026-09-30"}
    )

    assert "Incomplete" not in result[0].text
    assert "$465.00" in result[0].text
