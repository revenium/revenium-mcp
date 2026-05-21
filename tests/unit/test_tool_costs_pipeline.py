"""Unit tests for tool cost analytics pipeline — validation, processor, analyzer, engine, handler."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.analytics.validation import AnalyticsValidator, ValidationError
from src.revenium_mcp_server.analytics.simple_cost_analyzer import SimpleCostAnalyzer
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


class TestSimpleCostAnalyzerToolCosts:
    """Tests for SimpleCostAnalyzer tool cost methods."""

    @pytest.fixture
    def analyzer(self):
        mock_client = MagicMock()
        mock_client.team_id = "test-team-123"
        analyzer = SimpleCostAnalyzer(mock_client)
        return analyzer

    @pytest.mark.asyncio
    async def test_get_tool_costs_success(self, analyzer):
        analyzer.client.get_cost_by_tool_aggregated = AsyncMock(
            return_value={
                "_embedded": {
                    "items": [
                        {"toolId": "manage_products", "totalCost": 0.50, "callCount": 28},
                        {"toolId": "manage_tools", "totalCost": 0.30, "callCount": 15},
                    ]
                }
            }
        )
        result = await analyzer.get_tool_costs("HOUR", "TOTAL")
        assert len(result) == 2
        assert result[0]["tool"] == "manage_products"
        assert result[0]["cost"] == 0.50
        assert result[0]["call_count"] == 28
        assert "percentage" in result[0]
        analyzer.client.get_cost_by_tool_aggregated.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_tool_costs_empty_response(self, analyzer):
        analyzer.client.get_cost_by_tool_aggregated = AsyncMock(
            return_value={"_embedded": {"items": []}}
        )
        result = await analyzer.get_tool_costs("HOUR", "TOTAL")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_tool_costs_no_team_id_raises(self, analyzer):
        analyzer.client.team_id = None
        with pytest.MonkeyPatch.context() as m:
            m.delenv("REVENIUM_TEAM_ID", raising=False)
            with pytest.raises(Exception, match="Team ID"):
                await analyzer.get_tool_costs("HOUR", "TOTAL")

    @pytest.mark.asyncio
    async def test_get_top_tools_success(self, analyzer):
        analyzer.client.get_top_tools_by_call_count = AsyncMock(
            return_value=[
                {"groupName": "manage_products", "metrics": [{"metricResult": 28}]},
                {"groupName": "manage_tools", "metrics": [{"metricResult": 15}]},
            ]
        )
        result = await analyzer.get_top_tools("HOUR", "TOTAL")
        assert len(result) == 2
        assert result[0]["tool"] == "manage_products"
        assert result[0]["call_count"] == 28

    @pytest.mark.asyncio
    async def test_get_tool_costs_by_agent_success(self, analyzer):
        analyzer.client.get_cost_by_tool_agent = AsyncMock(
            return_value=[
                {"groupName": "claude-code", "metrics": [{"metricResult": 0.35}]},
            ]
        )
        result = await analyzer.get_tool_costs_by_agent("HOUR", "TOTAL")
        assert len(result) == 1
        assert result[0]["agent"] == "claude-code"
        assert result[0]["cost"] == 0.35

    @pytest.mark.asyncio
    async def test_get_tool_costs_by_provider_success(self, analyzer):
        analyzer.client.get_cost_by_tool_provider = AsyncMock(
            return_value=[
                {"groupName": "revenium", "metrics": [{"metricResult": 0.50}]},
            ]
        )
        result = await analyzer.get_tool_costs_by_provider("HOUR", "TOTAL")
        assert len(result) == 1
        assert result[0]["provider"] == "revenium"
        assert result[0]["cost"] == 0.50


class TestSimpleAnalyticsEngineToolCosts:
    """Tests for tool cost methods on SimpleAnalyticsEngine."""

    @pytest.fixture
    def engine(self):
        mock_client = MagicMock()
        mock_client.team_id = "test-team-123"
        engine = SimpleAnalyticsEngine(mock_client)
        # Mock the analyzer methods to return pre-formatted data
        engine.analyzer = MagicMock()
        engine.analyzer.get_tool_costs = AsyncMock(
            return_value=[{"tool": "manage_products", "cost": 0.50}]
        )
        engine.analyzer.get_top_tools = AsyncMock(
            return_value=[{"tool": "manage_products", "call_count": 28}]
        )
        engine.analyzer.get_tool_costs_by_agent = AsyncMock(
            return_value=[{"agent": "claude-code", "cost": 0.35}]
        )
        engine.analyzer.get_tool_costs_by_provider = AsyncMock(
            return_value=[{"provider": "revenium", "cost": 0.50}]
        )
        return engine

    @pytest.mark.asyncio
    async def test_get_tool_costs(self, engine):
        result = await engine.get_tool_costs(period="HOUR")
        assert isinstance(result, str)
        assert "Tool Cost" in result or "tool" in result.lower()

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
    async def test_invalid_period_returns_error(self, engine):
        result = await engine.get_tool_costs(period="INVALID")
        assert "Error" in result or "error" in result.lower()


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
        result = await tool.handle_action("get_tool_costs", {"period": "INVALID"})
        assert "Validation Error" in result[0].text

    @pytest.mark.asyncio
    async def test_get_tool_costs_generic_error(self, tool):
        tool.simple_analytics_engine.get_tool_costs = AsyncMock(
            side_effect=Exception("API down")
        )
        result = await tool.handle_action("get_tool_costs", {"period": "HOUR"})
        assert "Failed" in result[0].text

    @pytest.mark.asyncio
    async def test_supported_actions_includes_tool_costs(self, tool):
        actions = await tool._get_supported_actions()
        assert "get_tool_costs" in actions
        assert "get_top_tools" in actions
        assert "get_tool_costs_by_agent" in actions
        assert "get_tool_costs_by_provider" in actions
