"""
Base formatter interface and utilities for analytics responses.

Provides abstract base class and common formatting utilities
that all specialized formatters can inherit and use.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List


class BaseFormattingUtilities:
    """Common formatting utilities for all analytics formatters."""

    @staticmethod
    def format_currency(cost: Any) -> str:
        """Format cost value as currency string.

        Args:
            cost: Cost value to format

        Returns:
            Formatted currency string
        """
        if isinstance(cost, (int, float)):
            return f"${cost:,.2f}"
        return str(cost)

    @staticmethod
    def get_timestamp() -> str:
        """Get current timestamp in ISO format.

        Returns:
            Current timestamp string
        """
        return datetime.utcnow().isoformat()

    @staticmethod
    def add_insights_footer(analysis_type: str, period: str, extra_info: str) -> str:
        """Add standard insights footer to responses.

        Args:
            analysis_type: Type of analysis performed
            period: Time period analyzed
            extra_info: Additional info (aggregation, threshold, etc.)

        Returns:
            Formatted insights footer
        """
        return f"""
## **Analysis Insights**

This {analysis_type} analysis covers the {period} period using {extra_info}.

**Next Steps:**
- Use different time periods to see trends over time
- Try different aggregations (MEAN, MAXIMUM, MINIMUM) for different perspectives
- Combine with other analytics features for comprehensive insights
"""

    @staticmethod
    def format_no_data_response(analysis_type: str, period: str, extra_info: str) -> str:
        """Format standard no data response.

        Args:
            analysis_type: Type of analysis attempted
            period: Time period requested
            extra_info: Additional context (aggregation, etc.)

        Returns:
            Formatted no data response
        """
        timestamp = BaseFormattingUtilities.get_timestamp()

        return f"""# **{analysis_type.title()} Analysis**

## **No Data Available**

**Time Period**: {period}
**Additional Info**: {extra_info}
**Analysis Date**: {timestamp}

No data was found for the specified parameters. This could be because:
- No activity occurred during the time period
- Data is still being processed
- The time period is too recent

**Suggestions:**
- Try a longer time period (e.g., THIRTY_DAYS instead of SEVEN_DAYS)
- Check if there was any AI activity during this period
- Verify that data sources are properly configured

**For Help:**
- Use `get_capabilities()` to see supported parameters
- Use `get_examples()` to see working examples
"""


class AnalyticsResponseFormatter(ABC):
    """Base formatter for analytics responses."""

    def __init__(self, production_mode: bool = True):
        """Initialize the formatter.

        Args:
            production_mode: If True, hides debug information
        """
        self.production_mode = production_mode
        self.utilities = BaseFormattingUtilities()

    @abstractmethod
    def format(self, data: Any, params: Dict[str, Any]) -> str:
        """Format analytics data for response.

        Args:
            data: Analytics data to format
            params: Formatting parameters

        Returns:
            Formatted response string
        """
        pass
