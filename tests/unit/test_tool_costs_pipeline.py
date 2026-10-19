"""Unit tests for tool cost analytics pipeline — validation, processor, analyzer, engine, handler."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.analytics.envelope_reads import ENVELOPE_MAX_PAGES
from src.revenium_mcp_server.common.error_handling import ToolError

from src.revenium_mcp_server.analytics.validation import AnalyticsValidator, ValidationError
from src.revenium_mcp_server.analytics.simple_cost_analyzer import SimpleCostAnalyzer, ToolRows
from src.revenium_mcp_server.analytics.tool_reports import ToolReportRead
from src.revenium_mcp_server.tool_analytics_reports import ToolReportWindow
from src.revenium_mcp_server.analytics.simple_analytics_engine import SimpleAnalyticsEngine
from src.revenium_mcp_server.tools_decomposed.business_analytics_management import BusinessAnalyticsManagement


class TestToolCostsValidation:
    """Tests for validate_tool_costs_params."""

    @pytest.fixture
    def validator(self):
        return AnalyticsValidator()

    def test_valid_params(self, validator):
        result = validator.validate_tool_costs_params({"period": "HOUR"})
        assert result["period"] == "HOUR"
        assert result["aggregation"] == "TOTAL"

    def test_valid_params_with_aggregation(self, validator):
        result = validator.validate_tool_costs_params(
            {"period": "SEVEN_DAYS", "aggregation": "MEAN"}
        )
        assert result["period"] == "SEVEN_DAYS"
        assert result["aggregation"] == "MEAN"

    def test_invalid_period_raises(self, validator):
        with pytest.raises(ValidationError):
            validator.validate_tool_costs_params({"period": "INVALID"})

    def test_missing_period_raises(self, validator):
        with pytest.raises(ValidationError):
            validator.validate_tool_costs_params({})


def _envelope(items):
    return {"_embedded": {"items": items}, "page": {"number": 0, "totalPages": 1}}


class TestSimpleCostAnalyzerToolCosts:
    """Tests for SimpleCostAnalyzer tool cost methods."""

    @pytest.fixture
    def analyzer(self):
        mock_client = MagicMock()
        mock_client.team_id = "test-team-123"
        analyzer = SimpleCostAnalyzer(mock_client)
        return analyzer

    @pytest.mark.asyncio
    async def test_get_tool_costs_maps_grouped_envelope(self, analyzer):
        # Real wire shape: the REST transform serves groups of
        # {groupName: toolId, metrics: [{metricResult: Number(totalCost)}]}
        # (isotope api-core get-cost-by-tool-aggregated.ts, toAggregatedFormat).
        # The old parser read fabricated toolId/totalCost fields off these
        # items and rendered every row as "Unknown Tool" with cost 0.
        analyzer.client.get_cost_by_tool_aggregated = AsyncMock(
            return_value=_envelope([
                {"groupName": "Visa - Travel", "metrics": [
                    {"metricResult": 41599.25, "metricType": "COST_METRIC_BY_TOOL", "links": []}
                ]},
                {"groupName": "algolia.search", "metrics": [
                    {"metricResult": 0.0144, "metricType": "COST_METRIC_BY_TOOL", "links": []}
                ]},
            ])
        )
        result = await analyzer.get_tool_costs("HOUR", "TOTAL")
        assert len(result) == 2
        assert result[0]["tool"] == "Visa - Travel"
        assert result[0]["cost"] == 41599.25
        assert result[0]["percentage"] == pytest.approx(99.99, abs=0.01)
        assert result[1]["tool"] == "algolia.search"
        assert all("Unknown" not in r["tool"] for r in result)
        analyzer.client.get_cost_by_tool_aggregated.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_tool_costs_handles_groups_wrapper(self, analyzer):
        # The aggregated format may arrive wrapped: {startTimestamp, endTimestamp,
        # groups: [...]} — same handling the sibling actions get.
        analyzer.client.get_cost_by_tool_aggregated = AsyncMock(
            return_value=_envelope([
                {
                    "startTimestamp": "2026-07-01T00:00:00Z",
                    "endTimestamp": "2026-07-14T00:00:00Z",
                    "groups": [
                        {"groupName": "Visa - Travel", "metrics": [{"metricResult": 10.0}]},
                    ],
                }
            ])
        )
        result = await analyzer.get_tool_costs("SEVEN_DAYS", "TOTAL")
        assert list(result) == [{"tool": "Visa - Travel", "cost": 10.0, "percentage": 100.0}]

    @pytest.mark.asyncio
    async def test_zero_and_negative_costs_are_retained(self, analyzer):
        # Parity with the get_model_costs control (renders $0.00 rows) and
        # honesty for refunds/credits: unlike the sibling actions, tool costs
        # must not silently drop non-positive groups.
        analyzer.client.get_cost_by_tool_aggregated = AsyncMock(
            return_value=_envelope([
                {"groupName": "paid.tool", "metrics": [{"metricResult": 10.0}]},
                {"groupName": "free.tool", "metrics": [{"metricResult": 0}]},
                {"groupName": "refunded.tool", "metrics": [{"metricResult": -2.5}]},
            ])
        )
        result = await analyzer.get_tool_costs("SEVEN_DAYS", "TOTAL")
        by_name = {r["tool"]: r for r in result}
        assert set(by_name) == {"paid.tool", "free.tool", "refunded.tool"}
        assert by_name["free.tool"]["cost"] == 0
        assert by_name["refunded.tool"]["cost"] == -2.5
        assert result[0]["tool"] == "paid.tool"  # still sorted by cost desc

    def test_fabricated_field_parser_is_gone(self, analyzer):
        # The toolId/totalCost parser matched a shape the endpoint never
        # serves; keep it dead.
        assert not hasattr(analyzer, "_process_tool_cost_items")

    @pytest.mark.asyncio
    async def test_get_tool_costs_empty_response(self, analyzer):
        analyzer.client.get_cost_by_tool_aggregated = AsyncMock(return_value=_envelope([]))
        result = await analyzer.get_tool_costs("HOUR", "TOTAL")
        assert list(result) == []

    @pytest.mark.asyncio
    async def test_get_top_tools_success(self, analyzer):
        analyzer.client.get_top_tools_by_call_count = AsyncMock(
            return_value=_envelope([
                {"groupName": "manage_products", "metrics": [{"metricResult": 28}]},
                {"groupName": "manage_tools", "metrics": [{"metricResult": 15}]},
            ])
        )
        result = await analyzer.get_top_tools("HOUR", "TOTAL")
        assert len(result) == 2
        assert result[0]["tool"] == "manage_products"
        assert result[0]["call_count"] == 28

    @pytest.mark.asyncio
    async def test_get_tool_costs_by_agent_success(self, analyzer):
        analyzer.client.get_cost_by_tool_agent = AsyncMock(
            return_value=_envelope([
                {"groupName": "claude-code", "metrics": [{"metricResult": 0.35}]},
            ])
        )
        result = await analyzer.get_tool_costs_by_agent("HOUR", "TOTAL")
        assert len(result) == 1
        assert result[0]["agent"] == "claude-code"
        assert result[0]["cost"] == 0.35

    @pytest.mark.asyncio
    async def test_provider_costs_sum_one_provider_across_time_buckets(self, analyzer):
        def bucket(hour, cost):
            return {
                "startTimestamp": f"2026-10-15T{hour:02d}:00:00.000Z",
                "groups": [{"groupName": "isotope", "metrics": [{"metricResult": cost}]}],
            }

        analyzer.client.get_cost_by_tool_provider = AsyncMock(
            return_value=_envelope([bucket(8, 0.2), bucket(16, 0.2), bucket(17, 0.2)])
        )
        result = await analyzer.get_tool_costs_by_provider("TWENTY_FOUR_HOURS", "TOTAL")
        assert len(result) == 1
        assert result[0]["provider"] == "isotope"
        assert result[0]["cost"] == pytest.approx(0.6)


_WINDOW = ToolReportWindow("2026-10-15T23:00:00.000Z", "2026-10-16T00:00:00.000Z", label="HOUR")


def _rows(rows):
    return ToolRows(rows, ToolReportRead({}, _WINDOW))


class TestSimpleAnalyticsEngineToolCosts:
    """Tests for tool cost methods on SimpleAnalyticsEngine."""

    @pytest.fixture
    def engine(self):
        mock_client = MagicMock()
        mock_client.team_id = "test-team-123"
        engine = SimpleAnalyticsEngine(mock_client)
        # The processors share the engine's analyzer, so its methods are replaced in place.
        engine.analyzer.get_tool_costs = AsyncMock(
            return_value=_rows([{"tool": "manage_products", "cost": 0.50}])
        )
        engine.analyzer.get_top_tools = AsyncMock(
            return_value=_rows([{"tool": "manage_products", "call_count": 28}])
        )
        engine.analyzer.get_tool_costs_by_agent = AsyncMock(
            return_value=_rows([{"agent": "claude-code", "cost": 0.35}])
        )
        engine.analyzer.get_tool_costs_by_provider = AsyncMock(
            return_value=_rows([{"provider": "revenium", "cost": 0.50}])
        )
        return engine

    @pytest.mark.asyncio
    async def test_get_tool_costs(self, engine):
        result = await engine.get_tool_costs(period="HOUR")
        assert "Tool Cost Analysis" in result
        assert "HOUR: 2026-10-15T23:00:00.000Z to 2026-10-16T00:00:00.000Z" in result

    @pytest.mark.asyncio
    async def test_get_top_tools(self, engine):
        result = await engine.get_top_tools(period="HOUR")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_get_tool_costs_by_agent(self, engine):
        result = await engine.get_tool_costs_by_agent(period="HOUR")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_get_tool_costs_by_provider(self, engine):
        result = await engine.get_tool_costs_by_provider(period="HOUR")
        assert isinstance(result, str)

    def test_supported_actions_includes_tool_costs(self, engine):
        actions = engine.get_supported_actions()
        assert "get_tool_costs" in actions
        assert "get_top_tools" in actions
        assert "get_tool_costs_by_agent" in actions
        assert "get_tool_costs_by_provider" in actions

    @pytest.mark.asyncio
    async def test_invalid_period_raises_error(self, engine):
        with pytest.raises(ToolError) as exc:
            await engine.get_tool_costs(period="INVALID")
        assert "Error" in exc.value.message or "error" in exc.value.message.lower()


class TestBusinessAnalyticsToolCostActions:
    """Tests for tool cost actions in BusinessAnalyticsManagement."""

    @pytest.fixture
    def tool(self, monkeypatch):
        t = BusinessAnalyticsManagement(ucm_helper=None)
        mock_simple = MagicMock()
        mock_simple.get_cost_summary = AsyncMock(return_value="summary text")
        mock_simple.get_provider_costs = AsyncMock(return_value="provider costs")
        mock_simple.get_model_costs = AsyncMock(return_value="model costs")
        mock_simple.get_customer_costs = AsyncMock(return_value="customer costs")
        mock_simple.get_api_key_costs = AsyncMock(return_value="api key costs")
        mock_simple.get_agent_costs = AsyncMock(return_value="agent costs")
        mock_simple.get_tool_costs = AsyncMock(return_value="tool costs")
        mock_simple.get_top_tools = AsyncMock(return_value="top tools")
        mock_simple.get_tool_costs_by_agent = AsyncMock(return_value="tool costs by agent")
        mock_simple.get_tool_costs_by_provider = AsyncMock(return_value="tool costs by provider")
        t.simple_analytics_engine = mock_simple

        # Handlers now construct SimpleAnalyticsEngine per-request via
        # `engine = SimpleAnalyticsEngine(client)`. Patch the constructor at the
        # module path the handler imports from so every construction returns the
        # same mock as `t.simple_analytics_engine`, keeping existing assertions valid.
        monkeypatch.setattr(
            "src.revenium_mcp_server.tools_decomposed.business_analytics_management.SimpleAnalyticsEngine",
            lambda *_a, **_kw: mock_simple,
        )

        mock_spike = MagicMock()
        mock_spike.analyze_temporal_anomalies = AsyncMock(return_value={"anomalies": []})
        t.enhanced_spike_analyzer = mock_spike
        # Pre-seed the cached client so `await self.get_client(ctx=None)` returns it
        # without trying to instantiate a real ReveniumClient (which requires env vars).
        t.client = MagicMock()
        return t

    @pytest.mark.asyncio
    async def test_get_tool_costs_action(self, tool):
        result = await tool.handle_action("get_tool_costs", {"period": "SEVEN_DAYS"})
        assert result[0].text == "tool costs"

    @pytest.mark.asyncio
    async def test_get_top_tools_action(self, tool):
        result = await tool.handle_action("get_top_tools", {"period": "SEVEN_DAYS"})
        assert result[0].text == "top tools"

    @pytest.mark.asyncio
    async def test_get_tool_costs_by_agent_action(self, tool):
        result = await tool.handle_action("get_tool_costs_by_agent", {"period": "SEVEN_DAYS"})
        assert result[0].text == "tool costs by agent"

    @pytest.mark.asyncio
    async def test_get_tool_costs_by_provider_action(self, tool):
        result = await tool.handle_action("get_tool_costs_by_provider", {"period": "SEVEN_DAYS"})
        assert result[0].text == "tool costs by provider"

    @pytest.mark.asyncio
    async def test_get_tool_costs_validation_error(self, tool):
        tool.simple_analytics_engine.get_tool_costs = AsyncMock(
            side_effect=ValidationError("Invalid period", field="period")
        )
        with pytest.raises(ToolError) as exc:
            await tool.handle_action("get_tool_costs", {"period": "INVALID"})
        assert "Validation Error" in exc.value.message

    @pytest.mark.asyncio
    async def test_get_tool_costs_generic_error(self, tool):
        tool.simple_analytics_engine.get_tool_costs = AsyncMock(
            side_effect=Exception("API down")
        )
        with pytest.raises(ToolError) as exc:
            await tool.handle_action("get_tool_costs", {"period": "HOUR"})
        assert "Failed" in exc.value.message

    @pytest.mark.asyncio
    async def test_supported_actions_includes_tool_costs(self, tool):
        actions = await tool._get_supported_actions()
        assert "get_tool_costs" in actions
        assert "get_top_tools" in actions
        assert "get_tool_costs_by_agent" in actions
        assert "get_tool_costs_by_provider" in actions


class FakeToolReportClient:
    """Answers every tool report read with the page its ``page`` argument names, and records the reads."""

    def __init__(self, pages):
        self.team_id = "team-1"
        self.pages = pages
        self.reads = []

    def __getattr__(self, method):
        async def read(**params):
            self.reads.append((method, params))
            return self.pages[params.get("page", 0)]

        return read


def _business_analytics(client):
    with patch(
        "src.revenium_mcp_server.tools_decomposed.business_analytics_management.CHART_RENDERING_AVAILABLE",
        False,
    ):
        tool = BusinessAnalyticsManagement()
    tool.get_client = AsyncMock(return_value=client)
    return tool


def _instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


TOOL_COST_ACTIONS = {
    "get_tool_costs": "get_cost_by_tool_aggregated",
    "get_top_tools": "get_top_tools_by_call_count",
    "get_tool_costs_by_agent": "get_cost_by_tool_agent",
    "get_tool_costs_by_provider": "get_cost_by_tool_provider",
}


class TestToolCostReadsAskForTheWindow:
    """BACK-4624: the four tool cost actions send startDate/endDate, never a period name."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", sorted(TOOL_COST_ACTIONS))
    async def test_the_request_carries_the_dates_and_no_period(self, action):
        client = FakeToolReportClient({0: _envelope([])})

        await _business_analytics(client).handle_action(action, {"period": "SEVEN_DAYS"})

        [(method, params)] = client.reads
        assert method == TOOL_COST_ACTIONS[action]
        assert "period" not in params
        assert _instant(params["endDate"]) - _instant(params["startDate"]) == timedelta(days=7)

    @pytest.mark.asyncio
    async def test_seven_days_and_twenty_four_hours_ask_for_different_windows(self):
        client = FakeToolReportClient({0: _envelope([])})
        tool = _business_analytics(client)

        await tool.handle_action("get_tool_costs", {"period": "SEVEN_DAYS"})
        await tool.handle_action("get_tool_costs", {"period": "TWENTY_FOUR_HOURS"})

        week, day = (params for _, params in client.reads)
        gap = _instant(day["startDate"]) - _instant(week["startDate"])
        assert abs(gap - timedelta(days=6)) < timedelta(minutes=1)

    @pytest.mark.asyncio
    async def test_the_answer_names_the_window_the_platform_was_asked_for(self):
        rows = [{"groupName": "engineering-time", "metrics": [{"metricResult": 87.5}]}]
        client = FakeToolReportClient({0: _envelope(rows)})

        result = await _business_analytics(client).handle_action(
            "get_tool_costs", {"period": "SEVEN_DAYS"}
        )

        [(_, params)] = client.reads
        assert f"SEVEN_DAYS: {params['startDate']} to {params['endDate']}" in result[0].text
        assert "engineering-time" in result[0].text


