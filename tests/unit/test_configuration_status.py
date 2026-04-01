"""Unit tests for ConfigurationStatus tool.

Tests handle_action routing, unknown action error handling,
and the builder methods for environment variables, auto-discovery,
onboarding status, and system health reports.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from mcp.types import TextContent

from src.revenium_mcp_server.tools_decomposed.configuration_status import (
    ConfigurationStatus,
)


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
    async def test_unknown_action_returns_structured_error(self, config_tool):
        """Unknown action returns structured error with list of valid actions."""
        result = await config_tool.handle_action("nonexistent_action", {})
        text = result[0].text
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
    async def test_handler_exception_returns_error_text(self, config_tool):
        """Generic exception in handler returns error TextContent, not a raise."""
        config_tool._handle_environment_variables = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        result = await config_tool.handle_action("environment_variables", {})
        text = result[0].text
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

    def _make_validation_result(self, overall=True):
        result = MagicMock()
        result.summary = {
            "overall_status": overall,
            "direct_api_works": overall,
            "auto_discovery_works": overall,
        }
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
