"""Unit tests for tools_decomposed/business_analytics_management.py (M3).

Covers missed lines in BusinessAnalyticsManagement:
- __init__ chart path (lines 91-108)
- _generate_visual_chart (lines 116-144)
- handle_action routing for all actions (lines 160-210)
- _handle_get_cost_summary success / ValidationError / generic Exception paths
- _handle_get_capabilities
- _handle_get_agent_summary
- _handle_get_examples
- _handle_get_provider_costs, _handle_get_model_costs, _handle_get_customer_costs
- _handle_get_api_key_costs, _handle_get_agent_costs
- _handle_analyze_cost_anomalies: success, threshold param error,
  breakdown_by param error, missing period, ValidationError, generic Exception
- _handle_unsupported_action / _handle_unimplemented_feature
- _get_supported_actions / _get_tool_capabilities
- _format_api_error_details with ReveniumAPIError and generic exception
"""

import re
from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp.types import TextContent

from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    BusinessAnalyticsManagement,
)
from src.revenium_mcp_server.analytics.enhanced_spike_analyzer import (
    EnhancedSpikeAnalyzer,
    TemporalAnomaly,
)
from src.revenium_mcp_server.analytics.simple_cost_analyzer import PackRows
from src.revenium_mcp_server.analytics.validation import ValidationError
from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.common.error_handling import ToolError

# Module path prefix for patching constructors
_MOD = "src.revenium_mcp_server.tools_decomposed.business_analytics_management"


# ────────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def tool():
    """Create BusinessAnalyticsManagement with mocked get_client."""
    t = BusinessAnalyticsManagement(ucm_helper=None)
    # Mock get_client so handlers never hit the real client constructor
    t.get_client = AsyncMock(return_value=MagicMock())
    t.client = MagicMock()
    return t


# ────────────────────────────────────────────────────────────────────────────
# __init__ and chart initialization
# ────────────────────────────────────────────────────────────────────────────

class TestInit:
    """Test __init__ path branches."""

    def test_init_no_ucm_helper(self):
        t = BusinessAnalyticsManagement(ucm_helper=None)
        assert t.ucm_helper is None
        assert t.resource_type == "analytics"

    def test_chart_disabled_when_renderer_unavailable(self):
        """When MatplotlibChartRenderer is None, chart generation is disabled."""
        with patch(
            f"{_MOD}.CHART_RENDERING_AVAILABLE",
            False,
        ), patch(
            f"{_MOD}.MatplotlibChartRenderer",
            None,
        ):
            t = BusinessAnalyticsManagement()
            assert t.chart_generation_enabled is False
            assert t.chart_renderer is None

    def test_chart_enabled_when_renderer_available(self):
        """When MatplotlibChartRenderer is available, try to initialize chart renderer."""
        mock_renderer_class = MagicMock()
        mock_renderer_instance = MagicMock()
        mock_renderer_class.return_value = mock_renderer_instance

        mock_config_class = MagicMock()
        mock_config_instance = MagicMock()
        mock_config_class.return_value = mock_config_instance

        with patch(
            f"{_MOD}.CHART_RENDERING_AVAILABLE",
            True,
        ), patch(
            f"{_MOD}.MatplotlibChartRenderer",
            mock_renderer_class,
        ), patch(
            f"{_MOD}.ChartRenderConfig",
            mock_config_class,
        ):
            t = BusinessAnalyticsManagement()
            assert t.chart_generation_enabled is True
            assert t.chart_renderer is mock_renderer_instance

    def test_chart_disabled_when_renderer_init_raises(self):
        """When renderer instantiation raises, chart generation is disabled gracefully."""
        mock_renderer_class = MagicMock(side_effect=Exception("no matplotlib"))
        mock_config_class = MagicMock(return_value=MagicMock())

        with patch(
            f"{_MOD}.CHART_RENDERING_AVAILABLE",
            True,
        ), patch(
            f"{_MOD}.MatplotlibChartRenderer",
            mock_renderer_class,
        ), patch(
            f"{_MOD}.ChartRenderConfig",
            mock_config_class,
        ):
            t = BusinessAnalyticsManagement()
            assert t.chart_generation_enabled is False
            assert t.chart_renderer is None


# ────────────────────────────────────────────────────────────────────────────
# _generate_visual_chart
# ────────────────────────────────────────────────────────────────────────────

class TestGenerateVisualChart:
    """Test the visual chart generation helper."""

    @pytest.mark.asyncio
    async def test_returns_none_when_chart_disabled(self, tool):
        tool.chart_generation_enabled = False
        result = await tool._generate_visual_chart(MagicMock())
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_renderer(self, tool):
        tool.chart_generation_enabled = True
        tool.chart_renderer = None
        result = await tool._generate_visual_chart(MagicMock())
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_image_content_on_success(self, tool):
        tool.chart_generation_enabled = True
        mock_renderer = MagicMock()
        mock_renderer.render_chart = AsyncMock(return_value="base64data==")
        tool.chart_renderer = mock_renderer

        # Construct a fake chart_data with config that has width/height
        mock_chart_data = MagicMock()
        mock_chart_data.config.width = 800
        mock_chart_data.config.height = 600

        result = await tool._generate_visual_chart(mock_chart_data)
        assert result is not None
        assert result.type == "image"
        assert result.data == "base64data=="
        assert result.mime_type == "image/png"

    @pytest.mark.asyncio
    async def test_returns_none_on_render_exception(self, tool):
        tool.chart_generation_enabled = True
        mock_renderer = MagicMock()
        mock_renderer.render_chart = AsyncMock(side_effect=RuntimeError("render failed"))
        tool.chart_renderer = mock_renderer

        mock_chart_data = MagicMock()
        mock_chart_data.config.width = 800
        mock_chart_data.config.height = 600

        result = await tool._generate_visual_chart(mock_chart_data)
        assert result is None


# ────────────────────────────────────────────────────────────────────────────
# _format_api_error_details
# ────────────────────────────────────────────────────────────────────────────

class TestFormatApiErrorDetails:
    """Test error formatting for API errors vs generic exceptions."""

    def test_formats_revenium_api_error(self, tool):
        err = ReveniumAPIError("bad request")
        result = tool._format_api_error_details(err)
        assert "API Error" in result
        assert "bad request" in result

    def test_formats_api_error_with_status_code(self, tool):
        err = ReveniumAPIError("unauthorized")
        err.status_code = 401
        result = tool._format_api_error_details(err)
        assert "401" in result

    def test_formats_api_error_with_response_data_error_data(self, tool):
        err = ReveniumAPIError("forbidden")
        err.status_code = 403
        err.response_data = {
            "error_data": {"timestamp": "2026-10-16T03:15:54Z", "path": "/profitstream/v2/api/x"}
        }
        result = tool._format_api_error_details(err)
        assert "**API Error**: forbidden" in result
        assert "**HTTP Status**: 403" in result
        assert "API Response" not in result
        assert "'timestamp'" not in result
        assert "'path'" not in result

    def test_formats_api_error_with_empty_error_data(self, tool):
        err = ReveniumAPIError("ok")
        err.status_code = 200
        err.response_data = {"error_data": None}
        result = tool._format_api_error_details(err)
        # Should not crash, should still have message
        assert "ok" in result

    def test_formats_generic_exception(self, tool):
        err = ValueError("something went wrong")
        result = tool._format_api_error_details(err)
        assert "something went wrong" in result
        assert "Error" in result


# ────────────────────────────────────────────────────────────────────────────
# handle_action routing
# ────────────────────────────────────────────────────────────────────────────

@patch(f"{_MOD}.EnhancedSpikeAnalyzer")
@patch(f"{_MOD}.SimpleAnalyticsEngine")
class TestHandleActionRouting:
    """Test that handle_action routes to the correct handlers."""

    @pytest.mark.asyncio
    async def test_get_capabilities_action(self, _mock_engine_cls, _mock_analyzer_cls, tool):
        result = await tool.handle_action("get_capabilities", {})
        # BACK-3170: a second block carries the per-action parameter reference,
        # which the advertised MCP schema no longer lists.
        assert len(result) == 2
        assert isinstance(result[0], TextContent)
        assert "Business Analytics" in result[0].text
        assert "## Parameters" in result[1].text

    @pytest.mark.asyncio
    async def test_get_examples_action(self, _mock_engine_cls, _mock_analyzer_cls, tool):
        result = await tool.handle_action("get_examples", {})
        assert len(result) == 1
        assert "Examples" in result[0].text

    @pytest.mark.asyncio
    async def test_get_agent_summary_action(self, _mock_engine_cls, _mock_analyzer_cls, tool):
        result = await tool.handle_action("get_agent_summary", {})
        assert len(result) == 1
        assert "Business Analytics Management" in result[0].text

    @pytest.mark.asyncio
    async def test_get_provider_costs_action(self, mock_engine_cls, _mock_analyzer_cls, tool):
        mock_engine_cls.return_value.get_provider_costs = AsyncMock(return_value="provider costs")
        result = await tool.handle_action("get_provider_costs", {"period": "SEVEN_DAYS"})
        assert result[0].text == "provider costs"

    @pytest.mark.asyncio
    async def test_get_model_costs_action(self, mock_engine_cls, _mock_analyzer_cls, tool):
        mock_engine_cls.return_value.get_model_costs = AsyncMock(return_value="model costs")
        result = await tool.handle_action("get_model_costs", {"period": "SEVEN_DAYS"})
        assert result[0].text == "model costs"

    @pytest.mark.asyncio
    async def test_get_customer_costs_action(self, mock_engine_cls, _mock_analyzer_cls, tool):
        mock_engine_cls.return_value.get_customer_costs = AsyncMock(return_value="customer costs")
        result = await tool.handle_action("get_customer_costs", {"period": "SEVEN_DAYS"})
        assert result[0].text == "customer costs"

    @pytest.mark.asyncio
    async def test_get_api_key_costs_action(self, mock_engine_cls, _mock_analyzer_cls, tool):
        mock_engine_cls.return_value.get_api_key_costs = AsyncMock(return_value="api key costs")
        result = await tool.handle_action("get_api_key_costs", {"period": "SEVEN_DAYS"})
        assert result[0].text == "api key costs"

    @pytest.mark.asyncio
    async def test_get_agent_costs_action(self, mock_engine_cls, _mock_analyzer_cls, tool):
        mock_engine_cls.return_value.get_agent_costs = AsyncMock(return_value="agent costs")
        result = await tool.handle_action("get_agent_costs", {"period": "SEVEN_DAYS"})
        assert result[0].text == "agent costs"

    @pytest.mark.asyncio
    async def test_get_cost_summary_action(self, mock_engine_cls, _mock_analyzer_cls, tool):
        mock_engine_cls.return_value.get_cost_summary = AsyncMock(return_value="summary text")
        result = await tool.handle_action("get_cost_summary", {"period": "SEVEN_DAYS"})
        assert result[0].text == "summary text"

    @pytest.mark.asyncio
    async def test_analyze_cost_anomalies_action(self, _mock_engine_cls, mock_analyzer_cls, tool):
        mock_analyzer_cls.return_value.analyze_temporal_anomalies = AsyncMock(
            return_value={"anomalies": []}
        )
        result = await tool.handle_action("analyze_cost_anomalies", {"period": "SEVEN_DAYS"})
        assert len(result) == 1
        assert "anomalies" in result[0].text

    @pytest.mark.asyncio
    async def test_unsupported_action_get_cost_trends(self, _mock_engine_cls, _mock_analyzer_cls, tool):
        with pytest.raises(ToolError) as exc:
            await tool.handle_action("get_cost_trends", {})
        assert "Not Supported" in exc.value.message

    @pytest.mark.asyncio
    async def test_unsupported_action_unknown(self, _mock_engine_cls, _mock_analyzer_cls, tool):
        with pytest.raises(ToolError) as exc:
            await tool.handle_action("completely_unknown_action", {})
        assert "Not Supported" in exc.value.message

    @pytest.mark.asyncio
    async def test_tool_error_inside_handle_action_is_reraised(self, _mock_engine_cls, _mock_analyzer_cls, tool):
        """ToolError raised directly by handle_action routing is re-raised."""
        tool._handle_get_provider_costs = AsyncMock(
            side_effect=ToolError("intentional", "ERR_001")
        )
        with pytest.raises(ToolError):
            await tool.handle_action("get_provider_costs", {"period": "SEVEN_DAYS"})

    @pytest.mark.asyncio
    async def test_generic_exception_in_sub_handler_raises_tool_error(self, _mock_engine_cls, _mock_analyzer_cls, tool):
        """Unexpected exceptions propagated out of a sub-handler are wrapped as ToolError."""
        tool._handle_get_provider_costs = AsyncMock(side_effect=RuntimeError("unexpected"))
        with pytest.raises(ToolError):
            await tool.handle_action("get_provider_costs", {"period": "SEVEN_DAYS"})


# ────────────────────────────────────────────────────────────────────────────
# _handle_get_cost_summary
# ────────────────────────────────────────────────────────────────────────────

