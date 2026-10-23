"""Unit tests for Slack Setup Assistant tool.

Tests the SlackSetupAssistant class: guided setup decision tree,
configuration detection, default selection, and error paths.
All ReveniumClient calls are mocked.
"""

import math
import os

import pytest
from unittest.mock import AsyncMock, patch


from src.revenium_mcp_server.auth.tenant_context import TenantContext
from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tools_decomposed.slack_config_formatters import (
    format_single_config_summary,
)
from src.revenium_mcp_server.tools_decomposed.slack_setup_assistant import (
    SETUP_RECOMMENDATIONS,
    DefaultLookup,
    SetupState,
    SlackSetupAssistant,
    classify_setup,
    find_default_configuration,
)


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
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_default_slack_config_id",
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
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_default_slack_config_id",
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
        """A hosted organization's choice must NOT write the process-global
        REVENIUM_DEFAULT_SLACK_CONFIG_ID env var; that would leak Tenant A's
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
            text = result[0].text
            assert "your organization on this server" in text
            assert ".env" not in text
            assert "cfg-tenant" in text
        finally:
            if original is not None:
                os.environ["REVENIUM_DEFAULT_SLACK_CONFIG_ID"] = original


    @pytest.mark.asyncio
    async def test_select_default_with_an_unknown_id_is_a_not_found_error(self, setup_tool):
        mock_client = AsyncMock()
        mock_client.get_slack_configuration_by_id = AsyncMock(
            side_effect=ReveniumAPIError("HTTP 403: Access Denied", status_code=403)
        )
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=mock_client)
        ), patch.dict("os.environ", {}, clear=False), pytest.raises(ToolError) as raised:
            await setup_tool.handle_action(
                "select_default_configuration", {"config_id": "RdKdRMz"}
            )
        text = str(raised.value)
        assert "not found or is not in your organization" in text
        assert "Access Denied" not in text


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
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_default_slack_config_id",
            return_value="cfg-1",
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
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_default_slack_config_id",
            return_value=None,
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
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_default_slack_config_id",
            return_value=None,
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
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_default_slack_config_id",
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
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_default_slack_config_id",
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
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_default_slack_config_id",
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
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_default_slack_config_id",
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


class TestChannelAndCreatedMatchTheConfigurationList:
    """BACK-4679: detect_and_recommend and select_default_configuration print the
    channel name and creation date the way list_configurations does."""

    @pytest.mark.asyncio
    async def test_detect_and_recommend_prints_channel_and_created_like_list_configurations(
        self, setup_tool
    ):
        configs = [
            {
                "id": "cfg-1",
                "name": "Clerk Dev",
                "teamName": "WS",
                "channelName": "#clerk-dev",
                "created": "2026-02-18T04:16:23.476Z",
            },
            {
                "id": "cfg-2",
                "name": "Gabriel DM",
                "teamName": "WS",
                "channelName": "@gabriel.sabadin",
                "created": "2026-03-01T10:00:00.000Z",
            },
            {
                "id": "cfg-3",
                "name": "AI Prod",
                "teamName": "WS",
                "channelName": "ai-prod-cost-alerts",
                "created": "2026-04-02T11:30:00.000Z",
            },
        ]
        mock_client = _mock_client_with_configs(configs)
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=mock_client)
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_default_slack_config_id",
            return_value="cfg-1",
        ):
            result = await setup_tool.handle_action("detect_and_recommend", {})
        text = result[0].text

        assert "##clerk-dev" not in text
        assert "#@gabriel.sabadin" not in text
        assert "Created:** Unknown" not in text
        assert "- Channel: #clerk-dev\n" in text
        for i, c in enumerate(configs, 1):
            for line in format_single_config_summary(c, i).splitlines():
                if line.startswith("- **Channel:**") or line.startswith("- **Created:**"):
                    assert line + "\n" in text

    @pytest.mark.asyncio
    async def test_detect_and_recommend_prints_a_missing_channel_and_date_as_unknown(
        self, setup_tool
    ):
        configs = [{"id": "cfg-1", "name": "Bare", "teamName": "WS"}]
        mock_client = _mock_client_with_configs(configs)
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=mock_client)
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_default_slack_config_id",
            return_value=None,
        ):
            result = await setup_tool.handle_action("detect_and_recommend", {})
        text = result[0].text

        assert "- **Channel:** N/A\n" in text
        assert "#N/A" not in text
        assert "- **Created:** Unknown\n" in text

    @pytest.mark.asyncio
    async def test_select_default_configuration_prints_the_channel_name_as_sent(
        self, setup_tool
    ):
        configs = [{"id": "cfg-1", "name": "Ops", "teamName": "WS", "channelName": "#ops"}]
        mock_client = _mock_client_with_configs(configs)
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=mock_client)
        ), patch.dict("os.environ", {}, clear=False):
            result = await setup_tool.handle_action(
                "select_default_configuration", {"config_id": "cfg-1"}
            )
        text = result[0].text

        assert "- **Channel:** #ops\n" in text
        assert "##ops" not in text


_PATCH_DEFAULT = (
    "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_default_slack_config_id"
)


def _paged_client(total):
    """A client whose organization holds `total` configurations, one page read at a time."""
    every = [
        {"id": f"cfg-{i}", "name": f"Config {i}", "teamName": "WS", "channelName": f"ch-{i}"}
        for i in range(total)
    ]
    by_id = {c["id"]: c for c in every}

    async def get_by_id(config_id):
        if config_id not in by_id:
            raise ReveniumAPIError("HTTP 403: Access Denied", status_code=403)
        return by_id[config_id]

    async def list_page(page=0, size=20):
        return {
            "content": every[page * size : (page + 1) * size],
            "totalElements": total,
            "totalPages": math.ceil(total / size),
        }

    client = AsyncMock()
    client.get_slack_configurations = AsyncMock(side_effect=list_page)
    client.get_slack_configuration_by_id = AsyncMock(side_effect=get_by_id)
    return client


class TestPartialListsAndStaleDefaults:
    """BACK-4742: a partial list says so, and a missing default is never ready."""

    @pytest.mark.asyncio
    async def test_detect_and_recommend_says_it_shows_20_of_32(self, setup_tool):
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=_paged_client(32))
        ), patch(_PATCH_DEFAULT, return_value=None):
            result = await setup_tool.handle_action("detect_and_recommend", {})
        text = result[0].text
        assert "Showing 20 of 32 configurations" in text
        assert "list_configurations', page=1, size=20" in text

    @pytest.mark.asyncio
    async def test_detect_and_recommend_names_the_last_page_when_the_rest_spans_several(
        self, setup_tool
    ):
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=_paged_client(50))
        ), patch(_PATCH_DEFAULT, return_value=None):
            result = await setup_tool.handle_action("detect_and_recommend", {})
        text = result[0].text
        assert "Showing 20 of 50 configurations" in text
        assert "page=1, size=20)` through `page=2`." in text

    @pytest.mark.asyncio
    async def test_detect_and_recommend_names_only_page_1_when_one_page_is_left(
        self, setup_tool
    ):
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=_paged_client(32))
        ), patch(_PATCH_DEFAULT, return_value=None):
            result = await setup_tool.handle_action("detect_and_recommend", {})
        text = result[0].text
        assert "list_configurations', page=1, size=20)`.\n" in text
        assert "` through `page=" not in text

    @pytest.mark.asyncio
    async def test_detect_and_recommend_does_not_note_a_complete_list(self, setup_tool):
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=_paged_client(3))
        ), patch(_PATCH_DEFAULT, return_value=None):
            result = await setup_tool.handle_action("detect_and_recommend", {})
        text = result[0].text
        assert "Showing 3 of" not in text
        assert "configurations. See the rest with" not in text

    @pytest.mark.asyncio
    async def test_detect_and_recommend_finds_a_default_beyond_the_first_page(self, setup_tool):
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=_paged_client(32))
        ), patch(_PATCH_DEFAULT, return_value="cfg-30"):
            result = await setup_tool.handle_action("detect_and_recommend", {})
        text = result[0].text
        assert "## Current Default Configuration\n**Config 30**" in text
        assert "Default Configuration Issue" not in text

    @pytest.mark.asyncio
    async def test_guided_setup_finds_a_default_beyond_the_first_page(self, setup_tool):
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=_paged_client(32))
        ), patch(_PATCH_DEFAULT, return_value="cfg-30"):
            result = await setup_tool.handle_action("guided_setup", {})
        assert "**Current Default:** Config 30 (WS)" in result[0].text

    @pytest.mark.asyncio
    async def test_setup_status_with_a_stale_default_is_not_ready(self, setup_tool):
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=_paged_client(32))
        ), patch(_PATCH_DEFAULT, return_value="cfg-gone"):
            result = await setup_tool.handle_action("setup_status", {})
        text = result[0].text
        assert "## Setup Status: **NOT READY**" in text
        assert "COMPLETE" not in text
        assert "ready to use" not in text
        assert "`cfg-gone` (Configuration not found or not in your organization)" in text
        assert "detect_and_recommend" in text

    @pytest.mark.asyncio
    async def test_setup_status_with_a_live_default_is_complete(self, setup_tool):
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=_paged_client(32))
        ), patch(_PATCH_DEFAULT, return_value="cfg-30"):
            result = await setup_tool.handle_action("setup_status", {})
        text = result[0].text
        assert "## Setup Status: **COMPLETE**" in text
        assert "**Default Config Name:** Config 30" in text


def _client_whose_default_read_fails(total=32):
    client = _paged_client(total)
    client.get_slack_configuration_by_id = AsyncMock(
        side_effect=ReveniumAPIError("HTTP 503: Service Unavailable", status_code=503)
    )
    return client


class TestUnreadableDefault:
    """A default that cannot be read right now is neither missing nor a failed answer."""

    @pytest.mark.asyncio
    async def test_detect_and_recommend_keeps_the_list_when_the_default_read_fails(
        self, setup_tool
    ):
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=_client_whose_default_read_fails())
        ), patch(_PATCH_DEFAULT, return_value="cfg-30"):
            result = await setup_tool.handle_action("detect_and_recommend", {})
        text = result[0].text
        assert "Failed to detect" not in text
        assert "## Available Configurations" in text
        assert "`cfg-30` could not be read right now (HTTP 503: Service Unavailable)" in text
        assert "was not found" not in text

    @pytest.mark.asyncio
    async def test_guided_setup_keeps_the_list_when_the_default_read_fails(self, setup_tool):
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=_client_whose_default_read_fails())
        ), patch(_PATCH_DEFAULT, return_value="cfg-30"):
            result = await setup_tool.handle_action("guided_setup", {})
        text = result[0].text
        assert "Failed to perform guided setup" not in text
        assert "## Available Configurations" in text
        assert "could not be read right now" in text

    @pytest.mark.asyncio
    async def test_setup_status_asks_to_retry_instead_of_replacing_the_default(
        self, setup_tool
    ):
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=_client_whose_default_read_fails())
        ), patch(_PATCH_DEFAULT, return_value="cfg-30"):
            result = await setup_tool.handle_action("setup_status", {})
        text = result[0].text
        assert "## Setup Status: **UNKNOWN**" in text
        assert "NOT READY" not in text
        assert "choose another default" not in text.lower()
        assert "Configuration not found" not in text
        assert "**Retry the Status Check:**" in text


class TestOneSetupStatePerAnswer:
    """setup_status picks its state once; header and recommendation both read it."""

    @pytest.mark.parametrize(
        "total, lookup, expected",
        [
            (3, DefaultLookup.missing_from_platform("cfg-gone"), SetupState.NOT_READY),
            (3, DefaultLookup.unreadable_now("cfg-1", "HTTP 503"), SetupState.UNKNOWN),
            (3, DefaultLookup.found_as("cfg-1", {"id": "cfg-1"}), SetupState.COMPLETE),
            (3, DefaultLookup.nothing_saved(), SetupState.PARTIAL),
            (0, DefaultLookup.nothing_saved(), SetupState.NOT_CONFIGURED),
            (0, DefaultLookup.missing_from_platform("cfg-gone"), SetupState.NOT_CONFIGURED),
            (0, DefaultLookup.unreadable_now("cfg-1", "HTTP 503"), SetupState.NOT_CONFIGURED),
        ],
    )
    def test_each_combination_lands_in_one_state(self, total, lookup, expected):
        assert classify_setup(total, lookup).state is expected

    def test_every_state_has_a_recommendation(self):
        assert set(SETUP_RECOMMENDATIONS) == set(SetupState)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "default_id, client_factory, expected",
        [
            ("cfg-gone", lambda: _paged_client(32), SetupState.NOT_READY),
            ("cfg-30", lambda: _client_whose_default_read_fails(), SetupState.UNKNOWN),
            ("cfg-30", lambda: _paged_client(32), SetupState.COMPLETE),
            (None, lambda: _paged_client(32), SetupState.PARTIAL),
            (None, lambda: _mock_client_with_configs([], total=0), SetupState.NOT_CONFIGURED),
        ],
    )
    async def test_header_and_recommendation_name_the_same_state(
        self, setup_tool, default_id, client_factory, expected
    ):
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=client_factory())
        ), patch(_PATCH_DEFAULT, return_value=default_id):
            result = await setup_tool.handle_action("setup_status", {})
        text = result[0].text
        assert f"## Setup Status: **{expected.value}**" in text
        recommendations = text.split("## Recommendations", 1)[1]
        assert recommendations.lstrip().startswith(SETUP_RECOMMENDATIONS[expected].lead)


_SELECT_OPTION = "slack_management(action='select_default_configuration', config_id='cfg-0')"


class TestOneWayToSayNoDefault:
    """A default that was never saved is never read as a stale one."""

    def test_no_saved_default_is_not_missing(self):
        assert DefaultLookup.nothing_saved().missing is False
        assert DefaultLookup.nothing_saved().needs_choice is True

    def test_a_saved_default_that_was_not_found_is_missing(self):
        assert DefaultLookup.missing_from_platform("cfg-gone").missing is True
        assert DefaultLookup.missing_from_platform("cfg-gone").needs_choice is True

    @pytest.mark.parametrize(
        "lookup",
        [
            DefaultLookup.found_as("cfg-1", {"id": "cfg-1"}),
            DefaultLookup.unreadable_now("cfg-1", "HTTP 503"),
        ],
    )
    def test_a_found_or_unreadable_default_needs_no_choice(self, lookup):
        assert lookup.missing is False
        assert lookup.needs_choice is False


class TestStaleDefaultOffersAChoice:
    """NOT READY sends the caller to detect_and_recommend, which must offer the replacement."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["detect_and_recommend", "guided_setup"])
    async def test_a_stale_default_lists_select_default_configuration_options(
        self, setup_tool, action
    ):
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=_paged_client(32))
        ), patch(_PATCH_DEFAULT, return_value="cfg-gone"):
            result = await setup_tool.handle_action(action, {})
        text = result[0].text
        assert "Default ID `cfg-gone` was not found" in text
        assert "**Set a Default Configuration**" in text
        assert _SELECT_OPTION in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["detect_and_recommend", "guided_setup"])
    async def test_an_unreadable_default_is_not_offered_a_replacement(self, setup_tool, action):
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=_client_whose_default_read_fails())
        ), patch(_PATCH_DEFAULT, return_value="cfg-30"):
            result = await setup_tool.handle_action(action, {})
        assert _SELECT_OPTION not in result[0].text

    @pytest.mark.asyncio
    async def test_a_found_default_is_not_offered_a_replacement(self, setup_tool):
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=_paged_client(32))
        ), patch(_PATCH_DEFAULT, return_value="cfg-30"):
            result = await setup_tool.handle_action("detect_and_recommend", {})
        assert _SELECT_OPTION not in result[0].text


