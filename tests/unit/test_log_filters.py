"""Unit tests for LogFilter client-side filtering logic.

Tests the LogFilter class from log_filters.py which provides client-side
filtering of log entries by operation, status, and search term.
"""

import pytest
from unittest.mock import patch

from src.revenium_mcp_server.tools_decomposed.log_filters import LogFilter
from src.revenium_mcp_server.common.error_handling import ToolError


@pytest.fixture
def log_filter():
    """Create a LogFilter instance."""
    return LogFilter()


@pytest.fixture
def sample_log_entries():
    """Sample log entries for filtering tests."""
    return [
        {
            "id": "1",
            "operation": "AI_METRIC_PROCESSING",
            "status": "SUCCESS",
            "details": "Processed metric for product ABC",
            "system": "metering",
            "created": "2024-01-15T10:00:00Z",
        },
        {
            "id": "2",
            "operation": "AI_METRIC_PROCESSING",
            "status": "INFO",
            "details": "New organization created",
            "system": "metering",
            "created": "2024-01-15T09:00:00Z",
        },
        {
            "id": "3",
            "operation": "EMAIL_DISPATCH_AI_ALERT_NOTIFICATION",
            "status": "FAILURE",
            "details": "SMTP timeout connecting to mail server",
            "system": "notifications",
            "created": "2024-01-15T08:00:00Z",
        },
        {
            "id": "4",
            "operation": "EMAIL_DISPATCH_INVOICE_NOTIFICATION",
            "status": "SUCCESS",
            "details": "Invoice sent to customer@example.com",
            "system": "notifications",
            "created": "2024-01-15T07:00:00Z",
        },
        {
            "id": "5",
            "operation": "AUTH_CHECK",
            "status": "WARNING",
            "details": "Rate limit approaching threshold",
            "system": "auth",
            "created": "2024-01-15T06:00:00Z",
        },
    ]


class TestLogFilterByOperation:
    """Test filtering log entries by operation type."""

    def test_exact_match_filters_correctly(self, log_filter, sample_log_entries):
        """Exact operation name returns only matching entries."""
        filtered, applied = log_filter.apply_filters(
            sample_log_entries, operation_filter="AI_METRIC_PROCESSING"
        )
        assert len(filtered) == 2
        assert all(e["operation"] == "AI_METRIC_PROCESSING" for e in filtered)
        assert applied["operation_filter"] == "AI_METRIC_PROCESSING"

    def test_partial_match_filters_correctly(self, log_filter, sample_log_entries):
        """Partial operation name matches entries containing the substring."""
        filtered, applied = log_filter.apply_filters(
            sample_log_entries, operation_filter="EMAIL_DISPATCH"
        )
        assert len(filtered) == 2
        assert all("EMAIL_DISPATCH" in e["operation"] for e in filtered)

    def test_case_insensitive_operation_filter(self, log_filter, sample_log_entries):
        """Operation filter is case-insensitive."""
        filtered, _ = log_filter.apply_filters(
            sample_log_entries, operation_filter="auth_check"
        )
        assert len(filtered) == 1
        assert filtered[0]["operation"] == "AUTH_CHECK"

    def test_no_matching_operation_returns_empty(self, log_filter, sample_log_entries):
        """Operation filter with no matches returns empty list."""
        filtered, _ = log_filter.apply_filters(
            sample_log_entries, operation_filter="NONEXISTENT_OP"
        )
        assert filtered == []


class TestLogFilterByStatus:
    """Test filtering log entries by status."""

    def test_success_status_filter(self, log_filter, sample_log_entries):
        """SUCCESS filter returns only successful entries."""
        filtered, applied = log_filter.apply_filters(
            sample_log_entries, status_filter="SUCCESS"
        )
        assert len(filtered) == 2
        assert all(e["status"] == "SUCCESS" for e in filtered)
        assert applied["status_filter"] == "SUCCESS"

    def test_error_maps_to_failure(self, log_filter, sample_log_entries):
        """ERROR status maps to both ERROR and FAILURE entries."""
        filtered, _ = log_filter.apply_filters(
            sample_log_entries, status_filter="ERROR"
        )
        assert len(filtered) == 1
        assert filtered[0]["status"] == "FAILURE"

    def test_fail_maps_to_failure(self, log_filter, sample_log_entries):
        """FAIL status maps to FAILURE and ERROR entries."""
        filtered, _ = log_filter.apply_filters(
            sample_log_entries, status_filter="FAIL"
        )
        assert len(filtered) == 1
        assert filtered[0]["status"] == "FAILURE"

    def test_warning_filter(self, log_filter, sample_log_entries):
        """WARNING filter returns warning entries."""
        filtered, _ = log_filter.apply_filters(
            sample_log_entries, status_filter="WARNING"
        )
        assert len(filtered) == 1
        assert filtered[0]["status"] == "WARNING"

    def test_warn_maps_to_warning(self, log_filter, sample_log_entries):
        """WARN maps to WARNING status."""
        filtered, _ = log_filter.apply_filters(
            sample_log_entries, status_filter="WARN"
        )
        assert len(filtered) == 1
        assert filtered[0]["status"] == "WARNING"

    def test_unknown_status_used_as_literal(self, log_filter, sample_log_entries):
        """Unknown status filter falls back to literal match."""
        filtered, _ = log_filter.apply_filters(
            sample_log_entries, status_filter="CUSTOM_STATUS"
        )
        assert filtered == []


