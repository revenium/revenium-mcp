"""get_agent_costs answers the page it was asked for instead of every agent (BACK-5440).

On tpdtest1 in production, size=10 printed all 146 agents both over SEVEN_DAYS and
over a start_date/end_date range. Neither agent route pages by agent, so the
ranking over every agent is paged before it is printed.
"""

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.analytics.paging import page_of_rows
from src.revenium_mcp_server.analytics.validation import AnalyticsValidator, ValidationError
from src.revenium_mcp_server.tool_configuration.schema_slimming import apply_thin_tool_defaults
from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    BusinessAnalyticsManagement,
)

AGENT_COUNT = 146
SEVEN_DAYS = {"period": "SEVEN_DAYS"}
DATE_RANGE = {"start_date": "2026-11-01", "end_date": "2026-11-03"}


def _agent_groups():
    return [
        {"groupName": f"agent-{rank:03d}", "metrics": [{"metricResult": float(AGENT_COUNT - rank + 1)}]}
        for rank in range(1, AGENT_COUNT + 1)
    ]


def _legacy_response():
    return [{"startTimestamp": "2026-11-01T00:00:00.000Z", "groups": _agent_groups()}]


def _analytics_envelope():
    return {
        "_embedded": {"items": _legacy_response()},
        "page": {"number": 0, "size": 100, "totalPages": 1, "totalElements": 1},
    }


@pytest.fixture
def analytics_tool(monkeypatch):
    monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)
    with patch(
        "src.revenium_mcp_server.tools_decomposed.business_analytics_management.CHART_RENDERING_AVAILABLE",
        False,
    ):
        return BusinessAnalyticsManagement()


async def _run(analytics_tool, window, **arguments):
    response = _analytics_envelope() if "start_date" in window else _legacy_response()
    client = MagicMock()
    client.team_id = "team-1"
    client.get = AsyncMock(return_value=response)
    analytics_tool.get_client = AsyncMock(return_value=client)
    result = await analytics_tool.handle_action("get_agent_costs", {**window, **arguments})
    return client, result[0].text


def _ranked_names(text):
    return re.findall(r"^\*\*(\d+)\. (agent-\d+)\*\*$", text, flags=re.MULTILINE)


WINDOWS = [pytest.param(SEVEN_DAYS, id="period"), pytest.param(DATE_RANGE, id="date-range")]


class TestPageOfTheRanking:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("window", WINDOWS)
    async def test_size_ten_prints_the_ten_costliest_agents_and_the_next_page_call(
        self, analytics_tool, window
    ):
        _, text = await _run(analytics_tool, window, page=0, size=10)

        assert _ranked_names(text) == [(str(rank), f"agent-{rank:03d}") for rank in range(1, 11)]
        assert "Page 1 of 15, 146 agents in all." in text
        assert "Pass page=1 size=10 for the next page." in text
        assert "**Agents on this page**: 10 of 146" in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("window", WINDOWS)
    async def test_the_totals_say_which_cover_the_page_and_which_the_team(
        self, analytics_tool, window
    ):
        _, text = await _run(analytics_tool, window, page=0, size=10)

        page_cost = sum(AGENT_COUNT - rank + 1 for rank in range(1, 11))
        team_cost = sum(range(1, AGENT_COUNT + 1))
        assert f"**Total Cost (this page only)**: ${page_cost:,.2f}" in text
        assert f"**Total Cost (all 146 agents)**: ${team_cost:,.2f}" in text
        assert "Share of all agents" in text

    @pytest.mark.asyncio
    async def test_a_later_page_numbers_its_agents_from_its_offset(self, analytics_tool):
        _, text = await _run(analytics_tool, SEVEN_DAYS, page=14, size=10)

        assert _ranked_names(text) == [
            (str(rank), f"agent-{rank:03d}") for rank in range(141, AGENT_COUNT + 1)
        ]
        assert "Page 15 of 15, 146 agents in all." in text
        assert "for the next page" not in text

    @pytest.mark.asyncio
    async def test_a_page_past_the_last_points_back(self, analytics_tool):
        _, text = await _run(analytics_tool, SEVEN_DAYS, page=15, size=10)

        assert _ranked_names(text) == []
        assert "146 agents on 15 pages" in text
        assert "Pass page=14 size=10 for the last page" in text

    @pytest.mark.asyncio
    async def test_the_default_page_of_one_hundred_leaves_a_second_page(self, analytics_tool):
        _, text = await _run(analytics_tool, SEVEN_DAYS)

        assert len(_ranked_names(text)) == 100
        assert "Page 1 of 2, 146 agents in all." in text
        assert "Pass page=1 size=100 for the next page." in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "window, path",
        [
            pytest.param(SEVEN_DAYS, "/profitstream/v2/api/sources/metrics/ai/cost-metrics-by-agents-over-time", id="period"),
            pytest.param(DATE_RANGE, "/api/v2/analytics/cost-by-agent", id="date-range"),
        ],
    )
    async def test_the_caller_page_is_not_sent_to_either_route(self, analytics_tool, window, path):
        client, _ = await _run(analytics_tool, window, page=2, size=10)

        client.get.assert_awaited_once()
        assert client.get.call_args.args[0] == path
        sent = client.get.call_args.kwargs["params"]
        assert sent.get("page", 0) == 0
        assert sent.get("size") != 10


