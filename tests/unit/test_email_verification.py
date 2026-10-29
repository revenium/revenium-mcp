"""Unit tests for Email Verification tool.

Tests the EmailVerification class: action routing, email validation,
email update flow, status checking, and error handling.
"""

import json
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch


from src.revenium_mcp_server.auth.claims_middleware import _current_tenant
from src.revenium_mcp_server.auth.tenant_context import TenantContext
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from src.revenium_mcp_server import config_cache as config_cache_module
from src.revenium_mcp_server.config_cache import _default_cache
from src.revenium_mcp_server.saved_notification_email import saved_notification_email
from src.revenium_mcp_server.config_store import (
    ConfigurationStore,
    default_notification_email,
    notification_email_with_source,
)
from tests.unit._helpers_bare_calls import bare_setup_calls_in
from src.revenium_mcp_server.tools_decomposed.email_verification import (
    ADDRESS_SCOPE,
    ConfiguredEmail,
    EmailVerification,
    email_format_error,
    fix_address_section,
    invalid_address_verdict,
)


@contextmanager
def signed_in(caller):
    token = _current_tenant.set(caller)
    try:
        yield
    finally:
        _current_tenant.reset(token)


def configured(address, source="environment"):
    """The notification email lookup answering one address and the layer it came from."""
    return patch(
        "src.revenium_mcp_server.tools_decomposed.email_verification.notification_email_with_source",
        return_value=(address, source if address else None),
    )


@pytest.fixture
def email_tool():
    return EmailVerification()


class TestEmailActionRouting:
    """Test handle_action routes to correct handlers."""

    @pytest.mark.asyncio
    async def test_unknown_action_raises_a_structured_error(self, email_tool):
        with pytest.raises(ToolError) as refused:
            await email_tool.handle_action("nonexistent", {})
        text = refused.value.message.lower()
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
        with configured("user@example.com"):
            result = await email_tool.handle_action("check_status", {})
        text = result[0].text
        assert "user@example.com" in text
        assert "Configured" in text or "Active" in text

    @pytest.mark.asyncio
    async def test_email_not_configured_shows_warning(self, email_tool):
        with configured(None):
            result = await email_tool.handle_action("check_status", {})
        text = result[0].text
        assert "Not Configured" in text
        assert "update_email" in text


