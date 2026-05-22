"""Unit tests for Slack Configuration Management tool.

Tests the SlackConfigurationManagement class action routing, validation,
dry-run behavior, and error handling. All API calls are mocked.
"""

import os

import pytest
from unittest.mock import AsyncMock, patch


from src.revenium_mcp_server.auth.tenant_context import TenantContext
from src.revenium_mcp_server.tools_decomposed.slack_configuration_management import (
    SlackConfigurationManagement,
)
from src.revenium_mcp_server.common.error_handling import ToolError


@pytest.fixture
def config_tool():
    """Create SlackConfigurationManagement with mocked client."""
    tool = SlackConfigurationManagement()
    return tool


@pytest.fixture
def mock_client():
    """Create a mock ReveniumClient."""
    client = AsyncMock()
    client.get_slack_configurations = AsyncMock(
        return_value={
            "content": [
                {
                    "id": "cfg-1",
                    "name": "Test Config",
                    "channelName": "#test",
                    "teamName": "TestTeam",
                    "created": "2025-01-01",
                    "updated": "2025-01-02",
                }
            ],
            "totalElements": 1,
            "totalPages": 1,
        }
    )
    client.get_slack_configuration_by_id = AsyncMock(
        return_value={
            "id": "cfg-1",
            "name": "Test Config",
            "channelName": "#test",
            "teamName": "TestTeam",
            "created": "2025-01-01",
            "updated": "2025-01-02",
        }
    )
    return client


class TestSlackConfigActionRouting:
    """Test that actions are routed to the correct handler."""

    @pytest.mark.asyncio
    async def test_list_configurations_calls_api(self, config_tool, mock_client):
        with patch.object(config_tool, "get_client", return_value=mock_client):
            result = await config_tool.handle_action("list_configurations", {})
        mock_client.get_slack_configurations.assert_called_once_with(page=0, size=20)
        assert "Test Config" in result[0].text

    @pytest.mark.asyncio
    async def test_get_configuration_requires_config_id(self, config_tool, mock_client):
        with patch.object(config_tool, "get_client", return_value=mock_client):
            with pytest.raises(ToolError):
                await config_tool.handle_action("get_configuration", {})

    @pytest.mark.asyncio
    async def test_get_configuration_returns_details(self, config_tool, mock_client):
        with patch.object(config_tool, "get_client", return_value=mock_client):
            result = await config_tool.handle_action(
                "get_configuration", {"config_id": "cfg-1"}
            )
        assert "Test Config" in result[0].text
        mock_client.get_slack_configuration_by_id.assert_called_once_with("cfg-1")

    @pytest.mark.asyncio
    async def test_unknown_action_raises_tool_error(self, config_tool, mock_client):
        with patch.object(config_tool, "get_client", return_value=mock_client):
            with pytest.raises(ToolError) as exc_info:
                await config_tool.handle_action("nonexistent", {})
        assert "not supported" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_get_examples_returns_text(self, config_tool, mock_client):
        with patch.object(config_tool, "get_client", return_value=mock_client):
            result = await config_tool.handle_action("get_examples", {})
        assert "list_configurations" in result[0].text

    @pytest.mark.asyncio
    async def test_get_capabilities_returns_text(self, config_tool, mock_client):
        with patch.object(config_tool, "get_client", return_value=mock_client):
            result = await config_tool.handle_action("get_capabilities", {})
        assert "Available Actions" in result[0].text


class TestSlackConfigDryRun:
    """Test dry-run mode prevents actual API calls."""

    @pytest.mark.asyncio
    async def test_list_configurations_dry_run(self, config_tool, mock_client):
        with patch.object(config_tool, "get_client", return_value=mock_client):
            result = await config_tool.handle_action(
                "list_configurations", {"dry_run": True}
            )
        assert "Dry-run" in result[0].text
        mock_client.get_slack_configurations.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_configuration_dry_run(self, config_tool, mock_client):
        with patch.object(config_tool, "get_client", return_value=mock_client):
            result = await config_tool.handle_action(
                "get_configuration", {"config_id": "cfg-1", "dry_run": True}
            )
        assert "Dry-run" in result[0].text
        mock_client.get_slack_configuration_by_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_default_dry_run(self, config_tool, mock_client):
        with patch.object(config_tool, "get_client", return_value=mock_client):
            result = await config_tool.handle_action(
                "set_default_configuration", {"config_id": "cfg-1", "dry_run": True}
            )
        assert "Dry-run" in result[0].text
        mock_client.get_slack_configuration_by_id.assert_not_called()


