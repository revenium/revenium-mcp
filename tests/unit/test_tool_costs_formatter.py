"""Unit tests for ToolCostsFormatter."""

import pytest

from src.revenium_mcp_server.analytics.formatters.tool_costs_formatter import (
    ToolCostsFormatter,
)


class TestToolCostsFormatter:
    """Tests for ToolCostsFormatter.format()."""

    @pytest.fixture
    def formatter(self):
        return ToolCostsFormatter(production_mode=True)

    @pytest.fixture
    def formatter_debug(self):
        return ToolCostsFormatter(production_mode=False)

    def test_format_with_data(self, formatter):
        data = [
            {"tool": "manage_products", "cost": 0.50, "percentage": 62.5, "call_count": 28},
            {"tool": "manage_tools", "cost": 0.30, "percentage": 37.5, "call_count": 15},
        ]
        params = {"period": "HOUR", "aggregation": "TOTAL"}
        result = formatter.format(data, params)
        assert "Tool Cost Analysis" in result
        assert "manage_products" in result
        assert "$0.50" in result
        assert "manage_tools" in result
        assert "28" in result

    def test_format_empty_data(self, formatter):
        result = formatter.format([], {"period": "HOUR", "aggregation": "TOTAL"})
        assert "No Data Available" in result

    def test_format_none_data(self, formatter):
        result = formatter.format(None, {"period": "HOUR", "aggregation": "TOTAL"})
        assert "No Data Available" in result

    def test_format_with_percentage(self, formatter):
        data = [{"tool": "manage_products", "cost": 1.00, "percentage": 100.0}]
        params = {"period": "SEVEN_DAYS", "aggregation": "TOTAL"}
        result = formatter.format(data, params)
        assert "100.0%" in result

    def test_format_debug_mode_shows_debug_entry(self, formatter_debug):
        data = [{"tool": "DEBUG_INFO", "debug": {"raw_count": 5}}]
        params = {"period": "HOUR", "aggregation": "TOTAL"}
        result = formatter_debug.format(data, params)
        assert "DEBUG" in result

    def test_format_production_mode_hides_debug_entry(self, formatter):
        data = [{"tool": "DEBUG_INFO", "debug": {"raw_count": 5}}]
        params = {"period": "HOUR", "aggregation": "TOTAL"}
        result = formatter.format(data, params)
        assert "DEBUG" not in result or "No Data" in result

    def test_format_agent_keyed_data(self, formatter):
        """Agent-keyed data from get_tool_costs_by_agent should display agent names."""
        data = [
            {"agent": "billing-agent", "cost": 1.20, "percentage": 70.0, "call_count": 40},
            {"agent": "support-agent", "cost": 0.50, "percentage": 30.0, "call_count": 15},
        ]
        params = {"period": "DAY", "aggregation": "TOTAL"}
        result = formatter.format(data, params)
        assert "billing-agent" in result
        assert "support-agent" in result
        assert "Unknown" not in result
        assert "$1.20" in result

    def test_format_provider_keyed_data(self, formatter):
        """Provider-keyed data from get_tool_costs_by_provider should display provider names."""
        data = [
            {"provider": "openai", "cost": 2.00, "percentage": 80.0, "call_count": 100},
            {"provider": "anthropic", "cost": 0.50, "percentage": 20.0, "call_count": 25},
        ]
        params = {"period": "SEVEN_DAYS", "aggregation": "TOTAL"}
        result = formatter.format(data, params)
        assert "openai" in result
        assert "anthropic" in result
        assert "Unknown" not in result
        assert "$2.00" in result

    def test_format_call_count_only_no_cost_line(self, formatter):
        """Data without a cost key (e.g. get_top_tools) must not show a $0.00 cost line."""
        data = [
            {"tool": "manage_products", "call_count": 50},
            {"tool": "manage_tools", "call_count": 20},
        ]
        params = {"period": "HOUR", "aggregation": "TOTAL"}
        result = formatter.format(data, params)
        assert "manage_products" in result
        assert "manage_tools" in result
        assert "$0.00" not in result
        assert "Cost:" not in result
        assert "50" in result

    def test_format_cost_zero_not_shown(self, formatter):
        """An explicit cost of 0 should not render a cost line."""
        data = [{"tool": "free-tool", "cost": 0, "call_count": 10}]
        params = {"period": "HOUR", "aggregation": "TOTAL"}
        result = formatter.format(data, params)
        assert "free-tool" in result
        assert "Cost:" not in result
        assert "$0.00" not in result
