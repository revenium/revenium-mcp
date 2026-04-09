"""Unit tests for LogResponseFormatter formatting logic.

Tests the LogResponseFormatter class which formats API log responses
into structured markdown with operation summaries, status breakdowns,
diagnostic insights, and temporal analysis.
"""

import pytest

from src.revenium_mcp_server.tools_decomposed.log_formatters import LogResponseFormatter
from mcp.types import TextContent


@pytest.fixture
def formatter():
    """Create a LogResponseFormatter instance."""
    return LogResponseFormatter()


@pytest.fixture
def sample_api_response():
    """Sample API response matching real Revenium structure."""
    return {
        "_embedded": {
            "systemLogResourceList": [
                {
                    "operation": "AI_METRIC_PROCESSING",
                    "status": "SUCCESS",
                    "details": "Processed metric",
                    "created": "2024-01-15T10:00:00Z",
                },
                {
                    "operation": "AI_METRIC_PROCESSING",
                    "status": "INFO",
                    "details": "New org created",
                    "created": "2024-01-15T09:00:00Z",
                },
                {
                    "operation": "EMAIL_DISPATCH",
                    "status": "FAILURE",
                    "details": "SMTP timeout",
                    "created": "2024-01-15T08:00:00Z",
                },
            ]
        },
        "page": {
            "totalElements": 150,
            "totalPages": 3,
            "number": 0,
        },
    }


class TestFormatLogResponse:
    """Test the main format_log_response method."""

    def test_returns_text_content(self, formatter, sample_api_response):
        """Returns a list with a single TextContent element."""
        result = formatter.format_log_response(sample_api_response, "internal", 0, 200)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)

    def test_includes_log_type_in_header(self, formatter, sample_api_response):
        """Response header includes the log type."""
        result = formatter.format_log_response(sample_api_response, "internal", 0, 200)
        assert "Internal" in result[0].text

    def test_includes_pagination_info(self, formatter, sample_api_response):
        """Response includes pagination details from API response."""
        result = formatter.format_log_response(sample_api_response, "internal", 0, 200)
        text = result[0].text
        assert "150" in text  # total elements
        assert "1 of 3" in text  # page number (0-indexed + 1)

    def test_includes_operation_summary(self, formatter, sample_api_response):
        """Response includes operation frequency counts."""
        result = formatter.format_log_response(sample_api_response, "internal", 0, 200)
        text = result[0].text
        assert "AI_METRIC_PROCESSING" in text
        assert "EMAIL_DISPATCH" in text

    def test_includes_status_summary(self, formatter, sample_api_response):
        """Response includes status distribution."""
        result = formatter.format_log_response(sample_api_response, "internal", 0, 200)
        text = result[0].text
        assert "SUCCESS" in text
        assert "FAILURE" in text

    def test_includes_recent_entries(self, formatter, sample_api_response):
        """Response includes recent log entries section."""
        result = formatter.format_log_response(sample_api_response, "internal", 0, 200)
        text = result[0].text
        assert "Entry 1" in text
        assert "Processed metric" in text

    def test_includes_applied_filters(self, formatter, sample_api_response):
        """Applied filters are displayed when provided."""
        result = formatter.format_log_response(
            sample_api_response, "internal", 0, 200,
            applied_filters={"status_filter": "SUCCESS"}
        )
        text = result[0].text
        assert "Applied Filters" in text
        assert "status_filter" in text

    def test_empty_log_entries_no_recent_section(self, formatter):
        """Empty log entries skips the recent entries section."""
        api_response = {
            "_embedded": {"systemLogResourceList": []},
            "page": {"totalElements": 0, "totalPages": 0, "number": 0},
        }
        result = formatter.format_log_response(api_response, "internal", 0, 200)
        assert "Entry 1" not in result[0].text


