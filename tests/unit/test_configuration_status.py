"""Unit tests for ConfigurationStatus tool.

Tests handle_action routing, unknown action error handling,
and the builder methods for environment variables, auto-discovery,
onboarding status, and system health reports.
"""

import pytest
from src.revenium_mcp_server.common.error_handling import ToolError
from unittest.mock import AsyncMock, patch, MagicMock
from mcp.types import TextContent

from src.revenium_mcp_server.onboarding.env_validation import API_AUTH_REJECTED_MESSAGE
from src.revenium_mcp_server.tools_decomposed.configuration_status import (
    ConfigurationStatus,
)


@pytest.fixture(autouse=True)
def _platform_read_succeeds():
    """Renderer tests here mock the validator; the platform read itself is fixed."""
    from src.revenium_mcp_server.onboarding.platform_read import PlatformFacts

    facts = PlatformFacts(read={"status": "success", "status_code": 200, "payload": {}})
    with patch(
        "src.revenium_mcp_server.tools_decomposed.configuration_status.read_platform_facts",
        new=AsyncMock(return_value=facts),
    ), patch(
        "src.revenium_mcp_server.onboarding.platform_read.probe_platform_read",
        new=AsyncMock(return_value=facts.read),
    ):
        yield


@pytest.fixture
def config_tool():
    """Create a ConfigurationStatus instance."""
    return ConfigurationStatus()


class TestHandleActionRouting:
    """Test that handle_action routes correctly and returns proper responses."""

    @pytest.mark.asyncio
    async def test_get_capabilities_returns_capabilities_text(self, config_tool):
        """get_capabilities returns text describing all available actions."""
        result = await config_tool.handle_action("get_capabilities", {})
        text = result[0].text
        assert "Configuration Status Capabilities" in text
        assert "environment_variables" in text
        assert "auto_discovery" in text
        assert "system_health" in text

    @pytest.mark.asyncio
    async def test_get_examples_returns_usage_examples(self, config_tool):
        """get_examples returns text with JSON example payloads."""
        result = await config_tool.handle_action("get_examples", {})
        text = result[0].text
        assert "Examples" in text
        assert "environment_variables" in text
        assert "auto_discovery" in text

    @pytest.mark.asyncio
    async def test_unknown_action_raises_a_structured_error(self, config_tool):
        """Unknown action returns structured error with list of valid actions."""
        with pytest.raises(ToolError) as refused:
            await config_tool.handle_action("nonexistent_action", {})
        text = refused.value.message
        assert "nonexistent_action" in text or "Unknown" in text
        # Should mention valid actions
        assert "environment_variables" in text

    @pytest.mark.asyncio
    async def test_environment_variables_delegates_to_handler(self, config_tool):
        """environment_variables action runs the real handler and returns analysis text."""
        from unittest.mock import AsyncMock, patch, MagicMock

        # Build a minimal but realistic validation result
        validation_result = MagicMock()
        validation_result.variables = {"REVENIUM_API_KEY": {"status": "set"}}

        with patch(
            "src.revenium_mcp_server.tools_decomposed.configuration_status.validate_environment_variables",
            new_callable=AsyncMock,
            return_value=validation_result,
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.configuration_status.get_config_value",
            return_value="test-api-key-value",
        ):
            result = await config_tool.handle_action("environment_variables", {"verbose": True})

        # Verify the real handler produced substantive output about environment variables
        assert len(result) == 1
        text = result[0].text
        assert "Environment Variables" in text
        assert "REVENIUM_API_KEY" in text
        # API key values must be hidden in output
        assert "SET (hidden)" in text

    @pytest.mark.asyncio
    async def test_auto_discovery_delegates_to_handler(self, config_tool):
        """auto_discovery action invokes _handle_auto_discovery."""
        config_tool._handle_auto_discovery = AsyncMock(
            return_value=[TextContent(type="text", text="discovery result")]
        )
        result = await config_tool.handle_action("auto_discovery", {})
        config_tool._handle_auto_discovery.assert_called_once_with({})
        assert result[0].text == "discovery result"

    @pytest.mark.asyncio
    async def test_onboarding_status_delegates_to_handler(self, config_tool):
        """onboarding_status action invokes _handle_onboarding_status."""
        config_tool._handle_onboarding_status = AsyncMock(
            return_value=[TextContent(type="text", text="onboarding result")]
        )
        result = await config_tool.handle_action("onboarding_status", {})
        config_tool._handle_onboarding_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_system_health_delegates_to_handler(self, config_tool):
        """system_health action invokes _handle_system_health."""
        config_tool._handle_system_health = AsyncMock(
            return_value=[TextContent(type="text", text="health result")]
        )
        result = await config_tool.handle_action("system_health", {})
        config_tool._handle_system_health.assert_called_once()

    @pytest.mark.asyncio
    async def test_handler_exception_raises_a_tool_error(self, config_tool):
        """BACK-5086: a generic exception in a handler raises a flagged TOOL_ERROR."""
        config_tool._handle_environment_variables = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        with pytest.raises(ToolError) as refused:
            await config_tool.handle_action("environment_variables", {})
        text = refused.value.message
        assert "Failed to execute" in text or "error" in text.lower()


