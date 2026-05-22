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

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp.types import TextContent

from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    BusinessAnalyticsManagement,
)
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
        assert result.mimeType == "image/png"

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
        err.response_data = {"error_data": "access denied"}
        result = tool._format_api_error_details(err)
        assert "access denied" in result

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
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Business Analytics" in result[0].text

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
        result = await tool.handle_action("get_cost_trends", {})
        assert "Not Supported" in result[0].text

    @pytest.mark.asyncio
    async def test_unsupported_action_unknown(self, _mock_engine_cls, _mock_analyzer_cls, tool):
        result = await tool.handle_action("completely_unknown_action", {})
        assert "Not Supported" in result[0].text

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
    async def test_validation_error_returns_error_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_cost_summary = AsyncMock(
            side_effect=ValidationError("bad period", suggestions=["Use SEVEN_DAYS"])
        )
        result = await tool._handle_get_cost_summary({})
        assert "Validation Error" in result[0].text
        assert "bad period" in result[0].text
        assert "Use SEVEN_DAYS" in result[0].text

    @pytest.mark.asyncio
    async def test_generic_exception_returns_error_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_cost_summary = AsyncMock(
            side_effect=RuntimeError("oops")
        )
        result = await tool._handle_get_cost_summary({})
        assert "Failed" in result[0].text


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
        result = await tool._handle_get_provider_costs({})
        assert "Provider Costs Validation Error" in result[0].text
        assert "invalid period" in result[0].text

    @pytest.mark.asyncio
    async def test_generic_exception_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_provider_costs = AsyncMock(
            side_effect=RuntimeError("API failure")
        )
        result = await tool._handle_get_provider_costs({})
        assert "Provider Costs Analysis Failed" in result[0].text


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
        result = await tool._handle_get_model_costs({})
        assert "Model Costs Validation Error" in result[0].text

    @pytest.mark.asyncio
    async def test_generic_exception_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_model_costs = AsyncMock(
            side_effect=RuntimeError("crash")
        )
        result = await tool._handle_get_model_costs({})
        assert "Model Costs Analysis Failed" in result[0].text


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
        result = await tool._handle_get_customer_costs({})
        assert "Customer Costs Validation Error" in result[0].text

    @pytest.mark.asyncio
    async def test_generic_exception_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_customer_costs = AsyncMock(
            side_effect=Exception("error")
        )
        result = await tool._handle_get_customer_costs({})
        assert "Customer Costs Analysis Failed" in result[0].text


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
        result = await tool._handle_get_api_key_costs({})
        assert "API Key Costs Validation Error" in result[0].text

    @pytest.mark.asyncio
    async def test_generic_exception_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_api_key_costs = AsyncMock(
            side_effect=Exception("down")
        )
        result = await tool._handle_get_api_key_costs({})
        assert "API Key Costs Analysis Failed" in result[0].text


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
        result = await tool._handle_get_agent_costs({})
        assert "Agent Costs Validation Error" in result[0].text

    @pytest.mark.asyncio
    async def test_generic_exception_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_agent_costs = AsyncMock(
            side_effect=Exception("down")
        )
        result = await tool._handle_get_agent_costs({})
        assert "Agent Costs Analysis Failed" in result[0].text


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
    async def test_threshold_param_error_returns_guidance(self, mock_analyzer_cls, tool):
        """Using 'threshold' instead of 'min_impact_threshold' returns error text with correct param name.

        create_structured_validation_error returns a ToolError (not ValidationError), so it is
        caught by the outer `except Exception` handler in _handle_analyze_cost_anomalies, which
        formats the ToolError message and includes 'min_impact_threshold' in the response body.
        """
        result = await tool._handle_analyze_cost_anomalies(
            {"period": "SEVEN_DAYS", "threshold": 100.0}
        )
        assert "Cost Anomaly Analysis Failed" in result[0].text
        assert "min_impact_threshold" in result[0].text

    @pytest.mark.asyncio
    async def test_breakdown_by_error_returns_error_text(self, mock_analyzer_cls, tool):
        """Using 'breakdown_by' instead of 'include_dimensions' returns error text with correct param name.

        create_structured_validation_error returns a ToolError caught by `except Exception`,
        and the ToolError message includes 'include_dimensions'.
        """
        result = await tool._handle_analyze_cost_anomalies(
            {"period": "SEVEN_DAYS", "breakdown_by": "providers"}
        )
        assert "Cost Anomaly Analysis Failed" in result[0].text
        assert "include_dimensions" in result[0].text

    @pytest.mark.asyncio
    async def test_missing_period_returns_error_text(self, mock_analyzer_cls, tool):
        """Missing period returns error text explaining that period is required.

        create_structured_missing_parameter_error returns a ToolError caught by `except Exception`,
        and the ToolError message includes 'period'.
        """
        result = await tool._handle_analyze_cost_anomalies({})
        assert "Cost Anomaly Analysis Failed" in result[0].text
        assert "period" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_validation_error_from_analyzer_returns_text(self, mock_analyzer_cls, tool):
        mock_analyzer_cls.return_value.analyze_temporal_anomalies = AsyncMock(
            side_effect=ValidationError("invalid sensitivity", suggestions=["use normal"])
        )
        result = await tool._handle_analyze_cost_anomalies({"period": "SEVEN_DAYS"})
        assert "Validation Error" in result[0].text
        assert "invalid sensitivity" in result[0].text

    @pytest.mark.asyncio
    async def test_generic_exception_returns_error_text(self, mock_analyzer_cls, tool):
        mock_analyzer_cls.return_value.analyze_temporal_anomalies = AsyncMock(
            side_effect=RuntimeError("analyzer failed")
        )
        result = await tool._handle_analyze_cost_anomalies({"period": "SEVEN_DAYS"})
        assert "Failed" in result[0].text

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
        """breakdown_by=None doesn't crash the dimension mapping and returns guidance text.

        Even when breakdown_by is None, the ToolError message still directs the user to
        use 'include_dimensions', confirming the None-safe branch ran without raising.
        """
        result = await tool._handle_analyze_cost_anomalies(
            {"period": "SEVEN_DAYS", "breakdown_by": None}
        )
        assert "Cost Anomaly Analysis Failed" in result[0].text
        assert "include_dimensions" in result[0].text

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
                    ],
                },
            },
            "recommendations": ["Tag your credentials"],
        }
        out = fmt(payload)
        assert "# Cost Anomaly Analysis — SEVEN_DAYS" in out
        assert "**Total anomalies detected:** 2" in out
        assert "**Time groups analyzed:** 7" in out
        assert "| OPENAI | provider | Monday | $123.45 |" in out
        assert "$10.00–$20.00" in out
        assert "### Anomaly Context" in out
        assert "OPENAI Monday spike" in out
        assert "### Monday" in out
        assert "**Cost multiplier**: 10.90" in out
        assert "**Anomalous time periods**: Monday, Wednesday" in out
        assert "## New Entities Detected" in out
        assert "NEW-BOT" in out
        assert "$50.00 impact across 3 period(s)" in out
        assert "## Recommendations" in out
        assert "- Tag your credentials" in out

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
        result = await tool._handle_unsupported_action("mystery_action")
        assert "mystery_action" in result[0].text
        assert "Not Supported" in result[0].text



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
        assert tool.tool_name == "business_analytics_management"

    @pytest.mark.asyncio
    async def test_tool_version_class_var(self, tool):
        assert tool.tool_version == "1.0.0"
