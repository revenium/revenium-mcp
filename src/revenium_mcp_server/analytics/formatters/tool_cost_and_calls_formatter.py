"""Tool cost and call volume response formatter (get_tool_cost_and_call_volume)."""

from datetime import datetime, timezone
from typing import List, Tuple

from ...analytics_window import AnalyticsWindow, CalendarRange
from ...common.one_line import one_line
from ..paging import counted, pagination_lines, past_last_page_sentence
from ..tool_cost_and_calls import ToolCostAndCalls, ToolCostAndCallsPage
from .base_formatter import BaseFormattingUtilities

TITLE = "Tool Cost and Call Volume"
RANKING_NOTE = (
    "Ranked by total cost, then by call count. A tool with only one of the two "
    "figures is listed, and the other is marked not reported, never zero."
)
NAMES_NOTE = (
    "**Names**: a tool whose display name another tool also uses is listed under "
    "its tool id."
)
COST_NOT_REPORTED = "not reported (the platform has calls but no cost for this tool in the window)"
CALLS_NOT_REPORTED = "not reported (the platform has a cost but no calls for this tool in the window)"
NEITHER_REPORTED = "not reported (the platform sent no figure this tool can read for this row)"
MOVING_WINDOW_NOTE = (
    "**Paging**: a period window ends at the time of each read, so calls made between "
    "page reads can move a tool onto another page, where it is read twice or missed. "
    "start_date and end_date (yyyy-MM-dd, whole UTC days) name the same window on every "
    "read: to page through a window that no longer takes in new calls, pass a range that "
    "ends before today in place of period and start again at page=0."
)
OPEN_RANGE_NOTE = (
    "**Paging**: this range includes today, so calls made between page reads can move a "
    "tool onto another page, where it is read twice or missed. To page through a window "
    "that no longer takes in new calls, pass an end_date before today and start again at "
    "page=0."
)


ALTERED_TOOL_ID_NOTE = (
    "(shown on one line; the stored id holds line breaks, repeated spaces or control "
    "characters, so it cannot be copied from here)"
)


def _shown_tool_id(tool_id: str) -> str:
    """The stored id when it fits one line as it is, else flattened and marked as altered."""
    flattened = one_line(tool_id, len(tool_id))
    return tool_id if flattened == tool_id else f"{flattened} {ALTERED_TOOL_ID_NOTE}"


class ToolCostAndCallsFormatter:
    """Render one page of tools so a missing figure never reads as zero."""

    def __init__(self) -> None:
        self.utilities = BaseFormattingUtilities()

    def format(self, page: ToolCostAndCallsPage, asked: AnalyticsWindow) -> str:
        if page.tools:
            return self._format_tools(page, asked)
        if page.paging.total_elements:
            return self._format_past_last_page(page, page.paging.total_elements, asked)
        return self.utilities.format_no_data_response(
            "tool cost and call volume", str(page.window), "ranked by cost, then call count"
        )

    def _format_tools(self, page: ToolCostAndCallsPage, asked: AnalyticsWindow) -> str:
        lines = self._header(page)
        lines += ["## **Tools**", ""]
        first_index = page.paging.first_index
        for offset, tool in enumerate(page.tools):
            lines += self._tool_lines(tool, first_index + offset)
        lines += pagination_lines(page.paging, "tool", "tools", _window_arguments(asked))
        if page.paging.spans_several_pages:
            lines += _moving_window_lines(asked)
        lines += ["", NAMES_NOTE]
        return "\n".join(lines)

    def _format_past_last_page(
        self, page: ToolCostAndCallsPage, total_elements: int, asked: AnalyticsWindow
    ) -> str:
        lines = self._header(page)
        lines += [
            "## Page past the last one",
            "",
            past_last_page_sentence(
                page.paging, counted(total_elements, "tool", "tools"), _window_arguments(asked)
            ),
        ]
        return "\n".join(lines)

    def _header(self, page: ToolCostAndCallsPage) -> List[str]:
        return [
            f"# **{TITLE}**",
            "",
            f"- **Time Period**: {page.window}",
            f"- **Analysis Date**: {self.utilities.get_timestamp()}",
            "",
            RANKING_NOTE,
            "",
        ]

    def _tool_lines(self, tool: ToolCostAndCalls, index: int) -> List[str]:
        cost, calls = self._figures(tool)
        return [
            f"**{index}. {tool.tool_name}**",
            f"   - Tool ID: {_shown_tool_id(tool.tool_id)}",
            f"   - Total cost: {cost}",
            f"   - Calls: {calls}",
            "",
        ]

    def _figures(self, tool: ToolCostAndCalls) -> Tuple[str, str]:
        if tool.cost is None and tool.calls is None:
            return NEITHER_REPORTED, NEITHER_REPORTED
        cost = COST_NOT_REPORTED if tool.cost is None else self.utilities.format_currency(tool.cost)
        calls = CALLS_NOT_REPORTED if tool.calls is None else f"{tool.calls:,.0f}"
        return cost, calls


def _moving_window_lines(asked: AnalyticsWindow) -> List[str]:
    if isinstance(asked, str):
        return ["", MOVING_WINDOW_NOTE]
    if isinstance(asked, CalendarRange) and asked.end >= datetime.now(timezone.utc).date():
        return ["", OPEN_RANGE_NOTE]
    return []


def _window_arguments(asked: AnalyticsWindow) -> str:
    """The window as arguments this action accepts; nothing for a window it has no argument for."""
    if isinstance(asked, str):
        return f"period={asked}"
    if isinstance(asked, CalendarRange):
        return f"start_date={asked.start.isoformat()} end_date={asked.end.isoformat()}"
    return ""