class TestValidateEmail:
    """Test validate_email action: validates format without updating config."""

    @pytest.mark.asyncio
    async def test_missing_email_raises(self, email_tool):
        with pytest.raises(ToolError) as refused:
            await email_tool.handle_action("validate_email", {})
        text = refused.value.message.lower()
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
        result = await email_tool.handle_action(
            "update_email", {"email": "admin@company.com"}
        )
        text = result[0].text
        assert "Updated" in text
        assert "admin@company.com" in text
        assert saved_notification_email.read() == "admin@company.com"

    @pytest.mark.asyncio
    async def test_failed_update_shows_troubleshooting(self, email_tool):
        with patch.object(
            saved_notification_email,
            "save",
            side_effect=PermissionError(13, "Permission denied"),
        ):
            with pytest.raises(ToolError) as exc_info:
                await email_tool.handle_action(
                    "update_email", {"email": "admin@company.com"}
                )
        assert "was not saved" in exc_info.value.message
        assert "could not be written (Permission denied)" in exc_info.value.message
        assert exc_info.value.suggestions

    @pytest.mark.asyncio
    async def test_invalid_email_update_shows_error(self, email_tool):
        """Updating with an invalid email format should show error."""
        with pytest.raises(ToolError) as exc_info:
            await email_tool.handle_action("update_email", {"email": "invalid"})
        assert "was not saved" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_update_without_a_configuration_cache_saves_the_address(
        self, email_tool, monkeypatch, tmp_path
    ):
        """BACK-4967: the saved address does not depend on a valid .revenium_cache."""
        monkeypatch.delenv("AUTH_MODE", raising=False)
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "env@example.com")
        missing_cache = tmp_path / "no-cache.json"
        monkeypatch.setattr(_default_cache, "cache_file", missing_cache)

        result = await email_tool.handle_action(
            "update_email", {"email": "admin@company.com"}
        )

        assert "Successfully configured" in result[0].text
        assert default_notification_email() == "admin@company.com"
        assert not missing_cache.exists()

    @pytest.mark.asyncio
    async def test_update_where_the_file_cannot_be_written_refuses_and_keeps_the_default(
        self, email_tool, monkeypatch, tmp_path
    ):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "env@example.com")
        unwritable = tmp_path / "missing-directory" / "saved-notification-email"
        monkeypatch.setattr(saved_notification_email, "path", unwritable)

        with pytest.raises(ToolError) as exc_info:
            await email_tool.handle_action(
                "update_email", {"email": "admin@company.com"}
            )

        assert "admin@company.com was not saved" in exc_info.value.message
        assert str(unwritable) in exc_info.value.message
        assert default_notification_email() == "env@example.com"

    @pytest.mark.asyncio
    async def test_update_with_a_saved_configuration_writes_it_and_says_so(
        self, email_tool, monkeypatch, tmp_path
    ):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        monkeypatch.delenv("REVENIUM_DEFAULT_EMAIL", raising=False)
        path = tmp_path / "cache.json"
        _write_cache(path, dict(_REQUIRED_CACHE_FIELDS, REVENIUM_DEFAULT_EMAIL="cached@example.com"))
        monkeypatch.setattr(_default_cache, "cache_file", path)

        result = await email_tool.handle_action(
            "update_email", {"email": "admin@company.com"}
        )
        assert "Successfully configured" in result[0].text

        status = await EmailVerification().handle_action("check_status", {})
        assert "admin@company.com" in status[0].text
        assert "**Source**: Saved with update_email" in status[0].text
        assert "Email Not Configured" not in status[0].text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auth_mode", ["api_key", "clerk"])
    async def test_hosted_server_refuses_to_set_the_email(
        self, email_tool, monkeypatch, auth_mode
    ):
        monkeypatch.setenv("AUTH_MODE", auth_mode)
        update = MagicMock()
        with patch.object(saved_notification_email, "save", update):
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
        with configured("user@example.com"):
            result = await email_tool.handle_action("setup_guidance", {})
        text = result[0].text
        assert "user@example.com" in text
        assert "Management Options" in text or "Update Email" in text

    @pytest.mark.asyncio
    async def test_guidance_without_email_shows_initial_setup(self, email_tool):
        with configured(None):
            result = await email_tool.handle_action("setup_guidance", {})
        text = result[0].text
        assert "Initial Email Setup" in text
        assert "validate_email" in text


class TestTestConfiguration:
    """Test test_configuration action: analyzes current email config."""

    @pytest.mark.asyncio
    async def test_with_valid_email_shows_analysis(self, email_tool):
        with configured("admin@company.com"):
            result = await email_tool.handle_action("test_configuration", {})
        text = result[0].text
        assert "admin@company.com" in text
        assert "company.com" in text  # Domain analysis

    @pytest.mark.asyncio
    async def test_without_email_shows_not_found(self, email_tool):
        with configured(None):
            result = await email_tool.handle_action("test_configuration", {})
        text = result[0].text
        assert "No Email Configuration Found" in text


    @pytest.mark.asyncio
    async def test_invalid_configured_address_is_not_reported_ready(self, email_tool):
        """BACK-4679: a malformed address is never summarized as ready."""
        with configured("bob@"):
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
        with configured("bob@"):
            result = await email_tool.handle_action("test_configuration", {})
        text = result[0].text
        assert "action='update_email'" not in text
        assert "manage_alerts(action='create_simple', threshold=100, email='your@email.com')" in text

    @pytest.mark.asyncio
    async def test_valid_configured_address_is_reported_ready(self, email_tool):
        with configured("admin@company.com"):
            result = await email_tool.handle_action("test_configuration", {})
        text = result[0].text
        assert "- **Format Valid**: ✅ Yes\n" in text
        assert "- **Ready for Notifications**: ✅ Yes\n" in text


class TestBuildEmailStatus:
    """Test _build_email_status helper directly for both branches."""

    def test_with_email(self, email_tool):
        status = email_tool._build_email_status(ConfiguredEmail("test@example.com", "Not set"))
        assert "test@example.com" in status
        assert "Active" in status or "Configured" in status

    def test_without_email(self, email_tool):
        status = email_tool._build_email_status(ConfiguredEmail(None, "Not set"))
        assert "Not Configured" in status
        assert "update_email" in status