@patch(f"{_MOD}.SimpleAnalyticsEngine")
class TestHandleGetCostSummary:
    """Test cost summary handler success and error paths."""

    @pytest.mark.asyncio
    async def test_success_returns_text_content(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_cost_summary = AsyncMock(return_value="all good")
        result = await tool._handle_get_cost_summary({"period": "SEVEN_DAYS"})
        assert result[0].text == "all good"

    @pytest.mark.asyncio
    async def test_engine_created_per_request(self, mock_engine_cls, tool):
        """Engine is constructed fresh on every call (no caching)."""
        mock_engine_cls.return_value.get_cost_summary = AsyncMock(return_value="result")

        await tool._handle_get_cost_summary({})
        await tool._handle_get_cost_summary({})

        assert mock_engine_cls.call_count == 2

    @pytest.mark.asyncio
    async def test_validation_error_raises_error_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_cost_summary = AsyncMock(
            side_effect=ValidationError("bad period", suggestions=["Use SEVEN_DAYS"])
        )
        with pytest.raises(ToolError) as exc:
            await tool._handle_get_cost_summary({})
        assert "Validation Error" in exc.value.message
        assert "bad period" in exc.value.message
        assert "Use SEVEN_DAYS" in exc.value.message

    @pytest.mark.asyncio
    async def test_generic_exception_raises_error_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_cost_summary = AsyncMock(
            side_effect=RuntimeError("oops")
        )
        with pytest.raises(ToolError) as exc:
            await tool._handle_get_cost_summary({})
        assert "Failed" in exc.value.message


# ────────────────────────────────────────────────────────────────────────────
# _handle_get_provider_costs error paths
# ────────────────────────────────────────────────────────────────────────────

@patch(f"{_MOD}.SimpleAnalyticsEngine")
class TestHandleGetProviderCosts:
    @pytest.mark.asyncio
    async def test_validation_error_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_provider_costs = AsyncMock(
            side_effect=ValidationError("invalid period", suggestions=["Try SEVEN_DAYS"])
        )
        with pytest.raises(ToolError) as exc:
            await tool._handle_get_provider_costs({})
        assert "Provider Costs Validation Error" in exc.value.message
        assert "invalid period" in exc.value.message

    @pytest.mark.asyncio
    async def test_generic_exception_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_provider_costs = AsyncMock(
            side_effect=RuntimeError("API failure")
        )
        with pytest.raises(ToolError) as exc:
            await tool._handle_get_provider_costs({})
        assert "Provider Costs Analysis Failed" in exc.value.message


# ────────────────────────────────────────────────────────────────────────────
# _handle_get_model_costs error paths
# ────────────────────────────────────────────────────────────────────────────

@patch(f"{_MOD}.SimpleAnalyticsEngine")
class TestHandleGetModelCosts:
    @pytest.mark.asyncio
    async def test_validation_error_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_model_costs = AsyncMock(
            side_effect=ValidationError("bad group", suggestions=["Use TOTAL"])
        )
        with pytest.raises(ToolError) as exc:
            await tool._handle_get_model_costs({})
        assert "Model Costs Validation Error" in exc.value.message

    @pytest.mark.asyncio
    async def test_generic_exception_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_model_costs = AsyncMock(
            side_effect=RuntimeError("crash")
        )
        with pytest.raises(ToolError) as exc:
            await tool._handle_get_model_costs({})
        assert "Model Costs Analysis Failed" in exc.value.message


# ────────────────────────────────────────────────────────────────────────────
# _handle_get_customer_costs error paths
# ────────────────────────────────────────────────────────────────────────────

@patch(f"{_MOD}.SimpleAnalyticsEngine")
class TestHandleGetCustomerCosts:
    @pytest.mark.asyncio
    async def test_validation_error_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_customer_costs = AsyncMock(
            side_effect=ValidationError("missing param", suggestions=["add period"])
        )
        with pytest.raises(ToolError) as exc:
            await tool._handle_get_customer_costs({})
        assert "Customer Costs Validation Error" in exc.value.message

    @pytest.mark.asyncio
    async def test_generic_exception_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_customer_costs = AsyncMock(
            side_effect=Exception("error")
        )
        with pytest.raises(ToolError) as exc:
            await tool._handle_get_customer_costs({})
        assert "Customer Costs Analysis Failed" in exc.value.message


# ────────────────────────────────────────────────────────────────────────────
# _handle_get_api_key_costs error paths
# ────────────────────────────────────────────────────────────────────────────

@patch(f"{_MOD}.SimpleAnalyticsEngine")
class TestHandleGetApiKeyCosts:
    @pytest.mark.asyncio
    async def test_validation_error_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_api_key_costs = AsyncMock(
            side_effect=ValidationError("bad", suggestions=["fix it"])
        )
        with pytest.raises(ToolError) as exc:
            await tool._handle_get_api_key_costs({})
        assert "API Key Costs Validation Error" in exc.value.message

    @pytest.mark.asyncio
    async def test_generic_exception_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_api_key_costs = AsyncMock(
            side_effect=Exception("down")
        )
        with pytest.raises(ToolError) as exc:
            await tool._handle_get_api_key_costs({})
        assert "API Key Costs Analysis Failed" in exc.value.message


# ────────────────────────────────────────────────────────────────────────────
# _handle_get_agent_costs error paths
# ────────────────────────────────────────────────────────────────────────────

@patch(f"{_MOD}.SimpleAnalyticsEngine")
class TestHandleGetAgentCosts:
    @pytest.mark.asyncio
    async def test_validation_error_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_agent_costs = AsyncMock(
            side_effect=ValidationError("bad", suggestions=["fix it"])
        )
        with pytest.raises(ToolError) as exc:
            await tool._handle_get_agent_costs({})
        assert "Agent Costs Validation Error" in exc.value.message

    @pytest.mark.asyncio
    async def test_generic_exception_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_agent_costs = AsyncMock(
            side_effect=Exception("down")
        )
        with pytest.raises(ToolError) as exc:
            await tool._handle_get_agent_costs({})
        assert "Agent Costs Analysis Failed" in exc.value.message


# ────────────────────────────────────────────────────────────────────────────
# _handle_analyze_cost_anomalies
# ────────────────────────────────────────────────────────────────────────────

@patch(f"{_MOD}.EnhancedSpikeAnalyzer")
class TestHandleAnalyzeCostAnomalies:
    """Test all branches of the anomaly analysis handler."""

    @pytest.mark.asyncio
    async def test_success_returns_json(self, mock_analyzer_cls, tool):
        mock_analyzer_cls.return_value.analyze_temporal_anomalies = AsyncMock(
            return_value={"anomalies": []}
        )
        result = await tool._handle_analyze_cost_anomalies({"period": "SEVEN_DAYS"})
        assert "anomalies" in result[0].text

    @pytest.mark.asyncio
    async def test_threshold_param_error_raises_guidance(self, mock_analyzer_cls, tool):
        """Using 'threshold' instead of 'min_impact_threshold' raises with the correct param name.

        create_structured_validation_error returns a ToolError (not ValidationError), which
        _handle_analyze_cost_anomalies lets through unchanged, so the caller reads the
        refusal itself rather than a generic analysis failure wrapped around it.
        """
        with pytest.raises(ToolError) as exc:
            await tool._handle_analyze_cost_anomalies(
                {"period": "SEVEN_DAYS", "threshold": 100.0}
            )
        assert "Analysis Failed" not in exc.value.message
        assert "min_impact_threshold" in exc.value.message

    @pytest.mark.asyncio
    async def test_breakdown_by_error_raises_error_text(self, mock_analyzer_cls, tool):
        """Using 'breakdown_by' instead of 'include_dimensions' raises with the correct param name.

        create_structured_validation_error returns a ToolError that passes through unchanged,
        and its message includes 'include_dimensions'.
        """
        with pytest.raises(ToolError) as exc:
            await tool._handle_analyze_cost_anomalies(
                {"period": "SEVEN_DAYS", "breakdown_by": "providers"}
            )
        assert "Analysis Failed" not in exc.value.message
        assert "include_dimensions" in exc.value.message

    @pytest.mark.asyncio
    async def test_missing_period_raises_error_text(self, mock_analyzer_cls, tool):
        """Missing period raises with text explaining that period is required.

        create_structured_missing_parameter_error returns a ToolError that passes through
        unchanged, and its message includes 'period'.
        """
        with pytest.raises(ToolError) as exc:
            await tool._handle_analyze_cost_anomalies({})
        assert "Analysis Failed" not in exc.value.message
        assert "period" in exc.value.message.lower()

    @pytest.mark.asyncio
    async def test_validation_error_from_analyzer_raises_text(self, mock_analyzer_cls, tool):
        mock_analyzer_cls.return_value.analyze_temporal_anomalies = AsyncMock(
            side_effect=ValidationError("invalid sensitivity", suggestions=["use normal"])
        )
        with pytest.raises(ToolError) as exc:
            await tool._handle_analyze_cost_anomalies({"period": "SEVEN_DAYS"})
        assert "Validation Error" in exc.value.message
        assert "invalid sensitivity" in exc.value.message

    @pytest.mark.asyncio
    async def test_generic_exception_raises_error_text(self, mock_analyzer_cls, tool):
        mock_analyzer_cls.return_value.analyze_temporal_anomalies = AsyncMock(
            side_effect=RuntimeError("analyzer failed")
        )
        with pytest.raises(ToolError) as exc:
            await tool._handle_analyze_cost_anomalies({"period": "SEVEN_DAYS"})
        assert "Failed" in exc.value.message

    @pytest.mark.asyncio
    async def test_defaults_applied_for_optional_params(self, mock_analyzer_cls, tool):
        """Optional params are defaulted correctly before calling the analyzer."""
        mock_analyze = AsyncMock(return_value={"anomalies": []})
        mock_analyzer_cls.return_value.analyze_temporal_anomalies = mock_analyze

        result = await tool._handle_analyze_cost_anomalies({"period": "SEVEN_DAYS"})
        # Analyzer was called with default sensitivity="normal"
        call_kwargs = mock_analyze.call_args
        assert call_kwargs.kwargs.get("sensitivity") == "normal"
        assert call_kwargs.kwargs.get("min_impact_threshold") == 10.0

    @pytest.mark.asyncio
    async def test_breakdown_by_none_value_handled(self, mock_analyzer_cls, tool):
        """breakdown_by=None doesn't crash the dimension mapping and raises with guidance text.

        Even when breakdown_by is None, the ToolError message still directs the user to
        use 'include_dimensions', confirming the None-safe branch ran without raising.
        """
        with pytest.raises(ToolError) as exc:
            await tool._handle_analyze_cost_anomalies(
                {"period": "SEVEN_DAYS", "breakdown_by": None}
            )
        assert "Analysis Failed" not in exc.value.message
        assert "include_dimensions" in exc.value.message

    @pytest.mark.asyncio
    async def test_analyzer_created_per_request(self, mock_analyzer_cls, tool):
        """Analyzer is constructed fresh on every call (no caching)."""
        mock_analyzer_cls.return_value.analyze_temporal_anomalies = AsyncMock(
            return_value={"ok": True}
        )

        await tool._handle_analyze_cost_anomalies({"period": "SEVEN_DAYS"})
        await tool._handle_analyze_cost_anomalies({"period": "SEVEN_DAYS"})

        assert mock_analyzer_cls.call_count == 2


# ────────────────────────────────────────────────────────────────────────────
# _format_anomaly_results_markdown — direct formatter tests
# ────────────────────────────────────────────────────────────────────────────

class TestFormatAnomalyResultsMarkdown:
    """Direct unit coverage for the markdown formatter — all rendering branches."""

    @pytest.fixture
    def fmt(self):
        return BusinessAnalyticsManagement(ucm_helper=None)._format_anomaly_results_markdown

    def test_full_payload_renders_all_sections(self, fmt):
        payload = {
            "period_analyzed": "SEVEN_DAYS",
            "sensitivity_used": "aggressive",
            "time_groups_analyzed": 7,
            "entities_analyzed": {"providers": 6, "agents": 25},
            "total_anomalies_detected": 2,
            "temporal_anomalies": [
                {
                    "entity_name": "OPENAI",
                    "entity_type": "provider",
                    "time_group_label": "Monday",
                    "anomaly_value": 123.45,
                    "normal_range_min": 10.0,
                    "normal_range_max": 20.0,
                    "z_score": 7.0,
                    "severity_score": 50.0,
                    "anomaly_type": "entity_temporal",
                    "context": "OPENAI Monday spike",
                    "percentage_above_normal": 500.0,
                },
                {
                    "entity_name": "ANTHROPIC",
                    "entity_type": "provider",
                    "time_group_label": "Sunday",
                    "anomaly_value": 7.0,
                    "normal_range_min": 1.0,
                    "normal_range_max": 2.0,
                    "z_score": 3.2,
                    "severity_score": 12.0,
                    "anomaly_type": "entity_temporal",
                    "context": "Anthropic weekend pattern",
                    "percentage_above_normal": 250.0,
                },
            ],
            "time_period_summary": {
                "Monday": {"total_anomalies": 1, "cost_multiplier": 10.9},
            },
            "entity_summary": {
                "OPENAI": {
                    "anomalous_time_periods": ["Monday", "Wednesday"],
                    "anomaly_pattern": "Multiple periods",
                },
            },
            "new_entities_detected": 1,
            "new_entity_summary": "Detected 1 new cost source with $50 impact",
            "new_entities_by_type": {
                "agent": {
                    "count": 1,
                    "summary": "1 new agent",
                    "entities": [
                        {"entity_name": "NEW-BOT", "total_cost_impact": 50.0, "periods_active": 3},
                        {"entity_name": "TINY-BOT", "total_cost_impact": 0.004, "periods_active": 1},
                    ],
                },
            },
            "recommendations": ["Tag your credentials"],
        }
        out = fmt(payload)
        assert "# Cost Anomaly Analysis — SEVEN_DAYS" in out
        assert "**Total anomalies detected:** 2" in out
        assert "**Time groups analyzed for anomalies:** 7" in out
        assert "| OPENAI | provider | Monday | $123.45 |" in out
        assert "$10.00–$20.00" in out
        assert "### Anomaly Context" in out
        assert "OPENAI Monday spike" in out
        assert "### Monday" in out
        assert "**Cost multiplier**: 10.90" in out
        assert "**Anomalous time periods**: Monday, Wednesday" in out
        assert "## New Entities Detected" in out
        assert "NEW-BOT" in out
        assert "$50.00 impact, active in 3 bucket(s)" in out
        assert "**TINY-BOT**: $0.004 impact" in out
        assert "## Recommendations" in out
        assert "- Tag your credentials" in out

    def test_percent_column_compares_with_the_same_normal_as_the_multiplier(self, fmt):
        payload = {
            "period_analyzed": "SEVEN_DAYS",
            "sensitivity_used": "normal",
            "total_anomalies_detected": 1,
            "temporal_anomalies": [
                {
                    "entity_name": "CODEXCLI",
                    "entity_type": "provider",
                    "time_group_label": "Wednesday",
                    "anomaly_value": 86.31,
                    "normal_range_min": 0.0,
                    "normal_range_max": 45.11,
                    "z_score": 2.5,
                    "severity_score": 23.5,
                    "percentage_above_normal": 282.7,
                },
            ],
        }
        out = fmt(payload)
        assert "| % vs Normal |" in out
        assert "| % Above |" not in out

    def test_the_answer_states_the_spike_as_its_cost_divided_by_normal(self, fmt):
        analyzer = EnhancedSpikeAnalyzer(MagicMock())
        analyzer.entity_dimension_map = {"CODEXCLI": "providers"}
        spike = TemporalAnomaly(
            entity_name="CODEXCLI", entity_type="provider",
            time_group="2026-10-14T00:00:00.000Z", time_group_label="Wednesday",
            anomaly_value=86.31, normal_range_min=0.0, normal_range_max=45.11,
            z_score=2.5, severity_score=23.5, anomaly_type="entity_temporal",
            context="test", percentage_above_normal=376.6,
        )
        out = fmt(analyzer._format_temporal_results([spike], "SEVEN_DAYS", "normal", ["providers"]))
        assert "- **Cost multiplier**: 3.80" in out
        assert "with 3.8x normal cost levels" in out
        assert "| 282.7% |" in out

    def test_partly_read_and_unread_reports_are_named_in_the_answer(self, fmt):
        payload = {
            "period_analyzed": "SEVEN_DAYS",
            "sensitivity_used": "normal",
            "total_anomalies_detected": 0,
            "temporal_anomalies": [],
            "entities_analyzed": {"providers": 1},
            "dimensions_not_read": {"models": "HTTP 504: Gateway timeout"},
            "dimensions_incomplete": {
                "providers": "read 20 of 25 pages; buckets after 2026-10-13T23:59:59.999Z were not examined"
            },
        }
        out = fmt(payload)
        assert (
            "> ⚠️ Not read, so not examined for anomalies: models (HTTP 504: Gateway timeout)"
            in out
        )
        assert (
            "> ⚠️ Partly read: providers: read 20 of 25 pages; buckets after "
            "2026-10-13T23:59:59.999Z were not examined" in out
        )
        assert "- **models**: not read (HTTP 504: Gateway timeout)" in out
        assert "- **providers**: 1" in out

    def test_pipe_in_entity_name_is_escaped(self, fmt):
        payload = {
            "period_analyzed": "SEVEN_DAYS",
            "sensitivity_used": "normal",
            "total_anomalies_detected": 1,
            "temporal_anomalies": [
                {
                    "entity_name": "agent|with|pipes",
                    "entity_type": "ag|ent",
                    "time_group_label": "Mon|day",
                    "anomaly_value": 1.0,
                    "normal_range_min": 0.0,
                    "normal_range_max": 0.5,
                    "z_score": 3.0,
                    "severity_score": 1.0,
                    "percentage_above_normal": 100.0,
                },
            ],
        }
        out = fmt(payload)
        # Escaped pipes should NOT appear as bare table delimiters
        assert "agent\\|with\\|pipes" in out
        assert "ag\\|ent" in out
        assert "Mon\\|day" in out

    def test_new_entities_zero_does_not_render_empty_section(self, fmt):
        payload = {
            "period_analyzed": "SEVEN_DAYS",
            "sensitivity_used": "normal",
            "total_anomalies_detected": 0,
            "temporal_anomalies": [],
            "new_entities_detected": 0,
        }
        out = fmt(payload)
        assert "New Entities Detected" not in out

    def test_period_conversion_notice_emitted(self, fmt):
        payload = {
            "period_analyzed": "EIGHT_HOURS",
            "sensitivity_used": "normal",
            "total_anomalies_detected": 0,
            "temporal_anomalies": [],
            "period_conversion_notice": "Requested HOUR was widened to EIGHT_HOURS.",
        }
        out = fmt(payload)
        assert "> ⚠️ Requested HOUR was widened" in out

    def test_missing_keys_renders_gracefully(self, fmt):
        out = fmt({})
        assert "# Cost Anomaly Analysis — —" in out
        assert "**Total anomalies detected:** 0" in out
        assert "_No anomalies detected for the analyzed period._" in out


# ────────────────────────────────────────────────────────────────────────────
# _handle_unsupported_action and _handle_unimplemented_feature
# ────────────────────────────────────────────────────────────────────────────

class TestHandleUnsupportedActions:
    @pytest.mark.asyncio
    async def test_unsupported_action_message(self, tool):
        with pytest.raises(ToolError) as exc:
            await tool._handle_unsupported_action("mystery_action")
        assert "mystery_action" in exc.value.message
        assert "Not Supported" in exc.value.message



# ────────────────────────────────────────────────────────────────────────────
# Metadata provider methods
# ────────────────────────────────────────────────────────────────────────────

class TestMetadataProviderMethods:
    @pytest.mark.asyncio
    async def test_get_supported_actions_returns_list(self, tool):
        actions = await tool._get_supported_actions()
        assert "get_capabilities" in actions
        assert "analyze_cost_anomalies" in actions
        assert "get_cost_summary" in actions

    @pytest.mark.asyncio
    async def test_get_tool_capabilities_returns_list(self, tool):
        caps = await tool._get_tool_capabilities()
        assert len(caps) >= 2
        names = [c.name for c in caps]
        assert "Cost Analysis" in names
        assert "Anomaly Detection" in names

    @pytest.mark.asyncio
    async def test_tool_name_class_var(self, tool):
        assert tool.tool_name == "get_business_analytics"

    @pytest.mark.asyncio
    async def test_tool_version_class_var(self, tool):
        assert tool.tool_version == "1.0.0"


# ────────────────────────────────────────────────────────────────────────────
# _handle_get_unpaid_invoice_totals
# ────────────────────────────────────────────────────────────────────────────

class TestHandleGetUnpaidInvoiceTotals:
    @pytest.mark.asyncio
    async def test_success_renders_count_and_amount(self, tool):
        mock_client = MagicMock()
        mock_client.get_unpaid_invoice_totals = AsyncMock(
            return_value={"count": 3, "totalAmount": 1234.5}
        )
        tool.get_client = AsyncMock(return_value=mock_client)

        result = await tool._handle_get_unpaid_invoice_totals({})
        text = result[0].text
        assert "3" in text
        assert "1234.5" in text
        assert "Unpaid" in text

    @pytest.mark.asyncio
    async def test_zero_unpaid_renders_clean_state(self, tool):
        mock_client = MagicMock()
        mock_client.get_unpaid_invoice_totals = AsyncMock(
            return_value={"count": 0, "totalAmount": 0}
        )
        tool.get_client = AsyncMock(return_value=mock_client)

        result = await tool._handle_get_unpaid_invoice_totals({})
        text = result[0].text
        assert "0" in text
        assert "Unpaid" in text

    @pytest.mark.asyncio
    async def test_generic_exception_text(self, tool):
        mock_client = MagicMock()
        mock_client.get_unpaid_invoice_totals = AsyncMock(side_effect=Exception("down"))
        tool.get_client = AsyncMock(return_value=mock_client)

        with pytest.raises(ToolError) as exc:
            await tool._handle_get_unpaid_invoice_totals({})
        assert "Unpaid Invoice" in exc.value.message
        assert "Failed" in exc.value.message

    @pytest.mark.asyncio
    async def test_routed_via_handle_action(self, tool):
        mock_client = MagicMock()
        mock_client.get_unpaid_invoice_totals = AsyncMock(
            return_value={"count": 1, "totalAmount": 10}
        )
        tool.get_client = AsyncMock(return_value=mock_client)

        result = await tool.handle_action("get_unpaid_invoice_totals", {})
        assert "Unpaid" in result[0].text

    @pytest.mark.asyncio
    async def test_in_supported_actions(self, tool):
        actions = await tool._get_supported_actions()
        assert "get_unpaid_invoice_totals" in actions

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {"count": None, "totalAmount": None},
            {},
            {"count": "3", "totalAmount": "abc"},
            {"count": 3},
        ],
    )
    async def test_contract_failure_renders_error_not_zero_balance(self, tool, payload):
        """A partial/null/non-numeric response must render as an error, not a
        successful zero (or 'None') financial result."""
        mock_client = MagicMock()
        mock_client.get_unpaid_invoice_totals = AsyncMock(return_value=payload)
        tool.get_client = AsyncMock(return_value=mock_client)

        with pytest.raises(ToolError) as exc:
            await tool._handle_get_unpaid_invoice_totals({})
        text = exc.value.message
        assert "Failed" in text
        assert "None" not in text
        assert "Total outstanding**: 0" not in text

    @pytest.mark.asyncio
    async def test_structured_capabilities_include_action(self, tool):
        """ToolCapability-based discovery must advertise the action too."""
        caps = await tool._get_tool_capabilities()
        all_params = {k for c in caps for k in c.parameters}
        assert "get_unpaid_invoice_totals" in all_params


