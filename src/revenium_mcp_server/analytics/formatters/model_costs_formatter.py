"""
Model costs response formatter.

Dedicated formatter for model cost analysis responses,
following single responsibility principle.
"""

from typing import Any, Dict, List

from .base_formatter import AnalyticsResponseFormatter


class ModelCostsFormatter(AnalyticsResponseFormatter):
    """Format model costs analytics responses."""

    def format(self, data: List[Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format model costs data for response.

        Args:
            data: Model cost data from API
            params: Formatting parameters (period, aggregation)

        Returns:
            Formatted model costs response string
        """
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")

        if not data:
            return self.utilities.format_no_data_response(
                "model costs", period, f"aggregation: {aggregation}"
            )

        return self._format_model_costs_content(data, period, aggregation)

    def _format_model_costs_content(
        self, data: List[Dict[str, Any]], period: str, aggregation: str
    ) -> str:
        """Format the main model costs content.

        Args:
            data: Model cost data
            period: Time period analyzed
            aggregation: Aggregation type used

        Returns:
            Formatted response content
        """
        timestamp = self.utilities.get_timestamp()

        response = f"""# **Model Cost Analysis**

## **Analysis Summary**
- **Time Period**: {period}
- **Aggregation**: {aggregation}
- **Models Found**: {len(data)}
- **Analysis Date**: {timestamp}

## **Model Cost Ranking**

"""

        for i, model in enumerate(data, 1):
            model_name = model.get("model", "Unknown Model")
            cost = model.get("cost", 0)

            cost_formatted = self.utilities.format_currency(cost)

            response += f"**{i}. {model_name}**\n"
            response += f"   - Cost: {cost_formatted}\n"

            if "percentage" in model:
                response += f"   - Share: {model['percentage']:.1f}%\n"

            response += "\n"

        response += self.utilities.add_insights_footer(
            "model costs", period, f"{aggregation} aggregation"
        )

        return response