class TestSupportedActions:
    """Test _get_supported_actions."""

    @pytest.mark.asyncio
    async def test_returns_all_core_actions(self, config_tool):
        """Supported actions include all four core actions."""
        actions = await config_tool._get_supported_actions()
        assert "environment_variables" in actions
        assert "auto_discovery" in actions
        assert "onboarding_status" in actions
        assert "system_health" in actions


class TestBuildEnvironmentVariablesAnalysis:
    """Test _build_environment_variables_analysis produces correct categorization."""

    def test_api_key_categorized_as_core_required(self, config_tool):
        """REVENIUM_API_KEY goes into 'Core Required' category and its value is hidden."""
        validation_result = MagicMock()
        validation_result.variables = {"REVENIUM_API_KEY": {"status": "set"}}
        with patch(
            "src.revenium_mcp_server.tools_decomposed.configuration_status.get_config_value",
            return_value="test-key-123",
        ):
            text = config_tool._build_environment_variables_analysis(validation_result)
        # Variable must appear under its category heading
        assert "Core Required" in text
        assert "REVENIUM_API_KEY" in text
        # The actual key value must NOT appear in output — security requirement
        assert "test-key-123" not in text
        assert "SET (hidden)" in text
        # Criticality label must be present
        assert "CRITICAL" in text

    def test_email_categorized_as_notifications(self, config_tool):
        """REVENIUM_DEFAULT_EMAIL goes into 'Notifications' category and value is shown."""
        validation_result = MagicMock()
        validation_result.variables = {"REVENIUM_DEFAULT_EMAIL": {"status": "set"}}
        with patch(
            "src.revenium_mcp_server.tools_decomposed.configuration_status.get_config_value",
            return_value="test@example.com",
        ):
            text = config_tool._build_environment_variables_analysis(validation_result)
        # Email goes in Notifications, not Core Required or URLs
        assert "Notifications" in text
        assert "Core Required" not in text
        assert "URLs and Endpoints" not in text
        # Email value should be visible (it's not a secret like an API key)
        assert "test@example.com" in text

    def test_url_categorized_as_urls_and_endpoints(self, config_tool):
        """REVENIUM_BASE_URL goes into 'URLs and Endpoints' category and value is shown."""
        validation_result = MagicMock()
        validation_result.variables = {"REVENIUM_BASE_URL": {"status": "set"}}
        with patch(
            "src.revenium_mcp_server.tools_decomposed.configuration_status.get_config_value",
            return_value="https://api.example.com",
        ):
            text = config_tool._build_environment_variables_analysis(validation_result)
        # URL variable must go into the correct category
        assert "URLs and Endpoints" in text
        assert "REVENIUM_BASE_URL" in text
        # URL values are not secrets — they should be visible in the output
        assert "https://api.example.com" in text

    def test_unset_variable_shows_not_set(self, config_tool):
        """Variables without values show NOT SET status with a failure indicator."""
        validation_result = MagicMock()
        validation_result.variables = {"REVENIUM_TEAM_ID": {"status": "missing"}}
        with patch(
            "src.revenium_mcp_server.tools_decomposed.configuration_status.get_config_value",
            return_value=None,
        ):
            text = config_tool._build_environment_variables_analysis(validation_result)
        # Missing variable must be clearly flagged — users need to know what to set
        assert "NOT SET" in text
        assert "[FAIL]" in text
        # The variable name must appear so users know what is missing
        assert "REVENIUM_TEAM_ID" in text
        # A set value must NOT appear — get_config_value returned None
        assert "[OK]" not in text

    def test_statistics_section_included(self, config_tool):
        """Output includes Statistics section with configuration rate."""
        validation_result = MagicMock()
        validation_result.variables = {"REVENIUM_API_KEY": {}}
        with patch(
            "src.revenium_mcp_server.tools_decomposed.configuration_status.get_config_value",
            return_value=None,
        ):
            text = config_tool._build_environment_variables_analysis(validation_result)
        assert "Statistics" in text
        assert "Configuration Rate" in text


