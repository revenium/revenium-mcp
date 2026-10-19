"""State which records a page-sampled analytics answer covers (BACK-4630).

The subscription and customer analyses read one page of records and count
fields on it. Every count and rate they report is over that page, so the
answer carries the page it read and the platform total side by side, and a
rate is only ever the share of the covered records.
"""

from typing import Any, Dict, Iterable, Optional


def platform_total(page_info: Dict[str, Any]) -> Optional[int]:
    """The total the platform reported for a paged read, or None when it reported none."""
    total = page_info.get("totalElements")
    return total if isinstance(total, int) else None


def describe_sample(page: int, covered: int, total: Optional[int]) -> Dict[str, Any]:
    """Describe the page of records an analysis counted."""
    covers_all: Optional[bool]
    if total is None:
        covers_all = None
        note = (
            f"Counts and rates cover the {covered} records on page {page}; the platform "
            "reported no total, so whether they are all the records is unknown."
        )
    elif covered >= total:
        covers_all = True
        note = f"Counts and rates cover all {total} records."
    else:
        covers_all = False
        note = (
            f"Counts and rates cover only the {covered} records on page {page} "
            f"of {total} in total; read further pages (page, size up to 100) for the rest."
        )
    return {
        "page": page,
        "records_covered": covered,
        "total_records": total,
        "covers_all_records": covers_all,
        "note": note,
    }


def share_of_sample(count: int, covered: int) -> Optional[float]:
    """Percentage of the covered records, or None when nothing was covered."""
    if covered == 0:
        return None
    return round(count / covered * 100, 1)


def reference_id(record: Dict[str, Any], embedded_key: str, flat_key: str) -> Optional[str]:
    """Id of a related resource, from its embedded object or its flat id field."""
    embedded = record.get(embedded_key)
    if isinstance(embedded, dict) and embedded.get("id"):
        return str(embedded["id"])
    flat = record.get(flat_key)
    return str(flat) if flat else None


def distinct_ids_in_lists(records: Iterable[Dict[str, Any]], list_key: str) -> int:
    """Number of distinct ids across a list-of-ids field on each record."""
    return len({str(i) for r in records for i in (r.get(list_key) or []) if i})
