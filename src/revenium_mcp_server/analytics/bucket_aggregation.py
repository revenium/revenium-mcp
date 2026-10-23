"""How a ranked cost report turns each entity's per-bucket figures into the one figure it prints.

The legacy over-time reports answer one value per entity per time bucket (half-days
over SEVEN_DAYS), already combined inside each bucket by the ``group`` the caller
asked for; the analytics API does the same per bucket for ``metricType``. Summing
those bucket values is right for TOTAL only: a MAXIMUM is the largest bucket
value, a MINIMUM the smallest, and a MEAN the mean of the bucket values, so it
does not grow with the number of buckets in the window.
"""

from statistics import fmean
from typing import Any, Callable, Dict, Iterable, List, Mapping, Sequence

from .ranked_rows import metric_total, rank_with_shares

METRIC_TYPE_BY_AGGREGATION: Mapping[str, str] = {
    "TOTAL": "sum",
    "MEAN": "avg",
    "MAXIMUM": "max",
    "MINIMUM": "min",
}

_COMBINE_BY_AGGREGATION: Mapping[str, Callable[[Sequence[float]], float]] = {
    "TOTAL": sum,
    "MEAN": fmean,
    "MAXIMUM": max,
    "MINIMUM": min,
}


def metric_type_for(aggregation: str) -> str:
    """The analytics API ``metricType`` that asks for ``aggregation``."""
    return METRIC_TYPE_BY_AGGREGATION[aggregation.upper()]


def combine_bucket_values(values: Sequence[float], aggregation: str) -> float:
    """One entity's figure for the window from the values of the buckets it has a value in."""
    return float(_COMBINE_BY_AGGREGATION[aggregation.upper()](values))


def _buckets_of(items: Iterable[Any]) -> Iterable[List[Dict[str, Any]]]:
    for item in items:
        if not isinstance(item, dict):
            continue
        if "groups" not in item:
            yield [item]
            continue
        groups = item.get("groups")
        if isinstance(groups, list):
            yield [group for group in groups if isinstance(group, dict)]


def _entity_values_in_bucket(
    groups: Sequence[Dict[str, Any]],
    default_name: str,
    name_of: Callable[[str], str],
) -> Dict[str, float]:
    values: Dict[str, float] = {}
    for group in groups:
        value = metric_total(group.get("metrics"))
        if value is None:
            continue
        name = name_of(group.get("groupName", default_name))
        values[name] = values.get(name, 0.0) + value
    return values


def rank_entities(
    items: Iterable[Any],
    aggregation: str,
    entity_key: str,
    default_name: str,
    name_of: Callable[[str], str] = lambda name: name,
) -> List[Dict[str, Any]]:
    """One row per entity, its bucket values combined by ``aggregation``, costliest first.

    ``items`` are time buckets holding ``groups``, or bare group entries that are
    each a bucket of their own. A group entry's value is the sum of its numeric
    metricResults; an entry with none counts as no value rather than zero. Group
    entries naming the same entity inside one bucket add up to that entity's
    single value for the bucket. An entity is listed whenever it has a value in
    any bucket, so a $0 provider and a credit are rows too, and shares follow
    ``rank_with_shares``: positive rows only, against the positive total.
    """
    values_by_entity: Dict[str, List[float]] = {}
    for groups in _buckets_of(items):
        for name, value in _entity_values_in_bucket(groups, default_name, name_of).items():
            values_by_entity.setdefault(name, []).append(value)

    return rank_with_shares(
        [
            {entity_key: name, "cost": combine_bucket_values(values, aggregation)}
            for name, values in values_by_entity.items()
        ]
    )
