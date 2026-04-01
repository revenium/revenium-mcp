"""Unit tests for ai_routing.fallback_router module.

Tests FallbackRouter: rule-based routing of queries to tools and actions
using pattern matching, including tool context hints and fallback defaults.
"""

import pytest

from src.revenium_mcp_server.ai_routing.fallback_router import FallbackRouter
from src.revenium_mcp_server.ai_routing.models import RoutingMethod, RoutingStatus


@pytest.fixture
def router():
    return FallbackRouter()


class TestRouteQueryWithToolContext:
    """Tests for route_query when tool_context provides a direct hint."""

    @pytest.mark.asyncio
    async def test_uses_tool_context_when_matching(self, router):
        result = await router.route_query("show me everything", "products")
        assert result.tool_name == "products"
        assert result.routing_method == RoutingMethod.RULE_BASED

    @pytest.mark.asyncio
    async def test_context_hint_gives_high_confidence(self, router):
        result = await router.route_query("anything", "alerts")
        assert result.confidence >= 0.5


class TestRouteQueryToolDetection:
    """Tests for tool detection from query content."""

    @pytest.mark.asyncio
    async def test_detects_products_tool(self, router):
        result = await router.route_query("create a new product", "")
        assert result.tool_name == "products"

    @pytest.mark.asyncio
    async def test_detects_alerts_tool(self, router):
        result = await router.route_query("show me all alerts", "")
        assert result.tool_name == "alerts"

    @pytest.mark.asyncio
    async def test_detects_subscriptions_tool(self, router):
        result = await router.route_query("list my subscriptions", "")
        assert result.tool_name == "subscriptions"

    @pytest.mark.asyncio
    async def test_detects_customers_tool(self, router):
        result = await router.route_query("add a new customer", "")
        assert result.tool_name == "customers"

    @pytest.mark.asyncio
    async def test_detects_workflows_tool(self, router):
        result = await router.route_query("start a workflow", "")
        assert result.tool_name == "workflows"

    @pytest.mark.asyncio
    async def test_default_fallback_to_products(self, router):
        """Unrecognizable queries fall back to products with low confidence."""
        result = await router.route_query("xyzzy foobar", "")
        assert result.tool_name == "products"
        assert result.confidence <= 0.5


class TestRouteQueryActionDetection:
    """Tests for action detection from query content."""

    @pytest.mark.asyncio
    async def test_detects_create_action(self, router):
        result = await router.route_query("create a new product", "products")
        assert result.action == "create"

    @pytest.mark.asyncio
    async def test_detects_list_action(self, router):
        result = await router.route_query("list all products", "products")
        assert result.action == "list"

    @pytest.mark.asyncio
    async def test_detects_update_action(self, router):
        result = await router.route_query("update the product name", "products")
        assert result.action == "update"

    @pytest.mark.asyncio
    async def test_detects_delete_action(self, router):
        result = await router.route_query("delete this product", "products")
        assert result.action == "delete"

    @pytest.mark.asyncio
    async def test_detects_start_action_for_workflows(self, router):
        result = await router.route_query("start the onboarding process", "workflows")
        assert result.action == "start"

    @pytest.mark.asyncio
    async def test_default_action_is_list(self, router):
        """When no action is detected, defaults to 'list'."""
        result = await router.route_query("products", "products")
        assert result.action == "list"


class TestRouteQueryStatus:
    """Tests for routing result status."""

    @pytest.mark.asyncio
    async def test_success_when_tool_and_action_found(self, router):
        result = await router.route_query("list all alerts", "alerts")
        assert result.status == RoutingStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_routing_method_is_rule_based(self, router):
        result = await router.route_query("list products", "products")
        assert result.routing_method == RoutingMethod.RULE_BASED


class TestToolActionFiltering:
    """Tests for _get_valid_actions_for_tool."""

    def test_workflows_have_special_actions(self, router):
        actions = router._get_valid_actions_for_tool("workflows")
        assert "start" in actions
        assert "next_step" in actions
        assert "complete_step" in actions

    def test_products_have_crud_actions(self, router):
        actions = router._get_valid_actions_for_tool("products")
        assert "list" in actions
        assert "create" in actions
        assert "update" in actions
        assert "delete" in actions

    def test_unknown_tool_gets_default_actions(self, router):
        actions = router._get_valid_actions_for_tool("unknown_tool")
        assert "list" in actions
        assert "create" in actions


class TestRoutingPatternsSummary:
    """Tests for get_routing_patterns_summary."""

    def test_summary_contains_expected_keys(self, router):
        summary = router.get_routing_patterns_summary()
        assert "tool_patterns" in summary
        assert "action_patterns" in summary
        assert "total_patterns" in summary
        assert summary["total_patterns"] > 0

    def test_summary_has_all_tools(self, router):
        summary = router.get_routing_patterns_summary()
        for tool in ["products", "alerts", "subscriptions", "customers", "workflows"]:
            assert tool in summary["tool_patterns"]
