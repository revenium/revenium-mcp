"""Tool cost and call volume: the page get_tool_cost_and_call_volume reads back.

GET /api/v2/analytics/tool-cost-and-call-volume (operation
``get_tool_cost_and_call_volume``) on the analytics host answers one group per
tool over the whole window: ``groupName`` is the tool id, ``toolName`` its
display name (the tool id when two tools share a name), and ``metrics`` holds
the total cost and the call count, each named by its ``metricType``. A tool
with only one of the two has the other left out, so a missing figure is None
here, never zero. The platform ranks the tools by cost, then calls, and pages
them. Every answer carries ``_embedded.items``, an empty list on a page with no
tools, so a body without that list is not a page of tools.
"""

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional

from ..common.one_line import one_line
from ..tool_analytics_reports import ToolReportWindow
from .paging import PageInfo

TOOL_COST_AND_CALL_VOLUME_ACTION = "get_tool_cost_and_call_volume"

TOOL_COST_AND_CALLS_DEFAULT_PAGE_SIZE = 20

COST_METRIC_TYPE = "COST_METRIC_BY_TOOL"
CALLS_METRIC_TYPE = "TOP_TOOLS_BY_CALL_COUNT"

UNEXPECTED_BODY = (
    "The analytics service answered with a body that is not a page of tools "
    "(no _embedded.items list of tools), so nothing can be reported for this read."
)


_TOOL_NAME_MAX_LENGTH = 100


class UnexpectedToolCostAndCallsBody(ValueError):
    """The analytics service answered with something other than a page of tools."""


@dataclass(frozen=True)
class ToolCostAndCalls:
    tool_id: str
    tool_name: str
    cost: Optional[float]
    calls: Optional[float]


@dataclass(frozen=True)
class ToolCostAndCallsPage:
    tools: List[ToolCostAndCalls]
    window: ToolReportWindow
    paging: PageInfo


def parse_tool_cost_and_calls(envelope: Any, window: ToolReportWindow) -> ToolCostAndCallsPage:
    """Read the full analytics envelope (not the HAL-unwrapped item list).

    Raises:
        UnexpectedToolCostAndCallsBody: If the body is not a page of tools
    """
    return ToolCostAndCallsPage(
        tools=[_parse_tool(item) for item in _tool_items(envelope)],
        window=window,
        paging=PageInfo.from_envelope(envelope),
    )


def _tool_items(envelope: Any) -> List[Mapping[str, Any]]:
    embedded = envelope.get("_embedded") if isinstance(envelope, Mapping) else None
    items = embedded.get("items") if isinstance(embedded, Mapping) else None
    if not isinstance(items, list) or not all(isinstance(item, Mapping) for item in items):
        raise UnexpectedToolCostAndCallsBody(UNEXPECTED_BODY)
    return items


def _parse_tool(item: Mapping[str, Any]) -> ToolCostAndCalls:
    by_type = {
        metric.get("metricType"): metric.get("metricResult")
        for metric in item.get("metrics") or []
        if isinstance(metric, Mapping)
    }
    tool_id = str(item.get("groupName") or "")
    return ToolCostAndCalls(
        tool_id=tool_id,
        tool_name=one_line(item.get("toolName") or "", _TOOL_NAME_MAX_LENGTH)
        or one_line(tool_id, _TOOL_NAME_MAX_LENGTH),
        cost=_number(by_type.get(COST_METRIC_TYPE)),
        calls=_number(by_type.get(CALLS_METRIC_TYPE)),
    )


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