class TestBuildConfigurationTest:
    """Test _build_configuration_test helper email analysis logic."""

    def test_valid_email_analyzes_parts(self, email_tool):
        result = email_tool._build_configuration_test(ConfiguredEmail("user@example.com", "Not set"))
        assert "user" in result  # local part
        assert "example.com" in result  # domain
        assert "**Format Validation**: ✅ Valid" in result

    def test_no_email_shows_required_actions(self, email_tool):
        result = email_tool._build_configuration_test(ConfiguredEmail(None, "Not set"))
        assert "No Email Configuration Found" in result
        assert "update_email" in result


_HOSTED_HELP_ACTIONS = [
    ("check_status", {}),
    ("setup_guidance", {}),
    ("test_configuration", {}),
    ("validate_email", {"email": "user@example.com"}),
]


_REQUIRED_CACHE_FIELDS = {
    "REVENIUM_API_KEY": "fake-key-for-tests",
    "REVENIUM_TEAM_ID": "team_test",
    "REVENIUM_TENANT_ID": "tenant_test",
    "REVENIUM_OWNER_ID": "owner_test",
}


def _write_cache(path, config):
    path.write_text(json.dumps({"timestamp": time.time(), "config": config, "version": "1.0"}))


class TestHelpMatchesTheHostedToolSet:
    """BACK-4743: help names only calls this server answers."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auth_mode", ["api_key", "clerk"])
    @pytest.mark.parametrize("current_email", ["user@example.com", "bob@", None])
    @pytest.mark.parametrize("action,arguments", _HOSTED_HELP_ACTIONS)
    async def test_hosted_help_names_neither_update_email_nor_verify_email_setup(
        self, email_tool, monkeypatch, auth_mode, current_email, action, arguments
    ):
        monkeypatch.setenv("AUTH_MODE", auth_mode)
        with configured(current_email):
            result = await email_tool.handle_action(action, arguments)
        text = result[0].text
        assert "update_email" not in text
        assert "verify_email_setup" not in text
        assert not bare_setup_calls_in(text)

    @pytest.mark.asyncio
    async def test_hosted_guidance_without_an_email_points_to_the_alert_email_argument(
        self, email_tool, monkeypatch
    ):
        monkeypatch.setenv("AUTH_MODE", "api_key")
        with configured(None):
            result = await email_tool.handle_action("setup_guidance", {})
        assert (
            "manage_alerts(action='create_simple', threshold=100, email='your@email.com')"
            in result[0].text
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("current_email", ["user@example.com", "bob@", None])
    @pytest.mark.parametrize("action,arguments", _HOSTED_HELP_ACTIONS)
    async def test_local_help_names_system_setup_calls_only(
        self, email_tool, monkeypatch, current_email, action, arguments
    ):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        with configured(current_email):
            result = await email_tool.handle_action(action, arguments)
        text = result[0].text
        assert "verify_email_setup" not in text
        assert not bare_setup_calls_in(text)

    @pytest.mark.asyncio
    async def test_local_guidance_names_update_email_through_system_setup(
        self, email_tool, monkeypatch
    ):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        with configured(None):
            result = await email_tool.handle_action("setup_guidance", {})
        assert "manage_system_setup(action='update_email', email='your@email.com')" in result[0].text


class TestEmailSourceLabel:
    """BACK-4743: the source says where the address really came from."""

    @pytest.mark.asyncio
    async def test_a_cached_address_is_labelled_as_the_cache(
        self, email_tool, monkeypatch, tmp_path
    ):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "env@example.com")
        cache = tmp_path / "cache.json"
        _write_cache(cache, {"REVENIUM_DEFAULT_EMAIL": "cached@example.com"})
        monkeypatch.setattr(_default_cache, "cache_file", cache)
        result = await email_tool.handle_action("check_status", {})
        assert "**Current Email**: cached@example.com" in result[0].text
        assert "**Source**: Configuration cache (.revenium_cache)" in result[0].text

    @pytest.mark.asyncio
    async def test_an_environment_address_is_labelled_as_the_environment(
        self, email_tool, monkeypatch, tmp_path
    ):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "env@example.com")
        monkeypatch.setattr(_default_cache, "cache_file", tmp_path / "none.json")
        result = await email_tool.handle_action("check_status", {})
        assert "**Current Email**: env@example.com" in result[0].text
        assert "**Source**: Environment variable REVENIUM_DEFAULT_EMAIL" in result[0].text

    @pytest.mark.asyncio
    async def test_a_discovered_address_is_labelled_as_discovered(
        self, email_tool, monkeypatch, tmp_path
    ):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        monkeypatch.delenv("REVENIUM_DEFAULT_EMAIL", raising=False)
        monkeypatch.setattr(_default_cache, "cache_file", tmp_path / "none.json")
        with patch.object(
            ConfigurationStore, "_discovered_value", return_value="found@example.com"
        ):
            result = await email_tool.handle_action("test_configuration", {})
        assert "**Source**: Auto-discovered from your Revenium account" in result[0].text

    @pytest.mark.asyncio
    async def test_a_hosted_address_is_labelled_as_the_callers_account(
        self, email_tool, monkeypatch
    ):
        monkeypatch.setenv("AUTH_MODE", "clerk")
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "operator@example.com")
        caller = TenantContext(team_id="TeamC", api_key="caller-key", email="caller@example.com")
        with signed_in(caller):
            result = await email_tool.handle_action("check_status", {})
        assert "**Current Email**: caller@example.com" in result[0].text
        assert "**Source**: Your Revenium account" in result[0].text
        assert "Environment variable" not in result[0].text

    @pytest.mark.asyncio
    async def test_a_hosted_call_without_a_signed_in_caller_names_the_layer_it_read(
        self, email_tool, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("AUTH_MODE", "clerk")
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "operator@example.com")
        monkeypatch.setattr(_default_cache, "cache_file", tmp_path / "none.json")
        result = await email_tool.handle_action("check_status", {})
        assert "**Source**: Environment variable REVENIUM_DEFAULT_EMAIL" in result[0].text
        assert "Your Revenium account" not in result[0].text


class TestCheckStatusValidatesTheAddress:
    """BACK-4743: check_status does not call a malformed address active."""

    @pytest.mark.asyncio
    async def test_an_invalid_address_is_not_reported_active(self, email_tool):
        with configured("bob@"):
            result = await email_tool.handle_action("check_status", {})
        text = result[0].text
        assert "## Email Not Valid" in text
        assert "Active and ready" not in text

    @pytest.mark.asyncio
    async def test_a_valid_address_is_reported_active(self, email_tool):
        with configured("bob@example.com"):
            result = await email_tool.handle_action("check_status", {})
        assert "Active and ready for notifications" in result[0].text


class TestOneVerdictPerAddress:
    """check_status, test_configuration and setup_guidance judge an address by the same validator."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["check_status", "test_configuration", "setup_guidance"])
    async def test_a_dotted_domain_does_not_pass_an_invalid_address(self, email_tool, action):
        with configured("a b@example.com"):
            result = await email_tool.handle_action(action, {})
        text = result[0].text
        assert "Contains TLD" not in text
        assert "Active and ready" not in text
        assert "Configured and ready" not in text
        assert "Ready for Notifications**: ✅" not in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["check_status", "test_configuration", "setup_guidance"])
    async def test_every_reader_gives_the_same_verdict_and_fix_steps(self, email_tool, action):
        with configured("bob@"):
            text = (await email_tool.handle_action(action, {}))[0].text
        verdict = invalid_address_verdict(email_format_error("bob@"))
        assert f"**Status**: {verdict}\n" in text
        assert fix_address_section() in text


