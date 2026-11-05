"""Coding-assistant savings response formatter (get_ai_assistant_savings)."""

from typing import List, Optional

from ...client import ReveniumAPIError
from ..paging import counted, pagination_lines, past_last_page_sentence
from ..savings_findings import (
    DEPARTMENT_LEVEL,
    DEPARTMENT_SETUP_READY,
    DepartmentBreakdown,
    SavingsFindings,
    SavingsFindingsQuery,
    SavingsTotals,
)

# The documented shape has one person-level row per assistant and check, which
# the spec's enums bound at 55, so 50 shows the whole answer in practice while
# still bounding a list the platform does not page.
PERSON_ROWS_SHOWN = 50

SAVINGS_NOT_ENABLED_MESSAGE = (
    "Coding-assistant savings findings are not enabled for this team (the feature is "
    "not yet enabled in every region), so the platform has no savings to report here. "
    "This is not a zero saving: there is nothing to read until it is enabled."
)
ASSISTANT_NOT_ENABLED_NOTE = (
    "The assistant named is not enabled for this team. Call again without assistant "
    "to read every assistant the team has enabled."
)
SAVINGS_UNAVAILABLE_MESSAGE = (
    "Coding-assistant savings findings are unavailable right now: the platform could "
    "not read them in time. This is not a zero saving and not a sign the feature is "
    "off. Try again later."
)
METERING_KEY_REFUSED_NOTE = (
    "The platform does not answer this read for an API key with metering scope. Connect "
    "with a user sign-in (OAuth) or a key without metering scope."
)
NO_FINDINGS_RIGHT_NOW_NOTE = (
    "No findings right now: this is not a zero saving. Try again later."
)
TOTALS_NOTE = (
    "These totals are the platform's own figures: copy them, never add the rows below "
    "up to get them."
)
DEPARTMENT_FLOOR_NOTE = (
    "Each department's figure is a monthly floor ranked by its own amount; department "
    "figures do not add up to the totals above."
)
INCOMPLETE_TOTALS_NOTE = (
    "Some checks could not run (marked failed below), so these totals are incomplete."
)
DEPARTMENTS_INCOMPLETE_NOTE = (
    "The platform could not attribute every saving to a department, so the department "
    "rows are incomplete."
)
DEPARTMENTS_UNAVAILABLE_NOTE = (
    "No department breakdown is available, which is not a zero saving: the totals above "
    "still apply. Pass level=person for the savings by person."
)
NOT_PAGED_NOTE = "page and size do not apply at level=person: the platform returns every row at once."
MISSING = "n/a"


