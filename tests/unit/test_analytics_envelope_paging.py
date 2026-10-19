"""Paged analytics envelopes are read to their last page (FRONT-3434).

The timeseries and aggregated endpoints page their rows, 20 by default. A
30-day daily series has 31 buckets, so a read that stopped at the first page
ended on day 20 (verified on dev on 2026-10-09: cost_by_team_timeseries
answered totalPages 2 at the default size and all 31 buckets with size=100).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.analytics.department_costs import DepartmentCostsQuery
from src.revenium_mcp_server.analytics.envelope_reads import (
    ENVELOPE_MAX_PAGES,
    ENVELOPE_PAGE_SIZE,
)
from src.revenium_mcp_server.analytics.simple_cost_analyzer import SimpleCostAnalyzer
from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    BusinessAnalyticsManagement,
)


def _bucket(day):
    return {
        "startTimestamp": f"2026-09-{day:02d}T00:00:00.000Z",
        "endTimestamp": f"2026-09-{day:02d}T23:59:59.999Z",
        "groups": [
            {
                "groupName": "Engineering",
                "metrics": [{"label": "Engineering", "metricResult": float(day)}],
            }
        ],
    }


def _page(days, number, total_pages, total_elements):
    return {
        "resourceType": "metric_timeseries",
        "_embedded": {"items": [_bucket(day) for day in days]},
        "page": {
            "number": number,
            "size": ENVELOPE_PAGE_SIZE,
            "totalPages": total_pages,
            "totalElements": total_elements,
        },
    }


class FakePagedClient:
    """Answers each request with the page its ``page`` parameter names."""

    def __init__(self, pages):
        self.team_id = "team-1"
        self.pages = pages
        self.calls = []

    async def get(self, path, params=None, **kwargs):
        self.calls.append(dict(params or {}))
        return self.pages[(params or {}).get("page", 0)]


class TestEveryPageIsRead:
    @pytest.mark.asyncio
    async def test_two_pages_become_one_complete_series(self):
        client = FakePagedClient(
            {
                0: _page(range(1, 21), 0, 2, 31),
                1: _page(range(21, 32), 1, 2, 31),
            }
        )
        buckets = (await SimpleCostAnalyzer(client).get_team_costs("THIRTY_DAYS")).rows

        assert len(buckets) == 31
        assert buckets[-1]["startTimestamp"] == "2026-09-31T00:00:00.000Z"
        assert [call.get("page") for call in client.calls] == [None, 1]
        assert all(call["size"] == ENVELOPE_PAGE_SIZE for call in client.calls)

    @pytest.mark.asyncio
    async def test_a_single_page_is_read_once(self):
        client = FakePagedClient({0: _page(range(1, 10), 0, 1, 9)})
        analyzer = SimpleCostAnalyzer(client)

        result = await analyzer.get_team_costs("SEVEN_DAYS")

        assert len(client.calls) == 1
        assert result.unread is None
        assert len(result.rows) == 9

    @pytest.mark.asyncio
    async def test_the_walk_stops_at_the_page_cap_and_records_it(self):
        total_pages = ENVELOPE_MAX_PAGES + 5
        client = FakePagedClient(
            {number: _page([1], number, total_pages, total_pages) for number in range(total_pages)}
        )
        analyzer = SimpleCostAnalyzer(client)

        result = await analyzer.get_team_costs("THIRTY_DAYS")

        assert len(client.calls) == ENVELOPE_MAX_PAGES
        assert len(result.rows) == ENVELOPE_MAX_PAGES
        assert result.unread is not None
        assert (result.unread.pages_read, result.unread.total_pages) == (
            ENVELOPE_MAX_PAGES,
            total_pages,
        )

    @pytest.mark.asyncio
    async def test_department_costs_keep_the_page_the_caller_asked_for(self):
        client = FakePagedClient({0: _page(range(1, 21), 0, 2, 31)})
        query = DepartmentCostsQuery(period="THIRTY_DAYS", aggregation="TOTAL")

        await SimpleCostAnalyzer(client).get_department_costs(query)

        assert len(client.calls) == 1
        assert "size" not in client.calls[0]


class TestHandlerSaysWhenTheCapWasHit:
    @pytest.mark.asyncio
    async def test_team_costs_name_the_pages_left_unread(self):
        total_pages = ENVELOPE_MAX_PAGES + 1
        client = FakePagedClient(
            {number: _page([1], number, total_pages, total_pages) for number in range(total_pages)}
        )
        with patch(
            "src.revenium_mcp_server.tools_decomposed.business_analytics_management.CHART_RENDERING_AVAILABLE",
            False,
        ):
            tool = BusinessAnalyticsManagement()
        tool.get_client = AsyncMock(return_value=client)

        result = await tool.handle_action("get_team_costs", {"period": "TWELVE_MONTHS"})
        text = result[0].text

        assert f"the platform holds {total_pages} pages" in text
        assert f"stops after {ENVELOPE_MAX_PAGES} pages of {ENVELOPE_PAGE_SIZE}" in text

    @pytest.mark.asyncio
    async def test_a_complete_read_carries_no_notice(self):
        client = MagicMock()
        client.team_id = "team-1"
        client.get = AsyncMock(return_value=_page(range(1, 4), 0, 1, 3))
        with patch(
            "src.revenium_mcp_server.tools_decomposed.business_analytics_management.CHART_RENDERING_AVAILABLE",
            False,
        ):
            tool = BusinessAnalyticsManagement()
        tool.get_client = AsyncMock(return_value=client)

        result = await tool.handle_action("get_team_costs", {"period": "SEVEN_DAYS"})

        assert "Incomplete" not in result[0].text


class TestEveryBucketIsRendered:
    @pytest.mark.asyncio
    async def test_a_month_of_two_teams_renders_thirty_one_lines_without_truncation(self):
        def two_team_bucket(day):
            groups = [
                {
                    "groupName": team,
                    "metrics": [
                        {"label": team, "metricResult": cost, "metricType": "COST_BY_TEAM_OVER_TIME"}
                    ],
                }
                for team, cost in (("team-a", 12.3), ("team-b", 4.1))
            ]
            return {**_bucket(day), "groups": groups}

        days = range(1, 32)
        envelope = {
            "_embedded": {"items": [two_team_bucket(day) for day in days]},
            "page": {"number": 0, "size": ENVELOPE_PAGE_SIZE, "totalPages": 1, "totalElements": 31},
        }
        client = MagicMock()
        client.team_id = "team-1"
        client.get = AsyncMock(return_value=envelope)
        with patch(
            "src.revenium_mcp_server.tools_decomposed.business_analytics_management.CHART_RENDERING_AVAILABLE",
            False,
        ):
            tool = BusinessAnalyticsManagement()
        tool.get_client = AsyncMock(return_value=client)

        result = await tool.handle_action("get_team_costs", {"period": "THIRTY_DAYS"})
        text = result[0].text
        bucket_lines = [line for line in text.split("\n") if line.startswith("- **2026-09-")]

        assert len(bucket_lines) == 31
        assert bucket_lines[0] == "- **2026-09-01**: team-a $12.30, team-b $4.10"
        assert "truncated" not in text
        assert "not shown" not in text
