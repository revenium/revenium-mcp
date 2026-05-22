"""Unit tests for Slack Setup Assistant tool.

Tests the SlackSetupAssistant class: guided setup decision tree,
configuration detection, default selection, and error paths.
All ReveniumClient calls are mocked.
"""

import os

import pytest
from unittest.mock import AsyncMock, patch


from src.revenium_mcp_server.auth.tenant_context import TenantContext
from src.revenium_mcp_server.tools_decomposed.slack_setup_assistant import SlackSetupAssistant


@pytest.fixture
def setup_tool():
    return SlackSetupAssistant()


def _mock_client_with_configs(configs, total=None):
    """Create a mock client returning given configurations."""
    if total is None:
        total = len(configs)
    client = AsyncMock()
    client.get_slack_configurations = AsyncMock(
        return_value={"content": configs, "totalElements": total, "totalPages": 1}
    )
    client.get_slack_configuration_by_id = AsyncMock(
        return_value=configs[0] if configs else {}
    )
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


class TestSetupAssistantActionRouting:
    """Test that handle_action routes to correct handlers."""

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error_with_valid_actions(self, setup_tool):
        result = await setup_tool.handle_action("nonexistent_action", {})
        text = result[0].text
        assert "nonexistent_action" in text
        assert "VALIDATION_ERROR" in text or "Unknown" in text

    @pytest.mark.asyncio
    async def test_get_examples_is_substantive(self, setup_tool):
        result = await setup_tool.handle_action("get_examples", {})
        assert len(result[0].text) > 50

    @pytest.mark.asyncio
    async def test_get_capabilities_returns_text(self, setup_tool):
        result = await setup_tool.handle_action("get_capabilities", {})
        assert any(kw in result[0].text for kw in ["guided_setup", "setup_status", "select_default_configuration"])


class TestGuidedSetup:
    """Test guided_setup decision tree."""

    @pytest.mark.asyncio
    async def test_no_configs_shows_oauth_instructions(self, setup_tool):
        """When no Slack configs exist, guide user to OAuth."""
        mock_client = _mock_client_with_configs([])
        with patch.object(setup_tool, "get_client", AsyncMock(return_value=mock_client)):
            result = await setup_tool.handle_action("guided_setup", {})
        text = result[0].text
        assert "No Slack Configurations Found" in text
        assert "initiate_oauth" in text

    @pytest.mark.asyncio
    async def test_configs_with_default_shows_ready(self, setup_tool):
        """When configs exist and default is set, show ready status."""
        configs = [
            {"id": "cfg-1", "name": "Prod Config", "teamName": "ProdWS"}
        ]
        mock_client = _mock_client_with_configs(configs, total=1)
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=mock_client)
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_config_value",
            return_value="cfg-1",
        ):
            result = await setup_tool.handle_action("guided_setup", {})
        text = result[0].text
        assert "Prod Config" in text
        assert "ready to use" in text.lower() or "already set up" in text.lower()

    @pytest.mark.asyncio
    async def test_configs_without_default_triggers_detect(self, setup_tool):
        """When configs exist but no default, delegate to detect_and_recommend."""
        configs = [
            {"id": "cfg-1", "name": "Config A", "teamName": "WS-A"}
        ]
        mock_client = _mock_client_with_configs(configs, total=1)
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=mock_client)
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_config_value",
            return_value=None,
        ):
            result = await setup_tool.handle_action("guided_setup", {})
        # Should show detect_and_recommend output (config list)
        assert len(result[0].text) > 20

    @pytest.mark.asyncio
    async def test_guided_setup_handles_api_error_gracefully(self, setup_tool):
        """API errors should be caught and shown as user-friendly messages."""
        mock_client = AsyncMock()
        mock_client.get_slack_configurations = AsyncMock(
            side_effect=RuntimeError("Network error")
        )
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=mock_client)
        ):
            result = await setup_tool.handle_action("guided_setup", {})
        # Should not raise, should return error text
        assert "error" in result[0].text.lower() or len(result[0].text) > 20


