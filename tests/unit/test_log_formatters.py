"""Unit tests for LogResponseFormatter formatting logic.

Tests the LogResponseFormatter class which formats API log responses
into structured markdown with operation summaries, status breakdowns,
diagnostic insights, and temporal analysis.
"""

import pytest

from src.revenium_mcp_server.analytics.paging import PageInfo
from src.revenium_mcp_server.tools_decomposed.log_formatters import (
    LogResponseFormatter,
    PageCoverage,
)
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

    @staticmethod
    def _platform_page(entries):
        return {
            "_embedded": {"systemLogResourceList": entries},
            "page": {"size": 50, "totalElements": 78828, "totalPages": 1577, "number": 0},
        }

    def test_filtered_page_labels_the_platform_total_as_unfiltered(self, formatter):
        """A status filter prints the page's matches, never the unfiltered total as its own."""
        failure = {
            "operation": "EMAIL_DISPATCH",
            "status": "FAILURE",
            "details": "SMTP timeout",
            "created": "2026-10-15T08:00:00Z",
        }
        result = formatter.format_log_response(
            self._platform_page([failure]),
            "filtered_internal",
            0,
            50,
            applied_filters={"status_filter": "FAILURE", "log_type_filter": "internal"},
        )
        text = result[0].text
        assert "- **Total Entries**: 78,828" not in text
        assert "Large dataset available" not in text
        assert "- **Matches On This Page**: 1" in text
        lines_with_total = [line for line in text.splitlines() if "78,828" in line]
        assert lines_with_total
        assert all("unfiltered" in line for line in lines_with_total)

    def test_unfiltered_search_keeps_the_platform_total(self, formatter):
        """Only the log type applied: the platform total is the search's own total."""
        entry = {
            "operation": "AI_METRIC_PROCESSING",
            "status": "SUCCESS",
            "details": "Processed metric",
            "created": "2026-10-15T08:00:00Z",
        }
        result = formatter.format_log_response(
            self._platform_page([entry]),
            "filtered_internal",
            0,
            50,
            applied_filters={"log_type_filter": "internal"},
        )
        text = result[0].text
        assert "- **Total Entries**: 78,828" in text
        assert (
            "Read 1 of 78,828 entries (1 of 1577 pages); the other 78,827 were not read" in text
        )
        assert "available" not in text.lower()


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

    def test_unread_entries_insight_states_read_out_of_total(self, formatter):
        """BACK-4735: the insight says how many entries were read out of how many exist."""
        coverage = PageCoverage(
            pages_read=3, entries_read=300, platform=PageInfo(total_pages=1021, total_elements=102057)
        )
        insights = formatter._generate_diagnostic_insights([], {}, {}, coverage)
        assert insights == [
            "Read 300 of 102,057 entries (3 of 1021 pages); the other 101,757 were not read"
        ]

    def test_unread_entries_insight_without_a_page_count(self, formatter):
        coverage = PageCoverage(
            pages_read=1, entries_read=100, platform=PageInfo(total_elements=250)
        )
        insights = formatter._generate_diagnostic_insights([], {}, {}, coverage)
        assert insights == ["Read 100 of 250 entries; the other 150 were not read"]

    def test_no_unread_entries_insight_when_everything_was_read_or_the_total_is_unknown(
        self, formatter
    ):
        every_entry = PageCoverage(
            pages_read=1, entries_read=10, platform=PageInfo(total_pages=1, total_elements=10)
        )
        no_total = PageCoverage(pages_read=1, entries_read=10, platform=PageInfo())
        assert formatter._generate_diagnostic_insights([], {}, {}, every_entry) == []
        assert formatter._generate_diagnostic_insights([], {}, {}, no_total) == []

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
            PageCoverage(
                pages_read=1, entries_read=10, platform=PageInfo(total_pages=1, total_elements=10)
            ),
        )
        assert insights == []


class TestFormatMultiPageResponse:
    """Test multi-page response formatting."""

    @staticmethod
    def _read(entries, pages_read, total_pages=None, total_elements=None):
        return PageCoverage(
            pages_read=pages_read,
            entries_read=len(entries),
            platform=PageInfo(total_pages=total_pages, total_elements=total_elements),
        )

    def test_multi_page_includes_pages_retrieved(self, formatter):
        """Multi-page response includes pages_retrieved count."""
        entries = [
            {"operation": "TEST", "status": "SUCCESS", "created": "2024-01-15T10:00:00Z"},
        ]
        result = formatter.format_multi_page_response(entries, "internal", self._read(entries, 3))
        text = result[0].text
        assert "- **Pages Retrieved**: 3 of an unknown number" in text
        assert "Multi-Page" in text

    def test_multi_page_says_what_was_read_out_of_what_exists(self, formatter):
        """BACK-4735: entries and pages read out of the platform total, never 'available'."""
        entries = [
            {"operation": "TEST", "status": "SUCCESS", "created": "2024-01-15T10:00:00Z"}
        ] * 300
        result = formatter.format_multi_page_response(
            entries, "internal", self._read(entries, 3, total_pages=1021, total_elements=102057)
        )
        text = result[0].text
        assert "- **Total Entries Analyzed**: 300 of 102,057" in text
        assert "- **Pages Retrieved**: 3 of 1021" in text
        assert "Read 300 of 102,057 entries (3 of 1021 pages); the other 101,757 were not read" in text
        assert "available" not in text.lower()

    def test_multi_page_includes_temporal_analysis(self, formatter):
        """Multi-page response includes temporal analysis section."""
        entries = [
            {"operation": "TEST", "status": "SUCCESS", "created": "2024-01-15T10:00:00Z"},
            {"operation": "TEST", "status": "SUCCESS", "created": "2024-01-14T10:00:00Z"},
        ]
        result = formatter.format_multi_page_response(entries, "internal", self._read(entries, 2))
        assert "Temporal Analysis" in result[0].text

    def test_multi_page_with_filters(self, formatter):
        """Multi-page response includes applied filters."""
        entries = [{"operation": "TEST", "status": "SUCCESS", "created": "2024-01-15T10:00:00Z"}]
        result = formatter.format_multi_page_response(
            entries, "internal", self._read(entries, 1), applied_filters={"status_filter": "SUCCESS"}
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
            matches, "internal", PageCoverage(5, 500, PageInfo(total_pages=5, total_elements=500))
        )
        text = result[0].text
        assert "Comprehensive Search" in text
        assert "1" in text  # total matches
        assert "AI_METRIC_PROCESSING" in text

    def test_search_no_matches_shows_recommendations(self, formatter):
        """Search with no matches shows recommendations section."""
        result = formatter.format_comprehensive_search_response(
            [], "internal", PageCoverage(5, 500, PageInfo(total_pages=5, total_elements=500))
        )
        text = result[0].text
        assert "No Matches Found" in text
        assert "Recommendations" in text

    def test_search_with_filters(self, formatter):
        """Search response includes applied filters."""
        result = formatter.format_comprehensive_search_response(
            [], "internal", PageCoverage(3, 300, PageInfo(total_pages=3, total_elements=300)), applied_filters={"search_term": "error"}
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
