"""
Provider costs response formatter.

Dedicated formatter for provider cost analysis responses,
following single responsibility principle.
"""

from typing import Any, Dict, List

from .base_formatter import AnalyticsResponseFormatter


class ProviderCostsFormatter(AnalyticsResponseFormatter):
    """Format provider costs analytics responses."""

    def format(self, data: List[Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format provider costs data for response.

        Args:
            data: Provider cost data from API
            params: Formatting parameters (period, aggregation)

        Returns:
            Formatted provider costs response string
        """
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")

        if not data:
            return self.utilities.format_no_data_response(
                "provider costs", period, f"aggregation: {aggregation}"
            )

        return self._format_provider_costs_content(
            data, {"period": period, "aggregation": aggregation}
        )

    def _format_provider_costs_content(
        self, data: List[Dict[str, Any]], params: Dict[str, Any]
    ) -> str:
        """Format the main provider costs content with proper decomposition.

        Args:
            data: Provider cost data
            params: Parameters containing period and aggregation

        Returns:
            Formatted response content
        """
        header = self._format_provider_costs_header(data, params)
        table_content = self._format_provider_costs_table(data)
        footer = self._format_provider_costs_footer(params)

        return f"{header}\n\n{table_content}\n{footer}"

    def _format_provider_costs_header(
        self, data: List[Dict[str, Any]], params: Dict[str, Any]
    ) -> str:
        """Format header section for provider costs display.

        Args:
            data: Provider cost data for counting providers
            params: Parameters containing period and aggregation

        Returns:
            Formatted header section
        """
        timestamp = self.utilities.get_timestamp()
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")

        return f"""# **Provider Cost Analysis**

## **Analysis Summary**
- **Time Period**: {period}
- **Aggregation**: {aggregation}
- **Providers Found**: {len(data)}
- **Analysis Date**: {timestamp}

## **Provider Cost Ranking**
"""

    def _format_provider_costs_table(self, data: List[Dict[str, Any]]) -> str:
        """Format table section for provider costs data.

        Args:
            data: Provider cost data to format

        Returns:
            Formatted table section
        """
        table_content = ""

        for i, provider in enumerate(data, 1):
            provider_entry = self._format_single_provider_entry(provider, i)
            table_content += provider_entry

        return table_content

    def _format_single_provider_entry(self, provider: Dict[str, Any], index: int) -> str:
        """Format a single provider entry for the table.

        Args:
            provider: Single provider data
            index: Provider index for numbering

        Returns:
            Formatted provider entry
        """
        provider_name = provider.get("provider", "Unknown Provider")

        # Handle debug information - only show in debug mode
        if provider_name == "DEBUG_INFO" and "debug" in provider:
            return self._format_debug_entry(provider)

        return self._format_regular_provider_entry(provider, index)

    def _format_debug_entry(self, provider: Dict[str, Any]) -> str:
        """Format debug information entry.

        Args:
            provider: Provider data containing debug info

        Returns:
            Formatted debug entry or empty string if in production mode
        """
        if not self.production_mode:
            return f"## **DEBUG INFORMATION**\n\n**Debug Details**: {provider['debug']}\n\n"
        return ""

    def _format_regular_provider_entry(self, provider: Dict[str, Any], index: int) -> str:
        """Format a regular provider entry with cost and optional details.

        Args:
            provider: Provider data
            index: Provider index for numbering

        Returns:
            Formatted provider entry
        """
        provider_name = provider.get("provider", "Unknown Provider")
        cost = provider.get("cost", 0)
        cost_formatted = self.utilities.format_currency(cost)

        entry = f"**{index}. {provider_name}**\n   - Cost: {cost_formatted}\n"

        if "percentage" in provider:
            entry += f"   - Share: {provider['percentage']:.1f}%\n"

        # Add debug information if available - only in debug mode
        if not self.production_mode and "debug_metrics_count" in provider:
            debug_structure = provider.get("debug_metrics_structure", "N/A")
            entry += f"   - Debug: {provider['debug_metrics_count']} metrics, structure: {debug_structure}\n"

        return entry + "\n"

    def _format_provider_costs_footer(self, params: Dict[str, Any]) -> str:
        """Format footer section with insights and totals.

        Args:
            params: Parameters containing period and aggregation

        Returns:
            Formatted footer section
        """
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")
        return self.utilities.add_insights_footer(
            "provider costs", period, f"{aggregation} aggregation"
        )