class TestLogFilterBySearchTerm:
    """Test filtering log entries by search term in multiple fields."""

    def test_search_in_details_field(self, log_filter, sample_log_entries):
        """Search term found in details field returns matching entries."""
        filtered, applied = log_filter.apply_filters(
            sample_log_entries, search_term="timeout"
        )
        assert len(filtered) == 1
        assert "timeout" in filtered[0]["details"].lower()
        assert applied["search_term"] == "timeout"

    def test_search_in_operation_field(self, log_filter, sample_log_entries):
        """Search term found in operation field returns matching entries."""
        filtered, _ = log_filter.apply_filters(
            sample_log_entries, search_term="INVOICE"
        )
        assert len(filtered) == 1
        assert "INVOICE" in filtered[0]["operation"]

    def test_search_in_system_field(self, log_filter, sample_log_entries):
        """Search term found in system field returns matching entries."""
        filtered, _ = log_filter.apply_filters(
            sample_log_entries, search_term="auth"
        )
        assert len(filtered) == 1
        assert filtered[0]["system"] == "auth"

    def test_search_in_id_field(self, log_filter, sample_log_entries):
        """Search term found in id field returns matching entries."""
        filtered, _ = log_filter.apply_filters(
            sample_log_entries, search_term="3"
        )
        assert any(e["id"] == "3" for e in filtered)

    def test_case_insensitive_search(self, log_filter, sample_log_entries):
        """Search is case-insensitive."""
        filtered, _ = log_filter.apply_filters(
            sample_log_entries, search_term="SMTP"
        )
        assert len(filtered) == 1
        assert "SMTP" in filtered[0]["details"]


class TestCombinedFilters:
    """Test applying multiple filters together."""

    def test_operation_and_status_combined(self, log_filter, sample_log_entries):
        """Combined operation + status filters narrow results correctly."""
        filtered, applied = log_filter.apply_filters(
            sample_log_entries,
            operation_filter="AI_METRIC_PROCESSING",
            status_filter="SUCCESS",
        )
        assert len(filtered) == 1
        assert filtered[0]["status"] == "SUCCESS"
        assert filtered[0]["operation"] == "AI_METRIC_PROCESSING"

    def test_all_three_filters(self, log_filter, sample_log_entries):
        """All three filters applied together produce correct intersection."""
        filtered, applied = log_filter.apply_filters(
            sample_log_entries,
            operation_filter="EMAIL_DISPATCH",
            status_filter="FAIL",
            search_term="timeout",
        )
        assert len(filtered) == 1
        assert filtered[0]["id"] == "3"
        assert "operation_filter" in applied
        assert "status_filter" in applied
        assert "search_term" in applied

    def test_no_filters_returns_all(self, log_filter, sample_log_entries):
        """No filters returns all entries unchanged."""
        filtered, applied = log_filter.apply_filters(sample_log_entries)
        assert len(filtered) == len(sample_log_entries)
        assert applied == {}

    def test_log_type_filter_tracked_in_applied(self, log_filter, sample_log_entries):
        """log_type_filter is tracked in applied_filters but does not filter entries."""
        filtered, applied = log_filter.apply_filters(
            sample_log_entries, log_type_filter="internal"
        )
        assert len(filtered) == len(sample_log_entries)
        assert applied["log_type_filter"] == "internal"


class TestGetAvailableOperationsAndStatuses:
    """Test extracting unique operations and statuses from entries."""

    def test_get_available_operations(self, log_filter, sample_log_entries):
        """Returns sorted unique operations from entries."""
        ops = log_filter.get_available_operations(sample_log_entries)
        assert ops == sorted([
            "AI_METRIC_PROCESSING",
            "AUTH_CHECK",
            "EMAIL_DISPATCH_AI_ALERT_NOTIFICATION",
            "EMAIL_DISPATCH_INVOICE_NOTIFICATION",
        ])

    def test_get_available_statuses(self, log_filter, sample_log_entries):
        """Returns sorted unique statuses from entries."""
        statuses = log_filter.get_available_statuses(sample_log_entries)
        assert statuses == sorted(["FAILURE", "INFO", "SUCCESS", "WARNING"])

    def test_empty_entries_returns_empty(self, log_filter):
        """Empty entries returns empty list of operations/statuses."""
        assert log_filter.get_available_operations([]) == []
        assert log_filter.get_available_statuses([]) == []

    def test_entries_missing_fields_skipped(self, log_filter):
        """Entries missing operation/status fields are skipped."""
        entries = [{"details": "no op or status"}, {"operation": "TEST"}]
        ops = log_filter.get_available_operations(entries)
        assert ops == ["TEST"]