class TestHostedNextStepKeepsTheCheckedAddress:
    @pytest.mark.asyncio
    async def test_hosted_validate_email_puts_the_checked_address_in_the_alert_call(
        self, email_tool, monkeypatch
    ):
        monkeypatch.setenv("AUTH_MODE", "api_key")
        result = await email_tool.handle_action("validate_email", {"email": "ops@company.com"})
        text = result[0].text
        assert (
            "manage_alerts(action='create_simple', threshold=100, email='ops@company.com')"
            in text
        )
        assert "your@email.com" not in text


class TestConfigValueSource:
    """The source names the same layer get_value_with_override takes the value from."""

    @pytest.fixture
    def store(self, monkeypatch, tmp_path):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        monkeypatch.delenv("REVENIUM_DEFAULT_EMAIL", raising=False)
        monkeypatch.setattr(_default_cache, "cache_file", tmp_path / "none.json")
        return ConfigurationStore()

    def test_environment_wins_over_discovery(self, store, monkeypatch):
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "env@example.com")
        with patch.object(ConfigurationStore, "_discovered_value", return_value="d@example.com"):
            assert store.get_value_with_source("REVENIUM_DEFAULT_EMAIL")[1] == "environment"
            assert store.get_value_with_override("REVENIUM_DEFAULT_EMAIL") == "env@example.com"

    def test_discovery_is_named_when_nothing_else_is_set(self, store):
        with patch.object(ConfigurationStore, "_discovered_value", return_value="d@example.com"):
            assert store.get_value_with_source("REVENIUM_DEFAULT_EMAIL")[1] == "discovery"
            assert store.get_value_with_override("REVENIUM_DEFAULT_EMAIL") == "d@example.com"

    def test_a_signed_in_caller_supplies_the_value_and_is_named(self, store, monkeypatch):
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "operator@example.com")
        with signed_in(TenantContext(team_id="TeamC", api_key="caller-key", email="caller@example.com")):
            assert store.get_value_with_source("REVENIUM_DEFAULT_EMAIL")[1] == "caller"
            assert store.get_value_with_override("REVENIUM_DEFAULT_EMAIL") == "caller@example.com"

    def test_a_caller_without_the_setting_leaves_it_unset(self, store, monkeypatch):
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "operator@example.com")
        with signed_in(TenantContext(team_id="TeamC", api_key="caller-key")):
            assert store.get_value_with_source("REVENIUM_DEFAULT_EMAIL") == (None, None)
            assert store.get_value_with_override("REVENIUM_DEFAULT_EMAIL", "fallback") == "fallback"

    def test_an_unset_value_has_no_source(self, store):
        with patch.object(ConfigurationStore, "_discovered_value", return_value=None):
            assert store.get_value_with_source("REVENIUM_DEFAULT_EMAIL") == (None, None)
            assert store.get_value_with_override("REVENIUM_DEFAULT_EMAIL", "fallback") == "fallback"


