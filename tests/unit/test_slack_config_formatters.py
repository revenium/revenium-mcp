"""Unit tests for Slack Configuration Formatters.

Tests the pure formatting functions that transform API response data
into user-facing TextContent output.
"""

import pytest
from unittest.mock import patch

from mcp.types import TextContent

from src.revenium_mcp_server.tools_decomposed.slack_config_formatters import (
    format_configurations_list,
    format_single_config_summary,
    format_pagination_info,
    format_usage_instructions,
    format_configuration_details,
    format_default_set_success,
    format_no_default_message,
    format_default_configuration,
    format_oauth_url_response,
    get_examples_text,
    get_capabilities_text,
)


class TestFormatConfigurationsList:
    """Test format_configurations_list: transforms API paginated response into user-facing list."""

    def test_empty_configurations_suggests_oauth(self):
        """When no configs exist, user should be guided to OAuth setup."""
        response = {"content": [], "totalElements": 0, "totalPages": 0}
        result = format_configurations_list(response, page=0)

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "No Slack Configurations Found" in result[0].text
        assert "initiate_oauth" in result[0].text

    def test_single_configuration_shows_details(self):
        """A single config should show its name, workspace, and channel."""
        response = {
            "content": [
                {
                    "id": "slack-001",
                    "name": "Alerts Channel",
                    "channelName": "#alerts",
                    "teamName": "Acme Corp",
                    "created": "2025-01-15",
                }
            ],
            "totalElements": 1,
            "totalPages": 1,
        }
        result = format_configurations_list(response, page=0)

        text = result[0].text
        assert "Alerts Channel" in text
        assert "slack-001" in text
        assert "#alerts" in text
        assert "Acme Corp" in text

    def test_pagination_header_shown_for_multiple_pages(self):
        """When totalPages > 1, pagination info should appear."""
        response = {
            "content": [{"id": "s1", "name": "C1", "channelName": "#c1", "created": "2025-01-01"}],
            "totalElements": 25,
            "totalPages": 3,
        }
        result = format_configurations_list(response, page=1)

        text = result[0].text
        assert "Page 2 of 3" in text

    def test_no_pagination_for_single_page(self):
        """Single page results should not have navigation links."""
        response = {
            "content": [{"id": "s1", "name": "C1", "channelName": "#c1", "created": "2025-01-01"}],
            "totalElements": 1,
            "totalPages": 1,
        }
        result = format_configurations_list(response, page=0)

        text = result[0].text
        assert "Navigation" not in text

    def test_team_name_fallback_to_nested_label(self):
        """When teamName is absent, should fall back to team.label."""
        response = {
            "content": [
                {
                    "id": "s1",
                    "name": "C1",
                    "channelName": "#c1",
                    "team": {"label": "Fallback Team"},
                    "created": "2025-01-01",
                }
            ],
            "totalElements": 1,
            "totalPages": 1,
        }
        result = format_configurations_list(response, page=0)
        assert "Fallback Team" in result[0].text


class TestFormatPaginationInfo:
    """Test pagination navigation link generation."""

    def test_single_page_returns_empty(self):
        assert format_pagination_info(0, 1) == ""

    def test_first_page_has_next_only(self):
        result = format_pagination_info(0, 3)
        assert "Next page" in result
        assert "Previous page" not in result

    def test_last_page_has_previous_only(self):
        result = format_pagination_info(2, 3)
        assert "Previous page" in result
        assert "Next page" not in result

    def test_middle_page_has_both(self):
        result = format_pagination_info(1, 3)
        assert "Previous page" in result
        assert "Next page" in result


class TestFormatConfigurationDetails:
    """Test single configuration detail view formatting."""

    @patch("src.revenium_mcp_server.tools_decomposed.slack_config_formatters.get_config_value")
    def test_shows_default_badge_when_is_default(self, mock_config):
        """When viewing the current default config, it should say so."""
        mock_config.return_value = "cfg-123"
        config = {
            "name": "My Config",
            "teamName": "Team A",
            "channelName": "#general",
            "created": "2025-01-01",
            "updated": "2025-01-02",
        }
        result = format_configuration_details(config, "cfg-123")

        assert "current default" in result[0].text.lower()

    @patch("src.revenium_mcp_server.tools_decomposed.slack_config_formatters.get_config_value")
    def test_no_default_badge_when_not_default(self, mock_config):
        """Non-default configs should not show the default badge."""
        mock_config.return_value = "other-cfg"
        config = {
            "name": "My Config",
            "teamName": "Team A",
            "channelName": "#general",
            "created": "2025-01-01",
            "updated": "2025-01-02",
        }
        result = format_configuration_details(config, "cfg-123")

        assert "current default" not in result[0].text.lower()


class TestFormatDefaultSetSuccess:
    """Test successful default-set confirmation formatting."""

    def test_includes_config_details_and_env_hint(self):
        config = {"name": "Prod Alerts", "teamName": "ProdTeam", "channelName": "#prod-alerts"}
        result = format_default_set_success(config, "cfg-prod")

        text = result[0].text
        assert "Prod Alerts" in text
        assert "ProdTeam" in text
        assert "#prod-alerts" in text
        assert "cfg-prod" in text
        assert ".env" in text


class TestFormatNoDefaultMessage:
    """Test no-default-set message."""

    def test_provides_instructions_to_set_default(self):
        result = format_no_default_message()
        text = result[0].text
        assert "No Default" in text
        assert "list_configurations" in text
        assert "set_default_configuration" in text


class TestFormatOAuthUrlResponse:
    """Test OAuth URL display formatting."""

    def test_includes_url_and_steps(self):
        result = format_oauth_url_response(
            "https://example.com/slack/connect", "https://example.com"
        )
        text = result[0].text
        assert "https://example.com/slack/connect" in text
        assert "list_configurations" in text


class TestGetExamplesAndCapabilities:
    """Test static documentation text generators."""

    def test_examples_text_contains_actions(self):
        text = get_examples_text()
        assert "list_configurations" in text
        assert "get_configuration" in text
        assert "set_default_configuration" in text

    def test_capabilities_text_contains_actions(self):
        text = get_capabilities_text()
        assert "list_configurations" in text
        assert "get_app_oauth_url" in text
