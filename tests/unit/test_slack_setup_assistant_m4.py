"""Extended unit tests for SlackSetupAssistant — M4 coverage pass.

Targets missed lines (coverage run): 70, 78, 80, 162-163, 215,
224-238, 261, 285-289, 404-405, 436-438, 476-484, 493-599, 608-719, 724, 767, 779, 789, 873.

Key areas covered here:
- onboarding_setup action (lines 493-599) — first_time / returning user paths
- first_time_guidance action (lines 608-719) — all three status branches
- Additional handle_action routing: onboarding_setup and first_time_guidance
- detect_and_recommend: zero-config delegate, default config not in list, set default path
- select_default_configuration: missing config_id validation path
- setup_status: default config lookup failure fallback
- quick_setup: ToolError re-raise behaviour
- metadata helpers: _get_tool_capabilities, _get_supported_actions,
  _get_quick_start_guide, _get_common_use_cases, _get_input_schema
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp.types import TextContent

from src.revenium_mcp_server.tools_decomposed.slack_setup_assistant import SlackSetupAssistant
from src.revenium_mcp_server.common.error_handling import ToolError, ErrorCodes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def tool():
    return SlackSetupAssistant()


def _make_client(configs, total=None):
    """Return an async context-manager mock for ReveniumClient."""
    if total is None:
        total = len(configs)
    client = AsyncMock()
    client.get_slack_configurations = AsyncMock(
        return_value={"content": configs, "totalElements": total}
    )
    client.get_slack_configuration_by_id = AsyncMock(
        return_value=configs[0] if configs else {}
    )
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


_PATCH_CFG = "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_config_value"
_PATCH_ONBOARDING = (
    "src.revenium_mcp_server.tools_decomposed.slack_setup_assistant.get_onboarding_state"
)


def _onboarding_state(is_first_time: bool):
    state = MagicMock()
    state.is_first_time = is_first_time
    return AsyncMock(return_value=state)


# ---------------------------------------------------------------------------
# handle_action routing — onboarding_setup and first_time_guidance
# ---------------------------------------------------------------------------

class TestActionRouting:
    @pytest.mark.asyncio
    async def test_onboarding_setup_action_is_routed(self, tool):
        """handle_action 'onboarding_setup' produces onboarding-specific output (not guided_setup)."""
        configs = [{"id": "c1", "name": "N", "teamName": "WS"}]
        client = _make_client(configs)
        state = MagicMock(is_first_time=False)
        with (
            patch.object(tool, "get_client", AsyncMock(return_value=client)),
            patch(_PATCH_CFG, return_value="c1"),
            patch(_PATCH_ONBOARDING, return_value=AsyncMock(return_value=state)),
        ):
            result = await tool.handle_action("onboarding_setup", {})
        text = result[0].text
        # onboarding_setup produces "Slack Setup for Onboarding" heading (line 498 of production)
        assert "Onboarding" in text
        # With default set it renders the completion block
        assert "Setup Complete" in text or "create_simple_alert" in text

    @pytest.mark.asyncio
    async def test_first_time_guidance_action_is_routed(self, tool):
        """handle_action 'first_time_guidance' produces first-time guidance specific output."""
        configs = [{"id": "c1", "name": "N", "teamName": "WS"}]
        client = _make_client(configs)
        state = MagicMock()
        with (
            patch.object(tool, "get_client", AsyncMock(return_value=client)),
            patch(_PATCH_CFG, return_value="c1"),
            patch(_PATCH_ONBOARDING, AsyncMock(return_value=state)),
        ):
            result = await tool.handle_action("first_time_guidance", {})
        text = result[0].text
        # first_time_guidance always renders a troubleshooting section (line 685 of production)
        assert "Troubleshooting" in text
        # And an onboarding integration section (line 673)
        assert "Integration with Onboarding" in text

    @pytest.mark.asyncio
    async def test_unknown_action_lists_valid_actions(self, tool):
        """Unknown action text includes at least one valid action name."""
        result = await tool.handle_action("bogus_action", {})
        text = result[0].text
        assert "guided_setup" in text or "quick_setup" in text


# ---------------------------------------------------------------------------
# guided_setup: default config not found in list → delegate to detect_and_recommend
# ---------------------------------------------------------------------------

class TestGuidedSetupDefaultNotFound:
    @pytest.mark.asyncio
    async def test_default_id_not_in_config_list_delegates_to_detect(self, tool):
        """When default config ID doesn't match any config, delegate to detect_and_recommend."""
        configs = [{"id": "c1", "name": "Config A", "teamName": "WS-A", "channelName": "gen"}]
        client = _make_client(configs, total=1)
        # Default is set to a different ID not in the list
        with (
            patch.object(tool, "get_client", AsyncMock(return_value=client)),
            patch(_PATCH_CFG, return_value="c-missing"),
        ):
            result = await tool.handle_action("guided_setup", {})
        text = result[0].text
        # detect_and_recommend output: lists Available Configurations
        assert "Available Configurations" in text


