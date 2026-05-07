"""Unit tests for BusinessAnalyticsManagement tool.

Tests handle_action routing, get_capabilities/get_examples,
unsupported action handling, error formatting, and chart generation logic.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    BusinessAnalyticsManagement,
)
from src.revenium_mcp_server.common.error_handling import ToolError


@pytest.fixture
def analytics_tool():
    """Create a BusinessAnalyticsManagement instance with chart rendering disabled."""
    with patch(
        "src.revenium_mcp_server.tools_decomposed.business_analytics_management.CHART_RENDERING_AVAILABLE",
        False,
    ):
        tool = BusinessAnalyticsManagement()
    return tool


class TestHandleActionRouting:
    """Test that handle_action routes to the correct handler for each action."""

    @pytest.mark.asyncio
    async def test_get_capabilities_returns_analytics_info(self, analytics_tool):
        """get_capabilities returns text describing available analytics actions."""
        result = await analytics_tool.handle_action("get_capabilities", {})
        text = result[0].text
        assert "get_provider_costs" in text
        assert "get_model_costs" in text
        assert "get_customer_costs" in text

    @pytest.mark.asyncio
    async def test_get_examples_returns_usage_examples(self, analytics_tool):
        """get_examples returns text with example JSON payloads."""
        result = await analytics_tool.handle_action("get_examples", {})
        text = result[0].text
        assert "get_provider_costs" in text
        assert "period" in text

    @pytest.mark.asyncio
    async def test_get_agent_summary_returns_overview(self, analytics_tool):
        """get_agent_summary returns a high-level overview for agent consumption."""
        result = await analytics_tool.handle_action("get_agent_summary", {})
        text = result[0].text
        assert "Business Analytics" in text
        assert "Quick Start" in text

    @pytest.mark.asyncio
    async def test_unsupported_action_returns_available_actions(self, analytics_tool):
        """An unsupported action returns a message listing available actions."""
        result = await analytics_tool.handle_action("totally_fake_action", {})
        text = result[0].text
        assert "Not Supported" in text
        assert "totally_fake_action" in text
        assert "get_capabilities" in text

    @pytest.mark.asyncio
    async def test_deprecated_actions_treated_as_unsupported(self, analytics_tool):
        """Known deprecated actions like cost_spike_analysis route to unsupported handler."""
        result = await analytics_tool.handle_action("cost_spike_analysis", {})
        text = result[0].text
        assert "Not Supported" in text
        assert "cost_spike_analysis" in text

    @pytest.mark.asyncio
    async def test_toolerror_propagates_through_handle_action(self, analytics_tool):
        """ToolError raised by a handler propagates without modification."""
        analytics_tool._handle_get_capabilities = AsyncMock(
            side_effect=ToolError(message="deliberate test error", error_code="TEST")
        )
        with pytest.raises(ToolError, match="deliberate test error"):
            await analytics_tool.handle_action("get_capabilities", {})

    @pytest.mark.asyncio
    async def test_generic_exception_wraps_in_toolerror(self, analytics_tool):
        """Non-ToolError exceptions are wrapped with processing error details."""
        analytics_tool._handle_get_capabilities = AsyncMock(
            side_effect=RuntimeError("unexpected boom")
        )
        with pytest.raises(ToolError, match="unexpected boom"):
            await analytics_tool.handle_action("get_capabilities", {})

    @pytest.mark.asyncio
    async def test_wrong_type_page_returns_structured_error(self, analytics_tool):
        """Non-numeric page is rejected up front with a structured ToolError so it
        no longer silently slides through as it did before BACK-1097."""
        with pytest.raises(ToolError) as exc:
            await analytics_tool.handle_action(
                "get_provider_costs", {"page": "not_a_number"}
            )
        assert exc.value.field == "page"

    @pytest.mark.asyncio
    async def test_valid_page_passes_validation(self, analytics_tool):
        """A correctly-typed page does not trip validation; the action proceeds
        normally and any downstream behaviour is unchanged."""
        analytics_tool._handle_get_provider_costs = AsyncMock(return_value=[])
        await analytics_tool.handle_action(
            "get_provider_costs", {"page": 0, "size": 20}
        )
        analytics_tool._handle_get_provider_costs.assert_awaited_once()


class TestFormatApiErrorDetails:
    """Test _format_api_error_details with different error types."""

    def test_generic_exception_formats_message(self, analytics_tool):
        """Non-API exceptions produce a simple error string."""
        result = analytics_tool._format_api_error_details(ValueError("bad value"))
        assert "bad value" in result

    def test_revenium_api_error_includes_status(self, analytics_tool):
        """ReveniumAPIError with status_code shows HTTP status in output."""
        from src.revenium_mcp_server.client import ReveniumAPIError

        err = ReveniumAPIError("auth failed", status_code=401)
        result = analytics_tool._format_api_error_details(err)
        assert "401" in result
        assert "auth failed" in result

    def test_revenium_api_error_with_response_data(self, analytics_tool):
        """ReveniumAPIError with response_data dict includes error_data."""
        from src.revenium_mcp_server.client import ReveniumAPIError

        err = ReveniumAPIError(
            "server error",
            status_code=500,
            response_data={"error_data": "rate limit exceeded"},
        )
        result = analytics_tool._format_api_error_details(err)
        assert "rate limit exceeded" in result


class TestChartGeneration:
    """Test _generate_visual_chart graceful degradation."""

    @pytest.mark.asyncio
    async def test_chart_disabled_returns_none(self, analytics_tool):
        """When chart_generation_enabled is False, returns None immediately."""
        analytics_tool.chart_generation_enabled = False
        result = await analytics_tool._generate_visual_chart(MagicMock())
        assert result is None

    @pytest.mark.asyncio
    async def test_chart_error_returns_none(self, analytics_tool):
        """When chart rendering raises, returns None (graceful degradation)."""
        analytics_tool.chart_generation_enabled = True
        analytics_tool.chart_renderer = AsyncMock()
        analytics_tool.chart_renderer.render_chart = AsyncMock(
            side_effect=RuntimeError("render failed")
        )
        mock_chart_data = MagicMock()
        mock_chart_data.config.width = 800
        mock_chart_data.config.height = 600
        result = await analytics_tool._generate_visual_chart(mock_chart_data)
        assert result is None


class TestAnalyzeCostAnomaliesRejectsStringThreshold:
    """BACK-1270 / item #7 — non-numeric min_impact_threshold must reject cleanly."""

    @pytest.mark.asyncio
    async def test_non_numeric_threshold_returns_clean_error(self, analytics_tool):
        from tests.unit._helpers_no_framework_leak import assert_no_framework_leak
        with pytest.raises(ToolError) as exc:
            await analytics_tool.handle_action(
                "analyze_cost_anomalies",
                {"period": "LAST_24_HOURS", "min_impact_threshold": "high"},
            )
        assert exc.value.field == "min_impact_threshold"
        assert "number" in exc.value.message.lower() or "float" in exc.value.message.lower()
        assert_no_framework_leak(exc.value.message)


