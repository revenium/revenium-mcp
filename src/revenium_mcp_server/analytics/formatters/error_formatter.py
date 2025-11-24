"""
Error response formatter.

Dedicated formatter for error responses in analytics,
following single responsibility principle.
"""

from typing import Any, Dict, List, Optional

from .base_formatter import AnalyticsResponseFormatter


class ErrorFormatter(AnalyticsResponseFormatter):
    """Format analytics error responses."""

    def format(self, error_message: str, params: Dict[str, Any]) -> str:
        """Format error response with helpful suggestions.

        Args:
            error_message: Error message to format
            params: Formatting parameters (suggestions)

        Returns:
            Formatted error response string
        """
        suggestions = params.get("suggestions", [])

        return self._format_error_content(error_message, suggestions)

    def _format_error_content(
        self, error_message: str, suggestions: Optional[List[str]] = None
    ) -> str:
        """Format the main error content.

        Args:
            error_message: Error message
            suggestions: List of helpful suggestions

        Returns:
            Formatted error response content
        """
        timestamp = self.utilities.get_timestamp()

        response = f"""# **Analytics Error**

**Error**: {error_message}

**Timestamp**: {timestamp}

"""

        if suggestions:
            response += "**Suggestions:**\n"
            for suggestion in suggestions:
                response += f"- {suggestion}\n"
            response += "\n"

        response += self._get_help_footer()

        return response

    def _get_help_footer(self) -> str:
        """Get standard help footer for error responses.

        Returns:
            Formatted help footer
        """
        return """**For Help:**
- Use `get_capabilities()` to see supported parameters
- Use `get_examples()` to see working examples
- Check the rebuild status for implementation timeline
"""