def _client_whose_default_read_answers(error):
    client = _paged_client(32)
    client.get_slack_configuration_by_id = AsyncMock(side_effect=error)
    return client


class TestUndecodableDefaultIsMissing:
    """The platform answers 400 "failed to decode hashed id" for an id it holds no record of."""

    @pytest.mark.asyncio
    async def test_setup_status_calls_an_undecodable_default_not_ready(self, setup_tool):
        error = ReveniumAPIError(
            "Invalid Slack Configuration ID",
            status_code=400,
            response_data={"error_data": {"error": "Failed to decode hashed Id: [cfg-typo]"}},
        )
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=_client_whose_default_read_answers(error))
        ), patch(_PATCH_DEFAULT, return_value="cfg-typo"):
            result = await setup_tool.handle_action("setup_status", {})
        text = result[0].text
        assert "## Setup Status: **NOT READY**" in text
        assert "`cfg-typo` (Configuration not found or not in your organization)" in text
        assert "Retry the Status Check" not in text

    @pytest.mark.asyncio
    async def test_setup_status_keeps_another_400_unknown(self, setup_tool):
        error = ReveniumAPIError("HTTP 400: Bad Request", status_code=400, response_data={})
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=_client_whose_default_read_answers(error))
        ), patch(_PATCH_DEFAULT, return_value="cfg-30"):
            result = await setup_tool.handle_action("setup_status", {})
        assert "## Setup Status: **UNKNOWN**" in result[0].text


