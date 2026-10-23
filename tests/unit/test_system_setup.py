"""Unit tests for SystemSetup tool.

Tests the SystemSetup class which consolidates welcome guidance, setup
validation, and email configuration into a single onboarding tool.
"""

import pytest
from unittest.mock import AsyncMock

from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from src.revenium_mcp_server.tools_decomposed.system_setup import SystemSetup
from mcp.types import TextContent

from tests.unit._helpers_bare_calls import bare_setup_calls_in


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


async def _email_capability(setup_tool):
    capabilities = await setup_tool._get_tool_capabilities()
    return next(c for c in capabilities if c.name == "Email Configuration Management")


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
            setup_tool.welcome_tool.handle_action.assert_called_once_with(action, {}, ctx=None)

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
        """Unknown action raises a structured error with valid actions."""
        with pytest.raises(ToolError) as exc_info:
            await setup_tool.handle_action("bogus_action", {})
        text = exc_info.value.message
        assert "bogus_action" in text or "Unknown" in text
        assert "valid_actions" in text

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


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["help", "get_actions"])
async def test_help_and_get_actions_name_only_registered_tools(action):
    """Every tool the setup help tells the assistant to call is a registered tool.

    BACK-4677 section B: the help text named ``welcome_and_setup``, which no
    profile registers, so an assistant following it called a missing tool.
    """
    import re

    from src.revenium_mcp_server.tool_configuration.profiles import (
        PROFILE_DEFINITIONS,
    )

    result = await SystemSetup().handle_action(action, {})
    text = result[0].text

    callees = set(re.findall(r"`(\w+)\(", text))
    assert callees, "help text names no callable tool at all"
    assert callees <= PROFILE_DEFINITIONS["business"], (
        f"help names unregistered tools: {sorted(callees - PROFILE_DEFINITIONS['business'])}"
    )
    assert "welcome_and_setup" not in text


@pytest.mark.asyncio
async def test_update_email_on_the_hosted_server_is_refused_through_system_setup(
    monkeypatch,
):
    """BACK-4679: the hosted server cannot store a notification email, so
    system_setup update_email raises instead of claiming success."""
    monkeypatch.setenv("AUTH_MODE", "api_key")
    with pytest.raises(ToolError) as exc_info:
        await SystemSetup().handle_action(
            "update_email", {"email": "admin@company.com"}
        )
    assert exc_info.value.error_code == ErrorCodes.ACTION_NOT_SUPPORTED
    assert "not available on the hosted server" in exc_info.value.message


class TestGetExamplesNamesTheCallsThisServerAccepts:
    """get_examples never sends a hosted caller to update_email, and names system_setup calls."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auth_mode", ["api_key", "clerk"])
    async def test_hosted_examples_never_name_update_email(self, setup_tool, monkeypatch, auth_mode):
        monkeypatch.setenv("AUTH_MODE", auth_mode)
        text = (await setup_tool.handle_action("get_examples", {}))[0].text
        assert "update_email" not in text
        assert "manage_alerts(action='create_simple', threshold=100, email=" in text
        assert "`setup_checklist()`" not in text

    @pytest.mark.asyncio
    async def test_local_examples_name_update_email_through_system_setup(self, setup_tool, monkeypatch):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        text = (await setup_tool.handle_action("get_examples", {}))[0].text
        assert '"action": "update_email"' in text
        assert "system_setup(action='update_email', email='" in text
        assert "`setup_checklist()`" not in text
        assert "system_setup(action='setup_checklist')" in text


def _email_examples_section(text):
    return text.split("## **Email Configuration Examples**", 1)[1].split("## **Complete Setup Workflows**", 1)[0]


class TestHelpHeadingsAndCalls:
    """system_setup's help keeps the email example inside its section and names working calls."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "auth_mode,heading,absent_heading",
        [
            ("env", "### **Update Email Address**", None),
            ("api_key", "### **Set the Notification Email**", "### **Update Email Address**"),
        ],
    )
    async def test_the_set_email_example_is_a_subsection_of_the_email_examples(
        self, setup_tool, monkeypatch, auth_mode, heading, absent_heading
    ):
        monkeypatch.setenv("AUTH_MODE", auth_mode)
        text = (await setup_tool.handle_action("get_examples", {}))[0].text
        section = _email_examples_section(text)
        assert "\n## " not in section
        assert heading in section
        if absent_heading:
            assert absent_heading not in section

    @pytest.mark.asyncio
    async def test_the_workflow_completes_setup_with_its_confirmation(self, setup_tool):
        text = (await setup_tool.handle_action("get_examples", {}))[0].text
        assert "`system_setup(action='complete_setup', confirm_completion=True)`" in text
        assert "`system_setup(action='complete_setup')`" not in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auth_mode", ["env", "api_key"])
    async def test_capabilities_summary_and_quick_start_name_system_setup_calls(
        self, setup_tool, monkeypatch, auth_mode
    ):
        monkeypatch.setenv("AUTH_MODE", auth_mode)
        texts = [
            (await setup_tool.handle_action("get_capabilities", {}))[0].text,
            (await setup_tool.handle_action("get_agent_summary", {}))[0].text,
            "\n".join(await setup_tool._get_quick_start_guide()),
            "\n".join(
                example
                for capability in await setup_tool._get_tool_capabilities()
                for example in capability.examples
            ),
        ]
        for text in texts:
            assert not bare_setup_calls_in(text), text
        assert "system_setup(action='complete_setup', confirm_completion=True)" in texts[0]
        assert "system_setup(action='get_examples')" in texts[0]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auth_mode", ["api_key", "clerk"])
    async def test_hosted_capabilities_do_not_offer_update_email(
        self, setup_tool, monkeypatch, auth_mode
    ):
        monkeypatch.setenv("AUTH_MODE", auth_mode)
        text = (await setup_tool.handle_action("get_capabilities", {}))[0].text
        assert "`update_email` - Not available on this server" in text
        assert "system_setup(action='update_email'" not in text
        email_capability = await _email_capability(setup_tool)
        assert "update_email" not in email_capability.parameters

    @pytest.mark.asyncio
    async def test_local_capabilities_offer_update_email(self, setup_tool, monkeypatch):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        text = (await setup_tool.handle_action("get_capabilities", {}))[0].text
        assert "system_setup(action='update_email', email='your@email.com')" in text
        email_capability = await _email_capability(setup_tool)
        assert "update_email" in email_capability.parameters
