"""Unit tests for Welcome and Setup tool.

Tests the WelcomeSetup class: action routing, welcome message decision tree,
setup checklist, environment status, next steps, complete setup flow,
and error handling.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from mcp.types import TextContent

from src.revenium_mcp_server.tools_decomposed.welcome_setup import WelcomeSetup


@pytest.fixture
def welcome_tool():
    return WelcomeSetup()


def _mock_validation_result(api_status="success", auto_discovery=True):
    """Create a mock validation result."""
    result = MagicMock()
    result.summary = {
        "overall_status": api_status == "success",
        "auto_discovery_works": auto_discovery,
        "api_key_available": True,
        "required_fields_discovered": True,
        "email_discovered": True,
        "direct_api_works": True,
        "auth_config_works": True,
        "configuration_method": "auto",
    }
    result.api_connectivity = {"status": api_status}
    result.timestamp = datetime(2025, 3, 10, 12, 0, 0)
    result.variables = {
        "REVENIUM_API_KEY": MagicMock(
            is_set=True,
            required=True,
            auto_discoverable=False,
            display_value="SET (hidden)",
            description="API Key",
            category="Authentication",
        ),
    }
    return result


def _mock_onboarding_state(
    is_first_time=True,
    api_key=True,
    team_id=True,
    email=False,
    slack=False,
    auto_discovery=False,
):
    state = MagicMock()
    state.is_first_time = is_first_time
    state.setup_completion = {
        "api_key_configured": api_key,
        "team_id_configured": team_id,
        "email_configured": email,
        "slack_configured": slack,
        "auto_discovery_working": auto_discovery,
    }
    state.recommendations = ["Set up email", "Configure Slack"]
    return state


class TestWelcomeActionRouting:
    """Test handle_action routes correctly."""

    @pytest.mark.asyncio
    async def test_empty_action_defaults_to_show_welcome(self, welcome_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.get_onboarding_state",
            return_value=_mock_onboarding_state(),
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.validate_environment_variables",
            return_value=_mock_validation_result(),
        ):
            result = await welcome_tool.handle_action("", {})
        assert isinstance(result[0], TextContent)
        assert "welcome" in result[0].text.lower() or len(result[0].text) > 50

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self, welcome_tool):
        result = await welcome_tool.handle_action("nonexistent", {})
        text = result[0].text.lower()
        assert "unknown" in text

    @pytest.mark.asyncio
    async def test_help_action_returns_usage(self, welcome_tool):
        result = await welcome_tool.handle_action("help", {})
        assert "show_welcome" in result[0].text

    @pytest.mark.asyncio
    async def test_get_actions_alias_works(self, welcome_tool):
        result = await welcome_tool.handle_action("get_actions", {})
        assert "show_welcome" in result[0].text

    @pytest.mark.asyncio
    async def test_get_examples(self, welcome_tool):
        result = await welcome_tool.handle_action("get_examples", {})
        assert "show_welcome" in result[0].text

    @pytest.mark.asyncio
    async def test_get_capabilities(self, welcome_tool):
        result = await welcome_tool.handle_action("get_capabilities", {})
        assert "Available Actions" in result[0].text


class TestShowWelcome:
    """Test show_welcome decision tree."""

    @pytest.mark.asyncio
    async def test_first_time_auto_discovery_complete_with_slack(self, welcome_tool):
        """Auto-discovery complete + slack = streamlined welcome."""
        state = _mock_onboarding_state(
            is_first_time=True,
            api_key=True,
            team_id=True,
            email=True,
            slack=True,
            auto_discovery=True,
        )
        with patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.get_onboarding_state",
            return_value=state,
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.validate_environment_variables",
            return_value=_mock_validation_result(),
        ):
            result = await welcome_tool.handle_action("show_welcome", {})
        text = result[0].text
        assert "Welcome" in text
        assert "complete" in text.lower() or "all set" in text.lower()

    @pytest.mark.asyncio
    async def test_first_time_auto_discovery_complete_without_slack(self, welcome_tool):
        """Auto-discovery complete but no slack = suggests slack setup."""
        state = _mock_onboarding_state(
            is_first_time=True,
            api_key=True,
            team_id=True,
            email=True,
            slack=False,
            auto_discovery=True,
        )
        with patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.get_onboarding_state",
            return_value=state,
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.validate_environment_variables",
            return_value=_mock_validation_result(),
        ):
            result = await welcome_tool.handle_action("show_welcome", {})
        text = result[0].text
        assert "slack" in text.lower() or "Slack" in text

    @pytest.mark.asyncio
    async def test_first_time_no_auto_discovery_shows_detailed_setup(self, welcome_tool):
        """Without auto-discovery, show traditional detailed setup."""
        state = _mock_onboarding_state(
            is_first_time=True,
            api_key=True,
            team_id=False,
            email=False,
            auto_discovery=False,
        )
        with patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.get_onboarding_state",
            return_value=state,
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.validate_environment_variables",
            return_value=_mock_validation_result(api_status="failed"),
        ):
            result = await welcome_tool.handle_action("show_welcome", {})
        text = result[0].text
        assert "first time" in text.lower() or "Welcome" in text

    @pytest.mark.asyncio
    async def test_returning_user(self, welcome_tool):
        """Returning users see welcome back message."""
        state = _mock_onboarding_state(is_first_time=False, api_key=True, team_id=True)
        with patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.get_onboarding_state",
            return_value=state,
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.validate_environment_variables",
            return_value=_mock_validation_result(),
        ):
            result = await welcome_tool.handle_action("show_welcome", {})
        text = result[0].text
        assert "Welcome back" in text


class TestSetupChecklist:
    """Test setup_checklist action."""

    @pytest.mark.asyncio
    async def test_shows_core_requirements(self, welcome_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.get_onboarding_state",
            return_value=_mock_onboarding_state(),
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.validate_environment_variables",
            return_value=_mock_validation_result(),
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.get_config_value",
            side_effect=lambda key, *args: {
                "REVENIUM_API_KEY": "test_key",
                "REVENIUM_TEAM_ID": "team-1",
                "REVENIUM_DEFAULT_EMAIL": None,
                "REVENIUM_DEFAULT_SLACK_CONFIG_ID": None,
            }.get(key),
        ):
            result = await welcome_tool.handle_action("setup_checklist", {})
        text = result[0].text
        assert "API Key" in text
        assert "Team ID" in text


class TestEnvironmentStatus:
    """Test environment_status action."""

    @pytest.mark.asyncio
    async def test_shows_variables_by_category(self, welcome_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.validate_environment_variables",
            return_value=_mock_validation_result(),
        ):
            result = await welcome_tool.handle_action("environment_status", {})
        text = result[0].text
        assert "REVENIUM_API_KEY" in text
        assert "Authentication" in text


class TestNextSteps:
    """Test next_steps action decision tree."""

    @pytest.mark.asyncio
    async def test_auto_discovery_complete_with_slack(self, welcome_tool):
        """All configured = shows 'ready to go'."""
        state = _mock_onboarding_state(
            api_key=True, team_id=True, email=True, slack=True, auto_discovery=True
        )
        with patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.get_onboarding_state",
            return_value=state,
        ):
            result = await welcome_tool.handle_action("next_steps", {})
        text = result[0].text
        assert "Complete" in text or "Ready" in text

    @pytest.mark.asyncio
    async def test_auto_discovery_complete_without_slack(self, welcome_tool):
        """Auto-discovery OK but no slack = suggests slack."""
        state = _mock_onboarding_state(
            api_key=True, team_id=True, email=True, slack=False, auto_discovery=True
        )
        with patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.get_onboarding_state",
            return_value=state,
        ):
            result = await welcome_tool.handle_action("next_steps", {})
        text = result[0].text
        assert "Slack" in text or "slack" in text

    @pytest.mark.asyncio
    async def test_missing_api_key_shows_critical(self, welcome_tool):
        """Missing API key = critical priority."""
        state = _mock_onboarding_state(api_key=False, team_id=False)
        with patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.get_onboarding_state",
            return_value=state,
        ):
            result = await welcome_tool.handle_action("next_steps", {})
        text = result[0].text
        assert "Critical" in text or "API Key" in text


class TestCompleteSetup:
    """Test complete_setup action validation and flow."""

    @pytest.mark.asyncio
    async def test_missing_confirmation_returns_error(self, welcome_tool):
        result = await welcome_tool.handle_action("complete_setup", {})
        text = result[0].text.lower()
        assert "confirm" in text

    @pytest.mark.asyncio
    async def test_false_confirmation_returns_error(self, welcome_tool):
        result = await welcome_tool.handle_action(
            "complete_setup", {"confirm_completion": False}
        )
        text = result[0].text.lower()
        assert "confirm" in text

    @pytest.mark.asyncio
    async def test_successful_completion(self, welcome_tool):
        mock_config_store = MagicMock()
        mock_config_store.get_configuration = AsyncMock()
        mock_config_store._discovery_attempted = True
        mock_config_store._discovered_config = MagicMock()
        mock_config_store._discovered_config.has_required_fields.return_value = True

        mock_detection_service = MagicMock()
        mock_detection_service.mark_onboarding_completed = AsyncMock(return_value=True)

        with patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.get_config_value",
            side_effect=lambda key, *args: {
                "REVENIUM_API_KEY": "key",
                "REVENIUM_TEAM_ID": "team",
                "REVENIUM_TENANT_ID": "tenant",
                "REVENIUM_OWNER_ID": "owner",
            }.get(key),
        ), patch(
            "src.revenium_mcp_server.config_store.get_config_store",
            return_value=mock_config_store,
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.get_config_value",
            side_effect=lambda key, *args: {
                "REVENIUM_API_KEY": "key",
                "REVENIUM_TEAM_ID": "team",
                "REVENIUM_TENANT_ID": "tenant",
                "REVENIUM_OWNER_ID": "owner",
            }.get(key),
        ), patch(
            "src.revenium_mcp_server.onboarding.detection_service.get_detection_service",
            return_value=mock_detection_service,
        ):
            result = await welcome_tool.handle_action(
                "complete_setup", {"confirm_completion": True}
            )
        text = result[0].text
        assert "Complete" in text or "complete" in text

    @pytest.mark.asyncio
    async def test_missing_required_fields_shows_incomplete(self, welcome_tool):
        mock_config_store = MagicMock()
        mock_config_store.get_configuration = AsyncMock()
        mock_config_store._discovery_attempted = True
        mock_config_store._discovered_config = MagicMock()
        mock_config_store._discovered_config.has_required_fields.return_value = False

        with patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.get_config_value",
            side_effect=lambda key, *args: {
                "REVENIUM_API_KEY": "key",
                "REVENIUM_TEAM_ID": None,
                "REVENIUM_TENANT_ID": None,
                "REVENIUM_OWNER_ID": None,
            }.get(key),
        ), patch(
            "src.revenium_mcp_server.config_store.get_config_store",
            return_value=mock_config_store,
        ):
            result = await welcome_tool.handle_action(
                "complete_setup", {"confirm_completion": True}
            )
        text = result[0].text
        assert "Incomplete" in text or "missing" in text.lower()


class TestBuildNextSteps:
    """Test _build_next_steps helper decision tree directly."""

    def test_all_complete_no_steps(self, welcome_tool):
        state = _mock_onboarding_state(
            api_key=True, team_id=True, email=True, slack=True, auto_discovery=True
        )
        result = welcome_tool._build_next_steps(state)
        assert "Complete" in result or "Ready" in result

    def test_missing_items_prioritized(self, welcome_tool):
        state = _mock_onboarding_state(
            api_key=False, team_id=True, email=False, slack=False, auto_discovery=False
        )
        result = welcome_tool._build_next_steps(state)
        # API key should appear before email in output (higher priority)
        api_pos = result.find("API Key")
        email_pos = result.find("Email")
        assert api_pos < email_pos


class TestBuildWelcomeMessage:
    """Test _build_welcome_message helper decision tree."""

    def test_first_time_auto_discovery_complete_and_slack(self, welcome_tool):
        state = _mock_onboarding_state(
            is_first_time=True, api_key=True, team_id=True,
            email=True, slack=True, auto_discovery=True,
        )
        validation = _mock_validation_result()
        result = welcome_tool._build_welcome_message(state, validation)
        assert "Welcome" in result
        assert "complete" in result.lower() or "all set" in result.lower()

    def test_first_time_auto_discovery_no_slack(self, welcome_tool):
        state = _mock_onboarding_state(
            is_first_time=True, api_key=True, team_id=True,
            email=True, slack=False, auto_discovery=True,
        )
        validation = _mock_validation_result()
        result = welcome_tool._build_welcome_message(state, validation)
        assert "Slack" in result or "slack" in result

    def test_returning_user(self, welcome_tool):
        state = _mock_onboarding_state(is_first_time=False)
        validation = _mock_validation_result()
        result = welcome_tool._build_welcome_message(state, validation)
        assert "Welcome back" in result