class TestEveryEmailHelpNamesSystemSetupCalls:
    """BACK-4743: update_email, the quick start and the examples name only calls this server answers."""

    @pytest.mark.asyncio
    async def test_local_update_email_success_names_system_setup_calls(
        self, email_tool, monkeypatch
    ):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        result = await email_tool.handle_action("update_email", {"email": "ops@company.com"})
        text = result[0].text
        assert "get_system_setup(action='test_configuration')" in text
        assert "get_system_setup(action='check_status')" in text
        assert not bare_setup_calls_in(text)

    @pytest.mark.asyncio
    async def test_local_update_email_failure_suggests_validate_email_through_system_setup(
        self, email_tool, monkeypatch
    ):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        with pytest.raises(ToolError) as exc_info:
            await email_tool.handle_action("update_email", {"email": "ops@"})
        suggestions = " ".join(exc_info.value.suggestions or [])
        assert "get_system_setup(action='validate_email', email='ops@')" in suggestions
        assert "validate_email() to" not in suggestions

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auth_mode", ["api_key", "clerk"])
    async def test_hosted_quick_start_and_examples_never_name_update_email(
        self, email_tool, monkeypatch, auth_mode
    ):
        monkeypatch.setenv("AUTH_MODE", auth_mode)
        guide = "\n".join(await email_tool._get_quick_start_guide())
        examples = (await email_tool.handle_action("get_examples", {}))[0].text
        for text in (guide, examples):
            assert "update_email" not in text
            assert "manage_alerts(action='create_simple', threshold=100, email=" in text
            assert not bare_setup_calls_in(text)

    @pytest.mark.asyncio
    async def test_local_quick_start_and_examples_name_update_email_through_system_setup(
        self, email_tool, monkeypatch
    ):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        guide = "\n".join(await email_tool._get_quick_start_guide())
        examples = (await email_tool.handle_action("get_examples", {}))[0].text
        assert "manage_system_setup(action='update_email', email='your@email.com')" in guide
        assert "manage_system_setup(action='update_email', email='new@email.com')" in examples
        for text in (guide, examples):
            assert not bare_setup_calls_in(text)


