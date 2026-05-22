"""Unit tests for ReveniumLogAnalysis tool.

Tests handle_action routing, _validate_page_size, _analyze_operation_patterns,
_format_analysis_response, and error handling paths.
"""

import pytest
from unittest.mock import AsyncMock
from mcp.types import TextContent

from src.revenium_mcp_server.tools_decomposed.revenium_log_analysis import (
    ReveniumLogAnalysis,
)
from src.revenium_mcp_server.common.error_handling import ToolError


@pytest.fixture
def log_tool():
    """Create a ReveniumLogAnalysis instance."""
    return ReveniumLogAnalysis()


class TestHandleActionRouting:
    """Test that handle_action routes to the correct handler."""

    @pytest.mark.asyncio
    async def test_get_capabilities_returns_text(self, log_tool):
        """get_capabilities returns capabilities text content."""
        result = await log_tool.handle_action("get_capabilities", {})
        assert isinstance(result[0], TextContent)
        assert len(result[0].text) > 100  # Non-trivial content

    @pytest.mark.asyncio
    async def test_get_examples_returns_text(self, log_tool):
        """get_examples returns substantive examples text."""
        result = await log_tool.handle_action("get_examples", {})
        assert isinstance(result[0], TextContent)
        assert len(result[0].text) > 50

    @pytest.mark.asyncio
    async def test_unsupported_action_returns_message(self, log_tool):
        """Unsupported action returns a message (not an exception)."""
        result = await log_tool.handle_action("totally_bogus", {})
        text = result[0].text
        assert "totally_bogus" in text

    @pytest.mark.asyncio
    async def test_toolerror_propagates(self, log_tool):
        """ToolError from within a handler propagates without wrapping."""
        original = ToolError(message="direct error", error_code="TEST")
        log_tool._route_action = AsyncMock(side_effect=original)
        with pytest.raises(ToolError) as exc_info:
            await log_tool.handle_action("get_internal_logs", {})
        assert exc_info.value is original

    @pytest.mark.asyncio
    async def test_generic_exception_wrapped_in_toolerror(self, log_tool):
        """Non-ToolError exceptions are wrapped with _create_action_error."""
        log_tool._route_action = AsyncMock(side_effect=RuntimeError("oops"))
        with pytest.raises(ToolError, match="oops"):
            await log_tool.handle_action("get_internal_logs", {})


class TestRouteAction:
    """Test _route_action directs to the right handler."""

    @pytest.mark.asyncio
    async def test_routes_get_internal_logs(self, log_tool):
        log_tool._handle_get_internal_logs = AsyncMock(
            return_value=[TextContent(type="text", text="internal")]
        )
        result = await log_tool._route_action("get_internal_logs", {"page": 0})
        log_tool._handle_get_internal_logs.assert_called_once_with({"page": 0}, ctx=None)

    @pytest.mark.asyncio
    async def test_routes_get_integration_logs(self, log_tool):
        log_tool._handle_get_integration_logs = AsyncMock(
            return_value=[TextContent(type="text", text="integration")]
        )
        await log_tool._route_action("get_integration_logs", {})
        log_tool._handle_get_integration_logs.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_search_logs(self, log_tool):
        log_tool._handle_search_logs = AsyncMock(
            return_value=[TextContent(type="text", text="search")]
        )
        await log_tool._route_action("search_logs", {"search_term": "error"})
        log_tool._handle_search_logs.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_analyze_operations(self, log_tool):
        log_tool._handle_analyze_operations = AsyncMock(
            return_value=[TextContent(type="text", text="analysis")]
        )
        await log_tool._route_action("analyze_operations", {})
        log_tool._handle_analyze_operations.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_get_recent_logs(self, log_tool):
        log_tool._handle_get_recent_logs = AsyncMock(
            return_value=[TextContent(type="text", text="recent")]
        )
        await log_tool._route_action("get_recent_logs", {"pages": 2})
        log_tool._handle_get_recent_logs.assert_called_once()


class TestValidatePageSize:
    """Test _validate_page_size boundary validation."""

    def test_valid_size_passes(self, log_tool):
        """Size <= 1000 does not raise."""
        log_tool._validate_page_size(1000)  # Should not raise

    def test_size_exceeds_limit_raises(self, log_tool):
        """Size > 1000 raises ToolError."""
        with pytest.raises(ToolError, match="cannot exceed 1000"):
            log_tool._validate_page_size(1001)

    def test_small_size_passes(self, log_tool):
        """Small size value like 1 is valid."""
        log_tool._validate_page_size(1)  # Should not raise