class TestValidation:
    def test_size_above_the_platform_maximum_is_refused(self):
        with pytest.raises(ValidationError) as error:
            AnalyticsValidator().validate_agent_costs_params({**SEVEN_DAYS, "size": 101})
        assert error.value.field == "size"

    def test_negative_page_is_refused(self):
        with pytest.raises(ValidationError) as error:
            AnalyticsValidator().validate_agent_costs_params({**SEVEN_DAYS, "page": -1})
        assert error.value.field == "page"

    def test_without_page_or_size_it_reads_the_first_page_of_one_hundred(self):
        validated = AnalyticsValidator().validate_agent_costs_params(dict(SEVEN_DAYS))
        assert (validated["page"], validated["size"]) == (0, 100)


class TestThinDefaults:
    def test_get_agent_costs_defaults_to_the_get_user_costs_page_size(self):
        agent = apply_thin_tool_defaults("get_business_analytics", {"action": "get_agent_costs"})
        user = apply_thin_tool_defaults("get_business_analytics", {"action": "get_user_costs"})
        assert agent["size"] == user["size"] == 100
        assert agent["page"] == 0


class TestPageOfRows:
    def test_an_empty_report_has_no_pages(self):
        rows, paging = page_of_rows([], 0, 10)
        assert rows == []
        assert (paging.total_pages, paging.total_elements) == (0, 0)

    def test_a_partial_last_page_counts_as_a_page(self):
        rows, paging = page_of_rows(list(range(21)), 2, 10)
        assert rows == [20]
        assert (paging.number, paging.total_pages, paging.next_number) == (2, 3, None)


class TestPartialRead:
    def _format(self, ranking_complete):
        from src.revenium_mcp_server.analytics.formatters import AgentCostsFormatter

        agents = [{"agent": f"agent-{n}", "cost": 1.0, "percentage": 10.0} for n in range(10)]
        _, paging = page_of_rows(list(range(AGENT_COUNT)), 0, 10)
        return AgentCostsFormatter().format(
            agents,
            {
                "period": "THIRTY_DAYS",
                "aggregation": "TOTAL",
                "paging": paging,
                "all_agents_cost": 146.0,
                "ranking_complete": ranking_complete,
            },
        )

    def test_a_cut_short_read_does_not_claim_the_whole_team(self):
        text = self._format(ranking_complete=False)

        assert "**Total Cost (the 146 agents read)**: $146.00" in text
        assert "Share of the agents read" in text
        assert "every agent on the team" not in text
        assert "all 146 agents" not in text

    def test_a_complete_read_covers_every_agent(self):
        text = self._format(ranking_complete=True)

        assert "**Total Cost (all 146 agents)**: $146.00" in text
        assert "every agent on the team" in text

    @pytest.mark.asyncio
    async def test_the_engine_marks_a_cut_short_read_as_partial(self):
        from src.revenium_mcp_server.analytics.envelope_reads import UnreadPages
        from src.revenium_mcp_server.analytics.simple_analytics_engine import SimpleAnalyticsEngine
        from src.revenium_mcp_server.analytics.simple_cost_analyzer import RankedCosts

        client = MagicMock()
        client.team_id = "team-1"
        engine = SimpleAnalyticsEngine(client)
        rows = [{"agent": f"agent-{n:03d}", "cost": 1.0, "percentage": 1.0} for n in range(AGENT_COUNT)]
        unread = UnreadPages("cost_metrics_by_agents_over_time", 10, 12, None)
        with patch.object(
            engine.analyzer, "get_agent_costs", AsyncMock(return_value=RankedCosts(rows, unread))
        ):
            text = await engine.get_agent_costs(**DATE_RANGE, page=0, size=10)

        assert "Share of the agents read" in text
        assert "_Incomplete:" in text