class TestSlackConfigSetDefault:
    """Test set_default_configuration behavior."""

    @pytest.mark.asyncio
    async def test_set_default_sets_env_var(self, config_tool, mock_client):
        with patch.object(config_tool, "get_client", return_value=mock_client), \
             patch.dict("os.environ", {}, clear=False):
            result = await config_tool.handle_action(
                "set_default_configuration", {"config_id": "cfg-1"}
            )
        assert "Default Slack Configuration Set" in result[0].text
        assert "cfg-1" in result[0].text

    @pytest.mark.asyncio
    async def test_set_default_missing_config_id_raises(self, config_tool, mock_client):
        with patch.object(config_tool, "get_client", return_value=mock_client):
            with pytest.raises(ToolError):
                await config_tool.handle_action("set_default_configuration", {})

    @pytest.mark.asyncio
    async def test_set_default_skips_env_write_when_ctx_set(self, config_tool, mock_client):
        """Multi-tenant mode (ctx non-None) must NOT write the process-global
        REVENIUM_DEFAULT_SLACK_CONFIG_ID env var — that would leak Tenant A's
        selection into Tenant B's subsequent requests."""
        ctx = TenantContext(team_id="team-1", api_key="abcdef1234567890")

        # Capture starting env state and ensure our key is absent.
        original = os.environ.pop("REVENIUM_DEFAULT_SLACK_CONFIG_ID", None)
        try:
            with patch.object(config_tool, "get_client", return_value=mock_client):
                result = await config_tool.handle_action(
                    "set_default_configuration",
                    {"config_id": "cfg-1"},
                    ctx=ctx,
                )
            # Env var must NOT have been written.
            assert "REVENIUM_DEFAULT_SLACK_CONFIG_ID" not in os.environ
            # Response should make clear the selection is not persisted globally.
            text = result[0].text
            assert "Session" in text or "session" in text
            assert "cfg-1" in text
        finally:
            if original is not None:
                os.environ["REVENIUM_DEFAULT_SLACK_CONFIG_ID"] = original


class TestSlackConfigGetDefault:
    """Test get_default_configuration behavior."""

    @pytest.mark.asyncio
    async def test_get_default_when_none_set(self, config_tool, mock_client):
        with patch.object(config_tool, "get_client", return_value=mock_client), \
             patch(
                 "src.revenium_mcp_server.tools_decomposed.slack_configuration_management.get_config_value",
                 return_value=None,
             ):
            result = await config_tool.handle_action("get_default_configuration", {})
        assert "No Default" in result[0].text

    @pytest.mark.asyncio
    async def test_get_default_when_set(self, config_tool, mock_client):
        with patch.object(config_tool, "get_client", return_value=mock_client), \
             patch(
                 "src.revenium_mcp_server.tools_decomposed.slack_configuration_management.get_config_value",
                 return_value="cfg-1",
             ):
            result = await config_tool.handle_action("get_default_configuration", {})
        assert "Current Default" in result[0].text


class TestSlackConfigGetOAuthUrl:
    """Test get_app_oauth_url action."""

    @pytest.mark.asyncio
    async def test_generates_oauth_url(self, config_tool, mock_client):
        with patch.object(config_tool, "get_client", return_value=mock_client), \
             patch(
                 "src.revenium_mcp_server.tools_decomposed.slack_configuration_management.get_config_value",
                 return_value="https://ai.revenium.io",
             ):
            result = await config_tool.handle_action("get_app_oauth_url", {})
        assert "slack/connect" in result[0].text