class TestAnInvalidAddressIsNotPromisedNotifications:
    """check_status never says a malformed address will receive notifications."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auth_mode", ["env", "api_key"])
    async def test_an_invalid_address_gets_fix_steps_instead_of_notification_types(
        self, email_tool, monkeypatch, auth_mode
    ):
        monkeypatch.setenv("AUTH_MODE", auth_mode)
        with configured("bob@"):
            result = await email_tool.handle_action("check_status", {})
        text = result[0].text
        assert "will receive notifications" not in text
        assert "Notification Types" not in text
        assert "## Fix the Address" in text
        assert "get_system_setup(action='validate_email', email='your@email.com')" in text

    @pytest.mark.asyncio
    async def test_a_valid_address_is_described_as_the_default_for_alerts_without_an_email(
        self, email_tool
    ):
        with configured("bob@example.com"):
            text = (await email_tool.handle_action("check_status", {}))[0].text
        assert ADDRESS_SCOPE in text
        assert "System status updates" not in text
        assert "Performance reports" not in text


class TestAddressAndSourceComeFromOneLookup:
    """The address and its Source label are read in one walk of the precedence."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["check_status", "test_configuration"])
    async def test_one_walk_supplies_the_address_and_its_label(
        self, email_tool, monkeypatch, tmp_path, action
    ):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "env@example.com")
        monkeypatch.setattr(_default_cache, "cache_file", tmp_path / "none.json")
        walks = []
        original = ConfigurationStore.get_value_with_source

        def counted(store, *args, **kwargs):
            walks.append(args)
            return original(store, *args, **kwargs)

        with patch.object(ConfigurationStore, "get_value_with_source", counted):
            result = await email_tool.handle_action(action, {})
        assert len(walks) == 1
        assert "env@example.com" in result[0].text
        assert "**Source**: Environment variable REVENIUM_DEFAULT_EMAIL" in result[0].text


class TestSetupGuidanceJudgesTheAddress:
    """setup_guidance gives the same verdict and Source label as check_status."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auth_mode", ["env", "api_key"])
    async def test_an_invalid_address_gets_fix_steps_instead_of_ready(
        self, email_tool, monkeypatch, auth_mode
    ):
        monkeypatch.setenv("AUTH_MODE", auth_mode)
        with configured("alerts@", source="cache"):
            text = (await email_tool.handle_action("setup_guidance", {}))[0].text
        assert "Configured and ready" not in text
        assert "Not a valid email address" in text
        assert "## Fix the Address" in text
        assert "get_system_setup(action='validate_email', email='your@email.com')" in text
        assert "**Source**: Configuration cache (.revenium_cache)" in text

    @pytest.mark.asyncio
    async def test_a_valid_address_is_ready_and_names_its_source(self, email_tool):
        with configured("bob@example.com"):
            text = (await email_tool.handle_action("setup_guidance", {}))[0].text
        assert "**Status**: Configured and ready" in text
        assert "**Source**: Environment variable REVENIUM_DEFAULT_EMAIL" in text


class TestCapabilitiesMatchTheServer:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("auth_mode", ["api_key", "clerk"])
    async def test_hosted_capabilities_say_update_email_is_not_available(
        self, email_tool, monkeypatch, auth_mode
    ):
        monkeypatch.setenv("AUTH_MODE", auth_mode)
        text = (await email_tool.handle_action("get_capabilities", {}))[0].text
        assert "Update notification email address" not in text
        assert "**update_email** - Not available on this server" in text
        assert "manage_alerts(action='create_simple', threshold=100, email=" in text

    @pytest.mark.asyncio
    async def test_local_capabilities_offer_update_email(self, email_tool, monkeypatch):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        text = (await email_tool.handle_action("get_capabilities", {}))[0].text
        assert "**update_email** - Update notification email address" in text


class TestAlertsUseTheAddressCheckStatusReports:
    """BACK-4743: the fix steps' update_email changes the address alerts default to."""

    @pytest.fixture
    def cache(self, monkeypatch, tmp_path):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        path = tmp_path / "cache.json"
        monkeypatch.setattr(_default_cache, "cache_file", path)
        return path

    @pytest.mark.asyncio
    async def test_fixing_an_invalid_environment_address_changes_the_alert_default(
        self, email_tool, monkeypatch, cache
    ):
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "bob@")
        _write_cache(
            cache,
            {
                "REVENIUM_API_KEY": "fake-key-for-tests",
                "REVENIUM_TEAM_ID": "team_test",
                "REVENIUM_TENANT_ID": "tenant_test",
                "REVENIUM_OWNER_ID": "owner_test",
            },
        )
        assert default_notification_email() == "bob@"

        await email_tool.handle_action("update_email", {"email": "ops@company.com"})
        status = (await email_tool.handle_action("check_status", {}))[0].text

        assert "**Current Email**: ops@company.com" in status
        assert default_notification_email() == "ops@company.com"

    def test_the_environment_address_is_the_default_when_nothing_is_saved(
        self, monkeypatch, cache
    ):
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "env@example.com")
        assert default_notification_email() == "env@example.com"

    def test_a_hosted_caller_never_gets_the_saved_address(self, monkeypatch, cache):
        monkeypatch.setenv("AUTH_MODE", "clerk")
        _write_cache(cache, {"REVENIUM_DEFAULT_EMAIL": "operator@example.com"})
        caller = TenantContext(team_id="TeamC", api_key="caller-key", email="caller@example.com")
        with signed_in(caller):
            assert default_notification_email() == "caller@example.com"

    def test_a_saved_placeholder_falls_back_to_the_environment(self, monkeypatch, cache):
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "env@example.com")
        _write_cache(cache, {"REVENIUM_DEFAULT_EMAIL": "dummy@email.com"})
        assert default_notification_email() == "env@example.com"

    @pytest.mark.asyncio
    async def test_the_fix_step_says_which_alerts_the_saved_address_reaches(
        self, email_tool, monkeypatch, cache
    ):
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "bob@")
        status = (await email_tool.handle_action("check_status", {}))[0].text
        assert (
            "2. Set the address alerts created without an email go to with "
            "`manage_system_setup(action='update_email', email='your@email.com')`"
        ) in status


