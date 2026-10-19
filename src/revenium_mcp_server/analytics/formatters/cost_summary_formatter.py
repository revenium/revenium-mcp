"""
Cost summary response formatter.

Dedicated formatter for cost summary responses,
following single responsibility principle.
"""

from typing import Any, Callable, Dict, List

from .base_formatter import AnalyticsResponseFormatter, mask_api_key_name


class CostSummaryFormatter(AnalyticsResponseFormatter):
    """Format cost summary analytics responses."""

    # The summary aggregates the five dimension endpoints, which all live on
    # the same analytics plane; the provider endpoint is the total's primary
    # reference, so its key selects the plane for the scope note.
    ENDPOINT_KEY = "cost_metric_by_provider_over_time"

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
        total_text = (
            "not read (the provider part was not read; see Parts Not Read)"
            if total_cost is None
            else self.utilities.format_currency(total_cost)
        )

        response = f"""# **Cost Summary**

## **Summary Overview**
- **Time Period**: {period}
- **Aggregation**: {aggregation}
- **Total Cost**: {total_text}
- **Analysis Date**: {timestamp}

{self._format_parts_not_read(data.get("not_read") or {})}## **Top Contributors**

"""

        read = self._parts_read(data)
        response += self._format_top_contributors_section(
            "Providers", top_providers, "provider", read=read["top_providers"]
        )
        response += self._format_top_contributors_section(
            "Models", top_models, "model", read=read["top_models"]
        )
        response += self._format_top_contributors_section(
            "Customers", top_customers, "customer", read=read["top_customers"]
        )

        # Add new dimensions (API Keys and Agents)
        top_api_keys = data.get("top_api_keys", [])
        top_agents = data.get("top_agents", [])
        response += self._format_top_contributors_section(
            "API Keys",
            top_api_keys,
            "api_key",
            shown_as=mask_api_key_name,
            read=read["top_api_keys"],
        )
        response += self._format_top_contributors_section(
            "Agents", top_agents, "agent", read=read["top_agents"]
        )

        response += self.utilities.add_insights_footer(
            "cost summary", period, f"{aggregation} aggregation"
        )

        return f"{response}\n{self.utilities.coding_assistant_scope_note(self.ENDPOINT_KEY, period)}"

    @staticmethod
    def _parts_read(data: Dict[str, Any]) -> Dict[str, bool]:
        """Whether each top list comes from a part that was read, keyed by its top key."""
        from ..simple_cost_analyzer import COST_SUMMARY_PARTS

        not_read = data.get("not_read") or {}
        return {
            part.top_key: part.top_key in data and part.key not in not_read
            for part in COST_SUMMARY_PARTS
        }

    @staticmethod
    def _format_parts_not_read(not_read: Dict[str, str]) -> str:
        """Name each part that could not be read, its reason and the action that reads it alone."""
        from ..simple_cost_analyzer import COST_SUMMARY_PARTS

        if not not_read:
            return ""
        lines = ["## **Parts Not Read**", ""]
        for part in COST_SUMMARY_PARTS:
            if part.key in not_read:
                lines.append(
                    f"- **{part.label}**: {not_read[part.key]}. "
                    f"Retry this part alone with `{part.action}`."
                )
        lines += ["", "The figures below cover only the parts that were read."]
        return "\n".join(lines) + "\n\n"

    def _format_top_contributors_section(
        self,
        section_name: str,
        contributors: List[Dict[str, Any]],
        key_field: str,
        shown_as: Callable[[str], str] = str,
        read: bool = False,
    ) -> str:
        """Format a section of top contributors.

        Args:
            section_name: Display name for the section
            contributors: List of contributors
            key_field: Field name containing the contributor name
            read: Whether the part was read, so an empty list means nothing
                added cost rather than nothing read

        Returns:
            Formatted contributors section
        """
        if not contributors:
            if read:
                return (
                    f"**Top {section_name}:** none above "
                    f"{self.utilities.format_currency(0)}\n\n"
                )
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
            response += f"- {shown_as(name)}: {self.utilities.format_currency(cost)}\n"
        response += "\n"

        return response
