"""Rows of the provider, model, customer, API key and agent cost reports.

A row is listed whenever the platform sent a numeric figure for it, so a
provider at exactly $0 and a credit at a negative cost are both listed; a
group with no numeric figure at all is not a row.
"""

from typing import Any, Dict, Iterable, List, Optional


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def metric_total(metrics: Any) -> Optional[float]:
    """Sum of a group's numeric ``metricResult`` values, or None when it has none."""
    if not isinstance(metrics, list):
        return None
    values = [
        metric["metricResult"]
        for metric in metrics
        if isinstance(metric, dict) and _is_number(metric.get("metricResult"))
    ]
    return float(sum(values)) if values else None


def bare_cost(item: Dict[str, Any], fields: Iterable[str]) -> Optional[float]:
    """The first non-zero numeric cost field of a bare row, 0 when every numeric one is 0, None when it has none."""
    values = [item[field] for field in fields if _is_number(item.get(field))]
    if not values:
        return None
    return float(next((value for value in values if value), 0))


def rank_with_shares(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort rows by cost, highest first, and give each positive row its share of the positive total.

    A row at or below zero carries no share: against a total that credits
    reduce, a paid row would read above 100 percent.
    """
    positive_total = sum(row["cost"] for row in rows if row["cost"] > 0)
    for row in rows:
        if row["cost"] > 0:
            row["percentage"] = row["cost"] / positive_total * 100
    rows.sort(key=lambda row: row["cost"], reverse=True)
    return rows
