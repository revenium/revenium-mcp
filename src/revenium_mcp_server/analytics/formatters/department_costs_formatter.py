"""Department costs response formatter (get_department_costs)."""

import json
from typing import List, Optional

from ..department_costs import (
    DEPARTMENT_COSTS_ENDPOINT_KEY,
    DepartmentCostsPage,
    DepartmentCostsQuery,
    DepartmentFigures,
    DepartmentGroup,
)
from ..validation import DEFAULT_USER_COST_SOURCES
from .base_formatter import BaseFormattingUtilities

USAGE_UNASSIGNED = "USAGE_UNASSIGNED"

_SPEND_PER_PERSON_POINTER = "get_user_costs reports the same spend per person."
NO_GROUPING_EXPLANATIONS = {
    "NO_DEPARTMENTS": (
        "The team has no departments, so there is nothing to group spend by. "
        + _SPEND_PER_PERSON_POINTER
    ),
    "NO_ASSIGNMENTS": (
        "Departments exist but nobody is assigned to one, so there is nothing to "
        "group spend by. " + _SPEND_PER_PERSON_POINTER
    ),
    "DATA_NOT_LOADED": (
        "None of this team's calls are in this environment yet: its copy of the call "
        "data is still loading, or the team has sent none."
    ),
}
NOT_ZERO_SPEND_NOTE = (
    "This is not $0 of spend: the answer holds no department groups at all, and no "
    "figure here should be read as zero."
)
USAGE_UNASSIGNED_NOTE = (
    "None of the usage this report covers (the period, narrowed by any filter) is "
    "from someone assigned to a department, so all of it is in the No department "
    "assigned group."
)
HASHID_NOTE = (
    "**Department ids**: departmentId and parentDepartmentId are hashids. They are "
    "not the numeric department ids manage_customers list_departments returns (the "
    "ids get_pr_health department_id takes): never pass one kind where the other "
    "is expected."
)
SCOPE_LABELS_NOTE = (
    "**Own vs with sub-departments**: Own counts the calls of people in that "
    "department only. With sub-departments adds every sub-department under it, so "
    "a sub-department's spend appears in its own group and again in each parent's: "
    "never add the with-sub-departments figures across groups."
)
OWN_SUMS_TO_USER_COSTS_NOTE = (
    "With aggregation TOTAL the Own figures of every group, No department assigned "
    "included, add up to get_user_costs for the same period and filters."
)
ATTRIBUTION_NOTE = (
    "**Attribution**: each call counts in the department its person was in when the "
    "call was made, so moving someone never changes past figures. Calls that name "
    "no person are in no group."
)
COST_SOURCES_NOTE = (
    "**Cost sources**: unless you pass filters.costSources this report counts "
    f"{json.dumps(list(DEFAULT_USER_COST_SOURCES))}, the same default as "
    "get_user_costs."
)
UNASSIGNED_LABEL = "No department assigned"
# Only a sum of requests or tokens is a whole number; an average, maximum or
# minimum per call can be fractional and must not be rounded to look like one.
WHOLE_COUNT_AGGREGATION = "TOTAL"
MISSING_FIGURE = "n/a"