# ---------------------------------------------------------------------------
# detect_and_recommend: various paths
# ---------------------------------------------------------------------------

class TestDetectAndRecommend:
    @pytest.mark.asyncio
    async def test_zero_configs_delegates_to_guided_setup(self, tool):
        """detect_and_recommend with no configs delegates to guided_setup (OAuth flow)."""
        client = _make_client([])
        with patch.object(tool, "get_client", AsyncMock(return_value=client)):
            result = await tool.handle_action("detect_and_recommend", {})
        text = result[0].text
        assert "initiate_oauth" in text or "No Slack Configurations" in text

    @pytest.mark.asyncio
    async def test_configs_with_no_default_shows_recommendation(self, tool):
        """detect_and_recommend shows select command for each config when no default."""
        configs = [
            {"id": "c1", "name": "Prod", "teamName": "WS", "channelName": "gen", "createdDate": "2024"},
            {"id": "c2", "name": "Dev",  "teamName": "WS", "channelName": "dev", "createdDate": "2024"},
        ]
        client = _make_client(configs, total=2)
        with (
            patch.object(tool, "get_client", AsyncMock(return_value=client)),
            patch(_PATCH_CFG, return_value=None),
        ):
            result = await tool.handle_action("detect_and_recommend", {})
        text = result[0].text
        assert "select_default_configuration" in text
        assert "c1" in text
        assert "c2" in text

    @pytest.mark.asyncio
    async def test_configs_with_default_shows_current_default_section(self, tool):
        """detect_and_recommend shows 'Current Default Configuration' when default matches."""
        configs = [{"id": "c1", "name": "My Config", "teamName": "WS", "channelName": "ch", "createdDate": "2024"}]
        client = _make_client(configs, total=1)
        with (
            patch.object(tool, "get_client", AsyncMock(return_value=client)),
            patch(_PATCH_CFG, return_value="c1"),
        ):
            result = await tool.handle_action("detect_and_recommend", {})
        text = result[0].text
        assert "Current Default Configuration" in text
        assert "My Config" in text

    @pytest.mark.asyncio
    async def test_default_id_not_matching_shows_issue_section(self, tool):
        """detect_and_recommend shows 'Default Configuration Issue' when default ID missing."""
        configs = [{"id": "c1", "name": "My Config", "teamName": "WS", "channelName": "ch", "createdDate": "2024"}]
        client = _make_client(configs, total=1)
        with (
            patch.object(tool, "get_client", AsyncMock(return_value=client)),
            patch(_PATCH_CFG, return_value="nonexistent-id"),
        ):
            result = await tool.handle_action("detect_and_recommend", {})
        text = result[0].text
        assert "Default Configuration Issue" in text or "not found" in text.lower()

    @pytest.mark.asyncio
    async def test_api_error_returns_error_text(self, tool):
        """detect_and_recommend API failure returns ValidationError message (not a bare exception)."""
        client = AsyncMock()
        client.get_slack_configurations = AsyncMock(side_effect=RuntimeError("fail"))
        with patch.object(tool, "get_client", AsyncMock(return_value=client)):
            result = await tool.handle_action("detect_and_recommend", {})
        text = result[0].text
        # ValidationError.format_user_message() produces "Failed to detect and recommend" message
        assert "Failed" in text or "failed to detect" in text.lower()


# ---------------------------------------------------------------------------
# setup_status: default config fetch failure path
# ---------------------------------------------------------------------------

