"""
Cost summary response formatter.

Dedicated formatter for cost summary responses,
following single responsibility principle.
"""

from typing import Any, Dict, List

from .base_formatter import AnalyticsResponseFormatter


class CostSummaryFormatter(AnalyticsResponseFormatter):
    """Format cost summary analytics responses."""

    def format(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format cost summary data for response.

        Args:
            data: Cost summary data from API
            params: Formatting parameters (period, aggregation)

        Returns:
            Formatted cost summary response string
        """
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")

        return self._format_cost_summary_content(data, period, aggregation)

    def _format_cost_summary_content(
        self, data: Dict[str, Any], period: str, aggregation: str
    ) -> str:
        """Format the main cost summary content.

        Args:
            data: Cost summary data
            period: Time period analyzed
            aggregation: Aggregation type used

        Returns:
            Formatted response content
        """
        timestamp = self.utilities.get_timestamp()
        total_cost = data.get("total_cost", 0)
        top_providers = data.get("top_providers", [])
        top_models = data.get("top_models", [])
        top_customers = data.get("top_customers", [])

        response = f"""# **Cost Summary**

## **Summary Overview**
- **Time Period**: {period}
- **Aggregation**: {aggregation}
- **Total Cost**: {self.utilities.format_currency(total_cost)}
- **Analysis Date**: {timestamp}

## **Top Contributors**

"""

        response += self._format_top_contributors_section("Providers", top_providers, "provider")
        response += self._format_top_contributors_section("Models", top_models, "model")
        response += self._format_top_contributors_section("Customers", top_customers, "customer")

        # Add new dimensions (API Keys and Agents)
        top_api_keys = data.get("top_api_keys", [])
        top_agents = data.get("top_agents", [])
        response += self._format_top_contributors_section("API Keys", top_api_keys, "api_key")
        response += self._format_top_contributors_section("Agents", top_agents, "agent")

        response += self.utilities.add_insights_footer(
            "cost summary", period, f"{aggregation} aggregation"
        )

        return response

    def _format_top_contributors_section(
        self, section_name: str, contributors: List[Dict[str, Any]], key_field: str
    ) -> str:
        """Format a section of top contributors.

        Args:
            section_name: Display name for the section
            contributors: List of contributors
            key_field: Field name containing the contributor name

        Returns:
            Formatted contributors section
        """
        if not contributors:
            return ""

        response = f"**Top {section_name}:**\n"
        for contributor in contributors[:3]:  # Top 3
            # Handle different possible key names for compatibility
            name = (
                contributor.get(key_field)
                or contributor.get("name")
                or f"Unknown {section_name[:-1]}"
            )  # Remove 's' from section name
            cost = contributor.get("cost", 0)
            response += f"- {name}: {self.utilities.format_currency(cost)}\n"
        response += "\n"

        return response