class TestValidateFilterParameters:
    """Test filter parameter validation and warnings."""

    def test_invalid_status_produces_warning(self, log_filter):
        """Invalid status filter generates a warning."""
        warnings = log_filter.validate_filter_parameters(status_filter="BOGUS")
        assert len(warnings) == 1
        assert "BOGUS" in warnings[0]

    def test_valid_status_no_warning(self, log_filter):
        """Valid status filter produces no warnings."""
        warnings = log_filter.validate_filter_parameters(status_filter="SUCCESS")
        assert warnings == []

    def test_short_search_term_warning(self, log_filter):
        """Search term shorter than 2 chars generates a warning."""
        warnings = log_filter.validate_filter_parameters(search_term="x")
        assert len(warnings) == 1
        assert "short" in warnings[0].lower()

    def test_short_operation_filter_warning(self, log_filter):
        """Operation filter shorter than 3 chars generates a warning."""
        warnings = log_filter.validate_filter_parameters(operation_filter="AI")
        assert len(warnings) == 1
        assert "short" in warnings[0].lower()

    def test_no_params_no_warnings(self, log_filter):
        """No parameters produces no warnings."""
        assert log_filter.validate_filter_parameters() == []


class TestCreateFilterSummary:
    """Test filter summary generation."""

    def test_no_filters_returns_empty(self, log_filter):
        """Empty applied_filters returns empty string."""
        assert log_filter.create_filter_summary(100, 100, {}) == ""

    def test_summary_includes_counts(self, log_filter):
        """Summary includes original, filtered, and reduction counts."""
        summary = log_filter.create_filter_summary(
            100, 50, {"status_filter": "SUCCESS"}
        )
        assert "100" in summary
        assert "50" in summary

    def test_zero_results_shows_warning(self, log_filter):
        """Zero filtered results includes warning message."""
        summary = log_filter.create_filter_summary(
            100, 0, {"status_filter": "SUCCESS"}
        )
        assert "No entries match" in summary

    def test_highly_selective_filter_noted(self, log_filter):
        """Filter returning <10% of data is noted as highly selective."""
        summary = log_filter.create_filter_summary(
            1000, 5, {"search_term": "rare"}
        )
        assert "Highly selective" in summary


class TestSuggestCommonFilters:
    """Test filter suggestion generation from entry data."""

    def test_suggests_common_operations(self, log_filter, sample_log_entries):
        """Suggests the most common operations from entries."""
        suggestions = log_filter.suggest_common_filters(sample_log_entries)
        assert "common_operations" in suggestions
        assert len(suggestions["common_operations"]) > 0
        # AI_METRIC_PROCESSING appears twice, should be first
        assert suggestions["common_operations"][0] == "AI_METRIC_PROCESSING"

    def test_identifies_error_operations(self, log_filter, sample_log_entries):
        """Identifies operations that have FAILURE/ERROR status."""
        suggestions = log_filter.suggest_common_filters(sample_log_entries)
        assert "EMAIL_DISPATCH_AI_ALERT_NOTIFICATION" in suggestions["error_operations"]

    def test_lists_available_statuses(self, log_filter, sample_log_entries):
        """Lists all statuses found in entries."""
        suggestions = log_filter.suggest_common_filters(sample_log_entries)
        assert set(suggestions["common_statuses"]) == {"SUCCESS", "INFO", "FAILURE", "WARNING"}

    def test_empty_entries_returns_empty_suggestions(self, log_filter):
        """Empty entries returns empty suggestion lists."""
        suggestions = log_filter.suggest_common_filters([])
        assert suggestions["common_operations"] == []
        assert suggestions["error_operations"] == []
        assert suggestions["common_statuses"] == []

    def test_extracts_search_terms_from_details(self, log_filter):
        """Extracts alphabetic words >4 chars from details as search term suggestions."""
        entries = [
            {"details": "Connection timeout while processing batch request"},
        ]
        suggestions = log_filter.suggest_common_filters(entries)
        # Should find words like "Connection", "timeout", "while", "processing", "batch", "request"
        # Only words >4 chars and purely alphabetic qualify
        assert len(suggestions["sample_search_terms"]) > 0
        assert all(len(t) > 4 for t in suggestions["sample_search_terms"])