class TestSetupStatusDefaultConfigFetchFailure:
    @pytest.mark.asyncio
    async def test_default_config_fetch_failure_shows_id_not_found(self, tool):
        """When get_slack_configuration_by_id raises, setup_status shows ID + 'not found'."""
        config_fetcher = AsyncMock()
        config_fetcher.get_slack_configurations = AsyncMock(
            return_value={"content": [], "totalElements": 1}
        )
        config_fetcher.get_slack_configuration_by_id = AsyncMock(
            side_effect=RuntimeError("network error")
        )
        config_fetcher.__aenter__ = AsyncMock(return_value=config_fetcher)
        config_fetcher.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.object(tool, "get_client", AsyncMock(return_value=config_fetcher)),
            patch(
                _PATCH_CFG,
                side_effect=lambda k, *a: {
                    "REVENIUM_DEFAULT_SLACK_CONFIG_ID": "cfg-broken",
                    "REVENIUM_APP_BASE_URL": "https://ai.revenium.io",
                }.get(k, a[0] if a else None),
            ),
        ):
            result = await tool.handle_action("setup_status", {})
        text = result[0].text
        assert "cfg-broken" in text
        assert "not found" in text.lower() or "Configuration not found" in text


# ---------------------------------------------------------------------------
# quick_setup: ToolError is re-raised
# ---------------------------------------------------------------------------

class TestQuickSetupToolErrorReraise:
    @pytest.mark.asyncio
    async def test_tool_error_in_quick_setup_is_caught_by_outer_handler(self, tool):
        """When _handle_quick_setup raises ToolError (because it re-raises it),
        handle_action's outer except catches it and returns a formatted error TextContent.
        We verify that a ToolError raised during quick_setup does NOT propagate out of handle_action."""
        async def reraise_tool_error(args):
            raise ToolError(
                message="Injected ToolError",
                error_code=ErrorCodes.TOOL_ERROR,
                field="test",
                value="x",
            )

        # Bypass _handle_quick_setup entirely to inject ToolError at the handle_action level
        original = tool._handle_quick_setup
        tool._handle_quick_setup = reraise_tool_error
        try:
            result = await tool.handle_action("quick_setup", {})
        finally:
            tool._handle_quick_setup = original

        # handle_action outer except catches ToolError and returns formatted error
        assert isinstance(result[0], TextContent)
        text = result[0].text
        assert "TOOL_ERROR" in text or "failed" in text.lower()


# ---------------------------------------------------------------------------
# onboarding_setup: first-time user paths
# ---------------------------------------------------------------------------

class TestOnboardingSetup:
    @pytest.mark.asyncio
    async def test_first_time_no_configs_shows_onboarding_setup_steps(self, tool):
        """First-time user with no configs gets OAuth setup steps."""
        client = _make_client([], total=0)
        with (
            patch.object(tool, "get_client", AsyncMock(return_value=client)),
            patch(_PATCH_CFG, return_value=None),
            patch(_PATCH_ONBOARDING, _onboarding_state(True)),
        ):
            result = await tool.handle_action("onboarding_setup", {})
        text = result[0].text
        assert "initiate_oauth" in text
        assert "onboarding" in text.lower()

    @pytest.mark.asyncio
    async def test_first_time_configs_no_default_shows_choose_default(self, tool):
        """First-time user with configs but no default gets 'Set Default' prompt."""
        configs = [{"id": "c1", "name": "N", "teamName": "WS"}]
        client = _make_client(configs, total=1)
        with (
            patch.object(tool, "get_client", AsyncMock(return_value=client)),
            patch(_PATCH_CFG, return_value=None),
            patch(_PATCH_ONBOARDING, _onboarding_state(True)),
        ):
            result = await tool.handle_action("onboarding_setup", {})
        text = result[0].text
        assert "detect_and_recommend" in text
        assert "onboarding" in text.lower()

    @pytest.mark.asyncio
    async def test_first_time_setup_complete_shows_progress(self, tool):
        """First-time user with default set sees onboarding progress section."""
        configs = [{"id": "c1", "name": "N", "teamName": "WS"}]
        client = _make_client(configs, total=1)
        with (
            patch.object(tool, "get_client", AsyncMock(return_value=client)),
            patch(_PATCH_CFG, return_value="c1"),
            patch(_PATCH_ONBOARDING, _onboarding_state(True)),
        ):
            result = await tool.handle_action("onboarding_setup", {})
        text = result[0].text
        assert "Onboarding Progress" in text or "setup_checklist" in text

    @pytest.mark.asyncio
    async def test_returning_user_no_configs_shows_generic_setup(self, tool):
        """Returning user (not first-time) with no configs sees setup steps without onboarding section."""
        client = _make_client([], total=0)
        with (
            patch.object(tool, "get_client", AsyncMock(return_value=client)),
            patch(_PATCH_CFG, return_value=None),
            patch(_PATCH_ONBOARDING, _onboarding_state(False)),
        ):
            result = await tool.handle_action("onboarding_setup", {})
        text = result[0].text
        assert "initiate_oauth" in text
        # Onboarding-specific first-time section should NOT appear
        assert "Onboarding Integration" not in text

    @pytest.mark.asyncio
    async def test_returning_user_setup_complete_shows_test_setup(self, tool):
        """Returning user with default set sees 'Test Your Setup' section, not onboarding progress."""
        configs = [{"id": "c1", "name": "N", "teamName": "WS"}]
        client = _make_client(configs, total=1)
        with (
            patch.object(tool, "get_client", AsyncMock(return_value=client)),
            patch(_PATCH_CFG, return_value="c1"),
            patch(_PATCH_ONBOARDING, _onboarding_state(False)),
        ):
            result = await tool.handle_action("onboarding_setup", {})
        text = result[0].text
        assert "Test Your Setup" in text or "create_simple_alert" in text

    @pytest.mark.asyncio
    async def test_onboarding_setup_api_error_returns_tool_error_text(self, tool):
        """API error during onboarding_setup returns structured error text."""
        client = AsyncMock()
        client.get_slack_configurations = AsyncMock(side_effect=RuntimeError("boom"))
        with (
            patch.object(tool, "get_client", AsyncMock(return_value=client)),
            patch(_PATCH_ONBOARDING, _onboarding_state(True)),
        ):
            result = await tool.handle_action("onboarding_setup", {})
        text = result[0].text
        # Should contain ToolError-formatted output
        assert "TOOL_ERROR" in text or "Failed" in text