class TestBuildAutoDiscoveryAnalysis:
    """Test _build_auto_discovery_analysis for success and failure paths."""

    def test_success_status_shows_working(self, config_tool):
        """When status is success, report shows WORKING heading."""
        validation_result = MagicMock()
        validation_result.discovered_config = {
            "status": "success",
            "discovered_count": 3,
            "values": {"team_id": "t1", "tenant_id": "tn1", "api_key": "secret"},
        }
        text = config_tool._build_auto_discovery_analysis(validation_result)
        assert "WORKING" in text
        assert "3" in text

    def test_success_hides_api_key_values(self, config_tool):
        """API key values in discovered results are hidden."""
        validation_result = MagicMock()
        validation_result.discovered_config = {
            "status": "success",
            "discovered_count": 1,
            "values": {"api_key": "secret123"},
        }
        text = config_tool._build_auto_discovery_analysis(validation_result)
        assert "SET (hidden)" in text
        assert "secret123" not in text

    def test_failure_status_shows_failed(self, config_tool):
        """When status is not success, report shows FAILED heading."""
        validation_result = MagicMock()
        validation_result.discovered_config = {
            "status": "failed",
            "error": "Connection refused",
        }
        text = config_tool._build_auto_discovery_analysis(validation_result)
        assert "FAILED" in text
        assert "Connection refused" in text
        assert "Manual Configuration" in text

    def test_high_effectiveness_shows_excellent(self, config_tool):
        """Effectiveness >= 80% shows EXCELLENT rating."""
        validation_result = MagicMock()
        validation_result.discovered_config = {
            "status": "success",
            "discovered_count": 4,
            "values": {"a": "1", "b": "2", "c": "3", "d": "4", "e": "5"},
        }
        text = config_tool._build_auto_discovery_analysis(validation_result)
        assert "EXCELLENT" in text


