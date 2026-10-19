"""The tool analytics reports: the filters each operation declares, and the window a report is asked for.

Free of the analytics package so ``tools_decomposed.tool_management`` can import
it at module level; the paged read itself is ``analytics.tool_reports.read_tool_report``.
"""

from dataclasses import dataclass, field
from typing import Dict, Mapping

from .analytics_parameters import TimePeriod

from .analytics_window import AnalyticsWindow
from .endpoint_registry import window_bounds


@dataclass(frozen=True)
class ToolReport:
    """One tool analytics endpoint: the client method that reads it and the filters its operation declares.

    ``filters`` maps the caller's argument name to the query parameter the
    isotope operation declares (``specs/openapi/isotope.json``). Every report
    also takes startDate, endDate, page and size, which ``read_tool_report`` sets.
    """

    client_method: str
    filters: Mapping[str, str] = field(default_factory=dict)


COST_BY_TOOL = ToolReport("get_cost_by_tool", {"tool_id": "toolIds"})
COST_BY_TOOL_AGGREGATED = ToolReport("get_cost_by_tool_aggregated")
COST_BY_TOOL_AGENT = ToolReport("get_cost_by_tool_agent")
AGENT_TOOL_BREAKDOWN = ToolReport("get_agent_tool_breakdown")
COST_BY_TOOL_PROVIDER = ToolReport("get_cost_by_tool_provider", {"provider": "providers"})
COST_BY_TOOL_PROVIDER_AGGREGATED = ToolReport("get_cost_by_tool_provider_aggregated")
TOP_TOOLS_BY_CALL_COUNT = ToolReport("get_top_tools_by_call_count")
TOOL_SUCCESS_RATE = ToolReport("get_tool_success_rate")
TOOL_LATENCY = ToolReport("get_tool_latency")

PLATFORM_DEFAULT_PERIOD = TimePeriod.TWENTY_FOUR_HOURS.value


@dataclass(frozen=True)
class ToolReportWindow:
    """The startDate and endDate a tool report is asked for."""

    start: str
    end: str
    label: str = ""

    @classmethod
    def of(cls, window: AnalyticsWindow) -> "ToolReportWindow":
        start, end = window_bounds(window)
        return cls(start, end, label=str(window))

    @classmethod
    def platform_default(cls) -> "ToolReportWindow":
        """The window the platform answers for when no dates are sent, pinned so every page shares it."""
        start, end = window_bounds(PLATFORM_DEFAULT_PERIOD)
        return cls(start, end, label=f"{PLATFORM_DEFAULT_PERIOD}, the platform default")

    def params(self) -> Dict[str, str]:
        return {"startDate": self.start, "endDate": self.end}

    def __str__(self) -> str:
        bounds = f"{self.start} to {self.end}"
        return f"{self.label}: {bounds}" if self.label else bounds