class TestEveryEmailReaderSkipsWhatAlertsSkip:
    """check_status, setup_guidance, test_configuration and the alert default read one filtered walk."""

    @pytest.fixture
    def cache(self, monkeypatch, tmp_path):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        path = tmp_path / "cache.json"
        monkeypatch.setattr(_default_cache, "cache_file", path)
        return path

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["check_status", "setup_guidance", "test_configuration"])
    async def test_a_saved_placeholder_is_skipped_by_every_report(
        self, email_tool, monkeypatch, cache, action
    ):
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "env@example.com")
        _write_cache(cache, {"REVENIUM_DEFAULT_EMAIL": "dummy@email.com"})
        text = (await email_tool.handle_action(action, {}))[0].text
        assert "dummy@email.com" not in text
        assert default_notification_email() == "env@example.com"
        assert "env@example.com" in text
        assert "**Source**: Environment variable REVENIUM_DEFAULT_EMAIL" in text

    @pytest.mark.asyncio
    async def test_a_padded_address_is_reported_as_alerts_use_it(
        self, email_tool, monkeypatch, cache
    ):
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "  env@example.com  ")
        text = (await email_tool.handle_action("check_status", {}))[0].text
        assert default_notification_email() == "env@example.com"
        assert "**Current Email**: env@example.com\n" in text

    def test_a_hosted_placeholder_leaves_the_address_unset(self, monkeypatch, cache):
        monkeypatch.setenv("AUTH_MODE", "clerk")
        caller = TenantContext(team_id="TeamC", api_key="caller-key", email="dummy@email.com")
        with signed_in(caller):
            assert notification_email_with_source() == (None, None)

    def test_the_alert_default_reads_the_same_single_walk(self, monkeypatch, cache):
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "env@example.com")
        walks = []
        original = ConfigurationStore.get_value_with_source

        def counted(store, *args, **kwargs):
            walks.append(args)
            return original(store, *args, **kwargs)

        with patch.object(ConfigurationStore, "get_value_with_source", counted):
            assert default_notification_email() == "env@example.com"
        assert len(walks) == 1


