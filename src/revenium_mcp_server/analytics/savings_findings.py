"""Coding-assistant savings: the request get_ai_assistant_savings sends and the report it reads back.

GET /api/v2/analytics/ai-assistants/savings-findings (operation
``get_savings_findings``) on the analytics host ranks what a team can save on
its coding assistants. The two levels answer different shapes: level=person
lists each saving with the people it comes from and is not paged;
level=department lists one row per top-level department, paged, and names
nobody. Both carry the platform's own totals, which are copied, never summed.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from .paging import PageInfo

DEPARTMENT_LEVEL = "department"
PERSON_LEVEL = "person"
SAVINGS_LEVELS = (DEPARTMENT_LEVEL, PERSON_LEVEL)
DEFAULT_SAVINGS_LEVEL = DEPARTMENT_LEVEL
DEFAULT_SAVINGS_PAGE = 0
DEFAULT_SAVINGS_SIZE = 20
SAVINGS_ASSISTANTS = ("claude-code", "claude-cowork", "codex-cli", "cursor-ide", "github-copilot")
DEPARTMENT_SETUP_READY = "READY"


@dataclass(frozen=True)
class SavingsFindingsQuery:
    """The validated get_ai_assistant_savings arguments."""

    level: str = DEFAULT_SAVINGS_LEVEL
    page: int = DEFAULT_SAVINGS_PAGE
    size: int = DEFAULT_SAVINGS_SIZE
    assistant: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    @property
    def is_paged(self) -> bool:
        return self.level == DEPARTMENT_LEVEL

    def request_params(self) -> Dict[str, Any]:
        """Query parameters beside the resolved team; page and size only where they apply."""
        params: Dict[str, Any] = {"level": self.level}
        if self.is_paged:
            params.update(page=self.page, size=self.size)
        optional = {"assistant": self.assistant, "startDate": self.start_date, "endDate": self.end_date}
        params.update({name: value for name, value in optional.items() if value is not None})
        return params


@dataclass(frozen=True)
class SavingsTotals:
    savings_money: Optional[str] = None
    spend_to_inspect_money: Optional[str] = None
    insights_money: Optional[str] = None
    complete: Optional[bool] = None
    assistants_counted: Optional[int] = None
    assistants_left_out: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class SkippedCheck:
    check_id: str
    status: str
    reason: Optional[str]


@dataclass(frozen=True)
class AssistantSavings:
    label: str
    savings_money: Optional[str]
    spend_to_inspect_money: Optional[str]
    skipped_checks: List[SkippedCheck]


@dataclass(frozen=True)
class PersonSaving:
    name: str
    monthly: Optional[float]
    who: List[str]


@dataclass(frozen=True)
class DepartmentFinding:
    title: str
    money: Optional[str]


@dataclass(frozen=True)
class DepartmentSaving:
    name: str
    monthly: Optional[float]
    findings: List[DepartmentFinding]


@dataclass(frozen=True)
class DepartmentLeftover:
    label: str
    savings_money: Optional[str]


@dataclass(frozen=True)
class SpendToInspect:
    headline: str
    money: Optional[str]
    who: List[str]


@dataclass(frozen=True)
class InsightItem:
    title: str
    money: Optional[str]


@dataclass(frozen=True)
class SavingsInsights:
    total_money: Optional[str]
    items: List[InsightItem]
    dashboard_url: Optional[str]


@dataclass(frozen=True)
class DepartmentBreakdown:
    rows: List[DepartmentSaving]
    leftovers: List[DepartmentLeftover]
    setup_status: Optional[str]
    setup_message: Optional[str]
    complete: Optional[bool]
    notes: List[str]
    paging: PageInfo


@dataclass(frozen=True)
class SavingsFindings:
    period_start: Optional[str]
    period_end: Optional[str]
    totals: SavingsTotals
    assistants: List[AssistantSavings]
    spend_to_inspect: List[SpendToInspect]
    insights: Optional[SavingsInsights]
    person_rows: List[PersonSaving]
    departments: Optional[DepartmentBreakdown]


def parse_savings_findings(envelope: Mapping[str, Any], level: str) -> SavingsFindings:
    """Read the flat analytics envelope; only the fields the answer renders are kept."""
    period = _mapping(envelope.get("period"))
    items = _mappings(_mapping(envelope.get("_embedded")).get("items"))
    is_department = level == DEPARTMENT_LEVEL
    return SavingsFindings(
        period_start=period.get("start"),
        period_end=period.get("end"),
        totals=_parse_totals(_mapping(envelope.get("totals"))),
        assistants=[_parse_assistant(item) for item in _mappings(envelope.get("assistants"))],
        spend_to_inspect=[_parse_spend(item) for item in _mappings(envelope.get("spendToInspect"))],
        insights=_parse_insights(envelope.get("insights")),
        person_rows=[] if is_department else [_parse_person_saving(item) for item in items],
        departments=_parse_departments(envelope, items) if is_department else None,
    )


def _parse_totals(totals: Mapping[str, Any]) -> SavingsTotals:
    return SavingsTotals(
        savings_money=_text(totals.get("savingsMoney")),
        spend_to_inspect_money=_text(totals.get("spendToInspectMoney")),
        insights_money=_text(totals.get("insightsMoney")),
        complete=totals.get("complete") if isinstance(totals.get("complete"), bool) else None,
        assistants_counted=_whole_number(totals.get("assistantsCounted")),
        assistants_left_out=_strings(totals.get("assistantsLeftOut")),
    )


def _parse_assistant(item: Mapping[str, Any]) -> AssistantSavings:
    skipped = [
        SkippedCheck(str(check.get("id")), str(check.get("status")), _text(check.get("reason")))
        for check in _mappings(item.get("checks"))
        if check.get("status") in ("not_checked", "failed")
    ]
    return AssistantSavings(
        label=str(item.get("label") or item.get("assistant") or "Unnamed assistant"),
        savings_money=_text(item.get("savingsMoney")),
        spend_to_inspect_money=_text(item.get("spendToInspectMoney")),
        skipped_checks=skipped,
    )


def _parse_person_saving(item: Mapping[str, Any]) -> PersonSaving:
    return PersonSaving(
        name=str(item.get("groupName") or item.get("checkId") or "Unnamed saving"),
        monthly=_monthly_saving(item),
        who=_strings(item.get("who")),
    )


def _parse_departments(envelope: Mapping[str, Any], items: List[Mapping[str, Any]]) -> DepartmentBreakdown:
    setup = _mapping(envelope.get("departmentSetup"))
    complete = envelope.get("departmentsComplete")
    return DepartmentBreakdown(
        rows=[_parse_department_saving(item) for item in items],
        leftovers=[
            DepartmentLeftover(str(item.get("label") or item.get("kind")), _text(item.get("savingsMoney")))
            for item in _mappings(envelope.get("departmentLeftovers"))
        ],
        setup_status=_text(setup.get("status")),
        setup_message=_text(setup.get("message")),
        complete=complete if isinstance(complete, bool) else None,
        notes=_strings(envelope.get("departmentNotes")),
        paging=PageInfo.from_envelope(envelope),
    )


def _parse_department_saving(item: Mapping[str, Any]) -> DepartmentSaving:
    return DepartmentSaving(
        name=str(item.get("groupName") or item.get("departmentId") or "Unnamed department"),
        monthly=_monthly_saving(item),
        findings=[
            DepartmentFinding(str(finding.get("title") or finding.get("checkId")), _text(finding.get("money")))
            for finding in _mappings(item.get("findings"))
        ],
    )


def _parse_spend(item: Mapping[str, Any]) -> SpendToInspect:
    return SpendToInspect(
        headline=str(item.get("headline") or item.get("check") or "Unnamed spend"),
        money=_text(item.get("money")),
        who=_strings(item.get("who")),
    )


def _parse_insights(value: Any) -> Optional[SavingsInsights]:
    if not isinstance(value, Mapping):
        return None
    return SavingsInsights(
        total_money=_text(value.get("totalMoney")),
        items=[
            InsightItem(str(item.get("title") or "Untitled"), _text(item.get("money")))
            for item in _mappings(value.get("items"))
        ],
        dashboard_url=_text(value.get("dashboardUrl")),
    )


def _monthly_saving(item: Mapping[str, Any]) -> Optional[float]:
    for metric in _mappings(item.get("metrics")):
        if metric.get("metricType") == "SAVING_COST_MONTHLY":
            return _number(metric.get("metricResult"))
    return None


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _whole_number(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)


def _text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _strings(value: Any) -> List[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mappings(value: Any) -> List[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []
