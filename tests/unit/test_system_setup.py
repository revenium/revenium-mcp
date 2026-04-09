"""Unit tests for SystemSetup tool.

Tests the SystemSetup class which consolidates welcome guidance, setup
validation, and email configuration into a single onboarding tool.
"""

import pytest
from unittest.mock import AsyncMock

from src.revenium_mcp_server.tools_decomposed.system_setup import SystemSetup
from mcp.types import TextContent


@pytest.fixture
def setup_tool():
    """Create a SystemSetup instance with mocked sub-tools."""
    tool = SystemSetup()
    tool.welcome_tool.handle_action = AsyncMock(
        return_value=[TextContent(type="text", text="welcome result")]
    )
    tool.checklist_tool.handle_action = AsyncMock(
        return_value=[TextContent(type="text", text="checklist result")]
    )
    tool.email_tool.handle_action = AsyncMock(
        return_value=[TextContent(type="text", text="email result")]
    )
    return tool


class TestSystemSetupRouting:
    """Test action routing to correct sub-tools."""

    @pytest.mark.asyncio
    async def test_get_capabilities(self, setup_tool):
        """get_capabilities returns consolidated setup capabilities."""
        result = await setup_tool.handle_action("get_capabilities", {})
        text = result[0].text
        assert "System Setup" in text
        assert "Welcome" in text
        assert "Email" in text

    @pytest.mark.asyncio
    async def test_get_examples(self, setup_tool):
        """get_examples returns usage examples for all action groups."""
        result = await setup_tool.handle_action("get_examples", {})
        text = result[0].text
        assert "show_welcome" in text
        assert "validate_email" in text

    @pytest.mark.asyncio
    async def test_get_agent_summary(self, setup_tool):
        """get_agent_summary returns professional setup guidance."""
        result = await setup_tool.handle_action("get_agent_summary", {})
        text = result[0].text
        assert "System Setup" in text
        assert "Quick Start" in text

    @pytest.mark.asyncio
    async def test_welcome_actions_delegate_to_welcome_tool(self, setup_tool):
        """Welcome actions delegate to welcome_tool."""
        for action in ["show_welcome", "setup_checklist", "environment_status", "next_steps", "complete_setup", "help", "get_actions"]:
            setup_tool.welcome_tool.handle_action.reset_mock()
            result = await setup_tool.handle_action(action, {})
            setup_tool.welcome_tool.handle_action.assert_called_once_with(action, {})

    @pytest.mark.asyncio
    async def test_checklist_actions_delegate_to_checklist_tool(self, setup_tool):
        """Checklist actions delegate to checklist_tool."""
        for action in ["check_requirements", "check_optional", "check_system_status", "get_recommendations"]:
            setup_tool.checklist_tool.handle_action.reset_mock()
            result = await setup_tool.handle_action(action, {})
            setup_tool.checklist_tool.handle_action.assert_called_once()

    @pytest.mark.asyncio
    async def test_email_actions_delegate_to_email_tool(self, setup_tool):
        """Email actions delegate to email_tool."""
        for action in ["check_status", "update_email", "validate_email", "setup_guidance", "test_configuration"]:
            setup_tool.email_tool.handle_action.reset_mock()
            result = await setup_tool.handle_action(action, {})
            setup_tool.email_tool.handle_action.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self, setup_tool):
        """Unknown action returns structured error with valid actions."""
        result = await setup_tool.handle_action("bogus_action", {})
        text = result[0].text
        assert "bogus_action" in text or "Unknown" in text

    @pytest.mark.asyncio
    async def test_exception_from_sub_tool_propagates(self, setup_tool):
        """Exceptions from delegated tools propagate up."""
        setup_tool.welcome_tool.handle_action = AsyncMock(
            side_effect=RuntimeError("welcome crashed")
        )
        with pytest.raises(RuntimeError, match="welcome crashed"):
            await setup_tool.handle_action("show_welcome", {})


class TestSupportedActions:
    """Test _get_supported_actions."""

    @pytest.mark.asyncio
    async def test_includes_all_action_groups(self, setup_tool):
        """Supported actions include welcome, checklist, email, and meta actions."""
        actions = await setup_tool._get_supported_actions()
        assert "show_welcome" in actions
        assert "check_requirements" in actions
        assert "validate_email" in actions
        assert "get_capabilities" in actions
        assert "get_agent_summary" in actions