class TestBuildOnboardingStatusAnalysis:
    """Test _build_onboarding_status_analysis for different user states."""

    def _make_onboarding_state(self, first_time=False, completion=None):
        state = MagicMock()
        state.is_first_time = first_time
        state.cache_exists = not first_time
        state.cache_valid = not first_time
        state.has_existing_data = not first_time
        state.setup_completion = completion or {}
        state.recommendations = ["Do this", "Do that"]
        return state

    def _make_validation_result(self, overall=True, read_status="success"):
        result = MagicMock()
        result.summary = {
            "overall_status": overall,
            "direct_api_works": overall,
            "auto_discovery_works": overall,
        }
        result.api_connectivity = {"status": read_status}
        return result

    def test_first_time_user_identified(self, config_tool):
        """First-time users get 'First-Time User' heading and NOT 'Returning User'."""
        state = self._make_onboarding_state(first_time=True)
        validation = self._make_validation_result()
        text = config_tool._build_onboarding_status_analysis(state, validation)
        assert "First-Time User" in text
        # Must not misidentify as a returning user
        assert "Returning User" not in text

    def test_returning_user_identified(self, config_tool):
        """Returning users get 'Returning User' heading and NOT 'First-Time User'."""
        state = self._make_onboarding_state(first_time=False)
        validation = self._make_validation_result()
        text = config_tool._build_onboarding_status_analysis(state, validation)
        assert "Returning User" in text
        # Must not misidentify as a first-time user
        assert "First-Time User" not in text

    def test_low_completion_shows_starting(self, config_tool):
        """Completion < 40% shows STARTING assessment and not a higher rating."""
        state = self._make_onboarding_state(
            completion={"api_key_configured": True}
        )
        validation = self._make_validation_result(overall=False)
        text = config_tool._build_onboarding_status_analysis(state, validation)
        # 1/6 items = 16.7% -> STARTING
        assert "STARTING" in text
        # Must not show a better status than warranted
        assert "EXCELLENT" not in text
        assert "GOOD" not in text

    def test_high_completion_shows_excellent(self, config_tool):
        """Completion >= 80% shows EXCELLENT assessment."""
        state = self._make_onboarding_state(
            completion={
                "api_key_configured": True,
                "team_id_configured": True,
                "email_configured": True,
                "slack_configured": True,
                "cache_valid": True,
                "auto_discovery_working": False,
            }
        )
        validation = self._make_validation_result()
        text = config_tool._build_onboarding_status_analysis(state, validation)
        assert "EXCELLENT" in text

    def test_hosted_caller_is_not_scored_on_server_auto_discovery(self, config_tool):
        """Auto-discovery reads server settings, so it never scores a hosted caller."""
        state = self._make_onboarding_state(
            completion={
                "api_key_configured": True,
                "team_id_configured": True,
                "email_configured": True,
                "slack_configured": True,
                "auto_discovery_working": False,
            }
        )
        validation = self._make_validation_result()
        validation.summary["auto_discovery_works"] = False
        validation.summary["credential_source"] = "request"
        text = config_tool._build_onboarding_status_analysis(state, validation)
        assert "Auto-Discovery" not in text
        assert "**Overall Completion**: 4/4" in text

    @pytest.mark.parametrize("slack_configured", [True, False])
    def test_slack_step_is_suggested_only_without_slack(self, config_tool, slack_configured):
        state = self._make_onboarding_state(
            completion={
                "api_key_configured": True,
                "team_id_configured": True,
                "email_configured": True,
                "slack_configured": slack_configured,
                "cache_valid": False,
                "auto_discovery_working": False,
            }
        )
        text = config_tool._build_onboarding_status_analysis(
            state, self._make_validation_result()
        )
        assert "**Recommended Actions**" in text
        assert ("Configure optional features like Slack" in text) is not slack_configured


