"""Analytics figures print with the unit the platform documents for them."""

import re

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    BusinessAnalyticsManagement,
)
from src.revenium_mcp_server.analytics.metric_units import format_metric_result
from src.revenium_mcp_server.common.money import render_usd
from src.revenium_mcp_server.analytics.simple_cost_analyzer import PackRows

_MOD = "src.revenium_mcp_server.tools_decomposed.business_analytics_management"


@pytest.fixture
def tool():
    t = BusinessAnalyticsManagement(ucm_helper=None)
    t.get_client = AsyncMock(return_value=MagicMock())
    t.client = MagicMock()
    return t


def _row(group, value, metric_type, **extra):
    return {"group": group, "label": group, "metricResult": value, "metricType": metric_type, **extra}


def _mock_method(mock_cls, method_name, rows):
    instance = MagicMock()
    setattr(instance, method_name, AsyncMock(return_value=PackRows(rows)))
    mock_cls.return_value = instance
    return instance


async def _render(tool, action, arguments=None):
    result = await tool.handle_action(action, {"period": "SEVEN_DAYS", **(arguments or {})})
    return result[0].text


@patch(f"{_MOD}.SimpleCostAnalyzer")
class TestPlatformMetricUnits:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "dimension,metric_type",
        [("customer", "PROFIT_MARGIN_BY_CUSTOMER"), ("product", "PROFIT_MARGIN_BY_PRODUCT")],
    )
    async def test_profit_margin_prints_a_percent_sign(self, mock_cls, tool, dimension, metric_type):
        _mock_method(mock_cls, "get_profit_margins", [_row("Engineering", -14768.871861401596, metric_type)])
        text = await _render(tool, "get_profit_margins", {"dimension": dimension})
        assert "-14,768.87%" in text
        assert "-14,768.8719" not in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", [0, -0.0])
    async def test_a_zero_margin_says_the_customer_may_have_no_revenue(self, mock_cls, tool, value):
        _mock_method(mock_cls, "get_profit_margins", [_row("Revenium", value, "PROFIT_MARGIN_BY_CUSTOMER")])
        text = await _render(tool, "get_profit_margins", {"dimension": "customer"})
        assert "0.00% (no revenue, or revenue equal to cost; the platform reports 0 for both)" in text
        assert "-0.00%" not in text

    @pytest.mark.asyncio
    async def test_top_movers_print_the_change_as_a_percent_and_the_costs_as_dollars(self, mock_cls, tool):
        _mock_method(mock_cls, "get_top_movers", [
            _row("claude-opus-5-5", 38.12968922368237, "TOP_MOVERS",
                 currentValue=27308.145975, previousValue=19769.9322488, trend="up"),
            _row("haiku", 98185.76, "TOP_MOVERS", currentValue=5.923, previousValue=0.004, trend="up"),
        ])
        text = await _render(tool, "get_top_movers")
        assert "38.13%" in text
        assert "$19,769.93 → $27,308.15" in text
        assert "$0.004 → $5.92" in text
        assert "38.1297" not in text
        assert "$0.00 →" not in text

    @pytest.mark.asyncio
    async def test_task_performance_prints_milliseconds(self, mock_cls, tool):
        _mock_method(mock_cls, "get_task_performance_by_agent", [
            _row("anthropic-brief", 1682661, "TASK_PERFORMANCE_BY_AGENT"),
            _row("agent-alpha", 486.5, "TASK_PERFORMANCE_BY_AGENT"),
        ])
        text = await _render(tool, "get_task_performance")
        assert "1,682,661 ms" in text
        assert "486.50 ms" in text

    @pytest.mark.asyncio
    async def test_cost_and_count_figures_keep_their_units(self, mock_cls, tool):
        _mock_method(mock_cls, "get_vendor_costs", [_row("anthropic", 2239.36, "COST_METRIC_BY_VENDOR")])
        text = await _render(tool, "get_vendor_costs")
        assert "$2,239.36" in text
        assert "%" not in text

        _mock_method(mock_cls, "get_task_completion", [_row("code-review", 1993, "TASK_COMPLETION_AGGREGATED")])
        text = await _render(tool, "get_task_completion", {"aggregation": "aggregated"})
        assert "1,993" in text
        assert "1,993%" not in text
        assert "1,993 ms" not in text

    @pytest.mark.asyncio
    async def test_sub_cent_cost_rows_keep_their_digits(self, mock_cls, tool):
        _mock_method(mock_cls, "get_vendor_costs", [
            _row("anthropic", 0.0042, "COST_METRIC_BY_VENDOR"),
            _row("openai", 0.00042, "COST_METRIC_BY_VENDOR"),
            _row("google", 1234.5, "COST_METRIC_BY_VENDOR"),
            _row("refunded", -0.004, "COST_METRIC_BY_VENDOR"),
        ])
        text = await _render(tool, "get_vendor_costs")
        assert "$0.0042" in text
        assert "$0.00042" in text
        assert "$1,234.50" in text
        assert "$1,234.5000" not in text
        assert "$-0.004" in text
        assert not re.search(r"\$0\.00(?!\d)", text)

        _mock_method(mock_cls, "get_trace_cost_distribution", [
            {"transactionId": "tx1", "agentName": "a", "totalCost": 0.0031,
             "totalCalls": 2, "distinctTools": 1},
        ])
        text = await _render(tool, "get_trace_cost_distribution")
        assert "- **tx1** (a): $0.0031, 2 calls, 1 tools" in text

        _mock_method(mock_cls, "get_team_costs", [{
            "startTimestamp": "2026-07-01T00:00:00.000Z",
            "endTimestamp": "2026-07-01T23:59:59.999Z",
            "groups": [{"group": "team-a", "metrics": [
                {"label": "team-a", "metricResult": 0.0042, "metricType": "COST_METRIC_BY_TEAM"},
            ]}],
        }])
        text = await _render(tool, "get_team_costs")
        assert "- **2026-07-01**: team-a $0.0042" in text

        for not_a_number in (float("nan"), float("inf"), float("-inf")):
            assert tool._format_metric_value(not_a_number, "MONEY") == "n/a"

    @pytest.mark.parametrize("metric_type", ["PROFIT_MARGIN", "TOP_MOVERS_BY_MODEL", "AVG_TASK_PERFORMANCE"])
    def test_units_are_looked_up_by_the_exact_metric_type(self, mock_cls, metric_type):
        assert format_metric_result(12.5, metric_type) is None
        assert format_metric_result(12.5, "profit_margin_by_customer") == "12.50%"


