"""Cost by department: the request get_department_costs sends and the report it reads back.

GET /api/v2/analytics/cost-by-department-aggregated (operation
``get_cost_by_department_aggregated``) on the analytics host groups the same
spend cost-by-user-aggregated reports by the department each call's person was
in when the call was made.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from .validation import DEFAULT_USER_COST_SOURCES

DEPARTMENT_COSTS_ENDPOINT_KEY = "cost_metric_by_department_aggregated"

UNASSIGNED_DEPARTMENT_ID = "unassigned"

METRIC_TYPE_BY_AGGREGATION: Mapping[str, str] = {
    "TOTAL": "sum",
    "MEAN": "avg",
    "MAXIMUM": "max",
    "MINIMUM": "min",
}

_OWN_METRIC_TYPES = {
    "cost": "COST_METRIC_BY_DEPARTMENT",
    "requests": "REQUEST_METRIC_BY_DEPARTMENT",
    "tokens": "TOKEN_METRIC_BY_DEPARTMENT",
}
_WITH_SUBDEPARTMENTS_SUFFIX = "_WITH_SUBDEPARTMENTS"


@dataclass(frozen=True)
class DepartmentCostsQuery:
    """The validated get_department_costs arguments."""

    period: str
    aggregation: str
    filters: Dict[str, List[str]] = field(default_factory=dict)
    page: Optional[int] = None
    size: Optional[int] = None

    @property
    def metric_type(self) -> str:
        return METRIC_TYPE_BY_AGGREGATION[self.aggregation]

    def request_params(self) -> Dict[str, Any]:
        """Query parameters beside the date window and the resolved team."""
        params: Dict[str, Any] = {"metricType": self.metric_type, **self.filters}
        # The endpoint defaults to coding_assistant alone, which is empty for
        # tenants whose spend is API-metered; ask for every source, the same
        # default get_user_costs sends (see DEFAULT_USER_COST_SOURCES).
        params.setdefault("costSources", list(DEFAULT_USER_COST_SOURCES))
        if self.page is not None:
            params["page"] = self.page
        if self.size is not None:
            params["size"] = self.size
        return params


@dataclass(frozen=True)
class DepartmentFigures:
    """Cost, requests and tokens for one scope of one group; None when the platform sent none."""

    cost: Optional[float] = None
    requests: Optional[float] = None
    tokens: Optional[float] = None


@dataclass(frozen=True)
class DepartmentGroup:
    name: str
    department_id: str
    parent_department_id: Optional[str]
    own: DepartmentFigures
    with_subdepartments: DepartmentFigures

    @property
    def is_unassigned(self) -> bool:
        return self.department_id == UNASSIGNED_DEPARTMENT_ID


@dataclass(frozen=True)
class DepartmentSetup:
    status: Optional[str]
    message: Optional[str]
    setup_url: Optional[str]


@dataclass(frozen=True)
class DepartmentCostsPage:
    groups: List[DepartmentGroup]
    setup: DepartmentSetup
    period_start: Optional[str]
    period_end: Optional[str]
    page_number: Optional[int]
    page_size: Optional[int]
    total_pages: Optional[int]
    total_elements: Optional[int]


def parse_department_costs(envelope: Mapping[str, Any]) -> DepartmentCostsPage:
    """Read the full analytics envelope (not the HAL-unwrapped item list)."""
    embedded = _mapping(envelope.get("_embedded"))
    items = embedded.get("items")
    period = _mapping(envelope.get("period"))
    page = _mapping(envelope.get("page"))
    return DepartmentCostsPage(
        groups=[_parse_group(item) for item in items or [] if isinstance(item, Mapping)],
        setup=_parse_setup(_mapping(envelope.get("departmentSetup"))),
        period_start=period.get("start"),
        period_end=period.get("end"),
        page_number=page.get("number"),
        page_size=page.get("size"),
        total_pages=page.get("totalPages"),
        total_elements=page.get("totalElements"),
    )


def _parse_group(item: Mapping[str, Any]) -> DepartmentGroup:
    by_type = {
        metric.get("metricType"): metric.get("metricResult")
        for metric in item.get("metrics") or []
        if isinstance(metric, Mapping)
    }
    return DepartmentGroup(
        name=str(item.get("groupName") or item.get("departmentId") or "Unnamed department"),
        department_id=str(item.get("departmentId") or ""),
        parent_department_id=item.get("parentDepartmentId"),
        own=_figures(by_type, suffix=""),
        with_subdepartments=_figures(by_type, suffix=_WITH_SUBDEPARTMENTS_SUFFIX),
    )


def _figures(by_type: Mapping[Any, Any], suffix: str) -> DepartmentFigures:
    values = {
        name: _number(by_type.get(metric_type + suffix))
        for name, metric_type in _OWN_METRIC_TYPES.items()
    }
    return DepartmentFigures(**values)


def _parse_setup(setup: Mapping[str, Any]) -> DepartmentSetup:
    return DepartmentSetup(
        status=setup.get("status"),
        message=setup.get("message"),
        setup_url=setup.get("setupUrl"),
    )


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
