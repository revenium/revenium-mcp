"""
Customer costs response formatter.

Dedicated formatter for customer cost analysis responses,
following single responsibility principle.
"""

from typing import Any, Dict, List

from .base_formatter import AnalyticsResponseFormatter


class CustomerCostsFormatter(AnalyticsResponseFormatter):
    """Format customer costs analytics responses."""

    # Endpoint this formatter renders, so the coding-assistant scope note
    # follows the plane the registry actually routes to.
    ENDPOINT_KEY = "cost_metric_by_organization"

    def format(self, data: List[Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format customer costs data for response.

        Args:
            data: Customer cost data from API
            params: Formatting parameters (period, aggregation)

        Returns:
            Formatted customer costs response string
        """
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")

        if not data:
            return self.utilities.format_no_data_response(
                "customer costs",
                period,
                f"aggregation: {aggregation}",
                scope_note=self.utilities.coding_assistant_scope_note(self.ENDPOINT_KEY),
            )

        return self._format_customer_costs_content(data, period, aggregation)

    def _format_customer_costs_content(
        self, data: List[Dict[str, Any]], period: str, aggregation: str
    ) -> str:
        """Format the main customer costs content.

        Args:
            data: Customer cost data
            period: Time period analyzed
            aggregation: Aggregation type used

        Returns:
            Formatted response content
        """
        timestamp = self.utilities.get_timestamp()

        response = f"""# **Customer Cost Analysis**

## **Analysis Summary**
- **Time Period**: {period}
- **Aggregation**: {aggregation}
- **Customers Found**: {len(data)}
- **Analysis Date**: {timestamp}

## **Customer Cost Ranking**

"""

        for i, customer in enumerate(data, 1):
            customer_name = customer.get("customer", "Unknown Customer")
            cost = customer.get("cost", 0)

            cost_formatted = self.utilities.format_currency(cost)

            response += f"**{i}. {customer_name}**\n"
            response += f"   - Cost: {cost_formatted}\n"

            if "percentage" in customer:
                response += f"   - Share: {customer['percentage']:.1f}%\n"

            response += "\n"

        response += self.utilities.add_insights_footer(
            "customer costs", period, f"{aggregation} aggregation"
        )
        response += f"\n{self.utilities.coding_assistant_scope_note(self.ENDPOINT_KEY)}"

        return response