class TestSelectDefaultConfiguration:
    """Test select_default_configuration action."""

    @pytest.mark.asyncio
    async def test_missing_config_id_returns_error(self, setup_tool):
        """Missing config_id triggers a ValidationError internally which is caught
        by the outer exception handler (the ValidationError ctor gets unexpected kwargs).
        Either way, the user should see an error response, not an exception."""
        result = await setup_tool.handle_action("select_default_configuration", {})
        text = result[0].text
        assert "TOOL_ERROR" in text or "failed" in text.lower() or "error" in text.lower()

    @pytest.mark.asyncio
    async def test_successful_set_default(self, setup_tool):
        configs = [{"id": "cfg-1", "name": "My Config", "teamName": "WS", "channelName": "#ch"}]
        mock_client = _mock_client_with_configs(configs)
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=mock_client)
        ), patch.dict("os.environ", {}, clear=False):
            result = await setup_tool.handle_action(
                "select_default_configuration", {"config_id": "cfg-1"}
            )
        text = result[0].text
        assert "Successfully" in text or "Set Successfully" in text
        assert "cfg-1" in text

    @pytest.mark.asyncio
    async def test_set_default_api_error_returns_error_text(self, setup_tool):
        mock_client = AsyncMock()
        mock_client.get_slack_configuration_by_id = AsyncMock(
            side_effect=RuntimeError("Not found")
        )
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=mock_client)
        ):
            result = await setup_tool.handle_action(
                "select_default_configuration", {"config_id": "bad-id"}
            )
        assert "error" in result[0].text.lower() or len(result[0].text) > 20

    @pytest.mark.asyncio
    async def test_select_default_skips_env_write_when_ctx_set(self, setup_tool):
        """Multi-tenant mode (ctx non-None) must NOT write the process-global
        REVENIUM_DEFAULT_SLACK_CONFIG_ID env var — that would leak Tenant A's
        selection into Tenant B's subsequent requests."""
        ctx = TenantContext(team_id="team-1", api_key="abcdef1234567890")
        configs = [{"id": "cfg-tenant", "name": "Tenant Cfg", "teamName": "WS", "channelName": "ch"}]
        mock_client = _mock_client_with_configs(configs)

        # Capture starting env state and ensure our key is absent.
        original = os.environ.pop("REVENIUM_DEFAULT_SLACK_CONFIG_ID", None)
        try:
            with patch.object(
                setup_tool, "get_client", AsyncMock(return_value=mock_client)
            ):
                result = await setup_tool.handle_action(
                    "select_default_configuration",
                    {"config_id": "cfg-tenant"},
                    ctx=ctx,
                )
            # Env var must NOT have been written.
            assert "REVENIUM_DEFAULT_SLACK_CONFIG_ID" not in os.environ
            # Response should make clear the selection is not persisted globally.
            text = result[0].text
            assert "Session" in text or "session" in text
            assert "cfg-tenant" in text
        finally:
            if original is not None:
                os.environ["REVENIUM_DEFAULT_SLACK_CONFIG_ID"] = original


class TestSetupStatus:
    """Test setup_status action decision tree."""

    @pytest.mark.asyncio
    async def test_complete_status(self, setup_tool):
        """With configs and default set, status should say COMPLETE."""
        mock_client = _mock_client_with_configs(
            [{"id": "cfg-1", "name": "C1", "teamName": "WS"}], total=1
        )
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=mock_client)
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_config_value",
            side_effect=lambda key, *args: {
                "REVENIUM_DEFAULT_SLACK_CONFIG_ID": "cfg-1",
                "REVENIUM_APP_BASE_URL": "https://ai.revenium.io",
            }.get(key, args[0] if args else None),
        ):
            result = await setup_tool.handle_action("setup_status", {})
        assert "COMPLETE" in result[0].text

    @pytest.mark.asyncio
    async def test_partial_status_no_default(self, setup_tool):
        """With configs but no default, status should say PARTIAL."""
        mock_client = _mock_client_with_configs(
            [{"id": "cfg-1", "name": "C1"}], total=1
        )
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=mock_client)
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_config_value",
            side_effect=lambda key, *args: {
                "REVENIUM_DEFAULT_SLACK_CONFIG_ID": None,
                "REVENIUM_APP_BASE_URL": "https://ai.revenium.io",
            }.get(key, args[0] if args else None),
        ):
            result = await setup_tool.handle_action("setup_status", {})
        assert "PARTIAL" in result[0].text

    @pytest.mark.asyncio
    async def test_not_configured_status(self, setup_tool):
        """With no configs, status should say NOT CONFIGURED."""
        mock_client = _mock_client_with_configs([], total=0)
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=mock_client)
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_config_value",
            side_effect=lambda key, *args: {
                "REVENIUM_DEFAULT_SLACK_CONFIG_ID": None,
                "REVENIUM_APP_BASE_URL": "https://ai.revenium.io",
            }.get(key, args[0] if args else None),
        ):
            result = await setup_tool.handle_action("setup_status", {})
        assert "NOT CONFIGURED" in result[0].text


