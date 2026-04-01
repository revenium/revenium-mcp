"""Unit tests for Slack OAuth Workflow tool.

Tests the SlackOAuthWorkflow class action routing, dry-run mode,
OAuth URL generation, and error handling.
"""

import pytest
from unittest.mock import AsyncMock, patch

from mcp.types import TextContent

from src.revenium_mcp_server.tools_decomposed.slack_oauth_workflow import SlackOAuthWorkflow
from src.revenium_mcp_server.common.error_handling import ToolError


@pytest.fixture
def oauth_tool():
    return SlackOAuthWorkflow()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get_slack_configurations = AsyncMock(
        return_value={
            "content": [
                {
                    "id": "sc-1",
                    "name": "OAuth Config",
                    "channelName": "#alerts",
                    "teamName": "OAuthTeam",
                    "created": "2025-03-01",
                }
            ],
            "totalElements": 1,
            "totalPages": 1,
        }
    )
    return client


class TestOAuthRouting:
    """Test action routing to correct handlers."""

    @pytest.mark.asyncio
    async def test_initiate_oauth_generates_url(self, oauth_tool):
        with patch.object(oauth_tool, "get_client", return_value=AsyncMock()), \
             patch(
                 "src.revenium_mcp_server.tools_decomposed.slack_oauth_workflow.get_config_value",
                 return_value="https://ai.revenium.io",
             ):
            result = await oauth_tool.handle_action("initiate_oauth", {})
        text = result[0].text
        assert "slack/connect" in text
        assert "logged into Revenium" in text

    @pytest.mark.asyncio
    async def test_initiate_oauth_custom_return_to(self, oauth_tool):
        with patch.object(oauth_tool, "get_client", return_value=AsyncMock()), \
             patch(
                 "src.revenium_mcp_server.tools_decomposed.slack_oauth_workflow.get_config_value",
                 return_value="https://ai.revenium.io",
             ):
            result = await oauth_tool.handle_action(
                "initiate_oauth", {"return_to": "/custom-page"}
            )
        assert "/custom-page" in result[0].text

    @pytest.mark.asyncio
    async def test_get_oauth_instructions(self, oauth_tool):
        with patch.object(oauth_tool, "get_client", return_value=AsyncMock()):
            result = await oauth_tool.handle_action("get_oauth_instructions", {})
        assert "Troubleshooting" in result[0].text

    @pytest.mark.asyncio
    async def test_refresh_configurations(self, oauth_tool, mock_client):
        with patch.object(oauth_tool, "get_client", return_value=mock_client):
            result = await oauth_tool.handle_action("refresh_configurations", {})
        assert "OAuth Config" in result[0].text
        mock_client.get_slack_configurations.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_new_configurations(self, oauth_tool, mock_client):
        with patch.object(oauth_tool, "get_client", return_value=mock_client):
            result = await oauth_tool.handle_action("check_new_configurations", {})
        assert "OAuth Config" in result[0].text

    @pytest.mark.asyncio
    async def test_get_examples(self, oauth_tool):
        with patch.object(oauth_tool, "get_client", return_value=AsyncMock()):
            result = await oauth_tool.handle_action("get_examples", {})
        assert "initiate_oauth" in result[0].text

    @pytest.mark.asyncio
    async def test_get_capabilities(self, oauth_tool):
        with patch.object(oauth_tool, "get_client", return_value=AsyncMock()):
            result = await oauth_tool.handle_action("get_capabilities", {})
        assert "OAuth" in result[0].text


class TestOAuthDryRun:
    """Test dry-run mode across OAuth actions."""

    @pytest.mark.asyncio
    async def test_initiate_oauth_dry_run(self, oauth_tool):
        with patch.object(oauth_tool, "get_client", return_value=AsyncMock()):
            result = await oauth_tool.handle_action("initiate_oauth", {"dry_run": True})
        assert "Dry-run" in result[0].text

    @pytest.mark.asyncio
    async def test_refresh_configurations_dry_run(self, oauth_tool, mock_client):
        with patch.object(oauth_tool, "get_client", return_value=mock_client):
            result = await oauth_tool.handle_action(
                "refresh_configurations", {"dry_run": True}
            )
        assert "Dry-run" in result[0].text
        mock_client.get_slack_configurations.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_new_configurations_dry_run(self, oauth_tool, mock_client):
        with patch.object(oauth_tool, "get_client", return_value=mock_client):
            result = await oauth_tool.handle_action(
                "check_new_configurations", {"dry_run": True}
            )
        assert "Dry-run" in result[0].text
        mock_client.get_slack_configurations.assert_not_called()


class TestOAuthUnknownAction:
    """Test error handling for unknown actions."""

    @pytest.mark.asyncio
    async def test_unknown_action_raises_tool_error(self, oauth_tool):
        with patch.object(oauth_tool, "get_client", return_value=AsyncMock()):
            with pytest.raises(ToolError) as exc_info:
                await oauth_tool.handle_action("nonexistent", {})
        assert "not supported" in str(exc_info.value).lower()
