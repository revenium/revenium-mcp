"""Unit tests for SystemDiagnostics tool.

Tests the SystemDiagnostics class which consolidates configuration analysis,
auto-discovery debugging, and log analysis into a single tool via delegation.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.revenium_mcp_server.tools_decomposed.system_diagnostics import SystemDiagnostics
from mcp.types import TextContent


@pytest.fixture
def diagnostics_tool():
    """Create a SystemDiagnostics instance with mocked sub-tools."""
    tool = SystemDiagnostics()
    # Mock the delegated tools to avoid real initialization
    tool.config_tool.handle_action = AsyncMock(
        return_value=[TextContent(type="text", text="config result")]
    )
    tool.debug_tool.handle_action = AsyncMock(
        return_value=[TextContent(type="text", text="debug result")]
    )
    tool.log_tool.handle_action = AsyncMock(
        return_value=[TextContent(type="text", text="log result")]
    )
    return tool


class TestSystemDiagnosticsRouting:
    """Test action routing to correct sub-tools."""

    @pytest.mark.asyncio
    async def test_get_capabilities_returns_overview(self, diagnostics_tool):
        """get_capabilities returns consolidated capabilities text."""
        result = await diagnostics_tool.handle_action("get_capabilities", {})
        text = result[0].text
        assert "System Diagnostics" in text
        assert "Configuration Analysis" in text
        assert "Log Analysis" in text

    @pytest.mark.asyncio
    async def test_get_examples_returns_examples(self, diagnostics_tool):
        """get_examples returns usage examples for all action groups."""
        result = await diagnostics_tool.handle_action("get_examples", {})
        text = result[0].text
        assert "Examples" in text
        assert "environment_variables" in text
        assert "search_logs" in text

    @pytest.mark.asyncio
    async def test_config_action_delegates_to_config_tool(self, diagnostics_tool):
        """Configuration actions delegate to config_tool."""
        result = await diagnostics_tool.handle_action("environment_variables", {})
        diagnostics_tool.config_tool.handle_action.assert_called_once_with(
            "environment_variables", {}
        )
        assert result[0].text == "config result"

    @pytest.mark.asyncio
    async def test_debug_action_delegates_to_debug_tool(self, diagnostics_tool):
        """Debug actions delegate to debug_tool."""
        result = await diagnostics_tool.handle_action("debug", {})
        diagnostics_tool.debug_tool.handle_action.assert_called_once_with("debug", {})
        assert result[0].text == "debug result"

    @pytest.mark.asyncio
    async def test_log_action_delegates_to_log_tool(self, diagnostics_tool):
        """Log analysis actions delegate to log_tool."""
        result = await diagnostics_tool.handle_action("get_internal_logs", {"size": 50})
        diagnostics_tool.log_tool.handle_action.assert_called_once_with(
            "get_internal_logs", {"size": 50}
        )

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self, diagnostics_tool):
        """Unknown action returns structured error with valid actions."""
        result = await diagnostics_tool.handle_action("bogus_action", {})
        text = result[0].text
        assert "bogus_action" in text or "Unknown" in text

    @pytest.mark.asyncio
    async def test_all_config_actions_route_correctly(self, diagnostics_tool):
        """All four config actions route to config_tool."""
        for action in ["environment_variables", "auto_discovery", "onboarding_status", "system_health"]:
            diagnostics_tool.config_tool.handle_action.reset_mock()
            await diagnostics_tool.handle_action(action, {})
            diagnostics_tool.config_tool.handle_action.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_log_actions_route_correctly(self, diagnostics_tool):
        """All five log actions route to log_tool."""
        for action in ["get_internal_logs", "get_integration_logs", "get_recent_logs", "search_logs", "analyze_operations"]:
            diagnostics_tool.log_tool.handle_action.reset_mock()
            await diagnostics_tool.handle_action(action, {})
            diagnostics_tool.log_tool.handle_action.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_from_sub_tool_propagates(self, diagnostics_tool):
        """Exceptions from delegated tools propagate up."""
        diagnostics_tool.config_tool.handle_action = AsyncMock(
            side_effect=RuntimeError("config failed")
        )
        with pytest.raises(RuntimeError, match="config failed"):
            await diagnostics_tool.handle_action("environment_variables", {})


class TestSupportedActions:
    """Test _get_supported_actions."""

    @pytest.mark.asyncio
    async def test_includes_all_routed_actions(self, diagnostics_tool):
        """Supported actions include all routed actions plus meta actions."""
        actions = await diagnostics_tool._get_supported_actions()
        assert "environment_variables" in actions
        assert "debug" in actions
        assert "get_internal_logs" in actions
        assert "get_capabilities" in actions
        assert "get_examples" in actions
