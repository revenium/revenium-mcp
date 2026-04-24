"""
User costs response formatter.

Dedicated formatter for user cost analysis responses (cost-by-user endpoint).
Returns cost, request count, and token usage per subscriber email.
"""

from typing import Any, Dict, List

from .base_formatter import AnalyticsResponseFormatter


class UserCostsFormatter(AnalyticsResponseFormatter):
    """Format user costs analytics responses."""

    def format(self, data: List[Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format user costs data for response.

        Args:
            data: User cost data from API
            params: Formatting parameters (period, aggregation)

        Returns:
            Formatted user costs response string
        """
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")

        if not data:
            return self.utilities.format_no_data_response(
                "user costs", period, f"aggregation: {aggregation}"
            )

        return self._format_user_costs_content(
            data, {"period": period, "aggregation": aggregation}
        )

    def _format_user_costs_content(
        self, data: List[Dict[str, Any]], params: Dict[str, Any]
    ) -> str:
        header = self._format_user_costs_header(data, params)
        table_content = self._format_user_costs_table(data)
        footer = self._format_user_costs_footer(params)

        return f"{header}\n\n{table_content}\n{footer}"

    def _format_user_costs_header(self, data: List[Dict[str, Any]], params: Dict[str, Any]) -> str:
        timestamp = self.utilities.get_timestamp()
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")
        total_cost = sum(item.get("cost", 0) for item in data)
        total_requests = sum(item.get("requests", 0) for item in data)

        return f"""# **User Cost Analysis**

## **Analysis Summary**
- **Time Period**: {period}
- **Aggregation**: {aggregation}
- **Users Found**: {len(data)}
- **Total Cost**: {self.utilities.format_currency(total_cost)}
- **Total Requests**: {total_requests:,}
- **Analysis Date**: {timestamp}

## **User Cost Ranking**
"""

    def _format_user_costs_table(self, data: List[Dict[str, Any]]) -> str:
        table_content = ""

        for i, user in enumerate(data, 1):
            table_content += self._format_single_user_entry(user, i)

        return table_content

    def _format_single_user_entry(self, user: Dict[str, Any], index: int) -> str:
        user_email = user.get("user_email", "Unknown User")
        cost = user.get("cost", 0)
        requests = user.get("requests", 0)
        tokens = user.get("tokens", 0)
        cost_formatted = self.utilities.format_currency(cost)

        entry = f"**{index}. {user_email}**\n"
        entry += f"   - Cost: {cost_formatted}\n"

        if "percentage" in user:
            entry += f"   - Share: {user['percentage']:.1f}%\n"

        entry += f"   - Requests: {requests:,}\n"

        if tokens > 0:
            if tokens >= 1_000_000:
                entry += f"   - Tokens: {tokens / 1_000_000:.1f}M\n"
            elif tokens >= 1_000:
                entry += f"   - Tokens: {tokens / 1_000:.1f}K\n"
            else:
                entry += f"   - Tokens: {tokens:,}\n"

        return entry + "\n"

    def _format_user_costs_footer(self, params: Dict[str, Any]) -> str:
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")
        return self.utilities.add_insights_footer(
            "user costs", period, f"{aggregation} aggregation"
        )
