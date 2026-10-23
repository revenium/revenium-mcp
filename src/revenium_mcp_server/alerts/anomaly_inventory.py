"""Reading every alert definition a team has, page by page, and saying how much was read."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from loguru import logger

from ..common.platform_paging import PLATFORM_MAX_PAGE_SIZE

# The platform clamps a larger page to this size, so asking for more only hides the clamp.
ANOMALY_PAGE_SIZE = PLATFORM_MAX_PAGE_SIZE

# Bounds one account-wide action to MAX_ANOMALY_PAGES * ANOMALY_PAGE_SIZE alerts; past
# that it reports partial coverage.
MAX_ANOMALY_PAGES = 1000

# A stable order keeps rows from shifting between pages while the action reads them.
_STABLE_ORDER = "id,asc"


@dataclass(frozen=True)
class AnomalyInventory:
    anomalies: List[Dict[str, Any]]
    platform_total: Optional[int]
    reached_end: bool

    @property
    def complete(self) -> bool:
        if not self.reached_end:
            return False
        return self.platform_total is None or len(self.anomalies) >= self.platform_total

    @property
    def total(self) -> int:
        return self.platform_total if self.platform_total is not None else len(self.anomalies)

    def coverage_note(self, outcome: str) -> str:
        """A paragraph saying the action covered only part of the alerts, or "" when it covered all."""
        if self.complete:
            return ""
        covered = len(self.anomalies)
        total = str(self.platform_total) if self.platform_total is not None else "an unknown number of"
        return (
            f"\n\n**Partial:** read {covered} of {total} alerts before stopping, so {outcome} "
            "only for those. The rest were not reached; run the action again or act on them by id."
        )


def _page_metadata(response: Any) -> Dict[str, Any]:
    page_info = response.get("page") if isinstance(response, dict) else None
    return page_info if isinstance(page_info, dict) else {}


async def read_every_anomaly(client: Any) -> AnomalyInventory:
    """Every alert definition of the client's team, read page by page.

    A failure on the first page propagates. A failure on a later page ends the read
    early, and the inventory says how much it holds.
    """
    anomalies: List[Dict[str, Any]] = []
    seen_ids: Set[Any] = set()
    platform_total: Optional[int] = None
    for page in range(MAX_ANOMALY_PAGES):
        try:
            response = await client.get_anomalies(
                page=page, size=ANOMALY_PAGE_SIZE, sort=_STABLE_ORDER
            )
        except PermissionError:
            raise
        except Exception as error:
            if page == 0:
                raise
            logger.warning(f"Stopped reading alerts at page {page}: {error}")
            return AnomalyInventory(anomalies, platform_total, reached_end=False)

        rows = client._extract_embedded_data(response)
        page_info = _page_metadata(response)
        reported_total = page_info.get("totalElements")
        if isinstance(reported_total, int):
            platform_total = reported_total

        fresh = [row for row in rows if row.get("id") is None or row.get("id") not in seen_ids]
        seen_ids.update(row.get("id") for row in fresh)
        anomalies.extend(fresh)

        total_pages = page_info.get("totalPages")
        if not fresh:
            return AnomalyInventory(anomalies, platform_total, reached_end=True)
        if isinstance(total_pages, int):
            if page + 1 >= total_pages:
                return AnomalyInventory(anomalies, platform_total, reached_end=True)
        elif len(rows) < ANOMALY_PAGE_SIZE:
            return AnomalyInventory(anomalies, platform_total, reached_end=True)
    return AnomalyInventory(anomalies, platform_total, reached_end=False)