class TestBuildSystemHealthSummary:
    """Test _build_system_health_summary for different health states."""

    def _make_state(self, first_time=False, cache_valid=True):
        state = MagicMock()
        state.is_first_time = first_time
        state.cache_valid = cache_valid
        return state

    def _make_validation(self, api_key=True, api_works=True, auth=True, discovery=True):
        result = MagicMock()
        result.summary = {
            "overall_status": api_key and api_works,
            "api_key_available": api_key,
            "direct_api_works": api_works,
            "auth_config_works": auth,
            "auto_discovery_works": discovery,
        }
        return result

    def test_healthy_system_shows_healthy(self, config_tool):
        """All checks passing shows HEALTHY overall status and EXCELLENT score."""
        state = self._make_state()
        validation = self._make_validation()
        text = config_tool._build_system_health_summary(validation, state)
        # Overall health heading must reflect healthy state
        assert "HEALTHY" in text
        # Score must be EXCELLENT (all critical + optional passing = >=90%)
        assert "EXCELLENT" in text
        # Must not show any critical failure messages
        assert "NEEDS ATTENTION" not in text
        assert "API key not configured" not in text

    def test_no_api_key_shows_critical(self, config_tool):
        """Missing API key triggers critical diagnostic message."""
        state = self._make_state()
        validation = self._make_validation(api_key=False, api_works=False)
        text = config_tool._build_system_health_summary(validation, state)
        assert "NEEDS ATTENTION" in text
        assert "API key not configured" in text

    def test_first_time_user_cache_not_penalized(self, config_tool):
        """First-time users with no cache still get cache marked as healthy."""
        state = self._make_state(first_time=True, cache_valid=False)
        validation = self._make_validation()
        text = config_tool._build_system_health_summary(validation, state)
        # Cache System should show Available for first-time users
        assert "Cache System" in text
        # Should mention first-time info
        assert "first-time" in text.lower()

    def test_weighted_health_score_present(self, config_tool):
        """Health score section includes weighted percentage."""
        state = self._make_state()
        validation = self._make_validation()
        text = config_tool._build_system_health_summary(validation, state)
        assert "Health Score" in text
        assert "Critical:" in text
        assert "Optional:" in text

    def _make_clerk_validation(self, read_succeeded=True):
        """Clerk/OAuth-mode summary for a signed-in caller: the verdict is the read."""
        result = MagicMock()
        result.summary = {
            "auth_mode": "clerk",
            "credential_source": "request",
            "clerk_configured": True,
            "overall_status": read_succeeded,
            "api_key_available": True,
            "direct_api_works": read_succeeded,
            "api_unreachable": not read_succeeded,
            "auth_config_works": True,
            "auto_discovery_works": True,
        }
        return result

    def test_clerk_mode_with_successful_read_is_healthy(self, config_tool):
        """Clerk mode is HEALTHY when the caller's own read succeeded."""
        state = self._make_state()
        validation = self._make_clerk_validation(read_succeeded=True)
        text = config_tool._build_system_health_summary(validation, state)
        assert "NEEDS ATTENTION" not in text
        assert "system cannot function" not in text
        assert "NOT READY" not in text
        # Critical component is labelled for the sign-in model, not the API-key model
        assert "**Sign-in**: Operational" in text
        assert "API Key Configuration" not in text
        assert "Cache System" not in text

    def test_clerk_mode_without_successful_read_is_unhealthy(self, config_tool):
        """Clerk mode with OAuth configured but no successful read is not healthy."""
        state = self._make_state()
        validation = self._make_clerk_validation(read_succeeded=False)
        text = config_tool._build_system_health_summary(validation, state)
        assert "NEEDS ATTENTION" in text
        assert "[NOT READY]" in text
        assert "could not be reached" in text

    def _make_forbidden_validation(self, detail=None):
        """API-key mode where the key authenticates but every read is forbidden."""
        result = MagicMock()
        result.summary = {
            "auth_mode": "api_key",
            "overall_status": False,
            "api_key_available": True,
            "direct_api_works": False,
            "api_read_forbidden": True,
            "api_read_forbidden_detail": detail,
            "auth_config_works": True,
            "auto_discovery_works": True,
        }
        return result

    def test_forbidden_read_is_not_production_ready(self, config_tool):
        """A 403 probe must never yield a READY verdict or a full critical score."""
        state = self._make_state()
        validation = self._make_forbidden_validation(
            detail="The API refused to let this key read data (HTTP 403) - check the key scope."
        )
        text = config_tool._build_system_health_summary(validation, state)
        assert "[READY] System is ready for production use" not in text
        assert "[NOT READY]" in text
        assert "NEEDS ATTENTION" in text
        assert "EXCELLENT" not in text
        # One of two critical checks passes.
        assert "Critical: 1/2" in text

    def test_forbidden_read_surfaces_the_key_scope_cause(self, config_tool):
        """The scope-specific detail replaces the generic connectivity message."""
        state = self._make_state()
        validation = self._make_forbidden_validation(
            detail="metering-scope key (rev_mk_ prefix) cannot read analytics"
        )
        text = config_tool._build_system_health_summary(validation, state)
        assert "metering-scope key (rev_mk_ prefix) cannot read analytics" in text
        assert "API connectivity failed - check network and authentication" not in text
        assert (
            "Forbidden - the key cannot read data (wrong scope or unrecognized key)" in text
        )
        # The remediation names the cause instead of generic setup advice.
        assert "Verify REVENIUM_API_KEY and replace it with a key that has read access" in text

    def test_forbidden_read_without_detail_falls_back_to_scope_message(self, config_tool):
        """Missing detail still explains the key-scope cause, not a network failure."""
        state = self._make_state()
        validation = self._make_forbidden_validation(detail=None)
        text = config_tool._build_system_health_summary(validation, state)
        assert "rev_mk_" in text
        assert "API connectivity failed - check network and authentication" not in text

    def test_plain_connectivity_failure_keeps_generic_message(self, config_tool):
        """Without the forbidden flag the generic connectivity diagnostic is unchanged."""
        state = self._make_state()
        validation = self._make_validation(api_key=True, api_works=False)
        text = config_tool._build_system_health_summary(validation, state)
        assert "API connectivity failed - check network and authentication" in text
        assert "cannot read data" not in text

    def _make_auth_rejected_validation(self, detail=None):
        """API-key mode where the platform did not accept the configured key (401)."""
        result = MagicMock()
        result.summary = {
            "auth_mode": "api_key",
            "overall_status": False,
            "api_key_available": True,
            "direct_api_works": False,
            "api_read_forbidden": False,
            "api_read_forbidden_detail": None,
            "api_auth_rejected": True,
            "api_auth_rejected_detail": detail,
            "auth_config_works": True,
            "auto_discovery_works": True,
        }
        return result

    def test_rejected_key_is_not_production_ready(self, config_tool):
        """A 401 probe must never yield a READY verdict (BACK-2841)."""
        state = self._make_state()
        validation = self._make_auth_rejected_validation(detail=API_AUTH_REJECTED_MESSAGE)
        text = config_tool._build_system_health_summary(validation, state)
        assert "[READY] System is ready for production use" not in text
        assert "[NOT READY]" in text
        assert "NEEDS ATTENTION" in text
        assert "Critical: 1/2" in text

    def test_rejected_key_surfaces_the_shared_401_wording(self, config_tool):
        """The 401 detail replaces the generic connectivity message (BACK-2841)."""
        state = self._make_state()
        validation = self._make_auth_rejected_validation(detail=API_AUTH_REJECTED_MESSAGE)
        text = config_tool._build_system_health_summary(validation, state)
        assert API_AUTH_REJECTED_MESSAGE in text
        assert "API connectivity failed - check network and authentication" not in text
        assert "Rejected - the platform did not accept the key (HTTP 401)" in text
        # The remediation says wait and retry before replacing the key.
        assert (
            "Wait a moment and retry before replacing REVENIUM_API_KEY" in text
        )
        # The 403 wording must not leak into the 401 case.
        assert "The API refused to let this key read data" not in text

    def test_rejected_key_without_detail_falls_back_to_shared_message(self, config_tool):
        """Missing detail still explains the rejected-key case, not a network failure."""
        state = self._make_state()
        validation = self._make_auth_rejected_validation(detail=None)
        text = config_tool._build_system_health_summary(validation, state)
        assert API_AUTH_REJECTED_MESSAGE in text
        assert "API connectivity failed - check network and authentication" not in text