class TestAnalyzeOperationPatterns:
    """Test _analyze_operation_patterns business logic."""

    def test_empty_entries_returns_error(self, log_tool):
        """Empty list returns error dict."""
        result = log_tool._analyze_operation_patterns([])
        assert "error" in result

    def test_counts_operations_correctly(self, log_tool):
        """Operations are counted by frequency."""
        entries = [
            {"operation": "CREATE", "status": "SUCCESS"},
            {"operation": "CREATE", "status": "SUCCESS"},
            {"operation": "DELETE", "status": "SUCCESS"},
        ]
        result = log_tool._analyze_operation_patterns(entries)
        assert result["total_operations"] == 3
        assert result["operation_counts"]["CREATE"] == 2
        assert result["operation_counts"]["DELETE"] == 1

    def test_failure_rate_calculated(self, log_tool):
        """Failure rate is calculated as FAILURE count / total."""
        entries = [
            {"operation": "OP", "status": "SUCCESS"},
            {"operation": "OP", "status": "FAILURE"},
            {"operation": "OP", "status": "FAILURE"},
            {"operation": "OP", "status": "SUCCESS"},
        ]
        result = log_tool._analyze_operation_patterns(entries)
        assert result["failure_rate"] == 0.5

    def test_error_patterns_tracked(self, log_tool):
        """Operations with FAILURE/ERROR status are tracked in error_patterns."""
        entries = [
            {"operation": "SYNC", "status": "FAILURE", "details": "timeout"},
            {"operation": "SYNC", "status": "ERROR", "details": "connection reset"},
            {"operation": "SYNC", "status": "SUCCESS"},
        ]
        result = log_tool._analyze_operation_patterns(entries)
        assert "SYNC" in result["error_patterns"]
        assert len(result["error_patterns"]["SYNC"]) == 2

    def test_problematic_operations_identified(self, log_tool):
        """Operations with > 1 error are flagged as problematic."""
        entries = [
            {"operation": "FLAKY", "status": "FAILURE", "details": "err1"},
            {"operation": "FLAKY", "status": "FAILURE", "details": "err2"},
            {"operation": "STABLE", "status": "SUCCESS"},
        ]
        result = log_tool._analyze_operation_patterns(entries)
        assert "FLAKY" in result["problematic_operations"]
        assert "STABLE" not in result["problematic_operations"]

    def test_top_operations_sorted_by_frequency(self, log_tool):
        """top_operations is sorted descending by count, limited to 5."""
        entries = [{"operation": f"OP_{i % 3}", "status": "SUCCESS"} for i in range(9)]
        result = log_tool._analyze_operation_patterns(entries)
        top_ops = result["top_operations"]
        assert len(top_ops) <= 5
        # All counts should be 3
        assert all(count == 3 for _, count in top_ops)


class TestFormatAnalysisResponse:
    """Test _format_analysis_response output formatting."""

    def test_error_analysis_shows_no_entries(self, log_tool):
        """Analysis with error key shows 'No log entries found'."""
        analysis = {"error": "No entries to analyze"}
        text = log_tool._format_analysis_response(analysis, "internal", 3)
        assert "No log entries found" in text
        assert "internal" in text.lower()

    def test_normal_analysis_includes_summary(self, log_tool):
        """Normal analysis includes summary statistics."""
        analysis = {
            "total_operations": 100,
            "operation_counts": {"CREATE": 60, "DELETE": 40},
            "status_counts": {"SUCCESS": 90, "FAILURE": 10},
            "error_patterns": {"DELETE": ["err1", "err2"]},
            "failure_rate": 0.1,
            "top_operations": [("CREATE", 60), ("DELETE", 40)],
            "problematic_operations": ["DELETE"],
        }
        text = log_tool._format_analysis_response(analysis, "internal", 5)
        assert "100" in text
        assert "10.00%" in text  # failure rate
        assert "CREATE" in text
        assert "DELETE" in text
        assert "Problematic" in text

    def test_high_failure_rate_shows_warning(self, log_tool):
        """Failure rate > 10% triggers a warning insight."""
        analysis = {
            "total_operations": 10,
            "operation_counts": {"OP": 10},
            "status_counts": {"SUCCESS": 8, "FAILURE": 2},
            "error_patterns": {},
            "failure_rate": 0.2,
            "top_operations": [("OP", 10)],
            "problematic_operations": [],
        }
        text = log_tool._format_analysis_response(analysis, "internal", 1)
        assert "High failure rate" in text


class TestCreateActionError:
    """Test _create_action_error produces structured ToolError."""

    def test_creates_toolerror_with_action(self, log_tool):
        """Returned ToolError includes the action name and original error message."""
        err = log_tool._create_action_error("search_logs", ValueError("bad input"))
        assert isinstance(err, ToolError)
        assert "bad input" in err.message
        assert err.field == "action"
        assert err.value == "search_logs"
