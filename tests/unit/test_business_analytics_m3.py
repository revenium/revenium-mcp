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

        result = await tool._handle_get_unpaid_invoice_totals({})
        assert "Unpaid Invoice" in result[0].text
        assert "Failed" in result[0].text

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

        result = await tool._handle_get_unpaid_invoice_totals({})
        text = result[0].text
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
        result = await tool.handle_action("get_task_costs", {"period": "SEVEN_DAYS"})
        assert "Failed" in result[0].text

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
        result = await tool.handle_action(
            "get_profit_margins", {"period": "THIRTY_DAYS", "dimension": "bogus"}
        )
        text = result[0].text
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

    # ── overflow cap (>50 rows) ───────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_aggregated_render_caps_at_50_rows(self, mock_cls, tool):
        rows = [
            {"group": f"g{i}", "label": "m", "metricResult": float(i), "metricType": "MONEY"}
            for i in range(75)
        ]
        self._mock_method(mock_cls, "get_vendor_costs", rows)
        result = await tool.handle_action("get_vendor_costs", {"period": "SEVEN_DAYS"})
        text = result[0].text
        # 50 rendered + overflow line naming the remaining 25
        assert "g49" in text
        assert "g50" not in text
        assert "25 more" in text or "overflow" in text.lower() or "not shown" in text.lower()

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
            [{"transactionId": "t1", "agentName": "a", "totalCalls": 1, "distinctTools": 1}],
            period="SEVEN_DAYS",
        )
        assert "n/a" in text
        assert "None" not in text

    def test_timeseries_no_orphan_header_on_truncation(self, tool):
        buckets = [
            {
                "startTimestamp": f"2026-07-{d:02d}",
                "endTimestamp": f"2026-07-{d:02d}",
                "groups": [
                    {"group": f"g{d}-{i}", "metrics": [{"label": "cost", "metricResult": 1.0, "metricType": "MONEY"}]}
                    for i in range(30)
                ],
            }
            for d in range(1, 4)
        ]
        text = tool._render_timeseries_buckets(buckets, title="T", period="SEVEN_DAYS")
        lines = text.split("\n")
        # No header may be the last content line before the truncation notice
        for i, line in enumerate(lines):
            if line.startswith("**2026-07-"):
                following = [l for l in lines[i+1:] if l.strip()]
                assert following and (following[0].startswith("- ") or "(no data)" in following[0]), (
                    f"orphan bucket header: {line!r}"
                )

    def test_timeseries_cap_counts_rendered_lines(self, tool):
        # One bucket, 10 groups × 10 metrics = 100 metric lines; cap is 50
        buckets = [{
            "startTimestamp": "2026-07-01", "endTimestamp": "2026-07-02",
            "groups": [
                {"group": f"g{i}", "metrics": [
                    {"label": f"m{j}", "metricResult": 1.0, "metricType": None}
                    for j in range(10)
                ]}
                for i in range(10)
            ],
        }]
        text = tool._render_timeseries_buckets(buckets, title="T", period="SEVEN_DAYS")
        metric_lines = [l for l in text.split("\n") if l.startswith("- ")]
        assert len(metric_lines) <= tool._MAX_RENDERED_ROWS

    def test_aggregated_row_includes_label_when_distinct(self, tool):
        text = tool._render_aggregated_rows(
            [{"group": "Engineering", "label": "profit margin", "metricResult": 12.5, "metricType": "PERCENTAGE"}],
            title="T", period="SEVEN_DAYS", value_noun="rows",
        )
        assert "profit margin" in text

    def test_renderer_survives_malformed_metric_value(self, tool):
        """Contract failure: a non-numeric metricResult renders via the safe
        string path — no crash, no fabricated number."""
        text = tool._render_aggregated_rows(
            [{"group": "openai", "metricResult": "not-a-number", "metricType": "MONEY"}],
            title="T", period="SEVEN_DAYS", value_noun="rows",
        )
        assert "not-a-number" in text

    @pytest.mark.asyncio
    async def test_pack_handler_survives_malformed_analyzer_rows(self, tool):
        """The handler path renders malformed analyzer rows without crashing."""
        mock_analyzer = MagicMock()
        mock_analyzer.get_vendor_costs = AsyncMock(return_value=[
            {"group": "openai", "metricResult": "not-a-number", "metricType": "MONEY"},
            {"group": "anthropic", "metricResult": None, "metricType": "MONEY"},
        ])
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
    async def test_invalid_dimension_returns_validation_text(self, mock_engine_cls, tool):
        mock_engine_cls.return_value.get_filter_options = AsyncMock(
            side_effect=ValidationError(
                "Unknown filter dimension: 'widgets'",
                field="dimension",
                suggestions=["Valid dimensions: agents, api-keys, models"],
            )
        )
        result = await tool._handle_get_filter_options({"dimension": "widgets"})
        text = result[0].text
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
        result = await tool._handle_get_filter_options({"dimension": "models"})
        assert "Failed" in result[0].text

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
    def _client(self, items):
        c = MagicMock()
        c.get_invoices = AsyncMock(
            return_value={"_embedded": {"invoiceResourceList": items}}
        )
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
        # money: fixed decimals trimmed, currency code printed (no symbol)
        assert "1234.5 USD" in text
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
        assert kwargs["startDate"] == "2026-01-01"
        assert kwargs["endDate"] == "2026-02-01"
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
        await tool._handle_list_invoices({"bogus": "x", "action": "list_invoices"})
        kwargs = client.get_invoices.call_args.kwargs
        assert "bogus" not in kwargs
        assert "action" not in kwargs

    @pytest.mark.asyncio
    async def test_overflow_cap_at_50(self, tool):
        items = [dict(_INVOICE, invoiceNumber=f"INV-{i}") for i in range(60)]
        tool.get_client = AsyncMock(return_value=self._client(items))
        result = await tool._handle_list_invoices({})
        text = result[0].text
        assert "INV-49" in text
        assert "INV-50" not in text
        assert "10 more" in text

    @pytest.mark.asyncio
    async def test_generic_exception_text(self, tool):
        client = MagicMock()
        client.get_invoices = AsyncMock(side_effect=Exception("boom"))
        tool.get_client = AsyncMock(return_value=client)
        result = await tool._handle_list_invoices({})
        assert "Failed" in result[0].text

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

