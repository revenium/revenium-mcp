"""Unit tests for Slack OAuth Workflow Formatters.

Tests the pure formatting functions that transform OAuth and configuration
data into user-facing TextContent output.
"""

import pytest
from mcp.types import TextContent

from src.revenium_mcp_server.tools_decomposed.slack_oauth_formatters import (
    format_oauth_initiation_response,
    format_oauth_instructions,
    format_refresh_configurations_response,
    format_check_new_configurations_response,
    get_oauth_examples_text,
    get_oauth_capabilities_text,
)


class TestFormatOAuthInitiationResponse:
    """Test OAuth initiation response: the user sees a link and login warning."""

    def test_contains_oauth_url_and_login_warning(self):
        result = format_oauth_initiation_response(
            oauth_url="https://app.revenium.io/slack/connect?returnTo=/alerts",
            app_base_url="https://app.revenium.io",
            return_to="/alerts",
        )
        text = result[0].text
        assert "https://app.revenium.io/slack/connect" in text
        assert "logged into Revenium" in text
        assert "refresh_configurations" in text

    def test_includes_app_base_url_for_login(self):
        result = format_oauth_initiation_response(
            oauth_url="https://custom.io/slack/connect",
            app_base_url="https://custom.io",
            return_to="/alerts",
        )
        assert "https://custom.io" in result[0].text


class TestFormatOAuthInstructions:
    """Test static OAuth setup instructions."""

    def test_contains_troubleshooting_sections(self):
        result = format_oauth_instructions()
        text = result[0].text
        assert "Troubleshooting" in text
        assert "Page not found" in text
        assert "Authentication failed" in text
        assert "Slack authorization failed" in text

    def test_contains_step_by_step_process(self):
        result = format_oauth_instructions()
        text = result[0].text
        assert "initiate_oauth" in text
        assert "refresh_configurations" in text


class TestFormatRefreshConfigurationsResponse:
    """Test configuration refresh response formatting."""

    def test_empty_configurations_shows_troubleshooting(self):
        result = format_refresh_configurations_response([], total_elements=0)
        text = result[0].text
        assert "No Configurations Found" in text
        assert "Wait a moment" in text
        assert "initiate_oauth" in text

    def test_with_configurations_shows_details_and_next_steps(self):
        configs = [
            {
                "id": "sc-1",
                "name": "Prod Slack",
                "channelName": "#prod-alerts",
                "teamName": "ProdTeam",
                "created": "2025-03-01",
            }
        ]
        result = format_refresh_configurations_response(configs, total_elements=1)
        text = result[0].text
        assert "Prod Slack" in text
        assert "#prod-alerts" in text
        assert "ProdTeam" in text
        assert "set_default_configuration" in text

    def test_team_name_fallback_to_nested_label(self):
        configs = [
            {
                "id": "sc-1",
                "name": "Config",
                "channelName": "#ch",
                "team": {"label": "Nested Team"},
                "created": "2025-01-01",
            }
        ]
        result = format_refresh_configurations_response(configs, total_elements=1)
        assert "Nested Team" in result[0].text


class TestFormatCheckNewConfigurationsResponse:
    """Test check-new-configurations response formatting."""

    def test_zero_configurations_shows_retry_guidance(self):
        result = format_check_new_configurations_response([], total_elements=0)
        text = result[0].text
        assert "No Configurations Found" in text
        assert "initiate_oauth" in text

    def test_single_configuration_shows_most_recent(self):
        configs = [
            {
                "id": "sc-new",
                "name": "New Config",
                "channelName": "#new",
                "teamName": "NewTeam",
                "created": "2025-03-10",
            }
        ]
        result = format_check_new_configurations_response(configs, total_elements=1)
        text = result[0].text
        assert "Most Recent Configuration" in text
        assert "New Config" in text
        assert "set_default_configuration" in text

    def test_multiple_configurations_shows_total_count(self):
        configs = [
            {"id": "sc-1", "name": "C1", "channelName": "#c1", "teamName": "T1", "created": "2025-03-10"},
            {"id": "sc-2", "name": "C2", "channelName": "#c2", "teamName": "T2", "created": "2025-03-09"},
        ]
        result = format_check_new_configurations_response(configs, total_elements=2)
        text = result[0].text
        assert "2" in text
        assert "list_configurations" in text


class TestGetOAuthTexts:
    """Test static text generators for OAuth workflow."""

    def test_examples_text_covers_oauth_flow(self):
        text = get_oauth_examples_text()
        assert "initiate_oauth" in text
        assert "refresh_configurations" in text
        assert "check_new_configurations" in text

    def test_capabilities_text_covers_actions(self):
        text = get_oauth_capabilities_text()
        assert "initiate_oauth" in text
        assert "refresh_configurations" in text
        assert "get_oauth_instructions" in text