# ────────────────────────────────────────────────────────────────────────────
# BACK-2376 task / profitability / spend-mover analytics pack (10 actions)
# ────────────────────────────────────────────────────────────────────────────

# Aggregated-family rows (envelope B, flattened by the analyzer).
_AGG_ROWS = [
    {"group": "acme-corp", "label": "margin", "metricResult": 42.5, "metricType": "PERCENTAGE"},
    {"group": "globex", "label": "margin", "metricResult": 18.0, "metricType": "PERCENTAGE"},
]

_MOVER_ROWS = [
    {
        "group": "gpt-4o",
        "label": "cost",
        "metricResult": 120.0,
        "metricType": "MONEY",
        "currentValue": 120.0,
        "previousValue": 80.0,
        "trend": "UP",
    },
]

# Timeseries-family buckets (envelope A, flattened by the analyzer).
_TS_BUCKETS = [
    {
        "startTimestamp": "2026-07-01T00:00:00Z",
        "endTimestamp": "2026-07-02T00:00:00Z",
        "groups": [
            {"group": "code-review", "metrics": [{"label": "cost", "metricResult": 12.5}]},
        ],
    },
]

# Scatter-family data points (envelope C).
_SCATTER_POINTS = [
    {
        "transactionId": "tx-1",
        "agentName": "agent-a",
        "totalCost": 1.23,
        "totalCalls": 5,
        "distinctTools": 2,
    },
]


