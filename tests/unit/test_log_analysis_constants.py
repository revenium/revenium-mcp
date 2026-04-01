"""Unit tests for log_analysis_constants module.

Tests that the constants module provides the expected configuration values
used by the log analysis tool. These constants are consumed by other modules
to control API endpoints, defaults, and validation.
"""

from src.revenium_mcp_server.tools_decomposed.log_analysis_constants import (
    CAPABILITIES_TEXT,
    EXAMPLES_TEXT,
    UNSUPPORTED_ACTION_TEMPLATE,
    ERROR_MESSAGES,
    SUGGESTIONS,
    DEFAULT_VALUES,
    LOG_ENDPOINTS,
    VALID_VALUES,
)


class TestLogAnalysisConstants:
    """Test that log analysis constants provide expected values for consumers."""

    def test_log_endpoints_contain_required_types(self):
        """Log endpoints include both internal and integration paths."""
        assert "internal" in LOG_ENDPOINTS
        assert "integration" in LOG_ENDPOINTS
        assert LOG_ENDPOINTS["internal"].startswith("/")
        assert LOG_ENDPOINTS["integration"].startswith("/")

    def test_default_values_provide_sensible_page_size(self):
        """Default page size is a reasonable number for API pagination."""
        assert DEFAULT_VALUES["size"] == 200
        assert DEFAULT_VALUES["page"] == 0

    def test_valid_log_types_include_both_and_individual(self):
        """Valid log types allow querying individual types or both."""
        assert "internal" in VALID_VALUES["log_types"]
        assert "integration" in VALID_VALUES["log_types"]
        assert "both" in VALID_VALUES["log_types"]

    def test_valid_status_types_include_all_expected(self):
        """Status types include the standard log statuses."""
        expected = {"SUCCESS", "FAILURE", "INFO", "ERROR", "WARNING"}
        assert expected == set(VALID_VALUES["status_types"])

    def test_unsupported_action_template_has_placeholder(self):
        """Unsupported action template has {action} placeholder for formatting."""
        assert "{action}" in UNSUPPORTED_ACTION_TEMPLATE

    def test_error_messages_have_format_placeholders(self):
        """Error message templates contain format placeholders."""
        assert "{log_type}" in ERROR_MESSAGES["api_error"]
        assert "{error}" in ERROR_MESSAGES["api_error"]

    def test_capabilities_text_documents_available_actions(self):
        """Capabilities text lists the available actions for agents."""
        assert "get_internal_logs" in CAPABILITIES_TEXT
        assert "search_logs" in CAPABILITIES_TEXT
        assert "get_capabilities" in CAPABILITIES_TEXT

    def test_examples_text_includes_working_json(self):
        """Examples text includes JSON code blocks for agent consumption."""
        assert "```json" in EXAMPLES_TEXT
        assert '"action"' in EXAMPLES_TEXT
