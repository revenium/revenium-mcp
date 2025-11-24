"""FastMCP Performance Dashboard Error Handling.

This module contains all error handling methods for the FastMCP Performance Dashboard.
Extracted to maintain ≤300 lines per module enterprise standard.
"""

from typing import List, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..common.error_handling import ErrorCodes, ToolError


class FastMCPPerformanceErrors:
    """Error handling for FastMCP Performance Dashboard."""

    @staticmethod
    def get_error_suggestions() -> list:
        """Get error suggestions for dashboard failures.

        Returns:
            List of error suggestions
        """
        return [
            "Check FastMCP performance monitoring service status",
            "Verify performance metrics collection is working",
            "Try again after a few moments",
            "Contact system administrator if issue persists",
        ]

    @staticmethod
    def get_error_examples() -> dict:
        """Get error examples for dashboard failures.

        Returns:
            Dictionary of error examples
        """
        return {
            "troubleshooting": [
                "Check service status",
                "Verify metrics collection",
                "Test connectivity",
            ],
            "system_context": "🔧 SYSTEM: FastMCP dashboard provides real-time performance monitoring with alerting",
        }

    @staticmethod
    def create_dashboard_error(e: Exception) -> ToolError:
        """Create structured error for dashboard failures.

        Args:
            e: Exception that occurred during dashboard generation

        Returns:
            ToolError object for dashboard failure
        """
        return ToolError(
            message="Failed to generate FastMCP performance dashboard",
            error_code=ErrorCodes.TOOL_ERROR,
            field="fastmcp_performance_dashboard",
            value=str(e),
            suggestions=FastMCPPerformanceErrors.get_error_suggestions(),
            examples=FastMCPPerformanceErrors.get_error_examples(),
        )

    @staticmethod
    def handle_dashboard_error(
        e: Exception,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle dashboard generation errors.

        Args:
            e: Exception that occurred during dashboard generation

        Returns:
            Formatted error response list
        """
        logger.error(f"Error generating FastMCP performance dashboard: {e}")
        error = FastMCPPerformanceErrors.create_dashboard_error(e)
        from ..common.error_handling import format_structured_error

        error_text = format_structured_error(error)
        return [TextContent(type="text", text=error_text)]