@patch(f"{_MOD}.SimpleCostAnalyzer")
class TestAnalyticsPackActions:
    """Success render, empty state, error text, routing for every pack action."""

    def _mock_method(self, mock_cls, method_name, return_value):
        instance = MagicMock()
        if isinstance(return_value, list):
            return_value = PackRows(return_value)
        setattr(instance, method_name, AsyncMock(return_value=return_value))
        mock_cls.return_value = instance
        return instance

    # ── get_task_costs ────────────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_task_costs_timeseries_success(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_task_costs", _TS_BUCKETS)
        result = await tool.handle_action("get_task_costs", {"period": "SEVEN_DAYS"})
        text = result[0].text
        assert "code-review" in text
        assert "12.5" in text

    @pytest.mark.asyncio
    async def test_task_costs_aggregated_success(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_task_costs", _AGG_ROWS)
        result = await tool.handle_action(
            "get_task_costs", {"period": "SEVEN_DAYS", "aggregation": "aggregated"}
        )
        assert "acme-corp" in result[0].text

    @pytest.mark.asyncio
    async def test_task_costs_empty_names_period(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_task_costs", [])
        result = await tool.handle_action("get_task_costs", {"period": "THIRTY_DAYS"})
        assert "THIRTY_DAYS" in result[0].text

    @pytest.mark.asyncio
    async def test_task_costs_error_text(self, mock_cls, tool):
        instance = MagicMock()
        instance.get_task_costs = AsyncMock(side_effect=Exception("boom"))
        mock_cls.return_value = instance
        with pytest.raises(ToolError) as exc:
            await tool.handle_action("get_task_costs", {"period": "SEVEN_DAYS"})
        assert "Failed" in exc.value.message

    @pytest.mark.asyncio
    async def test_single_metric_group_shows_the_value_alone(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_task_completion", [{
            "group": "Tasks Completed", "label": "Tasks Completed",
            "metricResult": 3457734, "metricType": "TASK_COMPLETION_AGGREGATED",
        }])
        result = await tool.handle_action(
            "get_task_completion", {"period": "SEVEN_DAYS", "aggregation": "aggregated"}
        )
        assert "- **Tasks Completed**: 3,457,734" in result[0].text.split("\n")

        self._mock_method(mock_cls, "get_vendor_costs", [{
            "group": "anthropic", "label": "anthropic",
            "metricResult": 2239.36, "metricType": "COST_METRIC_BY_VENDOR",
        }])
        result = await tool.handle_action("get_vendor_costs", {"period": "SEVEN_DAYS"})
        assert "- **anthropic**: $2,239.36" in result[0].text.split("\n")

        self._mock_method(mock_cls, "get_task_completion", [{
            "group": "code-review", "label": "completed",
            "metricResult": 12, "metricType": "TASK_COMPLETION_AGGREGATED",
        }])
        result = await tool.handle_action(
            "get_task_completion", {"period": "SEVEN_DAYS", "aggregation": "aggregated"}
        )
        assert "- **code-review**: completed 12" in result[0].text.split("\n")

    # ── get_task_completion ───────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_task_completion_success(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_task_completion", _TS_BUCKETS)
        result = await tool.handle_action("get_task_completion", {"period": "SEVEN_DAYS"})
        assert "code-review" in result[0].text

    @pytest.mark.asyncio
    async def test_task_completion_forwards_agents(self, mock_cls, tool):
        instance = self._mock_method(mock_cls, "get_task_completion", _TS_BUCKETS)
        await tool.handle_action(
            "get_task_completion", {"period": "SEVEN_DAYS", "agents": ["a1"]}
        )
        _args, kwargs = instance.get_task_completion.call_args
        assert kwargs.get("agents") == ["a1"]

    @pytest.mark.asyncio
    async def test_task_completion_empty(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_task_completion", [])
        result = await tool.handle_action("get_task_completion", {"period": "SEVEN_DAYS"})
        assert "SEVEN_DAYS" in result[0].text

    # ── get_task_performance ──────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_task_performance_success(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_task_performance_by_agent", _AGG_ROWS)
        result = await tool.handle_action("get_task_performance", {"period": "SEVEN_DAYS"})
        assert "acme-corp" in result[0].text

    @pytest.mark.asyncio
    async def test_task_performance_empty(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_task_performance_by_agent", [])
        result = await tool.handle_action("get_task_performance", {"period": "SEVEN_DAYS"})
        assert "SEVEN_DAYS" in result[0].text

    # ── get_profit_margins ────────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_profit_margins_default_customer(self, mock_cls, tool):
        instance = self._mock_method(mock_cls, "get_profit_margins", _AGG_ROWS)
        await tool.handle_action("get_profit_margins", {"period": "THIRTY_DAYS"})
        _args, kwargs = instance.get_profit_margins.call_args
        # dimension forwarded (positional or keyword); default is customer
        passed = kwargs.get("dimension") or (_args[1] if len(_args) > 1 else None)
        assert passed == "customer"

    @pytest.mark.asyncio
    async def test_profit_margins_product(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_profit_margins", _AGG_ROWS)
        result = await tool.handle_action(
            "get_profit_margins", {"period": "THIRTY_DAYS", "dimension": "product"}
        )
        assert "acme-corp" in result[0].text

    @pytest.mark.asyncio
    async def test_profit_margins_invalid_dimension_rejected(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_profit_margins", _AGG_ROWS)
        with pytest.raises(ToolError) as exc:
            await tool.handle_action(
                "get_profit_margins", {"period": "THIRTY_DAYS", "dimension": "bogus"}
            )
        text = exc.value.message
        assert "bogus" in text or "dimension" in text.lower()
        assert "customer" in text and "product" in text

    @pytest.mark.asyncio
    async def test_profit_margins_empty(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_profit_margins", [])
        result = await tool.handle_action("get_profit_margins", {"period": "SEVEN_DAYS"})
        assert "SEVEN_DAYS" in result[0].text

    # ── get_top_movers ────────────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_top_movers_success_shows_trend(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_top_movers", _MOVER_ROWS)
        result = await tool.handle_action("get_top_movers", {"period": "THIRTY_DAYS"})
        text = result[0].text
        assert "gpt-4o" in text
        assert "UP" in text

    @pytest.mark.asyncio
    async def test_top_movers_forwards_group_by(self, mock_cls, tool):
        instance = self._mock_method(mock_cls, "get_top_movers", _MOVER_ROWS)
        await tool.handle_action(
            "get_top_movers", {"period": "THIRTY_DAYS", "group_by": "agent"}
        )
        _args, kwargs = instance.get_top_movers.call_args
        assert kwargs.get("group_by") == "agent"

    @pytest.mark.asyncio
    async def test_top_movers_empty(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_top_movers", [])
        result = await tool.handle_action("get_top_movers", {"period": "SEVEN_DAYS"})
        assert "SEVEN_DAYS" in result[0].text

    # ── get_token_breakdown ───────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_token_breakdown_success(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_token_breakdown", _TS_BUCKETS)
        result = await tool.handle_action("get_token_breakdown", {"period": "SEVEN_DAYS"})
        assert "code-review" in result[0].text

    @pytest.mark.asyncio
    async def test_token_breakdown_forwards_providers(self, mock_cls, tool):
        instance = self._mock_method(mock_cls, "get_token_breakdown", _TS_BUCKETS)
        instance.get_analytics_filter_options = AsyncMock(return_value=["openai"])
        await tool.handle_action(
            "get_token_breakdown", {"period": "SEVEN_DAYS", "providers": ["openai"]}
        )
        _args, kwargs = instance.get_token_breakdown.call_args
        assert kwargs.get("providers") == ["openai"]

    @pytest.mark.asyncio
    async def test_token_breakdown_empty(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_token_breakdown", [])
        result = await tool.handle_action("get_token_breakdown", {"period": "SEVEN_DAYS"})
        assert "SEVEN_DAYS" in result[0].text

    # ── get_team_costs ────────────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_team_costs_success(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_team_costs", _TS_BUCKETS)
        result = await tool.handle_action("get_team_costs", {"period": "THIRTY_DAYS"})
        assert "code-review" in result[0].text

    @pytest.mark.asyncio
    async def test_team_costs_empty(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_team_costs", [])
        result = await tool.handle_action("get_team_costs", {"period": "THIRTY_DAYS"})
        assert "THIRTY_DAYS" in result[0].text

    # ── get_vendor_costs ──────────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_vendor_costs_success(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_vendor_costs", _AGG_ROWS)
        result = await tool.handle_action("get_vendor_costs", {"period": "SEVEN_DAYS"})
        assert "acme-corp" in result[0].text

    @pytest.mark.asyncio
    async def test_vendor_costs_empty(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_vendor_costs", [])
        result = await tool.handle_action("get_vendor_costs", {"period": "SEVEN_DAYS"})
        assert "SEVEN_DAYS" in result[0].text

    # ── get_token_vs_tool_cost ────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_token_vs_tool_cost_success(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_token_vs_tool_cost", _TS_BUCKETS)
        result = await tool.handle_action("get_token_vs_tool_cost", {"period": "THIRTY_DAYS"})
        assert "code-review" in result[0].text

    @pytest.mark.asyncio
    async def test_token_vs_tool_cost_empty(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_token_vs_tool_cost", [])
        result = await tool.handle_action("get_token_vs_tool_cost", {"period": "SEVEN_DAYS"})
        assert "SEVEN_DAYS" in result[0].text

    # ── get_trace_cost_distribution ───────────────────────────────────────
    @pytest.mark.asyncio
    async def test_trace_cost_distribution_success(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_trace_cost_distribution", _SCATTER_POINTS)
        result = await tool.handle_action("get_trace_cost_distribution", {"period": "SEVEN_DAYS"})
        text = result[0].text
        assert "tx-1" in text
        assert "agent-a" in text

    @pytest.mark.asyncio
    async def test_trace_cost_distribution_empty(self, mock_cls, tool):
        self._mock_method(mock_cls, "get_trace_cost_distribution", [])
        result = await tool.handle_action("get_trace_cost_distribution", {"period": "SEVEN_DAYS"})
        assert "SEVEN_DAYS" in result[0].text

    # ── overflow cap (>50 groups) ─────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_aggregated_render_caps_at_50_rows(self, mock_cls, tool):
        rows = [
            {"group": f"g{i}", "label": "m", "metricResult": float(i), "metricType": "MONEY"}
            for i in range(75)
        ]
        self._mock_method(mock_cls, "get_vendor_costs", rows)
        result = await tool.handle_action("get_vendor_costs", {"period": "SEVEN_DAYS"})
        text = result[0].text
        # 50 costliest rendered, costliest first, + overflow line naming the remaining 25
        bullets = [line for line in text.split("\n") if line.startswith("- **")]
        assert len(bullets) == 50
        assert bullets[0].startswith("- **g74**")
        assert "**g25**" in text
        assert "**g24**" not in text
        assert "25 more vendors not shown" in text

    @staticmethod
    def _task_rows(costs_and_runs):
        """Two platform-shaped rows per task: cost, then runs (None cost means no cost row)."""
        rows = []
        for name, cost, runs in costs_and_runs:
            if cost is not None:
                rows.append(
                    {"group": name, "label": name, "metricResult": cost, "metricType": "COST_METRIC_BY_TASK"}
                )
            rows.append({"group": name, "label": name, "metricResult": runs, "metricType": "runs"})
        return rows

    @pytest.mark.asyncio
    async def test_aggregated_task_costs_show_each_task_once_ranked_by_cost(self, mock_cls, tool):
        rows = self._task_rows(
            [
                ("01-charter", 2105.76, 19259),
                ("code-analysis", 9387.71, 500),
                ("unknown", 29731.13, 1000),
                ("zz-nocost", None, 40000),
            ]
        )
        self._mock_method(mock_cls, "get_task_costs", rows)
        result = await tool.handle_action(
            "get_task_costs", {"period": "SEVEN_DAYS", "aggregation": "aggregated"}
        )
        text = result[0].text
        bullets = [line for line in text.split("\n") if line.startswith("- **")]
        assert len(bullets) == 4
        assert [b.split("**")[1] for b in bullets] == [
            "unknown", "code-analysis", "01-charter", "zz-nocost",
        ]
        assert "- **unknown**: cost $29,731.13, runs 1,000" in text.split("\n")

    @pytest.mark.asyncio
    async def test_aggregated_overflow_counts_hidden_tasks_not_lines(self, mock_cls, tool):
        rows = self._task_rows([(f"t{i:02d}", float(i), 10) for i in range(60)])
        self._mock_method(mock_cls, "get_task_costs", rows)
        result = await tool.handle_action(
            "get_task_costs", {"period": "SEVEN_DAYS", "aggregation": "aggregated"}
        )
        text = result[0].text
        bullets = [line for line in text.split("\n") if line.startswith("- **")]
        assert len(bullets) == 50
        assert bullets[0].startswith("- **t59**")
        assert "10 more tasks not shown" in text
        assert "top 50 by cost" in text

    @pytest.mark.asyncio
    async def test_cost_ranked_list_without_any_cost_never_claims_a_top(self, mock_cls, tool):
        rows = [
            {"group": f"t{i:02d}", "label": f"t{i:02d}", "metricResult": 60 - i, "metricType": "runs"}
            for i in range(60)
        ]
        self._mock_method(mock_cls, "get_task_costs", rows)
        result = await tool.handle_action(
            "get_task_costs", {"period": "SEVEN_DAYS", "aggregation": "aggregated"}
        )
        text = result[0].text
        bullets = [line for line in text.split("\n") if line.startswith("- **")]
        assert bullets[0].startswith("- **t00**")
        assert "top" not in text.lower()
        assert "showing the first 50 in the platform's order" in text

    @pytest.mark.asyncio
    async def test_unranked_aggregated_list_never_claims_a_top(self, mock_cls, tool):
        rows = [
            {"group": f"g{i}", "label": f"g{i}", "metricResult": float(60 - i), "metricType": "COUNT"}
            for i in range(60)
        ]
        self._mock_method(mock_cls, "get_task_completion", rows)
        result = await tool.handle_action(
            "get_task_completion", {"period": "SEVEN_DAYS", "aggregation": "aggregated"}
        )
        text = result[0].text
        assert "top" not in text.lower()
        assert "showing the first 50" in text
        bullets = [line for line in text.split("\n") if line.startswith("- **")]
        assert bullets[0].startswith("- **g0**")

    @pytest.mark.asyncio
    async def test_top_movers_keep_platform_order(self, mock_cls, tool):
        movers = [
            {
                "group": name,
                "label": "cost",
                "metricResult": value,
                "metricType": "MONEY",
                "currentValue": value,
                "previousValue": 1.0,
                "trend": "UP",
            }
            for name, value in (("small", 10.0), ("large", 500.0))
        ]
        self._mock_method(mock_cls, "get_top_movers", movers)
        result = await tool.handle_action("get_top_movers", {"period": "THIRTY_DAYS"})
        bullets = [line for line in result[0].text.split("\n") if line.startswith("- **")]
        assert bullets[0].startswith("- **small**")
        assert bullets[1].startswith("- **large**")

    @pytest.mark.asyncio
    async def test_scatter_points_never_claim_a_top(self, mock_cls, tool):
        points = [
            {
                "transactionId": f"tx-{i}",
                "agentName": "agent-a",
                "totalCost": float(i),
                "totalCalls": 5,
                "distinctTools": 2,
            }
            for i in range(60)
        ]
        self._mock_method(mock_cls, "get_trace_cost_distribution", points)
        result = await tool.handle_action("get_trace_cost_distribution", {"period": "SEVEN_DAYS"})
        text = result[0].text
        assert "10 more traces not shown" in text
        assert "top" not in text.lower()

    # ── AuthenticationError re-raise ──────────────────────────────────────
    @pytest.mark.asyncio
    async def test_authentication_error_reraised(self, mock_cls, tool):
        from src.revenium_mcp_server.auth import AuthenticationError as AuthErr

        instance = MagicMock()
        instance.get_vendor_costs = AsyncMock(side_effect=AuthErr("bad auth"))
        mock_cls.return_value = instance
        with pytest.raises((AuthErr, ToolError)):
            await tool.handle_action("get_vendor_costs", {"period": "SEVEN_DAYS"})


class TestAnalyticsPackDiscovery:
    """Supported-actions membership and structured-capabilities completeness."""

    _PACK_ACTIONS = [
        "get_task_costs",
        "get_task_completion",
        "get_task_performance",
        "get_profit_margins",
        "get_top_movers",
        "get_token_breakdown",
        "get_team_costs",
        "get_vendor_costs",
        "get_token_vs_tool_cost",
        "get_trace_cost_distribution",
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", _PACK_ACTIONS)
    async def test_action_in_supported_actions(self, tool, action):
        actions = await tool._get_supported_actions()
        assert action in actions

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", _PACK_ACTIONS)
    async def test_action_in_structured_capabilities(self, tool, action):
        caps = await tool._get_tool_capabilities()
        all_params = {k for c in caps for k in c.parameters}
        assert action in all_params

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", _PACK_ACTIONS)
    async def test_action_in_examples(self, tool, action):
        result = await tool._handle_get_examples({})
        assert action in result[0].text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", _PACK_ACTIONS)
    async def test_action_in_tool_description(self, tool, action):
        assert action in tool.tool_description


class TestAnalyticsPackRenderingHardening:
    """Review hardening: honest None, atomic buckets, per-line cap, labels."""

    def test_format_metric_value_none_is_na(self, tool):
        assert tool._format_metric_value(None, "MONEY") == "n/a"
        assert tool._format_metric_value(None, None) == "n/a"

    def test_scatter_missing_cost_renders_na(self, tool):
        text = tool._render_scatter_points(
            PackRows([{"transactionId": "t1", "agentName": "a", "totalCalls": 1, "distinctTools": 1}]),
            period="SEVEN_DAYS",
        )
        assert "n/a" in text
        assert "None" not in text

    def test_timeseries_renders_one_line_per_bucket_with_its_groups_side_by_side(self, tool):
        buckets = [
            {
                "startTimestamp": "2026-07-01T00:00:00.000Z",
                "endTimestamp": "2026-07-01T23:59:59.999Z",
                "groups": [
                    {"group": f"g{i}", "metrics": [
                        {"label": f"m{j}", "metricResult": 1.0, "metricType": None}
                        for j in range(10)
                    ]}
                    for i in range(10)
                ],
            }
        ]
        text = tool._render_timeseries_buckets(PackRows(buckets), title="T", period="SEVEN_DAYS")
        bucket_lines = [line for line in text.split("\n") if line.startswith("- ")]
        assert bucket_lines == [bucket_lines[0]]
        assert bucket_lines[0].startswith("- **2026-07-01**: g0 (m0) 1, ")
        assert bucket_lines[0].count(", ") == 99

    def test_hourly_buckets_keep_their_times(self, tool):
        """FRONT-3434: an EIGHT_HOURS series has several buckets on one date, so a
        date-only label would hide which hour each figure belongs to."""
        buckets = [
            {
                "startTimestamp": f"2026-10-09T{hour:02d}:00:00.000Z",
                "endTimestamp": f"2026-10-09T{hour:02d}:59:59.999Z",
                "groups": [{"group": "team-a", "metrics": [{"label": "team-a", "metricResult": 1.0}]}],
            }
            for hour in (10, 11, 12)
        ]
        text = tool._render_timeseries_buckets(PackRows(buckets), title="T", period="EIGHT_HOURS")
        bucket_lines = [line for line in text.split("\n") if line.startswith("- ")]

        assert len(bucket_lines) == 3
        assert bucket_lines[0].startswith(
            "- **2026-10-09T10:00:00.000Z → 2026-10-09T10:59:59.999Z**: team-a"
        )
        assert "- **2026-10-09**:" not in text

    def test_timeseries_cap_counts_buckets(self, tool):
        buckets = [
            {"startTimestamp": f"day-{d}", "endTimestamp": f"day-{d}-end", "groups": []}
            for d in range(tool._MAX_RENDERED_BUCKETS + 3)
        ]
        text = tool._render_timeseries_buckets(PackRows(buckets), title="T", period="TWELVE_MONTHS")
        bucket_lines = [line for line in text.split("\n") if line.startswith("- ")]
        assert len(bucket_lines) == tool._MAX_RENDERED_BUCKETS
        assert "…and 3 more buckets not shown" in text

    def test_timeseries_leaves_out_zero_entries_and_says_so(self, tool):
        def group(name, value):
            return {
                "group": name,
                "metrics": [{"label": name, "metricResult": value, "metricType": "MONEY"}],
            }

        buckets = [
            {
                "startTimestamp": "2026-07-01T00:00:00.000Z",
                "endTimestamp": "2026-07-01T23:59:59.999Z",
                "groups": [group("a", 1.5), group("b", 0.0), group("c", 0), group("d", 0.004)],
            }
        ]
        text = tool._render_timeseries_buckets(PackRows(buckets), title="T", period="SEVEN_DAYS")
        lines = text.split("\n")
        assert "- **2026-07-01**: a $1.50, d $0.004" in lines
        assert "_Entries at zero are left out._" in text

    def test_timeseries_bucket_of_only_zeros_is_not_called_no_data(self, tool):
        buckets = [
            {
                "startTimestamp": "2026-07-01T00:00:00.000Z",
                "endTimestamp": "2026-07-01T23:59:59.999Z",
                "groups": [
                    {"group": "a", "metrics": [{"label": "a", "metricResult": 0.0, "metricType": "MONEY"}]}
                ],
            },
            {
                "startTimestamp": "2026-07-02T00:00:00.000Z",
                "endTimestamp": "2026-07-02T23:59:59.999Z",
                "groups": [],
            },
        ]
        text = tool._render_timeseries_buckets(PackRows(buckets), title="T", period="SEVEN_DAYS")
        bucket_lines = [line for line in text.split("\n") if line.startswith("- ")]
        assert bucket_lines[0].endswith("nothing above zero")
        assert bucket_lines[1].endswith("no data")

    def test_aggregated_row_includes_label_when_distinct(self, tool):
        text = tool._render_aggregated_rows(
            PackRows([{"group": "Engineering", "label": "profit margin", "metricResult": 12.5, "metricType": "PERCENTAGE"}]),
            title="T", period="SEVEN_DAYS", value_noun="rows",
        )
        assert "profit margin" in text

    def test_renderer_survives_malformed_metric_value(self, tool):
        """Contract failure: a non-numeric metricResult renders via the safe
        string path — no crash, no fabricated number."""
        text = tool._render_aggregated_rows(
            PackRows([{"group": "openai", "metricResult": "not-a-number", "metricType": "MONEY"}]),
            title="T", period="SEVEN_DAYS", value_noun="rows",
        )
        assert "not-a-number" in text

    @pytest.mark.asyncio
    async def test_pack_handler_survives_malformed_analyzer_rows(self, tool):
        """The handler path renders malformed analyzer rows without crashing."""
        mock_analyzer = MagicMock()
        mock_analyzer.get_vendor_costs = AsyncMock(return_value=PackRows([
            {"group": "openai", "metricResult": "not-a-number", "metricType": "MONEY"},
            {"group": "anthropic", "metricResult": None, "metricType": "MONEY"},
        ]))
        with patch(f"{_MOD}.SimpleCostAnalyzer", return_value=mock_analyzer):
            result = await tool._handle_get_vendor_costs({"period": "SEVEN_DAYS"})
        text = result[0].text
        assert "openai" in text
        assert "n/a" in text

    def test_capabilities_list_names_all_pack_actions(self, tool):
        """The get_capabilities Available Actions markdown names every pack
        action — the discovery surface must not lag the implementation."""
        import asyncio
        result = asyncio.run(tool._handle_get_capabilities())
        text = result[0].text
        for action in (
            "get_task_costs", "get_task_completion", "get_task_performance",
            "get_profit_margins", "get_top_movers", "get_token_breakdown",
            "get_team_costs", "get_vendor_costs", "get_token_vs_tool_cost",
            "get_trace_cost_distribution",
        ):
            assert action in text, f"missing from capabilities list: {action}"


# get_filter_options
# ────────────────────────────────────────────────────────────────────────────

@patch(f"{_MOD}.SimpleAnalyticsEngine")
class TestHandleGetFilterOptions:
    @pytest.mark.asyncio
    async def test_success_renders_sorted_values_and_guidance(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_filter_options = AsyncMock(
            return_value=("**Filter Options: models**\n\n- gpt-4o\n"
                          "\nUse these values in the corresponding filter arguments "
                          "(e.g. filters.agents on get_user_costs).")
        )
        result = await tool._handle_get_filter_options({"dimension": "models"})
        text = result[0].text
        assert "gpt-4o" in text
        assert "filters.agents" in text

    @pytest.mark.asyncio
    async def test_engine_created_per_request(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_filter_options = AsyncMock(return_value="ok")
        await tool._handle_get_filter_options({"dimension": "models"})
        await tool._handle_get_filter_options({"dimension": "agents"})
        assert mock_engine_cls.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_values_still_returns_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_filter_options = AsyncMock(
            return_value="**Filter Options: models**\n\nNo values found."
        )
        result = await tool._handle_get_filter_options({"dimension": "models"})
        assert "No values" in result[0].text

    @pytest.mark.asyncio
    async def test_invalid_dimension_raises_validation_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_filter_options = AsyncMock(
            side_effect=ValidationError(
                "Unknown filter dimension: 'widgets'",
                field="dimension",
                suggestions=["Valid dimensions: agents, api-keys, models"],
            )
        )
        with pytest.raises(ToolError) as exc:
            await tool._handle_get_filter_options({"dimension": "widgets"})
        text = exc.value.message
        assert "Validation Error" in text
        assert "widgets" in text
        assert "agents, api-keys, models" in text

    @pytest.mark.asyncio
    async def test_authentication_error_reraised(self, mock_engine_cls, tool):
        from src.revenium_mcp_server.auth import AuthenticationError
        mock_engine_cls.return_value.get_filter_options = AsyncMock(
            side_effect=AuthenticationError("no creds")
        )
        with pytest.raises(AuthenticationError):
            await tool._handle_get_filter_options({"dimension": "models"})

    @pytest.mark.asyncio
    async def test_generic_exception_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_filter_options = AsyncMock(
            side_effect=RuntimeError("down")
        )
        with pytest.raises(ToolError) as exc:
            await tool._handle_get_filter_options({"dimension": "models"})
        assert "Failed" in exc.value.message

    @pytest.mark.asyncio
    async def test_routed_via_handle_action(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_filter_options = AsyncMock(return_value="routed")
        result = await tool.handle_action("get_filter_options", {"dimension": "models"})
        assert result[0].text == "routed"

    @pytest.mark.asyncio
    async def test_in_supported_actions(self, mock_engine_cls, tool):
        actions = await tool._get_supported_actions()
        assert "get_filter_options" in actions

    @pytest.mark.asyncio
    async def test_structured_capabilities_include_action_and_dimension(self, mock_engine_cls, tool):
        """Structured discovery must advertise the action and its dimension param."""
        caps = await tool._get_tool_capabilities()
        params_for_action = None
        for c in caps:
            if "get_filter_options" in c.parameters:
                params_for_action = c.parameters["get_filter_options"]
                break
        assert params_for_action is not None
        assert "dimension" in params_for_action


# ────────────────────────────────────────────────────────────────────────────
# list_invoices
# ────────────────────────────────────────────────────────────────────────────

_INVOICE = {
    "invoiceNumber": "INV-001",
    "state": "FINALIZED",
    "invoicePayStatus": "UNPAID",
    "totalAmount": 1234.5,
    "totalPaidAmount": None,
    "currency": "USD",
    "startDate": "2026-01-01",
    "endDate": "2026-01-31",
}


class TestHandleListInvoices:
    def _client(self, items, page=None):
        c = MagicMock()
        response = {"_embedded": {"invoiceResourceList": items}}
        if page is not None:
            response["page"] = page
        c.get_invoices = AsyncMock(return_value=response)
        c._extract_embedded_data = MagicMock(return_value=items)
        return c

    @pytest.mark.asyncio
    async def test_success_renders_compact_line(self, tool):
        tool.get_client = AsyncMock(return_value=self._client([_INVOICE]))
        result = await tool._handle_list_invoices({})
        text = result[0].text
        assert "INV-001" in text
        assert "FINALIZED" in text
        assert "UNPAID" in text
        # money: two decimals, currency code printed (no symbol)
        assert "1234.50 USD" in text
        assert "$" not in text
        # period rendered
        assert "2026-01-01" in text
        assert "2026-01-31" in text

    @pytest.mark.asyncio
    async def test_null_total_renders_na_not_zero(self, tool):
        item = dict(_INVOICE)
        item["totalAmount"] = None
        tool.get_client = AsyncMock(return_value=self._client([item]))
        result = await tool._handle_list_invoices({})
        text = result[0].text
        assert "n/a" in text
        # must not fabricate a zero balance for a missing amount
        assert "0 USD" not in text
        assert "None" not in text

    @pytest.mark.asyncio
    async def test_non_numeric_total_renders_na(self, tool):
        item = dict(_INVOICE)
        item["totalAmount"] = "abc"
        tool.get_client = AsyncMock(return_value=self._client([item]))
        result = await tool._handle_list_invoices({})
        assert "n/a" in result[0].text

    @pytest.mark.asyncio
    async def test_empty_state_message(self, tool):
        tool.get_client = AsyncMock(return_value=self._client([]))
        result = await tool._handle_list_invoices({})
        assert "No invoices" in result[0].text

    @pytest.mark.asyncio
    async def test_filter_mapping_snake_to_camel(self, tool):
        client = self._client([])
        tool.get_client = AsyncMock(return_value=client)
        await tool._handle_list_invoices(
            {
                "invoice_number": "INV-9",
                "start_date": "2026-01-01",
                "end_date": "2026-02-01",
                "pay_states": ["UNPAID"],
                "states": ["FINALIZED"],
                "starting_amount": 10,
                "ending_amount": 100,
                "page": 1,
                "size": 5,
            }
        )
        kwargs = client.get_invoices.call_args.kwargs
        assert kwargs["page"] == 1
        assert kwargs["size"] == 5
        assert kwargs["invoiceNumber"] == "INV-9"
        assert kwargs["startDate"] == "2026-01-01T00:00:00.000Z"
        assert kwargs["endDate"] == "2026-02-01T23:59:59.999Z"
        assert kwargs["payStates"] == ["UNPAID"]
        assert kwargs["states"] == ["FINALIZED"]
        assert kwargs["startingAmount"] == 10
        assert kwargs["endingAmount"] == 100
        # reserved keys must not leak into the filter mapping
        assert "page" not in {"invoiceNumber", "startDate"}

    @pytest.mark.asyncio
    async def test_unknown_filter_keys_not_forwarded(self, tool):
        client = self._client([])
        tool.get_client = AsyncMock(return_value=client)
        with pytest.raises(ToolError) as refusal:
            await tool._handle_list_invoices({"bogus": "x", "action": "list_invoices"})
        assert refusal.value.field == "bogus"
        client.get_invoices.assert_not_awaited()

        await tool._handle_list_invoices({"action": "list_invoices"})
        kwargs = client.get_invoices.call_args.kwargs
        assert "action" not in kwargs

    @pytest.mark.asyncio
    async def test_every_row_of_a_full_page_is_printed_with_the_total_and_next_page(self, tool):
        """size=100 printed 50 rows while page 1 starts at row 101, so rows
        51 to 100 could never be reached."""
        items = [dict(_INVOICE, invoiceNumber=f"INV-{i}") for i in range(100)]
        page = {"number": 0, "size": 100, "totalElements": 148138, "totalPages": 1482}
        tool.get_client = AsyncMock(return_value=self._client(items, page=page))
        result = await tool._handle_list_invoices({"size": 100})
        text = result[0].text
        assert "INV-50 " in text
        assert "INV-99 " in text
        assert "more not shown" not in text
        assert "Page 1 of 1482, 148138 invoices in all." in text
        assert "Pass page=1 size=100 for the next page." in text

    @pytest.mark.asyncio
    async def test_last_page_has_no_next_page_call(self, tool):
        page = {"number": 1481, "size": 100, "totalElements": 148138, "totalPages": 1482}
        tool.get_client = AsyncMock(return_value=self._client([_INVOICE], page=page))
        result = await tool._handle_list_invoices({"page": 1481, "size": 100})
        text = result[0].text
        assert "Page 1482 of 1482" in text
        assert "for the next page" not in text

    @pytest.mark.asyncio
    async def test_page_past_the_last_names_the_total(self, tool):
        page = {"number": 2000, "size": 100, "totalElements": 148138, "totalPages": 1482}
        tool.get_client = AsyncMock(return_value=self._client([], page=page))
        result = await tool._handle_list_invoices({"page": 2000, "size": 100})
        text = result[0].text
        assert "148138 invoices" in text
        assert "past the last" in text
        assert "No invoices found" not in text

    @pytest.mark.asyncio
    async def test_generic_exception_text(self, tool):
        client = MagicMock()
        client.get_invoices = AsyncMock(side_effect=Exception("boom"))
        tool.get_client = AsyncMock(return_value=client)
        with pytest.raises(ToolError) as exc:
            await tool._handle_list_invoices({})
        assert "Failed" in exc.value.message

    @pytest.mark.asyncio
    async def test_routed_via_handle_action(self, tool):
        tool.get_client = AsyncMock(return_value=self._client([_INVOICE]))
        result = await tool.handle_action("list_invoices", {})
        assert "INV-001" in result[0].text

    @pytest.mark.asyncio
    async def test_in_supported_actions(self, tool):
        assert "list_invoices" in await tool._get_supported_actions()

    @pytest.mark.asyncio
    async def test_in_structured_capabilities(self, tool):
        caps = await tool._get_tool_capabilities()
        all_params = {k for c in caps for k in c.parameters}
        assert "list_invoices" in all_params


# ────────────────────────────────────────────────────────────────────────────
# list_refunds
# ────────────────────────────────────────────────────────────────────────────

_REFUND = {
    "id": "3kTMd",
    "amount": 125.5,
    "currency": "USD",
    "issuedDate": "2024-09-30T23:59:59Z",
    "timestamp": "2024-09-15T12:00:00Z",
    "created": "2024-09-01T00:00:00Z",
    "label": "r-label",
    "product": {"id": "p1", "label": "revvie-sdlc"},
    "invoice": None,
}


class TestHandleListRefunds:
    def _client(self, items, page=None):
        c = MagicMock()
        response = {"_embedded": {"refundResourceList": items}}
        if page is not None:
            response["page"] = page
        c.get_refunds = AsyncMock(return_value=response)
        c._extract_embedded_data = MagicMock(return_value=items)
        return c

    @pytest.mark.asyncio
    async def test_refund_schema_fields_render_amount_issued_date_and_product(self, tool):
        """A refund (RefundResource_Read) has amount, timestamp (when it was
        issued), issuedDate (when it was applied to an invoice) and product,
        not the invoice's totalAmount; no state column exists to print as n/a."""
        tool.get_client = AsyncMock(return_value=self._client([_REFUND]))
        result = await tool._handle_list_refunds({})
        text = result[0].text
        assert (
            "- 3kTMd | 125.50 USD | issued 2024-09-15T12:00:00Z"
            " | applied 2024-09-30T23:59:59Z | revvie-sdlc"
        ) in text
        assert "2024-09-01" not in text
        assert "r-label" not in text
        assert "n/a" not in text

    @pytest.mark.asyncio
    async def test_empty_state_message(self, tool):
        tool.get_client = AsyncMock(return_value=self._client([]))
        result = await tool._handle_list_refunds({})
        assert "No refunds" in result[0].text

    @pytest.mark.asyncio
    async def test_success_renders_amount_with_currency(self, tool):
        refund = {"id": "r1", "amount": 25, "currency": "USD"}
        tool.get_client = AsyncMock(return_value=self._client([refund]))
        result = await tool._handle_list_refunds({})
        text = result[0].text
        assert "25.00 USD" in text
        assert "$" not in text

    @pytest.mark.asyncio
    async def test_null_amount_renders_na(self, tool):
        refund = {"id": "r1", "amount": None, "currency": "USD"}
        tool.get_client = AsyncMock(return_value=self._client([refund]))
        result = await tool._handle_list_refunds({})
        text = result[0].text
        assert "- r1 | n/a | issued n/a | applied n/a | n/a" in text
        assert " 0 USD" not in text
        assert "0.0 USD" not in text
        assert "None" not in text

    @pytest.mark.asyncio
    async def test_every_row_of_a_full_page_is_printed_with_the_total(self, tool):
        items = [dict(_REFUND, id=f"r{i}") for i in range(60)]
        page = {"number": 0, "size": 60, "totalElements": 61, "totalPages": 2}
        tool.get_client = AsyncMock(return_value=self._client(items, page=page))
        result = await tool._handle_list_refunds({"size": 60})
        text = result[0].text
        assert "- r59 |" in text
        assert "61 refunds in all." in text

    @pytest.mark.asyncio
    async def test_filter_mapping(self, tool):
        client = self._client([])
        tool.get_client = AsyncMock(return_value=client)
        await tool._handle_list_refunds(
            {
                "query": "acme",
                "start_date": "2026-01-01",
                "end_date": "2026-02-01",
                "minimum": 5,
                "maximum": 50,
                "page": 2,
                "size": 3,
            }
        )
        kwargs = client.get_refunds.call_args.kwargs
        assert kwargs["page"] == 2
        assert kwargs["size"] == 3
        assert kwargs["query"] == "acme"
        assert kwargs["startDate"] == "2026-01-01T00:00:00.000Z"
        assert kwargs["endDate"] == "2026-02-01T23:59:59.999Z"
        assert kwargs["minimum"] == 5
        assert kwargs["maximum"] == 50

    @pytest.mark.asyncio
    async def test_generic_exception_text(self, tool):
        client = MagicMock()
        client.get_refunds = AsyncMock(side_effect=Exception("boom"))
        tool.get_client = AsyncMock(return_value=client)
        with pytest.raises(ToolError) as exc:
            await tool._handle_list_refunds({})
        assert "Failed" in exc.value.message

    @pytest.mark.asyncio
    async def test_routed_via_handle_action(self, tool):
        tool.get_client = AsyncMock(return_value=self._client([]))
        result = await tool.handle_action("list_refunds", {})
        assert "refunds" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_in_supported_actions(self, tool):
        assert "list_refunds" in await tool._get_supported_actions()


# ────────────────────────────────────────────────────────────────────────────
# list_period_charges — cursor/keyset pagination
# ────────────────────────────────────────────────────────────────────────────

class TestHandleListPeriodCharges:
    def _client(self, items, has_more=False, cursor=None):
        c = MagicMock()
        c.get_period_charges = AsyncMock(
            return_value={
                "_embedded": {"periodChargeResourceList": items},
                "hasMore": has_more,
                "cursor": cursor,
            }
        )
        c._extract_embedded_data = MagicMock(return_value=items)
        return c

    @pytest.mark.asyncio
    async def test_success_renders_entries(self, tool):
        charge = {
            "id": "pc_1",
            "label": "tx_9",
            "transactionId": "tx_9",
            "charge": 1.5,
            "currency": "USD",
            "callCount": 3,
            "type": "TRANSACTIONAL",
            "chargeType": "CALL_COUNT_TRANSACTIONAL_CHARGE",
            "product": {"id": "p1", "label": "API calls"},
        }
        tool.get_client = AsyncMock(return_value=self._client([charge]))
        result = await tool._handle_list_period_charges({})
        text = result[0].text
        assert "pc_1" in text
        assert "1.50 USD" in text
        assert "3 calls" in text
        assert "API calls" in text

    @pytest.mark.asyncio
    async def test_line_shows_charge_calls_type_product_and_transaction_once(self, tool):
        """The platform record holds the charge, currency, call count, both
        types and the product; label repeats the transaction id."""
        charge = {
            "id": "Nj1ABBX",
            "label": "d8a2e6d6-c8ee-48d7-851f-6d81d1ccc27d",
            "charge": 0.2,
            "currency": "USD",
            "callCount": 1,
            "type": "TRANSACTIONAL",
            "chargeType": "CALL_COUNT_TRANSACTIONAL_CHARGE",
            "resource": "tool:x:y",
            "transactionId": "d8a2e6d6-c8ee-48d7-851f-6d81d1ccc27d",
            "created": "2026-10-15T17:14:27.045Z",
            "product": {"id": "p1", "label": "revvie-sdlc"},
        }
        tool.get_client = AsyncMock(return_value=self._client([charge]))
        result = await tool._handle_list_period_charges({})
        text = result[0].text
        assert (
            "- Nj1ABBX | 0.20 USD | 1 call | TRANSACTIONAL / CALL_COUNT_TRANSACTIONAL_CHARGE"
            " | revvie-sdlc | tx=d8a2e6d6-c8ee-48d7-851f-6d81d1ccc27d | 2026-10-15T17:14:27.045Z"
        ) in text
        assert text.count("d8a2e6d6-c8ee-48d7-851f-6d81d1ccc27d") == 1
        assert "tool:x:y" not in text

    @pytest.mark.asyncio
    async def test_sub_cent_charge_is_not_rendered_as_zero(self, tool):
        charge = {"id": "pc_1", "transactionId": "tx_9", "charge": 0.004, "currency": "USD"}
        tool.get_client = AsyncMock(return_value=self._client([charge]))
        result = await tool._handle_list_period_charges({})
        text = result[0].text
        assert "0.004 USD" in text
        assert "0 USD" not in text
        assert "0.00 USD" not in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "amount,shown,hidden",
        [
            (0.23200000000000004, "| 0.232 USD |", "0.23200000000000004"),
            (0.7999999999999999, "| 0.80 USD |", "0.7999"),
            (1e-12, "| 0.000000000001 USD |", "0.00 USD"),
            (1234.56789012345, "| 1234.56789 USD |", "1234.567890 USD"),
            (0.534666666666667, "| 0.534667 USD |", "0.5346666"),
            (0.0000015, "| 0.0000015 USD |", "0.000002 USD"),
        ],
    )
    async def test_float_noise_in_a_charge_is_not_printed(self, tool, amount, shown, hidden):
        charge = {"id": "EY199xX", "transactionId": "tx_9", "charge": amount, "currency": "USD"}
        tool.get_client = AsyncMock(return_value=self._client([charge]))
        text = (await tool._handle_list_period_charges({}))[0].text
        assert shown in text
        assert hidden not in text

    @pytest.mark.asyncio
    async def test_missing_charge_and_product_render_na_not_zero(self, tool):
        """A missing charge, call count, type or product is n/a in its own
        column, never a zero."""
        charge = {"id": "pc_1", "transactionId": "tx_9", "charge": None, "currency": "USD"}
        tool.get_client = AsyncMock(return_value=self._client([charge]))
        result = await tool._handle_list_period_charges({})
        text = result[0].text
        assert "- pc_1 | n/a | n/a calls | n/a / n/a | n/a | tx=tx_9 | n/a" in text
        assert " 0 USD" not in text
        assert "0.0 USD" not in text
        assert "None" not in text

    @pytest.mark.asyncio
    async def test_charge_below_a_billionth_is_not_rendered_as_zero(self, tool):
        charge = {"id": "pc_1", "transactionId": "tx_9", "charge": 0.0000000005, "currency": "USD"}
        tool.get_client = AsyncMock(return_value=self._client([charge]))
        result = await tool._handle_list_period_charges({})
        text = result[0].text
        assert "0.0000000005 USD" in text
        assert "0.00 USD" not in text

    @pytest.mark.asyncio
    async def test_empty_state_message(self, tool):
        tool.get_client = AsyncMock(return_value=self._client([]))
        result = await tool._handle_list_period_charges({})
        assert "No period charges" in result[0].text

    @pytest.mark.asyncio
    async def test_cursor_continuation_line_when_has_more(self, tool):
        charge = {"id": "pc_1", "label": "x"}
        tool.get_client = AsyncMock(
            return_value=self._client([charge], has_more=True, cursor="NEXT-CUR")
        )
        result = await tool._handle_list_period_charges({})
        text = result[0].text
        assert "More available" in text
        assert "cursor='NEXT-CUR'" in text

    @pytest.mark.asyncio
    async def test_every_row_of_the_page_is_printed_before_the_cursor_line(self, tool):
        charges = [{"id": f"pc_{i}", "transactionId": f"tx_{i}"} for i in range(60)]
        tool.get_client = AsyncMock(
            return_value=self._client(charges, has_more=True, cursor="NEXT")
        )
        result = await tool._handle_list_period_charges({"size": 60})
        text = result[0].text
        assert "- pc_59 |" in text
        assert "not shown" not in text
        assert "cursor='NEXT'" in text

    @pytest.mark.asyncio
    async def test_no_continuation_line_when_not_has_more(self, tool):
        charge = {"id": "pc_1", "label": "x"}
        tool.get_client = AsyncMock(
            return_value=self._client([charge], has_more=False, cursor="X")
        )
        result = await tool._handle_list_period_charges({})
        assert "More available" not in result[0].text

    @pytest.mark.asyncio
    async def test_never_sends_page_and_maps_filters(self, tool):
        client = self._client([])
        tool.get_client = AsyncMock(return_value=client)
        await tool._handle_list_period_charges(
            {
                "invoice_id": "inv_1",
                "start_date": "2026-01-01",
                "end_date": "2026-02-01",
                "cursor": "CUR-1",
                "size": 7,
                "page": 0,  # the first page is accepted, never forwarded
            }
        )
        kwargs = client.get_period_charges.call_args.kwargs
        assert kwargs["size"] == 7
        assert kwargs["invoiceId"] == "inv_1"
        assert kwargs["startDate"] == "2026-01-01T00:00:00.000Z"
        assert kwargs["endDate"] == "2026-02-01T23:59:59.999Z"
        assert kwargs["cursor"] == "CUR-1"
        assert "page" not in kwargs

    @pytest.mark.asyncio
    async def test_generic_exception_text(self, tool):
        client = MagicMock()
        client.get_period_charges = AsyncMock(side_effect=Exception("boom"))
        tool.get_client = AsyncMock(return_value=client)
        with pytest.raises(ToolError) as exc:
            await tool._handle_list_period_charges({})
        assert "Failed" in exc.value.message

    @pytest.mark.asyncio
    async def test_routed_via_handle_action(self, tool):
        charge = {"id": "pc_1", "label": "x"}
        tool.get_client = AsyncMock(return_value=self._client([charge]))
        result = await tool.handle_action("list_period_charges", {})
        assert "pc_1" in result[0].text

    @pytest.mark.asyncio
    async def test_in_supported_actions(self, tool):
        assert "list_period_charges" in await tool._get_supported_actions()


class TestBillingReadDiscoveryMembership:
    @pytest.mark.asyncio
    async def test_all_three_in_supported_actions(self, tool):
        actions = await tool._get_supported_actions()
        for a in ("list_invoices", "list_refunds", "list_period_charges"):
            assert a in actions

    @pytest.mark.asyncio
    async def test_all_three_in_structured_capabilities(self, tool):
        caps = await tool._get_tool_capabilities()
        all_params = {k for c in caps for k in c.parameters}
        for a in ("list_invoices", "list_refunds", "list_period_charges"):
            assert a in all_params

class TestBillingReadsNullHonesty:
    """Live-found: real invoices carry endDate: null (key present) — the
    .get(key, default) pattern misses explicit nulls and rendered 'None'."""

    @pytest.mark.asyncio
    async def test_invoice_null_fields_render_na(self, tool):
        mock_client = MagicMock()
        mock_client.get_invoices = AsyncMock(return_value={"_embedded": {}})
        mock_client._extract_embedded_data = MagicMock(return_value=[{
            "invoiceNumber": "X-1", "state": None, "invoicePayStatus": None,
            "totalAmount": 0, "currency": "USD",
            "startDate": "2026-05-07T19:00:00Z", "endDate": None,
        }])
        mock_client._extract_pagination_info = MagicMock(return_value={})
        tool.get_client = AsyncMock(return_value=mock_client)

        result = await tool._handle_list_invoices({"size": 5})
        text = result[0].text
        assert "None" not in text
        assert "n/a" in text

# ────────────────────────────────────────────────────────────────────────────
# list_skills / get_skill (cost by skill)
# ────────────────────────────────────────────────────────────────────────────

_SKILL = {
    "id": "JMwX9g4",
    "resourceType": "skill",
    "name": "code-review",
    "originCategory": "VENDOR",
    "source": "bundled",
    "kind": "workflow",
    "pluginName": "revenium-tools",
    "marketplaceName": "anthropics",
    "totalCost": 12.47,
    "callCount": 342,
    "traceCount": 57,
    "firstSeen": "2026-06-01T12:00:00Z",
    "lastSeen": "2026-06-29T18:30:00Z",
}


class TestHandleListSkills:
    def _client(self, items, page_info=None):
        c = MagicMock()
        c.get_skills = AsyncMock(
            return_value={"_embedded": {"skillUsageResourceList": items}}
        )
        c._extract_embedded_data = MagicMock(return_value=items)
        c._extract_pagination_info = MagicMock(return_value=page_info or {})
        return c

    @pytest.mark.asyncio
    async def test_success_renders_compact_line(self, tool):
        tool.get_client = AsyncMock(return_value=self._client([_SKILL]))
        result = await tool._handle_list_skills({})
        text = result[0].text
        assert "code-review" in text
        assert "JMwX9g4" in text
        assert "VENDOR" in text
        assert "bundled" in text
        assert "12.47" in text
        assert "342 calls" in text
        assert "57 traces" in text
        # no invented currency symbol
        assert "$" not in text

    @pytest.mark.asyncio
    async def test_default_sort_is_cost_descending(self, tool):
        client = self._client([])
        tool.get_client = AsyncMock(return_value=client)
        await tool._handle_list_skills({})
        assert client.get_skills.call_args.kwargs["sort"] == "totalCost,DESC"

    @pytest.mark.asyncio
    async def test_explicit_sort_overrides_default(self, tool):
        client = self._client([])
        tool.get_client = AsyncMock(return_value=client)
        await tool._handle_list_skills({"sort": "callCount,DESC"})
        assert client.get_skills.call_args.kwargs["sort"] == "callCount,DESC"

    @pytest.mark.asyncio
    async def test_period_forwarded_uppercased(self, tool):
        client = self._client([])
        tool.get_client = AsyncMock(return_value=client)
        await tool._handle_list_skills({"period": "ninety_days"})
        assert client.get_skills.call_args.kwargs["period"] == "NINETY_DAYS"

    @pytest.mark.asyncio
    async def test_pagination_forwarded(self, tool):
        client = self._client([])
        tool.get_client = AsyncMock(return_value=client)
        await tool._handle_list_skills({"page": 2, "size": 5})
        kwargs = client.get_skills.call_args.kwargs
        assert kwargs["page"] == 2
        assert kwargs["size"] == 5

    @pytest.mark.asyncio
    async def test_unknown_keys_not_forwarded(self, tool):
        client = self._client([])
        tool.get_client = AsyncMock(return_value=client)
        await tool._handle_list_skills({"bogus": "x", "action": "list_skills"})
        kwargs = client.get_skills.call_args.kwargs
        assert "bogus" not in kwargs
        assert "action" not in kwargs

    @pytest.mark.asyncio
    async def test_total_elements_rendered_once_in_the_footer(self, tool):
        page_info = {"number": 0, "size": 20, "totalElements": 137, "totalPages": 7}
        tool.get_client = AsyncMock(return_value=self._client([_SKILL], page_info))
        text = (await tool._handle_list_skills({}))[0].text
        assert "Page 1 of 7, 137 skills in all." in text
        assert "137 total" not in text

    @pytest.mark.asyncio
    async def test_null_cost_and_counts_render_na_not_zero(self, tool):
        item = dict(_SKILL, totalCost=None, callCount=None, traceCount=None,
                    originCategory=None, source=None)
        tool.get_client = AsyncMock(return_value=self._client([item]))
        text = (await tool._handle_list_skills({}))[0].text
        assert "n/a" in text
        assert "None" not in text
        assert "0 calls" not in text

    @pytest.mark.asyncio
    async def test_empty_state_message(self, tool):
        tool.get_client = AsyncMock(return_value=self._client([]))
        result = await tool._handle_list_skills({})
        assert "No skills" in result[0].text

    @pytest.mark.asyncio
    async def test_every_row_of_a_full_page_is_printed_with_the_next_page(self, tool):
        items = [dict(_SKILL, name=f"skill-{i}") for i in range(100)]
        page_info = {"number": 0, "size": 100, "totalElements": 300, "totalPages": 3}
        tool.get_client = AsyncMock(return_value=self._client(items, page_info))
        text = (await tool._handle_list_skills({"size": 100}))[0].text
        assert "- skill-99 " in text
        assert "more not shown" not in text
        assert "Page 1 of 3, 300 skills in all." in text
        assert "Pass page=1 size=100 for the next page." in text
        assert text.splitlines()[0] == "**Skills by Cost**"

    @pytest.mark.asyncio
    async def test_invalid_period_raises_structured_error(self, tool):
        with pytest.raises(ToolError) as exc:
            await tool._handle_list_skills({"period": "LAST_90_DAYS"})
        assert exc.value.field == "period"

    @pytest.mark.asyncio
    async def test_invalid_period_escapes_handle_action_unwrapped(self, tool):
        """The pre-flight validation runs outside the try/except, so the
        structured envelope reaches the caller instead of guidance text."""
        with pytest.raises(ToolError) as exc:
            await tool.handle_action("list_skills", {"period": "YESTERDAY"})
        assert exc.value.field == "period"

    @pytest.mark.asyncio
    async def test_wider_period_enum_accepted(self, tool):
        client = self._client([])
        tool.get_client = AsyncMock(return_value=client)
        for period in ("NINETY_DAYS", "SIX_MONTHS"):
            await tool._handle_list_skills({"period": period})
            assert client.get_skills.call_args.kwargs["period"] == period

    @pytest.mark.asyncio
    async def test_authentication_error_reraised(self, tool):
        from src.revenium_mcp_server.auth import AuthenticationError
        client = MagicMock()
        client.get_skills = AsyncMock(side_effect=AuthenticationError("no creds"))
        tool.get_client = AsyncMock(return_value=client)
        with pytest.raises(AuthenticationError):
            await tool._handle_list_skills({})

    @pytest.mark.asyncio
    async def test_generic_exception_text(self, tool):
        client = MagicMock()
        client.get_skills = AsyncMock(side_effect=Exception("boom"))
        tool.get_client = AsyncMock(return_value=client)
        with pytest.raises(ToolError) as exc:
            await tool._handle_list_skills({})
        assert "Failed" in exc.value.message

    @pytest.mark.asyncio
    async def test_routed_via_handle_action(self, tool):
        tool.get_client = AsyncMock(return_value=self._client([_SKILL]))
        result = await tool.handle_action("list_skills", {})
        assert "code-review" in result[0].text


class TestHandleGetSkill:
    def _client(self, detail):
        c = MagicMock()
        c.get_skill_by_id = AsyncMock(return_value=detail)
        return c

    @pytest.mark.asyncio
    async def test_success_renders_detail_block(self, tool):
        tool.get_client = AsyncMock(return_value=self._client(_SKILL))
        text = (await tool._handle_get_skill({"skill_id": "JMwX9g4"}))[0].text
        assert "code-review" in text
        assert "workflow" in text
        assert "revenium-tools" in text
        assert "anthropics" in text
        assert "12.47" in text
        assert "342" in text
        assert "2026-06-01T12:00:00Z" in text
        assert "2026-06-29T18:30:00Z" in text

    @pytest.mark.asyncio
    async def test_skill_id_forwarded_to_client(self, tool):
        client = self._client(_SKILL)
        tool.get_client = AsyncMock(return_value=client)
        await tool._handle_get_skill({"skill_id": "JMwX9g4", "period": "seven_days"})
        assert client.get_skill_by_id.call_args[0][0] == "JMwX9g4"
        assert client.get_skill_by_id.call_args.kwargs["period"] == "SEVEN_DAYS"

    @pytest.mark.asyncio
    async def test_sort_not_forwarded_to_detail(self, tool):
        client = self._client(_SKILL)
        tool.get_client = AsyncMock(return_value=client)
        await tool._handle_get_skill({"skill_id": "JMwX9g4", "sort": "totalCost,DESC"})
        assert "sort" not in client.get_skill_by_id.call_args.kwargs

    @pytest.mark.asyncio
    async def test_missing_skill_id_raises_structured_error(self, tool):
        with pytest.raises(ToolError) as exc:
            await tool._handle_get_skill({})
        assert exc.value.field == "skill_id"

    @pytest.mark.asyncio
    async def test_missing_skill_id_escapes_handle_action_unwrapped(self, tool):
        with pytest.raises(ToolError) as exc:
            await tool.handle_action("get_skill", {})
        assert exc.value.field == "skill_id"

    @pytest.mark.asyncio
    async def test_invalid_period_raises_structured_error(self, tool):
        with pytest.raises(ToolError) as exc:
            await tool._handle_get_skill({"skill_id": "JMwX9g4", "period": "FOREVER"})
        assert exc.value.field == "period"

    @pytest.mark.asyncio
    async def test_nulls_render_na(self, tool):
        detail = dict(_SKILL, kind=None, pluginName=None, marketplaceName=None,
                      totalCost=None, callCount=None, firstSeen=None)
        tool.get_client = AsyncMock(return_value=self._client(detail))
        text = (await tool._handle_get_skill({"skill_id": "JMwX9g4"}))[0].text
        assert "n/a" in text
        assert "None" not in text

    @pytest.mark.asyncio
    async def test_empty_response_reports_no_detail(self, tool):
        tool.get_client = AsyncMock(return_value=self._client({}))
        text = (await tool._handle_get_skill({"skill_id": "JMwX9g4"}))[0].text
        assert "No usage detail" in text

    @pytest.mark.asyncio
    async def test_authentication_error_reraised(self, tool):
        from src.revenium_mcp_server.auth import AuthenticationError
        client = MagicMock()
        client.get_skill_by_id = AsyncMock(side_effect=AuthenticationError("no creds"))
        tool.get_client = AsyncMock(return_value=client)
        with pytest.raises(AuthenticationError):
            await tool._handle_get_skill({"skill_id": "JMwX9g4"})

    @pytest.mark.asyncio
    async def test_generic_exception_text(self, tool):
        client = MagicMock()
        client.get_skill_by_id = AsyncMock(side_effect=Exception("boom"))
        tool.get_client = AsyncMock(return_value=client)
        with pytest.raises(ToolError) as exc:
            await tool._handle_get_skill({"skill_id": "JMwX9g4"})
        assert "Failed" in exc.value.message

    @pytest.mark.asyncio
    async def test_routed_via_handle_action(self, tool):
        tool.get_client = AsyncMock(return_value=self._client(_SKILL))
        result = await tool.handle_action("get_skill", {"skill_id": "JMwX9g4"})
        assert "code-review" in result[0].text


class TestSkillActionDiscoveryMembership:
    @pytest.mark.asyncio
    async def test_both_in_supported_actions(self, tool):
        actions = await tool._get_supported_actions()
        for a in ("list_skills", "get_skill"):
            assert a in actions

    @pytest.mark.asyncio
    async def test_both_in_structured_capabilities(self, tool):
        caps = await tool._get_tool_capabilities()
        all_params = {k for c in caps for k in c.parameters}
        for a in ("list_skills", "get_skill"):
            assert a in all_params

    @pytest.mark.asyncio
    async def test_documented_in_capabilities_and_examples(self, tool):
        caps_text = (await tool._handle_get_capabilities())[0].text
        examples_text = (await tool._handle_get_examples({}))[0].text
        for a in ("list_skills", "get_skill"):
            assert a in caps_text
            assert a in examples_text
        # the wider period enum must be discoverable, not folklore
        assert "NINETY_DAYS" in caps_text
        assert "SIX_MONTHS" in examples_text

    def test_named_in_tool_description(self, tool):
        assert "list_skills" in tool.tool_description
        assert "get_skill" in tool.tool_description


class TestSkillApiFeatureGate:
    """403 means the team lacks skill attribution, not a malformed request."""

    def _gated_client(self, method):
        c = MagicMock()
        setattr(
            c,
            method,
            AsyncMock(side_effect=ReveniumAPIError("Forbidden", status_code=403)),
        )
        return c

    @pytest.mark.asyncio
    async def test_list_skills_403_names_the_feature_flag(self, tool):
        tool.get_client = AsyncMock(return_value=self._gated_client("get_skills"))
        with pytest.raises(ToolError) as exc:
            await tool._handle_list_skills({})
        text = exc.value.message
        assert "skill-attribution" in text
        assert "feature flag" in text
        assert "enable it for this team" in text

    @pytest.mark.asyncio
    async def test_get_skill_403_names_the_feature_flag(self, tool):
        tool.get_client = AsyncMock(return_value=self._gated_client("get_skill_by_id"))
        with pytest.raises(ToolError) as exc:
            await tool._handle_get_skill({"skill_id": "JMwX9g4"})
        text = exc.value.message
        assert "skill-attribution" in text
        assert "feature flag" in text
        assert "enable it for this team" in text

    @pytest.mark.asyncio
    async def test_403_does_not_blame_request_parameters(self, tool):
        """The old generic text sent callers chasing page/size/period/sort."""
        tool.get_client = AsyncMock(return_value=self._gated_client("get_skills"))
        with pytest.raises(ToolError) as exc:
            await tool._handle_list_skills({})
        text = exc.value.message
        assert "Optional parameters: page, size, period, sort" not in text
        assert "Supported periods:" not in text

    @pytest.mark.asyncio
    async def test_403_keeps_the_api_status_visible(self, tool):
        tool.get_client = AsyncMock(return_value=self._gated_client("get_skills"))
        with pytest.raises(ToolError) as exc:
            await tool._handle_list_skills({})
        text = exc.value.message
        assert "403" in text

    @pytest.mark.asyncio
    async def test_gate_predicate_only_matches_403(self, tool):
        assert tool._is_skill_api_gated(ReveniumAPIError("no", status_code=403))
        assert not tool._is_skill_api_gated(ReveniumAPIError("no", status_code=401))
        assert not tool._is_skill_api_gated(Exception("403"))


class TestGetSkillNotFoundIsAmbiguous:
    """A 404 is either an empty window or an id that is not a skill of this team."""

    def _missing_client(self):
        c = MagicMock()
        c.get_skill_by_id = AsyncMock(
            side_effect=ReveniumAPIError("Not Found", status_code=404)
        )
        return c

    @pytest.mark.asyncio
    async def test_404_renders_empty_period_not_failure(self, tool):
        tool.get_client = AsyncMock(return_value=self._missing_client())
        text = (await tool._handle_get_skill(
            {"skill_id": "JMwX9g4", "period": "SEVEN_DAYS"}
        ))[0].text
        assert "Failed" not in text
        assert "No usage recorded" in text
        assert "JMwX9g4" in text

    @pytest.mark.asyncio
    async def test_404_names_the_requested_period_and_suggests_widening(self, tool):
        tool.get_client = AsyncMock(return_value=self._missing_client())
        text = (await tool._handle_get_skill(
            {"skill_id": "JMwX9g4", "period": "seven_days"}
        ))[0].text
        assert "SEVEN_DAYS" in text
        assert "THIRTY_DAYS" in text

    @pytest.mark.asyncio
    async def test_404_without_explicit_period_reports_the_default(self, tool):
        tool.get_client = AsyncMock(return_value=self._missing_client())
        text = (await tool._handle_get_skill({"skill_id": "JMwX9g4"}))[0].text
        assert "THIRTY_DAYS" in text

    @pytest.mark.asyncio
    async def test_404_does_not_use_the_failure_guidance(self, tool):
        tool.get_client = AsyncMock(return_value=self._missing_client())
        text = (await tool._handle_get_skill({"skill_id": "JMwX9g4"}))[0].text
        assert "`skill_id` is required" not in text

    @pytest.mark.asyncio
    async def test_404_says_the_id_may_not_name_a_skill_and_points_to_list_skills(self, tool):
        tool.get_client = AsyncMock(return_value=self._missing_client())
        text = (await tool._handle_get_skill(
            {"skill_id": "5jgY4G", "period": "THIRTY_DAYS"}
        ))[0].text
        assert "may not name a skill of this team" in text
        assert "`list_skills` to confirm" in text
        assert "Failed" not in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("period", BusinessAnalyticsManagement._SKILL_PERIODS)
    async def test_404_never_suggests_the_period_used_or_a_narrower_one(self, tool, period):
        periods = BusinessAnalyticsManagement._SKILL_PERIODS
        tool.get_client = AsyncMock(return_value=self._missing_client())
        text = (await tool._handle_get_skill(
            {"skill_id": "JMwX9g4", "period": period}
        ))[0].text
        wider_lines = [line for line in text.splitlines() if "wider period" in line]
        if period == periods[-1]:
            assert wider_lines == []
            assert "is the widest period" in text
            return
        assert len(wider_lines) == 1
        # Whole tokens, because HOUR is inside EIGHT_HOURS.
        offered = set(re.findall(r"[A-Z_]{4,}", wider_lines[0]))
        assert offered
        assert offered.isdisjoint(periods[: periods.index(period) + 1])

    @pytest.mark.asyncio
    async def test_404_without_a_period_suggests_periods_wider_than_thirty_days(self, tool):
        tool.get_client = AsyncMock(return_value=self._missing_client())
        text = (await tool._handle_get_skill({"skill_id": "JMwX9g4"}))[0].text
        wider_lines = [line for line in text.splitlines() if "wider period" in line]
        assert len(wider_lines) == 1
        assert "NINETY_DAYS" in wider_lines[0]
        assert "SIX_MONTHS" in wider_lines[0]
        assert "THIRTY_DAYS" not in wider_lines[0]

    @pytest.mark.asyncio
    async def test_genuine_failures_still_use_the_failure_path(self, tool):
        for status in (401, 422, 500, 503):
            client = MagicMock()
            client.get_skill_by_id = AsyncMock(
                side_effect=ReveniumAPIError("nope", status_code=status)
            )
            tool.get_client = AsyncMock(return_value=client)
            with pytest.raises(ToolError) as exc:
                await tool._handle_get_skill({"skill_id": "JMwX9g4"})
            text = exc.value.message
            assert "Get Skill Failed" in text, status

    @pytest.mark.asyncio
    async def test_list_skills_404_stays_on_the_failure_path(self, tool):
        """Only the detail endpoint treats 404 as an empty window."""
        client = MagicMock()
        client.get_skills = AsyncMock(
            side_effect=ReveniumAPIError("Not Found", status_code=404)
        )
        tool.get_client = AsyncMock(return_value=client)
        with pytest.raises(ToolError) as exc:
            await tool._handle_list_skills({})
        text = exc.value.message
        assert "List Skills Failed" in text


class TestPeriodChargesCursorHint:
    """Review: hasMore without a usable cursor must not suggest cursor='None'."""

    @pytest.mark.asyncio
    async def test_has_more_without_cursor_omits_bogus_hint(self, tool):
        mock_client = MagicMock()
        mock_client.get_period_charges = AsyncMock(return_value={
            "_embedded": {"periodChargeResourceList": [
                {"id": "c1", "label": "l1", "transactionId": "t1", "created": "2026-06-01"}
            ]},
            "hasMore": True,
            "cursor": None,
        })
        mock_client._extract_embedded_data = MagicMock(return_value=[
            {"id": "c1", "label": "l1", "transactionId": "t1", "created": "2026-06-01"}
        ])
        tool.get_client = AsyncMock(return_value=mock_client)

        result = await tool._handle_list_period_charges({"size": 5})
        text = result[0].text
        assert "cursor='None'" not in text
        assert "more" in text.lower()


# ────────────────────────────────────────────────────────────────────────────
# analyze_cost_anomalies when a dimension report cannot be read
# ────────────────────────────────────────────────────────────────────────────

class _AnomalyReports:
    """Legacy dimension reports: 12 codexcli buckets with one spike, or a 504 for the named paths."""

    def __init__(self, failing=()):
        self.team_id = "team-1"
        self.failing = failing

    async def get(self, path, params=None, **kwargs):
        if any(fragment in path for fragment in self.failing):
            raise ReveniumAPIError("Gateway timeout", status_code=504)
        costs = [20.0] * 12
        costs[5] = 900.0
        return [
            {
                "startTimestamp": f"2026-10-{day + 1:02d}T00:00:00.000Z",
                "groups": [{"groupName": "codexcli", "metrics": [{"metricResult": cost}]}],
            }
            for day, cost in enumerate(costs)
        ]


class TestAnomalyAnswerWhenAReportFails:
    """A report that could not be read is named in the answer, never counted as zero."""

    async def _answer(self, tool, monkeypatch, dimensions, failing=()):
        monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)
        tool.get_client = AsyncMock(return_value=_AnomalyReports(failing))
        result = await tool._handle_analyze_cost_anomalies(
            {"period": "SEVEN_DAYS", "include_dimensions": dimensions}
        )
        return result[0].text

    @pytest.mark.asyncio
    async def test_a_dimension_report_that_failed_is_named_not_read_in_the_answer(
        self, tool, monkeypatch
    ):
        out = await self._answer(
            tool, monkeypatch, ["providers", "models"], failing=("total-cost-by-model",)
        )
        assert "- **models**: not read (HTTP 504: Gateway timeout)" in out
        assert "- **models**: 0" not in out
        assert "- **providers**: 1" in out
        assert "**Total anomalies detected:** 1" in out

    @pytest.mark.asyncio
    async def test_every_dimension_failing_is_an_error_not_zero_anomalies(self, tool, monkeypatch):
        with pytest.raises(ToolError) as exc:
            await self._answer(
                tool,
                monkeypatch,
                ["providers", "models"],
                failing=("total-cost-by-provider-over-time", "total-cost-by-model"),
            )
        out = exc.value.message
        assert "Cost Anomaly Analysis Failed" in out
        assert "providers: HTTP 504: Gateway timeout" in out
        assert "models: HTTP 504: Gateway timeout" in out
        assert "Total anomalies detected" not in out

    @pytest.mark.asyncio
    async def test_an_unsupported_dimension_is_named_not_read(self, tool, monkeypatch):
        out = await self._answer(tool, monkeypatch, ["providers", "widgets"])
        assert (
            "- **widgets**: not read (not a supported dimension "
            "(providers, models, api_keys, agents, customers, tokens))" in out
        )
        assert "- **providers**: 1" in out


# ────────────────────────────────────────────────────────────────────────────
# analyze_cost_anomalies new-entity detection
_DIMENSION_PATHS = {
    "total-cost-by-provider-over-time": "providers",
    "cost-metrics-by-agents-over-time": "agents",
    "cost-metrics-by-subscriber-credential": "api_keys",
    "/api/v2/analytics/cost-by-provider": "providers",
    "/api/v2/analytics/cost-by-agent": "agents",
    "/api/v2/analytics/cost-by-api-key": "api_keys",
}

# The instant detection treats as now, so its window and comparison bounds are fixed
_NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
_NOW_ISO = "2026-10-16T12:00:00.000Z"
WINDOW = "window"
COMPARISON = "comparison"


def _months_from(year, month, count):
    starts = []
    for offset in range(count):
        index = month - 1 + offset
        starts.append(datetime(year + index // 12, index % 12 + 1, 1, tzinfo=timezone.utc))
    return starts


def _half_days_from(first, count=14):
    return [first + timedelta(hours=12 * index) for index in range(count)]


def _bucket_starts(part):
    """The bucket starts a report answers for a period name, or for a detection read."""
    if part == WINDOW:
        return _half_days_from(datetime(2026, 10, 9, 12, tzinfo=timezone.utc))
    if part == COMPARISON:
        return _half_days_from(datetime(2026, 10, 2, 12, tzinfo=timezone.utc))
    if part == "SEVEN_DAYS":
        return _half_days_from(datetime(2026, 10, 9, tzinfo=timezone.utc), count=15)
    if part == "THIRTY_DAYS":
        first = datetime(2026, 9, 16, tzinfo=timezone.utc)
        return [first + timedelta(days=index) for index in range(30)]
    if part == "TWELVE_MONTHS":
        return _months_from(2025, 11, 12)
    if part == "TWENTY_FOUR_HOURS":
        first = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
        return [first + timedelta(hours=index) for index in range(24)]
    if part == "EIGHT_HOURS":
        first = datetime(2026, 10, 16, 4, tzinfo=timezone.utc)
        return [first + timedelta(hours=index) for index in range(8)]
    first = datetime(2026, 10, 16, 11, tzinfo=timezone.utc)
    return [first + timedelta(minutes=15 * index) for index in range(4)]


class _NewEntityReports:
    """Over-time reports for the anomaly read (by period) and the two detection reads.

    The anomaly read goes to the legacy route with a period name; detection reads
    the analytics route with startDate/endDate, and a read ending at _NOW is the
    window, any other the comparison period. ``costs`` maps (dimension, part) to
    {group name: one cost per bucket}, where part is a period name, WINDOW or
    COMPARISON and None leaves the group out of that bucket. A report not named
    answers openai at $20 in every bucket. ``starts`` maps a part, or a
    (dimension, part), to the bucket starts that report answers.
    """

    def __init__(self, costs=None, failing=(), starts=None, epoch_ms=False, reverse=False):
        self.team_id = "team-1"
        self.costs = costs or {}
        self.failing = set(failing)
        self.starts = starts or {}
        self.epoch_ms = epoch_ms
        self.reverse = reverse
        self.calls = []
        self.detection_bounds = []

    def _stamp(self, start):
        if self.epoch_ms:
            return int(start.timestamp() * 1000)
        return f"{start:%Y-%m-%dT%H:%M:%S}.000Z"

    def _part(self, params, analytics_route):
        if not analytics_route:
            return params.get("period")
        self.detection_bounds.append((params["startDate"], params["endDate"]))
        return WINDOW if params["endDate"] == _NOW_ISO else COMPARISON

    async def get(self, path, params=None, **kwargs):
        params = params or {}
        analytics_route = bool(kwargs.get("use_bearer"))
        part = self._part(params, analytics_route)
        self.calls.append((path, part))
        dimension = next(name for fragment, name in _DIMENSION_PATHS.items() if fragment in path)
        if (dimension, part) in self.failing:
            raise ReveniumAPIError("Gateway timeout", status_code=504)
        starts = self.starts.get((dimension, part), self.starts.get(part, _bucket_starts(part)))
        costs = self.costs.get((dimension, part), {"openai": [20.0] * len(starts)})
        buckets = [
            {
                "startTimestamp": self._stamp(start),
                "groups": [
                    {"groupName": name, "metrics": [{"metricResult": series[index]}]}
                    for name, series in costs.items()
                    if series[index] is not None
                ],
            }
            for index, start in enumerate(starts)
        ]
        if self.reverse:
            buckets.reverse()
        if not analytics_route:
            return buckets
        return {
            "_embedded": {"items": buckets},
            "page": {"number": 0, "size": 100, "totalPages": 1, "totalElements": len(buckets)},
        }


def _gap_provider_week():
    """openai misses buckets in both reads; newprov has window cost in buckets 9, 10 and 12 only."""
    openai = [20.0] * 14
    openai[1] = None
    openai[11] = None
    newprov = [None] * 9 + [50.0, 50.0, None, 50.0, None]
    return {
        ("providers", WINDOW): {"openai": openai, "newprov": newprov},
        ("providers", COMPARISON): {"openai": openai},
    }


def _section(answer):
    """The New Entities part of the answer, up to the next top-level section."""
    assert "## New Entities" in answer, answer
    start = answer.index("## New Entities")
    end = answer.find("\n## ", start + 1)
    return answer[start:] if end == -1 else answer[start:end]


@pytest.fixture
def frozen_now(monkeypatch):
    from src.revenium_mcp_server.analytics import enhanced_spike_analyzer

    monkeypatch.setattr(enhanced_spike_analyzer, "utc_now", lambda: _NOW)


async def _registered_answer(monkeypatch, reports, arguments):
    """The answer the registered get_business_analytics tool gives, strings and all."""
    from fastmcp import Client, FastMCP

    from src.revenium_mcp_server.config_store import get_config_store
    from src.revenium_mcp_server.introspection.integration import introspection_integration
    from src.revenium_mcp_server.introspection.registry import IntrospectionRegistry
    from src.revenium_mcp_server.tool_configuration.config import ToolConfig
    from src.revenium_mcp_server.tool_configuration.registry import ToolConfigurationRegistry

    store = get_config_store()
    monkeypatch.setattr(store, "_discovered_configs", {})
    monkeypatch.setattr(store, "_discovery_attempted", {store._DEFAULT_TENANT})
    monkeypatch.setattr(introspection_integration.engine, "registry", IntrospectionRegistry())
    monkeypatch.setattr(
        BusinessAnalyticsManagement, "get_client", AsyncMock(return_value=reports)
    )
    mcp = FastMCP("new-entity-detection-test")
    registry = ToolConfigurationRegistry(
        tool_config=ToolConfig.create_for_testing(profile="business")
    )
    await registry._register_business_analytics_management(mcp)
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_business_analytics", arguments, raise_on_error=False
        )
    return "\n".join(getattr(block, "text", "") for block in result.content)


@pytest.mark.usefixtures("frozen_now")
class TestNewEntityDetectionAnswer:
    """New-entity detection reports what appeared, when, and which period it compared with."""

    async def _answer(self, tool, monkeypatch, reports, period, **arguments):
        monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)
        tool.get_client = AsyncMock(return_value=reports)
        result = await tool._handle_analyze_cost_anomalies(
            {"period": period, "detect_new_entities": True, **arguments}
        )
        return result[0].text

    @pytest.mark.asyncio
    async def test_a_provider_absent_from_the_comparison_period_is_reported_as_new_with_its_first_bucket_date(
        self, monkeypatch
    ):
        monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)
        reports = _NewEntityReports(_gap_provider_week())

        answer = await _registered_answer(
            monkeypatch,
            reports,
            {
                "action": "analyze_cost_anomalies",
                "period": "SEVEN_DAYS",
                "detect_new_entities": "true",
                "min_new_entity_threshold": "0",
            },
        )

        section = _section(answer)
        assert "**NEWPROV** (new)" in section
        assert "first active 2026-10-14" in section
        assert "active in 3 of 14 recent buckets" in section
        assert "the 14 buckets starting 2026-10-02 12:00 UTC to 2026-10-09 00:00 UTC" in section
        assert "no cost from 2026-10-02 12:00 UTC to 2026-10-09 00:00 UTC" in section
        assert "OPENAI" not in section

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "period, window_start, comparison_start",
        [
            ("SEVEN_DAYS", "2026-10-09T12:00:00.000Z", "2026-10-02T12:00:00.000Z"),
            ("THIRTY_DAYS", "2026-09-16T12:00:00.000Z", "2026-08-17T12:00:00.000Z"),
            ("TWELVE_MONTHS", "2025-10-16T12:00:00.000Z", "2024-10-16T12:00:00.000Z"),
            ("TWENTY_FOUR_HOURS", "2026-10-15T12:00:00.000Z", "2026-10-08T12:00:00.000Z"),
            ("EIGHT_HOURS", "2026-10-16T04:00:00.000Z", "2026-10-09T04:00:00.000Z"),
            ("HOUR", "2026-10-16T11:00:00.000Z", "2026-10-09T11:00:00.000Z"),
        ],
    )
    async def test_detection_reads_the_window_and_the_period_just_before_it(
        self, tool, monkeypatch, period, window_start, comparison_start
    ):
        """Same length as the window, never under 7 days, ending a millisecond before it (BACK-4842)."""
        reports = _NewEntityReports()

        await self._answer(tool, monkeypatch, reports, period)

        comparison_end = (
            datetime.fromisoformat(window_start.replace("Z", "+00:00")) - timedelta(milliseconds=1)
        ).strftime("%Y-%m-%dT%H:%M:%S.999Z")
        assert sorted(reports.detection_bounds) == sorted(
            [(window_start, _NOW_ISO), (comparison_start, comparison_end)]
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "period, length, floor",
        [
            ("SEVEN_DAYS", "7 days", False),
            ("THIRTY_DAYS", "30 days", False),
            ("TWELVE_MONTHS", "12 months", False),
            ("HOUR", "7 days", True),
            ("EIGHT_HOURS", "7 days", True),
            ("TWENTY_FOUR_HOURS", "7 days", True),
        ],
    )
    async def test_the_answer_states_the_comparison_period_it_used(
        self, tool, monkeypatch, period, length, floor
    ):
        reports = _NewEntityReports()

        section = _section(await self._answer(tool, monkeypatch, reports, period))

        stated = next(line for line in section.splitlines() if "comparison period is" in line)
        assert stated.startswith(f"The comparison period is the {length} before the {period} window")
        assert ("no window is compared with less than 7 days" in stated) is floor
        assert stated.endswith("the window ends 2026-10-16 12:00 UTC.")

    @pytest.mark.asyncio
    async def test_without_the_flag_the_time_group_count_names_the_anomaly_read_apart_from_detection(
        self, tool, monkeypatch
    ):
        """The legacy anomaly read and the analytics detection window return different grids."""
        reports = _NewEntityReports()

        answer = await self._answer(tool, monkeypatch, reports, "SEVEN_DAYS")

        assert "**Time groups analyzed for anomalies:** 15" in answer
        assert "**Time groups analyzed:**" not in answer
        assert (
            "in the recent part, the 14 buckets starting 2026-10-09 12:00 UTC to "
            "2026-10-16 00:00 UTC"
        ) in _section(answer)

    @pytest.mark.asyncio
    async def test_the_stated_comparison_period_names_its_bounds(self, tool, monkeypatch):
        reports = _NewEntityReports()

        section = _section(await self._answer(tool, monkeypatch, reports, "SEVEN_DAYS"))

        assert (
            "The comparison period is the 7 days before the SEVEN_DAYS window: "
            "2026-10-02 12:00 UTC up to 2026-10-09 12:00 UTC, where the window starts; "
            "the window ends 2026-10-16 12:00 UTC."
        ) in section

    @pytest.mark.asyncio
    async def test_an_agent_that_paused_and_resumed_in_the_window_is_not_new(
        self, tool, monkeypatch
    ):
        """It ran in the week before, so a pause at the window's start does not make it new (BACK-4842)."""
        pausebot_window = [None] * 5 + [12.0] * 9
        pausebot_week_before = [12.0] * 10 + [None] * 4
        reports = _NewEntityReports(
            {
                ("agents", WINDOW): {"steadybot": [10.0] * 14, "pausebot": pausebot_window},
                ("agents", COMPARISON): {
                    "steadybot": [10.0] * 14,
                    "pausebot": pausebot_week_before,
                },
            }
        )

        section = _section(
            await self._answer(
                tool, monkeypatch, reports, "SEVEN_DAYS", include_dimensions=["agents"]
            )
        )

        assert "PAUSEBOT" not in section
        assert "No new agent appeared in the recent part" in section

    @pytest.mark.asyncio
    async def test_a_source_that_ran_in_the_year_before_is_not_new_over_twelve_months(
        self, tool, monkeypatch
    ):
        reports = _NewEntityReports(
            {
                ("providers", WINDOW): {
                    "openai": [20.0] * 12,
                    "newprov": [None] * 8 + [40.0] * 4,
                    "oldprov": [None] * 8 + [40.0] * 4,
                },
                ("providers", COMPARISON): {
                    "openai": [20.0] * 12,
                    "oldprov": [15.0] * 12,
                },
            },
            starts={
                WINDOW: _months_from(2025, 11, 12),
                COMPARISON: _months_from(2024, 11, 12),
            },
        )

        section = _section(await self._answer(tool, monkeypatch, reports, "TWELVE_MONTHS"))

        assert "**NEWPROV** (new)" in section
        assert "OLDPROV" not in section
        assert "first active 2026-07-01" in section
        assert "the 12 buckets starting 2025-11-01 to 2026-10-01" in section
        assert "the 12 buckets starting 2024-11-01 to 2025-10-01" in section

    @pytest.mark.asyncio
    @pytest.mark.parametrize("period", ["HOUR", "EIGHT_HOURS", "TWENTY_FOUR_HOURS"])
    async def test_a_short_window_does_not_call_a_source_idle_overnight_new(
        self, tool, monkeypatch, period
    ):
        """A window shorter than the floor is compared with the 7 days before it (BACK-4842)."""
        window_starts = _bucket_starts(period)
        week_before = [
            datetime(2026, 10, 9, tzinfo=timezone.utc) + timedelta(days=index)
            for index in range(7)
        ]
        reports = _NewEntityReports(
            {
                ("providers", WINDOW): {
                    "openai": [20.0] * len(window_starts),
                    "nightprov": [10.0] * len(window_starts),
                    "newprov": [None] + [50.0] * (len(window_starts) - 1),
                },
                ("providers", COMPARISON): {
                    "openai": [20.0] * 7,
                    "nightprov": [10.0] * 6 + [None],
                },
            },
            starts={WINDOW: window_starts, COMPARISON: week_before},
        )

        answer = await self._answer(tool, monkeypatch, reports, period)

        header = answer.splitlines()[0]
        assert header.startswith("# Cost Anomaly Analysis") and header.endswith(period)
        section = _section(answer)
        assert "**NEWPROV** (new)" in section
        assert "NIGHTPROV" not in section
        assert "the 7 buckets starting 2026-10-09 00:00 UTC to 2026-10-15 00:00 UTC" in section

    @pytest.mark.asyncio
    async def test_a_short_window_without_detection_sends_one_request(self, tool, monkeypatch):
        monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)
        reports = _NewEntityReports()
        tool.get_client = AsyncMock(return_value=reports)

        result = await tool._handle_analyze_cost_anomalies({"period": "TWENTY_FOUR_HOURS"})

        assert [called_part for _, called_part in reports.calls] == ["TWENTY_FOUR_HOURS"]
        assert "SEVEN_DAYS" not in result[0].text
        assert "New Entities" not in result[0].text

    @pytest.mark.asyncio
    async def test_a_provider_dormant_in_the_comparison_period_is_reported_as_activated(
        self, tool, monkeypatch
    ):
        reports = _NewEntityReports(
            {
                ("providers", WINDOW): {
                    "openai": [20.0] * 14,
                    "zeroprov": [None] * 4 + [30.0] * 10,
                },
                ("providers", COMPARISON): {
                    "openai": [20.0] * 14,
                    "zeroprov": [5.0] + [0.0] * 13,
                },
            }
        )

        section = _section(await self._answer(tool, monkeypatch, reports, "SEVEN_DAYS"))

        assert "**ZEROPROV** (activated)" in section
        assert "**ZEROPROV** (new)" not in section
        assert "first active 2026-10-11" in section
        assert "no cost in 13 of 14 baseline buckets" in section

    @pytest.mark.asyncio
    async def test_detection_that_finds_nothing_says_so(self, tool, monkeypatch):
        reports = _NewEntityReports(
            {("providers", WINDOW): {"openai": [20.0] * 14, "zeroall": [0.0] * 14}}
        )

        section = _section(await self._answer(tool, monkeypatch, reports, "SEVEN_DAYS"))

        sentence = next(line for line in section.splitlines() if line.startswith("No new"))
        assert sentence.startswith("No new provider appeared")
        assert "agent" not in sentence
        assert "the 14 buckets starting 2026-10-09 12:00 UTC to 2026-10-16 00:00 UTC" in sentence
        assert "the 14 buckets starting 2026-10-02 12:00 UTC to 2026-10-09 00:00 UTC" in sentence
        assert "ZEROALL" not in section

    @pytest.mark.asyncio
    async def test_a_failed_window_read_is_named_and_anomalies_still_render(
        self, tool, monkeypatch
    ):
        reports = _NewEntityReports(failing={("providers", WINDOW)})

        answer = await self._answer(tool, monkeypatch, reports, "TWENTY_FOUR_HOURS")

        assert "**Total anomalies detected:** 0" in answer
        assert (
            "New-entity detection could not run: a read it needs failed: "
            "window read: providers (HTTP 504: Gateway timeout)"
        ) in _section(answer)

    @pytest.mark.asyncio
    async def test_a_comparison_read_failing_for_agents_only_is_named(self, tool, monkeypatch):
        reports = _NewEntityReports(
            {
                ("providers", WINDOW): {
                    "openai": [20.0] * 14,
                    "newprov": [None] * 9 + [50.0] * 5,
                }
            },
            failing={("agents", COMPARISON)},
        )

        section = _section(
            await self._answer(
                tool,
                monkeypatch,
                reports,
                "TWENTY_FOUR_HOURS",
                include_dimensions=["providers", "agents"],
            )
        )

        assert "**NEWPROV** (new)" in section
        assert (
            "Not read for new-entity detection, so not examined: "
            "agents (comparison period read: HTTP 504: Gateway timeout)"
        ) in section
        sentence = next(line for line in section.splitlines() if "buckets starting" in line)
        assert sentence.startswith("Examined providers:")
        assert "agent" not in sentence

    @pytest.mark.asyncio
    async def test_reversed_epoch_millisecond_buckets_give_the_same_first_active_date(
        self, tool, monkeypatch
    ):
        reports = _NewEntityReports(_gap_provider_week(), epoch_ms=True, reverse=True)

        section = _section(await self._answer(tool, monkeypatch, reports, "SEVEN_DAYS"))

        assert "**NEWPROV** (new)" in section
        assert "first active 2026-10-14" in section
        assert "active in 3 of 14 recent buckets" in section
        assert "OPENAI" not in section

    @pytest.mark.asyncio
    async def test_same_name_in_two_dimensions_is_reported_once_with_its_type(
        self, tool, monkeypatch
    ):
        reports = _NewEntityReports(
            {
                ("providers", WINDOW): {"openai": [20.0] * 14, "shared": [20.0] * 14},
                ("providers", COMPARISON): {"openai": [20.0] * 14, "shared": [20.0] * 14},
                ("agents", WINDOW): {
                    "bot": [20.0] * 14,
                    "shared": [None] * 9 + [40.0] * 5,
                },
                ("agents", COMPARISON): {"bot": [20.0] * 14},
            }
        )

        section = _section(
            await self._answer(
                tool,
                monkeypatch,
                reports,
                "SEVEN_DAYS",
                include_dimensions=["providers", "agents"],
            )
        )

        assert section.count("**SHARED**") == 1
        assert "### Agent (1)" in section
        assert "### Provider" not in section

    @pytest.mark.asyncio
    async def test_thirty_days_compares_with_the_thirty_days_before(self, tool, monkeypatch):
        first = datetime(2026, 9, 16, tzinfo=timezone.utc)
        reports = _NewEntityReports(
            {
                ("providers", WINDOW): {
                    "openai": [20.0] * 30,
                    "newprov": [None] * 7 + [30.0] * 23,
                },
                ("providers", COMPARISON): {"openai": [20.0] * 30},
            },
            starts={
                WINDOW: [first + timedelta(days=index) for index in range(30)],
                COMPARISON: [first - timedelta(days=30 - index) for index in range(30)],
            },
        )

        section = _section(await self._answer(tool, monkeypatch, reports, "THIRTY_DAYS"))

        assert "the 30 buckets starting 2026-08-17 to 2026-09-15" in section
        assert "**NEWPROV** (new)" in section
        assert "first active 2026-09-23" in section
        assert "active in 23 of 30 recent buckets" in section

    @pytest.mark.asyncio
    async def test_a_window_without_buckets_says_detection_could_not_run(
        self, tool, monkeypatch
    ):
        reports = _NewEntityReports(
            {("providers", WINDOW): {"openai": []}}, starts={WINDOW: []}
        )

        section = _section(await self._answer(tool, monkeypatch, reports, "SEVEN_DAYS"))

        assert (
            "New-entity detection could not run: the report returned no bucket for the "
            "window, so nothing could be compared"
        ) in section

    @pytest.mark.asyncio
    async def test_an_empty_comparison_period_is_named_and_window_sources_are_new(
        self, tool, monkeypatch
    ):
        reports = _NewEntityReports(
            {("providers", COMPARISON): {"openai": []}}, starts={COMPARISON: []}
        )

        section = _section(await self._answer(tool, monkeypatch, reports, "SEVEN_DAYS"))

        assert "**OPENAI** (new)" in section
        assert "the comparison period returned no bucket" in section
        assert "with the baseline, no bucket returned." in section

    @pytest.mark.asyncio
    async def test_a_comparison_period_without_cost_says_everything_counts_as_new(
        self, tool, monkeypatch
    ):
        """A team with no usage, or no data, before the window has every source new, and the answer says why (BACK-4842)."""
        reports = _NewEntityReports(
            {
                ("providers", COMPARISON): {"openai": [0.0] * 14},
                ("agents", WINDOW): {"newagent": [None] * 9 + [5.0] * 5},
                ("agents", COMPARISON): {"oldagent": [3.0] * 14},
            }
        )

        section = _section(
            await self._answer(
                tool,
                monkeypatch,
                reports,
                "SEVEN_DAYS",
                include_dimensions=["providers", "agents"],
            )
        )

        assert "**OPENAI** (new)" in section
        assert (
            "The comparison period held no cost for providers, so every source there with "
            "cost in the window counts as new: the team had no usage then, or the platform "
            "holds no data that far back."
        ) in section

    @pytest.mark.asyncio
    async def test_a_comparison_period_with_cost_adds_no_warning(self, tool, monkeypatch):
        reports = _NewEntityReports()

        section = _section(await self._answer(tool, monkeypatch, reports, "SEVEN_DAYS"))

        assert "held no cost" not in section

    @pytest.mark.asyncio
    async def test_a_failed_agents_read_is_named_when_providers_return_no_window_bucket(
        self, tool, monkeypatch
    ):
        reports = _NewEntityReports(
            {("providers", WINDOW): {"openai": []}},
            failing={("agents", WINDOW)},
            starts={("providers", WINDOW): []},
        )

        section = _section(
            await self._answer(
                tool,
                monkeypatch,
                reports,
                "TWENTY_FOUR_HOURS",
                include_dimensions=["providers", "agents"],
            )
        )

        assert (
            "New-entity detection could not run: the report returned no bucket for the window"
        ) in section
        assert (
            "Not read for new-entity detection, so not examined: "
            "agents (window read: HTTP 504: Gateway timeout)"
        ) in section

    @pytest.mark.asyncio
    async def test_daily_agent_buckets_are_compared_on_their_own_grid(
        self, tool, monkeypatch
    ):
        def daily(first_day):
            first = datetime(2026, 10, first_day, tzinfo=timezone.utc)
            return [first + timedelta(days=index) for index in range(7)]

        reports = _NewEntityReports(
            {
                ("providers", WINDOW): {
                    "openai": [20.0] * 14,
                    "newprov": [None] * 9 + [50.0] * 5,
                },
                ("agents", WINDOW): {
                    "steadybot": [10.0] * 7,
                    "newagent": [None] * 2 + [5.0] * 5,
                },
                ("agents", COMPARISON): {"steadybot": [10.0] * 7},
            },
            starts={("agents", WINDOW): daily(10), ("agents", COMPARISON): daily(3)},
        )

        section = _section(
            await self._answer(
                tool,
                monkeypatch,
                reports,
                "SEVEN_DAYS",
                include_dimensions=["providers", "agents"],
            )
        )

        assert "STEADYBOT" not in section
        assert (
            "Examined providers: compared the recent part, the 14 buckets starting "
            "2026-10-09 12:00 UTC to 2026-10-16 00:00 UTC, with the baseline, the 14 "
            "buckets starting 2026-10-02 12:00 UTC to 2026-10-09 00:00 UTC. Examined "
            "agents: compared the recent part, the 7 buckets starting 2026-10-10 to "
            "2026-10-16, with the baseline, the 7 buckets starting 2026-10-03 to "
            "2026-10-09."
        ) in section
        assert "**NEWPROV** (new)" in section
        assert "active in 5 of 14 recent buckets" in section
        assert "no cost from 2026-10-02 12:00 UTC to 2026-10-09 00:00 UTC" in section
        assert "**NEWAGENT** (new)" in section
        assert "active in 5 of 7 recent buckets" in section
        assert "no cost from 2026-10-03 to 2026-10-09" in section

    @pytest.mark.asyncio
    async def test_nothing_found_above_the_threshold_names_the_threshold(
        self, tool, monkeypatch
    ):
        """A source below min_new_entity_threshold did appear, so the answer names the threshold (BACK-4813)."""
        reports = _NewEntityReports(
            {
                ("providers", WINDOW): {
                    "openai": [20.0] * 14,
                    "smallnew": [None] * 9 + [50.0] * 5,
                }
            }
        )

        section = _section(
            await self._answer(
                tool, monkeypatch, reports, "SEVEN_DAYS", min_new_entity_threshold=100000
            )
        )

        sentence = next(line for line in section.splitlines() if line.startswith("No new"))
        assert sentence.startswith(
            "No new or activated provider reached $100,000.00 in the recent part"
        )
        assert "appeared" not in sentence
        assert "SMALLNEW" not in section

    @pytest.mark.asyncio
    async def test_found_above_a_threshold_says_only_those_are_listed(
        self, tool, monkeypatch
    ):
        reports = _NewEntityReports(
            {
                ("providers", WINDOW): {
                    "openai": [20.0] * 14,
                    "newprov": [None] * 9 + [50.0] * 5,
                    "smallnew": [None] * 9 + [1.0] * 5,
                }
            }
        )

        section = _section(
            await self._answer(
                tool, monkeypatch, reports, "SEVEN_DAYS", min_new_entity_threshold=100
            )
        )

        assert "**NEWPROV** (new)" in section
        assert "SMALLNEW" not in section
        assert "Only sources that reached $100.00 in the recent part are listed." in section

    @pytest.mark.asyncio
    async def test_nothing_found_with_threshold_zero_says_nothing_appeared(
        self, tool, monkeypatch
    ):
        reports = _NewEntityReports({("providers", WINDOW): {"openai": [20.0] * 14}})

        section = _section(
            await self._answer(
                tool, monkeypatch, reports, "SEVEN_DAYS", min_new_entity_threshold=0
            )
        )

        sentence = next(line for line in section.splitlines() if line.startswith("No new"))
        assert sentence.startswith("No new provider appeared in the recent part")
        assert "Only sources that reached" not in section

    @pytest.mark.asyncio
    async def test_detect_new_entities_schema_names_activation(self, tool):
        """The schema says detection reports activated sources, not only absent ones (BACK-4813)."""
        schema = await tool._get_input_schema()

        description = schema["properties"]["detect_new_entities"]["description"]
        assert "activated" in description
        assert "absent from the baseline" not in description

    @pytest.mark.asyncio
    async def test_detect_new_entities_schema_names_the_comparison_period(self, tool):
        schema = await tool._get_input_schema()

        description = schema["properties"]["detect_new_entities"]["description"]
        assert "the same length just before it and at least 7 days" in description