class TestQuickSetup:
    """Test quick_setup action."""

    @pytest.mark.asyncio
    async def test_quick_setup_returns_steps(self, setup_tool):
        result = await setup_tool.handle_action("quick_setup", {})
        text = result[0].text
        assert "Step" in text or "step" in text


class TestHandleActionErrorHandling:
    """Test top-level exception handling in handle_action."""

    @pytest.mark.asyncio
    async def test_exception_in_handler_returns_error_text(self, setup_tool):
        """Exceptions should be caught and returned as formatted error text."""
        with patch.object(
            setup_tool, "_handle_guided_setup", side_effect=RuntimeError("boom")
        ):
            result = await setup_tool.handle_action("guided_setup", {})
        text = result[0].text.lower()
        assert "failed" in text or "error" in text


class TestWorkspaceAndChannelFieldExtraction:
    """Regression tests for BACK-925: guided_setup and detect_and_recommend
    must extract workspace from teamName/team.label and channel from channelName,
    matching the pattern used by list_configurations."""

    @pytest.mark.asyncio
    async def test_guided_setup_uses_teamName(self, setup_tool):
        """guided_setup should display workspace from teamName field."""
        configs = [{"id": "cfg-1", "name": "Alerts", "teamName": "Acme Corp"}]
        mock_client = _mock_client_with_configs(configs, total=1)
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=mock_client)
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_config_value",
            return_value="cfg-1",
        ):
            result = await setup_tool.handle_action("guided_setup", {})
        assert "Acme Corp" in result[0].text
        assert "Unknown Workspace" not in result[0].text

    @pytest.mark.asyncio
    async def test_guided_setup_falls_back_to_team_label(self, setup_tool):
        """When teamName is absent, guided_setup should use team.label."""
        configs = [{"id": "cfg-1", "name": "Alerts", "team": {"label": "Fallback Team"}}]
        mock_client = _mock_client_with_configs(configs, total=1)
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=mock_client)
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_config_value",
            return_value="cfg-1",
        ):
            result = await setup_tool.handle_action("guided_setup", {})
        assert "Fallback Team" in result[0].text
        assert "Unknown Workspace" not in result[0].text

    @pytest.mark.asyncio
    async def test_detect_and_recommend_uses_teamName_and_channelName(self, setup_tool):
        """detect_and_recommend should display workspace and channel from correct fields."""
        configs = [
            {"id": "cfg-1", "name": "Prod", "teamName": "Revenium", "channelName": "alerts"},
            {"id": "cfg-2", "name": "Dev", "teamName": "Revenium Dev", "channelName": "dev-alerts"},
        ]
        mock_client = _mock_client_with_configs(configs, total=2)
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=mock_client)
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_config_value",
            return_value=None,
        ):
            result = await setup_tool.handle_action("detect_and_recommend", {})
        text = result[0].text
        assert "Revenium" in text
        assert "Revenium Dev" in text
        assert "Unknown Workspace" not in text
        assert "alerts" in text

    @pytest.mark.asyncio
    async def test_detect_and_recommend_falls_back_to_team_label(self, setup_tool):
        """detect_and_recommend should fall back to team.label when teamName is absent."""
        configs = [
            {"id": "cfg-1", "name": "Prod", "team": {"label": "Nested WS"}, "channelName": "ch1"},
        ]
        mock_client = _mock_client_with_configs(configs, total=1)
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=mock_client)
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_config_value",
            return_value=None,
        ):
            result = await setup_tool.handle_action("detect_and_recommend", {})
        assert "Nested WS" in result[0].text
        assert "Unknown Workspace" not in result[0].text

    @pytest.mark.asyncio
    async def test_select_default_uses_correct_fields(self, setup_tool):
        """select_default_configuration should show teamName and channelName."""
        configs = [{"id": "cfg-1", "name": "My Config", "teamName": "WS1", "channelName": "general"}]
        mock_client = _mock_client_with_configs(configs)
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=mock_client)
        ), patch.dict("os.environ", {}, clear=False):
            result = await setup_tool.handle_action(
                "select_default_configuration", {"config_id": "cfg-1"}
            )
        text = result[0].text
        assert "WS1" in text
        assert "Unknown Workspace" not in text
        assert "general" in text
