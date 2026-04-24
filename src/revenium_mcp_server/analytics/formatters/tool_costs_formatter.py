"""
Tool costs response formatter.

Dedicated formatter for tool cost analysis responses,
following single responsibility principle.
"""

from typing import Any, Dict, List

from .base_formatter import AnalyticsResponseFormatter


class ToolCostsFormatter(AnalyticsResponseFormatter):
    """Format tool costs analytics responses."""

    def format(self, data: List[Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format tool costs data for response.

        Args:
            data: Tool cost data from API
            params: Formatting parameters (period, aggregation)

        Returns:
            Formatted tool costs response string
        """
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")

        if not data:
            return self.utilities.format_no_data_response(
                "tool costs", period, f"aggregation: {aggregation}"
            )

        display_data = []
        for item in data:
            if item.get("tool") == "DEBUG_INFO":
                if not self.production_mode:
                    display_data.append(item)
            else:
                display_data.append(item)

        if not display_data:
            return self.utilities.format_no_data_response(
                "tool costs", period, f"aggregation: {aggregation}"
            )

        return self._format_tool_costs_content(
            display_data, {"period": period, "aggregation": aggregation}
        )

    def _format_tool_costs_content(
        self, data: List[Dict[str, Any]], params: Dict[str, Any]
    ) -> str:
        """Format the main tool costs content with proper decomposition.

        Args:
            data: Tool cost data
            params: Parameters containing period and aggregation

        Returns:
            Formatted response content
        """
        header = self._format_tool_costs_header(data, params)
        table_content = self._format_tool_costs_table(data)
        footer = self._format_tool_costs_footer(params)

        return f"{header}\n\n{table_content}\n{footer}"

    def _format_tool_costs_header(
        self, data: List[Dict[str, Any]], params: Dict[str, Any]
    ) -> str:
        """Format header section for tool costs display.

        Args:
            data: Tool cost data for counting tools
            params: Parameters containing period and aggregation

        Returns:
            Formatted header section
        """
        timestamp = self.utilities.get_timestamp()
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")

        return f"""# **Tool Cost Analysis**

## **Analysis Summary**
- **Time Period**: {period}
- **Aggregation**: {aggregation}
- **Tools Found**: {len(data)}
- **Analysis Date**: {timestamp}

## **Tool Cost Ranking**
"""

    def _format_tool_costs_table(self, data: List[Dict[str, Any]]) -> str:
        """Format table section for tool costs data.

        Args:
            data: Tool cost data to format

        Returns:
            Formatted table section
        """
        table_content = ""

        for i, tool in enumerate(data, 1):
            tool_entry = self._format_single_tool_entry(tool, i)
            table_content += tool_entry

        return table_content

    def _format_single_tool_entry(self, tool: Dict[str, Any], index: int) -> str:
        """Format a single tool entry for the table.

        Args:
            tool: Single tool data
            index: Tool index for numbering

        Returns:
            Formatted tool entry
        """
        tool_name = tool.get("tool", "Unknown")

        # Handle debug information
        if tool_name == "DEBUG_INFO" and "debug" in tool:
            return self._format_debug_entry(tool)

        return self._format_regular_tool_entry(tool, index)

    def _format_debug_entry(self, tool: Dict[str, Any]) -> str:
        """Format debug information entry.

        Args:
            tool: Tool data containing debug info

        Returns:
            Formatted debug entry (non-production mode only)
        """
        if not self.production_mode:
            return f"## **DEBUG INFORMATION**\n\n**Debug Details**: {tool['debug']}\n\n"
        return ""

    def _format_regular_tool_entry(self, tool: Dict[str, Any], index: int) -> str:
        """Format a regular tool entry with cost and optional details.

        Args:
            tool: Tool data
            index: Tool index for numbering

        Returns:
            Formatted tool entry
        """
        # Resolve entity name from multiple possible keys
        entity_name = None
        for key in ("tool", "agent", "provider"):
            if key in tool:
                entity_name = tool[key]
                break
        if entity_name is None:
            entity_name = "Unknown"

        entry = f"**{index}. {entity_name}**\n"

        cost = tool.get("cost")
        if cost is not None and cost > 0:
            cost_formatted = self.utilities.format_currency(cost)
            entry += f"   - Cost: {cost_formatted}\n"

        if "percentage" in tool:
            entry += f"   - Share: {tool['percentage']:.1f}%\n"

        call_count = tool.get("call_count")
        if call_count is not None:
            entry += f"   - Invocations: {call_count}\n"

        return entry + "\n"

    def _format_tool_costs_footer(self, params: Dict[str, Any]) -> str:
        """Format footer section with insights.

        Args:
            params: Parameters containing period and aggregation

        Returns:
            Formatted footer section
        """
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")
        return self.utilities.add_insights_footer(
            "tool costs", period, f"{aggregation} aggregation"
        )