def _skills_client(items):
    c = MagicMock()
    c.get_skills = AsyncMock(return_value={"_embedded": {"skillUsageResourceList": items}})
    c._extract_embedded_data = MagicMock(return_value=items)
    c._extract_pagination_info = MagicMock(return_value={})
    return c


def _skill_client(detail):
    c = MagicMock()
    c.get_skill_by_id = AsyncMock(return_value=detail)
    return c


_SKILL = {
    "id": "lm0KMv",
    "name": "d1-spike-skill",
    "originCategory": "UNKNOWN",
    "source": "project",
    "totalCost": 6e-06,
    "callCount": 1,
    "traceCount": 1,
}


class TestPlatformAmounts:
    @pytest.mark.asyncio
    async def test_a_sub_cent_skill_cost_keeps_its_digits(self, tool):
        tool.get_client = AsyncMock(return_value=_skills_client([_SKILL]))
        text = (await tool._handle_list_skills({}))[0].text
        assert "| 0.000006 USD |" in text
        assert "| 0 |" not in text

    @pytest.mark.asyncio
    async def test_skill_costs_carry_their_currency(self, tool):
        tool.get_client = AsyncMock(return_value=_skills_client([dict(_SKILL, totalCost=12345.5)]))
        text = (await tool._handle_list_skills({}))[0].text
        assert "| 12,345.50 USD |" in text

        tool.get_client = AsyncMock(return_value=_skill_client(dict(_SKILL, totalCost=792.45)))
        text = (await tool._handle_get_skill({"skill_id": "lm0KMv"}))[0].text
        assert "- **Total cost**: 792.45 USD" in text

    def test_pr_health_dollar_figures_keep_sub_cent_digits_and_currency(self, tool):
        at_risk = tool._render_pr_health_at_risk("Then", {"prs": 6, "estimatedDollars": 0.004})
        assert at_risk == "- Then: 6 pull requests, 0.004 USD estimated"

        totals = tool._render_pr_health_totals({"avgCostPerMergedPr": 1234.5})
        assert any(line.endswith("1,234.50 USD") for line in totals)

        report = {"basisNow": 0.004, "basisThen": 1234.5}
        text = "\n".join(tool._render_pr_health_follow_through(report, "github", None, None))
        assert "last 90 days: 0.004 USD; the 90 days ending on the first flag: 1,234.50 USD" in text

    def test_pr_health_estimates_carry_the_currency(self, tool):
        totals = {
            "avgCostPerMergedPr": 27.69,
            "rottingPrsAssisted": 76,
            "pricedRottingPrsAssisted": 76,
            "closedUnmergedAssisted": 20,
            "pricedClosedUnmergedAssisted": 20,
        }
        lines = tool._render_pr_health_totals(totals)
        assert any(line.endswith("~2,104.44 USD (estimate)") for line in lines)
        assert any(line.endswith("~553.80 USD (estimate)") for line in lines)
        assert not any("only cost figure" in line for line in lines)

    @pytest.mark.asyncio
    async def test_a_missing_amount_is_na_without_a_unit(self, tool):
        tool.get_client = AsyncMock(return_value=_skills_client([dict(_SKILL, totalCost=None)]))
        text = (await tool._handle_list_skills({}))[0].text
        assert "| n/a |" in text
        assert "n/a USD" not in text

    @pytest.mark.parametrize(
        "amount,expected",
        [
            (0.0067891, "0.0068 USD"),
            (5.551115123125783e-17, "0.000000000000000056 USD"),
            (-0.0, "0.00 USD"),
            (6e-06, "0.000006 USD"),
            (12345.5, "12,345.50 USD"),
            (None, "n/a"),
            (float("nan"), "n/a"),
            (True, "n/a"),
        ],
    )
    def test_sub_cent_amounts_keep_two_significant_digits(self, amount, expected):
        assert render_usd(amount) == expected