class DepartmentCostsFormatter:
    """Render a DepartmentCostsPage so an empty grouping never reads as $0."""

    def __init__(self) -> None:
        self.utilities = BaseFormattingUtilities()

    def format(self, page: DepartmentCostsPage, query: DepartmentCostsQuery) -> str:
        status = page.setup.status
        if status in NO_GROUPING_EXPLANATIONS:
            return self._format_no_grouping(page, query, status)
        if not page.groups and page.total_elements:
            return self._format_past_last_page(page, query, page.total_elements)
        if not page.groups:
            return self._format_no_groups(page, query)
        return self._format_groups(page, query)

    def _format_no_grouping(
        self, page: DepartmentCostsPage, query: DepartmentCostsQuery, status: str
    ) -> str:
        lines = self._header(page, query)
        lines += [
            f"## No department grouping (departmentSetup {status})",
            "",
            NO_GROUPING_EXPLANATIONS[status],
            "",
            NOT_ZERO_SPEND_NOTE,
        ]
        lines += self._platform_setup_lines(page)
        return "\n".join(lines)

    def _format_past_last_page(
        self, page: DepartmentCostsPage, query: DepartmentCostsQuery, total_elements: int
    ) -> str:
        total_pages = max(page.total_pages or 1, 1)
        requested = "" if page.page_number is None else f" (page={page.page_number})"
        size = self._size_hint(page)
        lines = self._header(page, query)
        lines += [
            "## Page past the last one",
            "",
            f"The report has {total_elements} department groups on {total_pages} "
            f"page{'s' if total_pages != 1 else ''}, and the page requested{requested} "
            f"is past the last. Pass page={total_pages - 1}{size} for the last page, or "
            f"page=0{size} for the first.",
        ]
        return "\n".join(lines)

    def _format_no_groups(self, page: DepartmentCostsPage, query: DepartmentCostsQuery) -> str:
        lines = self._header(page, query)
        lines += [
            "## No department groups returned",
            "",
            "The platform returned no department groups for this period and these "
            "filters. That is the boundary of this dataset, not a statement that "
            "nobody used AI: a short period or narrow filters can leave it empty.",
        ]
        lines += self._platform_setup_lines(page)
        lines += ["", self._scope_notes(query)]
        return "\n".join(lines)

    def _format_groups(self, page: DepartmentCostsPage, query: DepartmentCostsQuery) -> str:
        lines = self._header(page, query)
        if page.setup.status == USAGE_UNASSIGNED:
            lines += [USAGE_UNASSIGNED_NOTE, ""]
        lines += ["## Departments", ""]
        first_index = self._first_index(page)
        whole_counts = query.aggregation == WHOLE_COUNT_AGGREGATION
        for offset, group in enumerate(page.groups):
            lines += self._group_lines(group, first_index + offset, whole_counts)
        lines += self._pagination_lines(page)
        lines += ["", self._scope_notes(query)]
        return "\n".join(lines)

    def _header(self, page: DepartmentCostsPage, query: DepartmentCostsQuery) -> List[str]:
        window = query.period
        if page.period_start and page.period_end:
            window = f"{page.period_start} to {page.period_end} ({query.period})"
        return [
            "# Cost by Department",
            "",
            f"- **Period**: {window}",
            f"- **Aggregation**: {query.aggregation} (metricType {query.metric_type})",
            f"- **Department setup**: {page.setup.status or 'not reported'}",
            "",
        ]

    def _group_lines(
        self, group: DepartmentGroup, index: int, whole_counts: bool
    ) -> List[str]:
        if group.is_unassigned:
            return [
                f"**{index}. {UNASSIGNED_LABEL}**",
                "   - departmentId: unassigned (spend from people with no department "
                "when the call was made)",
                f"   - Own: {self._figures(group.own, whole_counts)}",
                "",
            ]
        return [
            f"**{index}. {group.name}**",
            f"   - departmentId (hashid): {group.department_id}",
            f"   - Parent: {self._parent(group.parent_department_id)}",
            f"   - Own (this department only): {self._figures(group.own, whole_counts)}",
            "   - With sub-departments (this department and every sub-department): "
            f"{self._figures(group.with_subdepartments, whole_counts)}",
            "",
        ]

    @staticmethod
    def _parent(parent_department_id: Optional[str]) -> str:
        if not parent_department_id:
            return "none (a top-level department)"
        return f"parentDepartmentId (hashid) {parent_department_id}"

    def _figures(self, figures: DepartmentFigures, whole_counts: bool) -> str:
        cost = (
            MISSING_FIGURE
            if figures.cost is None
            else self.utilities.format_currency(figures.cost)
        )
        return (
            f"cost {cost}, requests {self._count(figures.requests, whole_counts)}, "
            f"tokens {self._tokens(figures.tokens, whole_counts)}"
        )

    @staticmethod
    def _count(value: Optional[float], whole_counts: bool) -> str:
        if value is None:
            return MISSING_FIGURE
        return f"{value:,.0f}" if whole_counts else f"{value:,.2f}"

    @classmethod
    def _tokens(cls, value: Optional[float], whole_counts: bool) -> str:
        if value is None:
            return MISSING_FIGURE
        if value >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        if value >= 1_000:
            return f"{value / 1_000:.1f}K"
        return cls._count(value, whole_counts)

    @staticmethod
    def _first_index(page: DepartmentCostsPage) -> int:
        if page.page_number and page.page_size:
            return page.page_number * page.page_size + 1
        return 1

    @staticmethod
    def _pagination_lines(page: DepartmentCostsPage) -> List[str]:
        if page.total_pages is None or page.page_number is None:
            return []
        lines = [
            f"Page {page.page_number + 1} of {max(page.total_pages, 1)}, "
            f"{page.total_elements if page.total_elements is not None else 'unknown'} "
            "groups in all."
        ]
        if page.page_number + 1 < page.total_pages:
            size = DepartmentCostsFormatter._size_hint(page)
            lines.append(f"Pass page={page.page_number + 1}{size} for the next page.")
        return lines

    @staticmethod
    def _size_hint(page: DepartmentCostsPage) -> str:
        return f" size={page.page_size}" if page.page_size else ""

    @staticmethod
    def _platform_setup_lines(page: DepartmentCostsPage) -> List[str]:
        lines: List[str] = []
        if page.setup.message:
            lines += ["", f"Platform message: {page.setup.message}"]
        if page.setup.setup_url:
            lines += [f"Set up departments: {page.setup.setup_url}"]
        return lines

    def _scope_notes(self, query: DepartmentCostsQuery) -> str:
        scope = SCOPE_LABELS_NOTE
        if query.aggregation == "TOTAL":
            scope = f"{scope} {OWN_SUMS_TO_USER_COSTS_NOTE}"
        return "\n\n".join(
            [
                HASHID_NOTE,
                scope,
                ATTRIBUTION_NOTE,
                COST_SOURCES_NOTE,
                self.utilities.coding_assistant_scope_note(DEPARTMENT_COSTS_ENDPOINT_KEY),
            ]
        )
