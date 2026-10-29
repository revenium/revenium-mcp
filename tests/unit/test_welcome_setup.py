"""Unit tests for Welcome and Setup tool.

Tests the WelcomeSetup class: action routing, welcome message decision tree,
setup checklist, environment status, next steps, complete setup flow,
and error handling.
"""

import pytest
from src.revenium_mcp_server.common.error_handling import ToolError
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from mcp.types import TextContent

from src.revenium_mcp_server.onboarding.env_validation import API_AUTH_REJECTED_MESSAGE
from src.revenium_mcp_server.tools_decomposed.welcome_setup import WelcomeSetup
from tests.unit._helpers_bare_calls import bare_setup_calls_in


@pytest.fixture(autouse=True)
def _platform_read_succeeds():
    """Renderer tests here mock the validator; the platform read itself is fixed."""
    from src.revenium_mcp_server.onboarding.platform_read import PlatformFacts

    facts = PlatformFacts(read={"status": "success", "status_code": 200, "payload": {}})
    with patch(
        "src.revenium_mcp_server.tools_decomposed.welcome_setup.read_platform_facts",
        new=AsyncMock(return_value=facts),
    ), patch(
        "src.revenium_mcp_server.onboarding.platform_read.probe_platform_read",
        new=AsyncMock(return_value=facts.read),
    ), patch(
        "src.revenium_mcp_server.tools_decomposed.welcome_setup.probe_platform_read",
        new=AsyncMock(return_value=facts.read),
    ):
        yield


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
    async def test_unknown_action_raises(self, welcome_tool):
        with pytest.raises(ToolError) as refused:
            await welcome_tool.handle_action("nonexistent", {})
        text = refused.value.message.lower()
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
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.default_notification_email",
            return_value=None,
        ):
            result = await welcome_tool.handle_action("setup_checklist", {})
        text = result[0].text
        assert "API Key" in text
        assert "Team ID" in text

    @pytest.mark.asyncio
    async def test_permission_denied_gives_scope_guidance(self, welcome_tool):
        """The welcome checklist names the key-scope cause, not the network (BACK-2839)."""
        validation = _mock_validation_result(api_status="failed")
        validation.api_connectivity = {
            "status": "permission_denied",
            "status_code": 403,
            "error": "The API refused to let this key read data (HTTP 403)",
        }
        with patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.get_onboarding_state",
            return_value=_mock_onboarding_state(),
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.validate_environment_variables",
            return_value=validation,
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.default_notification_email",
            return_value=None,
        ):
            result = await welcome_tool.handle_action("setup_checklist", {})
        text = result[0].text
        assert "Forbidden - the key cannot read data" in text
        assert "Check API key and network" not in text
        # The readiness verdict must not contradict the Forbidden line above it.
        assert "Ready to Go!" not in text
        assert "Restore API read access" in text

    @pytest.mark.asyncio
    async def test_401_names_the_rejected_key_case(self, welcome_tool):
        """The welcome checklist carries the shared 401 wording (BACK-2841)."""
        validation = _mock_validation_result(api_status="failed")
        validation.api_connectivity = {
            "status": "failed",
            "status_code": 401,
            "error": API_AUTH_REJECTED_MESSAGE,
        }
        with patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.get_onboarding_state",
            return_value=_mock_onboarding_state(),
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.validate_environment_variables",
            return_value=validation,
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.default_notification_email",
            return_value=None,
        ):
            result = await welcome_tool.handle_action("setup_checklist", {})
        text = result[0].text
        assert "Not accepted (HTTP 401)" in text
        assert API_AUTH_REJECTED_MESSAGE in text
        assert "Check API key and network" not in text
        assert "Ready to Go!" not in text

    @pytest.mark.asyncio
    async def test_first_time_user_gets_configure_not_restore(self, welcome_tool):
        """No key configured means nothing to restore - point at configuration."""
        validation = _mock_validation_result(api_status="failed")
        validation.api_connectivity = {
            "status": "not_attempted",
            "error": "No API key available",
        }
        with patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.get_onboarding_state",
            return_value=_mock_onboarding_state(api_key=False, team_id=False),
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.validate_environment_variables",
            return_value=validation,
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.default_notification_email",
            return_value=None,
        ):
            result = await welcome_tool.handle_action("setup_checklist", {})
        text = result[0].text
        assert "Configure required environment variables" in text
        assert "Restore API read access" not in text

    @pytest.mark.asyncio
    async def test_a_placeholder_email_reads_as_not_configured(
        self, welcome_tool, placeholder_notification_email
    ):
        """BACK-4743: the checklist reads the email through the walk alerts use."""
        with patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.get_onboarding_state",
            return_value=_mock_onboarding_state(),
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.validate_environment_variables",
            return_value=_mock_validation_result(),
        ):
            text = (await welcome_tool.handle_action("setup_checklist", {}))[0].text
        assert "[ ] **Email Notifications**" in text
        assert "[x] **Email Notifications**" not in text

    @pytest.mark.asyncio
    async def test_cached_key_without_probe_is_not_ready(self, welcome_tool):
        """A key visible only in the config cache must not yield Ready to Go."""
        validation = _mock_validation_result(api_status="failed")
        validation.api_connectivity = {
            "status": "not_attempted",
            "error": "No API key available",
        }
        with patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.get_onboarding_state",
            return_value=_mock_onboarding_state(),
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.validate_environment_variables",
            return_value=validation,
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.default_notification_email",
            return_value="user@test.com",
        ):
            result = await welcome_tool.handle_action("setup_checklist", {})
        text = result[0].text
        assert "Ready to Go!" not in text
        assert "API connectivity was not verified" in text


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
    async def test_missing_confirmation_raises(self, welcome_tool):
        with pytest.raises(ToolError) as refused:
            await welcome_tool.handle_action("complete_setup", {})
        text = refused.value.message.lower()
        assert "confirm" in text

    @pytest.mark.asyncio
    async def test_false_confirmation_raises(self, welcome_tool):
        with pytest.raises(ToolError) as refused:
            await welcome_tool.handle_action(
                "complete_setup", {"confirm_completion": False}
            )
        text = refused.value.message.lower()
        assert "confirm" in text

    @pytest.mark.asyncio
    async def test_successful_completion(self, welcome_tool):
        """A successful read confirms setup, and nothing is written (BACK-4677)."""
        read = {"status": "success", "status_code": 200, "payload": {}}
        with patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.probe_platform_read",
            new=AsyncMock(return_value=read),
        ), patch(
            "src.revenium_mcp_server.config_cache.ConfigurationCache.save_config",
            new=AsyncMock(),
        ) as save_config:
            result = await welcome_tool.handle_action(
                "complete_setup", {"confirm_completion": True}
            )
        text = result[0].text
        assert "Setup Complete!" in text
        assert "your API key can read this organization's data" in text
        assert "sign-in" not in text
        assert "Debug Information" not in text
        save_config.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failed_read_raises_tool_error_with_next_step(self, welcome_tool):
        """A failed read is an error answer, never a success page (BACK-4677)."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        read = {"status": "error", "error": "The platform could not be reached, so nothing was verified."}
        with patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.probe_platform_read",
            new=AsyncMock(return_value=read),
        ):
            with pytest.raises(ToolError) as raised:
                await welcome_tool.handle_action(
                    "complete_setup", {"confirm_completion": True}
                )
        message = raised.value.message
        assert "Setup could not be completed" in message
        assert "could not be reached" in message
        assert "system_diagnostics(action='system_health')" in message


class TestBuildNextSteps:
    """Test _build_next_steps helper decision tree directly."""

    def test_all_complete_no_steps(self, welcome_tool):
        state = _mock_onboarding_state(
            api_key=True, team_id=True, email=True, slack=True, auto_discovery=True
        )
        result = welcome_tool._build_next_steps(state, _mock_validation_result())
        assert "Complete" in result or "Ready" in result
        assert "mark onboarding as complete" not in result
        assert "confirm that your credentials can read your organization's data" in result

    def test_missing_items_prioritized(self, welcome_tool):
        state = _mock_onboarding_state(
            api_key=False, team_id=True, email=False, slack=False, auto_discovery=False
        )
        result = welcome_tool._build_next_steps(state, _mock_validation_result())
        # API key should appear before email in output (higher priority)
        api_pos = result.find("API Key")
        email_pos = result.find("Email")
        assert api_pos < email_pos


    @pytest.mark.parametrize(
        "slack, completion_claim",
        [(True, "Setup Complete!"), (None, "Your setup is complete")],
    )
    def test_failed_read_never_claims_completion(self, welcome_tool, slack, completion_claim):
        """A configured local server whose data read failed is not told setup is done."""
        state = _mock_onboarding_state(
            api_key=True, team_id=True, email=True, slack=slack, auto_discovery=True
        )
        result = welcome_tool._build_next_steps(state, _mock_validation_result("error"))
        assert completion_claim not in result
        assert "The platform could not be read" in result
        assert "system_diagnostics(action='system_health')" in result


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


class TestEmailActionNamesACallTheServerAccepts:
    """BACK-4966: the email step names a call the server answers, never verify_email_setup()."""

    @staticmethod
    async def _texts_without_an_email(welcome_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.get_onboarding_state",
            return_value=_mock_onboarding_state(email=False),
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.validate_environment_variables",
            return_value=_mock_validation_result(),
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.welcome_setup.default_notification_email",
            return_value=None,
        ):
            return [
                (await welcome_tool.handle_action(action, {}))[0].text
                for action in ("setup_checklist", "next_steps")
            ]

    @pytest.mark.asyncio
    async def test_local_checklist_names_the_update_email_call(self, welcome_tool, monkeypatch):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        for text in await self._texts_without_an_email(welcome_tool):
            assert "verify_email_setup(" not in bare_setup_calls_in(text), text
            assert "manage_system_setup(action='update_email', email='your@email.com')" in text

    @pytest.mark.asyncio
    async def test_hosted_checklist_names_the_alert_email_argument(
        self, welcome_tool, monkeypatch
    ):
        monkeypatch.setenv("AUTH_MODE", "api_key")
        monkeypatch.setattr(WelcomeSetup, "get_client", AsyncMock(return_value=MagicMock()))
        for text in await self._texts_without_an_email(welcome_tool):
            assert "verify_email_setup(" not in bare_setup_calls_in(text), text
            assert "update_email" not in text
            assert "manage_alerts(action='create_simple'" in text