class TestDiagnosticInsights:
    """Test diagnostic insight generation based on log patterns."""

    def test_failure_insight_generated(self, formatter):
        """Failures in log entries generate an investigation insight."""
        entries = [{"operation": "TEST", "status": "FAILURE"}]
        op_counts = formatter._count_operations(entries)
        status_counts = formatter._count_statuses(entries)
        insights = formatter._generate_diagnostic_insights(
            entries, op_counts, status_counts
        )
        assert any("failed" in i.lower() for i in insights)

    def test_ai_metric_info_insight(self, formatter):
        """AI_METRIC_PROCESSING with INFO status generates specific insight."""
        entries = [
            {"operation": "AI_METRIC_PROCESSING", "status": "INFO"},
            {"operation": "AI_METRIC_PROCESSING", "status": "SUCCESS"},
        ]
        op_counts = formatter._count_operations(entries)
        status_counts = formatter._count_statuses(entries)
        insights = formatter._generate_diagnostic_insights(
            entries, op_counts, status_counts
        )
        assert any("AI_METRIC_PROCESSING" in i for i in insights)

    def test_large_dataset_insight_multi_page(self, formatter):
        """Large datasets with multiple pages generate pagination insight."""
        insights = formatter._generate_diagnostic_insights(
            [], {}, {}, total_elements=500, total_pages=3
        )
        assert any("500" in i and "3 pages" in i for i in insights)

    def test_large_dataset_insight_single_page(self, formatter):
        """Large single-page dataset generates simpler insight."""
        insights = formatter._generate_diagnostic_insights(
            [], {}, {}, total_elements=200, total_pages=1
        )
        assert any("200" in i for i in insights)

    def test_email_dispatch_failure_insight(self, formatter):
        """Email dispatch failures generate specific insight."""
        entries = [
            {"operation": "EMAIL_DISPATCH_ALERT", "status": "FAILURE"},
            {"operation": "EMAIL_DISPATCH_INVOICE", "status": "FAILURE"},
        ]
        op_counts = formatter._count_operations(entries)
        status_counts = formatter._count_statuses(entries)
        insights = formatter._generate_diagnostic_insights(
            entries, op_counts, status_counts
        )
        assert any("email dispatch" in i.lower() for i in insights)

    def test_no_issues_returns_empty_insights(self, formatter):
        """Healthy log data with small dataset returns no insights."""
        entries = [{"operation": "TEST", "status": "SUCCESS"}]
        insights = formatter._generate_diagnostic_insights(
            entries,
            {"TEST": 1},
            {"SUCCESS": 1},
            total_elements=10,
            total_pages=1,
        )
        assert insights == []


class TestFormatMultiPageResponse:
    """Test multi-page response formatting."""

    def test_multi_page_includes_pages_retrieved(self, formatter):
        """Multi-page response includes pages_retrieved count."""
        entries = [
            {"operation": "TEST", "status": "SUCCESS", "created": "2024-01-15T10:00:00Z"},
        ]
        result = formatter.format_multi_page_response(entries, "internal", 3)
        text = result[0].text
        assert "3" in text
        assert "Multi-Page" in text

    def test_multi_page_includes_temporal_analysis(self, formatter):
        """Multi-page response includes temporal analysis section."""
        entries = [
            {"operation": "TEST", "status": "SUCCESS", "created": "2024-01-15T10:00:00Z"},
            {"operation": "TEST", "status": "SUCCESS", "created": "2024-01-14T10:00:00Z"},
        ]
        result = formatter.format_multi_page_response(entries, "internal", 2)
        assert "Temporal Analysis" in result[0].text

    def test_multi_page_with_filters(self, formatter):
        """Multi-page response includes applied filters."""
        entries = [{"operation": "TEST", "status": "SUCCESS", "created": "2024-01-15T10:00:00Z"}]
        result = formatter.format_multi_page_response(
            entries, "internal", 1, applied_filters={"status_filter": "SUCCESS"}
        )
        assert "Applied Filters" in result[0].text


class TestFormatComprehensiveSearchResponse:
    """Test comprehensive search response formatting."""

    def test_search_with_matches(self, formatter):
        """Search with matches shows operation and status summaries."""
        matches = [
            {
                "operation": "AI_METRIC_PROCESSING",
                "status": "SUCCESS",
                "details": "Match found",
                "created": "2024-01-15T10:00:00Z",
            },
        ]
        result = formatter.format_comprehensive_search_response(
            matches, "internal", 5
        )
        text = result[0].text
        assert "Comprehensive Search" in text
        assert "1" in text  # total matches
        assert "AI_METRIC_PROCESSING" in text

    def test_search_no_matches_shows_recommendations(self, formatter):
        """Search with no matches shows recommendations section."""
        result = formatter.format_comprehensive_search_response(
            [], "internal", 5
        )
        text = result[0].text
        assert "No Matches Found" in text
        assert "Recommendations" in text

    def test_search_with_filters(self, formatter):
        """Search response includes applied filters."""
        result = formatter.format_comprehensive_search_response(
            [], "internal", 3, applied_filters={"search_term": "error"}
        )
        assert "search_term" in result[0].text


class TestTemporalAnalysis:
    """Test temporal analysis for multi-page data."""

    def test_empty_entries_returns_empty(self, formatter):
        """Empty entries returns empty string."""
        assert formatter._build_temporal_analysis([]) == ""

    def test_entries_with_timestamps(self, formatter):
        """Entries with timestamps show time range."""
        entries = [
            {"created": "2024-01-15T10:00:00Z"},
            {"created": "2024-01-14T10:00:00Z"},
        ]
        result = formatter._build_temporal_analysis(entries)
        assert "Time Range" in result
        assert "2024-01-14" in result
        assert "2024-01-15" in result

    def test_entries_without_timestamps(self, formatter):
        """Entries without created field show no timestamp message."""
        entries = [{"operation": "TEST"}]
        result = formatter._build_temporal_analysis(entries)
        assert "No timestamp data" in result