class TestHandleListRefunds:
    def _client(self, items):
        c = MagicMock()
        c.get_refunds = AsyncMock(return_value={"_embedded": {"refundResourceList": items}})
        c._extract_embedded_data = MagicMock(return_value=items)
        return c

    @pytest.mark.asyncio
    async def test_empty_state_message(self, tool):
        tool.get_client = AsyncMock(return_value=self._client([]))
        result = await tool._handle_list_refunds({})
        assert "No refunds" in result[0].text

    @pytest.mark.asyncio
    async def test_success_renders_amount_with_currency(self, tool):
        refund = {"totalAmount": 25, "currency": "USD", "state": "COMPLETE"}
        tool.get_client = AsyncMock(return_value=self._client([refund]))
        result = await tool._handle_list_refunds({})
        text = result[0].text
        assert "25 USD" in text
        assert "$" not in text

    @pytest.mark.asyncio
    async def test_null_amount_renders_na(self, tool):
        refund = {"totalAmount": None, "currency": "USD"}
        tool.get_client = AsyncMock(return_value=self._client([refund]))
        result = await tool._handle_list_refunds({})
        text = result[0].text
        assert "n/a" in text
        assert "None" not in text

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
        assert kwargs["startDate"] == "2026-01-01"
        assert kwargs["endDate"] == "2026-02-01"
        assert kwargs["minimum"] == 5
        assert kwargs["maximum"] == 50

    @pytest.mark.asyncio
    async def test_generic_exception_text(self, tool):
        client = MagicMock()
        client.get_refunds = AsyncMock(side_effect=Exception("boom"))
        tool.get_client = AsyncMock(return_value=client)
        result = await tool._handle_list_refunds({})
        assert "Failed" in result[0].text

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
        charge = {"id": "pc_1", "label": "API calls", "transactionId": "tx_9"}
        tool.get_client = AsyncMock(return_value=self._client([charge]))
        result = await tool._handle_list_period_charges({})
        text = result[0].text
        assert "pc_1" in text
        assert "API calls" in text

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
                "page": 3,  # must be ignored, never forwarded
            }
        )
        kwargs = client.get_period_charges.call_args.kwargs
        assert kwargs["size"] == 7
        assert kwargs["invoiceId"] == "inv_1"
        assert kwargs["startDate"] == "2026-01-01"
        assert kwargs["endDate"] == "2026-02-01"
        assert kwargs["cursor"] == "CUR-1"
        assert "page" not in kwargs

    @pytest.mark.asyncio
    async def test_generic_exception_text(self, tool):
        client = MagicMock()
        client.get_period_charges = AsyncMock(side_effect=Exception("boom"))
        tool.get_client = AsyncMock(return_value=client)
        result = await tool._handle_list_period_charges({})
        assert "Failed" in result[0].text

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
