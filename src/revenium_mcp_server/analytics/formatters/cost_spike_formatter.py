"""
Cost spike investigation response formatter.

Dedicated formatter for cost spike investigation responses,
following single responsibility principle.
"""

from typing import Any, Dict, List

from .base_formatter import AnalyticsResponseFormatter


class CostSpikeFormatter(AnalyticsResponseFormatter):
    """Format cost spike investigation analytics responses."""

    def format(self, data: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Format cost spike investigation data for response.

        Args:
            data: Cost spike investigation data
            params: Formatting parameters (threshold, period)

        Returns:
            Formatted cost spike response string
        """
        threshold = params.get("threshold", 0)
        period = params.get("period", "Unknown")

        return self._format_cost_spike_content(data, threshold, period)

    def _format_cost_spike_content(
        self, data: Dict[str, Any], threshold: float, period: str
    ) -> str:
        """Format the main cost spike investigation content.

        Args:
            data: Cost spike investigation data
            threshold: Threshold used for investigation
            period: Time period analyzed

        Returns:
            Formatted response content
        """
        timestamp = self.utilities.get_timestamp()
        spike_detected = data.get("spike_detected", False)
        contributors = data.get("contributors", [])
        total_spike_cost = data.get("total_spike_cost", 0)
        contributors_count = data.get("contributors_count", 0)

        response = f"""# **Cost Spike Investigation**

## **Investigation Summary**
- **Threshold**: {self.utilities.format_currency(threshold)}
- **Time Period**: {period}
- **Spike Detected**: {"Yes" if spike_detected else "No"}
- **Contributors Found**: {contributors_count}
- **Total Spike Cost**: {self.utilities.format_currency(total_spike_cost)}
- **Analysis Date**: {timestamp}

"""

        if spike_detected and contributors:
            response += self._format_spike_detected_section(contributors, threshold)
        elif spike_detected and not contributors:
            response += self._format_spike_no_contributors_section(threshold)
        else:
            response += self._format_no_spike_section(threshold, period)

        response += self.utilities.add_insights_footer(
            "cost spike investigation",
            period,
            f"threshold: {self.utilities.format_currency(threshold)}",
        )

        return response

    def _format_spike_detected_section(
        self, contributors: List[Dict[str, Any]], threshold: float
    ) -> str:
        """Format the spike detected section with contributors.

        Args:
            contributors: List of spike contributors
            threshold: Cost threshold

        Returns:
            Formatted spike detected section
        """
        threshold_formatted = self.utilities.format_currency(threshold)
        contributors_count = len(contributors)

        response = f"## **WARNING: Cost Spike Detected**\n\n"
        response += f"Found {contributors_count} cost contributors above the {threshold_formatted} threshold.\n\n"

        # Group contributors by type for better organization
        providers = [c for c in contributors if c.get("type") == "provider"]
        models = [c for c in contributors if c.get("type") == "model"]
        customers = [c for c in contributors if c.get("type") == "customer"]

        response += self._format_contributor_group("Provider", providers)
        response += self._format_contributor_group("Model", models)
        response += self._format_contributor_group("Customer", customers)

        return response

    def _format_contributor_group(self, group_type: str, contributors: List[Dict[str, Any]]) -> str:
        """Format a group of contributors.

        Args:
            group_type: Type of contributors (Provider, Model, Customer)
            contributors: List of contributors in this group

        Returns:
            Formatted contributor group section
        """
        if not contributors:
            return ""

        response = f"**{group_type} Contributors:**\n"
        for i, contributor in enumerate(contributors, 1):
            name = contributor.get("name", f"Unknown {group_type}")
            cost = contributor.get("cost", 0)
            cost_formatted = self.utilities.format_currency(cost)

            response += f"   {i}. **{name}** - {cost_formatted}"
            if "percentage" in contributor:
                response += f" ({contributor['percentage']:.1f}%)"
            response += "\n"
        response += "\n"

        return response

    def _format_spike_no_contributors_section(self, threshold: float) -> str:
        """Format section when spike detected but no contributors identified.

        Args:
            threshold: Cost threshold

        Returns:
            Formatted no contributors section
        """
        return f"""## **WARNING: Cost Spike Detected**

Spike detected but no specific contributors identified above threshold.

"""

    def _format_no_spike_section(self, threshold: float, period: str) -> str:
        """Format section when no spike is detected.

        Args:
            threshold: Cost threshold
            period: Time period analyzed

        Returns:
            Formatted no spike section
        """
        threshold_formatted = self.utilities.format_currency(threshold)

        return f"""## **No Cost Spike Detected**

All costs remained below the {threshold_formatted} threshold during the {period} period.

"""