class SavingsFindingsFormatter:
    """Render the savings report with the platform's totals and a bounded person list."""

    def format(self, findings: SavingsFindings, query: SavingsFindingsQuery) -> str:
        lines = self._header(findings, query) + self._totals(findings.totals)
        lines += self._assistants(findings)
        if query.level == DEPARTMENT_LEVEL and findings.departments is not None:
            lines += self._departments(findings.departments)
        else:
            lines += self._person_rows(findings)
        lines += self._spend_to_inspect(findings) + self._insights(findings)
        return "\n".join(lines)

    def format_failure(self, error: ReveniumAPIError, query: SavingsFindingsQuery) -> str:
        message = str(error.message).lower()
        if error.status_code == 403 and "not enabled" in message:
            lines = ["**Coding-Assistant Savings Not Enabled**", "", SAVINGS_NOT_ENABLED_MESSAGE]
            if query.assistant and "assistant" in message:
                lines += ["", ASSISTANT_NOT_ENABLED_NOTE]
            return "\n".join(lines)
        if error.status_code == 503:
            return "\n".join(["**Coding-Assistant Savings Unavailable**", "", SAVINGS_UNAVAILABLE_MESSAGE])
        lines = ["**Coding-Assistant Savings Failed**", "", f"**API Error**: {error.message}"]
        if error.status_code:
            lines.append(f"**Status Code**: {error.status_code}")
        if error.status_code == 403 and "metering scope" in message:
            lines += ["", METERING_KEY_REFUSED_NOTE]
        elif error.status_code == 429 or (isinstance(error.status_code, int) and error.status_code >= 500):
            lines += ["", NO_FINDINGS_RIGHT_NOW_NOTE]
        return "\n".join(lines)

    @staticmethod
    def _header(findings: SavingsFindings, query: SavingsFindingsQuery) -> List[str]:
        scope = "by department" if query.level == DEPARTMENT_LEVEL else "by person"
        assistant = f", {query.assistant} only" if query.assistant else ""
        lines = [f"**Coding-assistant savings findings ({scope}{assistant})**", ""]
        if findings.period_start and findings.period_end:
            lines += [f"**Window**: {findings.period_start} to {findings.period_end}", ""]
        return lines

    @staticmethod
    def _totals(totals: SavingsTotals) -> List[str]:
        lines = [
            "**Totals**",
            TOTALS_NOTE,
            f"- Savings a month: {totals.savings_money or MISSING}",
            f"- Spend to inspect a month: {totals.spend_to_inspect_money or MISSING}",
            f"- AI Insights savings: {totals.insights_money or MISSING}",
        ]
        if totals.assistants_counted is not None:
            lines.append(f"- Assistants counted: {totals.assistants_counted}")
        if totals.assistants_left_out:
            lines.append(f"- Assistants left out: {', '.join(totals.assistants_left_out)}")
        if totals.complete is False:
            lines.append(INCOMPLETE_TOTALS_NOTE)
        return lines + [""]

    @staticmethod
    def _assistants(findings: SavingsFindings) -> List[str]:
        if not findings.assistants:
            return []
        lines = ["**By assistant**"]
        for assistant in findings.assistants:
            lines.append(
                f"- {assistant.label}: savings {assistant.savings_money or MISSING} a month, "
                f"spend to inspect {assistant.spend_to_inspect_money or MISSING}"
            )
            lines += [
                f"  - {check.check_id} {check.status.replace('_', ' ')}"
                + (f": {check.reason}" if check.reason else "")
                for check in assistant.skipped_checks
            ]
        return lines + [""]

    def _person_rows(self, findings: SavingsFindings) -> List[str]:
        rows = findings.person_rows
        lines = ["**Savings, largest first**", NOT_PAGED_NOTE]
        if not rows:
            return lines + ["The platform found no savings rows in this window.", ""]
        shown = rows[:PERSON_ROWS_SHOWN]
        for index, row in enumerate(shown, start=1):
            who = f" (from {', '.join(row.who)})" if row.who else ""
            lines.append(f"{index}. {row.name}: {self._monthly(row.monthly)}{who}")
        omitted = len(rows) - len(shown)
        if omitted:
            lines.append(
                f"Showing the first {PERSON_ROWS_SHOWN} of {len(rows)} rows: "
                f"{counted(omitted, 'smaller row is', 'smaller rows are')} not shown. "
                "The totals above still cover every row. Pass assistant to narrow the "
                "list, or level=department for a paged view."
            )
        return lines + [""]

    def _departments(self, departments: DepartmentBreakdown) -> List[str]:
        lines = ["**By department**"]
        if departments.setup_status and departments.setup_status != DEPARTMENT_SETUP_READY:
            setup = departments.setup_message or f"Department setup is {departments.setup_status}."
            return lines + [setup, DEPARTMENTS_UNAVAILABLE_NOTE, ""]
        lines.append(DEPARTMENT_FLOOR_NOTE)
        lines += self._department_rows(departments)
        if departments.leftovers:
            lines.append("**Outside the ranked departments**")
            lines += [
                f"- {leftover.label}: {leftover.savings_money or MISSING} a month"
                for leftover in departments.leftovers
            ]
        if departments.complete is False:
            lines.append(DEPARTMENTS_INCOMPLETE_NOTE)
        lines += [f"- {note}" for note in departments.notes]
        return lines + pagination_lines(departments.paging, "department", "departments") + [""]

    def _department_rows(self, departments: DepartmentBreakdown) -> List[str]:
        paging = departments.paging
        if not departments.rows:
            total = paging.total_elements or 0
            if total and paging.number:
                return [past_last_page_sentence(paging, counted(total, "department", "departments"))]
            return ["No department has a saving in this window."]
        lines: List[str] = []
        for index, row in enumerate(departments.rows, start=paging.first_index):
            lines.append(f"{index}. {row.name}: {self._monthly(row.monthly)}")
            lines += [f"   - {finding.title}: {finding.money or MISSING}" for finding in row.findings]
        return lines

    @staticmethod
    def _spend_to_inspect(findings: SavingsFindings) -> List[str]:
        if not findings.spend_to_inspect:
            return []
        lines = ["**Spend to inspect**"]
        for item in findings.spend_to_inspect:
            who = f" (from {', '.join(item.who)})" if item.who else ""
            lines.append(f"- {item.headline}: {item.money or MISSING}{who}")
        return lines + [""]

    @staticmethod
    def _insights(findings: SavingsFindings) -> List[str]:
        insights = findings.insights
        if insights is None:
            return []
        lines = [f"**Latest AI Insights savings**: {insights.total_money or MISSING}"]
        lines += [f"- {item.title}: {item.money or MISSING}" for item in insights.items]
        if insights.dashboard_url:
            lines.append(f"Open in Revenium: {insights.dashboard_url}")
        return lines

    @staticmethod
    def _monthly(value: Optional[float]) -> str:
        return MISSING if value is None else f"${value:,.0f} a month"
