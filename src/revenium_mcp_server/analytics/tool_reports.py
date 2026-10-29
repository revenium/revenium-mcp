"""Reading a tool analytics report: every page of it, for the window it is asked for.

Both ``get_business_analytics`` (the four tool cost actions) and
``manage_tools`` (its tool analytics actions) read these reports through
``read_tool_report``, so they share the paging, the pinned platform default
and the step from a ``ToolReportWindow`` to startDate/endDate. Each tool parses
the caller's window itself: ``get_business_analytics`` through
``AnalyticsValidator.validate_window`` (a yyyy-MM-dd ``CalendarRange`` or a
``SupportedPeriod``), ``manage_tools`` through ``capped_utc_instant_bounds``
(yyyy-MM-dd days or ISO-8601 instants, read as ``utc_instant_bounds`` reads
them) or a ``TimePeriod``. Both refuse a range longer than
``CALENDAR_RANGE_MAX_DAYS``.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from ..tool_analytics_reports import ToolReport, ToolReportWindow
from .envelope_reads import ENVELOPE_PAGE_SIZE, UnreadPages, envelope_items, read_every_page


@dataclass(frozen=True)
class ToolReportRead:
    """A tool report with every page's rows, the window it was asked for, and what was left unread."""

    envelope: Dict[str, Any]
    window: ToolReportWindow
    unread: Optional[UnreadPages] = None

    @property
    def items(self) -> List[Dict[str, Any]]:
        return envelope_items(self.envelope)


async def read_tool_report(
    client: Any,
    report: ToolReport,
    window: Optional[ToolReportWindow],
    filters: Optional[Mapping[str, Any]] = None,
) -> ToolReportRead:
    """Read every page of ``report`` for ``window``, or for the platform's default window when none is asked.

    ``filters`` are already under the platform's names. The merged envelope
    drops the first page's ``page`` block, which would otherwise describe
    page 0 of a report this read holds whole.
    """
    read_window = window or ToolReportWindow.platform_default()
    params: Dict[str, Any] = {**(filters or {}), **read_window.params(), "size": ENVELOPE_PAGE_SIZE}
    fetch = getattr(client, report.client_method)

    async def fetch_page(page_params: Dict[str, Any]) -> Dict[str, Any]:
        page = await fetch(**page_params)
        return page if isinstance(page, dict) else {}

    read = await read_every_page(report.client_method, fetch_page, params)
    envelope = {key: value for key, value in read.envelope.items() if key != "page"}
    return ToolReportRead(envelope, read_window, read.unread)
