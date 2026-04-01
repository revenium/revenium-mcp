"""Unit tests for ai_routing.router module.

Tests UniversalQueryRouter: routing decisions, fallback behavior,
validation, configuration updates, metrics integration, and exception types.
All external dependencies (AIClient, ToolIntegrator) are mocked.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.ai_routing.config import AIRoutingConfig, TestingMode
from src.revenium_mcp_server.ai_routing.models import (
    RoutingMethod,
    RoutingResult,
    RoutingStatus,
)
from src.revenium_mcp_server.ai_routing.router import (
    UniversalQueryRouter,
)


@pytest.fixture
def router_disabled():
    """Create router with AI disabled (rule-based only)."""
    config = AIRoutingConfig.create_for_testing(global_enabled=False)
    with patch("src.revenium_mcp_server.ai_routing.router.ToolIntegrator"):
        with patch("src.revenium_mcp_server.ai_routing.router.FallbackRouter") as MockFallback:
            mock_fallback = MagicMock()
            mock_fallback.route_query = AsyncMock(
                return_value=RoutingResult(
                    tool_name="products",
                    action="list",
                    confidence=0.9,
                    routing_method=RoutingMethod.RULE_BASED,
                    status=RoutingStatus.SUCCESS,
                )
            )
            MockFallback.return_value = mock_fallback
            r = UniversalQueryRouter(config)
            r._mock_fallback = mock_fallback
            yield r


@pytest.fixture
def router_enabled():
    """Create router with AI enabled."""
    config = AIRoutingConfig.create_for_testing(
        global_enabled=True, testing_mode=TestingMode.AI_ONLY
    )
    with patch("src.revenium_mcp_server.ai_routing.router.ToolIntegrator"):
        with patch("src.revenium_mcp_server.ai_routing.router.AIClient") as MockAI:
            with patch("src.revenium_mcp_server.ai_routing.router.FallbackRouter") as MockFallback:
                mock_ai = MagicMock()
                MockAI.return_value = mock_ai
                mock_fallback = MagicMock()
                mock_fallback.route_query = AsyncMock(
                    return_value=RoutingResult(
                        tool_name="products",
                        action="list",
                        confidence=0.9,
                        routing_method=RoutingMethod.RULE_BASED,
                        status=RoutingStatus.SUCCESS,
                    )
                )
                MockFallback.return_value = mock_fallback
                r = UniversalQueryRouter(config)
                r._mock_ai = mock_ai
                r._mock_fallback = mock_fallback
                yield r


class TestRouteQueryDisabled:
    """Tests for route_query when AI is disabled."""

    @pytest.mark.asyncio
    async def test_uses_rule_based_routing(self, router_disabled):
        result = await router_disabled.route_query("list products", "products")
        assert result.tool_name == "products"
        assert result.routing_method == RoutingMethod.RULE_BASED

    @pytest.mark.asyncio
    async def test_records_metrics(self, router_disabled):
        await router_disabled.route_query("list products", "products")
        assert len(router_disabled.metrics_collector.metrics) == 1


class TestRouteQueryEnabled:
    """Tests for route_query when AI is enabled."""

    @pytest.mark.asyncio
    async def test_falls_back_on_ai_error(self, router_enabled):
        from src.revenium_mcp_server.ai_routing.ai_client import AIClientError

        router_enabled.ai_client.route_query = AsyncMock(
            side_effect=AIClientError("ai failed")
        )
        result = await router_enabled.route_query("list products", "products")
        # Should fallback to rule-based
        assert result.routing_method == RoutingMethod.RULE_BASED


class TestValidateRoutingResult:
    """Tests for _validate_routing_result."""

    def test_valid_result_passes(self, router_disabled):
        result = RoutingResult(
            tool_name="products", action="list", confidence=0.9
        )
        assert router_disabled._validate_routing_result(result) is True

    def test_unknown_tool_fails(self, router_disabled):
        result = RoutingResult(
            tool_name="nonexistent", action="list", confidence=0.9
        )
        assert router_disabled._validate_routing_result(result) is False

    def test_invalid_action_fails(self, router_disabled):
        result = RoutingResult(
            tool_name="products", action="invalid_action", confidence=0.9
        )
        assert router_disabled._validate_routing_result(result) is False

    def test_low_confidence_fails(self, router_disabled):
        result = RoutingResult(
            tool_name="products", action="list", confidence=0.1
        )
        assert router_disabled._validate_routing_result(result) is False


class TestGetRoutingStatus:
    """Tests for get_routing_status."""

    def test_returns_status_dict(self, router_disabled):
        status = router_disabled.get_routing_status()
        assert "config" in status
        assert "ai_client_available" in status
        assert "available_tools" in status
        assert "metrics_session" in status
        assert "total_queries_processed" in status

    def test_ai_client_unavailable_when_disabled(self, router_disabled):
        status = router_disabled.get_routing_status()
        assert status["ai_client_available"] is False


class TestGetMetricsReport:
    """Tests for get_metrics_report."""

    def test_returns_summary(self, router_disabled):
        report = router_disabled.get_metrics_report()
        # No metrics yet, should have error key
        assert "error" in report


class TestUpdateConfiguration:
    """Tests for update_configuration."""

    @pytest.mark.asyncio
    async def test_updates_config(self, router_disabled):
        router_disabled.config.config_file = None
        success = await router_disabled.update_configuration({"ai_percentage": 50})
        assert success is True
        assert router_disabled.config.ai_percentage == 50

    @pytest.mark.asyncio
    async def test_invalid_update_returns_false(self, router_disabled):
        router_disabled.config.config_file = None
        success = await router_disabled.update_configuration({"ai_percentage": 999})
        assert success is False


class TestClose:
    """Tests for close method."""

    @pytest.mark.asyncio
    async def test_close_with_ai_client(self, router_enabled):
        router_enabled.ai_client.close = AsyncMock()
        await router_enabled.close()
        router_enabled.ai_client.close.assert_awaited_once()


