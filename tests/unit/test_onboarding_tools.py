"""Unit tests for onboarding tools."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed.welcome_setup import WelcomeSetup
from src.revenium_mcp_server.tools_decomposed.configuration_status import ConfigurationStatus
from mcp.types import TextContent


class TestWelcomeSetup:
    """Test WelcomeSetup tool."""

    @pytest.fixture
    def tool(self):
        """Create WelcomeSetup instance."""
        return WelcomeSetup()

    def test_initialization(self, tool):
        """Test tool initialization exposes callable action handler."""
        assert callable(tool.handle_action)

    def test_tool_name(self, tool):
        """Test tool has correct name."""
        assert tool.tool_name == "welcome_and_setup"

    def test_tool_description_exists(self, tool):
        """Test tool has a description."""
        assert tool.tool_description is not None
        assert len(tool.tool_description) > 0

    def test_tool_description_mentions_welcome(self, tool):
        """Test tool description mentions welcome."""
        assert "welcome" in tool.tool_description.lower()

    @pytest.mark.asyncio
    async def test_get_capabilities(self, tool):
        """Test get_capabilities action."""
        result = await tool.handle_action("get_capabilities", {})
        assert len(result) >= 1
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_get_examples(self, tool):
        """Test get_examples action."""
        result = await tool.handle_action("get_examples", {})
        assert len(result) >= 1
        assert isinstance(result[0], TextContent)


class TestConfigurationStatus:
    """Test ConfigurationStatus tool."""

    @pytest.fixture
    def tool(self):
        """Create ConfigurationStatus instance."""
        return ConfigurationStatus()

    def test_initialization(self, tool):
        """Test tool initialization exposes callable action handler."""
        assert callable(tool.handle_action)

    def test_tool_name(self, tool):
        """Test tool has correct name."""
        assert tool.tool_name == "configuration_status"

    def test_tool_description_exists(self, tool):
        """Test tool has a description."""
        assert tool.tool_description is not None
        assert len(tool.tool_description) > 0

    def test_tool_description_mentions_configuration(self, tool):
        """Test tool description mentions configuration."""
        assert "configuration" in tool.tool_description.lower()

    @pytest.mark.asyncio
    async def test_get_capabilities(self, tool):
        """Test get_capabilities action."""
        result = await tool.handle_action("get_capabilities", {})
        assert len(result) >= 1
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_get_examples(self, tool):
        """Test get_examples action."""
        result = await tool.handle_action("get_examples", {})
        assert len(result) >= 1
        assert isinstance(result[0], TextContent)


class TestOnboardingToolsCommonBehavior:
    """Test common behavior across onboarding tools."""

    def test_welcome_setup_inherits_from_tool_base(self):
        """WelcomeSetup must inherit ToolBase and expose execute()."""
        from src.revenium_mcp_server.tools_decomposed.unified_tool_base import ToolBase
        tool = WelcomeSetup()
        assert isinstance(tool, ToolBase)
        assert callable(tool.execute)

    def test_configuration_status_inherits_from_tool_base(self):
        """ConfigurationStatus must inherit ToolBase and expose execute()."""
        from src.revenium_mcp_server.tools_decomposed.unified_tool_base import ToolBase
        tool = ConfigurationStatus()
        assert isinstance(tool, ToolBase)
        assert callable(tool.execute)

    def test_tools_have_different_names(self):
        """Test tools have unique names."""
        welcome = WelcomeSetup()
        config = ConfigurationStatus()
        assert welcome.tool_name != config.tool_name
