"""Unit tests for FastMCP Performance Dashboard error handling.

Tests the FastMCPPerformanceErrors class which creates structured error
responses when dashboard generation fails.
"""


from src.revenium_mcp_server.tools_decomposed.fastmcp_performance_errors import (
    FastMCPPerformanceErrors,
)
from mcp.types import TextContent


class TestFastMCPPerformanceErrors:
    """Test FastMCP performance error handling."""

    def test_handle_dashboard_error_returns_text_content(self):
        """handle_dashboard_error returns list with formatted TextContent."""
        exc = ConnectionError("connection refused")
        result = FastMCPPerformanceErrors.handle_dashboard_error(exc)

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Failed to generate FastMCP performance dashboard" in result[0].text

