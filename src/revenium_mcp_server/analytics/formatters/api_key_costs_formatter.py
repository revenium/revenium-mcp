"""
API key costs response formatter.

Dedicated formatter for API key cost analysis responses,
following single responsibility principle.
"""

from typing import Any, Dict, List

from .base_formatter import AnalyticsResponseFormatter, mask_api_key_name

__all__ = ["ApiKeyCostsFormatter", "mask_api_key_name"]


class ApiKeyCostsFormatter(AnalyticsResponseFormatter):
    """Format API key costs analytics responses."""

    # Endpoint this formatter renders, so the coding-assistant scope note
    # follows the plane the registry actually routes to.
    ENDPOINT_KEY = "cost_metrics_by_subscriber_credential"

    def format(self, data: List[Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format API key costs data for response.

        Args:
            data: API key cost data from API
            params: Formatting parameters (period, aggregation)

        Returns:
            Formatted API key costs response string
        """
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")

        if not data:
            return self.utilities.format_no_data_response(
                "API key costs",
                period,
                f"aggregation: {aggregation}",
                scope_note=self.utilities.coding_assistant_scope_note(self.ENDPOINT_KEY, period),
            )

        return self._format_api_key_costs_content(
            data, {"period": period, "aggregation": aggregation}
        )

    def _format_api_key_costs_content(
        self, data: List[Dict[str, Any]], params: Dict[str, Any]
    ) -> str:
        """Format the main API key costs content with proper decomposition.

        Args:
            data: API key cost data
            params: Parameters containing period and aggregation

        Returns:
            Formatted response content
        """
        header = self._format_api_key_costs_header(data, params)
        table_content = self._format_api_key_costs_table(data)
        footer = self._format_api_key_costs_footer(params)

        return f"{header}\n\n{table_content}\n{footer}"

    def _format_api_key_costs_header(
        self, data: List[Dict[str, Any]], params: Dict[str, Any]
    ) -> str:
        """Format header section for API key costs display.

        Args:
            data: API key cost data for counting keys
            params: Parameters containing period and aggregation

        Returns:
            Formatted header section
        """
        timestamp = self.utilities.get_timestamp()
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")

        return f"""# **API Key Cost Analysis**

## **Analysis Summary**
- **Time Period**: {period}
- **Aggregation**: {aggregation}
- **API Keys Found**: {sum(1 for row in data if row.get("api_key") != "DEBUG_INFO")}
- **Analysis Date**: {timestamp}

## **API Key Cost Ranking**
"""

    def _format_api_key_costs_table(self, data: List[Dict[str, Any]]) -> str:
        """Format table section for API key costs data.

        Args:
            data: API key cost data to format

        Returns:
            Formatted table section
        """
        table_content = ""

        for i, api_key in enumerate(data, 1):
            api_key_entry = self._format_single_api_key_entry(api_key, i)
            table_content += api_key_entry

        return table_content

    def _format_single_api_key_entry(self, api_key: Dict[str, Any], index: int) -> str:
        """Format a single API key entry for the table.

        Args:
            api_key: Single API key data
            index: API key index for numbering

        Returns:
            Formatted API key entry
        """
        api_key_name = api_key.get("api_key", "Unknown API Key")

        # Handle debug information - only show in debug mode
        if api_key_name == "DEBUG_INFO" and "debug" in api_key:
            return self._format_debug_entry(api_key)

        return self._format_regular_api_key_entry(api_key, index)

    def _format_debug_entry(self, api_key: Dict[str, Any]) -> str:
        """Format debug information entry.

        Args:
            api_key: API key data containing debug info

        Returns:
            Formatted debug entry or empty string if in production mode
        """
        if not self.production_mode:
            return f"## **DEBUG INFORMATION**\n\n**Debug Details**: {api_key['debug']}\n\n"
        return ""

    def _format_regular_api_key_entry(self, api_key: Dict[str, Any], index: int) -> str:
        """Format a regular API key entry with cost and optional details.

        Args:
            api_key: API key data
            index: API key index for numbering

        Returns:
            Formatted API key entry
        """
        api_key_name = api_key.get("api_key", "Unknown API Key")
        cost = api_key.get("cost", 0)
        cost_formatted = self.utilities.format_currency(cost)

        # Mask sensitive API key names for security
        masked_key_name = mask_api_key_name(api_key_name)

        entry = f"**{index}. {masked_key_name}**\n   - Cost: {cost_formatted}\n"

        if "percentage" in api_key:
            entry += f"   - Share: {api_key['percentage']:.1f}%\n"

        # Add debug information if available - only in debug mode
        if not self.production_mode and "debug_metrics_count" in api_key:
            debug_structure = api_key.get("debug_metrics_structure", "N/A")
            entry += f"   - Debug: {api_key['debug_metrics_count']} metrics, structure: {debug_structure}\n"

        return entry + "\n"

    def _format_api_key_costs_footer(self, params: Dict[str, Any]) -> str:
        """Format footer section with insights and totals.

        Args:
            params: Parameters containing period and aggregation

        Returns:
            Formatted footer section
        """
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")
        footer = self.utilities.add_insights_footer(
            "API key costs", period, f"{aggregation} aggregation"
        )
        return f"{footer}\n{self.utilities.coding_assistant_scope_note(self.ENDPOINT_KEY, period)}"
