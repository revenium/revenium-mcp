"""Unit tests for verify_email_setup module.

Tests the EmailVerificationRequest dataclass, _prepare_arguments helper,
and the supported email actions list.
"""

import pytest
from unittest.mock import AsyncMock, patch

from src.revenium_mcp_server.tools_decomposed.verify_email_setup import (
    EmailVerificationRequest,
    _prepare_arguments,
    get_supported_email_actions,
    verify_email_setup,
)


class TestEmailVerificationRequest:
    """Test EmailVerificationRequest dataclass."""

    def test_all_fields(self):
        """All fields can be populated."""
        req = EmailVerificationRequest(
            action="validate_email",
            email="test@example.com",
            validate_format=True,
            suggest_smart_defaults=True,
            include_setup_guidance=True,
            test_configuration=True,
        )
        assert req.email == "test@example.com"
        assert req.validate_format is True


class TestPrepareArguments:
    """Test _prepare_arguments helper."""

    def test_strips_none_values(self):
        """None values are stripped from the arguments dict."""
        req = EmailVerificationRequest(action="check_status", email="a@b.com")
        args = _prepare_arguments(req)
        assert "action" in args
        assert "email" in args
        assert "validate_format" not in args
        assert "suggest_smart_defaults" not in args

    def test_preserves_false_values(self):
        """False boolean values are preserved (not stripped)."""
        req = EmailVerificationRequest(action="check_status", validate_format=False)
        args = _prepare_arguments(req)
        # False is not None, so it should be preserved
        assert "validate_format" in args
        assert args["validate_format"] is False

    def test_all_none_returns_only_action(self):
        """Only action remains when all optionals are None."""
        req = EmailVerificationRequest(action="setup_guidance")
        args = _prepare_arguments(req)
        assert args == {"action": "setup_guidance"}


class TestGetSupportedEmailActions:
    """Test get_supported_email_actions."""

    @pytest.mark.asyncio
    async def test_returns_expected_actions(self):
        """Returns list of expected email verification actions."""
        actions = await get_supported_email_actions()
        assert "check_status" in actions
        assert "update_email" in actions
        assert "validate_email" in actions
        assert "setup_guidance" in actions
        assert "test_configuration" in actions

    @pytest.mark.asyncio
    async def test_returns_list_of_strings(self):
        """All actions are strings."""
        actions = await get_supported_email_actions()
        assert all(isinstance(a, str) for a in actions)


class TestVerifyEmailSetup:
    """Test verify_email_setup function delegates correctly."""

    @pytest.mark.asyncio
    async def test_delegates_to_standardized_execution(self):
        """verify_email_setup calls standardized_tool_execution with correct params."""
        req = EmailVerificationRequest(action="check_status", email="test@example.com")

        mock_exec = AsyncMock(return_value=[{"status": "ok"}])
        # The import happens at function call time inside verify_email_setup
        # so we mock the module it imports from
        import sys
        import types
        fake_module = types.ModuleType("src.revenium_mcp_server.enhanced_server")
        fake_module.standardized_tool_execution = mock_exec
        with patch.dict(sys.modules, {"src.revenium_mcp_server.enhanced_server": fake_module}):
            result = await verify_email_setup(req)
            mock_exec.assert_called_once()
            # Verify tool_name kwarg
            _, kwargs = mock_exec.call_args
            assert kwargs.get("tool_name") == "verify_email_setup"
