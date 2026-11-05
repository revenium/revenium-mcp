"""
Agent costs response formatter.

Dedicated formatter for agent cost analysis responses,
following single responsibility principle.
"""

from typing import Any, Dict, List, Optional

from ..paging import PageInfo, counted, pagination_lines, past_last_page_sentence
from ..validation import SupportedAggregation
from .base_formatter import AnalyticsResponseFormatter


class AgentCostsFormatter(AnalyticsResponseFormatter):
    """Format agent costs analytics responses."""

    # Endpoint this formatter renders, so the coding-assistant scope note
    # follows the plane the registry actually routes to.
    ENDPOINT_KEY = "cost_metrics_by_agents_over_time"

    def format(self, data: List[Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format agent costs data for response.

        Args:
            data: The agents on one page of the ranking
            params: Formatting parameters (period, aggregation, paging,
                all_agents_cost, ranking_complete, and the endpoint_key the
                rows were read with when it is not ENDPOINT_KEY)

        Returns:
            Formatted agent costs response string
        """
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")
        endpoint_key = params.get("endpoint_key", self.ENDPOINT_KEY)
        paging = params.get("paging") or PageInfo()

        if not data and paging.total_elements:
            return self._format_past_last_page(paging, period, aggregation, endpoint_key)
        if not data:
            return self.utilities.format_no_data_response(
                "agent costs",
                period,
                f"aggregation: {aggregation}",
                scope_note=self.utilities.coding_assistant_scope_note(endpoint_key, period),
            )

        return self._format_agent_costs_content(
            data,
            {
                "period": period,
                "aggregation": aggregation,
                "endpoint_key": endpoint_key,
                "paging": paging,
                "all_agents_cost": params.get("all_agents_cost"),
                "ranking_complete": params.get("ranking_complete", True),
            },
        )

    def _format_past_last_page(
        self, paging: PageInfo, period: Any, aggregation: Any, endpoint_key: str
    ) -> str:
        sentence = past_last_page_sentence(
            paging, counted(paging.total_elements or 0, "agent", "agents")
        )
        return f"""# **Agent Cost Analysis**

- **Time Period**: {period}
- **Aggregation**: {aggregation}

## **Page past the last one**

{sentence}

{self.utilities.coding_assistant_scope_note(endpoint_key, period)}"""

    def _format_agent_costs_content(
        self, data: List[Dict[str, Any]], params: Dict[str, Any]
    ) -> str:
        """Format the main agent costs content with proper decomposition.

        Args:
            data: Agent cost data
            params: Parameters containing period and aggregation

        Returns:
            Formatted response content
        """
        paging: PageInfo = params["paging"]
        header = self._format_agent_costs_header(data, params)
        table_content = self._format_agent_costs_table(
            data, paging, params.get("ranking_complete", True)
        )
        pages = "\n".join(pagination_lines(paging, "agent", "agents"))
        footer = self._format_agent_costs_footer(params)

        return f"{header}\n\n{table_content}{pages}\n{footer}"

    def _format_agent_costs_header(self, data: List[Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format header section for agent costs display.

        Args:
            data: Agent cost data for counting agents
            params: Parameters containing period and aggregation

        Returns:
            Formatted header section
        """
        timestamp = self.utilities.get_timestamp()
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")
        totals = self._format_agent_totals(data, params)

        return f"""# **Agent Cost Analysis**

## **Analysis Summary**
- **Time Period**: {period}
- **Aggregation**: {aggregation}
{totals}
- **Analysis Date**: {timestamp}

## **Agent Cost Ranking**
"""

    def _format_agent_totals(self, data: List[Dict[str, Any]], params: Dict[str, Any]) -> str:
        """The agent count, and for a TOTAL ranking the cost, of the page and of every agent.

        Summing per-agent means or extremes gives no team figure, so a MEAN,
        MAXIMUM or MINIMUM ranking states counts only.
        """
        paging: PageInfo = params["paging"]
        sums_costs = params.get("aggregation") == SupportedAggregation.TOTAL.value
        page_cost = self.utilities.format_currency(sum(agent.get("cost", 0) for agent in data))

        if not paging.spans_several_pages:
            lines = [f"- **Agents Found**: {len(data)}"]
            if sums_costs:
                lines.append(f"- **Total Cost**: {page_cost}")
            return "\n".join(lines)

        complete = params.get("ranking_complete", True)
        all_agents = "unknown" if paging.total_elements is None else paging.total_elements
        lines = [f"- **Agents on this page**: {len(data)} of {all_agents}"]
        if sums_costs:
            lines.append(f"- **Total Cost (this page only)**: {page_cost}")
            all_agents_cost: Optional[float] = params.get("all_agents_cost")
            if all_agents_cost is not None:
                scope = f"all {all_agents} agents" if complete else f"the {all_agents} agents read"
                lines.append(
                    f"- **Total Cost ({scope})**: {self.utilities.format_currency(all_agents_cost)}"
                )
        coverage = (
            "The ranking and the shares cover every agent on the team, not just this page."
            if complete
            else "The ranking and the shares cover the agents in the part of the period that "
            "was read, not the whole team: see the note at the end."
        )
        lines.append(
            f"- **Pages**: this is page {(paging.number or 0) + 1} of {paging.total_pages}. {coverage}"
        )
        return "\n".join(lines)

    def _format_agent_costs_table(
        self, data: List[Dict[str, Any]], paging: PageInfo, complete: bool = True
    ) -> str:
        """Format table section for agent costs data.

        Args:
            data: The agents on this page
            paging: Where this page sits, so agents are numbered from its offset
            complete: False when the shares cover only the agents read

        Returns:
            Formatted table section
        """
        share_label = "Share of all agents" if paging.spans_several_pages else "Share"
        if paging.spans_several_pages and not complete:
            share_label = "Share of the agents read"
        return "".join(
            self._format_single_agent_entry(agent, index, share_label)
            for index, agent in enumerate(data, paging.first_index)
        )

    def _format_single_agent_entry(
        self, agent: Dict[str, Any], index: int, share_label: str = "Share"
    ) -> str:
        """Format a single agent entry for the table.

        Args:
            agent: Single agent data
            index: Agent index for numbering
            share_label: How the share is labelled, by what it is a share of

        Returns:
            Formatted agent entry
        """
        agent_name = agent.get("agent", "Unknown Agent")

        # Handle debug information - only show in debug mode
        if agent_name == "DEBUG_INFO" and "debug" in agent:
            return self._format_debug_entry(agent)

        return self._format_regular_agent_entry(agent, index, share_label)

    def _format_debug_entry(self, agent: Dict[str, Any]) -> str:
        """Format debug information entry.

        Args:
            agent: Agent data containing debug info

        Returns:
            Formatted debug entry or empty string if in production mode
        """
        if not self.production_mode:
            return f"## **DEBUG INFORMATION**\n\n**Debug Details**: {agent['debug']}\n\n"
        return ""

    def _format_regular_agent_entry(
        self, agent: Dict[str, Any], index: int, share_label: str = "Share"
    ) -> str:
        """Format a regular agent entry with cost and optional details.

        Args:
            agent: Agent data
            index: Agent index for numbering
            share_label: How the share is labelled, by what it is a share of

        Returns:
            Formatted agent entry
        """
        agent_name = agent.get("agent", "Unknown Agent")
        cost = agent.get("cost", 0)
        cost_formatted = self.utilities.format_currency(cost)

        entry = f"**{index}. {agent_name}**\n   - Cost: {cost_formatted}\n"

        if "percentage" in agent:
            entry += f"   - {share_label}: {agent['percentage']:.1f}%\n"

        # Add debug information if available - only in debug mode
        if not self.production_mode and "debug_metrics_count" in agent:
            debug_structure = agent.get("debug_metrics_structure", "N/A")
            entry += f"   - Debug: {agent['debug_metrics_count']} metrics, structure: {debug_structure}\n"

        return entry + "\n"

    def _format_agent_costs_footer(self, params: Dict[str, Any]) -> str:
        """Format footer section with insights and totals.

        Args:
            params: Parameters containing period and aggregation

        Returns:
            Formatted footer section
        """
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")
        footer = self.utilities.add_insights_footer(
            "agent costs", period, f"{aggregation} aggregation"
        )
        endpoint_key = params.get("endpoint_key", self.ENDPOINT_KEY)
        scope_note = self.utilities.coding_assistant_scope_note(endpoint_key, period)
        return f"{footer}\n{scope_note}"