class TestNoConfigurationsOutranksAStaleDefault:
    """Deleting the only configuration while it was the default leaves nothing to choose."""

    @pytest.mark.asyncio
    async def test_setup_status_sends_a_stale_default_with_no_configurations_to_quick_setup(
        self, setup_tool
    ):
        client = _mock_client_with_configs([], total=0)
        client.get_slack_configuration_by_id = AsyncMock(
            side_effect=ReveniumAPIError("HTTP 404: Not Found", status_code=404)
        )
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=client)
        ), patch(_PATCH_DEFAULT, return_value="cfg-gone"):
            result = await setup_tool.handle_action("setup_status", {})
        text = result[0].text
        assert "## Setup Status: **NOT CONFIGURED**" in text
        assert "choose another default" not in text.lower()
        recommendations = text.split("## Recommendations", 1)[1]
        assert "slack_management(action='quick_setup')" in recommendations


class TestSetupStatusReadsTheDefaultFromItsPage:
    """setup_status hands its list page to the default lookup instead of reading by id again."""

    @pytest.mark.asyncio
    async def test_a_default_on_the_page_is_not_read_again(self, setup_tool):
        client = _paged_client(3)
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=client)
        ), patch(_PATCH_DEFAULT, return_value="cfg-1"):
            result = await setup_tool.handle_action("setup_status", {})
        assert "## Setup Status: **COMPLETE**" in result[0].text
        client.get_slack_configuration_by_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_configurations_skips_the_default_read(self, setup_tool):
        client = _paged_client(0)
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=client)
        ), patch(_PATCH_DEFAULT, return_value="cfg-gone"):
            result = await setup_tool.handle_action("setup_status", {})
        text = result[0].text
        assert "## Setup Status: **NOT CONFIGURED**" in text
        assert "- **Default Configuration:** Set" in text
        client.get_slack_configuration_by_id.assert_not_awaited()