class TestUpdateEmailSaysWhatItChanges:
    @pytest.mark.asyncio
    async def test_success_names_the_alerts_it_reaches_and_how_long_it_is_kept(
        self, email_tool, monkeypatch
    ):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        text = (await email_tool.handle_action("update_email", {"email": "ops@company.com"}))[0].text
        assert ADDRESS_SCOPE in text
        assert (
            f"It is saved in {saved_notification_email.path.resolve()}, ahead of "
            "REVENIUM_DEFAULT_EMAIL, and stays the default until you save another address "
            "or delete that file."
        ) in text
        assert "expire" not in text

    @pytest.mark.asyncio
    async def test_success_says_the_saved_address_overrides_a_different_environment_email(
        self, email_tool, monkeypatch
    ):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "env@company.com")
        text = (await email_tool.handle_action("update_email", {"email": "ops@company.com"}))[0].text
        assert (
            "REVENIUM_DEFAULT_EMAIL is set to env@company.com; the saved address is used instead."
        ) in text

    @pytest.mark.asyncio
    async def test_success_adds_no_override_note_when_the_environment_email_matches(
        self, email_tool, monkeypatch
    ):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "Ops@Company.com")
        text = (await email_tool.handle_action("update_email", {"email": "ops@company.com"}))[0].text
        assert "is used instead" not in text

    @pytest.mark.asyncio
    async def test_test_configuration_scope_matches_check_status(self, email_tool):
        with configured("bob@example.com"):
            text = (await email_tool.handle_action("test_configuration", {}))[0].text
        assert f"**Scope**: {ADDRESS_SCOPE}" in text
        assert "all notification types" not in text


BROADER_THAN_ADDRESS_SCOPE = (
    "system status",
    "system updates",
    "configuration updates",
    "performance",
    "monitoring",
    "all notification types",
)


class TestNoBranchPromisesMoreThanTheAddressScope:
    """Every check_status and test_configuration branch describes the address's reach the same way."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["check_status", "test_configuration"])
    @pytest.mark.parametrize("address", [None, "bob@example.com"])
    async def test_the_branch_states_the_address_scope(self, email_tool, action, address):
        with configured(address):
            text = (await email_tool.handle_action(action, {}))[0].text
        assert ADDRESS_SCOPE in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["check_status", "test_configuration"])
    @pytest.mark.parametrize("address", [None, "bob@example.com", "bob@"])
    async def test_the_branch_promises_nothing_beyond_the_address_scope(
        self, email_tool, action, address
    ):
        with configured(address):
            text = (await email_tool.handle_action(action, {}))[0].text.lower()
        assert [claim for claim in BROADER_THAN_ADDRESS_SCOPE if claim in text] == []

    @pytest.mark.asyncio
    async def test_the_missing_address_error_states_the_address_scope(self, email_tool):
        with pytest.raises(ToolError) as exc_info:
            await email_tool.handle_action("update_email", {})
        message = json.dumps(exc_info.value.examples)
        assert "system updates" not in message.lower()
        assert ADDRESS_SCOPE in message


class TestTheSavedAddressOutlivesTheCache:
    """BACK-4967: an address saved with update_email stays the alert default after the cache TTL."""

    @pytest.fixture
    def clock(self, monkeypatch):
        now = [time.time()]
        monkeypatch.setattr(config_cache_module, "time", SimpleNamespace(time=lambda: now[0]))
        return now

    @pytest.mark.asyncio
    async def test_the_saved_address_is_the_alert_default_after_the_cache_expires(
        self, email_tool, monkeypatch, tmp_path, clock
    ):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "env@example.com")
        cache = tmp_path / "cache.json"
        cache.write_text(
            json.dumps({"timestamp": clock[0], "config": _REQUIRED_CACHE_FIELDS, "version": "1.0"})
        )
        monkeypatch.setattr(_default_cache, "cache_file", cache)

        await email_tool.handle_action("update_email", {"email": "ops@company.com"})
        clock[0] += _default_cache.cache_ttl_seconds + 3600

        assert not _default_cache.is_cache_valid()
        assert default_notification_email() == "ops@company.com"
        status = (await email_tool.handle_action("check_status", {}))[0].text
        assert "**Current Email**: ops@company.com" in status

    @pytest.mark.asyncio
    async def test_a_hosted_caller_never_gets_the_saved_address(self, email_tool, monkeypatch):
        monkeypatch.delenv("AUTH_MODE", raising=False)
        await email_tool.handle_action("update_email", {"email": "operator@example.com"})
        monkeypatch.setenv("AUTH_MODE", "clerk")
        caller = TenantContext(team_id="TeamC", api_key="caller-key", email="caller@example.com")
        with signed_in(caller):
            assert default_notification_email() == "caller@example.com"

    def test_a_saved_placeholder_falls_back_to_the_environment(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "env@example.com")
        saved_notification_email.save("dummy@email.com")
        assert default_notification_email() == "env@example.com"
