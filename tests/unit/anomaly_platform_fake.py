"""An in-memory stand-in for the platform's AI anomaly endpoints that records every request body."""

import copy
import math
from typing import Any, Awaitable, Dict, Iterable, List, Optional, Tuple

from src.revenium_mcp_server.client import ReveniumClient
from src.revenium_mcp_server.common.error_handling import ToolError, format_structured_error

# The fields of the platform's AIAnomalyResource; anything else in a write is ignored.
PLATFORM_FIELDS = frozenset(
    {
        "id", "label", "name", "teamId", "alertType", "dataSource", "metricType",
        "operatorType", "threshold", "isPercentage", "notificationAddresses",
        "slackConfigurations", "description", "periodDuration", "enabled", "filters",
        "webhookConfigurations", "groupBy", "triggerAfterPersistsDuration",
    }
)

PLATFORM_MAX_PAGE_SIZE = 100

# AIAnomalyService.update: `monitor.dataSource = resource.dataSource ?: monitor.dataSource`.
# isPercentage and minSampleCount: a dev PUT sending both null kept the stored
# values (5 and true) on 2026-10-18.
KEPT_WHEN_NULL = frozenset({"dataSource", "isPercentage", "minSampleCount"})


def _name_matches(anomaly: Dict[str, Any], query: Optional[str]) -> bool:
    """AIAnomalyRepository.searchAIAlertRulesByTeamAndName: a case-blind name contains, blank matches all."""
    if not query or not query.strip():
        return True
    return query.lower() in str(anomaly.get("name", "")).lower()


class FakeAnomalyPlatform:
    team_id = "team-1"

    def __init__(
        self,
        anomalies: Iterable[Dict[str, Any]] = (),
        kept_on_update: Iterable[str] = (),
        omitted_from_update_answer: Iterable[str] = (),
        failing_list_page: Optional[int] = None,
    ) -> None:
        self.store: Dict[str, Dict[str, Any]] = {row["id"]: dict(row) for row in anomalies}
        self.kept_on_update = frozenset(kept_on_update)
        self.omitted_from_update_answer = frozenset(omitted_from_update_answer)
        self.read_ids: List[str] = []
        self.failing_list_page = failing_list_page
        self.created_bodies: List[Dict[str, Any]] = []
        self.updated_bodies: List[Tuple[str, Dict[str, Any]]] = []
        self.list_calls: List[Tuple[int, int]] = []
        self.list_filters: List[Dict[str, Any]] = []
        self.deleted_ids: List[str] = []

    @staticmethod
    def _stored(body: Dict[str, Any]) -> Dict[str, Any]:
        return {key: value for key, value in body.items() if key in PLATFORM_FIELDS}

    async def get_anomalies(self, page: int = 0, size: int = 20, **filters: Any) -> Dict[str, Any]:
        self.list_calls.append((page, size))
        self.list_filters.append(dict(filters))
        if page == self.failing_list_page:
            raise RuntimeError("platform timed out")
        size = min(size, PLATFORM_MAX_PAGE_SIZE)
        ordered = [
            self.store[key]
            for key in sorted(self.store)
            if _name_matches(self.store[key], filters.get("query"))
        ]
        rows = copy.deepcopy(ordered[page * size:(page + 1) * size])
        total = len(ordered)
        return {
            "_embedded": {"aIAnomalyResourceList": rows},
            "page": {
                "size": size,
                "number": page,
                "totalElements": total,
                "totalPages": math.ceil(total / size),
            },
        }

    async def get_anomaly_by_id(self, anomaly_id: str) -> Dict[str, Any]:
        self.read_ids.append(anomaly_id)
        return copy.deepcopy(self.store[anomaly_id])

    async def create_anomaly(self, body: Dict[str, Any]) -> Dict[str, Any]:
        self.created_bodies.append(copy.deepcopy(body))
        stored = self._stored(body)
        stored["id"] = f"new-{len(self.created_bodies)}"
        self.store[stored["id"]] = stored
        return copy.deepcopy(stored)

    async def update_anomaly(self, anomaly_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        self.updated_bodies.append((anomaly_id, copy.deepcopy(body)))
        current = self.store[anomaly_id]
        for key, value in self._stored(body).items():
            if key in self.kept_on_update or (key in KEPT_WHEN_NULL and value is None):
                continue
            current[key] = value
        return {
            key: copy.deepcopy(value)
            for key, value in current.items()
            if key not in self.omitted_from_update_answer
        }

    async def delete_anomaly(self, anomaly_id: str) -> Dict[str, Any]:
        self.deleted_ids.append(anomaly_id)
        del self.store[anomaly_id]
        return {}

    def _extract_embedded_data(self, response: Any) -> Any:
        return ReveniumClient._extract_embedded_data(self, response)  # type: ignore[arg-type]

    def _extract_pagination_info(self, response: Dict[str, Any]) -> Dict[str, Any]:
        return ReveniumClient._extract_pagination_info(self, response)  # type: ignore[arg-type]


def threshold_alert(anomaly_id: str, **overrides: Any) -> Dict[str, Any]:
    alert = {
        "id": anomaly_id,
        "name": f"Alert {anomaly_id}",
        "alertType": "THRESHOLD",
        "metricType": "TOTAL_COST",
        "operatorType": "GREATER_THAN",
        "threshold": 100.0,
        "isPercentage": False,
        "notificationAddresses": ["old@example.com"],
        "slackConfigurations": [],
        "periodDuration": "ONE_HOUR",
        "enabled": True,
        "filters": [],
    }
    alert.update(overrides)
    return alert


async def answer(call: Awaitable[Any]) -> Tuple[bool, str]:
    """What the caller sees: (error flag, text), whether a refusal is returned or raised."""
    try:
        result = await call
    except ToolError as exc:
        return True, format_structured_error(exc)
    return False, result[0].text
