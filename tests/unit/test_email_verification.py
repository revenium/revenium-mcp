"""Unit tests for Email Verification tool.

Tests the EmailVerification class: action routing, email validation,
email update flow, status checking, and error handling.
"""

import json
import time

import pytest
from unittest.mock import AsyncMock, patch


from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from src.revenium_mcp_server.config_cache import ConfigCacheError, _default_cache
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
        with pytest.raises(ToolError) as exc_info:
            await email_tool.handle_action("update_email", {})
        assert "email" in str(exc_info.value).lower()

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
            with pytest.raises(ToolError) as exc_info:
                await email_tool.handle_action(
                    "update_email", {"email": "admin@company.com"}
                )
        assert "was not saved" in exc_info.value.message
        assert exc_info.value.suggestions

    @pytest.mark.asyncio
    async def test_invalid_email_update_shows_error(self, email_tool):
        """Updating with an invalid email format should show error."""
        with pytest.raises(ToolError) as exc_info:
            await email_tool.handle_action("update_email", {"email": "invalid"})
        assert "was not saved" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_update_without_a_saved_configuration_says_not_saved(
        self, email_tool, monkeypatch
    ):
        """BACK-4679: with no valid .revenium_cache nothing is stored, so the
        reply must not claim the email was configured."""
        monkeypatch.delenv("AUTH_MODE", raising=False)
        with pytest.raises(ToolError) as exc_info:
            await email_tool.handle_action(
                "update_email", {"email": "admin@company.com"}
            )
        assert "was not saved" in exc_info.value.message
        assert "admin@company.com" in exc_info.value.message
        assert not _default_cache.cache_file.exists()

    @pytest.mark.asyncio
    async def test_update_when_the_cache_cannot_be_written_says_not_saved(
        self, email_tool, monkeypatch
    ):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        with patch.object(
            _default_cache,
            "update_config_field",
            AsyncMock(side_effect=ConfigCacheError("disk full")),
        ):
            with pytest.raises(ToolError) as exc_info:
                await email_tool.handle_action(
                    "update_email", {"email": "admin@company.com"}
                )
        assert "was not saved" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_update_with_a_saved_configuration_writes_it_and_says_so(
        self, email_tool, monkeypatch, tmp_path
    ):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        monkeypatch.delenv("REVENIUM_DEFAULT_EMAIL", raising=False)
        path = tmp_path / "cache.json"
        path.write_text(
            json.dumps(
                {
                    "timestamp": time.time(),
                    "config": {
                        "REVENIUM_API_KEY": "fake-key-for-tests",
                        "REVENIUM_TEAM_ID": "team_test",
                        "REVENIUM_TENANT_ID": "tenant_test",
                        "REVENIUM_OWNER_ID": "owner_test",
                    },
                    "version": "1.0",
                }
            )
        )
        monkeypatch.setattr(_default_cache, "cache_file", path)

        result = await email_tool.handle_action(
            "update_email", {"email": "admin@company.com"}
        )
        assert "Successfully configured" in result[0].text
        saved = json.loads(path.read_text())
        assert saved["config"]["REVENIUM_DEFAULT_EMAIL"] == "admin@company.com"

        status = await EmailVerification().handle_action("check_status", {})
        assert "admin@company.com" in status[0].text
        assert "Email Not Configured" not in status[0].text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auth_mode", ["api_key", "clerk"])
    async def test_hosted_server_refuses_to_set_the_email(
        self, email_tool, monkeypatch, auth_mode
    ):
        monkeypatch.setenv("AUTH_MODE", auth_mode)
        update = AsyncMock(return_value=True)
        with patch.object(_default_cache, "update_config_field", update):
            with pytest.raises(ToolError) as exc_info:
                await email_tool.handle_action(
                    "update_email", {"email": "admin@company.com"}
                )
        assert "not available on the hosted server" in exc_info.value.message
        assert exc_info.value.error_code == ErrorCodes.ACTION_NOT_SUPPORTED
        update.assert_not_called()


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


    @pytest.mark.asyncio
    async def test_invalid_configured_address_is_not_reported_ready(self, email_tool):
        """BACK-4679: a malformed address is never summarized as ready."""
        with patch(
            "src.revenium_mcp_server.tools_decomposed.email_verification.get_config_value",
            return_value="bob@",
        ):
            result = await email_tool.handle_action("test_configuration", {})
        text = result[0].text
        assert "- **Format Valid**: ❌ No\n" in text
        assert "- **Ready for Notifications**: ❌ No\n" in text
        assert "✅ Yes (if validation passed)" not in text
        assert "Your email configuration is ready!" not in text
        assert "Ready for Notifications**: ✅" not in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auth_mode", ["api_key", "clerk"])
    async def test_invalid_address_on_the_hosted_server_is_not_told_to_use_update_email(
        self, email_tool, monkeypatch, auth_mode
    ):
        """update_email is refused on the hosted server, so the fix steps point
        to the email argument of manage_alerts instead."""
        monkeypatch.setenv("AUTH_MODE", auth_mode)
        with patch(
            "src.revenium_mcp_server.tools_decomposed.email_verification.get_config_value",
            return_value="bob@",
        ):
            result = await email_tool.handle_action("test_configuration", {})
        text = result[0].text
        assert "action='update_email'" not in text
        assert "manage_alerts(action='create_simple', threshold=100, email='your@email.com')" in text

    @pytest.mark.asyncio
    async def test_valid_configured_address_is_reported_ready(self, email_tool):
        with patch(
            "src.revenium_mcp_server.tools_decomposed.email_verification.get_config_value",
            return_value="admin@company.com",
        ):
            result = await email_tool.handle_action("test_configuration", {})
        text = result[0].text
        assert "- **Format Valid**: ✅ Yes\n" in text
        assert "- **Ready for Notifications**: ✅ Yes\n" in text


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
