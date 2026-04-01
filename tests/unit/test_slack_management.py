"""Unit tests for Slack Management unified routing tool.

Tests the SlackManagement class which delegates actions to three sub-tools:
SlackConfigurationManagement, SlackOAuthWorkflow, and SlackSetupAssistant.
The key behavior is correct routing and error handling for unknown actions.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from mcp.types import TextContent

from src.revenium_mcp_server.tools_decomposed.slack_management import SlackManagement


@pytest.fixture
def slack_mgmt():
    """Create SlackManagement with mocked sub-tools to avoid real API calls."""
    with patch(
        "src.revenium_mcp_server.tools_decomposed.slack_management.SlackConfigurationManagement"
    ) as MockConfig, patch(
        "src.revenium_mcp_server.tools_decomposed.slack_management.SlackOAuthWorkflow"
    ) as MockOAuth, patch(
        "src.revenium_mcp_server.tools_decomposed.slack_management.SlackSetupAssistant"
    ) as MockSetup:
        mock_config = MockConfig.return_value
        mock_oauth = MockOAuth.return_value
        mock_setup = MockSetup.return_value

        # Each sub-tool's handle_action returns a distinguishable response
        mock_config.handle_action = AsyncMock(
            return_value=[TextContent(type="text", text="config_response")]
        )
        mock_oauth.handle_action = AsyncMock(
            return_value=[TextContent(type="text", text="oauth_response")]
        )
        mock_setup.handle_action = AsyncMock(
            return_value=[TextContent(type="text", text="setup_response")]
        )

        tool = SlackManagement()
        # Replace the sub-tool instances with our mocks
        tool.config_tool = mock_config
        tool.oauth_tool = mock_oauth
        tool.setup_tool = mock_setup
        # Rebuild routing map with the mocked tools
        tool.action_routing = {
            "list_configurations": mock_config,
            "get_configuration": mock_config,
            "set_default_configuration": mock_config,
            "get_default_configuration": mock_config,
            "get_app_oauth_url": mock_config,
            "initiate_oauth": mock_oauth,
            "refresh_configurations": mock_oauth,
            "check_new_configurations": mock_oauth,
            "get_oauth_instructions": mock_oauth,
            "guided_setup": mock_setup,
            "quick_setup": mock_setup,
            "onboarding_setup": mock_setup,
            "first_time_guidance": mock_setup,
            "setup_status": mock_setup,
            "detect_and_recommend": mock_setup,
            "select_default_configuration": mock_setup,
        }
        yield tool


class TestSlackManagementRouting:
    """Test that actions are routed to the correct sub-tool."""

    @pytest.mark.asyncio
    async def test_config_action_delegates_to_config_tool(self, slack_mgmt):
        result = await slack_mgmt.handle_action("list_configurations", {"page": 0})
        assert result[0].text == "config_response"
        slack_mgmt.config_tool.handle_action.assert_called_once_with(
            "list_configurations", {"page": 0}
        )

    @pytest.mark.asyncio
    async def test_oauth_action_delegates_to_oauth_tool(self, slack_mgmt):
        result = await slack_mgmt.handle_action("initiate_oauth", {})
        assert result[0].text == "oauth_response"
        slack_mgmt.oauth_tool.handle_action.assert_called_once_with("initiate_oauth", {})

    @pytest.mark.asyncio
    async def test_setup_action_delegates_to_setup_tool(self, slack_mgmt):
        result = await slack_mgmt.handle_action("guided_setup", {})
        assert result[0].text == "setup_response"
        slack_mgmt.setup_tool.handle_action.assert_called_once_with("guided_setup", {})

    @pytest.mark.asyncio
    async def test_get_capabilities_returns_capabilities_text(self, slack_mgmt):
        result = await slack_mgmt.handle_action("get_capabilities", {})
        text = result[0].text
        assert "Configuration Management" in text
        assert "OAuth Workflow" in text
        assert "Setup Assistant" in text

    @pytest.mark.asyncio
    async def test_get_examples_returns_examples_text(self, slack_mgmt):
        result = await slack_mgmt.handle_action("get_examples", {})
        text = result[0].text
        assert "list_configurations" in text
        assert "initiate_oauth" in text
        assert "guided_setup" in text


class TestSlackManagementUnknownAction:
    """Test error handling for unknown actions."""

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error_with_valid_actions(self, slack_mgmt):
        result = await slack_mgmt.handle_action("nonexistent_action", {})
        text = result[0].text.lower()
        assert "unknown" in text or "nonexistent_action" in text

    @pytest.mark.asyncio
    async def test_unknown_action_suggests_categories(self, slack_mgmt):
        result = await slack_mgmt.handle_action("bad_action", {})
        text = result[0].text
        # Should include references to valid action categories
        assert "configuration" in text.lower() or "oauth" in text.lower() or "setup" in text.lower()


class TestSlackManagementErrorPropagation:
    """Test that exceptions from sub-tools propagate correctly."""

    @pytest.mark.asyncio
    async def test_subtool_exception_propagates(self, slack_mgmt):
        slack_mgmt.config_tool.handle_action = AsyncMock(
            side_effect=RuntimeError("API unavailable")
        )
        with pytest.raises(RuntimeError, match="API unavailable"):
            await slack_mgmt.handle_action("list_configurations", {})