_UNDECODABLE_ID = ReveniumAPIError(
    "Invalid Slack Configuration ID",
    status_code=400,
    response_data={"error_data": {"error": "Failed to decode hashed Id: [cfg-x]"}},
)


class TestDefaultReadClassification:
    """One rule decides whether a failed default read means missing or unreadable."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [
            ReveniumAPIError("HTTP 404: Not Found", status_code=404),
            _UNDECODABLE_ID,
            ReveniumAPIError("HTTP 403: Access Denied", status_code=403),
        ],
        ids=["404", "400-undecodable-id", "403-missing-or-foreign"],
    )
    async def test_an_answer_naming_no_readable_configuration_is_missing(self, error):
        client = _client_whose_default_read_answers(error)
        lookup = await find_default_configuration(client, [], "cfg-x")
        assert lookup.missing is True
        assert lookup.unreadable is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [
            ReveniumAPIError("HTTP 503: Service Unavailable", status_code=503),
            ReveniumAPIError("HTTP 400: Bad Request", status_code=400, response_data={}),
            ReveniumAPIError("HTTP 401: Unauthorized", status_code=401),
            TimeoutError("read timed out"),
        ],
        ids=["503", "other-400", "401", "non-api-error"],
    )
    async def test_any_other_failure_is_a_read_error(self, error):
        client = _client_whose_default_read_answers(error)
        lookup = await find_default_configuration(client, [], "cfg-x")
        assert lookup.unreadable is True
        assert lookup.read_error == str(error)

    @pytest.mark.asyncio
    async def test_a_readable_default_carries_its_configuration(self):
        lookup = await find_default_configuration(_paged_client(32), [], "cfg-30")
        assert lookup.found is True
        assert lookup.config["id"] == "cfg-30"

    @pytest.mark.asyncio
    async def test_setup_status_names_a_403_default_as_missing_or_foreign(self, setup_tool):
        error = ReveniumAPIError("HTTP 403: Access Denied", status_code=403)
        with patch.object(
            setup_tool, "get_client", AsyncMock(return_value=_client_whose_default_read_answers(error))
        ), patch(_PATCH_DEFAULT, return_value="cfg-x"):
            result = await setup_tool.handle_action("setup_status", {})
        text = result[0].text
        assert "## Setup Status: **NOT READY**" in text
        assert "was not found or is not in your organization" in text
        assert "`cfg-x` (Configuration not found or not in your organization)" in text
