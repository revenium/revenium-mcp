"""
User costs response formatter.

Dedicated formatter for user cost analysis responses (cost-by-user endpoint).
Returns cost, request count, and token usage per subscriber email.
"""

from typing import Any, Dict, List

from ..paging import PageInfo, counted, pagination_lines, past_last_page_sentence
from .base_formatter import AnalyticsResponseFormatter


class UserCostsFormatter(AnalyticsResponseFormatter):
    """Format user costs analytics responses."""

    # Endpoint this formatter renders, so the coding-assistant scope note
    # follows the plane the registry actually routes to.
    ENDPOINT_KEY = "cost_metric_by_user_aggregated"

    def format(self, data: List[Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format user costs data for response.

        Args:
            data: The users on one page of the report
            params: Formatting parameters (period, aggregation, paging)

        Returns:
            Formatted user costs response string
        """
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")
        paging = params.get("paging") or PageInfo()

        if not data and paging.total_elements:
            return self._format_past_last_page(paging, period, aggregation)
        if not data:
            return self.utilities.format_no_data_response(
                "user costs",
                period,
                f"aggregation: {aggregation}",
                scope_note=self._scope_notes(),
            )

        return self._format_user_costs_content(
            data, {"period": period, "aggregation": aggregation, "paging": paging}
        )

    def _format_past_last_page(self, paging: PageInfo, period: Any, aggregation: Any) -> str:
        sentence = past_last_page_sentence(
            paging, counted(paging.total_elements or 0, "user", "users")
        )
        return f"""# **User Cost Analysis**

- **Time Period**: {period}
- **Aggregation**: {aggregation}

## **Page past the last one**

{sentence}

{self._scope_notes()}"""

    def _scope_notes(self) -> str:
        """Scope caveats every user-cost response carries, empty or not.

        A per-user total that is small or absent must never be read as a
        measure of a person's usage, so the caveat cannot be attached to the
        empty case alone.
        """
        return (
            self.utilities.coding_assistant_scope_note(self.ENDPOINT_KEY)
            + "\n"
            + self.utilities.user_attribution_note()
        )

    def _format_user_costs_content(
        self, data: List[Dict[str, Any]], params: Dict[str, Any]
    ) -> str:
        paging: PageInfo = params["paging"]
        header = self._format_user_costs_header(data, params)
        table_content = self._format_user_costs_table(data, paging)
        pages = "\n".join(pagination_lines(paging, "user", "users"))
        footer = self._format_user_costs_footer(params)

        return f"{header}\n\n{table_content}{pages}\n{footer}"

    def _format_user_costs_header(self, data: List[Dict[str, Any]], params: Dict[str, Any]) -> str:
        timestamp = self.utilities.get_timestamp()
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")
        paging: PageInfo = params["paging"]
        total_cost = self.utilities.format_currency(sum(item.get("cost", 0) for item in data))
        total_requests = sum(item.get("requests", 0) for item in data)

        if paging.spans_several_pages:
            all_users = "unknown" if paging.total_elements is None else paging.total_elements
            totals = f"""- **Users on this page**: {len(data)} of {all_users}
- **Total Cost (this page only)**: {total_cost}
- **Total Requests (this page only)**: {total_requests:,}
- **Pages**: this is page {(paging.number or 0) + 1} of {paging.total_pages}. The totals above \
cover this page, not the whole team: add every page's totals for the team figure."""
        else:
            totals = f"""- **Users Found**: {len(data)}
- **Total Cost**: {total_cost}
- **Total Requests**: {total_requests:,}"""

        return f"""# **User Cost Analysis**

## **Analysis Summary**
- **Time Period**: {period}
- **Aggregation**: {aggregation}
{totals}
- **Analysis Date**: {timestamp}

## **User Cost Ranking**
"""

    def _format_user_costs_table(self, data: List[Dict[str, Any]], paging: PageInfo) -> str:
        share_label = "Share of this page" if paging.spans_several_pages else "Share"
        return "".join(
            self._format_single_user_entry(user, index, share_label)
            for index, user in enumerate(data, paging.first_index)
        )

    def _format_single_user_entry(
        self, user: Dict[str, Any], index: int, share_label: str
    ) -> str:
        user_email = user.get("user_email", "Unknown User")
        cost = user.get("cost", 0)
        requests = user.get("requests", 0)
        tokens = user.get("tokens", 0)
        cost_formatted = self.utilities.format_currency(cost)

        entry = f"**{index}. {user_email}**\n"
        entry += f"   - Cost: {cost_formatted}\n"

        if "percentage" in user:
            entry += f"   - {share_label}: {user['percentage']:.1f}%\n"

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
        footer = self.utilities.add_insights_footer(
            "user costs", period, f"{aggregation} aggregation"
        )
        return f"{footer}\n{self._scope_notes()}"