class TestToolCostReadsReadEveryPage:
    """BACK-4640: the tool cost reads follow the report to its last page."""

    @staticmethod
    def _pages(total_pages):
        return {
            number: {
                "_embedded": {
                    "items": [
                        {
                            "startTimestamp": f"2026-10-15T{number:02d}:00:00.000Z",
                            "groups": [{"groupName": "isotope", "metrics": [{"metricResult": 0.2}]}],
                        }
                    ]
                },
                "page": {"number": number, "size": 100, "totalPages": total_pages},
            }
            for number in range(total_pages)
        }

    @pytest.mark.asyncio
    async def test_three_pages_of_buckets_add_up_to_the_whole_day(self):
        client = FakeToolReportClient(self._pages(3))

        result = await _business_analytics(client).handle_action(
            "get_tool_costs_by_provider", {"period": "TWENTY_FOUR_HOURS"}
        )

        assert [params.get("page") for _, params in client.reads] == [None, 1, 2]
        assert "$0.60" in result[0].text
        assert "Incomplete" not in result[0].text

    @pytest.mark.asyncio
    async def test_a_read_stopped_at_the_page_cap_says_so(self):
        total_pages = ENVELOPE_MAX_PAGES + 2
        client = FakeToolReportClient(self._pages(total_pages))

        result = await _business_analytics(client).handle_action(
            "get_tool_costs_by_provider", {"period": "TWELVE_MONTHS"}
        )

        assert len(client.reads) == ENVELOPE_MAX_PAGES
        assert f"the platform holds {total_pages} pages" in result[0].text