class TestCoerceNumericParam:
    """BACK-1270 / item #7 — numeric_param_validator helper coverage."""

    def test_numeric_string_is_coerced_to_float(self):
        from src.revenium_mcp_server.common.numeric_param_validator import coerce_numeric_param
        out = coerce_numeric_param(
            {"min_impact_threshold": "0.5"},
            "min_impact_threshold",
            action="analyze_cost_anomalies",
            minimum=0.0,
        )
        assert out["min_impact_threshold"] == 0.5
        assert isinstance(out["min_impact_threshold"], float)

    def test_int_is_coerced_to_float(self):
        from src.revenium_mcp_server.common.numeric_param_validator import coerce_numeric_param
        out = coerce_numeric_param(
            {"x": 42}, "x", action="test", minimum=0.0
        )
        assert out["x"] == 42.0
        assert isinstance(out["x"], float)

    def test_default_used_when_param_absent(self):
        from src.revenium_mcp_server.common.numeric_param_validator import coerce_numeric_param
        out = coerce_numeric_param({}, "x", action="test", default=10.0)
        assert out["x"] == 10.0

    def test_bool_is_rejected(self):
        from src.revenium_mcp_server.common.numeric_param_validator import coerce_numeric_param
        with pytest.raises(ToolError) as exc:
            coerce_numeric_param({"x": True}, "x", action="test")
        assert exc.value.field == "x"

    def test_below_minimum_is_rejected(self):
        from src.revenium_mcp_server.common.numeric_param_validator import coerce_numeric_param
        with pytest.raises(ToolError) as exc:
            coerce_numeric_param({"x": -1.0}, "x", action="test", minimum=0.0)
        assert exc.value.field == "x"
        assert ">=" in exc.value.message

    def test_above_maximum_is_rejected(self):
        from src.revenium_mcp_server.common.numeric_param_validator import coerce_numeric_param
        with pytest.raises(ToolError) as exc:
            coerce_numeric_param({"x": 999.0}, "x", action="test", maximum=100.0)
        assert exc.value.field == "x"
        assert "<=" in exc.value.message

    def test_nan_string_is_rejected(self):
        from src.revenium_mcp_server.common.numeric_param_validator import coerce_numeric_param
        with pytest.raises(ToolError) as exc:
            coerce_numeric_param({"x": "nan"}, "x", action="t", minimum=0.0)
        assert exc.value.field == "x"
        assert "finite" in exc.value.message.lower()  # finiteness branch, not parse-failure branch

    def test_inf_string_is_rejected(self):
        from src.revenium_mcp_server.common.numeric_param_validator import coerce_numeric_param
        with pytest.raises(ToolError) as exc:
            coerce_numeric_param({"x": "inf"}, "x", action="t", minimum=0.0)
        assert exc.value.field == "x"

    def test_nan_float_is_rejected(self):
        from src.revenium_mcp_server.common.numeric_param_validator import coerce_numeric_param
        with pytest.raises(ToolError) as exc:
            coerce_numeric_param({"x": float("nan")}, "x", action="t", minimum=0.0)
        assert exc.value.field == "x"

    def test_explicit_none_is_rejected(self):
        from src.revenium_mcp_server.common.numeric_param_validator import coerce_numeric_param
        with pytest.raises(ToolError) as exc:
            coerce_numeric_param({"x": None}, "x", action="t")
        assert exc.value.field == "x"
