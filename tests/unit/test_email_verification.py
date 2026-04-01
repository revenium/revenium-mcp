"""Unit tests for Email Verification tool.

Tests the EmailVerification class: action routing, email validation,
email update flow, status checking, and error handling.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from mcp.types import TextContent

from src.revenium_mcp_server.tools_decomposed.email_verification import EmailVerification


@pytest.fixture
def email_tool():
    return EmailVerification()


class TestEmailActionRouting:
    """Test handle_action routes to correct handlers."""

    @pytest.mark.asyncio
    async def test_unknown_action_returns_structured_error(self, email_tool):
        result = await email_tool.handle_action("nonexistent", {})
        text = result[0].text.lower()
        assert "unknown" in text or "nonexistent" in text
        assert "check_status" in text or "valid_actions" in text

    @pytest.mark.asyncio
    async def test_get_examples_returns_text(self, email_tool):
        result = await email_tool.handle_action("get_examples", {})
        assert "check_status" in result[0].text

    @pytest.mark.asyncio
    async def test_get_capabilities_returns_text(self, email_tool):
        result = await email_tool.handle_action("get_capabilities", {})
        assert "Available Actions" in result[0].text


class TestCheckStatus:
    """Test check_status action: shows different output based on whether email is configured."""

    @pytest.mark.asyncio
    async def test_email_configured_shows_active(self, email_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.email_verification.get_config_value",
            return_value="user@example.com",
        ):
            result = await email_tool.handle_action("check_status", {})
        text = result[0].text
        assert "user@example.com" in text
        assert "Configured" in text or "Active" in text

    @pytest.mark.asyncio
    async def test_email_not_configured_shows_warning(self, email_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.email_verification.get_config_value",
            return_value=None,
        ):
            result = await email_tool.handle_action("check_status", {})
        text = result[0].text
        assert "Not Configured" in text
        assert "update_email" in text


class TestValidateEmail:
    """Test validate_email action: validates format without updating config."""

    @pytest.mark.asyncio
    async def test_missing_email_returns_error(self, email_tool):
        result = await email_tool.handle_action("validate_email", {})
        text = result[0].text.lower()
        assert "email" in text
        assert "required" in text or "missing" in text

    @pytest.mark.asyncio
    async def test_valid_email_shows_success(self, email_tool):
        result = await email_tool.handle_action(
            "validate_email", {"email": "user@example.com"}
        )
        text = result[0].text
        assert "Validation Successful" in text
        assert "user@example.com" in text

    @pytest.mark.asyncio
    async def test_invalid_email_shows_failure(self, email_tool):
        result = await email_tool.handle_action(
            "validate_email", {"email": "not-an-email"}
        )
        text = result[0].text
        assert "Validation Failed" in text or "Invalid" in text.lower()


class TestUpdateEmail:
    """Test update_email action: validates, updates config, confirms."""

    @pytest.mark.asyncio
    async def test_missing_email_returns_error(self, email_tool):
        result = await email_tool.handle_action("update_email", {})
        text = result[0].text.lower()
        assert "email" in text

    @pytest.mark.asyncio
    async def test_successful_update(self, email_tool):
        with patch.object(
            email_tool, "_update_email_configuration", return_value=True
        ):
            result = await email_tool.handle_action(
                "update_email", {"email": "admin@company.com"}
            )
        text = result[0].text
        assert "Updated" in text
        assert "admin@company.com" in text

    @pytest.mark.asyncio
    async def test_failed_update_shows_troubleshooting(self, email_tool):
        with patch.object(
            email_tool, "_update_email_configuration", return_value=False
        ):
            result = await email_tool.handle_action(
                "update_email", {"email": "admin@company.com"}
            )
        text = result[0].text
        assert "Failed" in text
        assert "Troubleshooting" in text

    @pytest.mark.asyncio
    async def test_invalid_email_update_shows_error(self, email_tool):
        """Updating with an invalid email format should show error."""
        result = await email_tool.handle_action(
            "update_email", {"email": "invalid"}
        )
        text = result[0].text.lower()
        assert "error" in text or "failed" in text


class TestSetupGuidance:
    """Test setup_guidance action: context-aware guidance."""

    @pytest.mark.asyncio
    async def test_guidance_with_email_configured(self, email_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.email_verification.get_config_value",
            return_value="user@example.com",
        ):
            result = await email_tool.handle_action("setup_guidance", {})
        text = result[0].text
        assert "user@example.com" in text
        assert "Management Options" in text or "Update Email" in text

    @pytest.mark.asyncio
    async def test_guidance_without_email_shows_initial_setup(self, email_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.email_verification.get_config_value",
            return_value=None,
        ):
            result = await email_tool.handle_action("setup_guidance", {})
        text = result[0].text
        assert "Initial Email Setup" in text
        assert "validate_email" in text


class TestTestConfiguration:
    """Test test_configuration action: analyzes current email config."""

    @pytest.mark.asyncio
    async def test_with_valid_email_shows_analysis(self, email_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.email_verification.get_config_value",
            return_value="admin@company.com",
        ):
            result = await email_tool.handle_action("test_configuration", {})
        text = result[0].text
        assert "admin@company.com" in text
        assert "company.com" in text  # Domain analysis

    @pytest.mark.asyncio
    async def test_without_email_shows_not_found(self, email_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.email_verification.get_config_value",
            return_value=None,
        ):
            result = await email_tool.handle_action("test_configuration", {})
        text = result[0].text
        assert "No Email Configuration Found" in text


class TestBuildEmailStatus:
    """Test _build_email_status helper directly for both branches."""

    def test_with_email(self, email_tool):
        status = email_tool._build_email_status("test@example.com")
        assert "test@example.com" in status
        assert "Active" in status or "Configured" in status

    def test_without_email(self, email_tool):
        status = email_tool._build_email_status(None)
        assert "Not Configured" in status
        assert "update_email" in status


class TestBuildConfigurationTest:
    """Test _build_configuration_test helper email analysis logic."""

    def test_valid_email_analyzes_parts(self, email_tool):
        result = email_tool._build_configuration_test("user@example.com")
        assert "user" in result  # local part
        assert "example.com" in result  # domain
        assert "Contains TLD" in result

    def test_no_email_shows_required_actions(self, email_tool):
        result = email_tool._build_configuration_test(None)
        assert "No Email Configuration Found" in result
        assert "update_email" in result