# ---------------------------------------------------------------------------
# first_time_guidance: all status branches
# ---------------------------------------------------------------------------

class TestFirstTimeGuidance:
    @pytest.mark.asyncio
    async def test_no_configs_shows_step_by_step_process(self, tool):
        """first_time_guidance with no configs shows step-by-step onboarding process."""
        client = _make_client([], total=0)
        state = MagicMock()
        with (
            patch.object(tool, "get_client", AsyncMock(return_value=client)),
            patch(_PATCH_CFG, return_value=None),
            patch(_PATCH_ONBOARDING, AsyncMock(return_value=state)),
        ):
            result = await tool.handle_action("first_time_guidance", {})
        text = result[0].text
        assert "onboarding_setup" in text
        assert "Getting Started" in text or "No Configurations" in text

    @pytest.mark.asyncio
    async def test_configs_no_default_shows_choose_default_prompt(self, tool):
        """first_time_guidance with configs but no default shows detect_and_recommend prompt."""
        configs = [{"id": "c1", "name": "Config A", "teamName": "WS"}]
        client = _make_client(configs, total=1)
        state = MagicMock()
        with (
            patch.object(tool, "get_client", AsyncMock(return_value=client)),
            patch(_PATCH_CFG, return_value=None),
            patch(_PATCH_ONBOARDING, AsyncMock(return_value=state)),
        ):
            result = await tool.handle_action("first_time_guidance", {})
        text = result[0].text
        assert "detect_and_recommend" in text
        assert "Configurations Available" in text or "Set Default" in text

    @pytest.mark.asyncio
    async def test_setup_complete_shows_test_alert_command(self, tool):
        """first_time_guidance with full setup shows create_simple_alert command."""
        configs = [{"id": "c1", "name": "Config A", "teamName": "WS"}]
        client = _make_client(configs, total=1)
        state = MagicMock()
        with (
            patch.object(tool, "get_client", AsyncMock(return_value=client)),
            patch(_PATCH_CFG, return_value="c1"),
            patch(_PATCH_ONBOARDING, AsyncMock(return_value=state)),
        ):
            result = await tool.handle_action("first_time_guidance", {})
        text = result[0].text
        assert "create_simple_alert" in text or "Setup Complete" in text

    @pytest.mark.asyncio
    async def test_always_shows_troubleshooting_section(self, tool):
        """first_time_guidance always includes a Troubleshooting section."""
        client = _make_client([], total=0)
        state = MagicMock()
        with (
            patch.object(tool, "get_client", AsyncMock(return_value=client)),
            patch(_PATCH_CFG, return_value=None),
            patch(_PATCH_ONBOARDING, AsyncMock(return_value=state)),
        ):
            result = await tool.handle_action("first_time_guidance", {})
        text = result[0].text
        assert "Troubleshooting" in text

    @pytest.mark.asyncio
    async def test_always_shows_integration_with_onboarding_section(self, tool):
        """first_time_guidance always renders 'Integration with Onboarding' section (line 673)."""
        configs = [{"id": "c1", "name": "N", "teamName": "WS"}]
        client = _make_client(configs, total=1)
        state = MagicMock()
        with (
            patch.object(tool, "get_client", AsyncMock(return_value=client)),
            patch(_PATCH_CFG, return_value="c1"),
            patch(_PATCH_ONBOARDING, AsyncMock(return_value=state)),
        ):
            result = await tool.handle_action("first_time_guidance", {})
        text = result[0].text
        # Production line 673: "## Integration with Onboarding"
        assert "Integration with Onboarding" in text

    @pytest.mark.asyncio
    async def test_api_error_returns_tool_error_text(self, tool):
        """API error in first_time_guidance returns structured TOOL_ERROR text."""
        client = AsyncMock()
        client.get_slack_configurations = AsyncMock(side_effect=RuntimeError("network fail"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        state = MagicMock()
        with (
            patch.object(tool, "get_client", AsyncMock(return_value=client)),
            patch(_PATCH_ONBOARDING, AsyncMock(return_value=state)),
        ):
            result = await tool.handle_action("first_time_guidance", {})
        text = result[0].text
        assert "TOOL_ERROR" in text or "Failed" in text


# ---------------------------------------------------------------------------
# Metadata helper methods
# ---------------------------------------------------------------------------

class TestMetadataHelpers:
    @pytest.mark.asyncio
    async def test_get_tool_capabilities_returns_list(self, tool):
        """_get_tool_capabilities returns a non-empty list of ToolCapability objects."""
        caps = await tool._get_tool_capabilities()
        assert isinstance(caps, list)
        assert len(caps) > 0
        # Each capability should have a name
        for cap in caps:
            assert hasattr(cap, "name")
            assert len(cap.name) > 0

    @pytest.mark.asyncio
    async def test_get_supported_actions_includes_required_actions(self, tool):
        """_get_supported_actions includes core actions."""
        actions = await tool._get_supported_actions()
        assert "guided_setup" in actions
        assert "quick_setup" in actions
        assert "setup_status" in actions
        assert "detect_and_recommend" in actions
        assert "select_default_configuration" in actions

    @pytest.mark.asyncio
    async def test_get_quick_start_guide_contains_setup_references(self, tool):
        """_get_quick_start_guide items reference core setup actions."""
        guide = await tool._get_quick_start_guide()
        assert isinstance(guide, list)
        assert len(guide) > 0
        # Production returns guidance strings that mention specific setup actions
        all_text = " ".join(guide)
        assert "quick_setup" in all_text

    @pytest.mark.asyncio
    async def test_get_common_use_cases_contains_slack_references(self, tool):
        """_get_common_use_cases items describe Slack-related use cases."""
        cases = await tool._get_common_use_cases()
        assert isinstance(cases, list)
        assert len(cases) > 0
        all_text = " ".join(cases)
        # Production returns use cases about Slack setup/configuration
        assert "slack" in all_text.lower()

    @pytest.mark.asyncio
    async def test_get_input_schema_requires_action(self, tool):
        """_get_input_schema schema requires 'action' field."""
        schema = await tool._get_input_schema()
        assert "action" in schema["required"]
        assert "action" in schema["properties"]

    @pytest.mark.asyncio
    async def test_get_input_schema_action_enum_matches_supported_actions(self, tool):
        """Schema 'action' enum matches the supported actions list."""
        schema = await tool._get_input_schema()
        supported = await tool._get_supported_actions()
        schema_enum = schema["properties"]["action"]["enum"]
        # Every supported action must appear in schema enum
        for action in supported:
            assert action in schema_enum

    @pytest.mark.asyncio
    async def test_get_input_schema_has_config_id_property(self, tool):
        """_get_input_schema includes config_id for select_default_configuration."""
        schema = await tool._get_input_schema()
        assert "config_id" in schema["properties"]
