"""
Agent costs response formatter.

Dedicated formatter for agent cost analysis responses,
following single responsibility principle.
"""

from typing import Any, Dict, List

from .base_formatter import AnalyticsResponseFormatter


class AgentCostsFormatter(AnalyticsResponseFormatter):
    """Format agent costs analytics responses."""

    def format(self, data: List[Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format agent costs data for response.

        Args:
            data: Agent cost data from API
            params: Formatting parameters (period, aggregation)

        Returns:
            Formatted agent costs response string
        """
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")

        if not data:
            return self.utilities.format_no_data_response(
                "agent costs", period, f"aggregation: {aggregation}"
            )

        return self._format_agent_costs_content(
            data, {"period": period, "aggregation": aggregation}
        )

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
        header = self._format_agent_costs_header(data, params)
        table_content = self._format_agent_costs_table(data)
        footer = self._format_agent_costs_footer(params)

        return f"{header}\n\n{table_content}\n{footer}"

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

        return f"""# **Agent Cost Analysis**

## **Analysis Summary**
- **Time Period**: {period}
- **Aggregation**: {aggregation}
- **Agents Found**: {len(data)}
- **Analysis Date**: {timestamp}

## **Agent Cost Ranking**
"""

    def _format_agent_costs_table(self, data: List[Dict[str, Any]]) -> str:
        """Format table section for agent costs data.

        Args:
            data: Agent cost data to format

        Returns:
            Formatted table section
        """
        table_content = ""

        for i, agent in enumerate(data, 1):
            agent_entry = self._format_single_agent_entry(agent, i)
            table_content += agent_entry

        return table_content

    def _format_single_agent_entry(self, agent: Dict[str, Any], index: int) -> str:
        """Format a single agent entry for the table.

        Args:
            agent: Single agent data
            index: Agent index for numbering

        Returns:
            Formatted agent entry
        """
        agent_name = agent.get("agent", "Unknown Agent")

        # Handle debug information - only show in debug mode
        if agent_name == "DEBUG_INFO" and "debug" in agent:
            return self._format_debug_entry(agent)

        return self._format_regular_agent_entry(agent, index)

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

    def _format_regular_agent_entry(self, agent: Dict[str, Any], index: int) -> str:
        """Format a regular agent entry with cost and optional details.

        Args:
            agent: Agent data
            index: Agent index for numbering

        Returns:
            Formatted agent entry
        """
        agent_name = agent.get("agent", "Unknown Agent")
        cost = agent.get("cost", 0)
        cost_formatted = self.utilities.format_currency(cost)

        entry = f"**{index}. {agent_name}**\n   - Cost: {cost_formatted}\n"

        if "percentage" in agent:
            entry += f"   - Share: {agent['percentage']:.1f}%\n"

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
        return self.utilities.add_insights_footer(
            "agent costs", period, f"{aggregation} aggregation"
        )
